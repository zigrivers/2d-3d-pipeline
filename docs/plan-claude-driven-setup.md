# Claude-Code-driven pipeline setup — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `pipeline_doctor.py` from read-only auditor into a catalog-driven installer + drift detector, paired with a thin Claude Code skill that drives bootstrap + audit loops on a fresh or running Mac.

**Architecture:** `scripts/model_manifest.json` (schema v2) + `tools/_embed_lib.py` are the single source of truth. `pipeline_doctor.py` gains `--apply`, `--check installed`, and `--only STAGE` flags; it reconciles disk to catalog and reports drift in three tiers (T1 bytes-exact / T2 lockfile / T3 presence+size). A new `setup-skill/` deployed to `~/.claude/skills/asset-pipeline-setup/` handles the interactive bits (tier choice, HF auth, multi-select drift fixes, git-pull confirmation).

**Tech Stack:** Python 3.10–3.12 (stdlib + `huggingface_hub` + `requests`), bash wrappers, pytest for new unit tests, existing shell test scripts kept as-is.

**Reference:** `docs/spec-claude-driven-setup.md` (rev 3, commit `7017928`).

---

## Test infrastructure

New Python tests live under `tests/python/` and run via `pytest`. They run against the system Python with `pytest` installed via `pip install --user pytest pytest-mock`. The existing shell-based tests in `tools/test_*.sh` are unchanged.

Tests use a `tmp_path` fixture for filesystem isolation. The engine respects a `PIPELINE_ROOT` env var (already in `pipeline_doctor.py:51`), so tests redirect to a tmpdir without monkey-patching.

A new `make test` target runs both shell tests and pytest:

```makefile
test:
	./tools/test_meta_helper.sh
	./tools/test_update_manifest_meta.sh
	python3 -m pytest tests/python -v
```

---

## File structure

**New files:**
- `scripts/_install_lib.py` — host-tool recipes for smoke-warming (keyed by `managed_by` and `comfyui_kind`)
- `scripts/lockfiles/<name>.txt` — one per venv (`mflux-env.txt`, `pipeline-tools-env.txt`, `hunyuan3d-paint-env.txt`, `comfyui-env.txt`, `multiview-env.txt`)
- `scripts/launchd/queue-worker.plist.tmpl` — templated launchd plist for studio workers
- `setup-skill/SKILL.md` — driver skill content
- `setup-skill/scripts/audit_loop.py` — helper script for the multi-select drift UX
- `tests/python/conftest.py` — pytest fixtures (tmp pipeline root, fake manifest, mocked _install_lib recipes)
- `tests/python/test_schema_v2.py` — structure-check rules for v2 manifest
- `tests/python/test_apply_scripts.py` — scripts stage (T1 drift)
- `tests/python/test_apply_skill.py` — skill stage (T1 drift)
- `tests/python/test_apply_config.py` — config stage
- `tests/python/test_apply_dirs.py` — dirs stage
- `tests/python/test_apply_prereqs.py` — prereqs stage
- `tests/python/test_state_file.py` — `.install_state.json` shape + declined-optionals
- `tests/python/test_lock.py` — flock + network-FS refusal
- `tests/python/test_apply_venvs.py` — venvs stage (lockfile install + drift + retry)
- `tests/python/test_apply_models.py` — models stage (smoke + T3 + resumable downloads)
- `tests/python/test_hf_preflight.py` — per-repo `model_info` gate
- `tests/python/test_install_lib.py` — host-tool recipe dispatch
- `tests/python/test_studio_extras.py` — queue dirs + plist offer
- `tests/python/test_heartbeat.py` — mocked-time heartbeat write/read + watchdog
- `docs/setup-via-claude.md` — user-facing doc (single, not per-tier)

**Files modified:**
- `scripts/model_manifest.json` — bump to schema v2, add all new fields
- `scripts/pipeline_doctor.py` — add `--apply`, `--only`, `--yes`, `--tier`, `--check installed`, `--reconsider-optionals`; new stage runners; HF preflight; resumable downloads; state file management; flock
- `scripts/queue_worker.py` — heartbeat writes at each main-loop continue point
- `tools/_embed_lib.py` — add `_install_lib.py` to EMBEDS; add `EMBEDS_SCRIPTS` and `EMBEDS_SKILL` partition constants
- `skill/SKILL.md` — add "When to run setup" pointer section
- `CONVENTIONS.md` — document `setup-skill/` exception + v0.5 plural-skills tracked debt
- `docs/UPGRADES-laptop.md` — v0.4 delta entry
- `docs/UPGRADES-studio.md` — v0.4 delta entry (includes heartbeat)
- `docs/improvement-spec.md` — grep replace `--fix` → `--apply` at lines 986, 1013, 1099, 1129
- `Makefile` — add `test` target

---

## Phase 1 — Schema v2 + structure check (foundation)

No behaviour change yet. Lands the catalog fields and CI enforcement so subsequent phases can read them.

### Task 1.1: Bootstrap pytest infrastructure

**Files:**
- Create: `tests/python/conftest.py`
- Create: `tests/python/__init__.py` (empty)
- Modify: `Makefile`

- [ ] **Step 1: Create the pytest conftest**

Create `tests/python/conftest.py`:

```python
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
        "wrappers": [],
        "internal_scripts": [],
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
```

Create `tests/python/__init__.py` as an empty file.

- [ ] **Step 2: Add the test target to Makefile**

Read the current `Makefile` first, then add at the end:

```makefile
.PHONY: test
test:
	./tools/test_meta_helper.sh
	./tools/test_update_manifest_meta.sh
	python3 -m pytest tests/python -v
```

- [ ] **Step 3: Verify pytest is available**

Run: `python3 -m pytest --version`
Expected: prints pytest version. If "No module named pytest", run `python3 -m pip install --user pytest pytest-mock`.

- [ ] **Step 4: Verify the empty suite runs**

Run: `python3 -m pytest tests/python -v`
Expected: `no tests ran in X.XXs`, exit 0 (or exit 5 — "no tests collected" — which is fine here).

- [ ] **Step 5: Commit**

```bash
git add tests/python/conftest.py tests/python/__init__.py Makefile
git commit -m "P1.0: pytest infrastructure for v0.4 setup work"
```

---

### Task 1.2: Schema bump and structure-check version-gate

**Files:**
- Modify: `scripts/model_manifest.json` (bump `schema_version` from 1 to 2)
- Modify: `scripts/pipeline_doctor.py` (add v2-gating helper)
- Create: `tests/python/test_schema_v2.py`

- [ ] **Step 1: Write the failing test**

Create `tests/python/test_schema_v2.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v`
Expected: FAIL — `check_structure` has no v2-named rules yet.

- [ ] **Step 3: Bump schema_version in the manifest**

Edit `scripts/model_manifest.json`: change the top-level `"schema_version": 1` to `"schema_version": 2`. Do not add any other v2 fields yet — subsequent tasks add them and their structure rules together.

- [ ] **Step 4: Add the v2 gate helper + sentinel rule**

In `scripts/pipeline_doctor.py`, find `def check_structure(manifest: dict) -> dict:` (around line 228) and add this helper at the top of the function body, just after `status = "ok"`:

```python
    v2 = manifest.get("schema_version", 1) >= 2

    def _v2_ok(name: str, details: str = "") -> None:
        # Sentinel: ensures v2 mode is observable in the report
        checks.append({"name": f"v2:{name}", "status": "ok", "details": details})

    if v2:
        _v2_ok("schema-version", "manifest is v2; v2 rules active")
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v`
Expected: both tests PASS.

- [ ] **Step 6: Run the existing structure check against the bumped manifest**

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0; v1 rules pass; the sentinel `v2:schema-version` shows up.

- [ ] **Step 7: Commit**

```bash
git add scripts/model_manifest.json scripts/pipeline_doctor.py tests/python/test_schema_v2.py
git commit -m "P1.1: schema v2 bump + v2-gated structure-check scaffolding"
```

---

### Task 1.3: Add `tier_defaults` field + structure rule

**Files:**
- Modify: `scripts/model_manifest.json`
- Modify: `scripts/pipeline_doctor.py` (extend `check_structure`)
- Modify: `tests/python/test_schema_v2.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/python/test_schema_v2.py`:

```python
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k tier_defaults`
Expected: 3 FAILs.

- [ ] **Step 3: Add the structure rule**

In `scripts/pipeline_doctor.py`, inside `check_structure`, after the v2 sentinel block from task 1.2, add:

```python
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
```

- [ ] **Step 4: Add `tier_defaults` to the manifest**

In `scripts/model_manifest.json`, add a top-level key after `"description"`:

```json
  "tier_defaults": {
    "laptop": { "include": [] },
    "studio": { "include": ["hunyuan3d-paint"] }
  },
```

- [ ] **Step 5: Run the tests**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v`
Expected: all PASS.

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0; `v2:tier-defaults` reported `ok`.

- [ ] **Step 6: Commit**

```bash
git add scripts/model_manifest.json scripts/pipeline_doctor.py tests/python/test_schema_v2.py
git commit -m "P1.2: tier_defaults field + structure rule"
```

---

### Task 1.4: Add `prereqs` block + structure rule

**Files:**
- Modify: `scripts/model_manifest.json`
- Modify: `scripts/pipeline_doctor.py`
- Modify: `tests/python/test_schema_v2.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/python/test_schema_v2.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k prereq`
Expected: tests FAIL or ERROR.

- [ ] **Step 3: Add the structure rule**

In `check_structure`, after the tier_defaults rule:

```python
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
```

- [ ] **Step 4: Add prereqs to the manifest**

In `scripts/model_manifest.json`, add after `tier_defaults`:

```json
  "prereqs": [
    { "id": "python", "kind": "binary", "name": "python3",
      "min_version": "3.10", "max_version": "3.12",
      "max_version_severity": "warn",
      "install_hint": "brew install python@3.12" },
    { "id": "brew", "kind": "binary", "name": "brew",
      "install_hint": "see https://brew.sh" },
    { "id": "git", "kind": "binary", "name": "git" },
    { "id": "huggingface-cli", "kind": "binary", "name": "huggingface-cli",
      "install_hint": "pip install huggingface_hub[cli]" },
    { "id": "pip", "kind": "python_package", "name": "pip",
      "min_version": "23.1",
      "install_hint": "python3 -m pip install --upgrade pip" }
  ],
```

- [ ] **Step 5: Verify the tests + structure check**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k prereq`
Expected: all PASS.

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/model_manifest.json scripts/pipeline_doctor.py tests/python/test_schema_v2.py
git commit -m "P1.3: prereqs block + structure rule"
```

---

### Task 1.5: Add `mutable_embed_paths` field + structure rule

**Files:**
- Modify: `scripts/model_manifest.json`
- Modify: `scripts/pipeline_doctor.py`
- Modify: `tests/python/test_schema_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/python/test_schema_v2.py`:

```python
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
    # all v2 rules + mutable_embed_paths empty should pass
    assert any(c["name"] == "v2:mutable-embed-paths" and c["status"] == "ok"
               for c in result["structure"])
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k mutable_embed`
Expected: tests FAIL.

- [ ] **Step 3: Add the structure rule**

In `check_structure`, after the prereqs rule:

```python
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
```

- [ ] **Step 4: Add the field to the manifest**

In `scripts/model_manifest.json`, after `prereqs`:

```json
  "mutable_embed_paths": [],
```

- [ ] **Step 5: Run the tests + check**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k mutable_embed`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/model_manifest.json scripts/pipeline_doctor.py tests/python/test_schema_v2.py
git commit -m "P1.4: mutable_embed_paths field + structure rule"
```

---

### Task 1.6: Extend `models[]` with v2 fields + structure rules

**Files:**
- Modify: `scripts/model_manifest.json`
- Modify: `scripts/pipeline_doctor.py`
- Modify: `tests/python/test_schema_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/python/test_schema_v2.py`:

```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k "storage_layout or comfyui_kind or hf_auth"`
Expected: tests FAIL.

- [ ] **Step 3: Add the structure rule**

In `check_structure`, after the existing rule 3 (`model-feature-set`), add a new v2-gated block:

```python
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
                if kind not in ("checkpoint", "ip_adapter", "controlnet", "lora"):
                    _fail("v2:model-comfyui-kind",
                          f"model '{mid}' managed_by=comfyui requires comfyui_kind in "
                          "{checkpoint, ip_adapter, controlnet, lora}")
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
```

- [ ] **Step 4: Extend each model entry in the manifest**

In `scripts/model_manifest.json`, every entry in `"models": [...]` gains four new fields. For example, the `u2net` entry becomes:

```json
{
  "id": "u2net",
  "filename": "u2net.onnx",
  "feature_set": "tier1",
  "license_bucket": "commercial_safe",
  "size_mb": 170,
  "cache_dir": "~/3d-pipeline/models/rembg",
  "env_var": "U2NET_HOME",
  "download_url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
  "sha256": "",
  "managed_by": "rembg",
  "notes": "...",

  "requires_hf_auth": false,
  "hf_repo": null,
  "storage_layout": "literal",
  "warm_target": "u2net",
  "comfyui_kind": null
}
```

Concrete values for each model:

| id | requires_hf_auth | hf_repo | storage_layout | warm_target | comfyui_kind |
|----|------------------|---------|----------------|-------------|--------------|
| u2net | false | null | literal | u2net | null |
| clip-vit-l-14 | false | null | hf_snapshot | ViT-L-14 | null |
| hunyuan3d-paint | true | tencent/Hunyuan3D-2 | hf_snapshot | hunyuan3d-paint | null |
| sdxl-base | false | stabilityai/stable-diffusion-xl-base-1.0 | hf_snapshot | sd_xl_base_1.0 | checkpoint |
| ip-adapter-faceid-sdxl | false | h94/IP-Adapter-FaceID | hf_snapshot | ip-adapter-faceid_sdxl | ip_adapter |
| controlnet-openpose | false | xinsir/controlnet-openpose-sdxl-1.0 | hf_snapshot | controlnet-openpose-sdxl | controlnet |
| controlnet-canny | false | xinsir/controlnet-canny-sdxl-1.0 | hf_snapshot | controlnet-canny-sdxl | controlnet |

- [ ] **Step 5: Run tests + structure check**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v`
Expected: all PASS.

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0; `v2:model-fields` reports `ok`.

- [ ] **Step 6: Commit**

```bash
git add scripts/model_manifest.json scripts/pipeline_doctor.py tests/python/test_schema_v2.py
git commit -m "P1.5: model v2 fields (storage_layout, comfyui_kind, hf_auth, warm_target)"
```

---

### Task 1.7: Extend `venvs[]` with `python_version` + `lockfile` + structure rule

**Files:**
- Modify: `scripts/model_manifest.json`
- Modify: `scripts/pipeline_doctor.py`
- Modify: `tests/python/test_schema_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/python/test_schema_v2.py`:

```python
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
    # Place a fake lockfile in the repo under scripts/lockfiles/
    lockfile_dir = pipeline_doctor.REPO_ROOT / "scripts" / "lockfiles"
    lockfile_dir.mkdir(parents=True, exist_ok=True)
    lockfile = lockfile_dir / "test-bad.txt"
    lockfile.write_text("pip==24.0\nrequests==2.31.0\n")
    try:
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
    finally:
        lockfile.unlink()
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k venv`
Expected: tests FAIL.

- [ ] **Step 3: Add the structure rule**

In `check_structure`, after the existing rule 2 (`venv-feature-set`), add a new v2-gated block:

```python
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
```

- [ ] **Step 4: Create empty lockfile stubs**

Create `scripts/lockfiles/` with one empty file per venv. Use `touch`:

```bash
mkdir -p scripts/lockfiles
touch scripts/lockfiles/mflux-env.txt
touch scripts/lockfiles/pipeline-tools-env.txt
touch scripts/lockfiles/hunyuan3d-paint-env.txt
touch scripts/lockfiles/comfyui-env.txt
touch scripts/lockfiles/multiview-env.txt
```

(Empty content passes the "no pip/setuptools/wheel" rule. Tasks in Phase 3 populate them.)

- [ ] **Step 5: Update each venv in the manifest**

In `scripts/model_manifest.json`, every venv entry gains two new fields. For `mflux-env`:

```json
{
  "name": "mflux-env",
  "path": "~/3d-pipeline/mflux-env",
  "required": true,
  "feature_set": "tier1",
  "size_gb": 8,
  "purpose": "2D generation (Z-Image Turbo / FLUX schnell / FLUX dev)",
  "python_version": "3.12",
  "lockfile": "scripts/lockfiles/mflux-env.txt"
}
```

Repeat with appropriate `lockfile` path for each of the five venvs. All use `"python_version": "3.12"`.

- [ ] **Step 6: Run tests + structure check**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v`
Expected: all PASS.

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0; `v2:venv-fields` reports `ok`.

- [ ] **Step 7: Commit**

```bash
git add scripts/model_manifest.json scripts/pipeline_doctor.py scripts/lockfiles/ tests/python/test_schema_v2.py
git commit -m "P1.6: venv v2 fields (python_version, lockfile) + empty lockfile stubs"
```

---

### Task 1.8: Add `studio_extras` block + structure rule

**Files:**
- Modify: `scripts/model_manifest.json`
- Modify: `scripts/pipeline_doctor.py`
- Modify: `tests/python/test_schema_v2.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/python/test_schema_v2.py`:

```python
def test_studio_extras_required(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m.pop("studio_extras")
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_studio_extras_heartbeat_timeout_must_be_under_third_of_max_age(
    minimal_v2_manifest
):
    m = dict(minimal_v2_manifest)
    m["studio_extras"]["heartbeat_max_age_seconds"] = 30
    m["studio_extras"]["heartbeat_write_timeout_seconds"] = 25  # > 30/3
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"


def test_studio_extras_launchd_label_must_be_reverse_dns(minimal_v2_manifest):
    m = dict(minimal_v2_manifest)
    m["studio_extras"]["launchd_plist"]["label"] = "not-reverse-dns"
    result = pipeline_doctor.check_structure(m)
    assert result["status"] == "critical"
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v -k studio_extras`
Expected: tests FAIL.

- [ ] **Step 3: Add the structure rule**

In `check_structure`, after the venv v2 rule:

```python
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
                # very loose reverse-DNS check: at least two dots, starts with com./org./net./...
                if not (label.count(".") >= 2 and
                        label.split(".")[0] in ("com", "org", "net", "io", "dev")):
                    _fail("v2:studio-extras",
                          f"launchd_plist.label {label!r} must be reverse-DNS "
                          "(e.g. com.kenallred.3dpipeline.queue-worker)")
                    any_bad_se = True
            if not any_bad_se:
                _ok("v2:studio-extras", "studio_extras well-formed")
```

- [ ] **Step 4: Add to manifest**

In `scripts/model_manifest.json`, after `mutable_embed_paths`:

```json
  "studio_extras": {
    "queue_dirs": ["queue/pending", "queue/running", "queue/done", "queue/failed"],
    "launchd_plist": {
      "label": "com.kenallred.3dpipeline.queue-worker",
      "template": "scripts/launchd/queue-worker.plist.tmpl",
      "dest_path": "~/Library/LaunchAgents/com.kenallred.3dpipeline.queue-worker.plist",
      "optional": true
    },
    "heartbeat_file": "queue/.heartbeat-<machine>",
    "heartbeat_max_age_seconds": 90,
    "heartbeat_write_timeout_seconds": 25
  }
```

(25 < 90/3 = 30; passes the rule.)

- [ ] **Step 5: Run tests + check**

Run: `python3 -m pytest tests/python/test_schema_v2.py -v`
Expected: all PASS.

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add scripts/model_manifest.json scripts/pipeline_doctor.py tests/python/test_schema_v2.py
git commit -m "P1.7: studio_extras block + structure rule"
```

---

### Task 1.9: EMBEDS partition + `_install_lib.py` registration

**Files:**
- Modify: `tools/_embed_lib.py`
- Create: `scripts/_install_lib.py` (placeholder)
- Modify: `scripts/pipeline_doctor.py` (structure rule)
- Create: `tests/python/test_embeds_partition.py`

- [ ] **Step 1: Write failing test**

Create `tests/python/test_embeds_partition.py`:

```python
"""EMBEDS partition into scripts/ and skill/ destinations."""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from tools import _embed_lib  # noqa: E402


def test_embeds_scripts_and_embeds_skill_partition():
    assert hasattr(_embed_lib, "EMBEDS_SCRIPTS")
    assert hasattr(_embed_lib, "EMBEDS_SKILL")
    scripts_dests = set(_embed_lib.EMBEDS_SCRIPTS.values())
    skill_dests = set(_embed_lib.EMBEDS_SKILL.values())
    all_dests = set(_embed_lib.EMBEDS.values())
    # Every EMBED falls in exactly one partition
    assert scripts_dests | skill_dests == all_dests
    assert scripts_dests & skill_dests == set()
    # Prefix invariant
    for d in scripts_dests:
        assert d.startswith("~/3d-pipeline/workspace/")
    for d in skill_dests:
        assert d.startswith("~/.claude/skills/asset-pipeline/")


def test_install_lib_in_embeds():
    """_install_lib.py must ship via EMBEDS so HTML fallback works."""
    assert "scripts/_install_lib.py" in _embed_lib.EMBEDS
    assert _embed_lib.EMBEDS["scripts/_install_lib.py"] == \
        "~/3d-pipeline/workspace/_install_lib.py"
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_embeds_partition.py -v`
Expected: tests FAIL.

- [ ] **Step 3: Create placeholder `_install_lib.py`**

Create `scripts/_install_lib.py`:

```python
"""Host-tool recipes for smoke-warming lazy-managed models.

Dispatched by `pipeline_doctor.py` keyed by `managed_by` (and `comfyui_kind`
when `managed_by == "comfyui"`). Each recipe takes a model dict and returns
a (status, detail) tuple after attempting the host tool's first-use download.

Phase 3 fills in real recipes. Phase 1 ships this as an importable placeholder
so `pipeline_doctor.py` can declare the import without crashing.
"""
from __future__ import annotations


RECIPES: dict = {}


def warm(model: dict) -> tuple[str, str]:
    """Placeholder; populated in Phase 3."""
    return ("skipped", "no recipe registered yet")
```

- [ ] **Step 4: Add EMBEDS entry and partition constants**

Edit `tools/_embed_lib.py`. Add the `_install_lib.py` line into `EMBEDS` (preserve existing entries — insert after the `meta_helper.py` block, before the `pipeline_doctor.py` line so the import target is materialized first by an HTML-fallback paste):

```python
    "scripts/_install_lib.py":          "~/3d-pipeline/workspace/_install_lib.py",
```

After the closing brace of `EMBEDS`, append the partition constants:

```python
# Derived partitions for the v0.4 installer stages.
# Every EMBED destination lives under exactly one prefix.
EMBEDS_SCRIPTS: dict[str, str] = {
    src: dst for src, dst in EMBEDS.items()
    if dst.startswith("~/3d-pipeline/workspace/")
}
EMBEDS_SKILL: dict[str, str] = {
    src: dst for src, dst in EMBEDS.items()
    if dst.startswith("~/.claude/skills/asset-pipeline/")
}
assert set(EMBEDS_SCRIPTS) | set(EMBEDS_SKILL) == set(EMBEDS), \
    "EMBEDS partition incomplete — every entry must fall under a known prefix"
assert set(EMBEDS_SCRIPTS) & set(EMBEDS_SKILL) == set(), \
    "EMBEDS partition overlap — same source listed twice"
```

- [ ] **Step 5: Add a structure rule that enforces the same invariant**

In `scripts/pipeline_doctor.py`, inside `check_structure` after the studio_extras rule:

```python
    if v2:
        try:
            from tools._embed_lib import EMBEDS_SCRIPTS, EMBEDS_SKILL  # type: ignore
            scripts_set = set(EMBEDS_SCRIPTS.values())
            skill_set = set(EMBEDS_SKILL.values())
            from tools._embed_lib import EMBEDS  # type: ignore
            all_set = set(EMBEDS.values())
            if scripts_set | skill_set != all_set:
                _fail("v2:embeds-partition",
                      f"EMBEDS partition incomplete: "
                      f"{all_set - (scripts_set | skill_set)}")
            elif scripts_set & skill_set:
                _fail("v2:embeds-partition",
                      f"EMBEDS partition overlap: {scripts_set & skill_set}")
            else:
                _ok("v2:embeds-partition",
                    f"{len(EMBEDS_SCRIPTS)} scripts / {len(EMBEDS_SKILL)} skill embeds")
        except ImportError:
            _fail("v2:embeds-partition",
                  "could not import tools._embed_lib partitions")
```

- [ ] **Step 6: Run tests + check**

Run: `python3 -m pytest tests/python -v`
Expected: all PASS.

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0; `v2:embeds-partition` reports `ok`.

Run: `make verify`
Expected: existing embed verification still works.

- [ ] **Step 7: Regenerate the HTML to embed `_install_lib.py`**

Run: `make regenerate`
Expected: `docs/asset-pipeline-guide.html` and `-studio.html` updated with a new heredoc block for `_install_lib.py`.

- [ ] **Step 8: Commit**

```bash
git add tools/_embed_lib.py scripts/_install_lib.py scripts/pipeline_doctor.py tests/python/test_embeds_partition.py docs/asset-pipeline-guide.html docs/asset-pipeline-guide-studio.html
git commit -m "P1.8: EMBEDS partition (scripts/skill) + _install_lib.py placeholder"
```

---

### Phase 1 self-check

Run the full structure check and full test suite:

```
python3 scripts/pipeline_doctor.py --check structure --json | python3 -m json.tool | head -50
python3 -m pytest tests/python -v
make verify
```

Expected: structure check returns `"status": "ok"` with several `v2:*` checks all `ok`; pytest passes; embed verification passes.

Phase 1 is complete. The catalog is v2-shaped; CI validates it; no behaviour changed yet.

---

## Phase 2 — Engine local stages

Add `--apply`, `--only`, `--yes`, `--tier`, `--check installed`, `--reconsider-optionals`. Implement the network-free stages: `prereqs`, `dirs`, `config`, `scripts`, `skill`. Add the state file + flock. End of Phase 2: a fresh tmpdir can be bootstrapped to a working `~/3d-pipeline/workspace/` and `~/.claude/skills/asset-pipeline/` without any network calls.

### Task 2.1: Add new CLI flags (skeleton)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_cli_flags.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_cli_flags.py`:

```python
"""New CLI flags introduced by v0.4."""
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DOCTOR = REPO / "scripts" / "pipeline_doctor.py"


def _run(*args):
    return subprocess.run(
        [sys.executable, str(DOCTOR), *args],
        capture_output=True, text=True,
    )


def test_apply_flag_recognized():
    r = _run("--help")
    assert r.returncode == 0
    assert "--apply" in r.stdout


def test_only_flag_recognized():
    r = _run("--help")
    assert "--only" in r.stdout


def test_yes_flag_recognized():
    r = _run("--help")
    assert "--yes" in r.stdout


def test_tier_flag_recognized():
    r = _run("--help")
    assert "--tier" in r.stdout


def test_check_installed_recognized():
    r = _run("--help")
    assert "installed" in r.stdout


def test_reconsider_optionals_recognized():
    r = _run("--help")
    assert "--reconsider-optionals" in r.stdout


def test_fix_alias_warns(capsys):
    """--fix should still work but print a deprecation notice."""
    r = _run("--fix", "--check", "wrappers", "--json")
    # Either succeeds (current no-op) or routes to --apply; either way prints
    # a notice mentioning "deprecated" or "alias".
    assert "deprecat" in r.stderr.lower() or "alias" in r.stderr.lower()
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_cli_flags.py -v`
Expected: FAIL — flags not yet declared.

- [ ] **Step 3: Add the flags to `main()`**

In `scripts/pipeline_doctor.py`, edit the `argparse.ArgumentParser` block in `main()` (currently ends around line 479). Replace the existing `--check` choice tuple and add the new flags:

```python
    parser.add_argument("--check",
                        choices=["disk", "models", "venvs", "wrappers",
                                 "structure", "installed", "all"],
                        default="all",
                        help="Which subset to run (default: all). "
                             "'installed' walks every stage in read-only "
                             "drift-detection mode.")
    parser.add_argument("--include", default="",
                        help="Comma-separated opt-in feature sets")
    parser.add_argument("--warm-cache", action="store_true",
                        help="Pre-download models with direct URLs for the chosen scope")
    parser.add_argument("--fix", action="store_true",
                        help="(deprecated) alias for --apply; will be removed in v0.5")
    parser.add_argument("--json", action="store_true",
                        help="Emit structured JSON; suppresses human output")

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
```

After `args = parser.parse_args()`, add the `--fix` deprecation forward:

```python
    if args.fix and not args.apply:
        print("warning: --fix is a deprecated alias for --apply; "
              "use --apply directly. Removal scheduled for v0.5.",
              file=sys.stderr)
        args.apply = True
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_cli_flags.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_cli_flags.py
git commit -m "P2.1: new CLI flags (--apply, --only, --yes, --tier, --check installed)"
```

---

### Task 2.2: State file module

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_state_file.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_state_file.py`:

```python
"""`.install_state.json` shape and operations."""
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_load_missing_state_returns_empty_shape(tmp_pipeline_root):
    s = pipeline_doctor.load_state()
    assert s == {"stages": {}, "declined": {}}


def test_record_stage_ok_persists(tmp_pipeline_root):
    pipeline_doctor.record_stage_outcome("scripts", ok=True,
                                          manifest_sha="abc123")
    s = pipeline_doctor.load_state()
    assert s["stages"]["scripts"]["ok"] is True
    assert s["stages"]["scripts"]["manifest_sha"] == "abc123"
    assert "ts" in s["stages"]["scripts"]


def test_record_stage_failure_persists(tmp_pipeline_root):
    pipeline_doctor.record_stage_outcome("venvs", ok=False,
                                          error="torch wheel failed")
    s = pipeline_doctor.load_state()
    assert s["stages"]["venvs"]["ok"] is False
    assert s["stages"]["venvs"]["error"] == "torch wheel failed"


def test_record_declined_optional(tmp_pipeline_root):
    pipeline_doctor.record_declined("studio_extras.launchd_plist",
                                     reason="user declined")
    s = pipeline_doctor.load_state()
    assert "studio_extras.launchd_plist" in s["declined"]


def test_clear_declined(tmp_pipeline_root):
    pipeline_doctor.record_declined("x", reason="r")
    pipeline_doctor.clear_declined()
    s = pipeline_doctor.load_state()
    assert s["declined"] == {}
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_state_file.py -v`
Expected: FAIL — functions don't exist.

- [ ] **Step 3: Implement state-file functions**

In `scripts/pipeline_doctor.py`, after the `MANIFEST_PATH` constant (near line 54), add:

```python
STATE_PATH = PIPELINE_ROOT / ".install_state.json"


def _state_path() -> Path:
    # Re-read PIPELINE_ROOT each call so tests setting the env var work.
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


def record_stage_outcome(stage: str, *, ok: bool,
                          manifest_sha: str | None = None,
                          error: str | None = None) -> None:
    import datetime
    state = load_state()
    entry: dict = {"ok": ok, "ts": datetime.datetime.utcnow().isoformat() + "Z"}
    if manifest_sha is not None:
        entry["manifest_sha"] = manifest_sha
    if error is not None:
        entry["error"] = error
    state["stages"][stage] = entry
    _write_state(state)


def record_declined(resource_id: str, *, reason: str) -> None:
    import datetime
    state = load_state()
    state["declined"][resource_id] = {
        "ts": datetime.datetime.utcnow().isoformat() + "Z",
        "reason": reason,
    }
    _write_state(state)


def clear_declined() -> None:
    state = load_state()
    state["declined"] = {}
    _write_state(state)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_state_file.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_state_file.py
git commit -m "P2.2: install state file (stage outcomes + declined-optionals)"
```

---

### Task 2.3: Local-only flock

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_lock.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_lock.py`:

```python
"""Local-only advisory flock for --apply."""
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_lock_succeeds_on_local_fs(tmp_pipeline_root):
    with pipeline_doctor.apply_lock():
        pass  # entered + exited cleanly


def test_concurrent_lock_attempt_fails(tmp_pipeline_root):
    holder_ready = threading.Event()
    release = threading.Event()
    second_result = {"locked": None}

    def hold():
        with pipeline_doctor.apply_lock():
            holder_ready.set()
            release.wait(timeout=5)

    def attempt():
        holder_ready.wait(timeout=5)
        try:
            with pipeline_doctor.apply_lock():
                second_result["locked"] = "got-it"
        except pipeline_doctor.LockHeldError:
            second_result["locked"] = "rejected"

    t1 = threading.Thread(target=hold)
    t2 = threading.Thread(target=attempt)
    t1.start()
    t2.start()
    t2.join(timeout=5)
    release.set()
    t1.join(timeout=5)
    assert second_result["locked"] == "rejected"


def test_lock_refuses_network_fs(tmp_pipeline_root, monkeypatch):
    # Simulate the FS-type detection returning a network type
    monkeypatch.setattr(pipeline_doctor, "_is_network_fs", lambda p: True)
    try:
        with pipeline_doctor.apply_lock():
            assert False, "should have raised"
    except pipeline_doctor.NetworkFSError as e:
        assert "network" in str(e).lower()
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_lock.py -v`
Expected: FAIL — functions don't exist.

- [ ] **Step 3: Implement the lock**

In `scripts/pipeline_doctor.py`, after the state-file functions:

```python
import contextlib
import fcntl


class LockHeldError(RuntimeError):
    pass


class NetworkFSError(RuntimeError):
    pass


_NETWORK_FS_TYPES = {"smbfs", "nfs", "afpfs", "fuse.sshfs", "webdav"}


def _is_network_fs(path: Path) -> bool:
    """Return True if `path` is on a known network filesystem.

    macOS-specific: shells out to `mount` and matches the line whose
    mountpoint is a prefix of `path`.
    """
    try:
        out = subprocess.run(["mount"], capture_output=True, text=True,
                             timeout=5).stdout
    except (OSError, subprocess.TimeoutExpired):
        return False
    p = path.resolve()
    best_match_type = ""
    best_match_len = -1
    for line in out.splitlines():
        # Format: "//user@host/share on /mountpoint (smbfs, ...)"
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
    f = open(lock_path, "w")
    try:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LockHeldError(
                f"another --apply is already running (holding {lock_path})")
        yield
    finally:
        try:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_lock.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_lock.py
git commit -m "P2.3: local-only advisory flock with network-FS refusal"
```

---

### Task 2.4: `dirs` stage (apply + check)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_apply_dirs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_apply_dirs.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_apply_dirs_creates_tree(tmp_pipeline_root):
    result = pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    assert result["status"] == "ok"
    for sub in ("workspace", "models", "benchmarks"):
        assert (tmp_pipeline_root / sub).is_dir()


def test_apply_dirs_idempotent(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    result = pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    assert result["status"] == "ok"


def test_check_dirs_reports_missing(tmp_pipeline_root):
    # Don't apply — check should report missing
    result = pipeline_doctor.check_dirs(manifest={"schema_version": 2})
    assert result["status"] == "warning"
    missing = {d["name"] for d in result["dirs"] if d["status"] == "missing"}
    assert missing == {"workspace", "models", "benchmarks"}


def test_check_dirs_clean_after_apply(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={"schema_version": 2})
    result = pipeline_doctor.check_dirs(manifest={"schema_version": 2})
    assert result["status"] == "ok"
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_dirs.py -v`
Expected: FAIL — functions don't exist.

- [ ] **Step 3: Implement `dirs` stage**

In `scripts/pipeline_doctor.py`, after the lock helpers, add a clearly-labelled "stage runners" section:

```python
# ---------------- stage runners ----------------

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
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_apply_dirs.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_dirs.py
git commit -m "P2.4: dirs stage (apply + check)"
```

---

### Task 2.5: `config` stage (apply + check, with tier)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_apply_config.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_apply_config.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_apply_config_writes_tier(tmp_pipeline_root):
    result = pipeline_doctor.apply_config(manifest={}, tier="studio")
    assert result["status"] == "ok"
    content = (tmp_pipeline_root / ".config").read_text()
    assert "hardware_tier = studio" in content


def test_apply_config_idempotent(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    sha_before = pipeline_doctor._file_sha256(tmp_pipeline_root / ".config")
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    sha_after = pipeline_doctor._file_sha256(tmp_pipeline_root / ".config")
    assert sha_before == sha_after


def test_apply_config_overwrites_tier(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    pipeline_doctor.apply_config(manifest={}, tier="studio")
    assert "hardware_tier = studio" in (tmp_pipeline_root / ".config").read_text()


def test_read_tier_from_config(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="studio")
    assert pipeline_doctor.read_tier() == "studio"


def test_read_tier_returns_none_when_missing(tmp_pipeline_root):
    assert pipeline_doctor.read_tier() is None


def test_check_config_reports_drift(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    # Corrupt the config
    (tmp_pipeline_root / ".config").write_text("hardware_tier = laptop\nextra = junk\n")
    result = pipeline_doctor.check_config(manifest={}, tier="laptop")
    assert result["status"] == "warning"


def test_check_config_clean_after_apply(tmp_pipeline_root):
    pipeline_doctor.apply_config(manifest={}, tier="laptop")
    result = pipeline_doctor.check_config(manifest={}, tier="laptop")
    assert result["status"] == "ok"
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_config.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `config` stage and sha256 helper**

In `scripts/pipeline_doctor.py`, add a sha256 helper (near `_expand`):

```python
import hashlib


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
```

After `check_dirs`, add:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_apply_config.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_config.py
git commit -m "P2.5: config stage (apply + check + read_tier helper)"
```

---

### Task 2.6: `scripts` stage (uses EMBEDS_SCRIPTS, T1 bytes-exact)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_apply_scripts.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_apply_scripts.py`:

```python
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402
from tools import _embed_lib  # noqa: E402


def test_apply_scripts_materializes_all_embeds(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    result = pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    assert result["status"] == "ok"
    workspace = tmp_pipeline_root / "workspace"
    for src, dst in _embed_lib.EMBEDS_SCRIPTS.items():
        expected = Path(dst.replace("~/3d-pipeline", str(tmp_pipeline_root)))
        assert expected.exists(), f"missing {expected}"


def test_apply_scripts_preserves_executable_bit(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    # *.sh files must be executable
    for src, dst in _embed_lib.EMBEDS_SCRIPTS.items():
        if src.endswith(".sh"):
            expected = Path(dst.replace("~/3d-pipeline", str(tmp_pipeline_root)))
            assert os.access(expected, os.X_OK), f"{expected} not executable"


def test_apply_scripts_idempotent_no_mtime_change(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    # Snapshot mtimes
    workspace = tmp_pipeline_root / "workspace"
    snapshots = {p: p.stat().st_mtime_ns for p in workspace.iterdir() if p.is_file()}
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    for p, ts in snapshots.items():
        assert p.stat().st_mtime_ns == ts, f"{p} mtime changed on re-apply"


def test_check_scripts_reports_drift(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    # Mutate one file
    target = tmp_pipeline_root / "workspace" / "concept.sh"
    target.write_text(target.read_text() + "\n# drift\n")
    result = pipeline_doctor.check_scripts(manifest={}, mutable_paths=[])
    assert result["status"] == "warning"
    drifted = [s for s in result["scripts"] if s["status"] == "drift"]
    assert any(s["name"] == "concept.sh" for s in drifted)
    assert any("--apply --only scripts" in s.get("fix_command", "")
               for s in drifted)


def test_check_scripts_skips_mutable_paths(tmp_pipeline_root):
    pipeline_doctor.apply_dirs(manifest={})
    pipeline_doctor.apply_scripts(manifest={}, mutable_paths=[])
    target = tmp_pipeline_root / "workspace" / "concept.sh"
    target.write_text("drift")
    # Pass the mutated path as mutable — drift should be ignored (T0)
    result = pipeline_doctor.check_scripts(
        manifest={},
        mutable_paths=["~/3d-pipeline/workspace/concept.sh"],
    )
    drifted = [s for s in result["scripts"] if s["status"] == "drift"]
    assert not any(s["name"] == "concept.sh" for s in drifted)
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_scripts.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `scripts` stage**

In `scripts/pipeline_doctor.py`, after `check_config`:

```python
def _expand_workspace(rel: str) -> Path:
    """Translate an EMBEDS destination (`~/3d-pipeline/...`) to a real path
    rooted at PIPELINE_ROOT."""
    expanded = rel.replace("~/3d-pipeline", str(_root()), 1)
    return Path(expanded).expanduser()


def _materialize_embed(src_rel: str, dest_rel: str) -> dict:
    """Copy a canonical file from REPO_ROOT/src_rel to the deployed destination,
    atomic-rename, preserving executable bit on .sh files."""
    src = REPO_ROOT / src_rel
    dest = _expand_workspace(dest_rel)
    dest.parent.mkdir(parents=True, exist_ok=True)
    # No-op if already in sync
    if dest.exists() and _file_sha256(src) == _file_sha256(dest):
        return {"name": dest.name, "status": "ok", "changed": False}
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    tmp.write_bytes(src.read_bytes())
    if src_rel.endswith(".sh"):
        tmp.chmod(0o755)
    else:
        # Preserve source mode (esp. executable bit on python helpers)
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
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_apply_scripts.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_scripts.py
git commit -m "P2.6: scripts stage (apply + T1 drift detection)"
```

---

### Task 2.7: `skill` stage (uses EMBEDS_SKILL)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_apply_skill.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_apply_skill.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402
from tools import _embed_lib  # noqa: E402


def test_apply_skill_materializes_to_claude_dir(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    result = pipeline_doctor.apply_skill(manifest={}, mutable_paths=[])
    assert result["status"] == "ok"
    skill_root = fake_home / ".claude" / "skills" / "asset-pipeline"
    assert (skill_root / "SKILL.md").exists()


def test_check_skill_drift_after_mutation(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))
    pipeline_doctor.apply_skill(manifest={}, mutable_paths=[])
    target = fake_home / ".claude" / "skills" / "asset-pipeline" / "SKILL.md"
    target.write_text(target.read_text() + "\ndrift\n")
    result = pipeline_doctor.check_skill(manifest={}, mutable_paths=[])
    assert result["status"] == "warning"
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_skill.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `skill` stage**

The destination paths in `EMBEDS_SKILL` start with `~/.claude/...`. Add a helper and the stage functions to `pipeline_doctor.py`:

```python
def _expand_skill(rel: str) -> Path:
    """Translate `~/...` to an absolute path under $HOME."""
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
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_apply_skill.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_skill.py
git commit -m "P2.7: skill stage (apply + T1 drift detection)"
```

---

### Task 2.8: `prereqs` stage (apply = verify, never installs)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_apply_prereqs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_apply_prereqs.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


PREREQS = [
    {"id": "python", "kind": "binary", "name": "python3",
     "min_version": "3.10", "max_version": "3.12",
     "max_version_severity": "warn",
     "install_hint": "brew install python@3.12"},
    {"id": "git", "kind": "binary", "name": "git"},
    {"id": "missing-tool", "kind": "binary", "name": "definitely-not-a-real-binary-xyz",
     "install_hint": "brew install ghost"},
]


def test_check_prereqs_finds_python_and_git():
    result = pipeline_doctor.check_prereqs(manifest={"prereqs": PREREQS})
    assert result["status"] in ("warning", "critical")  # missing-tool always fails
    names = {p["id"]: p for p in result["prereqs"]}
    assert names["python"]["status"] == "ok"
    assert names["git"]["status"] == "ok"
    assert names["missing-tool"]["status"] == "missing"
    assert "brew install ghost" in names["missing-tool"]["install_hint"]


def test_check_prereqs_max_version_warn_does_not_fail():
    # Mock python3 to report 3.13 (above max)
    with patch("scripts.pipeline_doctor._binary_version",
               side_effect=lambda name: "3.13.0" if name == "python3" else "2.40.0"):
        prereqs = [
            {"id": "python", "kind": "binary", "name": "python3",
             "min_version": "3.10", "max_version": "3.12",
             "max_version_severity": "warn"},
            {"id": "git", "kind": "binary", "name": "git"},
        ]
        result = pipeline_doctor.check_prereqs(manifest={"prereqs": prereqs})
        py = next(p for p in result["prereqs"] if p["id"] == "python")
        assert py["status"] == "warning"
        # The overall should not be critical because severity is "warn"
        assert result["status"] != "critical"


def test_check_prereqs_min_version_fails():
    with patch("scripts.pipeline_doctor._binary_version",
               side_effect=lambda name: "3.9.0" if name == "python3" else "2.40.0"):
        prereqs = [{"id": "python", "kind": "binary", "name": "python3",
                    "min_version": "3.10", "max_version_severity": "warn"}]
        result = pipeline_doctor.check_prereqs(manifest={"prereqs": prereqs})
        assert result["status"] == "critical"


def test_apply_prereqs_never_installs():
    """--apply on prereqs is verify-only; it must not invoke install commands."""
    with patch("subprocess.run") as mock_run:
        # _binary_version uses subprocess.run; we let it return non-zero for the
        # binary so we can inspect what got called.
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Python 3.12.7"
        result = pipeline_doctor.apply_prereqs(manifest={"prereqs": PREREQS[:2]})
        # apply_prereqs delegates to check_prereqs; verify no `brew` or `pip
        # install` command was issued.
        all_args = [c.args[0] for c in mock_run.call_args_list]
        for argv in all_args:
            if isinstance(argv, list):
                assert argv[0] not in ("brew", "pip", "apt-get", "yum")
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_prereqs.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `prereqs` stage**

In `scripts/pipeline_doctor.py`, after the skill stage functions:

```python
import re
import shutil as _shutil  # already imported above as shutil; keep namespaces clean


def _binary_version(name: str) -> str | None:
    """Return a `major.minor.patch` string from `<name> --version`, or None
    if the binary is absent or the output is unparseable."""
    if _shutil.which(name) is None:
        return None
    try:
        r = subprocess.run([name, "--version"], capture_output=True,
                            text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or "") + (r.stderr or "")
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
        entry = {"id": p["id"], "name": name, "version": version}
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
    """Apply is verify-only for prereqs. Never installs; returns the check
    result so the caller / state file logic can act on it."""
    return check_prereqs(manifest)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_apply_prereqs.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_prereqs.py
git commit -m "P2.8: prereqs stage (verify-only; never installs)"
```

---

### Task 2.9: Stage dispatch + prerequisite enforcement

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_stage_dispatch.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_stage_dispatch.py`:

```python
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
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_stage_dispatch.py -v`
Expected: FAIL — dispatch not wired in.

- [ ] **Step 3: Implement dispatch in `main()`**

In `scripts/pipeline_doctor.py`, add a module-level constant:

```python
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
```

Now add a dispatcher function (before `main`):

```python
def _resolve_only(arg: str) -> list[str]:
    """Parse --only into canonical order; reject unknown stages."""
    if not arg:
        return list(STAGES_ORDER)
    requested = [s.strip() for s in arg.split(",") if s.strip()]
    unknown = [s for s in requested if s not in STAGES_ORDER]
    if unknown:
        print(f"error: unknown stage(s): {unknown}; "
              f"valid: {STAGES_ORDER}", file=sys.stderr)
        sys.exit(2)
    # Return in canonical order
    return [s for s in STAGES_ORDER if s in requested]


def _enforce_prereqs(stages: list[str]) -> None:
    """Fail-fast if a requested stage's prerequisites aren't also requested."""
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
                    tier: str, mutable_paths: list[str]) -> dict:
    report: dict = {"stages": {}}
    for stage in stages:
        if stage == "studio_extras" and tier != "studio":
            report["stages"][stage] = {"status": "skipped",
                                         "reason": "laptop tier"}
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
            r = {"status": "skipped",
                  "reason": "Phase 3 not yet implemented"}
        elif stage == "models":
            r = {"status": "skipped",
                  "reason": "Phase 3 not yet implemented"}
        elif stage == "studio_extras":
            r = {"status": "skipped",
                  "reason": "Phase 4 not yet implemented"}
        else:
            r = {"status": "critical", "error": f"unknown stage {stage!r}"}
        report["stages"][stage] = r
        record_stage_outcome(stage, ok=(r["status"] == "ok"),
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
        else:
            r = {"status": "skipped",
                  "reason": "Phase 3/4 stage not yet implemented"}
        report["stages"][stage] = r
    return report
```

Now wire dispatch into `main()`. Find the bottom of `main()` (around line 487) and replace the existing `if args.check in (...)` cascade with:

```python
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
                                                   mutable_paths=mutable_paths)
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
            report["structure"] = check_structure(manifest)
        if args.warm_cache:
            report["warm_cache"] = warm_cache(manifest, scope)
```

Update the exit-code computation to include the new keys:

```python
    worst = "ok"
    for k in ("disk", "venvs", "models", "wrappers", "structure",
              "apply", "check_installed"):
        if k not in report:
            continue
        # apply/check_installed are { "stages": { name: { "status": ... } } }
        if k in ("apply", "check_installed"):
            for stage_name, stage_r in report[k]["stages"].items():
                s = stage_r.get("status", "ok")
                if s == "critical":
                    worst = "critical"
                elif s in ("warning", "drift") and worst != "critical":
                    worst = "warning"
        else:
            s = report[k]["status"]
            if s == "critical":
                worst = "critical"
            elif s == "warning" and worst != "critical":
                worst = "warning"
    return {"ok": 0, "warning": 1, "critical": 1}[worst]
```

- [ ] **Step 4: Run tests + smoke a real apply**

Run: `python3 -m pytest tests/python/test_stage_dispatch.py -v`
Expected: all PASS.

Smoke against a tmpdir:

```bash
PIPELINE_ROOT=/tmp/p-test-1 python3 scripts/pipeline_doctor.py \
    --apply --tier laptop --only prereqs,dirs,config,scripts,skill --yes --json | \
    python3 -m json.tool | head -40
```

Expected: each requested stage reports `status: ok`. Files materialize at `/tmp/p-test-1/workspace/` and at `~/.claude/skills/asset-pipeline/` (skill is host-local; tests use a fake HOME). Clean up the tmpdir.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_stage_dispatch.py
git commit -m "P2.9: stage dispatcher + prerequisite enforcement + cold-start gate"
```

---

### Phase 2 self-check

```
python3 -m pytest tests/python -v
PIPELINE_ROOT=/tmp/p-phase2 python3 scripts/pipeline_doctor.py \
    --apply --tier studio --only prereqs,dirs,config,scripts,skill --yes
PIPELINE_ROOT=/tmp/p-phase2 python3 scripts/pipeline_doctor.py \
    --check installed --tier studio --json | python3 -m json.tool
```

Expected: all tests pass; the second command reports every implemented stage `ok`; venvs/models/studio_extras report `skipped — Phase 3/4 not yet implemented`.

Phase 2 ships a working local installer for everything that doesn't touch the network. Resumption from a cold tmpdir to a fully-populated workspace + skill is verified end-to-end.

---

## Phase 3 — Engine network stages

Implement `venvs` (lockfile install + drift + retry + patch pin check) and `models` (HF auth preflight + resumable downloads + smoke-warming + T3/T1 verify). Recipes live in `scripts/_install_lib.py`.

### Task 3.1: First-pass lockfiles (mflux + pipeline-tools)

This task is **manual** — the maintainer runs `pip freeze` once on a reference machine and commits the result. Subsequent installs are reproducible.

**Files:**
- Modify: `scripts/lockfiles/mflux-env.txt`
- Modify: `scripts/lockfiles/pipeline-tools-env.txt`

- [ ] **Step 1: Generate the mflux lockfile**

On a reference Mac with Python 3.12 installed:

```bash
python3.12 -m venv /tmp/lockgen-mflux
source /tmp/lockgen-mflux/bin/activate
pip install --upgrade pip setuptools wheel
pip install mflux Pillow
pip freeze --exclude pip --exclude setuptools --exclude wheel \
    > /Users/kenallred/Documents/dev-projects/2d-3d-pipeline/scripts/lockfiles/mflux-env.txt
deactivate
rm -rf /tmp/lockgen-mflux
```

- [ ] **Step 2: Generate the pipeline-tools lockfile**

```bash
python3.12 -m venv /tmp/lockgen-pt
source /tmp/lockgen-pt/bin/activate
pip install --upgrade pip setuptools wheel
pip install trimesh numpy scipy Pillow "rembg[cpu]" open_clip_torch torch tqdm requests
pip freeze --exclude pip --exclude setuptools --exclude wheel \
    > /Users/kenallred/Documents/dev-projects/2d-3d-pipeline/scripts/lockfiles/pipeline-tools-env.txt
deactivate
rm -rf /tmp/lockgen-pt
```

- [ ] **Step 3: Verify structure check still passes**

Run: `python3 scripts/pipeline_doctor.py --check structure`
Expected: exit 0; `v2:venv-fields` reports ok (lockfiles exist and contain no pip/setuptools/wheel entries).

- [ ] **Step 4: Commit**

```bash
git add scripts/lockfiles/mflux-env.txt scripts/lockfiles/pipeline-tools-env.txt
git commit -m "P3.1: first-pass lockfiles for mflux-env + pipeline-tools-env"
```

**Note:** The other three lockfiles (`hunyuan3d-paint-env`, `comfyui-env`, `multiview-env`) stay empty until Phase 3 work touches them. Empty lockfiles are valid by the structure check; the `apply venvs` stage will treat them as opt-in / not-yet-bootstrapped.

---

### Task 3.2: Python patch pin checker

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_python_pin.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_python_pin.py`:

```python
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_check_python_pin_ok(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("3.12.7\n")
    actual = "3.12.7"
    assert pipeline_doctor._patch_pin_matches(pin, actual)


def test_check_python_pin_minor_match_only_when_no_patch(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("3.12\n")
    assert pipeline_doctor._patch_pin_matches(pin, "3.12.7")
    assert pipeline_doctor._patch_pin_matches(pin, "3.12.0")


def test_check_python_pin_mismatch(tmp_path):
    pin = tmp_path / ".python-version"
    pin.write_text("3.12.7\n")
    assert not pipeline_doctor._patch_pin_matches(pin, "3.12.4")


def test_no_pin_file_is_acceptable(tmp_path):
    pin = tmp_path / ".python-version"  # not created
    assert pipeline_doctor._patch_pin_matches(pin, "3.12.5")
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_python_pin.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the pin checker**

In `scripts/pipeline_doctor.py`, near the other version helpers:

```python
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
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_python_pin.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_python_pin.py
git commit -m "P3.2: Python patch pin helper"
```

---

### Task 3.3: `venvs` stage — apply

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_apply_venvs.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_apply_venvs.py`:

```python
import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


VENV = {
    "name": "test-env",
    "path": "~/3d-pipeline/test-env",
    "required": True,
    "feature_set": "tier1",
    "size_gb": 1,
    "purpose": "test fixture",
    "python_version": "3.12",
    "lockfile": "scripts/lockfiles/_test_lockfile.txt",
}


def _seed_lockfile(content: str = "Pillow==10.4.0\n") -> Path:
    p = REPO / "scripts" / "lockfiles" / "_test_lockfile.txt"
    p.write_text(content)
    return p


def test_apply_venv_creates_venv_and_installs(tmp_pipeline_root):
    lockfile = _seed_lockfile()
    try:
        with patch("subprocess.run") as mock_run:
            mock_run.return_value.returncode = 0
            mock_run.return_value.stdout = ""
            mock_run.return_value.stderr = ""
            result = pipeline_doctor.apply_venv(VENV)
        # The venv directory should be created (mocked subprocess didn't run
        # python -m venv, so we check the dispatch arguments instead).
        calls = [c.args[0] for c in mock_run.call_args_list
                 if isinstance(c.args[0], list)]
        # First call: python -m venv <path>
        assert any(c[:3] == ["python3.12", "-m", "venv"] for c in calls)
        # A subsequent call: <venv>/bin/pip install -r <lockfile>
        pip_calls = [c for c in calls if c[-2:] == ["install", "-r"]
                     or (len(c) >= 4 and c[-3:-1] == ["install", "-r"])]
        assert pip_calls, f"no pip install -r call found in {calls}"
    finally:
        lockfile.unlink()


def test_apply_venv_skips_when_lockfile_empty(tmp_pipeline_root):
    lockfile = _seed_lockfile("")
    try:
        result = pipeline_doctor.apply_venv(VENV)
        assert result["status"] == "skipped"
        assert "empty lockfile" in result["reason"].lower()
    finally:
        lockfile.unlink()


def test_apply_venv_retries_on_wheel_failure(tmp_pipeline_root):
    lockfile = _seed_lockfile()
    try:
        # First pip install fails with wheel-build, second succeeds after
        # pip-setuptools-wheel upgrade.
        outcomes = iter([
            # python -m venv
            MagicMock(returncode=0, stdout="", stderr=""),
            # pip install -r lockfile (first try → fail)
            MagicMock(returncode=1, stdout="",
                       stderr="ERROR: Could not build wheels for torch"),
            # pip install --upgrade pip setuptools wheel
            MagicMock(returncode=0, stdout="", stderr=""),
            # pip install -r lockfile (retry → ok)
            MagicMock(returncode=0, stdout="", stderr=""),
        ])
        with patch("subprocess.run", side_effect=lambda *a, **k: next(outcomes)):
            result = pipeline_doctor.apply_venv(VENV)
        assert result["status"] == "ok"
        assert result.get("retried") is True
    finally:
        lockfile.unlink()


def test_apply_venv_double_failure_marks_partial(tmp_pipeline_root):
    lockfile = _seed_lockfile()
    try:
        outcomes = iter([
            MagicMock(returncode=0, stdout="", stderr=""),  # venv create
            MagicMock(returncode=1, stdout="", stderr="ERROR: build failed"),
            MagicMock(returncode=0, stdout="", stderr=""),  # pip upgrade
            MagicMock(returncode=1, stdout="", stderr="ERROR: still fails"),
        ])
        with patch("subprocess.run", side_effect=lambda *a, **k: next(outcomes)):
            result = pipeline_doctor.apply_venv(VENV)
        assert result["status"] == "critical"
        assert "failing_package" in result or "error" in result
    finally:
        lockfile.unlink()
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_venvs.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the venv stage**

In `scripts/pipeline_doctor.py`, after the prereqs/dirs/config/scripts/skill stage functions:

```python
def _venv_python(venv_path: Path) -> Path:
    return venv_path / "bin" / "python"


def _venv_pip(venv_path: Path) -> Path:
    return venv_path / "bin" / "pip"


def _parse_failing_package_from_pip_json(report_path: Path) -> str | None:
    """Read pip's --report JSON and identify the package that failed to install.
    Falls back to None on parse error."""
    if not report_path.exists():
        return None
    try:
        data = json.loads(report_path.read_text())
    except json.JSONDecodeError:
        return None
    # pip's report format: { "install": [ {"metadata": {"name": "..."} }, ... ] }
    # On failure the report is partial; the last entry is typically the one
    # that failed. This is best-effort.
    install = data.get("install") or []
    if install:
        return (install[-1].get("metadata") or {}).get("name")
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

    # Create the venv if missing
    if not path.exists():
        r = subprocess.run([f"python{pyver}", "-m", "venv", str(path)],
                            capture_output=True, text=True)
        if r.returncode != 0:
            return {"status": "critical", "name": name,
                    "stage": "venv-create", "error": r.stderr.strip()}

    pip = _venv_pip(path)

    # First install attempt
    r = subprocess.run([str(pip), "install", "-r", str(lockfile)],
                        capture_output=True, text=True)
    if r.returncode == 0:
        return {"status": "ok", "name": name, "retried": False}

    # Retry path: upgrade pip/setuptools/wheel, then re-install
    r_upgrade = subprocess.run(
        [str(pip), "install", "--upgrade", "pip", "setuptools", "wheel"],
        capture_output=True, text=True)
    r2 = subprocess.run([str(pip), "install", "-r", str(lockfile)],
                         capture_output=True, text=True)
    if r2.returncode == 0:
        return {"status": "ok", "name": name, "retried": True}

    # Both failed — record partial state
    # Try to get structured failure info via --dry-run --report
    report_path = path / ".pip-report.json"
    subprocess.run([str(pip), "install", "--dry-run",
                     "--report", str(report_path), "-r", str(lockfile)],
                    capture_output=True, text=True)
    failing = _parse_failing_package_from_pip_json(report_path)
    return {
        "status": "critical", "name": name,
        "retried": True,
        "failing_package": failing,
        "error": r2.stderr.strip()[:500],
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
        elif r["status"] in ("warning", "skipped") and overall == "ok":
            # skipped is not a failure but worth surfacing
            pass
    return {"status": overall, "venvs": rows}
```

- [ ] **Step 4: Wire `venvs` into the dispatcher**

In `dispatch_apply`, replace the `venvs` skipped branch:

```python
        elif stage == "venvs":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = apply_venvs(manifest, scope)
```

Also add `tier_includes` helper (above `dispatch_apply`):

```python
def tier_includes(manifest: dict, tier: str) -> list[str]:
    td = (manifest.get("tier_defaults") or {}).get(tier) or {}
    return list(td.get("include") or [])
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/python/test_apply_venvs.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_venvs.py
git commit -m "P3.3: venvs stage apply (lockfile install + pip-upgrade retry + partial)"
```

---

### Task 3.4: `venvs` stage — drift detection

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Modify: `tests/python/test_apply_venvs.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/python/test_apply_venvs.py`:

```python
def test_check_venv_drift_against_lockfile(tmp_pipeline_root):
    lockfile_dir = REPO / "scripts" / "lockfiles"
    lockfile = lockfile_dir / "_test_lockfile.txt"
    lockfile.write_text("Pillow==10.4.0\nrequests==2.31.0\n")
    try:
        venv = dict(VENV)
        # Mock `pip freeze` output that matches the lockfile
        with patch("scripts.pipeline_doctor._venv_pip_freeze",
                   return_value="Pillow==10.4.0\nrequests==2.31.0\n"):
            r = pipeline_doctor.check_venv(venv)
        assert r["status"] == "ok"

        # Now mock drifted freeze output
        with patch("scripts.pipeline_doctor._venv_pip_freeze",
                   return_value="Pillow==10.5.0\nrequests==2.31.0\n"):
            r = pipeline_doctor.check_venv(venv)
        assert r["status"] == "drift"
        assert "fix_command" in r
    finally:
        lockfile.unlink()


def test_check_venv_missing(tmp_pipeline_root):
    lockfile_dir = REPO / "scripts" / "lockfiles"
    lockfile = lockfile_dir / "_test_lockfile.txt"
    lockfile.write_text("Pillow==10.4.0\n")
    try:
        venv = dict(VENV)
        r = pipeline_doctor.check_venv(venv)
        assert r["status"] == "drift"
        assert r.get("reason") == "missing"
    finally:
        lockfile.unlink()
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_venvs.py -v -k check_venv`
Expected: FAIL.

- [ ] **Step 3: Implement the drift functions**

In `scripts/pipeline_doctor.py`:

```python
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
                "fix_command": f"pipeline_doctor.py --apply --only venvs"}

    expected = lockfile.read_text()
    actual = _venv_pip_freeze(path)
    if expected == actual:
        return {"status": "ok", "name": name}
    return {
        "status": "drift", "name": name, "reason": "lockfile-mismatch",
        "fix_command": f"pipeline_doctor.py --apply --only venvs",
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
```

- [ ] **Step 4: Wire into `dispatch_check_installed`**

Replace the venvs branch:

```python
        elif stage == "venvs":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = check_venvs_installed(manifest, scope)
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/python/test_apply_venvs.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_venvs.py
git commit -m "P3.4: venvs T2 drift detection (filtered pip freeze ↔ lockfile)"
```

---

### Task 3.5: HF auth preflight (per-repo `model_info`)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_hf_preflight.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_hf_preflight.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


GATED_MODEL = {
    "id": "hunyuan3d-paint", "filename": "hunyuan3d-paint.safetensors",
    "feature_set": "hunyuan3d-paint",
    "license_bucket": "commercial_threshold",
    "size_mb": 5000,
    "cache_dir": "~/3d-pipeline/models/hunyuan3d-paint",
    "env_var": "HUNYUAN3D_HOME", "download_url": "",
    "sha256": "", "managed_by": "hunyuan3d-paint",
    "notes": "",
    "requires_hf_auth": True, "hf_repo": "tencent/Hunyuan3D-2",
    "storage_layout": "hf_snapshot", "warm_target": "hunyuan3d-paint",
    "comfyui_kind": None,
}

OPEN_MODEL = {**GATED_MODEL, "id": "open", "requires_hf_auth": False,
              "hf_repo": "stabilityai/sd-vae-ft-mse"}


def test_preflight_skipped_when_no_gated_models():
    result = pipeline_doctor.hf_preflight([OPEN_MODEL])
    assert result["status"] == "ok"
    assert result["checked"] == 0


def test_preflight_passes_when_access_granted():
    with patch("huggingface_hub.HfApi") as MockApi:
        instance = MockApi.return_value
        instance.model_info.return_value = MagicMock()
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
    assert result["status"] == "ok"


def test_preflight_fails_with_401_per_repo():
    from huggingface_hub.utils import RepositoryNotFoundError
    with patch("huggingface_hub.HfApi") as MockApi:
        instance = MockApi.return_value
        instance.model_info.side_effect = RepositoryNotFoundError(
            "401 access denied")
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
    assert result["status"] == "critical"
    assert "tencent/Hunyuan3D-2" in result["details"]
    assert "huggingface-cli login" in result["details"] or \
        "request access" in result["details"]


def test_preflight_aborts_before_download():
    """The contract: returning critical means no download must have started."""
    from huggingface_hub.utils import RepositoryNotFoundError
    with patch("huggingface_hub.HfApi") as MockApi, \
         patch("huggingface_hub.hf_hub_download") as mock_dl:
        MockApi.return_value.model_info.side_effect = RepositoryNotFoundError(
            "401")
        result = pipeline_doctor.hf_preflight([GATED_MODEL])
        assert result["status"] == "critical"
        mock_dl.assert_not_called()
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_hf_preflight.py -v`
Expected: FAIL (and possibly skip if huggingface_hub not installed — see next step).

- [ ] **Step 3: Ensure huggingface_hub is available**

For the tests to run, `huggingface_hub` must be importable (we'll use it in production code). Install in the dev environment:

```bash
python3 -m pip install --user huggingface_hub requests
```

- [ ] **Step 4: Implement the preflight**

In `scripts/pipeline_doctor.py`:

```python
def hf_preflight(models: list[dict]) -> dict:
    """Per-repo access check for every model with requires_hf_auth=True.
    Returns critical on any 401 / RepositoryNotFoundError, with the offending
    repo named. Does not touch any downloads."""
    gated = [m for m in models if m.get("requires_hf_auth")]
    if not gated:
        return {"status": "ok", "checked": 0, "details": "no gated models in scope"}

    try:
        from huggingface_hub import HfApi
        from huggingface_hub.utils import (
            RepositoryNotFoundError, GatedRepoError,
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
            api.model_info(repo)
        except (RepositoryNotFoundError, GatedRepoError) as e:
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
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/python/test_hf_preflight.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_hf_preflight.py
git commit -m "P3.5: HF per-repo auth preflight (model_info, not just whoami)"
```

---

### Task 3.6: Resumable downloads (direct URL via Range + HF via hf_hub_download)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_downloads.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_downloads.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


def test_download_direct_url_writes_to_part_then_rename(tmp_path):
    dest = tmp_path / "out.bin"
    # Mock requests.get to return a small payload
    chunks = [b"hello ", b"world", b""]
    mock_resp = MagicMock()
    mock_resp.iter_content = lambda chunk_size: iter([c for c in chunks if c])
    mock_resp.status_code = 200
    mock_resp.headers = {"content-length": "11"}
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = lambda s, *a: None
    with patch("requests.get", return_value=mock_resp):
        result = pipeline_doctor._download_with_range(
            "https://example/out.bin", dest, expected_size=11)
    assert dest.exists()
    assert dest.read_bytes() == b"hello world"
    assert not (dest.with_suffix(".bin.part")).exists()
    assert result["status"] == "ok"


def test_download_direct_url_resumes_from_part(tmp_path):
    dest = tmp_path / "out.bin"
    part = dest.with_suffix(".bin.part")
    part.write_bytes(b"hello ")  # 6 bytes already on disk
    chunks = [b"world", b""]
    captured_headers = {}

    def fake_get(url, headers=None, stream=False, timeout=None):
        captured_headers.update(headers or {})
        m = MagicMock()
        m.iter_content = lambda chunk_size: iter([c for c in chunks if c])
        m.status_code = 206
        m.headers = {"content-length": "5"}
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, *a: None
        return m

    with patch("requests.get", side_effect=fake_get):
        result = pipeline_doctor._download_with_range(
            "https://example/out.bin", dest, expected_size=11)
    assert dest.read_bytes() == b"hello world"
    assert "Range" in captured_headers
    assert captured_headers["Range"] == "bytes=6-"
    assert result["status"] == "ok"


def test_download_direct_url_restarts_when_server_ignores_range(tmp_path):
    dest = tmp_path / "out.bin"
    part = dest.with_suffix(".bin.part")
    part.write_bytes(b"stale-bytes")  # 11 bytes of stale data

    def fake_get(url, headers=None, stream=False, timeout=None):
        m = MagicMock()
        m.iter_content = lambda chunk_size: iter([b"abcdefghij", b""])
        m.status_code = 200  # server ignored Range and returned full body
        m.headers = {"content-length": "10"}
        m.__enter__ = lambda s: s
        m.__exit__ = lambda s, *a: None
        return m

    with patch("requests.get", side_effect=fake_get):
        result = pipeline_doctor._download_with_range(
            "https://example/out.bin", dest, expected_size=10)
    assert dest.read_bytes() == b"abcdefghij"
    assert result.get("restarted") is True


def test_download_hf_uses_hf_hub_download(tmp_path):
    with patch("huggingface_hub.hf_hub_download") as mock_dl:
        mock_dl.return_value = str(tmp_path / "snapshot" / "file.bin")
        (tmp_path / "snapshot").mkdir()
        (tmp_path / "snapshot" / "file.bin").write_bytes(b"x" * 100)
        result = pipeline_doctor._download_hf(
            "tencent/Hunyuan3D-2", "hunyuan3d-paint.safetensors",
            cache_dir=tmp_path)
    assert result["status"] == "ok"
    mock_dl.assert_called_once()
    assert mock_dl.call_args.kwargs.get("resume_download") is True or \
        "resume_download" not in mock_dl.call_args.kwargs  # default is True
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_downloads.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement download functions**

In `scripts/pipeline_doctor.py`, replace the existing `_download` (around line 357) with:

```python
def _download_with_range(url: str, dest: Path, expected_size: int | None = None,
                          chunk_size: int = 65536) -> dict:
    """Resumable streaming download via HTTP Range header.

    Writes to `<dest>.part`; on success, atomic-renames to `dest`. If a `.part`
    file already exists, sends `Range: bytes=<offset>-`. If the server replies
    200 instead of 206, the server doesn't honour Range — discard the partial
    and start over.
    """
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
    """Download a file from a HuggingFace repo with native resume support."""
    try:
        from huggingface_hub import hf_hub_download  # type: ignore
    except ImportError:
        return {"status": "critical",
                "error": "huggingface_hub not installed"}
    cache_dir.mkdir(parents=True, exist_ok=True)
    try:
        path = hf_hub_download(
            repo_id=hf_repo, filename=filename,
            cache_dir=str(cache_dir), resume_download=True,
        )
        return {"status": "ok", "path": path}
    except Exception as e:
        return {"status": "critical",
                "error": f"{type(e).__name__}: {str(e)[:200]}"}
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_downloads.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_downloads.py
git commit -m "P3.6: resumable downloads (HF + direct-URL Range)"
```

---

### Task 3.7: `_install_lib.py` — host-tool recipes

**Files:**
- Modify: `scripts/_install_lib.py`
- Create: `tests/python/test_install_lib.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_install_lib.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import _install_lib  # noqa: E402


def test_dispatch_unknown_managed_by_returns_skipped():
    model = {"id": "x", "managed_by": "nope", "warm_target": "x"}
    status, detail = _install_lib.warm(model)
    assert status == "skipped"
    assert "nope" in detail.lower() or "unknown" in detail.lower()


def test_rembg_recipe_invokes_new_session():
    model = {"id": "u2net", "managed_by": "rembg",
             "warm_target": "u2net", "storage_layout": "literal",
             "cache_dir": "~/3d-pipeline/models/rembg",
             "filename": "u2net.onnx",
             "env_var": "U2NET_HOME"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        status, detail = _install_lib.warm(model)
    # Recipe should have shelled out to the venv python with a `from rembg ...`
    # snippet — check the arguments.
    called = False
    for c in mock_run.call_args_list:
        argv = c.args[0] if c.args else []
        if isinstance(argv, list) and any("rembg" in a for a in argv):
            called = True
            break
    assert called, f"rembg snippet not invoked; calls: {mock_run.call_args_list}"


def test_comfyui_dispatch_by_kind():
    """managed_by=comfyui dispatches by comfyui_kind."""
    for kind in ("checkpoint", "ip_adapter", "controlnet", "lora"):
        model = {"id": f"x-{kind}", "managed_by": "comfyui",
                 "comfyui_kind": kind, "warm_target": f"x-{kind}",
                 "storage_layout": "hf_snapshot",
                 "hf_repo": f"test/{kind}",
                 "filename": f"x-{kind}.safetensors",
                 "cache_dir": "~/3d-pipeline/models/comfyui"}
        with patch("scripts._install_lib._comfyui_warm") as mock_cf:
            mock_cf.return_value = ("ok", "downloaded")
            status, detail = _install_lib.warm(model)
        mock_cf.assert_called_once()
        kwargs = mock_cf.call_args.kwargs
        # Passed both model + kind for kind-specific placement
        assert mock_cf.call_args.args[0] == model or kwargs.get("model") == model


def test_open_clip_recipe_uses_env_var():
    model = {"id": "clip-vit-l-14", "managed_by": "open_clip",
             "warm_target": "ViT-L-14", "storage_layout": "hf_snapshot",
             "hf_repo": "laion/CLIP-ViT-L-14-laion2B-s32B-b82K",
             "filename": "open_clip_pytorch_model.bin",
             "cache_dir": "~/3d-pipeline/models/clip",
             "env_var": "OPEN_CLIP_CACHE_DIR"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        status, detail = _install_lib.warm(model)
    # Env passed to subprocess.run must include OPEN_CLIP_CACHE_DIR
    found = False
    for c in mock_run.call_args_list:
        env = c.kwargs.get("env") or {}
        if "OPEN_CLIP_CACHE_DIR" in env:
            found = True
            break
    assert found, "OPEN_CLIP_CACHE_DIR not passed to subprocess"
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_install_lib.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement recipes**

Replace `scripts/_install_lib.py`:

```python
"""Host-tool recipes for smoke-warming lazy-managed models.

Dispatched by `pipeline_doctor.py` keyed by `managed_by`. For ComfyUI, a
second-level dispatch by `comfyui_kind` handles the four distinct model kinds
(checkpoint, ip_adapter, controlnet, lora) that all share `managed_by:
comfyui` but need different placement.

Each recipe is a function (model_dict) -> (status, detail) where status is
one of {"ok", "skipped", "failed"} and detail is a short string.

Adding a new model under an existing managed_by + comfyui_kind requires only
a manifest edit. Adding a new managed_by or a new comfyui_kind requires a
function here.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path


def _expand(p: str) -> Path:
    return Path(os.path.expanduser(p))


def _run_in_venv(venv_path: Path, snippet: str, env_extra: dict | None = None) -> tuple[int, str, str]:
    """Run a one-line Python snippet inside a venv. Returns (returncode, stdout, stderr)."""
    python = venv_path / "bin" / "python"
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    r = subprocess.run([str(python), "-c", snippet],
                        capture_output=True, text=True, env=env, timeout=600)
    return r.returncode, r.stdout, r.stderr


def _rembg_warm(model: dict) -> tuple[str, str]:
    venv = _expand("~/3d-pipeline/pipeline-tools-env")
    target = model["warm_target"]
    snippet = f"from rembg import new_session; new_session({target!r}); print('ok')"
    env = {model["env_var"]: str(_expand(model["cache_dir"]))} if model.get("env_var") else None
    rc, out, err = _run_in_venv(venv, snippet, env_extra=env)
    if rc == 0:
        return ("ok", f"rembg new_session({target!r}) completed")
    return ("failed", err.strip()[:300])


def _open_clip_warm(model: dict) -> tuple[str, str]:
    venv = _expand("~/3d-pipeline/pipeline-tools-env")
    target = model["warm_target"]
    snippet = (
        "import open_clip; "
        f"open_clip.create_model_and_transforms({target!r}, pretrained='laion2b_s32b_b82k'); "
        "print('ok')"
    )
    env = {model["env_var"]: str(_expand(model["cache_dir"]))} if model.get("env_var") else None
    rc, out, err = _run_in_venv(venv, snippet, env_extra=env)
    if rc == 0:
        return ("ok", f"open_clip warm {target!r} completed")
    return ("failed", err.strip()[:300])


def _hunyuan_warm(model: dict) -> tuple[str, str]:
    """Hunyuan3D-Paint uses huggingface_hub from inside its own venv."""
    venv = _expand("~/3d-pipeline/hunyuan3d-paint-env")
    repo = model["hf_repo"]
    fn = model["filename"]
    cache = _expand(model["cache_dir"])
    snippet = (
        "from huggingface_hub import hf_hub_download; "
        f"hf_hub_download({repo!r}, {fn!r}, cache_dir={str(cache)!r}, resume_download=True); "
        "print('ok')"
    )
    rc, out, err = _run_in_venv(venv, snippet)
    if rc == 0:
        return ("ok", f"hunyuan {repo} {fn} downloaded")
    return ("failed", err.strip()[:300])


def _comfyui_warm(model: dict) -> tuple[str, str]:
    """ComfyUI has four kinds; each lives in a different cache subdirectory.
    The recipe downloads via huggingface_hub into the kind-specific dir."""
    venv = _expand("~/3d-pipeline/comfyui-env")
    repo = model["hf_repo"]
    fn = model["filename"]
    cache = _expand(model["cache_dir"])
    # cache_dir is already kind-specific per the manifest (e.g.
    # ~/3d-pipeline/models/sdxl, ~/3d-pipeline/models/ip-adapter)
    snippet = (
        "from huggingface_hub import hf_hub_download; "
        f"hf_hub_download({repo!r}, {fn!r}, cache_dir={str(cache)!r}, resume_download=True); "
        "print('ok')"
    )
    rc, out, err = _run_in_venv(venv, snippet)
    if rc == 0:
        return ("ok", f"comfyui {model.get('comfyui_kind')} {fn} downloaded")
    return ("failed", err.strip()[:300])


RECIPES = {
    "rembg":           _rembg_warm,
    "open_clip":       _open_clip_warm,
    "hunyuan3d-paint": _hunyuan_warm,
    "comfyui":         _comfyui_warm,
}


def warm(model: dict) -> tuple[str, str]:
    managed = model.get("managed_by")
    recipe = RECIPES.get(managed)
    if recipe is None:
        return ("skipped", f"unknown managed_by {managed!r}; recipe missing")
    return recipe(model)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_install_lib.py -v`
Expected: all PASS.

- [ ] **Step 5: Regenerate HTML embeds (so the new `_install_lib.py` content lands)**

Run: `make regenerate && make verify`
Expected: HTML guides updated; verify passes.

- [ ] **Step 6: Commit**

```bash
git add scripts/_install_lib.py tests/python/test_install_lib.py docs/asset-pipeline-guide.html docs/asset-pipeline-guide-studio.html
git commit -m "P3.7: _install_lib.py recipes (rembg, open_clip, hunyuan, comfyui)"
```

---

### Task 3.8: `models` stage — apply (warm + T3 verify)

**Files:**
- Modify: `scripts/pipeline_doctor.py`
- Create: `tests/python/test_apply_models.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_apply_models.py`:

```python
import sys
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import pipeline_doctor  # noqa: E402


MODEL_LITERAL = {
    "id": "u2net", "filename": "u2net.onnx",
    "feature_set": "tier1", "license_bucket": "commercial_safe",
    "size_mb": 170, "cache_dir": "~/3d-pipeline/models/rembg",
    "env_var": "U2NET_HOME",
    "download_url": "https://github.com/danielgatis/rembg/releases/download/v0.0.0/u2net.onnx",
    "sha256": "", "managed_by": "rembg", "notes": "",
    "requires_hf_auth": False, "hf_repo": None,
    "storage_layout": "literal", "warm_target": "u2net", "comfyui_kind": None,
}


def test_apply_model_warm_then_verify_present(tmp_pipeline_root):
    """A recipe that returns 'ok' and creates the file produces 'downloaded'."""
    cache = tmp_pipeline_root / "models" / "rembg"
    cache.mkdir(parents=True)

    def fake_recipe(m):
        # Simulate the host tool creating the file
        (cache / m["filename"]).write_bytes(b"x" * (m["size_mb"] * 1024 * 1024))
        return ("ok", "completed")

    with patch("scripts._install_lib.warm", side_effect=fake_recipe):
        result = pipeline_doctor.apply_model(MODEL_LITERAL)
    assert result["status"] == "ok"
    assert result.get("verified") is True


def test_apply_model_warm_succeeds_but_file_missing_fails(tmp_pipeline_root):
    """Recipe returns 'ok' but doesn't actually produce the file — must FAIL."""
    def fake_recipe(m):
        return ("ok", "completed")  # but file never appears

    with patch("scripts._install_lib.warm", side_effect=fake_recipe):
        result = pipeline_doctor.apply_model(MODEL_LITERAL)
    assert result["status"] == "critical"
    assert result.get("verified") is False


def test_apply_model_warm_failed_propagates(tmp_pipeline_root):
    def fake_recipe(m):
        return ("failed", "rembg crashed")
    with patch("scripts._install_lib.warm", side_effect=fake_recipe):
        result = pipeline_doctor.apply_model(MODEL_LITERAL)
    assert result["status"] == "critical"
    assert "rembg crashed" in result["error"]


def test_check_model_t3_size_window(tmp_pipeline_root):
    cache = tmp_pipeline_root / "models" / "rembg"
    cache.mkdir(parents=True)
    # File at declared size (170 MB)
    (cache / "u2net.onnx").write_bytes(b"x" * (170 * 1024 * 1024))
    r = pipeline_doctor.check_model(MODEL_LITERAL)
    assert r["status"] == "ok"

    # File way undersized
    (cache / "u2net.onnx").write_bytes(b"x" * 100)
    r = pipeline_doctor.check_model(MODEL_LITERAL)
    assert r["status"] == "drift"
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_apply_models.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement the models stage**

In `scripts/pipeline_doctor.py`:

```python
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

    # ±5% tolerance, plus a 1 MB floor for tiny files
    tolerance = max(expected_mb * 0.05, 1)
    if abs(actual_mb - expected_mb) > tolerance:
        return {"status": "drift",
                "reason": f"size {actual_mb:.1f} MB outside ±5% of {expected_mb} MB",
                "actual_mb": round(actual_mb, 1)}
    return {"status": "ok", "actual_mb": round(actual_mb, 1)}


def apply_model(model: dict) -> dict:
    """Warm the model via its host tool, then T3-verify the result."""
    from scripts import _install_lib  # type: ignore
    warm_status, warm_detail = _install_lib.warm(model)
    if warm_status == "failed":
        return {"status": "critical", "id": model["id"],
                "error": warm_detail, "verified": False}
    if warm_status == "skipped":
        # No recipe — fall through to verification (may still report ok if
        # the file happens to already exist from some other path)
        pass
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
    rows: list[dict] = []
    in_scope = [m for m in (manifest.get("models") or [])
                if m.get("feature_set") in scope]

    # HF auth preflight FIRST — must abort before any download
    preflight = hf_preflight(in_scope)
    if preflight["status"] == "critical":
        return {"status": "critical",
                "preflight": preflight,
                "models": [],
                "error": preflight["details"]}

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
```

- [ ] **Step 4: Wire into dispatcher**

In `dispatch_apply` and `dispatch_check_installed`, replace the `models` skipped branches:

```python
        elif stage == "models":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = apply_models(manifest, scope)   # in dispatch_apply

        elif stage == "models":
            scope = _resolve_feature_sets(manifest, tier_includes(manifest, tier))
            r = check_models_installed(manifest, scope)  # in dispatch_check_installed
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/python/test_apply_models.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add scripts/pipeline_doctor.py tests/python/test_apply_models.py
git commit -m "P3.8: models stage (HF preflight + warm + T3 verify)"
```

---

### Phase 3 self-check

```
python3 -m pytest tests/python -v
PIPELINE_ROOT=/tmp/p-phase3 python3 scripts/pipeline_doctor.py \
    --check installed --tier laptop --json | python3 -m json.tool | head -60
```

Expected: full pytest suite passes; check_installed reports every stage with structured drift/ok output. End-to-end `--apply --tier laptop` against a fresh root (with HF auth handled) is now possible for the tier1 feature set.

Phase 3 ships the full network-enabled installer. Models download with resume; venvs install from lockfile with auto-retry; HF preflight guards downloads.

---

## Phase 4 — Studio extras + heartbeat

Studio-tier-only stage: queue directories, opt-in launchd plist, and the worker heartbeat protocol that the setup skill uses to decide whether a foreign worker is alive before touching the shared queue.

### Task 4.1: Launchd plist template

**Files:**
- Create: `scripts/launchd/queue-worker.plist.tmpl`
- Modify: `scripts/pipeline_doctor.py` (template renderer)
- Create: `tests/python/test_studio_extras.py`

- [ ] **Step 1: Create the plist template**

Create `scripts/launchd/queue-worker.plist.tmpl`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>{worker_script}</string>
        <string>--assets-root</string>
        <string>{assets_root}</string>
        <string>--script-dir</string>
        <string>{script_dir}</string>
        <string>--reclaim-stuck-after</string>
        <string>30</string>
        <string>--max-claims</string>
        <string>3</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <dict>
        <key>SuccessfulExit</key>
        <false/>
    </dict>
    <key>StandardOutPath</key>
    <string>{log_dir}/queue-worker.out.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/queue-worker.err.log</string>
    <key>WorkingDirectory</key>
    <string>{assets_root}</string>
</dict>
</plist>
```

- [ ] **Step 2: Write failing test**

Create `tests/python/test_studio_extras.py`:

```python
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
```

- [ ] **Step 3: Run failing**

Run: `python3 -m pytest tests/python/test_studio_extras.py -v`
Expected: FAIL.

- [ ] **Step 4: Implement template renderer + stage**

In `scripts/pipeline_doctor.py`:

```python
def _render_launchd_plist(plist_cfg: dict) -> str:
    tmpl_rel = plist_cfg["template"]
    tmpl = (REPO_ROOT / tmpl_rel).read_text()
    workspace = _root() / "workspace"
    log_dir = _root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
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
```

- [ ] **Step 5: Wire into dispatcher**

In `dispatch_apply`, replace the `studio_extras` branch:

```python
        elif stage == "studio_extras":
            declined = load_state().get("declined", {})
            # In automated mode, default to declining the plist offer; the
            # skill prompts the user and re-runs with --reconsider-optionals.
            accept_plist = False
            r = apply_studio_extras(manifest, tier=tier,
                                       accept_plist=accept_plist,
                                       declined_state=declined)
```

In `dispatch_check_installed`:

```python
        elif stage == "studio_extras":
            declined = load_state().get("declined", {})
            r = check_studio_extras(manifest, tier=tier, declined_state=declined)
```

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/python/test_studio_extras.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add scripts/launchd/queue-worker.plist.tmpl scripts/pipeline_doctor.py tests/python/test_studio_extras.py
git commit -m "P4.1: studio_extras stage (queue dirs + opt-in launchd plist)"
```

---

### Task 4.2: Heartbeat write protocol (helper, no queue_worker changes yet)

**Files:**
- Modify: `scripts/pipeline_doctor.py` (heartbeat read helper)
- Create: `scripts/_heartbeat.py` (shared write helper)
- Modify: `tools/_embed_lib.py` (add to EMBEDS)
- Create: `tests/python/test_heartbeat.py`

- [ ] **Step 1: Write failing tests**

Create `tests/python/test_heartbeat.py`:

```python
import datetime
import socket
import sys
import time
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from scripts import _heartbeat  # noqa: E402
from scripts import pipeline_doctor  # noqa: E402


def test_write_heartbeat_local_temp_then_rename(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "test-machine"
    result = _heartbeat.write(queue, machine=machine, timeout_seconds=5)
    assert result["status"] == "ok"
    hb = queue / f".heartbeat-{machine}"
    assert hb.exists()
    # ISO timestamp
    datetime.datetime.fromisoformat(hb.read_text().strip().rstrip("Z"))


def test_heartbeat_read_alive_when_recent(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "remote-studio"
    _heartbeat.write(queue, machine=machine, timeout_seconds=5)
    alive = pipeline_doctor.is_heartbeat_alive(
        queue, machine=machine, max_age_seconds=90)
    assert alive is True


def test_heartbeat_read_dead_when_stale(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "remote-studio"
    hb = queue / f".heartbeat-{machine}"
    # Write a timestamp 5 minutes ago
    stale = (datetime.datetime.utcnow() - datetime.timedelta(minutes=5))
    hb.write_text(stale.isoformat() + "Z")
    alive = pipeline_doctor.is_heartbeat_alive(
        queue, machine=machine, max_age_seconds=90)
    assert alive is False


def test_heartbeat_write_timeout_returns_degraded(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    machine = "test-machine"

    # Simulate the atomic-rename taking longer than timeout
    real_replace = Path.replace

    def slow_replace(self, target):
        time.sleep(2)
        return real_replace(self, target)

    with patch.object(Path, "replace", slow_replace):
        result = _heartbeat.write(queue, machine=machine, timeout_seconds=1)
    assert result["status"] == "degraded"
    assert "timeout" in result["reason"].lower()


def test_heartbeat_missing_file_is_dead(tmp_path):
    queue = tmp_path / "queue"
    queue.mkdir()
    alive = pipeline_doctor.is_heartbeat_alive(
        queue, machine="nobody-home", max_age_seconds=90)
    assert alive is False
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_heartbeat.py -v`
Expected: FAIL — modules don't exist.

- [ ] **Step 3: Implement the heartbeat write helper**

Create `scripts/_heartbeat.py`:

```python
"""Heartbeat write helper used by queue_worker.py.

The protocol: write to a local tmp file, then atomic-rename onto the shared
queue path. Wrap the rename in a watchdog with `timeout_seconds`. On timeout,
return a `degraded` result; caller logs and continues.

This module is intentionally tiny so it can be imported from both
`pipeline_doctor.py` and `queue_worker.py` without pulling extra deps.
"""
from __future__ import annotations

import datetime
import os
import tempfile
import threading
from pathlib import Path


def write(queue_dir: Path, *, machine: str,
           timeout_seconds: int = 25) -> dict:
    """Write a heartbeat for `machine` into `queue_dir/.heartbeat-<machine>`."""
    queue_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.datetime.utcnow().isoformat() + "Z"
    dest = queue_dir / f".heartbeat-{machine}"

    # Write to a local temp file first
    tmp = Path(tempfile.gettempdir()) / f".heartbeat-{machine}-{os.getpid()}.tmp"
    tmp.write_text(ts)

    # Watchdog-guarded rename
    result: dict = {"status": "ok", "ts": ts}
    finished = threading.Event()

    def do_rename():
        try:
            tmp.replace(dest)
        except Exception as e:
            result["status"] = "failed"
            result["reason"] = f"{type(e).__name__}: {str(e)[:200]}"
        finally:
            finished.set()

    t = threading.Thread(target=do_rename, daemon=True)
    t.start()
    if not finished.wait(timeout=timeout_seconds):
        result["status"] = "degraded"
        result["reason"] = f"rename did not complete within {timeout_seconds}s"
        # Best-effort cleanup of the tmp file
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return result
```

- [ ] **Step 4: Implement the read helper in pipeline_doctor.py**

```python
def is_heartbeat_alive(queue_dir: Path, *, machine: str,
                        max_age_seconds: int) -> bool:
    """True iff the heartbeat for `machine` is < max_age_seconds old."""
    import datetime
    hb = queue_dir / f".heartbeat-{machine}"
    if not hb.exists():
        return False
    try:
        content = hb.read_text().strip()
        # Accept both `...Z` and bare ISO
        if content.endswith("Z"):
            content = content[:-1]
        ts = datetime.datetime.fromisoformat(content)
    except (ValueError, OSError):
        return False
    age = (datetime.datetime.utcnow() - ts).total_seconds()
    return age < max_age_seconds
```

- [ ] **Step 5: Add `_heartbeat.py` to EMBEDS**

Edit `tools/_embed_lib.py`, add to the `EMBEDS` dict (near `_install_lib.py`):

```python
    "scripts/_heartbeat.py":            "~/3d-pipeline/workspace/_heartbeat.py",
```

- [ ] **Step 6: Run tests + regenerate HTML**

Run: `python3 -m pytest tests/python/test_heartbeat.py -v`
Expected: all PASS.

Run: `make regenerate && make verify`
Expected: clean.

- [ ] **Step 7: Commit**

```bash
git add scripts/_heartbeat.py scripts/pipeline_doctor.py tools/_embed_lib.py tests/python/test_heartbeat.py docs/asset-pipeline-guide.html docs/asset-pipeline-guide-studio.html
git commit -m "P4.2: heartbeat write/read helpers (local-tmp + atomic-rename + watchdog)"
```

---

### Task 4.3: Wire heartbeat into `queue_worker.py`

**Files:**
- Modify: `scripts/queue_worker.py`
- Create: `tests/python/test_queue_worker_heartbeat.py`

- [ ] **Step 1: Read the existing queue_worker.py main loop**

Read `scripts/queue_worker.py` lines 280-370 to identify the three continue-points (pending-empty sleep, job-claimed continue, job-failed continue). The exact line numbers may differ from the spec; locate them by structure.

- [ ] **Step 2: Write failing test**

Create `tests/python/test_queue_worker_heartbeat.py`:

```python
"""Integration: queue_worker writes a heartbeat each poll cycle."""
import datetime
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
WORKER = REPO / "scripts" / "queue_worker.py"


def test_worker_writes_heartbeat_at_start(tmp_path):
    """Smoke: starting the worker creates a heartbeat file within 5s."""
    assets_root = tmp_path / "ws"
    (assets_root / "queue" / "pending").mkdir(parents=True)
    (assets_root / "queue" / "running").mkdir(parents=True)
    (assets_root / "queue" / "done").mkdir(parents=True)
    (assets_root / "queue" / "failed").mkdir(parents=True)

    # Start worker as a subprocess; let it write one heartbeat then stop it
    proc = subprocess.Popen(
        [sys.executable, str(WORKER),
         "--assets-root", str(assets_root),
         "--script-dir", str(assets_root),
         "--poll-seconds", "1"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        machine = socket.gethostname()
        hb = assets_root / "queue" / f".heartbeat-{machine}"
        deadline = time.time() + 8
        while time.time() < deadline:
            if hb.exists():
                break
            time.sleep(0.5)
        assert hb.exists(), "worker did not write a heartbeat within 8s"
        content = hb.read_text().strip()
        if content.endswith("Z"):
            content = content[:-1]
        ts = datetime.datetime.fromisoformat(content)
        # Should be very recent
        age = (datetime.datetime.utcnow() - ts).total_seconds()
        assert age < 30
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
```

- [ ] **Step 3: Run failing**

Run: `python3 -m pytest tests/python/test_queue_worker_heartbeat.py -v`
Expected: FAIL — heartbeat not yet wired.

- [ ] **Step 4: Add heartbeat writes to the worker main loop**

Edit `scripts/queue_worker.py`:

At the top (imports section), add:

```python
import socket
try:
    from _heartbeat import write as _heartbeat_write  # type: ignore
except ImportError:
    # Fallback when run from source: insert the script's dir into sys.path
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _heartbeat import write as _heartbeat_write  # type: ignore
```

Find the main-loop function (the one that calls `_list_pending` / claims / runs jobs — typically named `run()` or `main_loop()`). Identify its accepted arguments; we need access to `assets_root` and a way to read `heartbeat_max_age_seconds` / `heartbeat_write_timeout_seconds`.

Add a CLI argument:

```python
    parser.add_argument("--heartbeat-write-timeout-seconds", type=int, default=25,
                        help="Watchdog for heartbeat atomic-rename")
```

Add a helper near the top of the main loop function:

```python
    machine = socket.gethostname()
    queue_dir = Path(args.assets_root) / "queue"

    def _hb():
        try:
            _heartbeat_write(queue_dir, machine=machine,
                              timeout_seconds=args.heartbeat_write_timeout_seconds)
        except Exception as e:
            print(f"[worker] heartbeat write failed: {e}", file=sys.stderr)
```

Now insert `_hb()` calls at every continue-point in the main loop:

1. After the initial setup / before entering the loop:

```python
    _hb()  # initial heartbeat so an observer can confirm boot
```

2. At the top of each poll iteration (just after the `while True:`):

```python
    while True:
        _hb()
        # ... existing pending-listing logic
```

3. Before any `time.sleep(...)` for empty-pending:

```python
        if not pending:
            _hb()
            time.sleep(args.poll_seconds)
            continue
```

4. After processing each job (whether success or failure):

```python
        # after job dispatch (existing code) — ensure heartbeat lands
        _hb()
```

Exact placement depends on the existing structure; the goal is "at least one `_hb()` call between any two adjacent operations that could each take >30s".

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/python/test_queue_worker_heartbeat.py -v`
Expected: PASS.

- [ ] **Step 6: Regenerate HTML embeds**

Run: `make regenerate && make verify`

- [ ] **Step 7: Commit**

```bash
git add scripts/queue_worker.py tests/python/test_queue_worker_heartbeat.py docs/asset-pipeline-guide.html docs/asset-pipeline-guide-studio.html
git commit -m "P4.3: queue_worker.py writes heartbeats at each main-loop point"
```

---

### Phase 4 self-check

```
python3 -m pytest tests/python -v
# Smoke the studio_extras stage on a tmpdir
PIPELINE_ROOT=/tmp/p-phase4 python3 scripts/pipeline_doctor.py \
    --apply --tier studio --only dirs,scripts,studio_extras --yes
ls /tmp/p-phase4/workspace/queue/
```

Expected: pytest passes; queue directories exist; declined plist recorded in `.install_state.json`.

Phase 4 ships the studio-only pieces. The setup skill in Phase 5 will gate apply on the heartbeat liveness check.

---

## Phase 5 — Setup skill + docs

The driver skill is intentionally thin: it walks the user through tier choice, HF auth, optional feature_sets, and the multi-select drift UX. The engine does all the heavy lifting.

### Task 5.1: Create the setup-skill scaffold

**Files:**
- Create: `setup-skill/SKILL.md`
- Create: `setup-skill/scripts/audit_loop.py`
- Create: `tests/python/test_setup_skill_layout.py`

- [ ] **Step 1: Write a layout test**

Create `tests/python/test_setup_skill_layout.py`:

```python
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def test_setup_skill_directory_exists():
    assert (REPO / "setup-skill" / "SKILL.md").exists()


def test_setup_skill_not_in_embeds():
    """Per spec §1.1 the setup skill ships via repo clone, not EMBEDS."""
    import sys
    sys.path.insert(0, str(REPO))
    from tools._embed_lib import EMBEDS  # noqa
    forbidden = [src for src in EMBEDS if src.startswith("setup-skill/")]
    assert forbidden == [], \
        f"setup-skill files must not be in EMBEDS: {forbidden}"


def test_setup_skill_audit_loop_helper_exists():
    assert (REPO / "setup-skill" / "scripts" / "audit_loop.py").exists()
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_setup_skill_layout.py -v`
Expected: FAIL.

- [ ] **Step 3: Create the skill scaffold**

Create `setup-skill/SKILL.md`:

```markdown
# asset-pipeline-setup

> Setup + audit/fix skill for Ken's local 2D/3D/print asset pipeline.

This skill is invoked when:
- Setting up the pipeline on a fresh Mac (laptop or studio tier).
- Auditing an existing install for drift against the repo catalog.
- Reconciling a deployed machine after the repo gains new scripts, models, or venvs.

The runtime skill (`asset-pipeline`) handles actual pipeline work
(generating assets, etc.). This skill only handles install + audit.

## Bootstrap flow (first install)

1. **Verify the catalog repo is cloned locally.** If not, offer to clone
   it to `~/dev/2d-3d-pipeline/`. The repo path is whatever the user
   confirms; track it as `$REPO`.
2. **Ask the user: laptop or studio tier?** Both run the same scripts;
   the difference is recorded in `~/3d-pipeline/.config`.
3. **Run prereqs check:**
   ```
   python3 $REPO/scripts/pipeline_doctor.py --check structure --json
   python3 $REPO/scripts/pipeline_doctor.py --apply --tier <tier> \
       --only prereqs --json
   ```
   If any prereq is missing, surface the `install_hint` and ask the user
   to install it themselves. Never run `brew install` automatically.
4. **Ask which optional feature_sets to include** beyond the tier default:
   `hunyuan3d-paint`, `comfyui`, `multiview`. Show disk + download
   estimates from the manifest.
5. **HF auth.** If any in-scope model has `requires_hf_auth: true`, run:
   ```
   huggingface-cli whoami
   ```
   If exit non-zero, walk the user through `huggingface-cli login`.
   The engine's `hf_preflight` will then verify per-repo access; if
   that surfaces a 401, point at the `request access at
   https://huggingface.co/<repo>` URL and pause.
6. **Confirm disk + download volume.** Show the output of
   `python3 $REPO/scripts/pipeline_doctor.py --check disk --json`.
   Ask before proceeding.
7. **Run the apply end-to-end:**
   ```
   python3 $REPO/scripts/pipeline_doctor.py --apply --tier <tier> --yes --json
   ```
   Stream output. On any stage failure, surface the engine's `fix_command`
   and suspected cause.

## Audit loop (rerun)

1. **`git fetch` in the catalog repo.** If `HEAD..origin/<branch>` has any
   commits, show the commit-range summary and **ask before fast-forwarding**:
   ```
   git -C $REPO log HEAD..origin/<branch> --oneline
   ```
   Never silent-pull. This is the trust-model mitigation (spec §7).
2. **Run drift detection:**
   ```
   python3 $REPO/scripts/pipeline_doctor.py --check installed --json
   ```
3. **Render the drift report grouped by stage.** Use the helper at
   `$REPO/setup-skill/scripts/audit_loop.py` to format the output:
   ```
   python3 $REPO/setup-skill/scripts/audit_loop.py < drift.json
   ```
4. **For each stage with drift, ask one multi-select prompt:**
   ```
   scripts/ — 4 items drifted
     [1] generate.sh
     [2] print.sh
     [3] turntable_render.py
     [4] mesh_quality_check.py

   Apply: (a) all  (b) selected (e.g. "1,3-4")  (s) skip
   >
   ```
   Worst case is one prompt per stage (≤8 prompts total).
5. **For each user choice, run the engine's `fix_command`.**

## Studio tier — extra checks

Before any `studio_extras` apply on a machine where SMB is mounted:

1. Verify the share is mounted (the user wires this).
2. Check the foreign-machine heartbeat:
   ```
   python3 -c "from scripts import pipeline_doctor as pd; \
     print(pd.is_heartbeat_alive(<queue_dir>, machine='<other>', max_age_seconds=90))"
   ```
3. If a foreign worker is alive, refuse to write the queue directory and
   ask the user to coordinate.

## What this skill is NOT

- Not a brew installer.
- Not a HuggingFace token manager (walks login, doesn't store credentials).
- Not an SMB mounter.
- Not a release manager.

## Tracked technical debt

The repo has separate `skill/` (runtime) and `setup-skill/` (this skill)
directories. v0.5 will consolidate to `skills/runtime/` and
`skills/setup/`. See `CONVENTIONS.md`.
```

Create `setup-skill/scripts/audit_loop.py` as a placeholder:

```python
#!/usr/bin/env python3
"""Format pipeline_doctor --check installed --json output for the audit loop.

Reads JSON on stdin, writes a stage-grouped punch list to stdout suitable for
the multi-select prompts described in setup-skill/SKILL.md §audit loop.

This is a thin helper — the skill itself drives the actual user interaction.
"""
from __future__ import annotations

import json
import sys


def format_report(report: dict) -> str:
    out: list[str] = []
    stages = (report.get("check_installed") or {}).get("stages") or {}
    for stage_name, stage_data in stages.items():
        drifted = []
        for key in ("scripts", "skill", "venvs", "models", "items"):
            for row in (stage_data.get(key) or []):
                if row.get("status") in ("drift", "missing", "partial"):
                    drifted.append(row)
        if not drifted:
            continue
        out.append(f"{stage_name}/ — {len(drifted)} item(s) drifted")
        for i, row in enumerate(drifted, start=1):
            name = row.get("name") or row.get("id") or "<unknown>"
            reason = row.get("reason") or row.get("current") or row["status"]
            out.append(f"  [{i}] {name} — {reason}")
        out.append("")
        out.append("Apply: (a) all  (b) selected (e.g. \"1,3-4\")  (s) skip")
        out.append("")
    if not out:
        out.append("In sync. No drift detected.")
    return "\n".join(out)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2
    print(format_report(data))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Make it executable: `chmod +x setup-skill/scripts/audit_loop.py`.

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/python/test_setup_skill_layout.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add setup-skill/ tests/python/test_setup_skill_layout.py
git commit -m "P5.1: setup-skill scaffold (SKILL.md + audit_loop.py helper)"
```

---

### Task 5.2: Test the audit-loop helper formatter

**Files:**
- Modify: `setup-skill/scripts/audit_loop.py` (no code changes, only tests)
- Create: `tests/python/test_audit_loop.py`

- [ ] **Step 1: Write tests**

Create `tests/python/test_audit_loop.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
HELPER = REPO / "setup-skill" / "scripts" / "audit_loop.py"


def _run(stdin_text: str):
    return subprocess.run(
        [sys.executable, str(HELPER)],
        input=stdin_text, capture_output=True, text=True,
    )


def test_empty_report_says_in_sync():
    payload = json.dumps({"check_installed": {"stages": {}}})
    r = _run(payload)
    assert r.returncode == 0
    assert "in sync" in r.stdout.lower()


def test_drifted_scripts_render_as_punch_list():
    payload = json.dumps({"check_installed": {"stages": {
        "scripts": {"status": "warning", "scripts": [
            {"name": "generate.sh", "status": "drift",
             "current": "byte-mismatch"},
            {"name": "print.sh", "status": "drift",
             "current": "byte-mismatch"},
        ]},
    }}})
    r = _run(payload)
    assert r.returncode == 0
    assert "scripts/ — 2 item(s) drifted" in r.stdout
    assert "[1] generate.sh" in r.stdout
    assert "[2] print.sh" in r.stdout
    assert "Apply:" in r.stdout


def test_multiple_stages_get_separate_blocks():
    payload = json.dumps({"check_installed": {"stages": {
        "scripts": {"status": "warning", "scripts": [
            {"name": "x", "status": "drift", "current": "?"},
        ]},
        "venvs": {"status": "warning", "venvs": [
            {"name": "mflux-env", "status": "drift", "reason": "missing"},
        ]},
    }}})
    r = _run(payload)
    # Each stage produces its own header
    assert "scripts/" in r.stdout
    assert "venvs/" in r.stdout


def test_invalid_json_exits_2():
    r = _run("not json")
    assert r.returncode == 2
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/python/test_audit_loop.py -v`
Expected: PASS (the helper already implements all of this from Task 5.1).

- [ ] **Step 3: Commit**

```bash
git add tests/python/test_audit_loop.py
git commit -m "P5.2: test coverage for audit_loop formatter helper"
```

---

### Task 5.3: Add "When to run setup" section to runtime SKILL.md

**Files:**
- Modify: `skill/SKILL.md`
- Modify: `tests/python/test_setup_skill_layout.py`

- [ ] **Step 1: Write a test that the runtime skill links to setup**

Append to `tests/python/test_setup_skill_layout.py`:

```python
def test_runtime_skill_mentions_setup_skill():
    runtime = (REPO / "skill" / "SKILL.md").read_text()
    assert "asset-pipeline-setup" in runtime
    assert "When to run setup" in runtime or "When to run the setup" in runtime
```

- [ ] **Step 2: Run failing**

Run: `python3 -m pytest tests/python/test_setup_skill_layout.py::test_runtime_skill_mentions_setup_skill -v`
Expected: FAIL.

- [ ] **Step 3: Read the current runtime SKILL.md**

Read `skill/SKILL.md` to find a good insertion point — typically right after the title/intro, before the first usage section.

- [ ] **Step 4: Add the section**

In `skill/SKILL.md`, insert (after the introduction, before any usage instructions):

```markdown
## When to run setup

For installing the pipeline on a fresh Mac, auditing an existing install
for drift against the repo catalog, or reconciling after the repo gains
new scripts/models/venvs, invoke the **`asset-pipeline-setup`** skill
instead of working with this one. That skill handles:

- First-machine bootstrap (tier choice, HF auth, optional feature_sets)
- Audit loop (`git pull` → `pipeline_doctor.py --check installed` → multi-select fixes)
- Studio-tier extras (queue dirs, opt-in launchd plist, foreign-worker heartbeat check)

This skill (`asset-pipeline`) only handles pipeline work itself.
```

- [ ] **Step 5: Regenerate HTML embeds (runtime skill is in EMBEDS)**

Run: `make regenerate && make verify`

- [ ] **Step 6: Run tests**

Run: `python3 -m pytest tests/python/test_setup_skill_layout.py -v`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add skill/SKILL.md tests/python/test_setup_skill_layout.py docs/asset-pipeline-guide.html docs/asset-pipeline-guide-studio.html
git commit -m "P5.3: runtime skill links to asset-pipeline-setup"
```

---

### Task 5.4: Create `docs/setup-via-claude.md`

**Files:**
- Create: `docs/setup-via-claude.md`

- [ ] **Step 1: Write the doc**

Create `docs/setup-via-claude.md`:

```markdown
# Setup via Claude Code

A walkthrough of installing the pipeline on a fresh Mac (laptop or studio
tier) using the `asset-pipeline-setup` Claude Code skill. The alternative
copy-paste install via [`asset-pipeline-guide.html`](asset-pipeline-guide.html)
remains supported.

## Prerequisites

The skill verifies these but won't install them. On a fresh machine,
install in this order:

- **Homebrew** (`https://brew.sh`)
- **Python 3.12** (`brew install python@3.12`)
- **git** (ships with Xcode Command Line Tools; `xcode-select --install`)
- **huggingface-cli** (`pip install huggingface_hub[cli]`)
- **pip ≥ 23.1** (`python3 -m pip install --upgrade pip`)

## First install

Clone the catalog repo somewhere stable:

```sh
git clone https://github.com/<user>/2d-3d-pipeline ~/dev/2d-3d-pipeline
cd ~/dev/2d-3d-pipeline
```

In Claude Code, invoke the setup skill:

> Run the asset-pipeline-setup skill.

The skill will:

1. Confirm the repo path.
2. Ask whether this machine is **laptop** or **studio** tier.
3. Run `pipeline_doctor.py --apply --only prereqs` and surface any
   missing binaries.
4. Ask which optional feature_sets to include
   (`hunyuan3d-paint`, `comfyui`, `multiview`).
5. If any selected model requires HuggingFace authentication, walk
   you through `huggingface-cli login` and verify per-repo access.
6. Show disk + download estimates; ask before proceeding.
7. Run `pipeline_doctor.py --apply --tier <tier> --yes` end-to-end.

Typical bootstrap time on a laptop with broadband: ~15–30 minutes
plus model downloads.

## Audit / re-sync after repo updates

When the catalog repo gains new scripts, models, or venvs, re-invoke the
setup skill on each deployed machine:

> Run the asset-pipeline-setup audit loop.

The skill will:

1. `git fetch` the catalog repo; show the commit range and **ask
   before pulling** (no silent fast-forward).
2. Run `pipeline_doctor.py --check installed --json` against the
   freshly pulled catalog.
3. Render a stage-grouped drift report. For each stage with drift,
   ask one multi-select prompt (`a` for all, comma ranges, or `s`
   to skip the stage). Worst case is one prompt per stage (≤8).
4. For each user choice, run the engine's suggested `fix_command`.

## Studio tier — multi-machine specifics

The studio tier supports two machines sharing an SMB-mounted workspace.
Before the skill applies the `studio_extras` stage:

- The shared store must be mounted. The skill verifies the mount; it
  does not mount it for you.
- If a worker is running on the *other* studio (heartbeat in
  `<workspace>/queue/.heartbeat-<machine>` younger than 90 seconds),
  the skill refuses to touch the shared queue directory until you
  confirm.
- The launchd plist for auto-starting the worker is **opt-in**.
  Declining is sticky — the audit loop won't re-prompt until you run
  `pipeline_doctor.py --apply --only studio_extras --reconsider-optionals`.

## Troubleshooting

Most failures surface a `fix_command` from the engine. Re-run that
command and re-invoke the audit loop. Common cases:

- **Wheel build failure on Apple Silicon** (torch/onnxruntime): the
  engine auto-retries after `pip install --upgrade pip setuptools wheel`.
  If the second attempt also fails, the engine prints the failing
  package; install it manually from the venv and re-run.
- **HuggingFace 401 on a gated repo:** the engine names the repo and
  the access URL. Click through, request access, then re-run.
- **Killed download:** HF downloads use `huggingface_hub` native resume;
  direct-URL downloads use a `.part` file with `Range:` headers.
  Re-running `--apply --only models` continues from the byte offset.

For non-Claude installs, the [HTML guide](asset-pipeline-guide.html)
remains the canonical copy-paste fallback. Both consume the same catalog.
```

- [ ] **Step 2: Commit**

```bash
git add docs/setup-via-claude.md
git commit -m "P5.4: docs/setup-via-claude.md (single doc; tier handled at runtime)"
```

---

### Task 5.5: Add v0.4 delta entries to UPGRADES docs

**Files:**
- Modify: `docs/UPGRADES-laptop.md`
- Modify: `docs/UPGRADES-studio.md`

- [ ] **Step 1: Add to `UPGRADES-laptop.md`**

Read the file to find the latest version section. Add a new section near the top (after the v0.3 / v0.2 framing block):

```markdown
## v0.4 — Claude-Code-driven setup + audit/fix loop

A new `asset-pipeline-setup` Claude Code skill drives install and
drift-detection workflows from the catalog repo. The existing
copy-paste [`asset-pipeline-guide.html`](asset-pipeline-guide.html)
remains supported.

What's new (laptop tier):

- `pipeline_doctor.py` gains `--apply`, `--check installed`, and
  `--only STAGE` flags. Same code drives install and audit; same
  catalog drives both.
- Manifest schema bumps to v2 with a strict additive contract.
  Existing deployed manifests keep working.
- Venvs install from committed `pip freeze` lockfiles
  (`scripts/lockfiles/`), making `--apply` reproducible across runs.
- Models download with resume support — HuggingFace via
  `huggingface_hub.hf_hub_download`, direct URLs via `Range:` headers.
- New `docs/setup-via-claude.md` documents the Claude-driven flow.

What's deliberately unchanged:

- 2D default still Z-Image Turbo, 3D default still SF3D.
- The HTML guide still works as a manual install path.
- All v0.3 quality-check scripts are still invoked the same way.

Last updated: 2026-05-21
```

- [ ] **Step 2: Add to `UPGRADES-studio.md`**

Mirror the laptop entry, plus the studio-only additions:

```markdown
## v0.4 — Claude-Code-driven setup + audit/fix loop

Same as laptop tier (`asset-pipeline-setup` skill, `--apply`, lockfile-driven
venvs, resumable downloads). Studio-only additions:

- New `studio_extras` apply stage creates the queue directory tree and
  offers an opt-in launchd plist for auto-starting the worker.
- `queue_worker.py` now writes a heartbeat to
  `queue/.heartbeat-<machine>` every poll cycle. The setup skill
  uses this heartbeat (not the existing `mtime`-based stuck-job
  reclaim) to decide whether a foreign worker is alive before
  touching the shared queue.
- Heartbeat write uses a local-tmp + atomic-rename + watchdog timeout
  protocol so a slow SMB connection can't cause false-dead
  conclusions on the other machine.

Last updated: 2026-05-21
```

- [ ] **Step 3: Commit**

```bash
git add docs/UPGRADES-laptop.md docs/UPGRADES-studio.md
git commit -m "P5.5: v0.4 delta entries in tier UPGRADES docs"
```

---

### Task 5.6: Document the `setup-skill/` exception in CONVENTIONS.md

**Files:**
- Modify: `CONVENTIONS.md`

- [ ] **Step 1: Read the existing CONVENTIONS.md skill section**

Read `CONVENTIONS.md` around line 110 (per-tier docs table). The skill convention currently states `skill/` is singular.

- [ ] **Step 2: Add a new section near the bottom**

Append to `CONVENTIONS.md`:

```markdown
## Setup skill (v0.4) — naming exception

In addition to the runtime skill at `skill/` (singular), v0.4 adds a
second one-shot setup skill at `setup-skill/` deployed to
`~/.claude/skills/asset-pipeline-setup/`. The two have different
lifecycles — the runtime skill is hot-loaded constantly during
pipeline work; the setup skill runs rarely (install + audit). Sharing
a single repo directory would conflate the two.

This is a **soft exception** to the singular-`skill/` convention.
Tracked technical debt: v0.5 will consolidate to
`skills/runtime/` and `skills/setup/`, updating `EMBEDS` and the
HTML embed regenerator at the same time. Until then, both
directories coexist; the exception is documented here so it doesn't
quietly become a precedent.

`setup-skill/` is **not** in `EMBEDS`. The setup skill ships via
the repo clone alone — Claude-driven installs pull it directly.
This is enforced by `pipeline_doctor.py --check structure` (rule
`v2:embeds-partition`).
```

- [ ] **Step 3: Commit**

```bash
git add CONVENTIONS.md
git commit -m "P5.6: document setup-skill/ exception + v0.5 tracked debt"
```

---

### Task 5.7: Clean stale `--fix` references in improvement-spec.md

**Files:**
- Modify: `docs/improvement-spec.md`

- [ ] **Step 1: Grep for `--fix`**

Run:
```bash
grep -n -- "--fix" docs/improvement-spec.md
```

Expected: lines 986, 1013, 1099, 1129 (or thereabouts) reference
`pipeline_doctor.py --fix`.

- [ ] **Step 2: Replace each with `--apply`**

For each reference, replace `--fix` with `--apply` in context. The
semantics are equivalent (the alias forwards), but new docs should
use the canonical name.

Do not blindly `sed` — read each line in context to make sure the
replacement makes sense. Some references may be in code blocks
showing the historical CLI; if so, add a parenthetical:
`--fix (deprecated alias; use --apply)`.

- [ ] **Step 3: Verify**

Run:
```bash
grep -n -- "--fix" docs/improvement-spec.md
```

Expected: any remaining references are explicit deprecation mentions.

- [ ] **Step 4: Commit**

```bash
git add docs/improvement-spec.md
git commit -m "P5.7: docs cleanup — stale --fix references → --apply"
```

---

### Task 5.8: Wire the v2 structure check into the existing CI workflow (no-op)

The spec asserts that the existing `.github/workflows/pipeline-doctor.yml`
needs **no changes** — the new v2 rules ride the existing
`--check structure --json` invocation. This task verifies that and
documents it.

**Files:**
- Modify: `docs/spec-pipeline-doctor-ci.md` (add v0.4 note)

- [ ] **Step 1: Smoke the CI workflow locally**

Read `.github/workflows/pipeline-doctor.yml`. It runs:
```
python3 scripts/pipeline_doctor.py --check structure --json
python3 scripts/pipeline_doctor.py --check wrappers --json
```

Run both locally:
```bash
python3 scripts/pipeline_doctor.py --check structure --json | python3 -m json.tool | head -40
python3 scripts/pipeline_doctor.py --check wrappers --json | python3 -m json.tool | head -40
```

Expected: structure exits 0 with every v2 rule reporting `ok`. Wrappers exits 0.

- [ ] **Step 2: Add a v0.4 note to the CI spec**

In `docs/spec-pipeline-doctor-ci.md`, append a "v0.4 update" section:

```markdown
## v0.4 — additional structure rules

The pipeline-doctor structure check gained ten v2-gated rules
(named `v2:*`) covering: schema version, tier_defaults, prereqs,
mutable_embed_paths, model storage_layout/comfyui_kind/hf_auth,
venv python_version/lockfile, studio_extras heartbeat math, and
EMBEDS_SCRIPTS/EMBEDS_SKILL partition.

The CI workflow file is **unchanged**. The new rules execute as part
of the existing `--check structure` invocation; if a future v1
manifest is encountered (e.g. a long-lived branch), the v2 rules
silently skip via `schema_version >= 2` gating, so v1 PRs still pass.

Reference: `docs/spec-claude-driven-setup.md` rev 3 (§3, §1.1).
```

- [ ] **Step 3: Commit**

```bash
git add docs/spec-pipeline-doctor-ci.md
git commit -m "P5.8: document v0.4 additions to pipeline-doctor CI structure check"
```

---

### Phase 5 self-check + acceptance test pass

Run the full suite:

```bash
python3 -m pytest tests/python -v
./tools/test_meta_helper.sh
./tools/test_update_manifest_meta.sh
make verify
python3 scripts/pipeline_doctor.py --check structure --json | python3 -m json.tool | head -40
```

Expected: all tests pass; structure check is clean; HTML embeds verified.

End-to-end smoke against a tmpdir:

```bash
PIPELINE_ROOT=/tmp/p-final python3 scripts/pipeline_doctor.py \
    --apply --tier studio --only prereqs,dirs,config,scripts,skill,studio_extras --yes
PIPELINE_ROOT=/tmp/p-final python3 scripts/pipeline_doctor.py \
    --check installed --tier studio --json | \
    python3 setup-skill/scripts/audit_loop.py
```

Expected: stages complete; check_installed reports "In sync" or only T0 advisory items.

---

## Acceptance criteria → tasks map

Cross-check from spec §11 ACs to plan tasks:

| AC | Implemented by |
| --- | --- |
| AC1 — scripts idempotency | Task 2.6 |
| AC2 — bytes-exact drift | Task 2.6 |
| AC3 — venv lockfile cross-Python drift | Tasks 3.2, 3.4 |
| AC4 — HF preflight per-repo | Task 3.5 |
| AC5 — stage prerequisite enforcement | Task 2.9 |
| AC6 — smoke-warm verification | Task 3.8 |
| AC7 — partial venv handling | Task 3.3 |
| AC8 — studio extras opt-out is sticky | Tasks 2.2 + 4.1 |
| AC9 — multi-select UX prompt count | Tasks 5.1, 5.2 |
| AC9b — per-stage skip doesn't abort | Tasks 5.1, 5.2 |
| AC10 — heartbeat liveness, unit-tested | Tasks 4.2, 4.3 |
| AC11 — CI v2 schema validation | Tasks 1.3–1.9, 5.8 |
| AC12 — zero-engine-code-for-new-model (scoped) | Task 3.7 |
| AC13 — cold-start contract | Task 2.9 |
| AC14 — concurrent-apply lock + network-FS refusal | Task 2.3 |
| AC15 — EMBEDS partition invariant | Task 1.9 |
| AC16 — resumable HF download | Task 3.6 |
| AC17 — git-pull commit-range gate | Task 5.1 (skill content) |

Every AC has at least one task. AC17 is documented in `SKILL.md`
content rather than tested in pytest because it's a skill-flow
behaviour, not an engine call. The setup skill's content explicitly
mandates the gate; verification is via review of `setup-skill/SKILL.md`.

---

## Final notes

- **Frequent commits.** Every task ends in a commit. If a step
  fails, fix and re-run before moving on; don't accumulate
  uncommitted work.
- **Skip-and-revisit.** If a task's tests prove harder than expected
  (e.g. mocking `subprocess.run` on a specific code path), mark the
  task in-progress and move to the next; come back with fresh eyes.
- **CI gating.** Phase 1 commits should already trip the existing
  pipeline-doctor CI workflow. Watch for v2 schema validation
  failures on push and fix locally before re-pushing.
- **Pytest install.** If a fresh agent picks this up and `pytest` is
  missing, run `python3 -m pip install --user pytest pytest-mock
  huggingface_hub requests` and re-attempt.
