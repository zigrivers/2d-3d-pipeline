# Spec — Pipeline-doctor in CI

**Status:** draft for review · **Q5 from `docs/improvement-spec.md`
"Open questions"** · 2026-05-20

## What this is

A proposal to run `scripts/pipeline_doctor.py` in CI on pull
requests + pushes that touch the canonical scripts or model
manifest. The goal is to catch the easiest-to-miss class of bug
the doctor was designed to surface — stale `model_manifest.json`
entries, missing venv references, wrappers whose `--help` broke
recently — before a release goes out, not after a user reports it.

## Why bother

Today the doctor is a manual-run tool. Two failure modes nothing in
CI catches:

1. **Stale `model_manifest.json`.** Someone adds a new model to a
   wrapper (e.g. a new generator), forgets to add the model to the
   manifest. Pipeline-doctor's `--check models` would fail; CI
   today wouldn't.
2. **Drift between EMBEDS map and model_manifest.** A new script
   gets embedded but isn't surfaced in pipeline-doctor's venv /
   wrapper checks. Same shape of problem.
3. **Wrapper `--help` regressions.** A bash syntax error or stale
   arg parser slips past local testing and into a release.

The doctor's `--check wrappers` runs `<script> --help` and checks
the exit code. Trivial to run in CI; catches regressions early.

## What this proposal does NOT do

- **Does not install models in CI.** Downloads are gigabytes and
  CI runners can't host them sensibly. `--check models` instead
  treats every model as "absent" in CI and just validates the
  *manifest's structure* (no entries pointing at impossible paths,
  no entries for files that don't have a corresponding wrapper or
  EMBEDS entry).
- **Does not gate releases.** PRs can land with doctor warnings;
  warnings surface as inline PR comments via the existing GH
  Actions setup, not as failures. The goal is visibility, not
  enforcement.
- **Does not change the doctor's CLI.** Existing flags are enough;
  we run with `--check {wrappers,structure} --json` and parse the
  output in the workflow.

## What changes

### 1. New `--check structure` subcheck

Add a `structure` choice to `pipeline_doctor.py --check`. Validates
the **catalog itself** rather than the runtime state:

- Every file in `tools/_embed_lib.py::EMBEDS` exists on disk.
- Every model in `model_manifest.json` has a sensible feature_set
  (one of the declared sets).
- Every venv referenced by a model points at a venv declared in
  `model_manifest.json::venvs`.
- The wrappers list in `model_manifest.json::wrappers` matches the
  set of `.sh` files under `scripts/` (allowing exceptions for
  intentionally-internal scripts like `_pipeline_lib.sh`).

This subcheck is the one that CI actually exercises — it runs
without any models or venvs being present.

### 2. New `.github/workflows/pipeline-doctor.yml`

Triggers:
- Pull requests touching `scripts/**`, `skill/**`, or
  `tools/_embed_lib.py`.
- Pushes to `main` for the same paths.

Steps:
1. Check out repo
2. Set up Python 3.12 (no pip installs needed — `pipeline_doctor.py`
   is stdlib-only for structure + wrappers checks)
3. Run `pipeline_doctor.py --check structure --json` — fail the job
   if exit code = 1 (critical structural problem)
4. Run `pipeline_doctor.py --check wrappers --json` — fail on
   exit code = 1
5. On warning (exit 0 with non-empty notes), post the JSON output
   as a PR comment via `actions/github-script`. Doesn't fail the
   build, but the comment makes drift visible at review time.

Approx workflow length: 30 lines of YAML.

### 3. Documentation

- Mention the CI workflow in `CONVENTIONS.md` so new contributors
  know it'll catch model-manifest drift.
- Add a sentence to `model_manifest.json`'s top-level
  `_schema_note` explaining "this file is structurally validated
  in CI".

## What this catches

- Adding a new wrapper to `/scripts/` without adding it to
  `model_manifest.json::wrappers` → CI fails on `--check structure`.
- Adding a model to `model_manifest.json` referencing a venv that
  doesn't exist in the same file → fails on `--check structure`.
- A bash syntax error in any `.sh` wrapper that breaks `--help` →
  fails on `--check wrappers`.
- Removing a file from `/scripts/` without removing its EMBEDS
  entry → fails on `--check structure`.

## What this doesn't catch

- Anything that requires a model or venv actually being present.
  The doctor's `disk` / `models` / `venvs` checks need a real
  install and CI doesn't have one. That's fine — the manual run on
  developer machines covers it.
- Bugs in the model inference itself. The wrappers run; whether
  the models do the right thing is a different test (the
  benchmark harness in `tests/multiview-bench/`).

## Trade-offs

- **Pro:** zero extra dependencies; structure check runs in seconds;
  catches a real class of drift bug.
- **Pro:** stays out of the critical path — warnings comment on PRs,
  don't block.
- **Con:** small surface increase — one more thing to keep working.
  Trivially mitigated since the structure check is pure-Python
  stdlib and lives in the same repo as the script it validates.
- **Con:** the `--check structure` subcheck doesn't exist yet;
  shipping CI requires writing it first. Small (~50 LOC).

## Effort

| Item | Estimate |
|---|---|
| Implement `--check structure` in `pipeline_doctor.py` | ~1 hour |
| Write `.github/workflows/pipeline-doctor.yml` | ~30 min |
| Update `CONVENTIONS.md` + `model_manifest.json` notes | ~15 min |
| Smoke-test on this branch + an intentionally-broken branch | ~30 min |
| **Total** | **~2.5 hours** |

## Open questions for review

1. **Should the workflow fail or warn on `--check wrappers`
   regressions?** I'd argue fail — a wrapper whose `--help` exits
   non-zero is a real bug that should block the merge. But that
   means tighter loop on contributors. (My recommendation: fail.)
2. **Should we run the doctor on a schedule too** (e.g., nightly
   `cron`) to catch issues where the manifest references a model
   whose download URL silently changed upstream? Cheap; might be
   over-engineering today. (My recommendation: skip until we hit
   the case once.)
3. **PR comment format** — single comment with the full JSON, or
   one comment per finding? Single is less noisy. (My
   recommendation: single comment, collapsed `<details>` block.)

---

Awaiting your review before implementing. Quick green-light or
ask for changes; once approved I'll ship the `--check structure`
subcheck + the workflow file as a small follow-up PR.
