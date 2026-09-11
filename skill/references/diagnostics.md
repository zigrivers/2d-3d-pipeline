## When to run setup

For installing the pipeline on a fresh Mac, auditing an existing install
for drift against the repo catalog, or reconciling after the repo gains
new scripts/models/venvs, invoke the **`asset-pipeline-setup`** skill
instead of working with this one. That skill handles:

- First-machine bootstrap (tier choice, HF auth, optional feature_sets)
- Audit loop (`git pull` → `pipeline_doctor.py --check installed` → multi-select fixes)
- Studio-tier extras (queue dirs, opt-in launchd plist, foreign-worker heartbeat check)

This skill (`asset-pipeline`) only handles pipeline work itself.

## Pre-flight check (v0.3+)

On a fresh install, run this read-only check directly when shell access can reach the installed pipeline:

```bash
~/3d-pipeline/workspace/pipeline_doctor.py --check all
```

Ask the user to run it only when this environment cannot access their installation.

This reports disk space, expected venvs, expected model caches, and
that each wrapper's `--help` works. On a partial install, it lists
what's missing. To pre-download the v0.3 quality-feature models
(~1 GB total: rembg's u2net + SigLIP 2 base):

Note: `--warm-cache` does not yet cover the item-16 scorer stack
(ImageReward ~1.8 GB, DreamSim's ensemble weights ~1.5 GB) — those
download on first real use of `concept.sh`'s prompt-adherence scoring.

```bash
~/3d-pipeline/workspace/pipeline_doctor.py --warm-cache
```

Opt-in heavy components (Hunyuan3D-Paint, ComfyUI stack, multi-view)
are scoped behind `--include`:

```bash
~/3d-pipeline/workspace/pipeline_doctor.py --warm-cache --include hunyuan3d-paint
~/3d-pipeline/workspace/pipeline_doctor.py --check all --include comfyui --json
```

Mention pipeline_doctor proactively when:

- A user reports a generation that's been stuck for minutes (likely a
  first-run model download in progress with no progress indicator).
- A wrapper fails with "model not found" or similar.
- You're walking through a v0.3 feature install and the related venv
  or model isn't present yet.

The tool exits 0 on `ok` or `warning`; exits 1 only on `critical`
(out of disk for the chosen scope). Safe to invoke in CI / scripts.

---

