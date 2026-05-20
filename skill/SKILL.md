---
name: asset-pipeline
description: Use whenever the user wants to generate a 2D image, a 3D game asset, prepare a 3D asset for 3D printing, run a model bake-off, inspect or upscale textures, or submit jobs to the two-machine queue on their local pipeline. Auto-detects the active project (Unity, Unreal, or any directory with a .asset-pipeline.json config) and routes outputs into that project's assets/ folder. Falls back to ~/3d-pipeline/workspace/ when run outside any project. Reads ~/3d-pipeline/.config to detect the hardware tier (laptop vs studio) and behaves accordingly. Triggers on requests like "generate a 3D model from this image", "make me a 2D concept", "create a 3D asset for my game", "convert this image to 3D", "prepare this for 3D printing", "make an STL for my Snapmaker", "compare SF3D vs SPAR3D", "run a benchmark", "upscale this texture", "queue this job on the other Studio", or any mention of SF3D, SPAR3D, TRELLIS.2, FLUX, Z-Image, mflux, Real-ESRGAN, concept art, or the Snapmaker U1. Handles text-to-2D (mflux), 2D-to-3D (SF3D / SPAR3D / TRELLIS.2 + Blender), GLB-to-STL print preparation, Unity/Unreal engine import, model bake-offs, texture inspect/upscale, and the experimental two-machine job queue.
---

# Asset Pipeline (2D + 3D + Print)

Drives the user's local asset generation pipeline. The user runs this on
two hardware tiers, both Apple Silicon. The wrappers and this skill are
shared; the only thing that differs between tiers is the `.config` file
and which experimental lanes are reasonable to recommend.

## Pre-flight check (v0.3+)

On a fresh install, before any asset work, ask the user to run:

```bash
~/3d-pipeline/workspace/pipeline_doctor.py --check all
```

This reports disk space, expected venvs, expected model caches, and
that each wrapper's `--help` works. On a partial install, it lists
what's missing. To pre-download the v0.3 quality-feature models
(~1 GB total: rembg's u2net + OpenCLIP ViT-L/14):

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

## Hardware tiers

| Tier         | Hardware                                | Defaults / what to recommend                     |
| ------------ | --------------------------------------- | ------------------------------------------------ |
| `laptop`     | Apple Silicon Mac Laptop, modest RAM    | Commercial-safe defaults only. Skip the queue.   |
| `studio`     | Apple M3 Ultra Mac Studio, 512 GB UMA   | Same safe defaults; opt-in lanes are realistic.  |

Detect the active tier by reading `~/3d-pipeline/.config`:

```
hardware_tier = studio    # or laptop
```

If the file is missing or the value is anything else, treat it as
`laptop`. Never sniff hostname — renaming a machine should not silently
change behaviour. The wrappers do the same detection in `_pipeline_lib.sh`
(function `hardware_tier`); every `--json` output includes the
`hardware_tier` field so manifests and benchmark results stay tier-aware.

## Three pipeline halves + four new lanes

The three core halves are unchanged:

- **2D** — text → image via mflux
- **3D** — image → mesh via SF3D (default) / SPAR3D / TRELLIS.2, then Blender cleanup
- **Print** — clean GLB → printable STL via Blender mesh repair + scaling

v0.2 adds four lanes you'll occasionally recommend, none of them defaults:

- **Texture inspect/upscale** (`texture.sh`) — GLB and image stats, optional
  Real-ESRGAN upscale.
- **Model bake-off** (`benchmark.sh`) — runs a prompt suite across selected
  2D models and 3D generators, writes structured results.
- **Queue** (`queue_submit.py` / `queue_worker.py`) — file-based two-machine
  job queue. **Studio-tier recommendation only.** It works on a laptop but
  the value is multi-machine.
- **SPAR3D** (`generate.sh -g spar3d`) — alternative 3D generator. Opt-in
  and experimental.

---

## License buckets

Use these exact names in conversation, manifest entries, and JSON output:

| Bucket                          | Models                                              |
| ------------------------------- | --------------------------------------------------- |
| `commercial_safe`               | z-image-turbo, flux-schnell, qwen-image             |
| `commercial_threshold`          | sf3d, spar3d                                        |
| `non_commercial`                | flux-dev, trellis                                   |
| `source_available_restricted`   | (reserved; nothing default-mapped here yet)         |
| `unclear_risky` / `unknown`     | LoRAs and anything not explicitly tagged            |

The wrappers print a `[license] WARNING` to stderr when the user picks a
`non_commercial` model. Don't block the user — relay the warning and
proceed if they accepted the restriction.

When recommending a model outside the default lane (anything other than
z-image-turbo → SF3D → Blender), **always mention the license bucket** in
the conversation so the user is making an informed call:

> "I'll use SPAR3D this time — license bucket `commercial_threshold`, same
> as SF3D, so usable in Grithkin and GripCraft. Sound good?"

---

## Project context (read this first)

The wrappers (`concept.sh`, `generate.sh`, `print.sh`, `texture.sh`,
`benchmark.sh`) auto-detect the active project. **You don't need to specify
project paths — the wrappers handle it.** Detection order:

1. `--project PATH` flag (if passed explicitly)
2. `PROJECT_ROOT` env var (if set in the shell)
3. Walk up from the current directory looking for:
   - A `.asset-pipeline.json` config file, OR
   - Unity markers (`Assets/` + `ProjectSettings/`), OR
   - Unreal markers (`*.uproject` + `Content/`)
4. Fall back to global workspace (`~/3d-pipeline/workspace/`)

**Outputs land in different places depending on context:**

| Mode | Concept/raw/clean/print/textures | Engine staging |
|---|---|---|
| Global (no project detected) | `~/3d-pipeline/workspace/{concept,raw,clean,print,textures}/` | `~/3d-pipeline/workspace/engine/` |
| Project (no engine) | `<project>/assets/{concept,raw,clean,print,textures}/` | `<project>/assets/engine/` |
| Unity project | same as above for assets/ | `<project>/Assets/Models/AI/` (auto) |
| Unreal project | same as above for assets/ | `<project>/Content/Models/AI/` (auto) |

The cleaned GLB is **always** kept in `assets/clean/` (the canonical
version). For Unity/Unreal projects, a copy is *also* staged in the engine
folder so the editor picks it up directly. The user gets both.

### How to handle project context in conversation

At the start of each interaction where you'll generate assets, briefly
tell the user where outputs will land, then proceed. Example:

> "I'll generate that into your Unity project at `~/games/grithkin/`. Final
> GLB will appear in `Assets/Models/AI/`."

You can confirm by running:

```bash
cd <user's cwd>
source ~/3d-pipeline/workspace/_pipeline_lib.sh
resolve_project_context "" "$PWD" >/dev/null && print_context
```

But in practice, the wrapper prints the context as its first action; you
don't have to pre-check.

### Per-project config

`.asset-pipeline.json` schema (all optional; `{}` is a valid config):

- `engine`: `"unity" | "unreal" | "none"` — overrides auto-detection
- `engine_path`: relative-to-project or absolute path for final GLB staging
- `defaults.generator_2d`: `"z-image-turbo" | "flux-schnell" | "flux-dev" | "qwen-image"`
- `defaults.generator_3d`: `"sf3d" | "spar3d" | "trellis"`
- `defaults.polycount`: integer
- `defaults.texture_resolution`: integer
- `defaults.lora`: absolute path to .safetensors
- `naming.prefix`: string prepended to all output filenames
- `naming.auto_increment_collisions`: boolean (default true). Drives engine
  staging collision behaviour — see Flow 2 below.

If a `.asset-pipeline.json` `defaults.generator_2d` or `defaults.generator_3d`
points at a non-commercial model (flux-dev, trellis), the wrappers will
warn but proceed. Mention this to the user the first time you notice.

---

## Doc routing by hardware tier

Point users at the right setup guide for *their* machine:

- `laptop` tier → `docs/asset-pipeline-guide.html`
- `studio` tier → `docs/asset-pipeline-guide-studio.html`
- AI context (denser; for me) →
  - `context/asset-pipeline-ai-context.md` (laptop, canonical)
  - `context/asset-pipeline-ai-context-studio.md` (studio)
- v0.2 change log →
  - `docs/UPGRADES-laptop.md`
  - `docs/UPGRADES-studio.md`

---

## When the user invokes this skill

Determine which of the eight flows applies:

1. **Text → 2D only** — prompt only, image output
2. **2D → 3D** — image input, GLB output for games
3. **Text → 2D → 3D** — prompt only, GLB output (chain 1 + 2)
4. **GLB → printable STL** — existing 3D asset, STL output for the Snapmaker U1
5. **Text → 2D → 3D → STL** — full pipeline ending at a printable file
6. **Texture inspect / upscale** — describe a GLB or image, or upscale a texture
7. **Model bake-off / benchmark** — compare two or more model paths on the same prompts
8. **Queue-based batch generation (studio-tier, experimental)** — submit work that one of the Studios will pick up

If unclear, ask one short question. Common defaults:
- "make me a [thing] for my game" → flow 3
- "make me a [thing] I can 3D print" → flow 5
- "prepare [asset] for printing" or "make an STL of [asset]" → flow 4
- "inspect this GLB" / "upscale this texture" → flow 6
- "compare SF3D and SPAR3D" / "which 2D model is best for this prompt" → flow 7
- "queue these on the other Studio" → flow 8 (studio tier only)

**When chaining or scripting, always pass `--json` to the wrappers.** The
JSON is stable and parseable; the human-readable lines under `--json` are
routed to stderr so they don't corrupt the result.

---

## Flow 1: Text → 2D image

Use `concept.sh` with the user's prompt. Default model is Z-Image Turbo
(commercial_safe, ~10-30s). Use `flux-schnell` only when a LoRA is needed;
use `flux-dev` only if user accepts non-commercial output (mention the
bucket).

For variations, use `-n N`. For specific names, `-o NAME`. Default output
is in `<project>/assets/concept/` or `~/3d-pipeline/workspace/concept/`.

The wrapper prints the absolute path as its last line — capture it for
chaining. If you're scripting, pass `--json` and parse the last stdout
line as JSON; `outputs[0]` is the first image.

## Flow 2: 2D image → 3D asset

Use `generate.sh` with `-i <image_path>`. Default to SF3D unless asked
for SPAR3D or TRELLIS.2 or the asset needs unusual topology. Mention the
license bucket if you pick anything other than SF3D.

### Cleanup report (v0.3+)

After `clean_asset.py` runs (always — it's in v0.2), the wrapper now
emits a one-line summary if the meta.json has a `cleanup` section:

```
[pipeline] Cleanup: removed 47 duplicate points, filled 2 small gap(s),
                    simplified mesh: 18,400 → 3,000 polygons
```

Use this as a signal of generator output quality. Heuristics:

- `holes_filled > 5` or `duplicate_vertices_removed > 1,000` →
  raw mesh was poor; mention this to the user before they commit
  the asset to their project (re-generation often helps)
- `decimate ratio < 0.05` → raw mesh was extremely dense; current
  generator settings may be overkill; suggest a higher polycount
  target if the user wants more detail
- All counts ≈ 0 → raw mesh was already clean; nothing to flag

For prints (Flow 4 / 5): higher cleanup counts correlate with
slicer trouble. Worth surfacing when the destination is a printer.

### Input quality check (v0.3+)

When `pipeline-tools-env` is installed, the wrapper runs an input
quality + format-normalisation pass before the generator. WebP and
animated GIF inputs are converted to a static PNG under
`<assets>/concept/<name>_normalized.png` first; the original is
preserved. Quality issues are surfaced on stderr as
`[pipeline] input ⚠ <tag>` lines and recorded in the per-asset
meta.json under the `input` section. Common tags:

- `low_resolution` (< 512 px on shortest edge) — recommend the user
  upscale via `texture.sh --mode upscale --scale 2` first
- `very_low_resolution` (< 384 px) — strongly recommend regenerating
  or upscaling; downstream quality will suffer
- `extreme_aspect_ratio` (outside 1:2 to 2:1) — output mesh will be
  distorted; suggest cropping or re-shooting
- `multi_frame_input` — animated GIF or multi-frame WebP; only frame
  0 is used; mention this to the user
- `unsupported_format` — error; the wrapper exits

If pipeline-tools-env is missing, the check is a silent no-op and the
generator runs on the raw input (v0.2 behaviour).

Polycount guidance:
- Tiny pickup: 500–1000
- Standard prop (default 3000): 2000–4000
- Detailed: 5000–8000
- Character: 10000–20000
- Hero / Nanite: 15000+ or `--no-clean`

**In project mode with Unity/Unreal detected, the cleaned GLB is also
auto-copied to the engine folder.** Tell the user this happened. If they
explicitly don't want it staged (e.g., they're just experimenting), pass
`--no-engine-stage` to skip the copy.

### Engine staging collision behaviour (v0.2)

`generate.sh` now refuses to silently overwrite engine files:

- `naming.auto_increment_collisions=true` (default): on collision, the
  wrapper writes `<name>_2.glb`, `<name>_3.glb`, … and tells the user
  which slot took the new asset.
- `naming.auto_increment_collisions=false`: on collision, the wrapper
  SKIPS engine staging by default and tells the user how to override
  with `--overwrite-engine`. The clean GLB is still in `assets/clean/`.

Pass `--overwrite-engine` only when the user has explicitly asked to
replace an existing engine asset.

### SPAR3D (experimental)

`generate.sh -g spar3d -i image.png`. License bucket
`commercial_threshold` (same as SF3D, so commercial-usable). Requires
`~/3d-pipeline/stable-point-aware-3d/` with a `.venv` and `run.py`. If
the user asks for it and it's not installed, the wrapper fails clearly
with install guidance — relay that.

Recommend SPAR3D when:
- The asset has detail on the back face and SF3D has visibly hallucinated.
- The user is benchmarking and you're running flow 7.

Don't make it the default. Confirm with benchmarks before claiming it
wins on a given asset class.

## Flow 3: Text → 2D → 3D

Run flow 1, **show the user the 2D output before kicking off flow 2**.
Don't auto-proceed unless they explicitly said "go all the way" or similar.

## Flow 4: GLB → printable STL

### Step 1 — Identify the source GLB

The user might reference:
- A name from the manifest: `chest_clean`
- A path: `~/games/grithkin/assets/clean/chest_clean.glb` (project) or
  `~/3d-pipeline/workspace/clean/chest_clean.glb` (global)
- An image they want generated and then printed (chain through flows 1+2 first)

If it's a name only, expand within the active project's `assets/clean/`
first, then fall back to the global workspace if not found.

### Step 2 — Ask about target size

Real-world print size in millimeters. **Always ask if not specified** —
print size is a strong creative choice. Suggest:

> "What size should it be? Common choices: 25mm (small token), 50mm
> (tabletop figure), 100mm (large miniature), 150–200mm (display piece).
> The Snapmaker U1 build volume is 270mm on each axis."

Use 50mm as a fallback only if the user explicitly says "you pick".

### Step 3 — Run print.sh

```bash
~/3d-pipeline/workspace/print.sh -i <path> -s <SIZE_MM>
```

Or in JSON mode for chaining:

```bash
~/3d-pipeline/workspace/print.sh -i <path> -s <SIZE_MM> --json
```

`print.sh` validates final dimensions on **every axis** post-scale. If
*any* axis exceeds 270mm, it exits with error 3 and writes NO STL,
**unless** `--allow-oversize` is passed. Pass that flag only when the
user has acknowledged they're printing in pieces or has a larger
printer in mind.

STL is the only output format by design — the Snapmaker U1's color
capability lives in Orca's paint tool, not in the mesh, so 3MF would add
complexity without unlocking new capability. Don't suggest 3MF as a
fallback when an STL doesn't slice well; fix the mesh upstream instead.

### Step 4 — Verify output and report fit

The script reports final dimensions in mm and whether the asset fits
within the 270×270×270 U1 build volume. The `--json` result has:

```json
"final_dimensions_mm": {"x": 50.0, "y": 32.4, "z": 28.9},
"fits_snapmaker_u1": true,
"oversized_axes": []
```

(There's also a `<output.stl>.print_meta.json` sidecar with the same
information; useful for the manifest update.)

### Step 5 — Guide the user into Snapmaker Orca

The pipeline produces single-mesh STL. The U1's multi-color capability is
unlocked **in the slicer**, not from mesh data:

1. Open **Snapmaker Orca**
2. **File → Import → 3D Model** → select the STL
3. To use multiple colors: select the model, click the **Paint** tool
4. Use the brushes (Sphere / Triangle / Fill / Height Range) to paint regions
5. Each painted region maps to one of the 4 toolheads with its loaded filament
6. The color reference image (saved alongside the STL) is a guide for what
   each region should look like
7. Slice and print

Mention the color reference image specifically — users often miss it exists.
**Never claim multi-color mesh output**; U1 color painting is slicer-side.

## Flow 5: Text → 2D → 3D → STL

Run flows 1–3 to produce the clean GLB, then flow 4 to convert to STL.
Show user each output before moving to the next, except when they
explicitly chain ("make me a 50mm printable treasure chest" implies
authorization to run the full chain — still ask the size if it's not
in their request).

## Flow 6: Texture inspect / upscale

### Inspect

```bash
~/3d-pipeline/workspace/texture.sh -i <path> [--json]
```

Works on:
- A single image (PNG / JPG / WEBP) → dimensions, file size, color mode
- A GLB file → mesh / material / texture / image / node / scene counts
- A directory → enumerated image files with dimensions

Use inspect when the user asks "what's in this GLB?" or "how big is this
texture?" Output is fast (no Blender startup) because it parses the
glTF JSON chunk directly.

### Upscale

```bash
~/3d-pipeline/workspace/texture.sh -i <path> --mode upscale --scale 4 [--json]
```

Uses `real-esrgan-ncnn-vulkan` if installed. If not installed, the
wrapper fails with `status=error error=not_installed` JSON and stderr
install guidance — relay that and offer to wait until the user installs
it. **Do not invent a fallback path.** Real-ESRGAN ncnn-vulkan is the
only supported upscaler today.

Output lands in `assets/textures/` (or `~/3d-pipeline/workspace/textures/`
in global mode). `--engine-stage` copies to the engine's `Textures/`
folder when applicable.

### Paint (placeholder for Hunyuan3D-Paint — licence-gated, do NOT enable)

`texture.sh --mode paint` is a deliberately broken placeholder. It fails
with `status=error error=needs_license_review` and exits 2. The reason:
Hunyuan3D-Paint is licensed under the Tencent Hunyuan Community License,
which has revenue thresholds and region exclusions that haven't been
reviewed against Ken's commercial usage. Until that review happens,
the mode refuses to run rather than silently producing assets with
unclear commercial usability.

The licence bucket for `hunyuan3d-paint` is `unclear_risky` in
`_pipeline_lib.sh::license_bucket_for_model` so anything that *does*
get tagged with it shows up in manifests and benchmarks as unreviewed.

If the user asks about Hunyuan3D-Paint, do not try to enable it. Explain
the gate, point at the structured error message, and offer to help with
the licence review (which is human work, not pipeline work).

## Flow 7: Model bake-off / benchmark

```bash
~/3d-pipeline/workspace/benchmark.sh --suite default --json
```

Suites:
- `quick` — 3 prompts (fast sanity check)
- `default` — 14 representative prompts
- `custom` — requires `--prompts-file PATH` (one prompt per line, `#` comments)

Comparisons:
- `--models-2d z-image-turbo,flux-schnell` — bake off the 2D path
- `--generators sf3d,spar3d` — bake off the 3D path
- `--skip-2d` to reuse existing concept images
- `--skip-3d` for a concept-only sanity check

The harness writes:

```
<assets_root>/benchmarks/<YYYYMMDD-HHMMSS>/benchmark_results.json
```

Each run carries an `eval` block with `prompt_match`, `front_accuracy`,
`topology`, `unity_import`, `print_prep`, etc. — all `null` /
`"not_tested"` by default. After the bake-off, offer to walk the user
through scoring those fields; do not auto-score.

**Recommend benchmark.sh whenever the user is choosing between models
"in their head."** Better to spend 15 minutes generating real comparable
output than to argue about which model is "supposed" to be better.

Tier note: on `laptop`, suggest `--suite quick` first. On `studio`, the
default suite is realistic.

## Flow 8: Queue-based batch generation (studio-tier, experimental)

Studio-tier feature. **Mention "experimental" in the conversation.**

Submit:

```bash
python3 ~/3d-pipeline/workspace/queue_submit.py \
    --assets-root <root> \
    --stage image_to_3d \
    --input <image> \
    --generator sf3d \
    --polycount 3000 \
    --json
```

Worker (run on the other Studio, or as a background process):

```bash
python3 ~/3d-pipeline/workspace/queue_worker.py \
    --assets-root <root> \
    --script-dir ~/3d-pipeline/workspace \
    [--once | --max-jobs N]
```

Each job moves `pending/ → running/ → done/` (or `failed/`). The job
file is the canonical record — `cat queue/done/<uuid>.json` for the full
result including the wrapper's `--json` output.

Only suggest the queue when both Studios are available and the user has
a batch of work. For one-off generations, run the wrappers directly.

---

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

## When NOT to stage to engine folder

`--no-engine-stage` is the right move when:
- User is experimenting and explicitly says "don't add it to the project yet"
- User is generating placeholder/test assets they'll delete
- User wants to inspect the clean GLB in isolation before exposing it
  to their game

Otherwise, the auto-staging is what they want — assets appear in Unity
or Unreal automatically.

If you suspect the engine asset already exists, **don't** reflexively
pass `--overwrite-engine`. Let the wrapper's auto-increment do its thing
(default) or honour the user's `auto_increment_collisions=false` setting.

---

## Prompt-writing tips

For 3D-bound 2D prompts, describe:
- **Subject** with specific material/style ("ornate wooden chest with brass
  fittings" > "chest")
- **View** that captures 3D form (3/4 isometric > pure side > pure front)
- **Lighting** that's even, not dramatic
- **Background** that's clean (the default suffix handles this)

For printable assets, also avoid:
- Heavy overhangs (need support material)
- Thin spikes / delicate filaments (snap during printing)
- Multi-color prompts (color comes from filament in Snapmaker Orca,
  not the mesh)

If the user describes something hard to print, mention it before generating.

## Common issues

**"Project not detected" but I'm in one.** Make sure the project root has
the right markers: Unity needs both `Assets/` and `ProjectSettings/`;
Unreal needs `Content/` and a `*.uproject` file at the root. If neither
applies, add an empty `.asset-pipeline.json` to mark it as a project.

**Wrong project detected.** User is in a nested git checkout that
contains a Unity project at its root. Solutions: (a) `--project
/correct/path` override, (b) `PROJECT_ROOT=/correct/path` env var, (c)
add `.asset-pipeline.json` to the actual intended project root (closer
matches win).

**STL output has visible artifacts.** Run Snapmaker Orca's Auto Repair as
a second pass. The Blender print prep handles 90% of cases.

**STL was rejected as oversize (exit 3).** Re-run with a smaller `-s`
value. If the user insists, pass `--allow-oversize` AFTER they
acknowledge they'll print in pieces.

**Build volume warning on a non-longest axis.** Asset is wider than tall;
suggest a smaller `-s` value or reorientation.

**Non-commercial model warning fired.** flux-dev or trellis was selected.
Confirm the user has accepted the licence restriction for THIS asset
before proceeding. Add a note to the manifest if they want to track it.

**Queue worker says malformed JSON.** A wrapper printed something to
stdout that wasn't a valid JSON object. Re-run the wrapper directly with
`--json` to debug.

## What not to do

- Don't try to detect projects yourself — let the wrappers do it. They
  print context as their first action.
- Don't call `print.sh` on a raw, uncleaned GLB from `raw/`. Always use
  the cleaned version from `clean/`.
- Don't promise multi-color printing from the mesh alone. That's a
  slicer-side operation.
- Don't suggest non-U1 slicers unless asked.
- Don't quietly skip the size question for prints.
- Don't pass `--project` explicitly when the user is already in a project
  directory — let auto-detection do its job. Pass it only when the user
  is somewhere else (e.g., their home directory) but wants outputs in a
  specific project.
- Don't recommend the queue on the laptop tier.
- Don't silently switch to flux-dev or trellis as a default. They're
  non-commercial.
- Don't pass `--allow-oversize` without confirming the user understands
  why the model exceeded the build volume.
- Don't pass `--overwrite-engine` reflexively. Default behaviour is safer.

## Bundled resources

- `scripts/update_manifest.py` — manifest updater (v3-aware)
