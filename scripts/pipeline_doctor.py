#!/usr/bin/env python3
"""Pipeline doctor + cache manager.

Diagnoses the pipeline install (disk / venvs / models / wrappers) and
optionally fixes what it can. Required before first asset work on a
fresh install — the v0.3+ quality scripts download models on demand,
and without this preflight a generation request can stall on a
multi-GB download with no indication anything is happening.

Usage:
    pipeline_doctor.py [--check {disk,models,venvs,wrappers,structure,all}]
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
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

PIPELINE_ROOT = Path(os.environ.get("PIPELINE_ROOT", os.path.expanduser("~/3d-pipeline")))
SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_PATH = SCRIPT_DIR / "model_manifest.json"

# Disk thresholds
HARD_FLOOR_GB = 20.0
WORKING_MARGIN_GB = 5.0


def _expand(path_str: str) -> Path:
    return Path(os.path.expanduser(path_str))


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

    # Rules populated in Tasks 3-6; skeleton returns ok with no checks.
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
                        choices=["disk", "models", "venvs", "wrappers", "structure", "all"],
                        default="all",
                        help="Which subset to run (default: all)")
    parser.add_argument("--include", default="",
                        help="Comma-separated opt-in feature sets (e.g. hunyuan3d-paint,comfyui)")
    parser.add_argument("--warm-cache", action="store_true",
                        help="Pre-download models with direct URLs for the chosen scope")
    parser.add_argument("--fix", action="store_true",
                        help="(Future) attempt to install missing components. Currently reports only.")
    parser.add_argument("--json", action="store_true",
                        help="Emit structured JSON; suppresses human-readable output")
    args = parser.parse_args()

    manifest = _load_manifest()
    include = [s.strip() for s in args.include.split(",") if s.strip()]
    scope = _resolve_feature_sets(manifest, include)

    report: dict = {"scope": sorted(scope)}
    if args.check in ("disk", "all"):
        report["disk"] = check_disk(manifest, scope)
    if args.check in ("venvs", "all"):
        report["venvs"] = check_venvs(manifest, scope)
    if args.check in ("models", "all"):
        report["models"] = check_models(manifest, scope)
    if args.check in ("wrappers", "all"):
        report["wrappers"] = check_wrappers(manifest)
    if args.check in ("structure", "all"):
        report["structure"] = check_structure(manifest)
    if args.warm_cache:
        report["warm_cache"] = warm_cache(manifest, scope)

    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        _print_human(report, scope)
        if args.fix:
            print("--fix is a future feature; currently report-only.\n", file=sys.stderr)

    # Exit code reflects worst severity across checks
    worst = "ok"
    for k in ("disk", "venvs", "models", "wrappers", "structure"):
        if k in report:
            s = report[k]["status"]
            if s == "critical":
                worst = "critical"
            elif s == "warning" and worst != "critical":
                worst = "warning"
    return {"ok": 0, "warning": 0, "critical": 1}[worst]


if __name__ == "__main__":
    sys.exit(main())
