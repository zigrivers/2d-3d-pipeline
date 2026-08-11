#!/usr/bin/env python3
"""Pipeline doctor + cache manager.

Diagnoses the pipeline install (disk / venvs / models / wrappers) and
optionally fixes what it can. Required before first asset work on a
fresh install — the v0.3+ quality scripts download models on demand,
and without this preflight a generation request can stall on a
multi-GB download with no indication anything is happening.

Usage:
    pipeline_doctor.py [--check {disk,models,venvs,wrappers,structure,all}]
                       (note: "structure" requires a repo checkout; excluded from "all")
                       [--include FEATURE,FEATURE,...]
                       [--warm-cache]
                       [--fix]
                       [--json]

Examples:
    pipeline_doctor.py --check all
    pipeline_doctor.py --warm-cache
    pipeline_doctor.py --warm-cache --include hunyuan3d-paint
    pipeline_doctor.py --check disk --json

Feature sets (from scripts/model_manifest.json):
    tier1            v0.3 quality features (rembg + CLIP)
    hunyuan3d-paint  Item 7 — Hunyuan3D-Paint texture painting
    comfyui          Item 11 — ComfyUI consistency mode
    multiview        Item 12 — multi-view reconstruction (TBD)

Default scope is tier1. --include adds opt-in feature sets.

Disk threshold is dynamic: the doctor sums declared sizes for any
component in scope that isn't already installed, plus a 5 GB working
margin. Hard floor: warns unconditionally if free space < 20 GB.

Pure stdlib (Python 3.10+). tqdm + requests are used opportunistically
for nicer progress bars during --warm-cache; absent, falls back to
urllib + no-op progress.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PIPELINE_ROOT = Path(os.environ.get("PIPELINE_ROOT", os.path.expanduser("~/3d-pipeline")))
SCRIPT_DIR = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_DIR.parent
MANIFEST_PATH = SCRIPT_DIR / "model_manifest.json"

# Ensure the repo root is on sys.path so `tools._embed_lib` is importable
# whether the script is run directly or imported as a module.
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

# Disk thresholds
HARD_FLOOR_GB = 20.0
WORKING_MARGIN_GB = 5.0


# ---------------- state file ----------------

def _state_path() -> Path:
    root = Path(os.environ.get("PIPELINE_ROOT", os.path.expanduser("~/3d-pipeline")))
    return root / ".install_state.json"


def load_state() -> dict:
    p = _state_path()
    if not p.exists():
        return {"stages": {}, "declined": {}}
    try:
        data = json.loads(p.read_text())
    except json.JSONDecodeError:
        return {"stages": {}, "declined": {}}
    data.setdefault("stages", {})
    data.setdefault("declined", {})
    return data


def _write_state(state: dict) -> None:
    p = _state_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True))
    tmp.replace(p)


def _utc_iso_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def record_stage_outcome(stage: str, *, ok: bool,
                          manifest_sha: str | None = None,
                          error: str | None = None) -> None:
    state = load_state()
    entry: dict = {"ok": ok, "ts": _utc_iso_now()}
    if manifest_sha is not None:
        entry["manifest_sha"] = manifest_sha
    if error is not None:
        entry["error"] = error
    state["stages"][stage] = entry
    _write_state(state)


def record_declined(resource_id: str, *, reason: str) -> None:
    state = load_state()
    state["declined"][resource_id] = {"ts": _utc_iso_now(), "reason": reason}
    _write_state(state)


def clear_declined() -> None:
    state = load_state()
    state["declined"] = {}
    _write_state(state)


# ---------------- lock ----------------

class LockHeldError(RuntimeError):
    pass


class NetworkFSError(RuntimeError):
    pass


_NETWORK_FS_TYPES = {"smbfs", "nfs", "afpfs", "fuse.sshfs", "webdav"}


def _is_network_fs(path: Path) -> bool:
    try:
        out = subprocess.run(["mount"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    p = path.resolve()
    best_match_type = ""
    best_match_len = -1
    for line in out.splitlines():
        try:
            _, mountpoint_part = line.split(" on ", 1)
            mountpoint, rest = mountpoint_part.split(" (", 1)
            fstype = rest.split(",", 1)[0].strip()
        except ValueError:
            continue
        if str(p).startswith(mountpoint) and len(mountpoint) > best_match_len:
            best_match_len = len(mountpoint)
            best_match_type = fstype
    return best_match_type in _NETWORK_FS_TYPES


@contextlib.contextmanager
def apply_lock():
    """Acquire an advisory flock; refuse on network filesystems."""
    root = Path(os.environ.get("PIPELINE_ROOT",
                                os.path.expanduser("~/3d-pipeline")))
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / ".install.lock"
    if _is_network_fs(lock_path):
        raise NetworkFSError(
            f"refusing to lock {lock_path} on network filesystem — "
            "advisory locks are unreliable. Move PIPELINE_ROOT to local disk.")
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LockHeldError(
                f"another --apply is already running (holding {lock_path})")
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


def _expand(path_str: str) -> Path:
    """Expand `~/3d-pipeline/...` through PIPELINE_ROOT (so tests can
    redirect), and fall back to `os.path.expanduser` for everything else."""
    pipeline_root = os.environ.get("PIPELINE_ROOT")
    if pipeline_root and path_str.startswith("~/3d-pipeline"):
        return Path(path_str.replace("~/3d-pipeline", pipeline_root, 1))
    return Path(os.path.expanduser(path_str))


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _free_space_gb(path: Path) -> float:
    """Free space (GB) on the volume containing `path`. Walks up to find it."""
    p = path
    while not p.exists() and p != p.parent:
        p = p.parent
    try:
        usage = shutil.disk_usage(p)
        return usage.free / (1024**3)
    except OSError:
        return 0.0


def _load_manifest() -> dict:
    if not MANIFEST_PATH.exists():
        print(f"ERROR: model_manifest.json not found at {MANIFEST_PATH}",
              file=sys.stderr)
        sys.exit(2)
    return json.loads(MANIFEST_PATH.read_text())


def _resolve_feature_sets(manifest: dict, include: list[str]) -> set[str]:
    sets = {"tier1"}
    sets.update(include)
    unknown = sets - set(manifest["feature_sets"].keys())
    if unknown:
        print(f"WARNING: unknown feature sets: {sorted(unknown)}",
              file=sys.stderr)
        sets -= unknown
    return sets


# ---------------- stage runners ----------------

STAGES_ORDER = ["prereqs", "dirs", "config", "scripts", "skill",
                "venvs", "models", "studio_extras"]

STAGE_PREREQUISITES: dict[str, list[str]] = {
    "prereqs": [],
    "dirs": ["prereqs"],
    "config": ["prereqs", "dirs"],
    "scripts": ["dirs"],
    "skill": ["dirs"],
    "venvs": ["prereqs", "dirs"],
    "models": ["venvs"],
    "studio_extras": ["dirs", "scripts"],
}

_REQUIRED_DIRS = ("workspace", "models", "benchmarks")


def _root() -> Path:
    return Path(os.environ.get("PIPELINE_ROOT",
                                os.path.expanduser("~/3d-pipeline")))


def apply_dirs(manifest: dict) -> dict:
    root = _root()
    root.mkdir(parents=True, exist_ok=True)
    created: list[str] = []
    for sub in _REQUIRED_DIRS:
        p = root / sub
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created.append(sub)
    return {"status": "ok", "created": created}


def check_dirs(manifest: dict) -> dict:
    root = _root()
    rows: list[dict] = []
    overall = "ok"
    for sub in _REQUIRED_DIRS:
        p = root / sub
        if p.is_dir():
            rows.append({"name": sub, "status": "ok"})
        else:
            rows.append({"name": sub, "status": "missing"})
            overall = "warning"
    return {"status": overall, "dirs": rows}


_CONFIG_TEMPLATE = "hardware_tier = {tier}\n"


def apply_config(manifest: dict, tier: str) -> dict:
    if tier not in ("laptop", "studio"):
        return {"status": "critical", "error": f"unknown tier {tier!r}"}
    cfg = _root() / ".config"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    desired = _CONFIG_TEMPLATE.format(tier=tier)
    if cfg.exists() and cfg.read_text() == desired:
        return {"status": "ok", "changed": False}
    tmp = cfg.with_suffix(cfg.suffix + ".tmp")
    tmp.write_text(desired)
    tmp.replace(cfg)
    return {"status": "ok", "changed": True}


def read_tier() -> str | None:
    cfg = _root() / ".config"
    if not cfg.exists():
        return None
    for line in cfg.read_text().splitlines():
        if "=" not in line:
            continue
        k, v = (s.strip() for s in line.split("=", 1))
        if k == "hardware_tier":
            return v if v in ("laptop", "studio") else None
    return None


def check_config(manifest: dict, tier: str) -> dict:
    cfg = _root() / ".config"
    if not cfg.exists():
        return {"status": "warning", "reason": "missing"}
    desired = _CONFIG_TEMPLATE.format(tier=tier)
    if cfg.read_text() == desired:
        return {"status": "ok", "tier": tier}
    return {"status": "warning", "reason": "drift", "tier": tier}


def _expand_workspace(rel: str) -> Path:
    expanded = rel.replace("~/3d-pipeline", str(_root()), 1)
    return Path(expanded).expanduser()


def _materialize_embed(src_rel: str, dest_rel: str) -> dict:
    src = REPO_ROOT / src_rel
    dest = _expand_workspace(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and _file_sha256(src) == _file_sha256(dest):
        return {"name": dest.name, "status": "ok", "changed": False}
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(src.read_bytes())
    if src_rel.endswith(".sh"):
        tmp.chmod(0o755)
    else:
        tmp.chmod(src.stat().st_mode & 0o777)
    tmp.replace(dest)
    return {"name": dest.name, "status": "ok", "changed": True}


def _drift_check_embed(src_rel: str, dest_rel: str,
                        mutable_set: set[str]) -> dict:
    src = REPO_ROOT / src_rel
    dest = _expand_workspace(dest_rel)
    if dest_rel in mutable_set:
        return {"name": dest.name, "status": "advisory",
                "reason": "marked mutable_embed_paths"}
    if not dest.exists():
        return {"name": dest.name, "status": "drift",
                "current": "missing", "expected": "present",
                "fix_command": "pipeline_doctor.py --apply --only scripts"}
    if _file_sha256(src) != _file_sha256(dest):
        return {"name": dest.name, "status": "drift",
                "current": "byte-mismatch", "expected": "sha256 match",
                "fix_command": "pipeline_doctor.py --apply --only scripts"}
    return {"name": dest.name, "status": "ok"}


def apply_scripts(manifest: dict, mutable_paths: list[str]) -> dict:
    from tools._embed_lib import EMBEDS_SCRIPTS  # type: ignore
    rows = [_materialize_embed(s, d) for s, d in EMBEDS_SCRIPTS.items()]
    return {"status": "ok", "scripts": rows}


def check_scripts(manifest: dict, mutable_paths: list[str]) -> dict:
    from tools._embed_lib import EMBEDS_SCRIPTS  # type: ignore
    mutable_set = set(mutable_paths or [])
    rows = [_drift_check_embed(s, d, mutable_set)
            for s, d in EMBEDS_SCRIPTS.items()]
    overall = "ok"
    if any(r["status"] == "drift" for r in rows):
        overall = "warning"
    return {"status": overall, "scripts": rows}


def _expand_skill(rel: str) -> Path:
    return Path(os.path.expanduser(rel))


def _materialize_skill_embed(src_rel: str, dest_rel: str) -> dict:
    src = REPO_ROOT / src_rel
    dest = _expand_skill(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and _file_sha256(src) == _file_sha256(dest):
        return {"name": dest.name, "status": "ok", "changed": False}
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(src.read_bytes())
    tmp.chmod(src.stat().st_mode & 0o777)
    tmp.replace(dest)
    return {"name": dest.name, "status": "ok", "changed": True}


def _drift_check_skill_embed(src_rel: str, dest_rel: str,
                              mutable_set: set[str]) -> dict:
    src = REPO_ROOT / src_rel
    dest = _expand_skill(dest_rel)
    if dest_rel in mutable_set:
        return {"name": dest.name, "status": "advisory",
                "reason": "marked mutable_embed_paths"}
    if not dest.exists():
        return {"name": dest.name, "status": "drift",
                "current": "missing", "expected": "present",
                "fix_command": "pipeline_doctor.py --apply --only skill"}
    if _file_sha256(src) != _file_sha256(dest):
        return {"name": dest.name, "status": "drift",
                "current": "byte-mismatch", "expected": "sha256 match",
                "fix_command": "pipeline_doctor.py --apply --only skill"}
    return {"name": dest.name, "status": "ok"}


def apply_skill(manifest: dict, mutable_paths: list[str]) -> dict:
    from tools._embed_lib import EMBEDS_SKILL  # type: ignore
    rows = [_materialize_skill_embed(s, d) for s, d in EMBEDS_SKILL.items()]
    return {"status": "ok", "skill": rows}


def check_skill(manifest: dict, mutable_paths: list[str]) -> dict:
    from tools._embed_lib import EMBEDS_SKILL  # type: ignore
    mutable_set = set(mutable_paths or [])
    rows = [_drift_check_skill_embed(s, d, mutable_set)
            for s, d in EMBEDS_SKILL.items()]
    overall = "ok"
    if any(r["status"] == "drift" for r in rows):
        overall = "warning"
    return {"status": overall, "skill": rows}


def _binary_version(name: str) -> str | None:
    if shutil.which(name) is None:
        return None
    try:
        r = subprocess.run([name, "--version"], capture_output=True,
                            text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    stdout = r.stdout if isinstance(r.stdout, str) else ""
    stderr = r.stderr if isinstance(r.stderr, str) else ""
    out = stdout + stderr
    m = re.search(r"\b(\d+\.\d+(?:\.\d+)?)\b", out)
    return m.group(1) if m else None


def _version_tuple(v: str) -> tuple[int, ...]:
    parts = []
    for x in v.split("."):
        try:
            parts.append(int(x))
        except ValueError:
            parts.append(0)
    return tuple(parts)


def check_prereqs(manifest: dict) -> dict:
    rows: list[dict] = []
    overall = "ok"
    for p in (manifest.get("prereqs") or []):
        name = p["name"]
        version = _binary_version(name)
        entry: dict = {"id": p["id"], "name": name, "version": version}
        if version is None:
            entry["status"] = "missing"
            entry["install_hint"] = p.get("install_hint", "")
            overall = "critical"
            rows.append(entry)
            continue
        vt = _version_tuple(version)
        if p.get("min_version"):
            if vt < _version_tuple(p["min_version"]):
                entry["status"] = "critical"
                entry["reason"] = f"version {version} < min {p['min_version']}"
                entry["install_hint"] = p.get("install_hint", "")
                overall = "critical"
                rows.append(entry)
                continue
        if p.get("max_version"):
            if vt > _version_tuple(p["max_version"]):
                sev = p.get("max_version_severity", "warn")
                entry["status"] = "warning" if sev == "warn" else "critical"
                entry["reason"] = f"version {version} > max {p['max_version']}"
                if sev != "warn":
                    overall = "critical"
                elif overall == "ok":
                    overall = "warning"
                rows.append(entry)
                continue
        entry["status"] = "ok"
        rows.append(entry)
    return {"status": overall, "prereqs": rows}


def apply_prereqs(manifest: dict) -> dict:
    return check_prereqs(manifest)


# ---------------- Python pin + venvs stage ----------------

def _patch_pin_matches(pin_path: Path, actual: str) -> bool:
    """Compare `actual` (e.g. '3.12.7') against the version recorded in
    `pin_path` (a `.python-version` file). If the file is missing, return
    True (no constraint). If the pin has no patch (e.g. '3.12'), compare
    only major.minor."""
    if not pin_path.exists():
        return True
    pinned = pin_path.read_text().strip()
    if not pinned:
        return True
    pinned_parts = pinned.split(".")
    actual_parts = actual.split(".")
    if len(pinned_parts) == 2:
        return pinned_parts == actual_parts[:2]
    return pinned == actual


def _venv_python(venv_path: Path) -> Path:
    return venv_path / "bin" / "python"


def _venv_pip(venv_path: Path) -> Path:
    return venv_path / "bin" / "pip"


def _active_python_version(major_minor: str) -> str | None:
    """Return the patch version of `python{major_minor}` on PATH, or None."""
    try:
        r = subprocess.run([f"python{major_minor}", "-c",
                             "import sys; print('.'.join(str(p) for p in sys.version_info[:3]))"],
                            capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    stdout = r.stdout if isinstance(r.stdout, str) else ""
    return stdout.strip() or None


_PIP_WHEEL_FAILURE_RE = re.compile(
    r"(?:Could not build wheels for|Failed building wheel for|"
    r"Building wheel for)\s+([A-Za-z0-9_.\-]+)")


def _parse_failing_package_from_stderr(stderr: str) -> str | None:
    """Extract the failing package name from pip stderr."""
    if not stderr:
        return None
    for line in stderr.splitlines():
        m = _PIP_WHEEL_FAILURE_RE.search(line)
        if m:
            return m.group(1)
    m = re.search(r"No matching distribution found for\s+([A-Za-z0-9_.\-]+)",
                   stderr)
    if m:
        return m.group(1)
    return None


def apply_venv(venv: dict) -> dict:
    """Create or update one venv against its lockfile."""
    name = venv["name"]
    path = _expand(venv["path"])
    pyver = venv["python_version"]
    lockfile = REPO_ROOT / venv["lockfile"]

    if not lockfile.exists() or not lockfile.read_text().strip():
        return {"status": "skipped", "name": name,
                "reason": "empty lockfile — not yet bootstrapped"}

    # Python patch pin check (spec §3.1 / AC3)
    active = _active_python_version(pyver)
    if active is None:
        return {"status": "critical", "name": name,
                "error": f"python{pyver} not on PATH; "
                          f"hint: `pyenv install {pyver}` or `brew install python@{pyver}`"}
    pin = REPO_ROOT / ".python-version"
    if not _patch_pin_matches(pin, active):
        pinned = pin.read_text().strip() if pin.exists() else "<missing>"
        return {"status": "critical", "name": name,
                "error": (f"active python{pyver} is {active}, but "
                           f".python-version pins {pinned}. "
                           f"Either run `pyenv install {pinned} && pyenv local {pinned}`, "
                           "or regenerate the lockfiles on this machine "
                           "(see scripts/lockfiles/README.md).")}

    # Create the venv if missing
    if not path.exists():
        r = subprocess.run([f"python{pyver}", "-m", "venv", str(path)],
                            capture_output=True, text=True)
        if r.returncode != 0:
            return {"status": "critical", "name": name,
                    "stage": "venv-create", "error": (r.stderr or "").strip()}

    pip = _venv_pip(path)

    # First install attempt
    r = subprocess.run([str(pip), "install", "-r", str(lockfile)],
                        capture_output=True, text=True)
    if r.returncode == 0:
        return {"status": "ok", "name": name, "retried": False}

    # Retry path: upgrade pip/setuptools/wheel, then re-install
    subprocess.run(
        [str(pip), "install", "--upgrade", "pip", "setuptools", "wheel"],
        capture_output=True, text=True)
    r2 = subprocess.run([str(pip), "install", "-r", str(lockfile)],
                         capture_output=True, text=True)
    if r2.returncode == 0:
        return {"status": "ok", "name": name, "retried": True}

    failing = _parse_failing_package_from_stderr(r2.stderr or r.stderr or "")
    return {
        "status": "critical", "name": name,
        "retried": True,
        "failing_package": failing,
        "error": ((r2.stderr or "").strip())[:500],
        "manual_fix": (f"Try: source {path}/bin/activate && "
                       f"pip install {failing or '<package>'} "
                       f"(then `pipeline_doctor.py --apply --only venvs`)"),
    }


def apply_venvs(manifest: dict, scope: set[str]) -> dict:
    rows: list[dict] = []
    overall = "ok"
    for v in (manifest.get("venvs") or []):
        if v.get("feature_set") not in scope:
            continue
        r = apply_venv(v)
        rows.append(r)
        if r["status"] == "critical":
            overall = "critical"
    return {"status": overall, "venvs": rows}


def _venv_pip_freeze(venv_path: Path) -> str:
    """Return `pip freeze --exclude pip --exclude setuptools --exclude wheel`
    for a venv. Returns empty string if the venv is missing or pip fails."""
    pip = _venv_pip(venv_path)
    if not pip.exists():
        return ""
    r = subprocess.run(
        [str(pip), "freeze",
         "--exclude", "pip", "--exclude", "setuptools", "--exclude", "wheel"],
        capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ""


def check_venv(venv: dict) -> dict:
    name = venv["name"]
    path = _expand(venv["path"])
    lockfile = REPO_ROOT / venv["lockfile"]

    if not lockfile.exists() or not lockfile.read_text().strip():
        return {"status": "skipped", "name": name,
                "reason": "empty lockfile"}
    if not path.exists():
        return {"status": "drift", "name": name, "reason": "missing",
                "fix_command": "pipeline_doctor.py --apply --only venvs"}

    expected = lockfile.read_text()
    actual = _venv_pip_freeze(path)
    if expected == actual:
        return {"status": "ok", "name": name}
    return {
        "status": "drift", "name": name, "reason": "lockfile-mismatch",
        "fix_command": "pipeline_doctor.py --apply --only venvs",
    }


def check_venvs_installed(manifest: dict, scope: set[str]) -> dict:
    rows: list[dict] = []
    overall = "ok"
    for v in (manifest.get("venvs") or []):
        if v.get("feature_set") not in scope:
            continue
        r = check_venv(v)
        rows.append(r)
        if r["status"] == "drift":
            overall = "warning"
    return {"status": overall, "venvs": rows}


# ---------------- HF preflight + downloads + models stage ----------------

def _hf_whoami() -> tuple[bool, str]:
    """Returns (logged_in, raw_output). Used as an early pre-check."""
    try:
        r = subprocess.run(["huggingface-cli", "whoami"],
                            capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired) as e:
        return (False, f"huggingface-cli unavailable: {e}")
    stdout = r.stdout if isinstance(r.stdout, str) else ""
    stderr = r.stderr if isinstance(r.stderr, str) else ""
    return (r.returncode == 0, (stdout or stderr).strip())


def hf_preflight(models: list[dict]) -> dict:
    """Per-repo access check for every model with requires_hf_auth=True."""
    gated = [m for m in models if m.get("requires_hf_auth")]
    if not gated:
        return {"status": "ok", "checked": 0, "details": "no gated models in scope"}

    # Step 1: whoami pre-check
    logged_in, whoami_out = _hf_whoami()
    if not logged_in:
        return {
            "status": "critical", "checked": 0,
            "details": (f"No HuggingFace token found ({whoami_out}). "
                         "Run `huggingface-cli login` and re-try."),
        }

    # Step 2: per-repo access check
    try:
        from huggingface_hub import HfApi
        from huggingface_hub.utils import (
            RepositoryNotFoundError, GatedRepoError, HfHubHTTPError,
        )
    except ImportError:
        return {"status": "critical", "checked": 0,
                "details": "huggingface_hub not installed — "
                           "pip install huggingface_hub[cli]"}

    api = HfApi()
    failures: list[dict] = []
    for m in gated:
        repo = m.get("hf_repo")
        if not repo:
            failures.append({
                "id": m["id"],
                "error": "requires_hf_auth=true but no hf_repo declared",
            })
            continue
        try:
            api.model_info(repo, timeout=10)
        except (RepositoryNotFoundError, GatedRepoError, HfHubHTTPError) as e:
            failures.append({
                "id": m["id"], "hf_repo": repo,
                "error": str(e)[:200],
                "remediation": (
                    f"huggingface-cli login  (and if needed, "
                    f"request access at https://huggingface.co/{repo})"),
            })
        except Exception as e:
            failures.append({
                "id": m["id"], "hf_repo": repo,
                "error": f"{type(e).__name__}: {str(e)[:200]}",
            })

    if failures:
        details_lines = [
            f"- {f['id']} ({f.get('hf_repo','?')}): {f['error']}"
            + (f"\n  fix: {f['remediation']}" if 'remediation' in f else "")
            for f in failures
        ]
        return {
            "status": "critical",
            "checked": len(gated),
            "failures": failures,
            "details": "HuggingFace access denied for:\n" + "\n".join(details_lines),
        }
    return {"status": "ok", "checked": len(gated),
            "details": f"{len(gated)} gated repo(s) accessible"}


def _download_with_range(url: str, dest: Path, expected_size: int | None = None,
                          chunk_size: int = 65536) -> dict:
    """Resumable streaming download via HTTP Range header."""
    try:
        import requests  # type: ignore
    except ImportError:
        return {"status": "critical",
                "error": "requests not installed; pip install requests"}

    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    offset = part.stat().st_size if part.exists() else 0
    headers = {"Range": f"bytes={offset}-"} if offset > 0 else {}

    result_extra: dict = {}
    try:
        with requests.get(url, headers=headers, stream=True, timeout=60) as r:
            if offset > 0 and r.status_code == 200:
                # Server ignored Range; restart from scratch
                part.unlink(missing_ok=True)
                offset = 0
                result_extra["restarted"] = True
            mode = "ab" if offset > 0 else "wb"
            with open(part, mode) as f:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if chunk:
                        f.write(chunk)
    except Exception as e:
        return {"status": "critical", "error": f"{type(e).__name__}: {str(e)[:200]}"}

    if expected_size is not None:
        actual = part.stat().st_size
        if abs(actual - expected_size) > expected_size * 0.05 + 1024:
            return {"status": "critical",
                    "error": f"size mismatch: got {actual}, expected {expected_size}"}

    part.replace(dest)
    return {"status": "ok", **result_extra}


def _download_hf(hf_repo: str, filename: str, cache_dir: Path) -> dict:
    """Download a file from a HuggingFace repo (resume is always-on)."""
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError:
        return {"status": "critical",
                "error": "huggingface_hub not installed"}
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = hf_hub_download(
            repo_id=hf_repo, filename=filename,
            cache_dir=str(cache_dir),
        )
        return {"status": "ok", "path": path}
    except Exception as e:
        return {"status": "critical",
                "error": f"{type(e).__name__}: {str(e)[:200]}"}


def _model_t3_check(model: dict) -> dict:
    """Presence + size ±5% check at the declared storage layout."""
    storage = model.get("storage_layout", "literal")
    expected_mb = model.get("size_mb", 0)
    if storage == "literal":
        target = _expand(model["cache_dir"]) / model["filename"]
        if not target.exists():
            return {"status": "drift", "reason": "missing",
                    "path": str(target)}
        actual_mb = target.stat().st_size / (1024 * 1024)
    elif storage == "hf_snapshot":
        cache = _expand(model["cache_dir"])
        try:
            from huggingface_hub import try_to_load_from_cache  # type: ignore
            cached = try_to_load_from_cache(
                repo_id=model["hf_repo"], filename=model["filename"],
                cache_dir=str(cache),
            )
        except ImportError:
            cached = None
        if not cached or not Path(cached).exists():
            return {"status": "drift", "reason": "missing",
                    "path": f"{cache}/<snapshot>/{model['filename']}"}
        actual_mb = Path(cached).stat().st_size / (1024 * 1024)
    else:
        return {"status": "critical",
                "reason": f"unknown storage_layout {storage!r}"}

    # 5% relative tolerance + 10 KB absolute floor (covers timestamp/header
    # variation in HF snapshot blobs without masking genuinely truncated files).
    tolerance = max(expected_mb * 0.05, 0.01)
    if abs(actual_mb - expected_mb) > tolerance:
        return {"status": "drift",
                "reason": f"size {actual_mb:.1f} MB outside ±5% of {expected_mb} MB",
                "actual_mb": round(actual_mb, 1)}
    return {"status": "ok", "actual_mb": round(actual_mb, 1)}


def apply_model(model: dict) -> dict:
    """Warm the model, then T3-verify the result."""
    from scripts import _install_lib  # type: ignore

    storage = model.get("storage_layout", "literal")
    url = model.get("download_url")

    if storage == "literal" and url:
        target = _expand(model["cache_dir"]) / model["filename"]
        expected = int(model.get("size_mb", 0)) * 1024 * 1024
        dl_result = _download_with_range(
            url, target, expected_size=expected if expected > 0 else None)
        if dl_result["status"] != "ok":
            return {"status": "critical", "id": model["id"],
                    "error": dl_result.get("error", "download failed"),
                    "verified": False}
        warm_detail = (f"direct-URL download" +
                        (" (restarted)" if dl_result.get("restarted") else ""))
    else:
        warm_status, warm_detail = _install_lib.warm(model)
        if warm_status == "failed":
            return {"status": "critical", "id": model["id"],
                    "error": warm_detail, "verified": False}

    t3 = _model_t3_check(model)
    if t3["status"] == "ok":
        return {"status": "ok", "id": model["id"],
                "warm_detail": warm_detail, "verified": True,
                "actual_mb": t3.get("actual_mb")}
    return {"status": "critical", "id": model["id"],
            "error": f"post-warm verify failed: {t3.get('reason','?')}",
            "verified": False}


def check_model(model: dict) -> dict:
    t3 = _model_t3_check(model)
    if t3["status"] == "ok":
        return {"status": "ok", "id": model["id"], **t3}
    return {"status": "drift", "id": model["id"],
            "fix_command": "pipeline_doctor.py --apply --only models",
            **t3}


def apply_models(manifest: dict, scope: set[str]) -> dict:
    in_scope = [m for m in (manifest.get("models") or [])
                if m.get("feature_set") in scope]

    # HF auth preflight FIRST — must abort before any download
    preflight = hf_preflight(in_scope)
    if preflight["status"] == "critical":
        return {"status": "critical",
                "preflight": preflight,
                "models": [],
                "error": preflight["details"]}

    rows: list[dict] = []
    overall = "ok"
    for m in in_scope:
        r = apply_model(m)
        rows.append(r)
        if r["status"] == "critical":
            overall = "critical"
    return {"status": overall, "preflight": preflight, "models": rows}


def check_models_installed(manifest: dict, scope: set[str]) -> dict:
    rows: list[dict] = []
    overall = "ok"
    for m in (manifest.get("models") or []):
        if m.get("feature_set") not in scope:
            continue
        r = check_model(m)
        rows.append(r)
        if r["status"] == "drift":
            overall = "warning"
    return {"status": overall, "models": rows}


def tier_includes(manifest: dict, tier: str) -> list[str]:
    td = (manifest.get("tier_defaults") or {}).get(tier) or {}
    return list(td.get("include") or [])


# ---------------- studio_extras stage ----------------

def _render_launchd_plist(plist_cfg: dict) -> str:
    """Pure template substitution. No side effects (no mkdir) so that the
    read-only check_studio_extras can call this for drift comparison without
    polluting the filesystem; apply_studio_extras creates the log_dir."""
    tmpl_rel = plist_cfg["template"]
    tmpl = (REPO_ROOT / tmpl_rel).read_text()
    workspace = _root() / "workspace"
    log_dir = _root() / "logs"
    return tmpl.format(
        label=plist_cfg["label"],
        python=str(_expand("~/3d-pipeline/pipeline-tools-env/bin/python")),
        worker_script=str(workspace / "queue_worker.py"),
        assets_root=str(workspace),
        script_dir=str(workspace),
        log_dir=str(log_dir),
    )


def apply_studio_extras(manifest: dict, tier: str, *,
                         accept_plist: bool,
                         declined_state: dict) -> dict:
    if tier != "studio":
        return {"status": "skipped", "reason": "laptop tier"}
    se = manifest.get("studio_extras") or {}
    workspace = _root() / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (_root() / "logs").mkdir(parents=True, exist_ok=True)

    created_dirs: list[str] = []
    for d in se.get("queue_dirs", []):
        p = workspace / d
        if not p.exists():
            p.mkdir(parents=True, exist_ok=True)
            created_dirs.append(d)

    plist_cfg = se.get("launchd_plist") or {}
    plist_optional = plist_cfg.get("optional", True)
    plist_status: dict = {"installed": False, "skipped": False}

    if "studio_extras.launchd_plist" in declined_state and plist_optional:
        plist_status["skipped"] = True
        plist_status["reason"] = "previously declined"
    elif accept_plist:
        dest = _expand_skill(plist_cfg["dest_path"])
        dest.parent.mkdir(parents=True, exist_ok=True)
        rendered = _render_launchd_plist(plist_cfg)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        tmp.write_text(rendered)
        tmp.replace(dest)
        plist_status["installed"] = True
        plist_status["path"] = str(dest)
    else:
        record_declined("studio_extras.launchd_plist",
                         reason="user declined during apply")
        plist_status["skipped"] = True
        plist_status["reason"] = "user declined"

    return {"status": "ok", "created_dirs": created_dirs,
            "launchd_plist": plist_status}


def check_studio_extras(manifest: dict, tier: str, declined_state: dict) -> dict:
    if tier != "studio":
        return {"status": "skipped", "reason": "laptop tier"}
    se = manifest.get("studio_extras") or {}
    workspace = _root() / "workspace"
    rows: list[dict] = []
    overall = "ok"
    for d in se.get("queue_dirs", []):
        p = workspace / d
        rows.append({"name": d,
                      "status": "ok" if p.is_dir() else "drift"})
        if not p.is_dir():
            overall = "warning"
    plist_cfg = se.get("launchd_plist") or {}
    dest = _expand_skill(plist_cfg["dest_path"])
    if "studio_extras.launchd_plist" in declined_state:
        rows.append({"name": "launchd_plist", "status": "advisory",
                      "reason": "previously declined"})
    elif dest.exists():
        expected = _render_launchd_plist(plist_cfg)
        actual = dest.read_text()
        if expected == actual:
            rows.append({"name": "launchd_plist", "status": "ok"})
        else:
            rows.append({"name": "launchd_plist", "status": "drift",
                          "fix_command":
                              "pipeline_doctor.py --apply --only studio_extras"})
            overall = "warning"
    else:
        rows.append({"name": "launchd_plist", "status": "advisory",
                      "reason": "not yet offered or declined"})
    return {"status": overall, "items": rows}


def is_heartbeat_alive(queue_dir: Path, *, machine: str,
                        max_age_seconds: int,
                        template: str = ".heartbeat-<machine>") -> bool:
    """True iff the heartbeat for `machine` is < max_age_seconds old.

    `template` is the manifest's `studio_extras.heartbeat_file`. Caller is
    responsible for reading the field from the manifest and passing it here;
    the default matches the v0.4 manifest value.
    """
    from scripts._heartbeat import _heartbeat_path
    hb = _heartbeat_path(queue_dir, machine, template)
    if not hb.exists():
        return False
    try:
        content = hb.read_text().strip()
        if content.endswith("Z"):
            content = content[:-1]
        ts = datetime.datetime.fromisoformat(content)
        if ts.tzinfo is None:
            # Treat naive timestamps as UTC (legacy)
            ts = ts.replace(tzinfo=datetime.timezone.utc)
    except (ValueError, OSError):
        return False
    now = datetime.datetime.now(datetime.timezone.utc)
    age = (now - ts).total_seconds()
    return age < max_age_seconds


def _resolve_only(arg: str) -> list[str]:
    if not arg:
        return list(STAGES_ORDER)
    requested = [s.strip() for s in arg.split(",") if s.strip()]
    unknown = [s for s in requested if s not in STAGES_ORDER]
    if unknown:
        print(f"error: unknown stage(s): {unknown}; "
              f"valid: {STAGES_ORDER}", file=sys.stderr)
        sys.exit(2)
    return [s for s in STAGES_ORDER if s in requested]


def _enforce_prereqs(stages: list[str]) -> None:
    requested = set(stages)
    for stage in stages:
        missing = [p for p in STAGE_PREREQUISITES[stage]
                    if p not in requested]
        if missing:
            print(f"error: stage {stage!r} requires stages {missing} — "
                  f"run with --only {','.join(missing + [stage])} first, "
                  "or drop --only.", file=sys.stderr)
            sys.exit(1)


def dispatch_apply(manifest: dict, stages: list[str],
                    tier: str, mutable_paths: list[str],
                    *, yes: bool = False) -> dict:
    report: dict = {"stages": {}}
    for stage in stages:
        if stage == "studio_extras" and tier != "studio":
            report["stages"][stage] = {"status": "skipped", "reason": "laptop tier"}
            continue
        if stage == "prereqs":
            r = apply_prereqs(manifest)
        elif stage == "dirs":
            r = apply_dirs(manifest)
        elif stage == "config":
            r = apply_config(manifest, tier=tier)
        elif stage == "scripts":
            r = apply_scripts(manifest, mutable_paths=mutable_paths)
        elif stage == "skill":
            r = apply_skill(manifest, mutable_paths=mutable_paths)
        elif stage == "venvs":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = apply_venvs(manifest, scope)
        elif stage == "models":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = apply_models(manifest, scope)
        elif stage == "studio_extras":
            declined = load_state().get("declined", {})
            # In automated mode, default to declining the plist offer; the
            # skill prompts the user and re-runs with --reconsider-optionals.
            accept_plist = False
            r = apply_studio_extras(manifest, tier=tier,
                                     accept_plist=accept_plist,
                                     declined_state=declined)
        else:
            r = {"status": "critical", "error": f"unknown stage {stage!r}"}
        report["stages"][stage] = r
        record_stage_outcome(stage, ok=(r["status"] in ("ok", "skipped")),
                              error=r.get("error"))
    return report


def dispatch_check_installed(manifest: dict, stages: list[str],
                              tier: str, mutable_paths: list[str]) -> dict:
    report: dict = {"stages": {}}
    for stage in stages:
        if stage == "studio_extras" and tier != "studio":
            report["stages"][stage] = {"status": "skipped"}
            continue
        if stage == "prereqs":
            r = check_prereqs(manifest)
        elif stage == "dirs":
            r = check_dirs(manifest)
        elif stage == "config":
            r = check_config(manifest, tier=tier)
        elif stage == "scripts":
            r = check_scripts(manifest, mutable_paths=mutable_paths)
        elif stage == "skill":
            r = check_skill(manifest, mutable_paths=mutable_paths)
        elif stage == "venvs":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = check_venvs_installed(manifest, scope)
        elif stage == "models":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = check_models_installed(manifest, scope)
        elif stage == "studio_extras":
            declined = load_state().get("declined", {})
            r = check_studio_extras(manifest, tier=tier, declined_state=declined)
        else:
            r = {"status": "skipped",
                  "reason": "unknown stage"}
        report["stages"][stage] = r
    return report


# ---------------- checks ----------------

def check_disk(manifest: dict, scope: set[str]) -> dict:
    free_gb = _free_space_gb(PIPELINE_ROOT)
    # Required = sum of (component sizes for items in scope that AREN'T installed)
    required_gb = 0.0
    missing_components: list[dict] = []
    for model in manifest["models"]:
        if model["feature_set"] not in scope:
            continue
        target = _expand(model["cache_dir"]) / model["filename"]
        if not target.exists():
            required_gb += model["size_mb"] / 1024
            missing_components.append({
                "id": model["id"],
                "filename": model["filename"],
                "size_mb": model["size_mb"],
            })
    for venv in manifest["venvs"]:
        if venv["feature_set"] not in scope:
            continue
        if not _expand(venv["path"]).exists():
            required_gb += venv["size_gb"]
            missing_components.append({
                "id": venv["name"],
                "size_gb": venv["size_gb"],
            })
    required_total = required_gb + WORKING_MARGIN_GB

    status = "ok"
    notes: list[str] = []
    if free_gb < HARD_FLOOR_GB:
        status = "warning"
        notes.append(f"free space {free_gb:.1f} GB is below the {HARD_FLOOR_GB:.0f} GB hard-floor warning level")
    if free_gb < required_total:
        status = "critical"
        notes.append(f"free space {free_gb:.1f} GB is below the {required_total:.1f} GB required for scope {sorted(scope)} (sum of uninstalled components + {WORKING_MARGIN_GB:.0f} GB margin)")
    return {
        "status": status,
        "free_gb": round(free_gb, 1),
        "required_gb": round(required_total, 1),
        "missing_components": missing_components,
        "notes": notes,
    }


def check_venvs(manifest: dict, scope: set[str]) -> dict:
    rows: list[dict] = []
    for venv in manifest["venvs"]:
        in_scope = venv["feature_set"] in scope
        exists = _expand(venv["path"]).exists()
        status = "ok" if exists else ("missing" if venv["required"] or in_scope else "missing_optional")
        rows.append({
            "name": venv["name"],
            "path": venv["path"],
            "feature_set": venv["feature_set"],
            "exists": exists,
            "in_scope": in_scope,
            "required": venv["required"],
            "status": status,
            "purpose": venv["purpose"],
        })
    overall = "ok"
    for r in rows:
        if r["in_scope"] and not r["exists"]:
            overall = "warning"
    return {"status": overall, "venvs": rows}


def check_models(manifest: dict, scope: set[str]) -> dict:
    rows: list[dict] = []
    for model in manifest["models"]:
        in_scope = model["feature_set"] in scope
        target = _expand(model["cache_dir"]) / model["filename"]
        exists = target.exists()
        size_mb = target.stat().st_size / (1024**2) if exists else None
        # Light "partial" heuristic: if the file is way smaller than declared, flag it
        is_partial = False
        if exists and size_mb is not None and size_mb < model["size_mb"] * 0.5:
            is_partial = True
        status = "ok"
        if not exists:
            status = "missing" if in_scope else "missing_optional"
        elif is_partial:
            status = "partial"
        rows.append({
            "id": model["id"],
            "filename": model["filename"],
            "feature_set": model["feature_set"],
            "in_scope": in_scope,
            "expected_size_mb": model["size_mb"],
            "actual_size_mb": round(size_mb, 1) if size_mb else None,
            "license_bucket": model["license_bucket"],
            "status": status,
        })
    overall = "ok"
    for r in rows:
        if r["in_scope"] and r["status"] in ("missing", "partial"):
            overall = "warning"
    return {"status": overall, "models": rows}


def check_wrappers(manifest: dict) -> dict:
    workspace = PIPELINE_ROOT / "workspace"
    rows: list[dict] = []
    overall = "ok"
    for wrapper in manifest["wrappers"]:
        path = workspace / wrapper
        if not path.exists():
            rows.append({"name": wrapper, "status": "missing", "exit_code": None})
            overall = "warning"
            continue
        try:
            r = subprocess.run(
                [str(path), "--help"],
                capture_output=True, text=True, timeout=10,
            )
            rows.append({
                "name": wrapper,
                "status": "ok" if r.returncode == 0 else "broken",
                "exit_code": r.returncode,
            })
            if r.returncode != 0:
                overall = "warning"
        except (subprocess.TimeoutExpired, OSError) as e:
            rows.append({"name": wrapper, "status": "broken", "error": str(e)})
            overall = "warning"
    return {"status": overall, "wrappers": rows}


# ---------------- structure check ----------------

def check_structure(manifest: dict) -> dict:
    """Validate catalog consistency without requiring any models/venvs installed.

    Each rule appends a check dict to the returned list and elevates
    status to 'critical' on any failure. Rules are added incrementally
    (Tasks 3-6); this skeleton runs clean on a valid manifest.
    """
    checks: list[dict] = []
    status = "ok"

    def _fail(name: str, details: str) -> None:
        nonlocal status
        status = "critical"
        checks.append({"name": name, "status": "critical", "details": details})

    def _ok(name: str, details: str = "") -> None:
        checks.append({"name": name, "status": "ok", "details": details})

    v2 = manifest.get("schema_version", 1) >= 2

    def _v2_ok(name: str, details: str = "") -> None:
        checks.append({"name": f"v2:{name}", "status": "ok", "details": details})

    if v2:
        _v2_ok("schema-version", "manifest is v2; v2 rules active")

    if v2:
        td = manifest.get("tier_defaults")
        known_sets = set((manifest.get("feature_sets") or {}).keys())
        if td is None:
            _fail("v2:tier-defaults", "missing 'tier_defaults' block")
        elif not isinstance(td, dict):
            _fail("v2:tier-defaults", f"'tier_defaults' must be an object, got {type(td).__name__}")
        else:
            missing_tiers = {"laptop", "studio"} - set(td.keys())
            if missing_tiers:
                _fail("v2:tier-defaults", f"missing tier(s): {sorted(missing_tiers)}")
            else:
                any_bad = False
                for tier, body in td.items():
                    inc = (body or {}).get("include", [])
                    if not isinstance(inc, list):
                        _fail("v2:tier-defaults", f"tier '{tier}' include must be a list")
                        any_bad = True
                        continue
                    unknown = [s for s in inc if s not in known_sets]
                    if unknown:
                        _fail("v2:tier-defaults",
                              f"tier '{tier}' includes unknown feature_set(s): {unknown}")
                        any_bad = True
                if not any_bad:
                    _ok("v2:tier-defaults", "both tiers declared with valid feature_sets")

    if v2:
        prereqs = manifest.get("prereqs")
        if prereqs is None:
            _fail("v2:prereqs", "missing 'prereqs' block")
        elif not isinstance(prereqs, list):
            _fail("v2:prereqs", f"'prereqs' must be a list, got {type(prereqs).__name__}")
        else:
            any_bad = False
            for i, p in enumerate(prereqs):
                if not isinstance(p, dict):
                    _fail("v2:prereqs", f"prereqs[{i}] must be an object")
                    any_bad = True
                    continue
                for required in ("id", "kind", "name"):
                    if required not in p:
                        _fail("v2:prereqs", f"prereqs[{i}] missing field '{required}'")
                        any_bad = True
                sev = p.get("max_version_severity", "warn")
                if sev not in ("warn", "fail"):
                    _fail("v2:prereqs",
                          f"prereqs[{i}] max_version_severity must be 'warn' or 'fail', got {sev!r}")
                    any_bad = True
            if not any_bad:
                _ok("v2:prereqs", f"{len(prereqs)} prereq(s) well-formed")

    if v2:
        mep = manifest.get("mutable_embed_paths")
        if mep is None:
            _fail("v2:mutable-embed-paths", "missing 'mutable_embed_paths' field (use [] for default)")
        elif not isinstance(mep, list):
            _fail("v2:mutable-embed-paths",
                  f"'mutable_embed_paths' must be a list, got {type(mep).__name__}")
        elif any(not isinstance(p, str) for p in mep):
            _fail("v2:mutable-embed-paths", "all entries must be strings (embed destination paths)")
        else:
            _ok("v2:mutable-embed-paths", f"{len(mep)} entry/entries")

    if v2:
        any_bad_model_v2 = False
        for m in (manifest.get("models") or []):
            mid = m.get("id", "<unknown>")
            layout = m.get("storage_layout")
            if layout not in ("literal", "hf_snapshot"):
                _fail("v2:model-storage-layout",
                      f"model '{mid}' storage_layout must be 'literal' or 'hf_snapshot', got {layout!r}")
                any_bad_model_v2 = True

            managed = m.get("managed_by")
            kind = m.get("comfyui_kind")
            if managed == "comfyui":
                if kind not in ("checkpoint", "ip_adapter", "controlnet", "lora", "clip_vision"):
                    _fail("v2:model-comfyui-kind",
                          f"model '{mid}' managed_by=comfyui requires comfyui_kind in "
                          "{checkpoint, ip_adapter, controlnet, lora, clip_vision}")
                    any_bad_model_v2 = True
            elif kind is not None:
                _fail("v2:model-comfyui-kind",
                      f"model '{mid}' has comfyui_kind={kind!r} but managed_by={managed!r}")
                any_bad_model_v2 = True

            if m.get("requires_hf_auth") and not m.get("hf_repo"):
                _fail("v2:model-hf-auth",
                      f"model '{mid}' requires_hf_auth=true but no hf_repo declared")
                any_bad_model_v2 = True

        if not any_bad_model_v2:
            _ok("v2:model-fields", "all models have valid v2 fields")

    if v2:
        any_bad_venv_v2 = False
        for v in (manifest.get("venvs") or []):
            name = v.get("name", "<unnamed>")
            pyver = v.get("python_version")
            if not isinstance(pyver, str) or not pyver:
                _fail("v2:venv-python-version",
                      f"venv '{name}' missing 'python_version' (e.g. '3.12')")
                any_bad_venv_v2 = True
            lockfile_rel = v.get("lockfile")
            if not isinstance(lockfile_rel, str) or not lockfile_rel:
                _fail("v2:venv-lockfile",
                      f"venv '{name}' missing 'lockfile' path")
                any_bad_venv_v2 = True
                continue
            lockfile_abs = (REPO_ROOT / lockfile_rel).resolve()
            if not lockfile_abs.is_relative_to(REPO_ROOT.resolve()):
                _fail("v2:venv-lockfile",
                      f"venv '{name}' lockfile {lockfile_rel!r} resolves outside repo")
                any_bad_venv_v2 = True
                continue
            if not lockfile_abs.exists():
                _fail("v2:venv-lockfile",
                      f"venv '{name}' lockfile not found at {lockfile_rel}")
                any_bad_venv_v2 = True
                continue
            content = lockfile_abs.read_text()
            forbidden = []
            for line in content.splitlines():
                pkg = line.split("==")[0].strip().lower()
                if pkg in ("pip", "setuptools", "wheel"):
                    forbidden.append(pkg)
            if forbidden:
                _fail("v2:venv-lockfile",
                      f"venv '{name}' lockfile contains {forbidden} — regenerate with "
                      "`pip freeze --exclude pip --exclude setuptools --exclude wheel`")
                any_bad_venv_v2 = True
        if not any_bad_venv_v2:
            _ok("v2:venv-fields", "all venvs have valid python_version + lockfile")

    if v2:
        se = manifest.get("studio_extras")
        if se is None:
            _fail("v2:studio-extras", "missing 'studio_extras' block")
        elif not isinstance(se, dict):
            _fail("v2:studio-extras",
                  f"'studio_extras' must be an object, got {type(se).__name__}")
        else:
            any_bad_se = False
            for required in ("queue_dirs", "launchd_plist", "heartbeat_file",
                             "heartbeat_max_age_seconds",
                             "heartbeat_write_timeout_seconds"):
                if required not in se:
                    _fail("v2:studio-extras", f"studio_extras missing '{required}'")
                    any_bad_se = True
            if not any_bad_se:
                max_age = se["heartbeat_max_age_seconds"]
                timeout = se["heartbeat_write_timeout_seconds"]
                if not (isinstance(max_age, int) and isinstance(timeout, int)):
                    _fail("v2:studio-extras",
                          "heartbeat_*_seconds must be integers")
                    any_bad_se = True
                elif timeout >= max_age / 3:
                    _fail("v2:studio-extras",
                          f"heartbeat_write_timeout_seconds ({timeout}) must be "
                          f"strictly less than heartbeat_max_age_seconds/3 "
                          f"({max_age/3}) to avoid races")
                    any_bad_se = True
                plist = se.get("launchd_plist") or {}
                label = plist.get("label", "")
                if not (label.count(".") >= 2 and
                        label.split(".")[0] in ("com", "org", "net", "io", "dev")):
                    _fail("v2:studio-extras",
                          f"launchd_plist.label {label!r} must be reverse-DNS "
                          "(e.g. com.kenallred.3dpipeline.queue-worker)")
                    any_bad_se = True
            if not any_bad_se:
                _ok("v2:studio-extras", "studio_extras well-formed")

    if v2:
        try:
            sys.path.insert(0, str(REPO_ROOT))
            from tools._embed_lib import EMBEDS_SCRIPTS, EMBEDS_SKILL, EMBEDS  # type: ignore
            scripts_dests = set(EMBEDS_SCRIPTS.values())
            skill_dests = set(EMBEDS_SKILL.values())
            all_dests = set(EMBEDS.values())
            if scripts_dests | skill_dests != all_dests:
                _fail("v2:embeds-partition",
                      "EMBEDS_SCRIPTS ∪ EMBEDS_SKILL does not cover all EMBEDS")
            elif scripts_dests & skill_dests:
                _fail("v2:embeds-partition",
                      f"EMBEDS_SCRIPTS and EMBEDS_SKILL overlap: {scripts_dests & skill_dests}")
            else:
                bad_scripts = [d for d in scripts_dests
                               if not d.startswith("~/3d-pipeline/workspace/")]
                bad_skill = [d for d in skill_dests
                             if not d.startswith("~/.claude/skills/asset-pipeline/")]
                if bad_scripts or bad_skill:
                    _fail("v2:embeds-partition",
                          f"prefix invariant violated — scripts: {bad_scripts}, skill: {bad_skill}")
                else:
                    _ok("v2:embeds-partition",
                        f"{len(EMBEDS_SCRIPTS)} scripts dest(s), {len(EMBEDS_SKILL)} skill dest(s)")
        except ImportError:
            _fail("v2:embeds-partition",
                  "could not import EMBEDS_SCRIPTS/EMBEDS_SKILL from tools._embed_lib")

    # Rule 1 — every EMBEDS source path exists on disk.
    try:
        sys.path.insert(0, str(REPO_ROOT))
        from tools._embed_lib import EMBEDS  # type: ignore
        bad_paths, missing = [], []
        for src in EMBEDS:
            resolved = (REPO_ROOT / src).resolve()
            if not resolved.is_relative_to(REPO_ROOT.resolve()):
                bad_paths.append(src)
            elif not resolved.exists():
                missing.append(src)
        for src in bad_paths:
            _fail("embeds-file-exists", f"{src} resolves outside repo root")
        for src in missing:
            _fail("embeds-file-exists", f"{src} missing from repo")
        if not bad_paths and not missing:
            _ok("embeds-file-exists", f"all {len(EMBEDS)} EMBEDS source files present")
    except ImportError:
        _fail("embeds-file-exists", "could not import tools._embed_lib — EMBEDS check skipped")

    # Rule 2 — every venv references a declared feature_set.
    known_sets = set((manifest.get("feature_sets") or {}).keys())
    all_venvs = manifest.get("venvs") or []
    any_bad = False
    for v in all_venvs:
        name = v.get("name", "<unnamed>")
        fs = v.get("feature_set")
        if fs is None:
            _fail("venv-feature-set", f"venv '{name}' is missing 'feature_set' field")
            any_bad = True
        elif not isinstance(fs, str):
            _fail("venv-feature-set", f"venv '{name}' 'feature_set' must be a string, got {type(fs).__name__}")
            any_bad = True
        elif fs not in known_sets:
            _fail("venv-feature-set", f"venv '{name}' references unknown feature_set '{fs}'")
            any_bad = True
    if not any_bad:
        _ok("venv-feature-set", f"all {len(all_venvs)} venvs reference valid feature_sets")

    # Rule 3 — every model references a valid feature_set AND has at least one venv for it.
    venv_sets = {v.get("feature_set") for v in (manifest.get("venvs") or []) if isinstance(v.get("feature_set"), str)}
    all_models = manifest.get("models") or []
    any_bad_model = False
    for m in all_models:
        mid = m.get("id", "<unknown>")
        fs = m.get("feature_set")
        if fs is None:
            _fail("model-feature-set", f"model '{mid}' is missing 'feature_set' field")
            any_bad_model = True
        elif not isinstance(fs, str):
            _fail("model-feature-set", f"model '{mid}' 'feature_set' must be a string, got {type(fs).__name__}")
            any_bad_model = True
        elif fs not in known_sets:
            _fail("model-feature-set", f"model '{mid}' references unknown feature_set '{fs}'")
            any_bad_model = True
        elif fs not in venv_sets:
            _fail("model-feature-set",
                  f"model '{mid}' has feature_set '{fs}' but no venv targets that set")
            any_bad_model = True
    if not any_bad_model:
        _ok("model-feature-set", f"all {len(all_models)} models reference valid feature_sets with a venv")

    # Rule 4 — wrappers list ↔ scripts/ parity.
    # Every entry in manifest.wrappers must exist in scripts/ and be executable.
    # Every scripts/*.sh must be in manifest.wrappers OR manifest.internal_scripts.
    declared_wrappers = manifest.get("wrappers") or []
    internal_scripts = manifest.get("internal_scripts") or []
    accounted_for = set(declared_wrappers) | set(internal_scripts)
    any_bad_wrapper = False
    scripts_root = SCRIPT_DIR.resolve()

    for wrapper in declared_wrappers:
        if "/" in wrapper or wrapper.startswith("."):
            _fail("wrapper-parity", f"wrappers entry '{wrapper}' must be a plain filename, not a path")
            any_bad_wrapper = True
            continue
        path = (SCRIPT_DIR / wrapper).resolve()
        if not path.is_relative_to(scripts_root):
            _fail("wrapper-parity", f"wrappers entry '{wrapper}' resolves outside scripts/")
            any_bad_wrapper = True
        elif not path.is_file():
            _fail("wrapper-parity", f"wrappers entry '{wrapper}' not found in scripts/")
            any_bad_wrapper = True
        elif not os.access(path, os.X_OK):
            _fail("wrapper-parity", f"wrappers entry '{wrapper}' is not executable")
            any_bad_wrapper = True

    all_sh = sorted(SCRIPT_DIR.glob("*.sh"))
    unregistered = [p.name for p in all_sh if p.name not in accounted_for]
    for name in unregistered:
        _fail("wrapper-parity", f"scripts/{name} not in wrappers or internal_scripts — register it")
        any_bad_wrapper = True

    if not any_bad_wrapper:
        _ok("wrapper-parity", f"all {len(all_sh)} .sh files accounted for; all {len(declared_wrappers)} wrappers executable")

    # Inner key "structure" follows the existing file pattern:
    # report["wrappers"]["wrappers"], report["venvs"]["venvs"], etc.
    return {"status": status, "structure": checks}


# ---------------- warm-cache ----------------

def _have_tqdm():
    try:
        import tqdm  # type: ignore # noqa
        return True
    except ImportError:
        return False


def _download(url: str, dest: Path) -> None:
    """Stream a URL to disk with stdlib. Used for models that ship a direct URL."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(url) as resp, open(tmp, "wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.rename(dest)


def warm_cache(manifest: dict, scope: set[str]) -> dict:
    """Pre-download every model in scope that has a direct download URL."""
    rows: list[dict] = []
    for model in manifest["models"]:
        if model["feature_set"] not in scope:
            continue
        target = _expand(model["cache_dir"]) / model["filename"]
        if target.exists():
            rows.append({"id": model["id"], "status": "already_present"})
            continue
        if not model["download_url"]:
            rows.append({
                "id": model["id"],
                "status": "skipped",
                "reason": f"no direct URL; managed by {model['managed_by']} on first use",
            })
            continue
        try:
            print(f"Downloading {model['id']} ({model['size_mb']} MB)…", file=sys.stderr)
            _download(model["download_url"], target)
            rows.append({"id": model["id"], "status": "downloaded"})
        except Exception as e:  # network errors, permissions, etc.
            rows.append({"id": model["id"], "status": "failed", "error": str(e)})
            if target.with_suffix(target.suffix + ".part").exists():
                target.with_suffix(target.suffix + ".part").unlink()
    return {"results": rows}


# ---------------- reporting ----------------

def _emoji(status: str) -> str:
    return {
        "ok": "✓",
        "warning": "⚠",
        "critical": "✗",
        "missing": "⚠",
        "missing_optional": "·",
        "partial": "⚠",
        "broken": "✗",
        "already_present": "·",
        "downloaded": "✓",
        "skipped": "·",
        "failed": "✗",
    }.get(status, "·")


def _print_human(report: dict, scope: set[str]) -> None:
    print("Pipeline status check")
    print("─" * 21)
    print()
    if "disk" in report:
        d = report["disk"]
        print(f"Disk:           {_emoji(d['status'])} {d['free_gb']} GB free")
        print(f"                Required for scope {sorted(scope)}: {d['required_gb']} GB")
        for note in d["notes"]:
            print(f"                ⚠ {note}")
        if d["missing_components"]:
            for c in d["missing_components"][:5]:
                size = c.get('size_mb') or (c.get('size_gb', 0) * 1024)
                print(f"                  - missing: {c['id']} (~{size:.0f} MB)")
    if "venvs" in report:
        v = report["venvs"]
        print(f"Venvs:          {_emoji(v['status'])}")
        for row in v["venvs"]:
            mark = _emoji(row["status"])
            scope_tag = "" if row["in_scope"] else "  (out of scope)"
            print(f"                {mark} {row['name']}{scope_tag} — {row['purpose']}")
    if "models" in report:
        m = report["models"]
        print(f"Models:         {_emoji(m['status'])}")
        for row in m["models"]:
            mark = _emoji(row["status"])
            tag = f"[{row['license_bucket']}]"
            scope_tag = "" if row["in_scope"] else "  (out of scope)"
            print(f"                {mark} {row['id']} {tag}{scope_tag}")
    if "wrappers" in report:
        w = report["wrappers"]
        print(f"Wrappers:       {_emoji(w['status'])}")
        for row in w["wrappers"]:
            print(f"                {_emoji(row['status'])} {row['name']}")
    if "structure" in report:
        s = report["structure"]
        print(f"Structure:      {_emoji(s['status'])}")
        for row in s["structure"]:
            detail = f": {row['details']}" if row['details'] else ""
            print(f"                {_emoji(row['status'])} {row['name']}{detail}")
    if "warm_cache" in report:
        c = report["warm_cache"]
        print("Warm-cache results:")
        for row in c["results"]:
            extra = ""
            if "reason" in row:
                extra = f" — {row['reason']}"
            elif "error" in row:
                extra = f" — {row['error']}"
            print(f"  {_emoji(row['status'])} {row['id']}: {row['status']}{extra}")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Pipeline doctor + cache manager")
    parser.add_argument("--check",
                        choices=["disk", "models", "venvs", "wrappers",
                                 "structure", "installed", "all"],
                        default="all",
                        help="Which subset to run (default: all). "
                             "'installed' walks every stage in read-only "
                             "drift-detection mode.")
    parser.add_argument("--include", default="",
                        help="Comma-separated opt-in feature sets (e.g. hunyuan3d-paint,comfyui)")
    parser.add_argument("--warm-cache", action="store_true",
                        help="Pre-download models with direct URLs for the chosen scope")
    parser.add_argument("--fix", action="store_true",
                        help="(deprecated) alias for --apply; will be removed in v0.5")
    parser.add_argument("--json", action="store_true",
                        help="Emit structured JSON; suppresses human-readable output")

    # v0.4 flags
    parser.add_argument("--apply", action="store_true",
                        help="Reconcile disk state to the catalog (opposite of --check)")
    parser.add_argument("--only", default="",
                        help="Comma-separated stage list to restrict --check or --apply to "
                             "(prereqs,dirs,config,scripts,skill,venvs,models,studio_extras)")
    parser.add_argument("--yes", action="store_true",
                        help="Skip interactive confirmation gates (for CI / re-runs)")
    parser.add_argument("--tier", choices=["laptop", "studio"], default=None,
                        help="Hardware tier; required when ~/3d-pipeline/.config is absent")
    parser.add_argument("--reconsider-optionals", action="store_true",
                        help="Clear declined-optional state for this run")
    args = parser.parse_args()

    if args.fix and not args.apply:
        print("warning: --fix is a deprecated alias for --apply; "
              "use --apply directly. Removal scheduled for v0.5.",
              file=sys.stderr)
        args.apply = True

    manifest = _load_manifest()
    include = [s.strip() for s in args.include.split(",") if s.strip()]
    scope = _resolve_feature_sets(manifest, include)

    report: dict = {"scope": sorted(scope)}

    # --apply path
    if args.apply:
        cfg_tier = read_tier()
        if args.tier is None and cfg_tier is None:
            print("error: --tier is required on a fresh machine "
                  "(no ~/3d-pipeline/.config found).",
                  file=sys.stderr)
            return 1
        chosen_tier = args.tier or cfg_tier
        stages = _resolve_only(args.only)
        _enforce_prereqs(stages)
        mutable_paths = manifest.get("mutable_embed_paths") or []
        if args.reconsider_optionals:
            clear_declined()
        try:
            with apply_lock():
                report["apply"] = dispatch_apply(manifest, stages,
                                                   tier=chosen_tier,
                                                   mutable_paths=mutable_paths,
                                                   yes=args.yes)
        except LockHeldError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        except NetworkFSError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1

    # --check installed path
    elif args.check == "installed":
        cfg_tier = read_tier()
        if args.tier is None and cfg_tier is None:
            print("error: --tier is required on a fresh machine.",
                  file=sys.stderr)
            return 1
        chosen_tier = args.tier or cfg_tier
        stages = _resolve_only(args.only)
        mutable_paths = manifest.get("mutable_embed_paths") or []
        report["check_installed"] = dispatch_check_installed(
            manifest, stages, tier=chosen_tier, mutable_paths=mutable_paths)

    # Existing --check paths (disk/models/venvs/wrappers/structure/all)
    else:
        if args.check in ("disk", "all"):
            report["disk"] = check_disk(manifest, scope)
        if args.check in ("venvs", "all"):
            report["venvs"] = check_venvs(manifest, scope)
        if args.check in ("models", "all"):
            report["models"] = check_models(manifest, scope)
        if args.check in ("wrappers", "all"):
            report["wrappers"] = check_wrappers(manifest)
        if args.check == "structure":
            # structure is not included in "all" — it requires a repo checkout
            # (tools._embed_lib) and is intended for CI, not user installs.
            report["structure"] = check_structure(manifest)
        if args.warm_cache:
            report["warm_cache"] = warm_cache(manifest, scope)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, scope)

    # Two exit-code regimes:
    # - Legacy --check: warning → 0, critical → 1.
    # - New --apply / --check installed: any drift/failure → 1, ok → 0.
    new_command = "apply" in report or "check_installed" in report
    if new_command:
        for k in ("apply", "check_installed"):
            if k not in report:
                continue
            for _, stage_r in report[k]["stages"].items():
                s = stage_r.get("status", "ok")
                if s in ("critical", "drift", "warning"):
                    return 1
        return 0

    worst = "ok"
    for k in ("disk", "venvs", "models", "wrappers", "structure"):
        if k not in report:
            continue
        s = report[k]["status"]
        if s == "critical":
            worst = "critical"
        elif s == "warning" and worst != "critical":
            worst = "warning"
    return {"ok": 0, "warning": 0, "critical": 1}[worst]


if __name__ == "__main__":
    sys.exit(main())
