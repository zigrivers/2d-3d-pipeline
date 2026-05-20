# Pipeline quality-improvement spec (v3 — gates resolved, MMR-reviewed)

**Status:** ready for implementation · **Author:** asset-pipeline
maintainers · **Target release:** v0.3.x (Tier 1) · v0.3.4 (item 7) ·
v0.4 (item 12) · v0.5 (item 11)

This spec captures fourteen proposed improvements to the 2D-to-3D asset
pipeline. The pipeline serves non-technical users via the
`asset-pipeline` Claude Code skill, so quality, predictability, and
clear feedback matter more than raw flexibility. Items are grouped by
tier; tier reflects impact × implementability, not priority of value.

Each item answers nine questions: problem, approach, dependencies +
license bucket, hardware tier, manifest changes, user-facing output,
failure modes, test strategy, effort (S ≤ 1 day, M ≤ 3 days, L > 3 days).

## What changed from v2 (gate resolutions + second MMR pass)

The three decision gates that v2 left open were resolved 2026-05-20:

- **Item 7 (Hunyuan3D-Paint):** approved; ship as v0.3.4. Decision
  record at [`docs/license-review-hunyuan3d-paint.md`](license-review-hunyuan3d-paint.md).
  Bucket: `commercial_threshold`.
- **Item 11 (ComfyUI consistency mode):** Option A confirmed. ComfyUI
  added as a second 2D backend behind `--backend comfyui`. Sub-PRs
  P3.2a–e.
- **Item 12 (multi-view):** approved with explicit ~3-day backend
  research phase (P3.1a) before implementation (P3.1c+).

The second MMR review pass (after the gate resolutions landed)
surfaced additional gaps that v3 incorporates:

- **`generation` is now a first-class top-level section** of the
  per-asset meta.json — previously the schema only listed
  input/preprocessing/cleanup/quality/print/preview/clip, but items
  4 and 12 needed a place for backend / inputs / model_role data.
  Schema + merge contract updated below.
- **Pipeline-doctor (item 10) now manages Hunyuan3D-Paint, ComfyUI,
  and multi-view caches** — previously item 10 was written before
  these items were approved, so it omitted them. Disk threshold
  raised from 5 GB to 20 GB and made dynamic based on the installed
  component set.
- **Item 7 routing rules** explicitly documented — when to use paint
  vs the existing texture inspect/upscale path.
- **Item 11 sub-PRs reordered** so the consistency-pack format is
  defined (P3.2b) before the parser is implemented (P3.2c).
- **Item 12 input format** now specifies view-angle metadata
  explicitly, with deterministic directory ordering and required-view
  validation.
- **Item 12 research methodology** expanded with a concrete dataset
  protocol, scoring rubric, pass/fail thresholds, and reproducibility
  requirements.
- **Item 12 Flow 9 skill update** now documents the `-i` / `-d` /
  view-angle flags for the skill to invoke correctly.

## What changed from v1 (first MMR pass — retained for historical context)

This is v2. v1 was reviewed by `mmr review` (gemini + codex channels);
17 findings drove the following structural changes. Reviewers cited by
name in the bullet are the source of each change.

- **Single per-asset metadata file** instead of seven sidecars. `<output>.meta.json`
  is the canonical per-asset record, written by a merge helper that all
  passes share. Eliminates the race condition where items 2 and 6 both
  wrote `clean_meta.json` (gemini, codex). Manifest fields land in one
  `quality` block with documented merge precedence (codex).
- **One `pipeline-tools-env` venv** for rembg + CLIP + trimesh, sharing
  Torch / Pillow / numpy. Saves ~15 GB of duplicated dep trees on
  laptop tier (gemini). ComfyUI stays separate (different stack).
- **Three new Tier 1 items**: item 10 (pipeline-doctor + cache
  manager), item 13 (UV / game-engine validation), item 14 (print-
  structural gates). All three were genuine gaps cited by codex.
- **Background removal demoted to conditional default-on.** The cross-
  cutting rule says default-on requires < 1 s + never wrong; rembg
  is 2 s and silently degrades on legitimate inputs with thin geometry
  or transparency (codex). Now runs only when the input-quality check
  detects a non-uniform background, with a foreground-coverage sanity
  check that falls back to the original on suspicious results.
- **Turntable preview demoted to opt-in on laptop.** Same rule
  violation (3–6 s on laptop). Static hero PNG ships default-on
  (cheap); GIF is opt-in or default-on-studio (codex).
- **CLIP scoring repositioned as variant-ranking + soft signal**,
  not an absolute pass/fail threshold. ViT-L/14 scores aren't
  calibrated across prompt length / style / generator (codex).
- **Input format normalisation step added** for WebP / GIF / multi-
  frame inputs before generator dispatch (codex).
- **Scale sanity threshold** added to item 2 (gemini).
- **User-facing translation map** added under cross-cutting design
  principles — turns "non-manifold boundary edge" into "small gap in
  the surface" for skill output (gemini).
- **ComfyUI license clarified** (item 11): the GPL classification
  applies to redistribution of ComfyUI itself, not to image outputs;
  outputs retain the bucket of their generating model (gemini).
- **Item numbering**: the numbering hole at 10 from v1 is now filled
  by the new pipeline-doctor item.

The v1 → v2 diff is available alongside this document and is the
authoritative record of what changed.

---

## Cross-cutting design principles

These apply to every item below. Repeating them once here avoids
restating them eleven (now fourteen) times.

### 1. Additive, never breaking

Every change preserves existing `--json` contracts, existing CLI
flags, and existing default behaviour. New behaviour ships behind a
flag default-on **only when**:

(a) it's fast (< 1 s on the slower of the two hardware tiers), AND
(b) it cannot silently degrade output quality, AND
(c) its failure modes are observable to a non-technical user.

If any of these fails, the feature is opt-in or tier-conditional.
This rule blocks two v1 default-ons: rembg (item 1) and turntable
(item 5).

### 2. One metadata file per asset

Replacing v1's "seven sidecars" pattern. Each generated asset gets
a single `<output>.meta.json` that all quality passes merge into.

Merge contract:

- Each pass calls `scripts/meta_helper.py merge <meta-json-path>
  --section <name> --data <inline-json>`.
- The helper takes an advisory file lock (`fcntl.flock` on macOS) to
  prevent concurrent writes.
- The schema is namespaced: `input`, `preprocessing`, `generation`,
  `cleanup`, `quality`, `print`, `preview`, `clip` are top-level
  sections.
- Each section is owned by exactly one pass. No cross-pass writes.
- Adding a new section requires a CHANGELOG entry; never modifying
  an existing section's shape after release.

Example end-state:

```json
{
  "schema_version": 1,
  "asset_name": "dragon",
  "input": { "width": 1024, "height": 1024, "format": "PNG", "issues": [] },
  "preprocessing": {
    "bg_removal": { "applied": true, "model": "u2net", "alpha_mean": 0.42 },
    "input_normalization": { "applied": false }
  },
  "generation": {
    "backend": "sf3d",
    "model_role": "default",
    "license_bucket": "commercial_threshold",
    "inputs": [{"path": ".../dragon.png"}],
    "polycount_target": 3000,
    "texture_resolution": 2048,
    "duration_seconds": 18.4
  },
  "cleanup": {
    "duplicate_vertices_removed": 47,
    "loose_elements_deleted": 3,
    "holes_filled": 2,
    "decimate": { "before": 18432, "after": 2987 }
  },
  "quality": {
    "manifold": { "is_watertight": true, "hole_count": 0 },
    "textures": { "issues": [] },
    "uv": { "island_count": 14, "occupancy_ratio": 0.78, "has_overlap": false },
    "scale": { "longest_dim_mm": 50.0, "in_sane_range": true }
  },
  "preview": { "hero_png_path": "...", "gif_path": null },
  "clip": { "similarity": 0.84, "model": "ViT-L-14" }
}
```

**Manifest mapping:** `update_manifest.py` gains a single
`--meta-json PATH` arg with a documented mapping table:

| meta.json section | Maps to manifest entry block |
|---|---|
| `input`, `preprocessing` | manifest entry `generation.input` (existing) |
| `generation` | manifest entry `generation` and `model` blocks (existing schema; field-level merge) |
| `cleanup`, `quality`, `preview`, `clip` | manifest entry `quality` block (consolidated under `quality` for searchability) |
| `print` | manifest entry `print` block (existing) |

The merge is field-level (not block-replace), so partial passes —
e.g. generation completes but cleanup crashes — leave the manifest
in a consistent partial state rather than wiping prior fields.

### 3. One `pipeline-tools-env` venv for the new deps

Items 1 (rembg), 2/3/6/13/14 (trimesh + Pillow), 8 (open_clip)
share a single venv at `~/3d-pipeline/pipeline-tools-env/`:

```
trimesh
numpy
Pillow
rembg[cpu]
open_clip_torch
torch  # already brought in by open_clip; reused by rembg
```

ComfyUI (item 11, if it ships) stays in its own venv —
incompatible PyTorch builds / model assumptions.

Estimated disk impact: ~6 GB for the consolidated env vs. ~15 GB
across four separate envs (rembg + clip + trimesh + comfyui).

### 4. License-bucket every new model

Every new dependency that ships weights must declare a bucket in
`_pipeline_lib.sh::license_bucket_for_model`. New buckets only when
the existing five don't fit. Below, each item declares the bucket
for its weights.

### 5. Stderr for human output under `--json`

Any new subprocess must be routed through `json_mode_begin` /
`json_mode_end`, or its noise will corrupt the wrapper's JSON.

### 6. Skill changes are first-class deliverables

A code change that doesn't propagate into `skill/SKILL.md` is
invisible to the non-technical user. Every item lists the skill
change, even when it's one sentence.

### 7. Doc regeneration is required

Any script change must be followed by `make regenerate && make verify`.
The pre-commit hook enforces this; CI re-checks. Bundle
(`make bundle`) must still build.

### 8. User-friendly translations (jargon map)

The skill should speak the user's language, not the engine's. A
shared translation table lives in `skill/SKILL.md` and the
wrappers reference it for any user-facing message:

| Engine term | User-facing translation |
|---|---|
| "non-manifold edge" | "small gap in the surface" |
| "watertight ✓" | "fully sealed (good for printing)" |
| "is_watertight=false, hole_count=3" | "3 small gaps in the surface — may print fine but worth knowing" |
| "boundary edge" | "open edge" |
| "UV island" | "texture patch" |
| "decimate ratio 0.16" | "simplified mesh: 18,400 → 3,000 polygons" |
| "alpha_mean 0.42" | "subject takes up about 42% of the image" |
| "CLIP similarity 0.84" | "image matches your prompt: very good (0.84/1.0)" |
| "CLIP similarity 0.71" | "image matches your prompt: weak (0.71/1.0) — consider re-generating" |
| "non-manifold internal shell" | "hidden geometry inside the mesh" |
| "wall thickness 0.4mm" | "thinnest part is 0.4mm — may fail to print" |

The wrapper outputs the raw value in `--json`; the skill text
translates when speaking to the user.

### 9. Sidecar files never write next to user inputs

User inputs may be read-only, in unexpected directories, or
collision-prone with other jobs reusing the same basename. All
sidecars live under `$ASSETS_ROOT` next to their generated output,
not next to the input.

### 10. Failure mode default: warn, don't block

Quality gates report; they don't refuse. Exceptions: the existing
all-axis 270 mm check (blocking by design) and any new dimension
that would produce a silently corrupt asset.

---

# Tier 1 — high impact, automatable

## 1. Conditional background removal before image→3D

### Problem

`generate.sh` accepts any image and feeds it directly to SF3D / SPAR3D
/ TRELLIS. Non-uniform backgrounds bleed into mesh geometry. The
2026 best-practice survey identifies background removal as the
single highest-impact preprocessing step for image-to-3D quality.

**MMR-noted risk (codex P1):** Background removal isn't safe to apply
blindly. Inputs with intentional transparency, thin geometry (hair,
filaments), reflective bases, or shadow context can be silently
damaged by rembg. v2 makes the step **conditional** rather than
unconditional default-on.

### Approach

New script `scripts/rembg_preprocess.py` — thin wrapper around the
`rembg` library. Takes `--input PATH --output PATH [--model u2net|isnet-general-use]`.
Lives in `pipeline-tools-env`.

New helper `process_input_image` in `_pipeline_lib.sh` decides
whether to run rembg based on signals from item 4 (input image
quality check):

```
case "$BG_REMOVAL_MODE" in
    auto)
        # The input quality check already wrote $ASSETS_ROOT/<basename>.meta.json
        # with input.background_uniformity. Read it; run rembg only when
        # the background is non-uniform AND the image isn't already RGBA-with-
        # low-alpha-coverage (i.e. already cropped).
        ;;
    on)   # explicit --bg-removal
        ;;
    off)  # explicit --no-bg-removal
        ;;
esac
```

Detection logic for `auto`:

- Skip rembg if input is RGBA with alpha coverage < 80% (already cropped).
- Skip rembg if input is grayscale (probably a sketch / line art).
- Skip rembg if input.background_uniformity score > 0.85 (probably
  already a clean studio image).
- Run rembg otherwise.

Sanity check after rembg:

- Compute foreground coverage on the result (alpha mean).
- If `foreground_coverage < 0.05`, rembg likely destroyed the subject.
  Fall back to the original input. Log `preprocessing.bg_removal.fallback="subject_lost"`.
- If `foreground_coverage > 0.95`, rembg didn't actually remove
  anything. Log `preprocessing.bg_removal.applied=false, reason="nothing_to_remove"`.

`generate.sh` flag: `--bg-removal {auto,on,off}` (default `auto`).

New `.asset-pipeline.json` field `defaults.bg_removal_mode` (default
`auto`).

Output path: rembg writes to `$ASSETS_ROOT/concept/<asset_name>_nobg.png`
(under ASSETS_ROOT, not next to the input — addresses codex P1 on
sidecar locations).

### Dependencies

- `rembg[cpu]` (PyPI) — MIT — `commercial_safe`
- `u2net.onnx` (Apache 2.0) — `commercial_safe` (default)
- `isnet-general-use.onnx` (Apache 2.0) — `commercial_safe` (better,
  slower; opt-in)
- Lives in `pipeline-tools-env` (shared with items 2/3/6/8/13/14)
- Model cache: `~/3d-pipeline/models/rembg/` (env var `U2NET_HOME`)

License-bucket addition: `rembg_u2net` → `commercial_safe`.

### Hardware tier

Both. CPU-only build is < 2 s on a 1024×1024 image on either tier.

### Manifest schema changes

Lives under `preprocessing.bg_removal` in the per-asset meta.json
(see cross-cutting principle 2):

```json
"preprocessing": {
  "bg_removal": {
    "applied": true,
    "mode": "auto",
    "trigger": "non_uniform_background",
    "model": "u2net",
    "alpha_mean": 0.42,
    "fallback": null,
    "duration_seconds": 1.3
  }
}
```

`update_manifest.py` merges via `--meta-json PATH`.

### User-facing output

```
[pipeline] Background removal: auto mode, ran u2net (1.3s)
[pipeline]   Subject covers 42% of the frame.
```

When skipped:

```
[pipeline] Background removal: skipped (image is already cropped)
```

When fallback:

```
[pipeline] Background removal: result discarded (subject was lost)
[pipeline]   Used the original image instead.
```

Skill change in Flow 2: same as v1 but mention the `auto` mode
explicitly and tell the user when to override (e.g. "this is a sketch,
not a photo — pass `--no-bg-removal`").

### Failure modes

Per the cross-cutting "warn, don't block" rule:

- Rembg not installed → log + use original image.
- Rembg crash → log + use original image.
- Subject lost (foreground < 5%) → fall back to original (already in
  the approach).
- ONNX model not downloaded on first run → emit a clear "first run:
  downloading u2net (~170 MB)…" message via item 10's progress mechanism.

### Test strategy

- Clean studio image → expect `applied=false, reason="already_cropped"` or
  `reason="nothing_to_remove"`.
- Photo with cluttered background → expect `applied=true, alpha_mean ∈ [0.2, 0.7]`.
- Grayscale sketch → expect `applied=false, reason="grayscale"`.
- 1024×1024 of pure black → expect `applied=true` followed by
  `fallback="subject_lost"`.

### Effort

**M.** Most work is the venv setup + setup-guide HTML embeds + the
auto-detection plumbing + the sanity checks.

---

## 2. Watertight + scale sanity check

### Problem

`clean_asset.py` runs five hygiene passes silently. No watertight
check; no scale validation. Users don't learn about problems until
they slice or import.

**MMR-noted gap (gemini P2):** AI generators sometimes produce
assets at the wrong scale entirely — microscopic (0.01 mm bounding
box) or massive (5,000 mm). Currently undetected.

### Approach

Two scripts touched.

**`scripts/clean_asset.py`** — after the existing 6-pass cleanup and
export, invoke a separate check via the `pipeline-tools-env` venv:

```python
# Called via subprocess from generate.sh, not from inside Blender's Python.
# This avoids fragile Blender-version-specific trimesh installs.
import trimesh
mesh = trimesh.load(output_path, force='mesh')
meta = {
    "manifold": {
        "is_watertight": bool(mesh.is_watertight),
        "is_winding_consistent": bool(mesh.is_winding_consistent),
        "boundary_edges": int(...),
        "hole_count": int(...),
    },
    "scale": {
        "longest_dim_normalized": float(max(mesh.extents)),
        "in_sane_range": bool(0.001 < max(mesh.extents) < 1000.0),
    },
    "polycount": int(len(mesh.faces)),
}
# Merge into <output>.meta.json via meta_helper.py
```

Scale sanity at the clean stage uses normalised units (the cleaned
GLB is normalised so longest dim ≈ 1.0). The check confirms that
normalisation worked. Print stage (next paragraph) checks real-world
mm.

**`scripts/prepare_for_print.py`** — extend `write_meta()` similarly,
but the scale check is in mm:

```python
"scale": {
    "longest_dim_mm": dims_mm[max_axis_index],
    "in_sane_range": 1.0 < longest_dim_mm < 1000.0
}
```

The 1 mm / 1000 mm bounds reject anything that's almost certainly
a mistake. The existing 270 mm Snapmaker U1 check is unchanged
(it still blocks export when exceeded without `--allow-oversize`).

Both scripts use the merge helper from cross-cutting principle 2.

### Dependencies

- `trimesh` — MIT — `commercial_safe` (in `pipeline-tools-env`)
- `numpy` — BSD — `commercial_safe` (already transitively)

### Hardware tier

Both. trimesh check is sub-second up to ~250 k polys.

### Manifest schema changes

Under `quality.manifold` and `quality.scale` in the per-asset
meta.json. Merged into the manifest entry's `quality` block by
`update_manifest.py --meta-json PATH`.

### User-facing output

Using the translation map:

```
[pipeline] Mesh: fully sealed (good for printing) — 2,987 polygons
```

Or:

```
[pipeline] Mesh: 3 small gaps in the surface (may still print)
[pipeline]   Tip: Snapmaker Orca's Auto Repair often fixes these.
```

Scale warning:

```
[pipeline] Scale: ⚠ asset is unusually small (longest dimension 0.003 of normalised unit)
[pipeline]   This is usually a generator bug. Try a different seed or generator.
```

Skill change in Flow 2 + Flow 4: relay the translated message, not
the raw terms. Don't say "non-manifold" or "boundary edge".

### Failure modes

- trimesh import fails → meta omits `quality.manifold`; wrapper
  prints "(quality check unavailable — pipeline-tools-env missing)".
- GLB unreadable → meta writes `quality.manifold.error="load_failed: ..."`.
- Mesh > 250 k polys → check still completes but warns; gate behind
  `--skip-quality-check` if it becomes a bottleneck.

### Test strategy

- Generate a known-good asset → expect `is_watertight=true,
  scale.in_sane_range=true`.
- Generate against a deliberately broken input → expect
  `is_watertight=false, hole_count > 0`.
- Hand-corrupt a clean GLB (delete a face in Blender) → re-run
  check → expect `is_watertight=false, hole_count=1`.

### Effort

**S.** trimesh integration is ~50 lines; merge helper handles the
sidecar plumbing.

---

## 3. Texture quality validation

### Problem

SF3D + SPAR3D ship PBR textures but sometimes produce degenerate
ones: pure-black albedo, flat roughness/metallic, zero-magnitude
normal maps. TRELLIS-on-Mac emits vertex colours only.

No detection today. Users discover broken textures during engine
import.

### Approach

New script `scripts/texture_quality_check.py` (in `pipeline-tools-env`).
Runs after `clean_asset.py`, before engine staging. Uses trimesh
to extract embedded PIL images from the cleaned GLB.

Checks per map:

| Map | Check | Issue tag |
|---|---|---|
| Albedo | mean luminance < 8/255 | `flat-black-albedo` |
| Albedo | stdev < 5 across image | `flat-color-albedo` |
| Roughness | stdev < 2 across image | `uniform-roughness` |
| Metallic | stdev < 2 across image | `uniform-metallic` |
| Normal | XY magnitude (offset from 128) mean < 8/255 | `low-detail-normal` |
| Any map | mean > 250 and stdev < 2 | `uninitialised` |

Writes to the per-asset meta.json under `quality.textures`:

```json
"quality": {
  "textures": {
    "textures_present": ["albedo", "roughness", "metallic", "normal"],
    "issues": ["flat-black-albedo"],
    "stats": {
      "albedo": {"mean": 4.2, "stdev": 1.8, "luminance": 4.1},
      "roughness": {"mean": 192.0, "stdev": 1.2},
      "metallic": {"mean": 8.0, "stdev": 0.5},
      "normal": {"xy_magnitude_mean": 14.2}
    }
  }
}
```

### Dependencies

`trimesh`, `Pillow`, `numpy` — all in `pipeline-tools-env`. No
new deps over item 2.

### Hardware tier

Both. Sub-second on any texture size used by the pipeline.

### Manifest schema changes

Under `quality.textures` in the per-asset meta.json. Merged into
manifest via `--meta-json`.

### User-facing output

When clean:

```
[pipeline] Textures: 4 maps, all look healthy
```

When issues:

```
[pipeline] Textures: ⚠ the colour map is almost entirely black
[pipeline]   This usually means the generator couldn't read the input image's
[pipeline]   colours. Try a different generator (SPAR3D) or a better-lit input.
```

Each issue tag has a fixed user-facing translation in the skill.

### Failure modes

- GLB has no embedded textures (TRELLIS on Mac) → `textures_present=[]`,
  `issues=["no_textures"]`. Informational; the skill mentions
  vertex-colour mode is in effect.
- Pillow can't decode a specific map → per-map `error="decode_failed"`.
- All maps uninitialised → strong signal of generator failure; skill
  should recommend re-run.

### Test strategy

- Generate a known-good SF3D asset → expect `issues=[]`.
- Generate against a deliberately-black input → expect `issues
  contains "flat-black-albedo"`.
- Run against a TRELLIS output → expect `issues=["no_textures"]`.

### Effort

**S.** ~80 lines of Python; thresholds may need calibration after
real-world runs.

---

## 4. Input image quality check + format normalisation

### Problem

`generate.sh` accepts any image without validating suitability.
Low-resolution, extreme aspect ratios, watermarks, and multi-subject
images all degrade output silently.

**MMR-noted gap (codex P1):** The v1 spec promised PNG/JPG/WEBP
support but never normalised WebP / multi-frame inputs to a static
PNG. SF3D / SPAR3D / TRELLIS document PNG/JPG only; passing WebP
through silently risks downstream failure inside the generator.

### Approach

New helper `check_and_normalize_input` in `_pipeline_lib.sh`, called
at the top of `generate.sh` after the existence check but before
background removal.

**Checks (read-only):**

| Check | Trigger | Action |
|---|---|---|
| Resolution | width OR height < 512 | warn |
| Resolution | < 384 px | warn loudly; suggest upscale-first |
| Aspect ratio | > 2:1 or < 1:2 | warn |
| Background uniformity | edge-pixel stdev < threshold | informational; consumed by item 1 |
| File size | < 5 KB | warn |
| Format | not in {png, jpg, jpeg, webp, gif} | error |

**Normalisation (writes a converted file):**

- WebP → PNG, single-frame: convert via Pillow, write to
  `$ASSETS_ROOT/concept/<basename>_normalized.png`. Record
  conversion in meta.json.
- Animated GIF / multi-frame WebP → first frame to PNG, warn that
  remaining frames are ignored.
- JPEG → kept as JPEG (SF3D accepts it).
- PNG → kept as PNG.

After normalisation, `INPUT` in `generate.sh` points at the
normalised PNG, not the original. The original path is recorded in
meta.json.input.original_path.

Writes to per-asset meta.json:

```json
"input": {
  "original_path": "/Users/.../downloads/dragon.webp",
  "normalized_path": "/.../assets/concept/dragon_normalized.png",
  "format_original": "WEBP",
  "format_normalized": "PNG",
  "width": 1024,
  "height": 1024,
  "aspect_ratio": 1.0,
  "background_uniformity": 0.72,
  "issues": []
}
```

Sidecar location: under `$ASSETS_ROOT/concept/`, never next to the
user-supplied input (codex P1).

### Dependencies

Pillow only (already present). No new deps.

### Hardware tier

Both.

### Manifest schema changes

Under `input` in the per-asset meta.json. Merged via `--meta-json`.

### User-facing output

```
[pipeline] Input: 1024×1024 PNG (RGBA, 187 KB)
```

With normalisation:

```
[pipeline] Input: 1024×1024 WebP → converted to PNG (one-time, 0.1s)
```

With issues:

```
[pipeline] Input: 320×240 JPEG ⚠
[pipeline]   Below recommended minimum (512px). Output quality will suffer.
[pipeline]   Consider running texture.sh --mode upscale --scale 2 first.
```

Skill change in Flow 2: relay quality issues. Don't block; let the
user decide.

### Failure modes

- Pillow can't open → wrapper exits 1 (real fault).
- Animated GIF → first-frame extraction with warning.
- Unsupported format → wrapper exits 1 with the list of supported
  formats.

### Test strategy

- 320×240 PNG → expect `issues=["low_resolution"]`.
- WebP → expect normalisation + `format_original="WEBP"`.
- Animated GIF → expect first-frame extraction + warning.
- Known-good 1024×1024 PNG → expect `issues=[]`.

### Effort

**S.** ~120 lines now (was ~80 in v1) — normalisation adds the bulk.

---

## 5. Turntable preview render (hero PNG default, GIF opt-in on laptop)

### Problem

After 3D generation, the user has a clean GLB but no quick preview.
The skill tells them the path; they then context-switch to a viewer.

Leading commercial tools all show a preview before the full job
completes.

**MMR-noted issue (codex P1):** v1 made the 12-frame GIF render
default-on at 3–6 s on laptop. That violates the cross-cutting
"default-on must be < 1 s and never wrong" rule, increases every
generation's latency, and is noisy in queue/headless runs.

### Approach

Three render modes:

| Mode | Output | Cost | Default by tier |
|---|---|---|---|
| `none` | nothing | 0 s | (never the default) |
| `png` | single hero render (1024×1024, 32 samples, Eevee) | ~1 s laptop / < 0.5 s studio | **laptop default**, studio default |
| `gif` | hero PNG + 12-frame 360° turntable GIF (512×512) | ~3–6 s laptop / ~1.5 s studio | **studio default**, laptop opt-in |

Hero PNG is cheap and never wrong (a single render is bounded);
ships default-on across both tiers.

GIF adds 12× the render cost; default-on only on studio.

`scripts/turntable_render.py` (Blender headless) implements both
modes via a `--mode {png,gif}` flag. Writes to:

- `$ASSETS_ROOT/preview/<name>.png` (hero)
- `$ASSETS_ROOT/preview/<name>.gif` (turntable, if requested)

`generate.sh` flags:

- `--preview {none,png,gif}` (default depends on `hardware_tier`)
- `--no-preview` (alias for `--preview none`)

Add `mkdir -p "$ASSETS_ROOT/preview"` to
`_pipeline_lib.sh::resolve_project_context`.

In `--json` queue mode (i.e. `queue_worker.py` invocations), the
worker overrides preview default to `none` — queue jobs have no
interactive viewer.

### Dependencies

- Blender (present)
- Pillow (present, in `pipeline-tools-env`) for GIF assembly
- No new venvs

### Hardware tier

Both, with different defaults (see table above).

### Manifest schema changes

Under `preview` in the per-asset meta.json:

```json
"preview": {
  "mode": "png",
  "hero_png_path": "/path/to/preview/dragon.png",
  "gif_path": null,
  "frames": 1,
  "resolution": 1024,
  "duration_seconds": 1.1
}
```

### User-facing output

```
[pipeline] Preview: hero render → /path/to/preview/dragon.png (1.1s)
```

GIF mode:

```
[pipeline] Preview: 12-frame turntable → /path/to/preview/dragon.gif (3.4s)
[pipeline]   Hero PNG: /path/to/preview/dragon.png
```

Skill change in Flow 2 + Flow 5:

> The wrapper now produces a hero PNG by default. Surface the
> absolute path to the user. On studio tier, a turntable GIF is
> also produced. Don't tell the user to run an extra command;
> let them know it already exists.

### Failure modes

- Blender render fails → meta records error; wrapper continues
  without the preview.
- GIF assembly fails → fall back to PNG-only with a warning.
- Render time exceeds 30 s → abort the subprocess; same fallback.

### Test strategy

- Known-good generation on laptop → expect hero PNG, no GIF.
- Same on studio → expect both files.
- `--preview none` → expect neither.
- Kill the Blender subprocess mid-render → expect graceful
  continuation.

### Effort

**M.** Blender Python ~150 lines (Eevee setup + light rig + camera +
render loop) + the mode-switching logic in the wrapper. Slightly
more work than v1 because of the mode split.

---

## 6. Cleanup report — instrument `clean_asset.py`

### Problem

`clean_asset.py` runs five hygiene passes silently. Users don't
know what was wrong with the raw output. That information is
valuable for judging generator quality.

### Approach

Instrument each pass in `clean_asset.py` to count what changed:

| Pass | Counted |
|---|---|
| `remove_doubles(0.0001)` | vertices removed (vertex-count delta) |
| `delete_loose` | loose elements deleted (delta) |
| `fill_holes(sides=6)` | holes filled (boundary-edge-count delta) |
| `decimate` | polys before / after / ratio |
| `normals_make_consistent` | applied (no count exposed) |

Writes under `cleanup` in the per-asset meta.json **via the merge
helper** (this is the change from v1 that fixes the codex/gemini
race-condition P1):

```json
"cleanup": {
  "duplicate_vertices_removed": 47,
  "loose_elements_deleted": 3,
  "holes_filled": 2,
  "decimate": { "before": 18432, "after": 2987, "ratio": 0.162 },
  "duration_seconds": 4.2
}
```

The merge helper guarantees this doesn't clobber `quality.manifold`
or `quality.scale` from item 2 — both passes write to different
sections of the same file with file-lock-protected merges.

`generate.sh` surfaces a translated one-liner:

```
[pipeline] Cleanup: removed 47 duplicate points, filled 2 small gaps,
[pipeline]          simplified mesh: 18,400 → 3,000 polygons
```

### Dependencies

None new (pure Blender Python API).

### Hardware tier

Both.

### Manifest schema changes

Under `cleanup` in per-asset meta.json. Merged via `--meta-json`.

### User-facing output

See above. Single line under non-`--json`; full block under `--json`.

### Failure modes

- Mid-pass exception → record `null` for that field, continue.
- Decimate modifier failed → record `decimate.error=<message>`.

### Test strategy

- Run against a known-dirty input (SPAR3D output) → expect
  `holes_filled > 0` or `duplicate_vertices_removed > 0`.
- Re-clean an already-clean asset → expect all counts ≈ 0.

### Effort

**S.** Mostly threading deltas through `clean_asset.py`. Schema
already exists from item 2.

---

## 10. Pipeline doctor + cache manager (NEW — Tier 1)

### Problem

**MMR-noted gap (codex P1, gemini P2):** v1 added rembg (~170 MB),
CLIP ViT-L/14 (~890 MB), and optionally SDXL + IP-Adapter +
ControlNet (~10 GB). First-run downloads happen lazily, with no
preflight disk check, no progress UX, no graceful handling of
partial downloads, no offline behaviour.

For non-technical users, this means: a generation request triggers
a multi-GB download with no indication that anything is happening
beyond a stalled terminal. Or: disk fills mid-download and the
asset never finishes generating.

This item makes installation, caching, and runtime checks first-class.

### Approach

New CLI `scripts/pipeline_doctor.py` invoked as:

```bash
pipeline_doctor.py [--check {disk,models,venvs,wrappers,all}] [--fix] [--json]
```

Behaviours per check:

- **disk**: scan model cache dirs, report total used and free space
  remaining on the relevant volumes. Disk threshold is **dynamic**:
  compute the *required* free space as the sum of (uninstalled
  approved components × their declared sizes from
  `model_manifest.json`) + a 5 GB working margin. Warn when free
  space < required. Hard floor: warn unconditionally if free < 20 GB
  (covers the worst-case where every approved component is missing
  on a laptop tier).
- **models**: enumerate models the pipeline expects, check each is
  fully downloaded (not a partial), check the sha256 against a known
  manifest in `scripts/model_manifest.json`. List "missing" /
  "partial" / "ok" per model.
- **venvs**: confirm `mflux-env`, `pipeline-tools-env`, optional
  `comfyui-env`, `hunyuan3d-paint-env`, `multiview-env` exist with
  the expected packages installed and at acceptable versions.
  Optional venvs are flagged as missing only if their corresponding
  feature was requested (e.g. `comfyui-env` only matters if the
  user enables consistency mode).
- **wrappers**: spot-check each wrapper's `--help` works (catches
  recent edits that broke arg parsing).
- **all**: runs every check.

`--fix` mode:

- Creates missing venvs (calls the relevant setup commands from
  the setup guides).
- Downloads missing models with progress bars (uses `tqdm` via the
  underlying lib's hooks where possible; else a wrapper).
- Removes partial downloads.
- Cannot fix disk pressure — only reports it.

New CLI `scripts/pipeline_warmcache.py` (or `pipeline_doctor.py --warm-cache`):

- Pre-downloads every model the pipeline might need, scoped to the
  approved component set.
- Progress bar per model.
- Tier 1 only (default): ~2 GB (rembg u2net + open_clip ViT-L/14).
- All approved components (Tier 1 + 2 + 3): ~17 GB
  (+ ~5 GB Hunyuan3D-Paint, + ~10 GB ComfyUI stack, + chosen
  multi-view backend size — TBD post-research).
- `--warm-cache --include hunyuan3d-paint,comfyui` selects opt-in
  heavy components. Default downloads only Tier 1.
- Recommend running once after install before first asset job.

Cache locations (all under `~/3d-pipeline/models/`):

```
~/3d-pipeline/models/rembg/             # u2net.onnx, isnet-general-use.onnx (~170 MB)
~/3d-pipeline/models/clip/              # ViT-L-14 weights (~890 MB)
~/3d-pipeline/models/sf3d/              # already there
~/3d-pipeline/models/spar3d/            # already there
~/3d-pipeline/models/trellis/           # already there
~/3d-pipeline/models/hunyuan3d-paint/   # item 7 paint model (~5 GB)
~/3d-pipeline/models/sdxl/              # item 11 SDXL base (~7 GB)
~/3d-pipeline/models/ip-adapter/        # item 11 IP-Adapter FaceID (~700 MB)
~/3d-pipeline/models/controlnet/        # item 11 OpenPose + Canny (~2 GB)
~/3d-pipeline/models/multiview/         # item 12 chosen backend (size TBD)
```

Each lib gets its env var set in the wrappers so caches stay in
the pipeline-managed locations:

```
export U2NET_HOME="$HOME/3d-pipeline/models/rembg"
export OPEN_CLIP_CACHE_DIR="$HOME/3d-pipeline/models/clip"
export HUNYUAN3D_HOME="$HOME/3d-pipeline/models/hunyuan3d-paint"
export COMFYUI_MODELS_DIR="$HOME/3d-pipeline/models"  # ComfyUI re-uses sdxl/ ip-adapter/ controlnet/ subdirs
```

`scripts/model_manifest.json` carries the authoritative per-model
list with size estimates + sha256s; pipeline-doctor reads this for
both the disk check and the warm-cache scoping.

### Dependencies

- `tqdm` (PyPI) — MIT — `commercial_safe` (in `pipeline-tools-env`)
- `requests` (PyPI) — Apache 2.0 — `commercial_safe` (in
  `pipeline-tools-env`)

### Hardware tier

Both. Identical implementation.

### Manifest schema changes

None. This tool operates outside the per-asset meta.json.

### User-facing output

`pipeline_doctor.py --check all`:

```
Pipeline status check
─────────────────────

Disk:           ✓ 47 GB free on / (model caches use 4.2 GB)
                Required for approved components: 2.1 GB (Tier 1 only)
                ⚠ enable consistency mode (item 11) and you'll need ~17 GB more
Venvs:          ✓ mflux-env, pipeline-tools-env
                ⚠ hunyuan3d-paint-env missing (needed for texture.sh --mode paint)
                ⚠ comfyui-env missing (only needed for consistency mode)
                ⚠ multiview-env missing (only needed for multi-view reconstruction)
Models:         ✓ sf3d, u2net, ViT-L-14, real-esrgan
                ⚠ isnet-general-use missing (optional alternative bg-removal model)
                ⚠ hunyuan3d-paint missing (needed for paint mode; ~5 GB)
                ⚠ sdxl, ip-adapter, controlnet missing (needed for consistency mode; ~10 GB)
Wrappers:       ✓ concept.sh, generate.sh, print.sh, texture.sh, benchmark.sh

Run with --fix to install missing optional components.
Run --warm-cache --include hunyuan3d-paint to pre-download paint model.
```

`pipeline_warmcache.py`:

```
Pre-downloading pipeline models…
  u2net.onnx        [████████████████████]  170 MB / 170 MB  done
  ViT-L-14.pt       [████████████████████]  890 MB / 890 MB  done

Done. 1.06 GB downloaded. Subsequent runs will be fast.
```

Skill change — new section near the top of `SKILL.md`:

> Before any asset work in a fresh install, run
> `pipeline_doctor.py --check all` to confirm everything is set up
> and `pipeline_warmcache.py` to pre-fetch model weights. The first
> generation after install can otherwise stall on a multi-GB download
> the user can't see. Mention this to the user proactively when you
> notice generators failing with "model not found" or downloads
> taking visibly long.

### Failure modes

- Network unavailable during warm-cache → tool reports failed
  downloads; can be re-run later.
- Disk full mid-download → cleanup partial file; report disk pressure.
- Sha256 mismatch on a model → flag as `partial/corrupt`; suggest
  `--fix` to redownload.

### Test strategy

- Run on a clean install → expect all checks to identify what's
  needed.
- Delete a partial download → run again → expect `partial` flag.
- Run `--warm-cache` on a clean install, time it, check the
  cache directories.

### Effort

**M.** ~250 lines of Python + the manifest data file + setup-guide
mentions. Highest UX leverage of any Tier 1 item — likely
implement first.

---

## 13. UV + game-engine validation (NEW — Tier 1)

### Problem

**MMR-noted gap (gemini P1, codex P1):** AI-generated meshes
frequently have spaghetti UVs (hundreds of micro-islands),
non-standard normal-map handedness, missing tangents, wrong color-
space encoding, or non-power-of-two texture sizes. Watertight
geometry plus visually-plausible textures can still produce engine-
import failures or visibly wrong materials in Unity/Unreal.

The existing pipeline never checks any of this.

### Approach

Extend `scripts/texture_quality_check.py` (item 3) to cover the
geometry-side too. Alternatively, split into
`scripts/game_asset_check.py` to keep the texture and geometry
checks decoupled. Recommendation: split.

`scripts/game_asset_check.py` runs after `clean_asset.py`, in
`pipeline-tools-env`. Uses trimesh + Pillow.

Checks:

| Subject | Check | Threshold / value |
|---|---|---|
| UV unwrap presence | Has primary UV channel? | bool |
| UV island count | Number of disjoint UV charts | warn if > 50, error if > 500 |
| UV occupancy | Fraction of UV space covered by islands | warn if < 0.40 |
| UV overlap | Any islands overlap? | warn if true (causes texture bleeding) |
| UV bounds | All UVs in [0,1]? | warn if false |
| Tangents | Mesh has tangent data? | warn if missing (engine will compute, may differ) |
| Normal map handedness | Y-axis convention (+Y up / -Y up) | check against expected (Unity = -Y, Unreal = +Y) |
| Texture sizes | All textures power-of-two? | informational (mobile/older engines care) |
| Color-space hints | sRGB/linear flag on each map? | warn if albedo not sRGB or normal not linear |
| Embedded image format | All embedded as PNG/JPEG? (not BMP/TIFF) | error if exotic |
| Texture count | Total embedded textures | informational |

Writes under `quality.uv` and `quality.engine` in per-asset meta.json:

```json
"quality": {
  "uv": {
    "has_uv": true,
    "island_count": 14,
    "occupancy_ratio": 0.78,
    "has_overlap": false,
    "in_bounds": true
  },
  "engine": {
    "tangents_present": true,
    "normal_handedness": "y_minus",   // Unity convention
    "texture_sizes": [2048, 2048, 2048, 2048],
    "all_power_of_two": true,
    "embedded_formats": ["png", "png", "png", "png"],
    "color_space_hints": {"albedo": "sRGB", "normal": "linear"}
  }
}
```

The skill uses this to surface issues specific to the user's target
engine. E.g. when the project is detected as Unity, warn if
`normal_handedness != "y_minus"`.

### Dependencies

`trimesh`, `Pillow`, `numpy` — all in `pipeline-tools-env`. No new
deps.

### Hardware tier

Both.

### Manifest schema changes

Under `quality.uv` and `quality.engine` in per-asset meta.json.

### User-facing output

```
[pipeline] UVs: 14 texture patches covering 78% of the UV space (good)
[pipeline] Engine: ready for Unity (Y-down normals, sRGB albedo, all PoT textures)
```

When issues:

```
[pipeline] UVs: ⚠ 312 micro-patches — texture detail will be very fragmented
[pipeline]   Consider re-generating; this generator often produces poor UVs.
```

```
[pipeline] Engine: ⚠ normals expect +Y up but your project is Unity (-Y up)
[pipeline]   Unity may import this with inverted bumps. Try a different generator.
```

Skill change in Flow 2: after generation, check `quality.uv` and
`quality.engine`. If the project is Unity or Unreal, surface engine-
specific warnings using the translation map.

### Failure modes

- No UV channel (rare for SF3D / TRELLIS) → record `has_uv=false`,
  warn that this asset can't take textures in-engine without a UV
  unwrap pass.
- Overlap detection slow on dense UVs → bounded by polycount; not
  a real risk for assets in this pipeline.

### Test strategy

- Known-good SF3D output → expect `island_count < 50`,
  `occupancy_ratio > 0.4`, no overlap.
- Hand-broken mesh (delete UV channel in Blender) → expect
  `has_uv=false`.
- TRELLIS Mac output (vertex colours, no textures) → expect
  `texture_sizes=[]`, `has_uv=false` or low confidence.

### Effort

**M.** UV island count + overlap require non-trivial trimesh code (or
shelling to `xatlas`). Normal-handedness detection is a heuristic
(sample normal map XY, compare to vertex normals on a few faces).

---

## 14. Print structural gates (NEW — Tier 1)

### Problem

**MMR-noted gap (codex P1):** Watertight is necessary but not
sufficient for printability. A watertight STL can still:

- Have walls thinner than the nozzle can produce (< 0.4 mm on FDM,
  < 0.1 mm on resin) — print will fail mid-layer
- Have small disconnected islands (printer skips, supports needed)
- Have severe overhangs (need support material)
- Have fragile spikes / filaments (snap during printing)
- Have a near-zero base contact area (won't stick to the bed)
- Be top-heavy (tips during printing)

The v1 spec promised watertight; v2 needs the structural check too.

### Approach

New script `scripts/print_structural_check.py` (in
`pipeline-tools-env`). Runs at the end of `prepare_for_print.py`,
between watertight check and meta-write.

Uses trimesh + numpy. Checks:

| Subject | Method | Threshold |
|---|---|---|
| Min wall thickness | trimesh sample + nearest-neighbour distance heuristic | warn < 1.0 mm; error < 0.4 mm |
| Disconnected islands | `mesh.split()` count | informational |
| Self-intersections | trimesh `repair.broken_faces` count | warn > 0 |
| Overhang area | faces whose normal has Z < -cos(45°) | informational; total area in mm² |
| Base contact area | bottom-N% of mesh, project to Z=0, polygon area | warn < 100 mm² for small assets |
| Center of mass vs base | XY of COM vs XY centroid of base | warn if COM > 0.5× base radius offset (tipping risk) |
| Fragile features | small isolated branches (heuristic: mesh.body_count > 1) | informational |

Writes under `print.structural` in per-asset meta.json:

```json
"print": {
  "structural": {
    "min_wall_thickness_mm": 0.8,
    "wall_thickness_safe": false,
    "disconnected_islands": 1,
    "self_intersections": 0,
    "overhang_area_mm2": 142.0,
    "base_contact_area_mm2": 287.5,
    "base_contact_safe": true,
    "com_offset_normalized": 0.18,
    "stable_on_bed": true
  }
}
```

The min-wall-thickness check is approximate (true convex distance
field is expensive); document the heuristic in the script. False
positives possible. Frame the message as advisory.

### Dependencies

`trimesh`, `numpy`, `scipy` (for KDTree) — add `scipy` to
`pipeline-tools-env` (~30 MB, BSD, `commercial_safe`).

### Hardware tier

Both. Sub-2-second for assets in this pipeline.

### Manifest schema changes

Under `print.structural` in the per-asset meta.json (printable
flow only).

### User-facing output

```
[pipeline] Print structure: looks printable
[pipeline]   Walls ≥ 0.8mm (good), base ≥ 287mm² (good), stable on bed
```

When issues:

```
[pipeline] Print structure: ⚠ thin walls detected
[pipeline]   Thinnest section is 0.3mm — likely too thin for FDM (need ≥ 0.4mm)
[pipeline]   Options:
[pipeline]     • Scale the model up (re-run with a larger -s value)
[pipeline]     • Re-print on the resin printer if you have one
```

Skill change in Flow 4 + Flow 5: surface structural warnings before
handing off to Orca. Don't say "non-manifold internal shell"; say
"hidden geometry inside the mesh". For thin walls, suggest scaling
or different printer.

### Failure modes

- KDTree fails on extremely sparse meshes → mark `min_wall_thickness_mm=null`,
  continue.
- Self-intersection detection times out (rare) → skip with warning.

### Test strategy

- Known-printable asset (e.g. a 50 mm chest) → expect
  `wall_thickness_safe=true, stable_on_bed=true`.
- Generate a small (5 mm) figurine → expect thin-wall warning.
- Generate a tall top-heavy asset → expect tipping-risk warning.

### Effort

**M.** Wall-thickness heuristic is the trickiest part. The other
checks are straightforward.

---

# Tier 2 — medium impact

## 7. Hunyuan3D-Paint — approved, ship implementation

### Status

**Approved 2026-05-20** by Ken Allred. License bucket:
`commercial_threshold`. Full decision record:
[`docs/license-review-hunyuan3d-paint.md`](license-review-hunyuan3d-paint.md).

### Problem (unchanged)

`texture.sh --mode paint` was a deliberate placeholder that failed
with `status=error error=needs_license_review`. Hunyuan3D-Paint
significantly improves texture quality, especially for TRELLIS
outputs that ship vertex colours only.

### Approach (code work)

The decision gate is closed. Remaining work is implementation:

1. **Update `scripts/_pipeline_lib.sh::license_bucket_for_model`**
   — change `hunyuan3d-paint` from `unclear_risky` to
   `commercial_threshold`.
2. **Remove the stub** in `scripts/texture.sh --mode paint`. Replace
   with the real invocation of the Hunyuan3D-Paint inference (its
   `texture.py` or equivalent entry point — confirm against the
   upstream repo at implementation time).
3. **Install location:** `~/3d-pipeline/hunyuan3d-paint/` with a
   dedicated venv (model weights are large + the dep tree is
   different from mflux / pipeline-tools-env).
4. **Setup guide updates:** new install step in both
   `docs/asset-pipeline-guide.html` and `-studio.html` via heredoc
   embed. Studio-tier defaults to opt-in; laptop-tier mentions but
   doesn't auto-install (model is ~5 GB).
5. **Skill update:** `skill/SKILL.md` Flow 6 (texture) — remove the
   "do not enable" warning; add the routing rules below; mention the
   `commercial_threshold` bucket inline (same convention as SF3D).

### Routing rules — when to use paint mode

Paint mode is **not** a default; the user (via the skill) opts in.
The skill decides between paint mode and the existing texture
inspect/upscale path based on three signals from `generate.sh`'s
per-asset meta.json:

| Signal | Recommendation |
|---|---|
| Generator was TRELLIS *and* `quality.textures.textures_present` is empty (vertex colours only) | Recommend paint mode — this is the headline use case |
| `quality.textures.issues` includes `flat-black-albedo` or `uninitialised` from item 3 | Recommend paint mode — the existing texture pass produced a degenerate result |
| `quality.textures.issues` is empty and textures exist | Do **not** recommend paint — keep the existing PBR textures |
| User explicitly asks "re-texture" / "paint this mesh" | Run paint mode regardless of signals |

The wrapper never auto-runs paint after `generate.sh`. It is always
a separate `texture.sh --mode paint -i <glb>` invocation; the skill
proposes it and waits for the user to accept (license-bucket
disclosure first, per the existing `commercial_threshold` rules).

The selected texture generator is recorded under
`generation.texture_backend` in the per-asset meta.json so future
audits can see whether an asset's textures came from the original
3D generator or from a separate paint pass.

### Dependencies

- Hunyuan3D-Paint model weights — Tencent Hunyuan Community
  License — `commercial_threshold` per the approved review
- Its own venv (cannot share with mflux or pipeline-tools-env)
- Disk: ~5 GB for weights + venv (managed by item 10's pipeline-doctor)

### Hardware tier

**Studio recommended** for primary use. The model is large; laptop
tier works but the user should be made aware of the disk + memory
footprint via item 10's pre-install check.

### Manifest schema changes

Existing fields suffice. `model_role` and `generator` already
support recording which generator produced any texture; adding
`hunyuan3d-paint` as a recognised name in
`license_bucket_for_model` is the only mapping change.

### User-facing output

```
[texture] Painting textures via Hunyuan3D-Paint (commercial_threshold license)
[texture] Input mesh:    /path/to/asset_clean.glb
[texture] Output mesh:   /path/to/asset_painted.glb
[texture] Duration:      24.3s
```

Skill change in Flow 6: `texture.sh --mode paint` is now usable;
mention the bucket inline (same convention as other commercial_threshold
models).

### Failure modes

- Hunyuan3D-Paint not installed → wrapper fails with install guidance
  pointing at the setup guide (same pattern as SPAR3D today).
- Model weights missing or partial → handled by item 10's pipeline-doctor.
- Inference crashes on unusual mesh topology → log and exit non-zero
  with the underlying error; the original mesh is untouched.

### Test strategy

End-to-end: `texture.sh --mode paint -i path/to/trellis_clean.glb
--json`. Expect a new GLB with PBR textures + texture-quality check
(item 3) running cleanly on the result.

Regression: confirm `texture.sh --mode inspect` and `--mode upscale`
unchanged.

### Effort

**S–M.** ~3–5 days including install + setup guide + skill updates +
testing. The license decision (formerly M) is closed.

---

## 8. CLIP variant ranking + soft signal (calibrated)

### Problem

**MMR-noted issue (codex P2):** v1 treated a single absolute CLIP
ViT-L/14 threshold (0.75 / 0.82) as a hard pass/fail. But CLIP
scores aren't calibrated across:

- Prompt length (longer prompts score lower for identical content)
- Prompt style (concrete > abstract)
- Generator (mflux Z-Image Turbo scores differently from FLUX-schnell)
- Image distribution (in-distribution vs. out-of-distribution)

A single threshold creates false warnings for prompts that are
fine, and misses real failures for prompts that always score high
regardless of fidelity.

### Approach

CLIP score becomes:

1. **A variant-ranking tool**, not an absolute gate. When the user
   asks for multiple variants (`-n N`), the wrapper ranks them by
   CLIP score and surfaces the best one as the "primary" output,
   demoting others as alternates. This is where CLIP scores are
   most trustworthy — comparing variants of the same prompt with the
   same model.

2. **A soft signal** with per-model calibration. The wrapper ships
   with reference percentile bands computed once per model at
   install time (via a small calibration script — items 7 in
   `pipeline_doctor.py --calibrate`):
   - Z-Image Turbo: 95% of well-formed prompts score ≥ X
   - FLUX-schnell: 95% score ≥ Y
   - FLUX-dev: 95% score ≥ Z
   The "below threshold" message references the per-model band,
   not a global number.

3. **Never block.** Always emit the score; the skill decides if
   it's worth telling the user.

`scripts/clip_score.py` interface unchanged from v1 but now also
takes `--rank` mode that takes multiple image paths and returns
them sorted by score in JSON. `concept.sh` uses `--rank` when
`COUNT > 1`.

Per-model bands live in `scripts/clip_calibration.json` (checked
into the repo, refreshed quarterly):

```json
{
  "z-image-turbo": {"p50": 0.81, "p25": 0.76, "p10": 0.71},
  "flux-schnell": {"p50": 0.78, "p25": 0.73, "p10": 0.68},
  "flux-dev": {"p50": 0.83, "p25": 0.78, "p10": 0.73}
}
```

Skill flags a score "low" when it's below the model's p25
(weak quartile), not against a global cutoff.

### Dependencies

`open_clip_torch` (in `pipeline-tools-env`) — MIT — `commercial_safe`.
ViT-L-14 weights — OpenAI checkpoint, MIT — `commercial_safe`.
Model cache: `~/3d-pipeline/models/clip/` (~890 MB; managed by
item 10).

License-bucket: `clip-vit-l-14` → `commercial_safe`.

### Hardware tier

Both. ViT-L/14 inference is ~1 s on laptop M-series.

### Manifest schema changes

Under `clip` in per-asset meta.json:

```json
"clip": {
  "similarity": 0.84,
  "model": "ViT-L-14",
  "model_band": "p50",
  "percentile_for_this_model": 0.62
}
```

When ranking variants, the JSON adds a `rank` field per variant.

### User-facing output

Single image:

```
[concept] CLIP similarity: 0.84 (typical for Z-Image Turbo — good)
```

Below model band:

```
[concept] CLIP similarity: 0.69 (lower than 75% of Z-Image Turbo outputs)
[concept]   The image may not strongly match the prompt. Options:
[concept]     • re-run with a different seed
[concept]     • simplify the prompt
[concept]     • try -n 4 to see four variants and pick the best
```

Variant ranking (`-n 4`):

```
[concept] CLIP scores (best first): 0.86, 0.82, 0.78, 0.71
[concept]   Primary: dragon.png (CLIP 0.86)
[concept]   Alternates: dragon_v2.png (0.82), dragon_v3.png (0.78), dragon_v4.png (0.71)
```

Skill change in Flow 1 + Flow 3:

> The CLIP score is calibrated per-model. Trust the model_band
> field — "p10" or "below_p10" warrants a re-generation suggestion;
> "p50" or above is fine. Don't compare absolute scores across
> different 2D models.

### Failure modes

- open_clip not installed → skip; JSON omits `clip` section.
- Model not downloaded → item 10 handles this; user sees a clear
  download progress message.
- Calibration file missing → fall back to global threshold
  (0.75) with a stderr warning.

### Test strategy

- Run `concept.sh "a treasure chest" -n 4` → expect ranking with
  primary = highest score.
- Run with a vague prompt → expect lower band classification.
- Compare scores across models for the same prompt — verify the
  per-model bands behave differently.

### Effort

**M.** Same as v1 (~120 lines) + the calibration script and the
ranking mode.

---

## 9. Generator auto-selection hints in `SKILL.md`

### Problem

The skill defaults to SF3D unconditionally. SF3D is wrong sometimes:
characters (TRELLIS is better), mech assets (SPAR3D), quick
iteration (SPAR3D), assets with prominent back-face geometry
(TRELLIS).

### Approach

Pure skill-text change. Add a recommendation matrix in `SKILL.md`:

| Intent signals | Recommend | Why |
|---|---|---|
| "character", "figure", "creature" with detail | TRELLIS | Better topology; tolerate non_commercial bucket |
| "mech", "robot", "weapon", "hard surface" | SPAR3D | Sharper edges; faster |
| "quick", "draft", "iterate", "prototype" | SPAR3D | ~2× speed at acceptable quality |
| "prop", "chest", "barrel", default | SF3D | Default; commercial-safe; reliable |
| Visible back face needed | TRELLIS or multi-view (item 12) | SF3D hallucinates the back |
| Final asset for commercial release | SF3D or SPAR3D only | Both commercial_threshold; never TRELLIS |

When deviating from SF3D, state the bucket and reason in
conversation. Skill text identical to v1 here.

### Dependencies, tier, manifest, UX, failure modes, tests, effort

Identical to v1. **S.**

---

# Tier 3 — larger lift

## 11. LoRA + IP-Adapter for character consistency — Option A confirmed

### Status

**Decision: Option A** (add ComfyUI as a second 2D backend), confirmed
2026-05-20. Option B (wait for mflux IP-Adapter) is no longer in scope.

### Problem (unchanged)

Game asset pipelines exist to produce **many** related assets:
multiple poses of a character, variations on a weapon family. The
current 2D path produces one-offs that drift in identity across
runs. LoRA alone locks style; IP-Adapter + ControlNet are needed
to lock identity.

mflux doesn't support IP-Adapter today; ComfyUI is the standard
backend for SDXL + LoRA + IP-Adapter + ControlNet workflows.

**License clarification (gemini P3, retained from v2):** ComfyUI's
GPL classification applies to redistribution of ComfyUI itself.
Image **outputs** from ComfyUI are **not GPL-encumbered**; they
inherit the bucket of their generating model (SDXL =
`commercial_threshold`, etc.).

### Approach (Option A)

ComfyUI as a second 2D backend behind a `--backend comfyui` flag on
`concept.sh`. mflux remains the default for one-off generations;
ComfyUI activates when the user passes `--backend comfyui` or
`--consistency-pack PATH`.

Sub-PRs (per the implementation plan; **note: P3.2b — format — comes
before P3.2c — parser — so the implementation has a versioned
contract to build against**):

- **P3.2a — ComfyUI install:** New `~/3d-pipeline/comfyui-env/`,
  dedicated venv (incompatible PyTorch build with pipeline-tools-env).
  Install steps in both setup guides. Model paths registered with
  pipeline-doctor (item 10).
- **P3.2b — Consistency-pack format (defined before parsed):**
  A directory containing `pack.json` (manifest), reference images,
  and an optional LoRA `.safetensors`. Schema versioned. Documented
  in `docs/consistency-pack-format.md`. Includes a JSON schema file
  so future parser changes can validate against the same contract.
- **P3.2c — `--backend comfyui` flag in concept.sh:** Routes to a
  ComfyUI workflow JSON; reads + validates consistency-pack against
  the schema from P3.2b; runs the workflow headlessly; collects the
  output PNG.
- **P3.2d — Reference workflow + tests:** Ship a reference
  consistency-pack and the ComfyUI workflow JSON that produces
  identity-locked outputs from it. End-to-end test with the
  reference pack; CHANGELOG entry.
- **P3.2e — Skill update:** Flow 1 + Flow 3 in `SKILL.md` — how to
  recognise a consistency need (multiple poses of one character,
  weapon family, etc.); how to pass `--backend comfyui
  --consistency-pack PATH`; license-bucket disclosure (SDXL = `commercial_threshold`).

### Dependencies

- **ComfyUI** — GPL-3.0 (the **tool**, not the outputs). Bucket:
  `source_available_restricted` for redistribution of ComfyUI
  itself. Image outputs are not GPL-encumbered and inherit the
  generating-model's bucket.
- **SDXL base** — CreativeML Open RAIL-M — `commercial_threshold`
- **IP-Adapter FaceID** — Apache 2.0 — `commercial_safe`
- **ControlNet (OpenPose, Canny)** — Apache 2.0 — `commercial_safe`
- New venv `comfyui-env/` (cannot share `pipeline-tools-env` —
  different PyTorch build expectations)

### Hardware tier, manifest schema, UX, failure modes, tests, effort

Identical to v1. **L** (1–2 weeks).

---

## 12. Multi-view reconstruction pipeline lane — approved with backend research phase

### Status

**Approved 2026-05-20** with an explicit ~3-day backend research
phase before implementation. The pipeline will gain a multi-view
lane; the specific backend (TRELLIS multi-view, InstantMesh, or
OpenLRM) will be chosen empirically against the same 4 reference
images.

### Problem (unchanged)

The pipeline today is single-image-to-3D throughout. For assets
with complex back-face geometry, fine silhouettes, or real-world
objects (photogrammetry), multi-view input yields better geometry.

### Approach (two phases)

**Phase 1 — Backend research (~3 days). Sub-PR P3.1a in the plan.**

Methodology — explicit and reproducible:

**Dataset:**

- **3 subjects**, fixed across all backend runs, checked into
  `tests/multiview-bench/subjects/`:
  - `subject-1-character/` — humanoid figure (asymmetric;
    front/back differ significantly)
  - `subject-2-hardsurface/` — small mechanical prop (sharp edges;
    repeated geometry)
  - `subject-3-organic/` — natural object (e.g. a small rock or
    plant; irregular surface)
- **Per subject:** 4 calibrated reference images at fixed angles
  (0°, 90°, 180°, 270° around the vertical axis), 1024×1024 PNG,
  shot under uniform white-background studio lighting.
- **Ground-truth scan:** where available (laser-scan or known
  ground-truth GLB), used for the Hausdorff metric. For subjects
  without scans, mark "no GT" and rely on visual + the other metrics.

**Scoring rubric (weighted, 0–10 per dimension):**

| Dimension | Weight | Metric |
|---|---|---|
| Geometric accuracy | 0.35 | Hausdorff distance to GT (lower = higher score); for subjects without GT, manual visual score |
| Texture / colour fidelity | 0.20 | SSIM + visual review of UV-mapped textures |
| Speed (studio tier) | 0.15 | Wall-clock seconds for the full 4-image run |
| Speed (laptop tier) | 0.10 | Same, on laptop |
| Install footprint | 0.10 | Total disk: venv + models. Lower = higher score |
| License clarity | 0.10 | `commercial_safe` = 10, `commercial_threshold` = 7, `non_commercial` = 4, `unclear_risky` = 0 (unless review completes) |

**Pass/fail thresholds:**

- Minimum acceptable weighted score: **6.5 / 10** overall.
- No single dimension may score < 3.0 (no fatal weakness).
- License score must be ≥ 4 (`non_commercial` floor); below this the
  backend is disqualified regardless of total.

**Reproducibility requirements:**

- Each backend runs 3× per subject (catches stochastic outputs);
  scores are means with stdev recorded.
- Hardware: 1 laptop run + 1 studio run per backend per subject.
- Raw outputs (GLBs) + scores committed under
  `tests/multiview-bench/results/<backend>/<subject>/`.
- The recommendation doc (`docs/multiview-backend-research.md`) must
  include the raw scores table, the weighted total, the disqualifier
  list, and a one-paragraph rationale per backend.

**InstantMesh license parallel-track:** if InstantMesh appears
within 2 points of the leader, file a license review (same shape as
the Hunyuan3D-Paint review) before P3.1c so the implementation
isn't blocked. If TRELLIS or OpenLRM wins outright, no license work
needed.

**Phase 2 — Implementation. Sub-PRs P3.1c–e in the plan.**

New `scripts/multiview.sh` wrapper (Flow 9 in the skill). Wires
through the same `clean_asset.py` cleanup + quality checks (items 2,
3, 13) so multi-view outputs benefit from the Tier 1 work.

#### Interface

```bash
# Comma-separated paths in canonical view order (front, right, back, left):
multiview.sh -i front.png,right.png,back.png,left.png -o asset_name --json

# Directory of images with view labels in filenames (recommended):
multiview.sh -d /path/to/image/dir -o asset_name --json
# Filenames must include one of: _front, _right, _back, _left, _top, _bottom
# OR an explicit angle: _000deg, _090deg, _180deg, _270deg

# Explicit manifest file (highest precedence; for non-standard angles):
multiview.sh -m views.json -o asset_name --json
```

#### View ordering and metadata

Multi-view backends are sensitive to view ordering. The wrapper
**requires** view metadata; it never guesses.

- **`-i` (comma list):** ordering is **canonical**: front, right,
  back, left (4 images) OR front, right-front, right, right-back,
  back, left-back, left, left-front (8 images). Fewer or more is
  an error.
- **`-d` (directory):** the wrapper scans for PNG/JPG files whose
  basenames end in a recognised view tag (`_front`, `_right`,
  `_back`, `_left`, `_top`, `_bottom`) or an explicit angle
  (`_000deg`, `_045deg`, …). Files without recognised tags are
  ignored with a warning. Directory order is **never** used —
  only the explicit tags.
- **`-m` (manifest):** a JSON file `[{"path": "...", "view": "front",
  "angle_degrees": 0, "elevation_degrees": 0}, ...]` for arbitrary
  view setups (e.g. non-cardinal angles, varying elevation).

The wrapper validates that at minimum the front view is present.
Missing back/left/right warn but don't block (the backend may still
produce a usable mesh; just note it).

### Dependencies

Backend dependencies are decided in Phase 1. Common deps:

- The chosen backend's package + model weights
- New venv (likely `multiview-env/` for isolation from other backends)
- Existing pipeline-tools-env for the cleanup + quality checks

### Hardware tier

**Studio recommended** for primary use (multi-view models tend to
be larger / slower than single-image). Laptop tier supported but
expect slower runs.

### Manifest schema changes

Under `generation` in the per-asset meta.json (now a first-class
top-level section — see cross-cutting principle 2):

```json
"generation": {
  "backend": "multiview-trellis",
  "license_bucket": "non_commercial",
  "inputs": [
    {"path": "front.png", "view": "front", "angle_degrees": 0, "elevation_degrees": 0},
    {"path": "right.png", "view": "right", "angle_degrees": 90, "elevation_degrees": 0},
    {"path": "back.png",  "view": "back",  "angle_degrees": 180, "elevation_degrees": 0},
    {"path": "left.png",  "view": "left",  "angle_degrees": 270, "elevation_degrees": 0}
  ],
  "duration_seconds": 12.4
}
```

### User-facing output

```
[multiview] Inputs: 4 images (front, right, back, left)
[multiview] Backend: TRELLIS multi-view (license: non_commercial)
[multiview] Generation finished in 12.4s → assets/raw/dragon_raw.glb
```

Skill change — new Flow 9 in `skill/SKILL.md`:

> **Flow 9 — Multi-view 3D reconstruction (Tier 3).**
>
> Trigger phrases: "I have multiple photos of this", "use these
> reference images", "reconstruct from these views",
> "photogrammetry", "make a 3D from these N photos".
>
> Three input modes:
> - `-i front.png,right.png,back.png,left.png` — canonical 4- or
>   8-image order
> - `-d <dir>` — directory of images whose filenames include view
>   tags (`_front`, `_right`, `_back`, `_left`) or explicit angles
>   (`_000deg`, `_090deg`)
> - `-m views.json` — explicit manifest for non-cardinal angles
>
> The wrapper always requires view metadata; it never guesses from
> directory order. If the user supplies files without recognised
> tags, ask them to rename or supply a manifest.
>
> Always state the license bucket inline (the bucket depends on the
> backend selected in P3.1; record this in conversation per the same
> rule as Flow 2).

### Failure modes

- **Insufficient images (< 3):** wrapper exits 1 with a clear
  message.
- **Inconsistent image dimensions:** wrapper auto-resizes to a
  common size and warns.
- **Backend not installed:** wrapper fails with install guidance.

### Test strategy

Capture 4 photos of a small physical object (figurine), run through
the wrapper, compare the resulting mesh to a single-image generation
of the same subject. Expect better silhouette accuracy.

### Effort

**L** total. Phase 1 (research): ~3 days. Phase 2 (implementation):
~1–2 weeks. If InstantMesh wins the benchmark, add license-review
time (M-decision) parallel to implementation.

---

# Cross-cutting concerns

## `pipeline-tools-env` venv (consolidated)

Items 1, 2, 3, 6, 8, 13, 14 share a single venv at
`~/3d-pipeline/pipeline-tools-env/`:

```
trimesh
numpy
scipy
Pillow
rembg[cpu]
open_clip_torch
torch                # shared dep brought in by open_clip
tqdm                 # for item 10 progress bars
requests             # for item 10 downloads
```

Disk impact: ~6 GB total (vs ~15 GB across separate envs).

ComfyUI keeps its own venv if/when item 11 ships.

## Per-asset `<output>.meta.json` (consolidated)

Single file per generated asset; merged into via
`scripts/meta_helper.py merge <meta-json-path> --section <name>
--data <inline-json>`. File-locked. Each pass owns one section.

Sections used:

```
input/             # item 4
preprocessing/     # item 1
generation/        # generators (SF3D/SPAR3D/TRELLIS/multiview/comfyui)
cleanup/           # items 2 (cleanup-specific) + 6
quality/manifold/  # item 2
quality/scale/     # item 2
quality/textures/  # item 3
quality/uv/        # item 13
quality/engine/    # item 13
preview/           # item 5
clip/              # item 8
print/structural/  # item 14
print/dimensions/  # existing prepare_for_print.py meta
```

`update_manifest.py` gains a single `--meta-json PATH` arg that
merges the file into the manifest entry per the mapping table in
cross-cutting principle 2 (generation/print to their own blocks;
cleanup/quality/preview/clip to the manifest's quality block; input
+ preprocessing to generation.input). Old per-section flags (from
v1) are deleted.

## `~/3d-pipeline/.config` additions

```
bg_removal_mode = auto        # auto | on | off
clip_check_default = true
preview_default_laptop = png
preview_default_studio = gif
preview_default_queue = none
```

Per-machine toggles. Per-project overrides via `.asset-pipeline.json
defaults.<field>`.

## Skill version bump

`skill/SKILL.md` v0.3 changes:

- Item 9's generator recommendation matrix
- Translation map (cross-cutting principle 8)
- Reference to `pipeline_doctor.py` from setup section
- CLIP per-model band interpretation
- Failure-mode language: warn-friendly translations of every new
  quality-gate failure

## Documentation work per item

Each Tier 1 item touches:

1. `/scripts/*.sh` or `/scripts/*.py` (canonical script)
2. `/skill/SKILL.md`
3. `/docs/asset-pipeline-guide.html` (laptop) — via `make regenerate`
4. `/docs/asset-pipeline-guide-studio.html` (studio mirror)
5. `/context/asset-pipeline-ai-context{,-studio}.{md,html}`
6. `/docs/UPGRADES-{laptop,studio}.md`
7. `CHANGELOG.md`
8. `tools/_embed_lib.py::EMBEDS` (new script files)

The pre-commit hook + `make verify` catch most missing-link cases.

---

# Effort summary (v2)

| # | Item | Effort | Tier |
|---|---|---|---|
| 1 | Conditional background removal | M | 1 |
| 2 | Watertight + scale sanity | S | 1 |
| 3 | Texture quality validation | S | 1 |
| 4 | Input quality + format normalisation | S | 1 |
| 5 | Hero PNG + optional turntable GIF | M | 1 |
| 6 | Cleanup report | S | 1 |
| 10 | Pipeline doctor + cache manager (NEW) | M | 1 |
| 13 | UV + engine validation (NEW) | M | 1 |
| 14 | Print structural gates (NEW) | M | 1 |
| 7 | Hunyuan3D-Paint implementation (approved 2026-05-20) | S–M | 2 |
| 8 | CLIP variant ranking + soft signal | M | 2 |
| 9 | Generator auto-selection hints | S | 2 |
| 11 | LoRA + IP-Adapter consistency | L | 3 |
| 12 | Multi-view reconstruction | L | 3 |

Tier 1 total: 4 × S + 5 × M ≈ 10–14 days of focused work.
Tier 2 total: 1 × S + 1 × (S–M) + 1 × M ≈ 5–7 days (all gates resolved).
Tier 3: 2 × L ≈ 3–4 weeks (item 12 includes ~3-day backend research phase).

---

# Open questions for review

1. **Wall-thickness heuristic accuracy**: item 14's approximate
   wall-thickness check will have false positives. Acceptable for
   v1 of v0.3, or block until a more rigorous algorithm?
2. **Meta.json schema versioning**: how do we evolve the per-asset
   schema after v0.3 ships? Recommend a `schema_version` field
   (already in the example) + a migration helper if a section's
   shape ever changes.
3. **Calibration cadence for item 8**: how often do per-model CLIP
   bands need refreshing? Quarterly is the current proposal;
   confirm against actual drift if any.
4. **Engine staging during preview render**: should the hero PNG
   also get staged into the project's `Assets/Models/AI/` folder
   alongside the GLB? Useful for in-editor previews; adds another
   file the user has to manage.
5. **Pipeline-doctor in CI?** Run on PRs that touch script files?
   Catches stale model_manifest entries early.

### Resolved (2026-05-20)

- ~~Hunyuan3D-Paint review timing:~~ **approved**; ship in v0.3.4
  (see [`docs/license-review-hunyuan3d-paint.md`](license-review-hunyuan3d-paint.md))
- ~~ComfyUI Option A vs B:~~ **Option A confirmed**; ComfyUI added
  as a second 2D backend for consistency mode (item 11)
- ~~Multi-view backend research:~~ **approved with ~3-day research
  phase**; document in `docs/multiview-backend-research.md`
  before implementation (item 12)

---

*End of spec v3 (gates resolved, second MMR pass complete).*
