---
name: asset-pipeline
description: Use whenever the user wants to generate a 2D image, a 3D game asset, or prepare a 3D asset for 3D printing on their local pipeline. Auto-detects the active project (Unity, Unreal, or any directory with a .asset-pipeline.json config) and routes outputs into that project's assets/ folder. Falls back to ~/3d-pipeline/workspace/ when run outside any project. Triggers on requests like "generate a 3D model from this image", "make me a 2D concept", "create a 3D asset for my game", "convert this image to 3D", "prepare this for 3D printing", "make an STL for my Snapmaker", or any mention of SF3D, TRELLIS.2, FLUX, Z-Image, mflux, concept art, or the Snapmaker U1. Handles text-to-2D (mflux), 2D-to-3D (SF3D/TRELLIS.2 + Blender), GLB-to-STL print preparation, and Unity/Unreal engine import.
---

# Asset Pipeline (2D + 3D + Print)

Drives the user's local asset generation pipeline. The user is on Apple Silicon macOS with 128 GB unified memory and a Snapmaker U1 3D printer.

Three pipeline halves:
- **2D** — text → image via mflux
- **3D** — image → mesh via SF3D or TRELLIS.2, then Blender cleanup
- **Print** — clean GLB → printable STL via Blender mesh repair + scaling

They chain. The full text-to-printable path runs all three.

---

## Project context (read this first)

The wrappers (`concept.sh`, `generate.sh`, `print.sh`) auto-detect the active project. **You don't need to specify project paths — the wrappers handle it.** Here's how detection works:

1. `--project PATH` flag (if passed explicitly)
2. `PROJECT_ROOT` env var (if set in the shell)
3. Walk up from the current directory looking for:
   - A `.asset-pipeline.json` config file, OR
   - Unity markers (`Assets/` + `ProjectSettings/`), OR
   - Unreal markers (`*.uproject` + `Content/`)
4. Fall back to global workspace (`~/3d-pipeline/workspace/`)

**Outputs land in different places depending on context:**

| Mode | Concept/raw/clean/print | Engine staging |
|---|---|---|
| Global (no project detected) | `~/3d-pipeline/workspace/{concept,raw,clean,print}/` | `~/3d-pipeline/workspace/engine/` |
| Project (no engine) | `<project>/assets/{concept,raw,clean,print}/` | `<project>/assets/engine/` |
| Unity project | `<project>/assets/{concept,raw,clean,print}/` | `<project>/Assets/Models/AI/` (auto) |
| Unreal project | `<project>/assets/{concept,raw,clean,print}/` | `<project>/Content/Models/AI/` (auto) |

The cleaned GLB is **always** kept in `assets/clean/` (the canonical version). For Unity/Unreal projects, a copy is *also* staged in the engine folder so the editor picks it up directly. The user gets both.

### How to handle project context in conversation

At the start of each interaction where you'll generate assets, **briefly tell the user where outputs will land**, then proceed. Example:

> "I'll generate that into your Unity project at `~/games/grithkin/`. Final GLB will appear in `Assets/Models/AI/`."

You can find the project root by running this from the wrapper directory:

```bash
cd <user's cwd>
source ~/.claude/skills/asset-pipeline/scripts/_pipeline_lib.sh 2>/dev/null || source ~/3d-pipeline/workspace/_pipeline_lib.sh
resolve_project_context "" "$PWD" >/dev/null && print_context
```

But in practice, just running the wrapper will print the context as its first action. You don't have to pre-check.

### When to suggest creating a config

If the user is working in a project that doesn't have `.asset-pipeline.json` and you notice they keep passing the same overrides (e.g. always `-p 5000`, always `-l <some-lora>`), suggest creating a config:

> "I noticed you've used `-p 5000 -l flux-game-assets.safetensors` three times now. Want me to drop a `.asset-pipeline.json` in this project so those become the defaults?"

Then offer to create it:

```json
{
  "defaults": {
    "polycount": 5000,
    "lora": "/full/path/to/flux-game-assets.safetensors"
  }
}
```

Schema:
- `engine`: `"unity" | "unreal" | "none"` — overrides auto-detection
- `engine_path`: relative-to-project or absolute path for final GLB staging
- `defaults.generator_2d`: `"z-image-turbo" | "flux-schnell" | "flux-dev"`
- `defaults.generator_3d`: `"sf3d" | "trellis"`
- `defaults.polycount`: integer
- `defaults.texture_resolution`: integer
- `defaults.lora`: absolute path to .safetensors
- `naming.prefix`: string prepended to all output filenames
- `naming.auto_increment_collisions`: boolean (default true)

All fields optional. `{}` is a valid config (just signals "this is a project").

---

## When the user invokes this skill

Determine which of five flows applies:

1. **Text → 2D only** — prompt only, image output
2. **2D → 3D** — image input, GLB output for games
3. **Text → 2D → 3D** — prompt only, GLB output (chain 1 + 2)
4. **GLB → printable STL** — existing 3D asset, STL output for the Snapmaker U1
5. **Text → 2D → 3D → STL** — full pipeline ending at a printable file

If unclear, ask one short question. Common defaults:
- "make me a [thing] for my game" → flow 3
- "make me a [thing] I can 3D print" → flow 5
- "prepare [asset] for printing" or "make an STL of [asset]" → flow 4

---

## Flow 1: Text → 2D image

Use `concept.sh` with the user's prompt. Default model is Z-Image Turbo (Apache 2.0, ~10-30s). Use `flux-schnell` only when a LoRA is needed; use `flux-dev` only if user accepts non-commercial output.

For variations, use `-n N`. For specific names, `-o NAME`. Default output is in `<project>/assets/concept/` or `~/3d-pipeline/workspace/concept/`.

The script prints the absolute path as its last line — capture for chaining.

## Flow 2: 2D image → 3D asset

Use `generate.sh` with `-i <image_path>`. Default to SF3D unless asked for TRELLIS.2 or the asset needs unusual topology.

Polycount guidance:
- Tiny pickup: 500–1000
- Standard prop (default 3000): 2000–4000
- Detailed: 5000–8000
- Character: 10000–20000
- Hero / Nanite: 15000+ or `--no-clean`

**In project mode with Unity/Unreal detected, the cleaned GLB is also auto-copied to the engine folder.** Tell the user this happened. If they explicitly don't want it staged (e.g., they're just experimenting), pass `--no-engine-stage` to skip the copy.

## Flow 3: Text → 2D → 3D

Run flow 1, **show user the 2D output before kicking off flow 2**. Don't auto-proceed unless they explicitly said "go all the way" or similar.

## Flow 4: GLB → printable STL

For when the user wants to 3D print on the Snapmaker U1.

### Step 1 — Identify the source GLB

The user might reference:
- A name from the manifest: `chest_clean`
- A path: `~/games/grithkin/assets/clean/chest_clean.glb` (project) or `~/3d-pipeline/workspace/clean/chest_clean.glb` (global)
- An image they want generated and then printed (chain through flows 1+2 first)

If it's a name only, expand within the active project's `assets/clean/` first, then fall back to the global workspace if not found.

### Step 2 — Ask about target size

Real-world print size in millimeters. If the user didn't specify, ask:

> "What size should it be? Common choices: 25mm (small token), 50mm (tabletop figure), 100mm (large miniature), 150-200mm (display piece). The Snapmaker U1 build volume is 270mm max."

Don't assume — print size is a strong creative choice. Use 50mm as a fallback if you must default.

### Step 3 — Run print.sh

```bash
~/3d-pipeline/workspace/print.sh -i <path> -s <SIZE_MM>
```

This wraps Blender headless and:
- Repairs non-manifold geometry (holes, internal faces, bad normals)
- Scales mesh to the user's target size in millimeters
- Orients lowest point at Z=0 for Snapmaker Orca
- Exports binary STL into `<project>/assets/print/` or global workspace
- Copies the concept image alongside as a color reference

Expected runtime: 5–10 seconds.

### Step 4 — Verify output and report fit

The script reports final dimensions in mm and whether the asset fits within the 270×270×270 U1 build volume. If a non-longest axis exceeds 270mm even though the user's chosen longest axis is smaller, the script prints a warning — relay this to the user with a suggested smaller `-s` value.

### Step 5 — Guide the user into Snapmaker Orca

The pipeline produces single-mesh STL. The U1's multi-color capability is unlocked in the slicer:

1. Open **Snapmaker Orca**
2. **File → Import → 3D Model** → select the STL
3. To use multiple colors: select the model, click the **Paint** tool
4. Use the brushes (Sphere / Triangle / Fill / Height Range) to paint regions
5. Each painted region maps to one of the 4 toolheads with its loaded filament
6. The color reference image (saved alongside the STL) is a guide for what each region should look like
7. Slice and print

Mention the color reference image specifically — users often miss that it exists.

## Flow 5: Text → 2D → 3D → STL

Run flows 1–3 to produce the clean GLB, then flow 4 to convert to STL. Show user each output before moving to the next, except when they explicitly chain ("make me a 50mm printable treasure chest" implies authorization to run the full chain).

---

## After each generation — update the manifest

The manifest lives at:
- `<project>/assets/asset_manifest.json` in project mode
- `~/3d-pipeline/workspace/asset_manifest.json` in global mode

Update it after every generation:

```bash
python3 ~/.claude/skills/asset-pipeline/scripts/update_manifest.py \
    --manifest <manifest path from above> \
    --name <output_name> \
    --concept <concept_path> \
    --raw <raw_path_or_empty> \
    --clean <clean_path_or_empty> \
    --stl <stl_path_or_empty> \
    --stl-size-mm <size_or_0> \
    --generator <model_name> \
    --polycount <N_or_0> \
    --category <prop|character|hero|environment|weapon|vehicle|2d-only> \
    --notes "<one-line description>"
```

The wrappers print their final output path on their last stdout line — easy to capture for the manifest call.

Skip the manifest only if the user explicitly says they don't want tracking.

---

## When NOT to stage to engine folder

Skip `--no-engine-stage` is the right move when:
- User is experimenting and explicitly says "don't add it to the project yet"
- User is generating placeholder/test assets they'll delete
- User wants to inspect the clean GLB in isolation before exposing it to their game

Otherwise, the auto-staging is what they want — assets appear in Unity/Unreal automatically.

---

## Prompt-writing tips

For 3D-bound 2D prompts, describe:
- **Subject** with specific material/style ("ornate wooden chest with brass fittings" > "chest")
- **View** that captures 3D form (3/4 isometric > pure side > pure front)
- **Lighting** that's even, not dramatic
- **Background** that's clean (the default suffix handles this)

For printable assets, also avoid:
- Heavy overhangs (need support material)
- Thin spikes / delicate filaments (snap during printing)
- Multi-color prompts (color comes from filament in Snapmaker Orca, not the mesh)

If the user describes something hard to print, mention it before generating.

## Common issues

**"Project not detected" but I'm in one.** Make sure the project root has the right markers: Unity needs both `Assets/` and `ProjectSettings/`; Unreal needs `Content/` and a `*.uproject` file at the root. If neither applies, add an empty `.asset-pipeline.json` to mark it as a project.

**Wrong project detected.** User is in a nested git checkout that contains a Unity project at its root. Solutions: (a) `--project /correct/path` override, (b) `PROJECT_ROOT=/correct/path` env var, (c) add `.asset-pipeline.json` to the actual intended project root (closer matches win).

**STL output has visible artifacts.** Run Snapmaker Orca's Auto Repair as a second pass. The Blender print prep handles 90% of cases.

**Model wider than tall, won't fit on bed.** Re-run with a smaller `-s` value. The script scales the longest dimension; the user needs to think about which axis ends up longest.

**Build volume warning.** Asset exceeds 270mm on some axis. Suggest a smaller `-s`.

## What not to do

- Don't try to detect projects yourself — let the wrappers do it. They print context as their first action.
- Don't call print.sh on a raw, uncleaned GLB from `raw/`. Always use the cleaned version from `clean/`.
- Don't promise multi-color printing from the mesh alone. That's a slicer-side operation.
- Don't suggest non-U1 slicers unless asked.
- Don't quietly skip the size question for prints.
- Don't pass `--project` explicitly when the user is already in a project directory — let auto-detection do its job. Pass it only when the user is somewhere else (e.g., their home directory) but wants outputs in a specific project.

## Bundled resources

- `scripts/update_manifest.py` — manifest updater
