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

Bootstrap budget: roughly 6–7 prompts (tier, feature_sets, HF login if
needed, disk confirmation, apply confirmation). The audit loop below
is bounded at ≤8 prompts (one per stage).

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
   One prompt per stage (not per item). Worst case is one prompt per
   stage (≤8 prompts total). Choosing `(s) skip` for one stage does
   not abort the loop — the next stage is offered independently.
5. **For each user choice, run the engine's `fix_command`.**

## Studio tier — extra checks

Before any `studio_extras` apply on a machine where SMB is mounted:

1. Verify the share is mounted (the user wires this).
2. Check the foreign-machine heartbeat:
   ```
   python3 -c "from scripts import pipeline_doctor as pd; \
     print(pd.is_heartbeat_alive(<queue_dir>, machine='<other>', max_age_seconds=90))"
   ```
3. If a foreign worker is alive (`is_heartbeat_alive` returns True),
   refuse to write the queue directory and ask the user to coordinate.

## What this skill is NOT

- Not a brew installer.
- Not a HuggingFace token manager (walks login, doesn't store credentials).
- Not an SMB mounter.
- Not a release manager.

## Tracked technical debt

The repo has separate `skill/` (runtime) and `setup-skill/` (this skill)
directories. v0.5 will consolidate to `skills/runtime/` and
`skills/setup/`. See `CONVENTIONS.md`.
