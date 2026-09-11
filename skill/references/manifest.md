## After each generation — update the manifest

The manifest lives at:
- `<project>/assets/asset_manifest.json` in project mode
- `~/3d-pipeline/workspace/asset_manifest.json` in global mode

Manifest schema version 3 (v0.2) adds nested blocks. Update after every
generation using the new fields where you have them — the wrapper's
`--json` output gives you most of them for free:

```bash
python3 ~/.claude/skills/asset-pipeline/scripts/update_manifest.py \
    --manifest <manifest path> \
    --name <output_name> \
    --concept <concept_path> \
    --raw <raw_path_or_empty> \
    --clean <clean_path_or_empty> \
    --stl <stl_path_or_empty> \
    --stl-size-mm <size_or_0> \
    --generator <model_name> \
    --polycount <N_or_0> \
    --category <prop|character|hero|environment|weapon|vehicle|2d-only> \
    --license-bucket <bucket> \
    --model-role default \
    --prompt "<original>" \
    --final-prompt "<after game-prompt suffix>" \
    --seed <N> --steps <N> --width <N> --height <N> \
    --duration-seconds <N> \
    --machine <hostname> \
    --hardware-tier <laptop|studio> \
    --engine-path <engine_glb_or_empty> \
    --final-dimensions-mm-json '{"x":50.0,"y":32.4,"z":28.9}' \
    --fits-snapmaker-u1 true \
    --oversized-axes-json '[]' \
    --source-wrapper-json '<JSON the wrapper emitted>' \
    --notes "<one-line description>"
```

All of the v3 args are optional — omit them when you don't have the data.
The wrappers' `--json` outputs include `machine`, `hardware_tier`,
`license_bucket`, `duration_seconds`, and per-stage details ready to
forward.

Skip the manifest only if the user explicitly says they don't want
tracking.

---

