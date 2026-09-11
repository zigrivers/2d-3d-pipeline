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
~/3d-pipeline/workspace/texture.sh -i <path> --mode upscale --scale 4 [--engine realesrgan|seedvr2] [--json]
```

Two engines (item 24, v0.4+):

- **`realesrgan`** (default) — `real-esrgan-ncnn-vulkan` if installed.
  If not installed, the wrapper fails with `status=error
  error=not_installed` JSON and stderr install guidance — relay that
  and offer to wait until the user installs it, or suggest `--engine
  seedvr2` instead.
- **`seedvr2`** — SeedVR2 3B (laptop tier) / 7B (studio tier) via
  mflux's native `mflux-upscale-seedvr2`, no separate install (ships
  in mflux ≥ 0.18, same venv as everything else in mflux-env).
  `commercial_safe` (gate G5, R0.6 spike: both HF cards
  `license: apache-2.0`; confirmed live on this Studio, real 2x
  upscale). Modern and maintained where Real-ESRGAN ncnn-vulkan isn't
  (last portable release 2022) — suggest it first if the user hasn't
  already got Real-ESRGAN installed, since it needs zero extra setup.
  Real-ESRGAN stays the *default* until a formal bake-off flips it
  (principle P-A — no silent default change).

Output lands in `assets/textures/` (or `~/3d-pipeline/workspace/textures/`
in global mode). `--engine-stage` copies to the engine's `Textures/`
folder when applicable. `quality.textures.upscale_engine` in the
output's meta.json records which engine ran.

### Paint mode — Hunyuan3D-Paint MLX port (v0.4+, item 19 retarget)

`texture.sh --mode paint -i <glb> --image <ref.png>` paints PBR
textures onto an existing 3D mesh. Retargeted from item 7's original
CUDA-only design to
[`dgrauet/Hunyuan3D-2.1-mlx`](https://github.com/dgrauet/Hunyuan3D-2.1-mlx)
(Apple Silicon MLX port; upstream Hunyuan3D-Paint needs CUDA,
unavailable on Mac). Bucket is `commercial_threshold` — same as SF3D
and SPAR3D. **The Tencent license does NOT apply in the EU, UK, or
South Korea** — mention this if the user's distribution plans touch
those regions; see `docs/license-review-hunyuan3d-paint.md` and its
2026-08-12 addendum for the full record.

`--image` is required — the multiview diffusion pass needs a
reference image (typically the concept image the mesh was generated
from), not just the mesh geometry.

**When to recommend paint mode** (per item 7 routing rules):

| Signal in meta.json | Recommendation |
|---|---|
| `generator=trellis` AND `quality.textures.textures_present` is empty | Strongly recommend paint — TRELLIS-on-Mac ships vertex colours only |
| `quality.textures.issues` includes `flat-black-albedo` or `uninitialised-*` | Recommend paint — original generator produced degenerate textures |
| `quality.textures.textures_present` includes `metallic` or `roughness` already | Don't recommend paint — a real PBR bake already exists (e.g. TRELLIS.2) |
| SF3D output with only `albedo`/`normal`, no `metallic`/`roughness` | Paint is still worthwhile — SF3D bakes metallic/roughness as flat material factors, not textures |
| User explicitly asks "re-texture" / "paint this mesh" | Run paint regardless |

The wrapper never auto-runs paint after `generate.sh`. It's always a
separate `texture.sh --mode paint` call. State the
`commercial_threshold` bucket inline (same convention as recommending
SPAR3D over SF3D).

**Hard refusal, not just a soft recommendation:** the wrapper itself
checks (via a live `texture_quality_check.py` run, not a possibly-
stale meta.json) whether the input already has a real baked
metallic-roughness map, and exits with structured
`status=error error=already_textured` JSON if so — painting a
TRELLIS.2 output is refused with a clear explanation, not silently
run. Relay that explanation rather than retrying; suggest
`--mode upscale` instead if the user wants to improve an existing
texture.

Install layout: `$HUNYUAN3D_PAINT_DIR` (default
`~/3d-pipeline/hunyuan3d-paint-mlx/`) with `.venv` and
`hy3dpaint/textureGenPipeline_mlx.py`. When the wrapper finds either
missing, it exits with structured `status=error error=not_installed`
JSON and points at the install docs. Relay the install guidance;
don't try to substitute a different texture generator, and don't
suggest the Brainkeys MPS fork as a paint fallback — its paint stage
is limited/disabled, shape-generation only.

### PBR pass — StableDelight + Marigold-IID (v0.4+, item 24)

```bash
~/3d-pipeline/workspace/texture.sh -i <glb> --mode pbr [--json]
```

Albedo → StableDelight (removes baked-in specular highlights) →
Marigold-IID Appearance (roughness + metallic decomposition) → writes
a new GLB with the delighted albedo as `baseColorTexture` and a
packed `metallicRoughnessTexture`. Both models `commercial_safe`:
StableDelight (code + weights apache-2.0, verified directly) and
Marigold-IID (CreativeML OpenRAIL++-M, gate G4 — commercial use
allowed with narrow behavioral-use restrictions; mention this inline
when recommending the pass, see `docs/decision-marigold-bucket.md`
for the full call). No `--image` needed — the reference is the mesh's
own existing `baseColorTexture`, extracted automatically.

**Same hard-refusal rule as paint mode, same mechanism:** refuses
with `status=error error=already_textured` when
`quality.textures.textures_present` already includes `metallic` or
`roughness` (TRELLIS.2 output, a prior paint/pbr pass) — use
`--mode upscale` to improve an existing texture instead. Best fit is
exactly SF3D's own output (`albedo`/`normal` present, no real
metallic-roughness map — see the paint-mode routing table above,
same signal).

Install layout: `$PBR_PASS_ENV` (default `~/3d-pipeline/pbr-pass-env/`)
— a dedicated diffusers + torch venv, not shared with
pipeline-tools-env. Missing venv exits with structured
`status=error error=not_installed` JSON; relay the install guidance.

