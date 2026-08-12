---
name: asset-pipeline
description: Use whenever the user wants to generate a 2D image, a 3D game asset, prepare a 3D asset for 3D printing, run a model bake-off, inspect or upscale textures, or submit jobs to the two-machine queue on their local pipeline. Auto-detects the active project (Unity, Unreal, or any directory with a .asset-pipeline.json config) and routes outputs into that project's assets/ folder. Falls back to ~/3d-pipeline/workspace/ when run outside any project. Reads ~/3d-pipeline/.config to detect the hardware tier (laptop vs studio) and behaves accordingly. Triggers on requests like "generate a 3D model from this image", "make me a 2D concept", "create a 3D asset for my game", "convert this image to 3D", "prepare this for 3D printing", "make an STL for my Snapmaker", "compare SF3D vs SPAR3D", "run a benchmark", "upscale this texture", "queue this job on the other Studio", or any mention of SF3D, SPAR3D, TRELLIS.2, FLUX, Z-Image, mflux, Real-ESRGAN, concept art, or the Snapmaker U1. Handles text-to-2D (mflux), 2D-to-3D (SF3D / SPAR3D / TRELLIS.2 + Blender), GLB-to-STL print preparation, Unity/Unreal engine import, model bake-offs, texture inspect/upscale, and the experimental two-machine job queue.
---

# Asset Pipeline (2D + 3D + Print)

Drives the user's local asset generation pipeline. The user runs this on
two hardware tiers, both Apple Silicon. The wrappers and this skill are
shared; the only thing that differs between tiers is the `.config` file
and which experimental lanes are reasonable to recommend.

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

On a fresh install, before any asset work, ask the user to run:

```bash
~/3d-pipeline/workspace/pipeline_doctor.py --check all
```

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

## Three pipeline halves + four (now six) new lanes

The three core halves are unchanged:

- **2D** — text → image via mflux
- **3D** — image → mesh via SF3D (default) / SPAR3D / TRELLIS (v1) / TRELLIS.2 (v2), then Blender cleanup
- **Print** — clean GLB → printable STL via Blender mesh repair + scaling

v0.2 added four lanes; v0.3.2 adds a fifth; v0.4 adds a sixth. None are defaults:

- **Texture inspect/upscale** (`texture.sh`) — GLB and image stats, optional
  Real-ESRGAN upscale. Paint mode (Hunyuan3D-Paint) approved v0.3.0.
- **Model bake-off** (`benchmark.sh`) — runs a prompt suite across selected
  2D models and 3D generators, writes structured results.
- **Queue** (`queue_submit.py` / `queue_worker.py`) — file-based two-machine
  job queue. **Studio-tier recommendation only.** It works on a laptop but
  the value is multi-machine.
- **SPAR3D** (`generate.sh -g spar3d`) — alternative 3D generator. Opt-in
  and experimental.
- **Multi-view 3D reconstruction** (`multiview.sh`, v0.3.2+) — Flow 9.
  Takes 3+ views of one subject and reconstructs a single mesh. Backend
  default is TRELLIS multi-view (`non_commercial`); openlrm
  (`commercial_safe`) and instantmesh (`unclear_risky`) opt-in.
- **Edit lane** (`edit.sh`, v0.4+) — Flow 10. Instruction-based concept
  edits and parametric camera-angle views via Qwen-Image-Edit-2511
  (`commercial_safe`). Angle-view mode's LoRA is currently a known
  no-op upstream in mflux — see Flow 10.

---

## License buckets

Use these exact names in conversation, manifest entries, and JSON output:

| Bucket                          | Models                                              |
| ------------------------------- | --------------------------------------------------- |
| `commercial_safe`               | z-image-turbo, flux-schnell, qwen-image, trellis2   |
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
- `defaults.generator_2d`: `"z-image-turbo" | "flux-schnell" | "flux-dev" | "flux2-klein" | "ernie-image" | "qwen-image"`
- `defaults.generator_3d`: `"sf3d" | "spar3d" | "trellis" | "trellis2"`
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

Determine which of the nine flows applies:

1. **Text → 2D only** — prompt only, image output
2. **2D → 3D** — image input, GLB output for games
3. **Text → 2D → 3D** — prompt only, GLB output (chain 1 + 2)
4. **GLB → printable STL** — existing 3D asset, STL output for the Snapmaker U1
5. **Text → 2D → 3D → STL** — full pipeline ending at a printable file
6. **Texture inspect / upscale / paint** — describe a GLB or image, upscale a texture, or paint PBR textures onto a mesh (Hunyuan3D-Paint, v0.3.0+)
7. **Model bake-off / benchmark** — compare two or more model paths on the same prompts
8. **Queue-based batch generation (studio-tier, experimental)** — submit work that one of the Studios will pick up
9. **Multi-view 3D reconstruction (v0.3.2+, Tier 3)** — 3+ views of one subject → single 3D mesh; for photogrammetry or recovering back-face detail

If unclear, ask one short question. Common defaults:
- "make me a [thing] for my game" → flow 3
- "make me a [thing] I can 3D print" → flow 5
- "prepare [asset] for printing" or "make an STL of [asset]" → flow 4
- "inspect this GLB" / "upscale this texture" / "paint this mesh" → flow 6
- "compare SF3D and SPAR3D" / "which 2D model is best for this prompt" → flow 7
- "queue these on the other Studio" → flow 8 (studio tier only)
- "I have multiple photos of this" / "reconstruct from these views" → flow 9

**When chaining or scripting, always pass `--json` to the wrappers.** The
JSON is stable and parseable; the human-readable lines under `--json` are
routed to stderr so they don't corrupt the result.

---

## Flow 1: Text → 2D image

Use `concept.sh` with the user's prompt. Default model is Z-Image Turbo
(commercial_safe, ~10-30s) — this default is unchanged by item 20; don't
switch it silently (principle P-A).

| Situation | Model | Why |
|---|---|---|
| Default | `z-image-turbo` | Fast, `commercial_safe`, good general quality |
| A FLUX-ecosystem LoRA is needed, or built-in instruction editing | `flux2-klein` (item 20) | Same checkpoint does generation + instruction edits; `commercial_safe` (Apache 2.0 — the FLUX.2 family's permissive exception; 9B/dev variants are NOT, don't substitute those) |
| A FLUX.1-era LoRA specifically is needed (legacy) | `flux-schnell` | `commercial_safe`; kept working, no longer the recommended LoRA path — prefer `flux2-klein` for new LoRA work |
| Prompt adherence is weak / 3/4-view compliance keeps failing on Z-Image | ~~`ernie-image`~~ **currently broken, see below** | Would be the strongest-at-release open t2i for prompt adherence; wired but non-functional pending an upstream fix |
| User accepts non-commercial output | `flux-dev` | Mention the `non_commercial` bucket explicitly |

**Z-Image Turbo's known weakness**: subjects tend to face the camera
head-on rather than at a 3/4 angle, even with the game-asset prompt
suffix. The suffix + `--judge`/`--best-of` (item 17) compensate for most
of this, but if a user keeps getting front-on results despite judge
rejections, suggest retrying with `flux2-klein` rather than just
re-rolling Z-Image seeds indefinitely — `ernie-image` would be the
other retry option but is currently broken (see below), so don't
suggest it yet.

**`ernie-image` is wired but currently non-functional** (verified live,
2026-08-12): mflux 0.18.1 (the latest release) expects a `text_encoder_2`
component that doesn't exist in either `baidu/ERNIE-Image`'s or
`baidu/ERNIE-Image-Turbo`'s actual current Hugging Face repo layout
(confirmed by listing both repos directly) — both fail identically with
`FileNotFoundError: No safetensors files found in .../text_encoder_2`.
This is an upstream mflux/HF-repo mismatch, not a pipeline bug, and not
fixable by re-wiring `concept.sh`. Don't suggest `-m ernie-image` to a
user until a newer mflux release fixes this — check `pip index versions
mflux` for a release past 0.18.1 first. The dispatch code stays in
place so no further wiring is needed once mflux does fix it.

**LoRA + FLUX.2/ERNIE**: FLUX.1 LoRAs (trained for `flux-schnell` /
`flux-dev`) are a different checkpoint architecture than `flux2-klein`
or `ernie-image` and are not interchangeable — `concept.sh` errors out
immediately with a message naming the mismatch rather than forwarding
it into a confusing mflux crash. If a user wants LoRA output on the
newer models, they need a LoRA actually trained for that model family;
there isn't a curated one in this pipeline yet.

For variations, use `-n N`. For specific names, `-o NAME`. Default output
is in `<project>/assets/concept/` or `~/3d-pipeline/workspace/concept/`.

The wrapper prints the absolute path as its last line — capture it for
chaining. If you're scripting, pass `--json` and parse the last stdout
line as JSON; `outputs[0]` is the first image.

### VLM judge + best-of-N (v0.3.5+, item 17)

`concept.sh` can score concepts against a rubric using a local VLM
(mlx-vlm + Qwen3-VL) instead of relying only on SigLIP/CLIP similarity.
The judge catches things prompt-adherence scoring misses — wrong camera
angle, cluttered background, harsh shadows — the exact failures that
later ruin image-to-3D reconstruction.

- `--judge` — score all generated variants (or the single image), write
  the ranking/verdict into meta.json's `judge` section, print it. Does
  not delete or move anything.
- `--best-of N` — generate N variants, judge them, keep the winner in
  `concept/`, move the rest to `concept/rejected/`. Implies `--judge`.

```bash
concept.sh "a treasure chest" --best-of 4
```

**Recognition signals.** Suggest `--best-of N` when the user wants "the
best one" from several tries, or has been regenerating the same concept
repeatedly hoping for a better angle/composition. Suggest plain
`--judge` when they want to see the scores but decide themselves.

**Relay the verdict in plain language**, not raw scores — see the
translation table below. If a variant's `visible_faces` shows only one
face (e.g. `"front only"`), that's why `three_quarter_view` scored low;
mention it if the user asks why a variant lost.

**Cost.** The default judge model is the 30B-A3B MoE tier (~17 GB,
first-use download), not the smaller 8B tier — R0.3's spike found the
8B tier does not reliably catch camera-angle violations, even with an
explicit reasoning-first rubric; the 30B tier does. Mention this before
suggesting `--best-of` on a laptop with limited disk. Judge latency is
a few seconds per image after the model is loaded once.

**When NOT to suggest it:** a single one-off generation the user is
already happy with; `vlm-env` not installed and the user wants to
generate right now (offer it as a follow-up instead).

**Concept doctor (v0.6.1, `--auto-retry`).** With `--best-of N`, if the
judge rejects every variant (all below the floor), `--auto-retry` sends
the prompt plus the judge's scores to an OpenAI-compatible chat endpoint
(`$PIPELINE_PROMPT_DOCTOR_ENDPOINT`) which rewrites the prompt to target
the lowest-scoring dimensions (most commonly forcing a real 3/4 view),
then regenerates once with the rewritten prompt. Opt-in twice over: the
flag AND the endpoint must both be present, and a retry never retries
again. If the doctor endpoint is unset or fails, the run keeps the
rejected winner exactly as before.

**Remote judge endpoint (v0.6.1).** If `PIPELINE_JUDGE_ENDPOINT` is set
(or `vlm_judge.py --endpoint URL`), judge calls go to an OpenAI-compatible
vision chat server (e.g. `mlx_vlm server` on another machine) instead of
loading the model in-process — same rubric, temperature-0 sampling, and
scoring. With an endpoint set, `vlm-env` isn't required at all; an
unreachable endpoint warns and falls back to the in-process path. This is
generic wiring: nothing in the pipeline assumes any particular server
exists, and with the env var unset nothing changes. All wrappers
(`concept.sh`, `generate.sh`, `benchmark.sh`) inherit it automatically.

### Consistency mode (v0.3.2+, ComfyUI backend)

When the user needs **identity-locked** generations across multiple
prompts (multiple poses of one character, weapon-family variants, a
coherent prop set), route through ComfyUI instead of mflux:

```bash
concept.sh "the hero swinging a sword" \
    --backend comfyui \
    --consistency-pack ~/3d-pipeline/consistency-packs/grithkin-hero
```

**Recognition signals.** Use consistency mode when the user says:
- "generate multiple poses of [character]"
- "make N variants of the same [character / weapon / prop]"
- "this should look like the same [character] across all images"
- mentions a specific named character they want to keep consistent

A consistency pack is a directory containing `pack.json`, reference
images for IP-Adapter / ControlNet, and an optional LoRA. Format
spec: `docs/consistency-pack-format.md`. Users build their own packs
once per character / asset family.

**License bucket.** The pack's `pack.json` declares the bucket; the
wrapper resolves the most-restrictive of (pack-declared, base-model
default). SDXL defaults to `commercial_threshold`; an
`unclear_risky` LoRA in the pack would bump it higher. State the
resolved bucket inline (same convention as picking SPAR3D over SF3D
in Flow 2).

**Prerequisites.** ComfyUI must be installed (section 10 in both
setup guides) and running on `http://127.0.0.1:8188`. The
dispatcher fails with `comfyui_server_unreachable` if it isn't.
Tell the user to start it first:

```bash
source ~/3d-pipeline/comfyui-env/bin/activate
cd ~/3d-pipeline/ComfyUI && python main.py --port 8188
```

**Speed.** SDXL via ComfyUI is 15–30s per image vs. 5–10s for
mflux. Mention this when offering consistency mode; if the user
only needs one variant, mflux + LoRA is faster and uses less disk.

**When NOT to suggest consistency mode:**

- User has only one prompt and won't iterate on the same subject
  later — mflux is sufficient
- User explicitly wants the variation that mflux gives them
  (e.g., "8 different chest designs" — those aren't supposed to
  be the same chest)
- ComfyUI isn't installed and the user wants to start generating
  immediately — installation is 10+ GB and takes a while; offer
  mflux now and consistency mode after install

## Flow 2: 2D image → 3D asset

Use `generate.sh` with `-i <image_path>`. Default to SF3D unless asked
for SPAR3D, TRELLIS (v1), or TRELLIS.2 (v2, item 15) — or the asset
needs unusual topology or real PBR at higher geometry density than
SF3D gives. Mention the license bucket if you pick anything other than
SF3D. **TRELLIS and TRELLIS.2 are two different models — v1 is
`non_commercial` and vertex-colors-only; v2 is `commercial_safe` with
real PBR but the slowest generator in the pipeline (~5–6 min/asset).**

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

### Mesh judge (v0.3.6+, item 18)

`generate.sh --judge-mesh` renders a turntable (default 8 views,
independent of `--preview`) of the cleaned GLB and scores it with the
same local VLM judge as Flow 1's concept judge: recognizable-as-object,
back-face plausibility, geometry artifacts (slivers/holes/floaters),
and texture coherence. It catches "bad but valid" meshes that heuristic
checks miss — a mesh can pass every structural check and still look
wrong to a person.

```bash
generate.sh -i concept/chest.png --judge-mesh
```

**Warn, don't block.** A below-floor verdict (default <2/10) flags the
asset as "likely degenerate — regenerate recommended" in meta.json and
the console output. It never fails the run — the GLB is still produced
and staged normally.

**Recognition signals.** Suggest `--judge-mesh` when the user is about
to commit an asset to their project and wants a sanity check, or has
seen degenerate output from this generator/prompt combination before.
Skip it for quick iteration passes where they'll eyeball the result
themselves anyway.

**Relay findings in plain language.** If `judge.mesh.notes` names a
specific artifact (e.g. "2 floating fragments near the base"), say
that — not the raw score. If `cleanup.loose_elements_deleted` is
non-zero, mention that cleanup already removed some loose geometry
before the judge ran, so a floater note may be describing something
already partly addressed.

**When NOT to suggest it:** `vlm-env` not installed; the user is mid
rapid-iteration and doesn't want the extra render+judge latency (a few
seconds of render plus judge time on top of the normal pipeline).

### Translation map (v0.3+ user-friendly language)

The wrappers and Claude both speak engine-jargon natively, but the
user does not. When relaying quality-check output, translate via
this table (cross-cutting principle 8 from improvement-spec.md):

| Engine term | User-facing translation |
|---|---|
| "non-manifold edge" / "boundary edge" | "small gap in the surface" |
| "is_watertight=true" | "fully sealed (good for printing)" |
| "is_watertight=false, hole_count=N" | "N small gap(s) in the surface — may still print" |
| "UV island" | "texture patch" |
| "decimate ratio 0.16" | "simplified mesh: 18,400 → 3,000 polygons" |
| "alpha_mean 0.42" | "subject takes up about 42% of the image" |
| "SigLIP similarity 0.16, band p50_or_better" | "image matches your prompt: very good" |
| "SigLIP similarity 0.04, band below_p10" | "image matches your prompt: weak — consider re-generating" |
| "non-manifold internal shell" | "hidden geometry inside the mesh" |
| "wall thickness 0.4mm" | "thinnest part is 0.4mm — may fail to print" |
| "extreme_aspect_ratio" | "image is unusually wide/tall — output mesh will be distorted" |
| "low_resolution" | "image is below 512px — output quality will suffer" |
| "image_reward 1.6" | "people-preference score: strong (ImageReward typically ranges roughly -2 to +2)" |
| "image_reward -0.3" | "people-preference score: weak — the image is technically on-prompt but doesn't look great" |
| "dreamsim_dupes: [[1, 3]]" | "variants 2 and 4 look like near-duplicates" |
| "dreamsim_dupes: []" | "all variants are visually distinct" |
| "judge.verdict 9, three_quarter_view 9" | "judge picked this one — good angle, clean composition (9/10)" |
| "judge.verdict 5, three_quarter_view 3, visible_faces: front only" | "judge flagged this — shot straight-on, no side visible, may hurt the 3D reconstruction" |
| "judge.rejected: true" | "judge thinks this one is likely unusable — consider regenerating" |
| "judge.mesh.verdict 8, geometry_artifacts 9" | "3D check: looks solid — clean geometry, recognizable shape (8/10)" |
| "judge.mesh.rejected: true, notes: '2 floating fragments...'" | "3D check flagged this one — 2 floating fragments near the base, likely worth regenerating" |
| "judge.mesh.scores.texture_coherence: null" | "mesh has no texture yet, so the judge only checked geometry" |

When a check emits a raw value (in `--json` mode), translate before
speaking to the user. The wrapper already pre-translates some lines
for stderr (`[pipeline] Mesh: fully sealed (good for printing)`),
but if you're reading meta.json directly, do the translation here.

### Mesh quality check (v0.3+)

After cleanup, the wrapper runs a watertight + scale sanity check
on the cleaned GLB. Output looks like:

```
[pipeline] Mesh: fully sealed (good for printing) — 0 holes
```

Or when problems:

```
[pipeline] Mesh: 3 small gap(s) in the surface (may still print)
[pipeline] Scale: ⚠ longest dim 0.0008 is outside the sane normalized range
```

Skill behaviour:

- `is_watertight=false` + low hole count (1–3) → mention to the user;
  print may still work via Orca's Auto Repair
- High hole count (> 10) → strongly recommend re-generation
- `scale.in_sane_range=false` → almost always a generator bug; offer
  to re-generate with a different seed

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

### LOD chain + UV re-unwrap (v0.4+, item 23)

```bash
generate.sh -i concept/chest.png --lods "3000,1000,300"
generate.sh -i concept/chest.png --reuv
```

**`--lods "N,N,N"`** (descending target polycounts) emits
`clean/<name>_lod{0,1,2}.glb` via `gltfpack`, plus runs a gltfpack
optimize pass (no quantization) on the base clean GLB itself. Engine
staging copies the whole LOD set alongside the main GLB when
applicable, same `_lod0`/`_lod1`/... suffix.

**Real finding worth relaying to the user:** gltfpack's default
quality cap (`-se`, 1% max deviation) means the *actual* resulting
polycount can land well above the target, especially for aggressive
reductions — `generate.sh` uses `-sa` (aggressive) to get closer, but
still won't hit the exact number. Each `cleanup.lods[]` entry in
meta.json records both `polycount` (actual) and `polycount_target`
(requested) — check both, don't assume they match. Requires
`gltfpack` on PATH; **no Homebrew formula exists** — it's a prebuilt
binary from
[meshoptimizer's GitHub Releases](https://github.com/zeux/meshoptimizer/releases).
`--lods` fails clearly (`status=error error=not_installed`) rather
than silently skipping when missing.

**`--reuv`** re-unwraps UVs from scratch via `xatlas` when item 13's
UV check (`quality.uv.occupancy_ratio`) reports low occupancy
(< 40%) or a high island count. **Warn-suggested, never automatic**
— only run it when the user asks or you've flagged low occupancy and
they agree.

**Hard refusal, not just a warning:** `generate.sh` checks
`quality.textures.textures_present` (already computed by the quality
checks that run before this) and refuses with
`status=error error=already_textured` if the mesh already has baked
textures — re-unwrapping would invalidate them. `--reuv` is only for
untextured meshes (vertex-color-only output, or before a
`texture.sh --mode paint` pass — same "before paint" rule as item
19's paint-mode refusal). Relay the refusal message; don't retry.

**Known ceiling:** the re-unwrapped mesh does not preserve vertex
colors if the input had them (`cleanup.reuv.vertex_colors_discarded`
in meta.json) — reuv's own worldview is "about to be freshly
textured," not "the vertex colors are the final look."

### Quad retopo — QuadWild bi-MDF (v0.4+, item 25)

```bash
generate.sh -i concept/chest.png --retopo quad
generate.sh -i concept/chest.png --retopo quad --retopo-timeout 300
```

Opt-in, replaces the mesh's decimated tri-soup topology with a
quad-dominant retopology via [QuadWild bi-MDF](https://github.com/cgg-bern/quadwild-bimdf)
(`quadwild` + `quad_from_patches`, both required on PATH — GPL-3 CLI,
`commercial_safe` bucket: tool-side copyleft only, no shipped weights,
generated GLB outputs unaffected). Suggest it for assets headed to
sculpt, animation, or close-up — not for background props, where the
default decimated mesh is fine.

**Same "before paint, never after" ordering rule as item 23.** Hard
refusal (not a warning) on an already-textured mesh — retopo discards
topology and any UV layout unconditionally. Same
`quality.textures.textures_present`-based refusal mechanism as
`--reuv` and paint mode. **In practice this means SF3D's own output
already has baked textures at generation time**, so `--retopo` refuses
immediately after a default SF3D run — it needs an untextured
mesh, same constraint `--reuv` already has. Relay the refusal
message; don't retry.

QuadWild's own output OBJ carries no UV data at all (verified by
inspection — zero `vt` lines), so run `--reuv` right after a
successful `--retopo quad` to give the new topology a UV layout before
any texture pass.

**Real finding worth relaying to the user:** `quad_from_patches`'s
exit code is not a reliable success/failure signal on its own —
`retopo_quad.py` checks for the actual expected output file instead.
Records `cleanup.retopo: {method, faces_before, faces_after,
quad_fraction, watertight}` in meta.json.

**Timeout:** pathological input meshes can hang the solver — each of
QuadWild's two steps (prep/remesh, then quadrangulation) is killed
after `--retopo-timeout` seconds (default 600) and reported as
`status=error stage=retopo error=timeout`. Requires both `quadwild`
and `quad_from_patches` on PATH; **no Homebrew formula exists** — both
binaries ship together in the prebuilt
[macOS release zip](https://github.com/cgg-bern/quadwild-bimdf/releases)
(arm64+x86_64 universal). `--retopo` fails clearly
(`status=error error=not_installed`) rather than silently skipping
when missing.

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

When consistency mode is appropriate (recurring character / asset
family — see Flow 1's "Consistency mode" subsection), pass
`--backend comfyui --consistency-pack PATH` through to flow 1's
`concept.sh` call. Flow 2's 3D generators (SF3D / SPAR3D /
TRELLIS) handle ComfyUI's outputs the same way they handle mflux's.

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

## Flow 9: Multi-view 3D reconstruction (v0.3.2+, Tier 3)

Use `multiview.sh` when the user has **multiple views of the same
subject** (3+ images) and wants a single 3D mesh that respects all of
them — rather than running `generate.sh` on just one view and hoping
the back-face hallucinates correctly.

**Trigger phrases:** "I have multiple photos of this", "use these
reference images", "reconstruct from these views", "photogrammetry",
"turn these N photos into a 3D model".

**Two input modes:**

```bash
# Canonical 4 cardinal-angle views (front, right, back, left):
multiview.sh -i front.png,right.png,back.png,left.png

# Explicit per-view manifest (for non-cardinal angles, e.g. Zero123++'s
# 6 native angles with alternating elevation):
multiview.sh -m views.json
```

Manifest schema (`-m` mode):

```json
[
  {"path": "v0.png", "view": "front",     "azimuth_deg": 0,   "elevation_deg": 0},
  {"path": "v1.png", "view": "right",     "azimuth_deg": 90,  "elevation_deg": 0},
  {"path": "v2.png", "view": "right_up",  "azimuth_deg": 90,  "elevation_deg": 30}
]
```

**Backend choice** (`--backend`):

| Backend | License bucket | When to suggest |
|---|---|---|
| `trellis` (default) | `non_commercial` (CC BY-NC) | Best general-purpose match; same bucket as the existing TRELLIS single-image path so the user already knows what they're accepting |
| `instantmesh` | `unclear_risky` | Don't recommend until P3.1b's license review completes — the wrapper auto-DQs it from benchmark scoring for the same reason. If the user explicitly asks, mention the risk and proceed only with explicit acknowledgement |
| `openlrm` | `commercial_safe` (Apache 2.0) | Recommend when the user needs a commercially-clean license; quality may be lower than TRELLIS so warn the trade-off |

**Always state the license bucket inline** (same convention as Flow 2's
generator-selection matrix).

After the backend runs, the wrapper applies the same Blender cleanup +
v0.3 quality checks (mesh / texture / UV / engine) + turntable preview
+ engine staging as `generate.sh`. The output GLB lands in
`assets/clean/<name>_clean.glb` with a co-located meta.json.

**When to suggest multi-view over single-image:**

- User has 3+ images of the same subject (photos or AI-generated)
- Asset has visible back / side detail (asymmetric character, prop with
  features on multiple sides)
- Single-image generations have repeatedly hallucinated the back face
  for this asset class
- Photogrammetry use case (capturing a real physical object)

**When NOT to suggest multi-view:**

- User has only one image — Flow 2 (`generate.sh`) is correct
- Asset is rotationally symmetric (a barrel, a sphere) — single image
  gives the same result with less effort
- Commercial release + only TRELLIS is installed — the
  `non_commercial` bucket disqualifies; either install OpenLRM first
  or recommend Flow 2 with SF3D/SPAR3D

**Chaining example** (full mvgen → 3D path):

> "I'll feed your concept image to Zero123++ to generate 6 multi-view-
> consistent images, then reconstruct a 3D mesh from those via TRELLIS
> multi-view. License bucket `non_commercial` — confirm before we
> ship anything from this in Grithkin."

(That chain currently requires you to invoke `build_mvgen_dataset.py`
manually to get the views and then `multiview.sh -m <generated-manifest>`;
a future feature will wrap the chain behind a single
`generate.sh --multiview-from-concept` flag once the benchmark picks
a canonical chain.)

---

## Flow 10: Edit a concept / generate camera-angle views (v0.4+)

Use `edit.sh` when the user wants to **change an existing concept image**
in place, or wants **additional camera angles** of it to feed into
Flow 9's multi-view reconstruction. Both modes call
Qwen-Image-Edit-2511 (`commercial_safe`, Apache 2.0) and always run a
DreamSim drift check afterward so a no-op or over-aggressive edit is
caught automatically instead of silently shipped.

**Trigger phrases:** "make this darker/older/mossier", "edit this
concept", "I need a side view of this", "give me more angles of this
image", "tweak the color on this".

**Instruction-edit mode** — free-text change to a concept image:

```bash
edit.sh -i concept/chest.png "make the wood darker and more weathered"
# -> concept/chest_edit1.png (auto-numbered; re-running keeps prior edits)
```

**Angle-view mode** — parametric camera rotation via the official
Multiple-Angles LoRA:

```bash
edit.sh -i concept/chest.png --angle 90,0
# -> concept/chest_090deg.png
```

`--angle H,V` takes azimuth (0=front, 90=right, 180=back, 270=left)
and elevation (-30/0/30/60) in degrees, snapped to the LoRA's real
8×4 grid — read this off the tool's own "requested X,Y -> snapped
X,Y" line, don't assume the exact number you passed was used.

> **Known limitation — tell the user before they rely on `--angle`:**
> as of mflux 0.18.1, the Multiple-Angles LoRA's diffusers-style key
> names (`transformer_blocks.N.attn.*.lora_A/B`) don't match mflux's
> internal Qwen-Image-Edit-2511 layer names, so mflux applies **zero**
> LoRA weight (confirmed live: "Applied to 0 layers (0/1680 keys
> matched)", and the output image showed no rotation at all versus
> the source). This is tracked upstream at
> github.com/filipstrand/mflux/issues/298, not something fixable from
> this repo. `edit.sh` detects the 0-key-match case itself, prints a
> loud warning, and records `angle_lora_applied: false` in the
> output's meta.json — always check that field (or watch for the
> warning) before treating an `--angle` output as a real rotated view.
> Instruction-edit mode is unaffected and fully working.

Outputs from either mode land in the same `concept/` directory as
`concept.sh`, so angle-view outputs (once the upstream LoRA gap is
fixed) are ready to feed straight into `multiview.sh`.

**Drift check:** every run prints `[edit] edit drift: 0.NNN (band)`.
`too_similar` means the edit likely had no real effect (re-run with a
stronger instruction); `too_different` means the subject may have
changed rather than just the requested attribute. `similar_but_changed`
is the expected healthy result. These bootstrap thresholds
(0.03/0.45) are uncalibrated — treat the band as a hint, not a hard
gate.

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
