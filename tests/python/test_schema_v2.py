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
