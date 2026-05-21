# Implementation Plan — Pipeline-doctor in CI (Q5)

**Spec:** [`docs/spec-pipeline-doctor-ci.md`](spec-pipeline-doctor-ci.md)
(rev 2, MMR-clean) · **Branch:** `q5-doctor-ci` (new) · **Target:**
single PR into `main` · 2026-05-20

## Decisions to confirm before Task 1

The spec's three open questions need answers before implementation.
Recommended choices baked into this plan:

| # | Question | Plan assumes |
|---|---|---|
| 1 | Allow-list location | **In `model_manifest.json` as `internal_scripts: []`** (spec recommendation; manifest stays single source of truth) |
| 2 | Nightly scheduled run | **Skip** (spec recommendation; revisit if we hit the case) |
| 3 | SKILL.md linting in doctor | **Skip** (spec recommendation; `make verify` already covers this) |

If any of these flip, only Task 3 and Task 6 are affected — small
blast radius.

## Task list

Each task is sized to fit one focused edit pass (≤200 LOC touched,
single file or tightly-scoped pair). All tasks include their own
verification step so failures surface immediately.

### Phase 1 — Foundations

**Task 1: Branch + workspace stub.** Create `q5-doctor-ci` branch
off `main`. Add `internal_scripts: ["_pipeline_lib.sh",
"migrate_assets.sh", "multiview.sh"]` to `scripts/model_manifest.json`
as a new top-level array, alongside `wrappers`. Update the manifest's
top-level `description` field to add "Structurally validated in CI
on PRs touching scripts/ or tools/_embed_lib.py."
*Verify:* `python -c "import json; m=json.load(open('scripts/model_manifest.json')); assert m['internal_scripts'] and 'CI' in m['description']"`
*Files:* `scripts/model_manifest.json` (~5 lines).

**Task 2: `check_structure()` skeleton.** Add a no-op
`check_structure(manifest)` function to `scripts/pipeline_doctor.py`
returning `{"status": "ok", "checks": []}`. Add `"structure"` to the
`--check` argparse choices. Wire it into `main()` alongside the
existing check dispatchers so `--check structure` runs the new
function.
*Verify:* `python scripts/pipeline_doctor.py --check structure --json` exits 0 with valid JSON containing `"status": "ok"`.
*Files:* `scripts/pipeline_doctor.py` (~15 lines).

### Phase 2 — Structure check rules (one rule per task)

Each of the next five tasks adds one rule to `check_structure()`. Each
rule appends a dict to `report["checks"]` (`{"name": ..., "status":
"ok"|"critical", "details": ...}`) and elevates `report["status"]` to
`"critical"` on failure. Order matters only for the smoke test in
Task 8.

**Task 3: Rule — EMBEDS files exist.** Import `EMBEDS` from
`tools._embed_lib`, walk each entry's source path, assert it exists
on disk relative to repo root. One check entry per missing file.
*Verify:* Run on a known-good repo state → status ok. Temporarily
add a fake EMBEDS entry pointing at `/nonexistent`, rerun, confirm
critical.
*Files:* `scripts/pipeline_doctor.py` (~15 lines).

**Task 4: Rule — venvs reference valid feature_sets.** For each
entry in `manifest["venvs"]`, assert `entry["feature_set"]` is a key
in `manifest["feature_sets"]`.
*Verify:* Run → ok. Temporarily set a venv's `feature_set` to
`"bogus"`, rerun, confirm critical.
*Files:* `scripts/pipeline_doctor.py` (~10 lines).

**Task 5: Rule — models reference valid feature_sets + have a
venv.** For each model, assert `feature_set` exists in
`feature_sets`, and that at least one venv shares the same
feature_set.
*Verify:* Run → ok. Temporarily move `u2net.feature_set` to
`"hunyuan3d-paint"` (which has its own venv) → ok. Set to a
made-up feature_set → critical.
*Files:* `scripts/pipeline_doctor.py` (~12 lines).

**Task 6: Rule — wrappers list ↔ scripts/ parity.** Build the set
of `scripts/*.sh` files (basenames). For each entry in
`manifest["wrappers"]`, assert the file exists in `scripts/` and is
executable (`os.access(p, os.X_OK)`). For each `scripts/*.sh` file,
assert it appears in `wrappers` OR in `internal_scripts` (Task 1).
*Verify:* Run → ok against current repo. Temporarily `chmod -x
scripts/concept.sh` → critical; restore. Add a fake
`scripts/zz_demo.sh` not in either list → critical; remove.
*Files:* `scripts/pipeline_doctor.py` (~20 lines).

**Task 7: Human-readable formatting for structure check.** Extend
`_print_human()` so `--check structure` (no `--json`) prints a
readable summary of each rule's outcome, matching the style of the
existing checks. Emoji-prefix per-row; one section header.
*Verify:* `python scripts/pipeline_doctor.py --check structure` (no
JSON) prints a human-readable block.
*Files:* `scripts/pipeline_doctor.py` (~15 lines).

### Phase 3 — CI workflow

**Task 8: End-to-end local smoke test.** Before writing the
workflow, validate the full doctor invocation locally exactly as CI
will. Run:
1. `mkdir -p /tmp/q5-ws/workspace && for f in scripts/*.sh; do ln -s "$PWD/$f" /tmp/q5-ws/workspace/; done`
2. `PIPELINE_ROOT=/tmp/q5-ws python scripts/pipeline_doctor.py --check structure --json` → exit 0
3. `PIPELINE_ROOT=/tmp/q5-ws python scripts/pipeline_doctor.py --check wrappers --json` → exit 0
4. Temporarily break `scripts/concept.sh` (add `exit 1` at top of
   `--help` branch), re-run wrappers check, parse JSON, confirm a
   non-ok row appears. Restore.
*Verify:* All four steps behave as expected. Cleanup `/tmp/q5-ws`.
*Files:* none (smoke run only).

**Task 9: Write the workflow file.** Create
`.github/workflows/pipeline-doctor.yml` verbatim from the spec
(rev 2, lines 109–209). Do not improvise — the spec's YAML is the
MMR-reviewed contract.
*Verify:* `python -c "import yaml; yaml.safe_load(open('.github/workflows/pipeline-doctor.yml'))"` parses without error. If `pyyaml` not installed, use `python -c "import json,subprocess; subprocess.check_call(['gh','workflow','view','--yaml','pipeline-doctor.yml'])"` after pushing, or skip and rely on GH Actions to surface YAML syntax errors on first push.
*Files:* `.github/workflows/pipeline-doctor.yml` (~70 lines).

### Phase 4 — Docs + ship

**Task 10: Update CONVENTIONS.md.** Add a short paragraph in
the existing "CI / verification" area (or create one if absent)
naming the workflow, what it checks, and what to do when it fails.
≤8 lines.
*Verify:* Read updated `CONVENTIONS.md` — paragraph is present,
links to the workflow file path and the spec.
*Files:* `CONVENTIONS.md` (~8 lines).

**Task 11: CHANGELOG entry.** Add a bullet under an `Unreleased`
or new minor-version section describing the doctor's new
`--check structure` subcheck and the CI workflow.
*Verify:* `git diff CHANGELOG.md` shows a single added bullet
under the right header.
*Files:* `CHANGELOG.md` (~3 lines).

**Task 12: Open PR + watch first CI run.** Push branch, open PR
against `main`. Watch the first run of `pipeline-doctor.yml` —
confirm both checks pass and a PR comment is posted with the JSON
reports. If the comment doesn't appear, check the permissions /
`always()` gate before merging.
*Verify:* CI green; PR comment present with `structure.json` and
`wrappers.json` blocks. Self-merge if good; otherwise file
follow-up tasks.
*Files:* none (operational).

## Total estimate

| Phase | Tasks | Time |
|---|---|---|
| 1 — Foundations | 1, 2 | ~30 min |
| 2 — Structure rules | 3–7 | ~90 min |
| 3 — CI workflow | 8, 9 | ~60 min |
| 4 — Docs + ship | 10–12 | ~45 min (+ CI wait) |
| **Total active work** | | **~3.75 hours** |

(Slightly above the spec's 3.25h estimate because Phase 2 is broken
into five separately-verified tasks; trade-off is much safer
incremental progress.)

## Rollback

Every task is a single small commit on a feature branch. To roll
back, `git revert <sha>` for the offending task; later tasks don't
depend on earlier ones touching the same file in ways that conflict.

The workflow file is the only thing that affects shared
infrastructure (GitHub Actions); if it misbehaves after merge,
deleting the file in a follow-up PR is sufficient — no migration
needed.

## Pre-flight checklist (before starting Task 1)

- [ ] Spec is approved (Q5 green-lit by user)
- [ ] Decisions table at top of this plan reflects the chosen
      answers for the spec's three open questions
- [ ] Working tree clean
- [ ] On `main`, up-to-date with `origin/main`
