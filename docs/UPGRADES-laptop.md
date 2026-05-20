# v0.2 — Laptop-tier changes

Short summary of what changed in v0.2 that affects the **laptop tier**.
The studio-tier deltas (queue, full-suite bake-offs, 512&nbsp;GB headroom narrative)
are documented separately in [`UPGRADES-studio.md`](UPGRADES-studio.md).

Default behaviour on the laptop is **unchanged** unless you opt into one of
the new flags or wrappers. Z-Image Turbo → SF3D → Blender → Snapmaker U1 still
just works.

---

## What's new on the laptop tier

### `--json` on every wrapper

`concept.sh`, `generate.sh`, `print.sh`, `texture.sh`, and `benchmark.sh` all
accept `--json`. Without it: human-readable output as before, last line is the
output path (chaining-compatible). With it: human-readable lines are routed to
stderr; stdout contains a single JSON object on its last line.

```bash
$ ~/3d-pipeline/workspace/concept.sh "ornate treasure chest" --json
{"status":"ok","stage":"text_to_image","model":"z-image-turbo",
 "license_bucket":"commercial_safe","prompt":"...","outputs":["/abs/path.png"],
 "machine":"...","hardware_tier":"laptop","created":"..."}
```

Useful for: Claude Code chaining, scripting, and feeding the benchmark harness.

### License buckets

Every wrapper now annotates its model choice with a license bucket. The exact
names (used everywhere — code, manifest, docs):

| Bucket                          | Models                              |
| ------------------------------- | ----------------------------------- |
| `commercial_safe`               | z-image-turbo, flux-schnell, qwen-image |
| `commercial_threshold`          | sf3d, spar3d                        |
| `non_commercial`                | flux-dev, trellis                   |
| `source_available_restricted`   | (reserved — nothing default-mapped) |
| `unclear_risky` / `unknown`     | LoRAs and anything untagged         |

When you select a `non_commercial` model the wrapper prints a `[license]
WARNING` to stderr but does **not** block. Stop and confirm before using such
output for Grithkin or GripCraft.

### Hardware tier via `~/3d-pipeline/.config`

The wrappers and the Claude Code skill read a per-machine key=value config:

```
hardware_tier = laptop
```

Default is `laptop` when the file is missing, so this is opt-in for the laptop
tier — only relevant if you ever want a benchmark or manifest entry on your
laptop to record `hardware_tier=laptop` explicitly. If you don't create the
file, everything still works.

### Manifest schema v3

`update_manifest.py` now accepts a lot of optional fields:

```
--license-bucket --model-role --prompt --final-prompt --seed --steps
--width --height --texture-resolution --duration-seconds --machine
--hardware-tier --engine-path --raw-size-bytes --clean-size-bytes
--stl-size-bytes --final-dimensions-mm-json --fits-snapmaker-u1
--oversized-axes-json --eval-json --source-wrapper-json
```

Existing v1/v2 manifests keep working — flat fields stay at the top level for
backward compat. New writes set `version: 3` and add nested blocks
(`model{}`, `generation{}`, `print{}`, `eval{}`). If your manifest is in the
legacy list-of-assets shape, it migrates automatically with a
`.bak.<timestamp>` backup.

### All-axis Snapmaker U1 validation

`print.sh` now refuses to produce an STL whose final dimensions exceed
270&nbsp;mm on **any** axis (not just the longest). Override with
`--allow-oversize` when you'll print in pieces.

A sidecar `<output.stl>.print_meta.json` is always written with the final
dimensions, oversized axes, polygon and vertex counts.

```bash
$ print.sh -i clean/chest_clean.glb -s 50
[print] Print-ready in 7s
[print] STL: /…/assets/print/chest.stl (1.2 MB)

$ cat /…/assets/print/chest.stl.print_meta.json
{
  "final_dimensions_mm": {"x": 50.0, "y": 32.4, "z": 28.9},
  "fits_snapmaker_u1": true,
  "oversized_axes": [],
  ...
}
```

### Safer engine staging

`generate.sh` now refuses to silently overwrite engine-staged GLBs:

- Default (`naming.auto_increment_collisions: true`): writes `<name>_2.glb`,
  `<name>_3.glb`, … on collision and tells you which slot it used.
- `naming.auto_increment_collisions: false`: skips the stage on collision and
  tells you how to override with `--overwrite-engine`. Your existing engine
  asset is preserved.

### `texture.sh` (experimental)

New wrapper for texture work:

```bash
# Inspect a GLB, image, or directory
~/3d-pipeline/workspace/texture.sh -i path/to/thing --json

# Upscale a texture (requires real-esrgan-ncnn-vulkan on PATH)
~/3d-pipeline/workspace/texture.sh -i texture.png --mode upscale --scale 4
```

Outputs go to `assets/textures/` (or `~/3d-pipeline/workspace/textures/` in
global mode). If the upscaler binary isn't installed, the wrapper fails clearly
with install guidance — no silent fallback.

### `benchmark.sh` (works on laptop, lighter suites recommended)

Quick sanity check (3 prompts) is realistic on the laptop tier:

```bash
~/3d-pipeline/workspace/benchmark.sh --suite quick --json
```

The full `default` suite (14 prompts) can run, but `quick` is generally enough
on the laptop unless you're doing a serious comparison. Each result row records
`hardware_tier` and `machine`, so a future studio run is directly comparable.

### SPAR3D opt-in

`generate.sh -g spar3d` now wires up SPAR3D as an experimental 3D generator
(commercial_threshold, same as SF3D). It needs a separate install at
`~/3d-pipeline/stable-point-aware-3d/` with its own `.venv`. The wrapper fails
clearly with install guidance if it's missing — relay the install URL and the
`SPAR3D_DIR` override env var if you want to try it elsewhere.

Not the default. Don't switch to SPAR3D without benchmark evidence that it
wins on the asset class you care about.

---

## What's deliberately unchanged

- 2D default: **Z-Image Turbo** (commercial_safe).
- 3D default: **SF3D** (commercial_threshold).
- Print default: **STL**, 50&nbsp;mm fallback only when you say "you pick".
- All existing scripts keep their old CLI; only new flags were added.
- The Claude Code skill still routes auto-detected projects; nothing about
  project mode / global mode changed.
- The setup guide for the laptop tier still installs everything to
  `~/3d-pipeline/workspace/`.

## What's not in the laptop docs (on purpose)

- **Two-machine queue.** It works on the laptop in principle but the operational
  recipe is only useful with two Mac Studios sharing a folder. See
  [`UPGRADES-studio.md`](UPGRADES-studio.md) if you're curious.
- **Headroom narrative for 512&nbsp;GB unified memory.** The laptop tier has its
  own memory budget; recommendations there haven't changed.

---

## Warnings worth repeating

- **`flux-dev` and `trellis` are `non_commercial`.** The wrappers print a
  warning; don't use their output for Grithkin / GripCraft unless you've
  accepted the licence restrictions for that specific asset.
- **The U1 prints from a single mesh.** Multi-color comes from Snapmaker Orca's
  paint tool, not from anything the pipeline generates.
- **Don't run `print.sh` on a raw GLB.** Always use the cleaned version from
  `assets/clean/`.

## What's coming next (v0.3 prep)

### `pipeline-tools-env` venv (optional, installable now)

v0.3 adds quality-check scripts (watertight + scale, texture quality,
input quality, background removal, CLIP scoring, pipeline doctor) that
share a single Python environment at `~/3d-pipeline/pipeline-tools-env/`.

The setup guide ships a new optional step (section 10) for installing
this venv. The venv is **unused** by v0.2 — nothing changes about how
your current pipeline runs. Install it now if you want a head start on
v0.3; skip it otherwise.

Packages installed:

```
trimesh numpy scipy Pillow rembg[cpu] open_clip_torch torch tqdm requests
```

Disk impact: ~6 GB once populated. Caches at `~/3d-pipeline/models/rembg/`
(env: `U2NET_HOME`) and `~/3d-pipeline/models/clip/`
(env: `OPEN_CLIP_CACHE_DIR`).

If a wheel fails to install: `pip install --upgrade pip setuptools wheel`
first, then retry. `torch` on Apple Silicon is the most common failure;
make sure you're on Python 3.10–3.12.

Last updated: 2026-05-20
