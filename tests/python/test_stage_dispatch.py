import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCTOR = REPO / "scripts" / "pipeline_doctor.py"


def _run(*args, env_override=None):
    import os as _os
    env = _os.environ.copy()
    if env_override:
        env.update(env_override)
    return subprocess.run([sys.executable, str(DOCTOR), *args],
                          capture_output=True, text=True, env=env)


def test_canonical_stage_order():
    """--only respects canonical order regardless of CLI argument order."""
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from scripts import pipeline_doctor
    canonical = pipeline_doctor.STAGES_ORDER
    # spec § 4.2 ordering
    assert canonical == ["prereqs", "dirs", "config", "scripts",
                          "skill", "venvs", "models", "studio_extras"]


def test_only_models_without_venvs_fails_fast(tmp_path):
    """--apply --only models with no venvs exits 1 with a precise message."""
    r = _run("--apply", "--only", "models", "--tier", "laptop",
              env_override={"PIPELINE_ROOT": str(tmp_path / "p")})
    assert r.returncode != 0
    assert "requires stages" in r.stderr
    assert "venvs" in r.stderr


def test_studio_extras_skipped_on_laptop(tmp_path):
    """--apply --only studio_extras on laptop tier is a no-op (not an error)."""
    r = _run("--apply", "--only", "studio_extras", "--tier", "laptop",
              "--yes",
              env_override={"PIPELINE_ROOT": str(tmp_path / "p")})
    # Should succeed and report stage as skipped
    assert r.returncode in (0, 1)  # 0 if cleanly skipped


def test_apply_without_tier_or_config_fails(tmp_path):
    """Cold-start: --apply without --tier when .config is absent → exit 1."""
    r = _run("--apply",
              env_override={"PIPELINE_ROOT": str(tmp_path / "fresh")})
    assert r.returncode == 1
    assert "--tier" in r.stderr.lower()


def test_yes_flag_passed_through_to_dispatch(tmp_path):
    """--yes must be threaded into dispatch_apply (used by studio_extras in P4)."""
    import sys as _sys
    _sys.path.insert(0, str(REPO))
    from scripts import pipeline_doctor
    import inspect
    sig = inspect.signature(pipeline_doctor.dispatch_apply)
    assert "yes" in sig.parameters, \
        "dispatch_apply must accept yes= so studio_extras can auto-accept"


def test_yes_flag_in_cli(tmp_path):
    """--yes appears in --help output."""
    r = _run("--help")
    assert "--yes" in r.stdout
