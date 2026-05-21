# Spec — Pipeline-doctor in CI

**Status:** draft for review (rev 2 — MMR findings applied) ·
**Q5 from `docs/improvement-spec.md` "Open questions"** · 2026-05-20

## What this is

A proposal to run `scripts/pipeline_doctor.py` in CI on pull
requests + pushes that touch the canonical scripts or model
manifest. The goal is to catch the easiest-to-miss class of bug
the doctor was designed to surface — manifest drift, structural
breakage of the script catalog, wrappers whose `--help` exits
non-zero — before a release goes out, not after a user reports it.

## Why bother

Today the doctor is a manual-run tool. Three failure modes nothing
in CI catches:

1. **Drift between `scripts/` and `model_manifest.json::wrappers`.**
   Someone adds a new user-facing wrapper, forgets to register it
   in the manifest. The doctor's `--check wrappers` only iterates
   what the manifest declares, so it silently skips the new
   wrapper today. The new `--check structure` step (below) closes
   this gap by validating in both directions.
2. **Internal manifest inconsistency.** A new feature_set is
   declared but no venv or model points at it; a venv references a
   feature_set that doesn't exist; an EMBEDS entry points at a
   file that's been deleted.
3. **Wrapper `--help` regressions.** A bash syntax error or stale
   arg parser slips past local testing and into a release. The
   doctor's existing `--check wrappers` catches this, but only
   when run.

## What this proposal does NOT do

- **Does not install models in CI.** Downloads are gigabytes and
  CI runners can't host them sensibly. `--check models` and
  `--check disk` are skipped in CI entirely.
- **Does not detect "wrapper uses a generator/model that isn't in
  the manifest".** That would require parsing every wrapper's
  generator-selection logic, which the current doctor doesn't do
  and which is out of scope for this proposal. Limited to internal
  manifest + EMBEDS consistency.
- **Does not gate releases (for non-wrapper warnings).** A failure
  on `--check structure` (critical) blocks the PR. A non-`ok`
  wrapper status — missing or `--help`-broken — also blocks the
  PR; even though the doctor itself reports those as `warning`
  and exits 0, the CI workflow parses the JSON and fails the job.
  We chose the strict gate because a wrapper whose `--help` exits
  non-zero is a real bug; see "Trade-offs" below. Other
  `warning`-level findings (none today, but room for future
  subchecks) would surface only as a PR comment.
- **Does not change the doctor's existing CLI surface for `disk`,
  `venvs`, `models`, `wrappers`.** Existing exit-code semantics
  stay (`warning` → 0, `critical` → 1) so as not to break local
  invocations. CI parses `--json` output to enforce stricter gates
  instead of relying solely on exit codes (see workflow below).

## What changes

### 1. New `--check structure` subcheck in `pipeline_doctor.py`

Add `structure` to the `--check` choices. Validates the **catalog
itself** rather than the runtime install state — runs without
any models, venvs, or workspace symlink being present:

- Every file in `tools/_embed_lib.py::EMBEDS` exists at the
  declared source path on disk.
- Every venv in `model_manifest.json::venvs` has a `feature_set`
  that exists in `feature_sets`.
- Every model in `model_manifest.json::models` has a `feature_set`
  that exists in `feature_sets`, and at least one venv exists for
  the same feature_set (so the model has somewhere to run from).
- Every entry in `model_manifest.json::wrappers` exists as a file
  in `scripts/` and is executable.
- Every `scripts/*.sh` file is **either** declared in
  `model_manifest.json::wrappers` **or** appears in a hard-coded
  allow-list of intentionally-internal scripts (current
  exceptions: `_pipeline_lib.sh`, `migrate_assets.sh`,
  `multiview.sh`). The allow-list lives in
  `pipeline_doctor.py` next to the check so adding a new
  internal script is an obvious one-line change.
- The doctor returns the structure result with `status:
  "critical"` if any check fails (mapping to exit code 1, so CI's
  default behavior fails the job).

Pure-stdlib. Roughly 60 LOC including the allow-list and
human-readable formatting.

### 2. CI runs the doctor against the repo, not an install

The existing `check_wrappers()` resolves wrapper paths via
`PIPELINE_ROOT / "workspace"`, which doesn't exist on a fresh CI
runner. Two options; we use option A:

- **(A — chosen) Stage a workspace in the runner.** The workflow
  creates `$RUNNER_TEMP/workspace` (matches the path
  `check_wrappers()` resolves: `PIPELINE_ROOT / "workspace"`),
  symlinks every `scripts/*.sh` into it, then runs the doctor
  with `PIPELINE_ROOT=$RUNNER_TEMP`. No doctor change required;
  preserves the existing semantics for local users.
- (B — rejected for now) Add a `--workspace PATH` flag to the
  doctor so CI can point straight at `./scripts`. Cleaner, but
  bigger surface change; revisit if multiple call sites need it.

### 3. New `.github/workflows/pipeline-doctor.yml`

```yaml
name: pipeline-doctor

on:
  pull_request:
    paths:
      - 'scripts/**'
      - 'tools/_embed_lib.py'
  push:
    branches: [main]
    paths:
      - 'scripts/**'
      - 'tools/_embed_lib.py'

permissions:
  contents: read
  pull-requests: write   # for the warning comment below

jobs:
  doctor:
    runs-on: ubuntu-latest
    defaults:
      run:
        # pipefail so `... | tee` propagates the doctor's exit code
        # instead of masking it with tee's (always-zero) status.
        shell: bash -euo pipefail {0}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }

      - name: Stage workspace
        run: |
          mkdir -p "$RUNNER_TEMP/workspace"
          for f in scripts/*.sh; do
            ln -s "$PWD/$f" "$RUNNER_TEMP/workspace/$(basename "$f")"
          done
          echo "PIPELINE_ROOT=$RUNNER_TEMP" >> "$GITHUB_ENV"

      - name: Structure check (fail on critical)
        run: |
          python scripts/pipeline_doctor.py --check structure --json \
            | tee structure.json
          # pipefail (see defaults.run.shell) ensures doctor's
          # exit code propagates: critical → exit 1 → step fails.

      - name: Wrapper check (fail on any non-ok)
        run: |
          python scripts/pipeline_doctor.py --check wrappers --json \
            | tee wrappers.json
          # Existing exit-code semantics map warning→0. We want
          # stricter gating in CI: parse JSON and fail on any
          # wrapper whose status != "ok". The doctor emits
          # report["wrappers"] = {"status": ..., "wrappers": [rows]}.
          # Heredoc (rather than `python -c "..."`) keeps the
          # Python source flush-left regardless of YAML indent.
          python - <<'PY'
          import json, sys
          d = json.load(open('wrappers.json'))
          rows = d.get('wrappers', {}).get('wrappers', [])
          bad = [w for w in rows if w.get('status') != 'ok']
          if bad:
              print('Broken wrappers:', bad, file=sys.stderr)
              sys.exit(1)
          PY

      - name: Post warning comment on PR
        # `always()` so the comment still posts when the structure
        # or wrapper step failed — that's exactly when reviewers
        # most need the JSON report inline on the PR.
        if: |
          always() &&
          github.event_name == 'pull_request' &&
          !cancelled()
        continue-on-error: true
        uses: actions/github-script@v7
        with:
          script: |
            const fs = require('fs');
            const marker = '<!-- pipeline-doctor-comment -->';
            const sections = [];
            for (const f of ['structure.json', 'wrappers.json']) {
              try {
                const data = JSON.parse(fs.readFileSync(f, 'utf8'));
                sections.push(`### ${f}\n\n<details>\n\n\`\`\`json\n${JSON.stringify(data, null, 2)}\n\`\`\`\n\n</details>`);
              } catch (e) { /* missing file = step failed earlier */ }
            }
            const body = `${marker}\n\n## pipeline-doctor report\n\n${sections.join('\n\n')}`;
            const { owner, repo } = context.repo;
            const pr = context.issue.number;
            const existing = await github.paginate(
              github.rest.issues.listComments, { owner, repo, issue_number: pr });
            const mine = existing.find(c => c.body && c.body.startsWith(marker));
            if (mine) {
              await github.rest.issues.updateComment(
                { owner, repo, comment_id: mine.id, body });
            } else {
              await github.rest.issues.createComment(
                { owner, repo, issue_number: pr, body });
            }
```

Notes baked into the workflow above:
- `if: github.event_name == 'pull_request'` on the comment step so
  pushes to `main` don't try to comment on a non-existent PR.
- `continue-on-error: true` on the comment step so a missing
  `pull-requests: write` permission (e.g., a fork PR with the
  default token scope) doesn't fail the build.
- Idempotent: looks up an existing comment by marker and updates
  it in place rather than spamming on every push.

### 4. Documentation

- Mention the CI workflow in `CONVENTIONS.md` so new contributors
  know it catches manifest drift.
- Add a sentence to `model_manifest.json`'s top-level `description`
  field explaining "structurally validated in CI on PR".

## What this catches

- Adding a new user-facing wrapper to `scripts/` without
  registering it in `model_manifest.json::wrappers` (and without
  adding it to the internal-script allow-list) → fails on
  `--check structure`.
- Adding a venv referencing a non-existent feature_set → fails on
  `--check structure`.
- Adding a model whose feature_set has no venv to run it → fails
  on `--check structure`.
- Removing a file from `scripts/` (or anywhere referenced by
  EMBEDS) without removing its EMBEDS entry → fails on
  `--check structure`.
- A bash syntax error or stale arg parser breaking any wrapper's
  `--help` → fails on `--check wrappers` (via the JSON parse,
  even though the doctor's own exit code is 0).

## What this doesn't catch

- Anything that requires a model or venv actually being present.
  The doctor's `disk` / `models` / `venvs` checks need a real
  install. CI doesn't have one; manual `pipeline_doctor.py
  --check all` on developer machines covers it.
- A wrapper that picks a generator/model not declared in the
  manifest — see "What this proposal does NOT do" above.
- Bugs in the model inference itself. The wrappers run; whether
  the models do the right thing is the benchmark harness's job
  (`tests/multiview-bench/`).

## Trade-offs

- **Pro:** zero extra dependencies; structure + wrappers check
  runs in seconds; catches a real class of drift bug.
- **Pro:** PR-warning comments are idempotent (updated in place)
  and tolerant of fork/permission edge cases via
  `continue-on-error`.
- **Con:** small surface increase — one more workflow + one more
  doctor subcheck to keep working.
- **Con:** CI's strict wrapper gate (JSON parse) duplicates exit-
  code interpretation outside the doctor. If we end up with three
  call sites doing this, promote it to a `--fail-on-warning` flag
  in the doctor. Premature today.

## Effort

| Item | Estimate |
|---|---|
| Implement `--check structure` in `pipeline_doctor.py` (+ allow-list) | ~1.5 hours |
| Write `.github/workflows/pipeline-doctor.yml` | ~45 min |
| Update `CONVENTIONS.md` + `model_manifest.json` notes | ~15 min |
| Smoke-test on this branch + an intentionally-broken branch (each fail mode) | ~45 min |
| **Total** | **~3.25 hours** |

## Open questions for review

1. **Internal-script allow-list location.** Hard-coded in
   `pipeline_doctor.py`, or a new array in `model_manifest.json`
   (e.g., `internal_scripts: [...]`)? Manifest is more discoverable
   and keeps all catalog truth in one file. (My recommendation:
   put it in the manifest as `internal_scripts`, validated by the
   structure check the same way `wrappers` is.)
2. **Nightly scheduled run.** Cron the doctor against `main` to
   catch upstream model-URL changes? Cheap; might be
   over-engineering before we hit the case once. (My
   recommendation: skip until we hit the case.)
3. **Should `--check structure` also lint `skill/SKILL.md`** (e.g.,
   ensure every embed marker has a matching EMBEDS entry)? The
   `make verify` target already does this on `make verify` /
   pre-commit. Duplicating in the doctor is redundant unless we
   want a single source of truth in CI. (My recommendation: leave
   `make verify` as the SKILL-parity gate; doctor stays focused
   on manifest + scripts.)

---

Awaiting your review. Quick green-light or ask for changes; once
approved I'll ship the `--check structure` subcheck + the
workflow file as a small follow-up PR.
