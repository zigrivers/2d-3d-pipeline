"""Structure-check rules introduced by manifest schema v2."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_v1_manifest_skips_v2_rules(minimal_v2_manifest):
    """A manifest with schema_version: 1 must not trigger v2-only rules."""
    m = dict(minimal_v2_manifest)
    m["schema_version"] = 1
    # Remove v2 fields to simulate a real v1 manifest
    for k in ("tier_defaults", "prereqs", "mutable_embed_paths", "studio_extras"):
        m.pop(k, None)
    result = pipeline_doctor.check_structure(m)
    # No v2 rule should fire and add a critical finding
    assert all(c["status"] != "critical" or "v2:" not in c["name"]
               for c in result["structure"])


def test_v2_manifest_runs_v2_rules(minimal_v2_manifest):
    """A manifest with schema_version: 2 evaluates v2 rules."""
    result = pipeline_doctor.check_structure(minimal_v2_manifest)
    # Existence of v2-named checks proves the gate fired
    names = {c["name"] for c in result["structure"]}
    assert any(n.startswith("v2:") for n in names)


def test_tier_defaults_required_in_v2(minimal_v2_manifest):
    """v2 manifest without tier_defaults block fails structure check."""
    m = dict(minimal_v2_manifest)
    m.pop("tier_defaults")
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"
    assert any(c["name"] == "v2:tier-defaults" and c["status"] == "critical"
               for c in result["structure"])


def test_tier_defaults_must_have_laptop_and_studio(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["tier_defaults"] = {"laptop": {"include": []}}  # missing studio
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"
    assert any(c["name"] == "v2:tier-defaults" for c in result["structure"])


def test_tier_defaults_include_must_be_list_of_known_feature_sets(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["tier_defaults"] = {
        "laptop": {"include": ["does-not-exist"]},
        "studio": {"include": []},
    }
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_prereqs_required_in_v2(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m.pop("prereqs")
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"
    assert any(c["name"] == "v2:prereqs" for c in result["structure"])


def test_prereqs_must_be_list_of_objects(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["prereqs"] = "not-a-list"
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_prereq_entry_requires_id_kind_name(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["prereqs"] = [{"id": "python"}]  # missing kind, name
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_prereq_max_version_severity_must_be_warn_or_fail(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["prereqs"] = [{
        "id": "python", "kind": "binary", "name": "python3",
        "max_version": "3.12", "max_version_severity": "explode",
    }]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_well_formed_prereqs_pass(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["prereqs"] = [
        {"id": "python", "kind": "binary", "name": "python3",
         "min_version": "3.10", "max_version": "3.12",
         "max_version_severity": "warn"},
        {"id": "git", "kind": "binary", "name": "git"},
    ]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "ok"


def test_mutable_embed_paths_default_empty(minimal_v2_manifest):
    """Field is required in v2, default is empty list."""
    m = dict(minimal_v2_manifest)
    m.pop("mutable_embed_paths")
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"
    assert any(c["name"] == "v2:mutable-embed-paths" for c in result["structure"])


def test_mutable_embed_paths_must_be_list(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["mutable_embed_paths"] = "not-a-list"
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_mutable_embed_paths_entries_must_be_strings(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["mutable_embed_paths"] = [123]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_mutable_embed_paths_empty_list_passes(minimal_v2_manifest):
    """Empty list is the documented default and should pass."""
    result = pipeline_doctor.check_structure(minimal_v2_manifest)
    assert any(c["name"] == "v2:mutable-embed-paths" and c["status"] == "ok"
               for c in result["structure"])


def _model_with(**overrides):
    base = {
        "id": "u2net", "filename": "u2net.onnx",
        "feature_set": "tier1", "license_bucket": "commercial_safe",
        "size_mb": 170, "cache_dir": "~/3d-pipeline/models/rembg",
        "env_var": "U2NET_HOME", "download_url": "https://example/u2net.onnx",
        "sha256": "", "managed_by": "rembg", "notes": "",
        "requires_hf_auth": False, "hf_repo": None,
        "storage_layout": "literal", "warm_target": "u2net",
        "comfyui_kind": None,
    }
    base.update(overrides)
    return base


def test_model_storage_layout_must_be_literal_or_hf_snapshot(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["venvs"] = [{
        "name": "rembg-env", "path": "~/3d-pipeline/rembg-env", "required": True,
        "feature_set": "tier1", "size_gb": 1, "purpose": "test",
        "python_version": "3.12",
        "lockfile": "scripts/lockfiles/rembg-env.txt",
    }]
    m["models"] = [_model_with(storage_layout="other")]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_model_comfyui_kind_must_match_managed_by(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["feature_sets"]["comfyui"] = {"description": "t", "components": []}
    m["venvs"] = [{
        "name": "comfyui-env", "path": "~/3d-pipeline/comfyui-env", "required": False,
        "feature_set": "comfyui", "size_gb": 10, "purpose": "test",
        "python_version": "3.12",
        "lockfile": "scripts/lockfiles/comfyui-env.txt",
    }]
    # comfyui_kind set but managed_by != comfyui → invalid
    m["models"] = [_model_with(managed_by="rembg", comfyui_kind="checkpoint",
                                feature_set="tier1")]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_model_comfyui_kind_required_when_managed_by_comfyui(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["feature_sets"]["comfyui"] = {"description": "t", "components": []}
    m["venvs"] = [{
        "name": "comfyui-env", "path": "~/3d-pipeline/comfyui-env", "required": False,
        "feature_set": "comfyui", "size_gb": 10, "purpose": "test",
        "python_version": "3.12",
        "lockfile": "scripts/lockfiles/comfyui-env.txt",
    }]
    # managed_by=comfyui but kind is None → invalid
    m["models"] = [_model_with(managed_by="comfyui", comfyui_kind=None,
                                feature_set="comfyui")]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_requires_hf_auth_implies_hf_repo(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["venvs"] = [{
        "name": "rembg-env", "path": "~/3d-pipeline/rembg-env", "required": True,
        "feature_set": "tier1", "size_gb": 1, "purpose": "t",
        "python_version": "3.12",
        "lockfile": "scripts/lockfiles/rembg-env.txt",
    }]
    m["models"] = [_model_with(requires_hf_auth=True, hf_repo=None)]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_venv_python_version_required(minimal_v2_manifest, tmp_path):
    m = dict(minimal_v2_manifest)
    m["venvs"] = [{
        "name": "x", "path": "~/3d-pipeline/x", "required": True,
        "feature_set": "tier1", "size_gb": 1, "purpose": "t",
        # missing python_version
        "lockfile": "scripts/lockfiles/x.txt",
    }]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_venv_lockfile_must_exist(minimal_v2_manifest, monkeypatch, tmp_path):
    m = dict(minimal_v2_manifest)
    m["venvs"] = [{
        "name": "x", "path": "~/3d-pipeline/x", "required": True,
        "feature_set": "tier1", "size_gb": 1, "purpose": "t",
        "python_version": "3.12",
        "lockfile": "scripts/lockfiles/does-not-exist.txt",
    }]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_venv_lockfile_must_not_contain_pip_setuptools_wheel(
    minimal_v2_manifest, tmp_path, monkeypatch
):
    """Write the fake lockfile under tmp_path and monkeypatch REPO_ROOT so we
    don't pollute the real repo (which would trip the pre-commit hook on a
    test interrupt)."""
    fake_repo = tmp_path / "repo"
    (fake_repo / "scripts" / "lockfiles").mkdir(parents=True)
    lockfile = fake_repo / "scripts" / "lockfiles" / "test-bad.txt"
    lockfile.write_text("pip==24.0\nrequests==2.31.0\n")
    monkeypatch.setattr(pipeline_doctor, "REPO_ROOT", fake_repo)

    m = dict(minimal_v2_manifest)
    m["venvs"] = [{
        "name": "x", "path": "~/3d-pipeline/x", "required": True,
        "feature_set": "tier1", "size_gb": 1, "purpose": "t",
        "python_version": "3.12",
        "lockfile": "scripts/lockfiles/test-bad.txt",
    }]
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"
    assert any("pip" in c["details"].lower()
               for c in result["structure"] if c["status"] == "critical")
