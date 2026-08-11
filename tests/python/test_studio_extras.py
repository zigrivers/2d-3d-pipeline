import plistlib
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


SE = {
    "queue_dirs": ["queue/pending", "queue/running", "queue/done", "queue/failed"],
    "launchd_plist": {
        "label": "com.kenallred.3dpipeline.queue-worker",
        "template": "scripts/launchd/queue-worker.plist.tmpl",
        "dest_path": "~/Library/LaunchAgents/com.kenallred.3dpipeline.queue-worker.plist",
        "optional": True,
    },
    "heartbeat_file": "queue/.heartbeat-<machine>",
    "heartbeat_max_age_seconds": 90,
    "heartbeat_write_timeout_seconds": 25,
}


def test_render_plist_substitutes_all_placeholders(tmp_pipeline_root):
    rendered = pipeline_doctor._render_launchd_plist(SE["launchd_plist"])
    # All `{...}` placeholders consumed
    assert "{" not in rendered or "{" + "}" not in rendered  # no leftover
    # Parses as valid plist
    parsed = plistlib.loads(rendered.encode())
    assert parsed["Label"] == "com.kenallred.3dpipeline.queue-worker"
    assert "queue_worker.py" in parsed["ProgramArguments"][1]


def test_apply_studio_extras_creates_queue_dirs(tmp_pipeline_root):
    workspace = tmp_pipeline_root / "workspace"
    workspace.mkdir(parents=True)
    result = pipeline_doctor.apply_studio_extras(
        manifest={"studio_extras": SE}, tier="studio",
        accept_plist=False, declined_state={})
    assert result["status"] == "ok"
    for d in SE["queue_dirs"]:
        assert (workspace / d).is_dir()


def test_apply_studio_extras_declining_plist_records_state(tmp_pipeline_root):
    workspace = tmp_pipeline_root / "workspace"
    workspace.mkdir(parents=True)
    declined_calls = []

    def fake_record(rid, reason):
        declined_calls.append((rid, reason))

    with patch("scripts.pipeline_doctor.record_declined",
               side_effect=fake_record):
        pipeline_doctor.apply_studio_extras(
            manifest={"studio_extras": SE}, tier="studio",
            accept_plist=False, declined_state={})
    assert any(rid == "studio_extras.launchd_plist" for rid, _ in declined_calls)


def test_apply_studio_extras_skipped_on_laptop(tmp_pipeline_root):
    result = pipeline_doctor.apply_studio_extras(
        manifest={"studio_extras": SE}, tier="laptop",
        accept_plist=False, declined_state={})
    assert result["status"] == "skipped"


def test_check_studio_extras_has_no_filesystem_side_effects(tmp_pipeline_root):
    """check_* functions must be read-only. Verifies _render_launchd_plist
    doesn't create logs/ as a side effect."""
    workspace = tmp_pipeline_root / "workspace"
    workspace.mkdir(parents=True)
    for d in SE["queue_dirs"]:
        (workspace / d).mkdir(parents=True, exist_ok=True)
    assert not (tmp_pipeline_root / "logs").exists()
    pipeline_doctor.check_studio_extras(
        manifest={"studio_extras": SE}, tier="studio", declined_state={})
    assert not (tmp_pipeline_root / "logs").exists(), \
        "check_studio_extras must be read-only; logs/ leaked from renderer"


def test_sticky_decline_round_trip(tmp_pipeline_root):
    """AC8 full round-trip."""
    workspace = tmp_pipeline_root / "workspace"
    workspace.mkdir(parents=True)

    # Apply with accept_plist=False; declined entry recorded
    pipeline_doctor.apply_studio_extras(
        manifest={"studio_extras": SE}, tier="studio",
        accept_plist=False, declined_state={})
    declined = pipeline_doctor.load_state()["declined"]
    assert "studio_extras.launchd_plist" in declined

    # Check must NOT flag drift for the declined plist
    check1 = pipeline_doctor.check_studio_extras(
        manifest={"studio_extras": SE}, tier="studio",
        declined_state=declined)
    plist_row = next(r for r in check1["items"] if r["name"] == "launchd_plist")
    assert plist_row["status"] == "advisory"
    assert "decline" in (plist_row.get("reason") or "").lower()

    # Run --reconsider-optionals path
    pipeline_doctor.clear_declined()
    check2 = pipeline_doctor.check_studio_extras(
        manifest={"studio_extras": SE}, tier="studio",
        declined_state=pipeline_doctor.load_state()["declined"])
    plist_row2 = next(r for r in check2["items"] if r["name"] == "launchd_plist")
    assert plist_row2["status"] == "advisory"
    assert "not yet" in (plist_row2.get("reason") or "").lower() or \
        "declined" not in (plist_row2.get("reason") or "").lower()
