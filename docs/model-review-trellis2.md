# Model review — TRELLIS.2

**Status:** approved for `commercial_safe` opt-in install · **Decision date:** 2026-08-12 ·
**Signatory:** Ken Allred (zigrivers@outlook.com)

## Subject

[TRELLIS.2](https://github.com/microsoft/TRELLIS.2) (`microsoft/TRELLIS.2-4B`
on Hugging Face) is Microsoft's newer image-to-3D generation model — a
separate, newer model from the "TRELLIS" (v1) already in this pipeline
(`generate.sh -g trellis`, `non_commercial`, vertex-colors-only on Mac).
**Do not conflate the two: different models, different Mac ports installed
at different local paths, different license buckets.**

The Mac port used here is
[`shivampkumar/trellis-mac`](https://github.com/shivampkumar/trellis-mac),
pinned at commit `d58628f4f5b9c3de8274cb110074154f4b31cef2` (2026-04-28),
installed at `~/3d-pipeline/trellis2-mac` and selected via
`generate.sh -g trellis2`. An alternative, younger/smaller MLX-native port
([`pedronaugusto/trellis2-apple`](https://github.com/pedronaugusto/trellis2-apple))
exists as a fallback option but is not installed by default.

Unlike v1, this port bakes real PBR texture maps (baseColor +
metallic/roughness) through a Metal-based texture-baking stage — verified
directly (see Evidence below), not just claimed by the port's README.

## License clauses reviewed (gate G1, R0.1 spike)

### Port code (`shivampkumar/trellis-mac`)

Repo root `LICENSE`, quoted in full:

> Permission is hereby granted, free of charge, to any person obtaining a
> copy of this software... to use, copy, modify, merge, publish,
> distribute, sublicense, and/or sell copies of the Software...

Standard MIT license text. No restrictions material to this pipeline's use.

### Model weights (`microsoft/TRELLIS.2-4B`)

HF README frontmatter: `license: mit`. Body text confirms: "This model is
released under the MIT License." No commercial-use restriction, no
revenue threshold, no field-of-use limit.

### DINOv3 encoder (`facebook/dinov3-vitl16-pretrain-lvd1689m`)

Gated on Hugging Face — requires an explicit access-request approval per
account (instant approval observed; see the setup guide's gated-models
step). Meta's custom DINOv3 license grants:

> a non-exclusive, worldwide, non-transferable and royalty-free limited
> license... to use, reproduce, distribute, copy, create derivative works
> of, and make modifications

with **no commercial-use restriction, no revenue cap, no field-of-use
limit** — only the standard Trade-Controls / export-law and
military-use-prohibition clauses common to Meta's model licenses. DINOv3
is used only as an internal feature extractor (image conditioning) and is
never shipped in output GLBs, so it does not affect the `commercial_safe`
bucket recommendation below.

### RMBG-2.0 (bundled by the port, NOT part of this pipeline's chain)

RMBG-2.0 (CC BY-NC 4.0, non-commercial) is the port's own bundled
background-removal step, invoked by `generate.py`'s bundled pipeline
(`Trellis2ImageTo3DPipeline.preprocess_image()`) whenever the input image
lacks a usable alpha channel. **This pipeline never lets that branch run**:
`generate.sh -g trellis2` forces the existing `rembg_preprocess.py` step
(MIT `rembg`, already `commercial_safe`) to run unconditionally before
dispatch, so the input always arrives with a real alpha channel and
`preprocess_image()`'s `has_alpha` branch (which skips RMBG-2.0 entirely)
is always the one taken. Verified live: RMBG-2.0's HF cache directory was
confirmed untouched (stale, pre-dating the test run) across a real
`generate.sh -g trellis2` smoke generation — see Evidence.

## Approval terms

- License bucket: `trellis2` → `commercial_safe` (MIT port + MIT weights).
  The legacy `trellis` (v1) entry is untouched and stays `non_commercial`.
- Approval is for the pinned commit above. A different commit — including
  a newer one on the same upstream branch — requires re-review, enforced
  by `pipeline_doctor.py`'s pinned-commit smoke check (principle P-B:
  community-fork risk is named, not just hoped away). If the pin ever
  needs to move (e.g. a real upstream fix), re-run the license review
  against the diff, not just re-pin blindly.
- Not the default 3D generator. Promoting any generator to default is
  gate G6 — a separate, user-approved decision gated on the bake-off
  below, per principle P-A (no silent default-model changes).

## Port limits (from the spike + this PR's live testing)

- **Hole-filling disabled, meshes pre-simplified to ~200K faces before
  baking** — documented port limitation, not something this pipeline
  works around.
- **Sparse attention unfused** (SDPA-padded) — the port's own documented
  performance ceiling on Apple Silicon; generation latency here (188s)
  is dominated by this, not by memory pressure.
- **`clean_asset.py`'s decimate step did not reach the configured
  polycount target on this port's output**: a real smoke run targeting
  the default 3000 polys landed at 46,085 (195,718 → 46,085) instead —
  TRELLIS.2's raw mesh is far denser (195K faces) than SF3D's typical
  output (~17K faces) going into the same decimate pass. Not a licensing
  or correctness blocker for this PR (a GLB with real PBR maps was still
  produced, satisfying the acceptance criteria), but worth tracking
  before TRELLIS.2 could ever be considered for default promotion —
  logged here rather than silently accepted.
- **UV fragmentation**: the same smoke run's `game_asset_check.py`
  reported 8,125 texture patches (UV islands) on the decimated mesh — a
  lot, plausibly connected to the above decimate/polycount finding.
  Also tracked here, not fixed in this PR.
- **Weight footprint**: ~15 GB (TRELLIS.2-4B) + ~1.1 GB (DINOv3) on
  first real generation, on top of the ~1.2 GB port + dependencies.
- **Speed**: ~5–6 minutes per asset end-to-end (cold pipeline load +
  generation + Metal PBR bake) on this Studio (M3 Ultra) — see Evidence
  for the real measured breakdown. Slower than the port README's own
  M4 Pro benchmark; per the R0.1 spike, this is attention-latency-bound
  (SDPA, unfused) rather than a memory-pressure difference, so "Studio
  > laptop" should not be assumed for this specific model.

## Evidence

Real end-to-end smoke generation via `generate.sh -i <canned concept.sh
PNG> -g trellis2 -o r14_trellis2_test --no-preview` on this Studio
(2026-08-12):

- Generation: 188.2s. Total pipeline (including Blender cleanup):
  323s / 339s wall clock.
- Output mesh inspected with `trimesh`: `PBRMaterial` with **both**
  `baseColorTexture` and `metallicRoughnessTexture` present as real
  texture maps — confirms real PBR, not vertex colors.
- `meta.json` `generation.backend == "trellis2"`,
  `generation.license_bucket == "commercial_safe"` (both newly wired by
  this PR — no script previously wrote the `generation` meta.json section
  at all, for any generator).
- RMBG-2.0 non-invocation confirmed two ways: (1) the RMBG-2.0 HF cache
  directory's last-modified timestamp pre-dates this test run (stale from
  the earlier R0.1 spike, which used the port's own standalone CLI
  directly — not through `generate.sh`), and (2) the actual input image
  fed to `generate.py` was confirmed `RGBA` with genuine non-uniform alpha
  (0–255 range), which is exactly what `preprocess_image()`'s `has_alpha`
  branch requires to skip RMBG-2.0.
- `pipeline_doctor.py`'s pinned-commit check verified both directions
  live: PASS at the pinned commit, correct `drift`/`commit-mismatch`
  report (with a working `fix_command`) after temporarily checking out a
  different real commit on the same clone, restored afterward.

## Bake-off (placeholder — plan phase R1.5)

Not yet run. Plan phase R1.5 runs `scripts/model_bakeoff.py`'s studio
`default` suite across `sf3d` / `spar3d` / `trellis2`, judges outputs with
item 18's mesh judge (`--judge-mesh`), and fills per-model scores,
timings, memory, and a recommendation into this section. **Default
promotion is gate G6 (user decision) — this PR does not change any
default.**

## Re-review triggers

- The pinned commit needs to move for any reason (upstream fix,
  compatibility break with a newer macOS/Xcode/Blender release).
- Microsoft revises the TRELLIS.2-4B license.
- The `shivampkumar/trellis-mac` port's own license changes.
- DINOv3's gated-access terms change on Hugging Face.
- The R1.5 bake-off surfaces a reason to reconsider the `commercial_safe`
  bucket (it shouldn't — the bucket is a license property, not a quality
  one — but flagging the coupling here for clarity).
