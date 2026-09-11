## Flow 2: 2D image → 3D asset

Use `generate.sh` with `-i <image_path>`. Default to SF3D unless asked
for SPAR3D, TRELLIS (v1), or TRELLIS.2 (v2, item 15) — or the asset
needs unusual topology or real PBR at higher geometry density than
SF3D gives. Mention the license bucket if you pick anything other than
SF3D. **TRELLIS and TRELLIS.2 are two different models — v1 is
`non_commercial` and vertex-colors-only; v2 is `commercial_safe` with
real PBR but the slowest generator in the pipeline (~5–6 min/asset).**

For judge results, cleanup warnings, LODs, re-UV, or quad retopology, read
[Mesh quality and processing](mesh-quality.md) only when needed. Its before-paint
ordering and hard refusals apply to those optional operations.

### Generator recommendation matrix (v0.3+, item 15 adds TRELLIS.2)

Before invoking `generate.sh`, classify the asset by reading the user's
request. Match the closest row and recommend that generator (stating
the license bucket inline, as already required for non-default choices).

| Intent signals (in prompt or context) | Recommend | Why |
|---|---|---|
| "character", "figure", "creature", "person" with detail, commercial OK | TRELLIS.2 | Same organic-topology advantage as v1, real PBR, `commercial_safe` — but ~5–6 min/asset, slowest option |
| "character", "figure", "creature", "person" with detail, non-commercial OK | TRELLIS (v1) | Faster than TRELLIS.2 (~30–60s); user must accept `non_commercial` and vertex-colors-only texture |
| "mech", "robot", "weapon", "gun", "tool", "hard surface" | SPAR3D | Sharper edges; ~2× faster |
| "quick", "draft", "iterate", "prototype", "test" | SPAR3D | ~2× speed at acceptable quality for iteration |
| "prop", "chest", "barrel", "rock", "crate", default | SF3D | Default; `commercial_safe` ‡; reliable |
| Asset needs visible back face (e.g. character figurine) | TRELLIS.2 or TRELLIS (v1), or multi-view (Flow 9, v0.4) | SF3D hallucinates the back |
| Final asset for **commercial** release, best geometry+texture, time not critical | TRELLIS.2 | `commercial_safe`; real PBR; slow |
| Final asset for **commercial** release, speed matters | SF3D **or** SPAR3D | Both `commercial_threshold`; fast; **never TRELLIS (v1)** here |

‡ Note SF3D is technically `commercial_threshold`, the same as SPAR3D — but it's the documented default so the threshold disclosure is implicit. Be explicit when picking ANYTHING else.

When you deviate from SF3D, state the bucket and the reason in
conversation. Examples:

> "This is a character with fine detail and needs to ship commercially —
> I'd recommend TRELLIS.2 for better topology and real PBR textures.
> License bucket `commercial_safe`, so no restriction there, but it's
> the slowest generator (~5–6 minutes vs SF3D's ~15 seconds). Want me
> to proceed with TRELLIS.2, or use SF3D (faster, noisier topology)?"

> "This is a character with fine detail, for a personal project — I'd
> recommend TRELLIS (v1) for better topology. License bucket
> `non_commercial`, which means this asset can't ship in Grithkin or
> GripCraft commercially. Want me to proceed with TRELLIS (v1), use the
> slower but commercial-safe TRELLIS.2 instead, or use SF3D
> (commercial-safe but noisier topology)?"

If unclear, ask one short question to disambiguate intent.

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

For a requested full 3D asset, run [image generation](image.md), show the concept as progress, and continue to mesh generation. The full asset request authorizes these intermediate stages. Pause only for an explicitly requested concept review, a material unresolved choice, or a next stage outside agreed cost or license limits.

When consistency mode is appropriate (recurring character / asset
family — see Flow 1's "Consistency mode" subsection), pass
`--backend comfyui --consistency-pack PATH` through to flow 1's
`concept.sh` call. Flow 2's 3D generators (SF3D / SPAR3D /
TRELLIS) handle ComfyUI's outputs the same way they handle mflux's.

### Routing when Blender is the destination (v0.4+)

Two doors reach this pipeline when the user is working in Blender through
the "MCP for Blender" add-on. They fail in opposite directions, so pick by
context rather than defaulting blindly.

| Door | How it runs | Use when |
|---|---|---|
| **Shell** | You run `concept.sh` / `generate.sh` via bash, then import the GLB with `execute_blender_code` → `bpy.ops.import_scene.gltf(filepath=...)` | You have shell access — which is the default whenever you do |
| **Bridge** | The add-on's `generate_hunyuan3d_model` tool POSTs to `blender_bridge.py` on `127.0.0.1:8081`, which calls the same wrappers | No shell access (Claude Desktop, other MCP clients), or a quick one-off with no project involved |

**Prefer the shell door whenever you have bash**, for three reasons:

- **Project staging.** The wrappers detect the active project from the
  working directory. The bridge always runs with its cwd set to
  `~/3d-pipeline/workspace`, so everything it makes lands in the global
  workspace and the user has to move it by hand. Run the wrappers from the
  project directory instead and the GLB lands in `assets/clean/` and stages
  to `Assets/Models/AI/` automatically.
- **Generator and flag choice.** `-g trellis2`, `--polycount`, `--best-of`,
  `--judge-mesh` and `--lods` are all reachable from the shell. The bridge
  is locked to the SF3D default because the add-on has no way to send
  options.
- **Blender stays responsive.** The add-on runs commands on Blender's main
  thread, so a bridge generation freezes the UI for its whole duration
  (~80s for text → 3D). The shell door's only Blender call is the import,
  which is sub-second.

**Never route a slow generator through the bridge.** TRELLIS.2 is ~5–6
min/asset; through the bridge that freezes Blender for the entire run and
will likely exceed the MCP client's timeout. Slow generators take the shell
door, always.

**Tell the user which door you used** whenever it changes where the file
landed. Global workspace versus project staging is exactly the kind of
difference they would otherwise discover much later.

The bridge runs under launchd (`com.kenallred.blender-bridge`) and starts at
login. If a bridge call fails, check it is up before debugging anything else:

```bash
curl -s http://127.0.0.1:8081/health
```

