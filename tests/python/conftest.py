"""Shared fixtures for the pipeline-doctor pytest suite."""
import json
import os
from pathlib import Path

import pytest


@pytest.fixture
def tmp_pipeline_root(tmp_path, monkeypatch):
    """Redirect PIPELINE_ROOT to a fresh tmpdir for the duration of a test."""
    root = tmp_path / "3d-pipeline"
    root.mkdir()
    monkeypatch.setenv("PIPELINE_ROOT", str(root))
    return root


@pytest.fixture
def minimal_v2_manifest():
    """Return a minimal but structurally-valid v2 manifest dict."""
    return {
        "schema_version": 2,
        "description": "test fixture",
        "feature_sets": {
            "tier1": {"description": "test", "components": []},
        },
        "venvs": [],
        "models": [],
        "wrappers": [
            "concept.sh", "generate.sh", "multiview.sh",
            "print.sh", "texture.sh", "benchmark.sh", "edit.sh",
        ],
        "internal_scripts": ["_pipeline_lib.sh", "migrate_assets.sh"],
        "tier_defaults": {"laptop": {"include": []}, "studio": {"include": []}},
        "prereqs": [],
        "mutable_embed_paths": [],
        "studio_extras": {
            "queue_dirs": [],
            "launchd_plist": {
                "label": "com.kenallred.3dpipeline.queue-worker",
                "template": "scripts/launchd/queue-worker.plist.tmpl",
                "dest_path": "~/Library/LaunchAgents/com.kenallred.3dpipeline.queue-worker.plist",
                "optional": True,
            },
            "heartbeat_file": "queue/.heartbeat-<machine>",
            "heartbeat_max_age_seconds": 90,
            "heartbeat_write_timeout_seconds": 25,
        },
    }


@pytest.fixture
def write_manifest(tmp_path):
    """Write a manifest dict to a tmp path and return the path."""
    def _write(manifest_dict, name="model_manifest.json"):
        p = tmp_path / name
        p.write_text(json.dumps(manifest_dict, indent=2))
        return p
    return _write
