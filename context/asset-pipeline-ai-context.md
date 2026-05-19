# Asset Pipeline · AI Context Document

*A technical context document for AI assistants helping Ken with his local 2D/3D/print asset generation pipeline.*

---

> **For AI assistants**
>
> This document is intentionally dense. It transfers the architectural reasoning, trade-offs, and failure history of a working pipeline so a future AI can help maintain, extend, or troubleshoot it without needing follow-up context. Read top-to-bottom for the full mental model; sections are designed to be reasonably self-contained for targeted lookup. Throughout, "Ken" refers to the human user.

---

## Table of contents

**Context**
- [00 · Audience & purpose](#00-audience-purpose)
- [01 · The user](#01-the-user)
- [02 · Problem space](#02-problem-space)
- [03 · Hardware & platform](#03-hardware-platform)

**Stack**
- [04 · 2D models](#04-2d-models)
- [05 · 3D models](#05-3d-models)
- [06 · Cleanup & repair](#06-cleanup-repair)
- [07 · 3D print stack](#07-3d-print-stack)
- [08 · Licensing landscape](#08-licensing-landscape)

**Architecture**
- [09 · System overview](#09-system-overview)
- [10 · Bash wrappers](#10-bash-wrappers)
- [11 · Shared library](#11-shared-library-_pipeline_libsh)
- [12 · Project awareness](#12-project-awareness)
- [13 · The Claude Code skill](#13-the-claude-code-skill)
- [14 · The asset manifest](#14-the-asset-manifest)

**Decisions**
- [15 · Why bash, not Python](#15-why-bash-not-python)
- [16 · Why one venv per tool](#16-why-one-venv-per-tool)
- [17 · Why a Claude Code skill, not a CLI Claude can call](#17-why-a-claude-code-skill-not-a-cli-claude-can-call)
- [18 · Why mflux, not diffusers](#18-why-mflux-not-diffusers)
- [19 · Why TRELLIS is optional](#19-why-trellis-is-optional)

**Rough edges**
- [20 · Setup failures we've already hit](#20-setup-failures-weve-already-hit)
- [21 · Runtime failure modes](#21-runtime-failure-modes)
- [22 · Known limitations](#22-known-limitations)

**Working with this**
- [23 · How to help the user effectively](#23-how-to-help-the-user-effectively)
- [24 · Extension points](#24-extension-points)

---

## v0.2 hardware-tier notes (laptop)

This is the **laptop-tier** AI context. The pipeline now also targets two Apple M3 Ultra Mac Studios; the additional studio-only decisions (queue, shared storage, full-suite bake-offs, 512 GB headroom narrative) live in [`asset-pipeline-ai-context-studio.md`](asset-pipeline-ai-context-studio.md). Read this file first; the studio doc is a delta.

Tier detection: every wrapper and the Claude Code skill read `~/3d-pipeline/.config` for `hardware_tier = laptop | studio`. The default is `laptop` when the file is absent. The wrappers never sniff hostname — explicit config is the contract.

License-bucket vocabulary (used in code, `--json`, manifest, docs — exact names):

- `commercial_safe`: z-image-turbo, flux-schnell, qwen-image
- `commercial_threshold`: sf3d, spar3d
- `non_commercial`: flux-dev, trellis
- `source_available_restricted`: reserved
- `unclear_risky` / `unknown`: LoRAs, anything untagged

New wrappers and flags in v0.2 (covered in detail throughout the architecture and decisions sections):

- `concept.sh --json`, `generate.sh --json`, `print.sh --json` — structured output; subcommand stdout routes to stderr. Every JSON line includes `hardware_tier` and `machine`.
- `print.sh --allow-oversize` — per-axis 270 mm validation; pass the flag only when you've decided to print in pieces.
- `generate.sh --overwrite-engine` and the new collision-aware engine staging (auto-suffix `<name>_2.glb`, etc.) when `naming.auto_increment_collisions=true`.
- `generate.sh -g spar3d` — optional, experimental, `commercial_threshold`.
- `scripts/json_emit.py` — typed key=value → JSON helper used by every wrapper.
- `scripts/texture.sh` (`--mode inspect|upscale`) + `scripts/texture_inspect.py` — GLB and image stats; Real-ESRGAN ncnn-vulkan integration.
- `scripts/benchmark.sh` + `scripts/model_bakeoff.py` — model bake-off harness.
- `scripts/queue_submit.py` + `scripts/queue_worker.py` — file-based job queue (studio-tier in practice; works single-machine but the operational recipe is in the studio doc).

> **🔵 Context — Why the laptop guide isn't getting much smaller**
>
> v0.2's defaults are identical to v0.1 (Z-Image Turbo → SF3D → Blender → Snapmaker U1). The wrappers grew flags; they didn't change behaviour when those flags aren't used. So everything below in this document is still accurate for laptop-tier work. The studio doc covers what's actually new architecturally — multi-machine queue, full-suite bake-offs, shared storage.

---

## 00 · Audience & purpose

This document exists because the asset pipeline has accumulated non-obvious architectural decisions over a long development arc, and most of the reasoning isn't visible in the code itself. The setup guide and workflows guide tell users *what* and *how*; this document tells future AI assistants *why*.

If an AI assistant — Claude, GPT, Gemini, or any successor — is asked to extend, modify, troubleshoot, or explain this pipeline, this document should provide enough context to reason productively about the system without re-deriving every decision from scratch.

### Companion documents

- `asset-pipeline-guide.html` — user-facing setup instructions, step-by-step
- `asset-pipeline-workflows.html` — click-by-click usage scenarios in conversational form
- `asset-pipeline-upgrade-guide.md` — migration path for pre-project-aware installs
- `~/.claude/skills/asset-pipeline/SKILL.md` — the skill that drives Claude Code's behavior with this pipeline

Those documents are authoritative for usage; this one is authoritative for reasoning.

---

## 01 · The user

Knowing who's using this matters because it shaped many design decisions. The pipeline is built for a specific person with a specific working style, not a hypothetical "general developer."

| | |
|---|---|
| **Identity** | Ken Allred — experienced entrepreneur (previously founded and sold Primary Intelligence / TruVoice), now builds software products independently using AI-assisted development. |
| **Location** | Draper, Utah. |
| **Primary tool** | Claude Code on Apple Silicon Mac. |
| **Workflow style** | Multi-agent prompt pipelines, git worktrees, Beads task tracking, the "Olympian Protocol" multi-agent system. High familiarity with AI-assisted development but is *not* a traditional software engineer — leans heavily on AI for implementation details. |
| **Active projects** | Grithkin Battle Forge (game), GripCraft (pickleball paddle wrap business), pickleball management/tournament app (Kitchen Krew / Trushot / Court Boss). |
| **Hardware** | MacBook Pro M-series with 128 GB unified memory; Snapmaker U1 4-toolhead 3D printer. |
| **Operating context** | Almost always working inside Claude Code with the asset-pipeline skill enabled. Rarely runs wrappers directly from the terminal. |

> **🧠 Rationale — Why this matters**
>
> The pipeline optimizes for a Claude Code-driven workflow, not for bash power users. Wrappers are designed to print helpful context lines and produce predictable filenames so the AI driver can reason about state. The "`--project` flag is just a flag" mentality matters less than "the wrapper auto-detects sensibly so the AI doesn't have to pre-think about it."

---

## 02 · Problem space

### What Ken is trying to do

Generate game-ready 3D assets — and occasionally 3D-printable physical assets — from text or 2D images, locally, without subscription dependencies, and without ceding rights to the output. The pipeline supports three independent flows that chain:

1. **Text → 2D image** (concept art, game UI elements, reference imagery)
2. **2D image → 3D mesh** (props, characters, environments for Unity/Unreal)
3. **3D mesh → printable STL** (tabletop figures, props, hero display pieces)

Flows 1+2 chain ("make me a 3D treasure chest"); flows 1+2+3 chain ("make me a 50mm printable treasure chest"). Each can also run standalone.

### What he is *not* trying to do

- **Real-time generation** — minute-scale latency is fine; this isn't a live tool
- **Photorealistic rendering** — outputs are stylized game/print assets, not film-grade
- **Mass production at scale** — single-user workflow, not a service
- **Character rigging or animation** — static meshes only
- **Texture authoring from scratch** — relies on model-generated PBR or vertex colors

### Hard constraints

| | |
|---|---|
| **Commercial use** | Output must be shippable in commercial games. This rules out FLUX dev (non-commercial), TRELLIS (CC BY-NC), and certain LoRAs. Models chosen carefully — see [section 08](#08-licensing-landscape). |
| **Local execution** | No cloud API calls in the hot path. Privacy, cost, latency, and rights ownership all benefit. Acceptable to use HuggingFace as a one-time weights distribution channel. |
| **Mac native** | Apple Silicon, MLX or Metal/MPS where possible. No CUDA. This excludes many state-of-the-art models that haven't been ported. |
| **AI-driveable** | Every component must be callable by Claude Code with predictable I/O. CLI tools win over GUI tools. Filename conventions matter. |
| **Frictionless reuse** | Asset created today must be reproducible tomorrow with the same prompt + seed. Manifest tracks generation metadata. |

### Soft preferences

- **Apache 2.0 / MIT / permissive licenses** preferred over copyleft when comparable models exist
- **Speed over fidelity** for concept work (Z-Image Turbo's 8 steps over FLUX dev's 30+)
- **Engine awareness** — outputs should land where Unity / Unreal expect them, not in some intermediate folder the user has to manually move

---

## 03 · Hardware & platform

Apple Silicon dominates this design. Every architectural choice was filtered through "does this run well on M-series with unified memory?"

| | |
|---|---|
| **Architecture** | Apple M-series (M2 Ultra / M3 / M4 family). ARM64. |
| **Memory** | 128 GB unified memory on Ken's primary machine. Unified means GPU and CPU share the same memory pool — different from PC where GPU VRAM is a hard limit on model size. |
| **Compute** | Metal (low-level) and MPS (PyTorch's Metal backend). MLX (Apple's array framework) used directly by mflux for 2D models. |
| **OS** | macOS 14 Sonoma or later. Some tools assume macOS-specific commands (`open`, `brew`, `sed -i ''`). |
| **Python** | 3.10–3.12 supported. SF3D is brittle outside this range. Homebrew Python preferred; venvs for everything. |
| **Off-platform deps** | Blender (cask install), Snapmaker Orca (manual install), Git LFS for some model checkpoints. |

### What unified memory enables

On a 24 GB PC GPU, FLUX dev quantized to int8 barely fits. On a 128 GB Mac, you can run unquantized FLUX dev, SF3D, TRELLIS.2, and Blender concurrently. This is the key enabler — the pipeline assumes you can hold large models in memory without aggressive swap or offload, which makes the "just run everything locally" thesis viable.

> **🔵 Context — Memory budget by tool (rough, at runtime)**
>
> - `mflux + FLUX schnell q8`: ~14 GB
> - `mflux + FLUX dev q8`: ~16 GB
> - `mflux + Z-Image Turbo q8`: ~10 GB
> - `SF3D inference`: ~6 GB
> - `TRELLIS.2 inference`: ~10–14 GB depending on stage
> - `Blender headless cleanup`: ~2 GB
>
> None of these run concurrently in the current pipeline — each wrapper activates its venv, runs, deactivates. Memory pressure is sequential, not parallel. Still, the headroom matters because users with less RAM hit swap aggressively.

### What unified memory *doesn't* give us

Apple Silicon's MPS backend is still less mature than CUDA. Some operations fall back to CPU silently, dramatically slowing things down. Both SF3D and TRELLIS were ported with explicit MPS workarounds (`PYTORCH_ENABLE_MPS_FALLBACK=1` is required for SF3D). Some operations — notably `nvdiffrast` in TRELLIS — have no Mac port at all and are stubbed out, which is why TRELLIS produces vertex colors only (no PBR textures) on Mac.

---

## 04 · 2D models

Three 2D models supported, in order of preference:

| Model | License | Steps | Speed | When to use |
|---|---|---|---|---|
| **Z-Image Turbo** (default) | Apache 2.0 | 8 (typically 9) | 10–30s | Default for everything. Commercial-safe. High quality. Fast. No LoRA support. |
| **FLUX schnell** | Apache 2.0 | 4 | 5–15s | When a LoRA is needed (and the LoRA is FLUX-compatible). Stylization, character consistency. |
| **FLUX dev** | FLUX.1 Non-Commercial | 20–50 | 30–90s | Reserved for non-commercial work or evaluation. **Never** used for assets shipping in Ken's commercial games. |

### Why these three, not others

#### Why Z-Image Turbo is default

It's the rare model that combines Apache 2.0 licensing (no commercial use restrictions, no waterfall licensing of LoRAs to worry about), strong image quality competitive with FLUX schnell, and very fast inference. Released by Alibaba in mid-2025. The "Turbo" variant is distilled from a larger model and runs in 8 steps. *Default for new generations unless a specific reason exists to use FLUX.*

#### Why FLUX schnell still matters

The FLUX LoRA ecosystem is enormous — hundreds of trained styles, characters, art directions on Civitai. Z-Image has almost no LoRA ecosystem yet. When Ken wants to use a specific LoRA, that LoRA was almost certainly trained against FLUX, so we need FLUX schnell to use it. Schnell is Apache 2.0, distilled to 4 steps, and most LoRAs trained on FLUX dev work transparently with schnell with minor scale adjustments.

#### Why FLUX dev is still listed but rarely used

FLUX dev produces the highest-quality output of the three but its license forbids commercial use of the output. Including it makes the pipeline complete (some users *do* have non-commercial use cases), but the SKILL.md is explicit: never use FLUX dev for Ken's commercial work. If asked to generate something for Grithkin or GripCraft, the AI should refuse FLUX dev or warn aggressively.

### What about other models?

- **SDXL** — older, lower quality than current FLUX/Z-Image, but Apache 2.0. We don't use it because schnell + Z-Image dominate it on every metric except LoRA ecosystem (where SDXL is still huge — but FLUX is catching up fast).
- **SD3 / SD3.5** — Stability's licensing requires revenue-based commercial licensing. Hard pass for a pipeline that wants "set it and forget it" commercial safety.
- **Qwen-Image, Kolors** — explored but didn't make the cut. Qwen-Image is permissively licensed but underwhelming; Kolors has murky commercial terms.
- **Closed APIs (DALL-E 3, Imagen, Midjourney)** — disqualified on the local-execution constraint and the rights-ownership constraint.

### Runtime: mflux

The runtime for all three models is **mflux**, an MLX-native port. See [section 18](#18-why-mflux-not-diffusers) for why mflux and not diffusers.

---

## 05 · 3D models

Two 3D generators supported. SF3D is default; TRELLIS.2 is optional.

| Model | License | Output | Speed | When to use |
|---|---|---|---|---|
| **SF3D** (default) | Stability Community License (commercial OK under $1M ARR) | Textured GLB with PBR materials | ~10–20s per asset after weights cached | Default for everything. Game assets, props, decorations. Solid for stylized work. |
| **TRELLIS.2** (optional) | CC BY-NC 4.0 (non-commercial) | GLB with **vertex colors only** on Mac (PBR textures need nvdiffrast which has no Mac port) | ~30–60s per asset | Higher-fidelity geometry for hero assets when textures don't matter. Non-commercial use only. |

### Why SF3D as default

Three considerations stacked up:

1. **Commercial safe at Ken's scale.** Stability Community License permits commercial use up to $1M ARR. Ken's projects are far below that ceiling and likely to stay that way for years.
2. **PBR materials.** SF3D outputs textured GLBs with full PBR maps (baseColor, normal, roughness, metallic). These import cleanly into Unity (with glTFast) and Unreal 5.1+ (native GLB support). TRELLIS on Mac gives vertex colors only, which look adequate in some engines and bad in others.
3. **Speed.** SF3D is genuinely fast — sub-20-second generation after weights are cached. TRELLIS is 2–3× slower and produces inferior textures on Mac.

### Why TRELLIS is still in the pipeline (and why it's optional)

TRELLIS produces denser, sharper geometry than SF3D — sometimes meaningfully so for organic shapes (creatures, characters, sculptural pieces). When geometry quality matters more than commercial-safety (e.g., a personal art project), TRELLIS is the better tool. We keep it as an opt-in install because:

- The license blocks commercial use, so it can't be default
- The Mac port is mature for geometry but stubs out texturing
- The 15+ GB weight download is heavy if you're not going to use it

### What about Hunyuan3D, InstantMesh, others?

- **Hunyuan3D 2 / 2mini** — explored extensively. Hunyuan3D-2mini is Apache 2.0 and produces great geometry, but the Mac port is less mature than SF3D's and the texture stage requires a separate pass. Currently not in the default pipeline but a reasonable future addition.
- **InstantMesh** — older. Surpassed by SF3D on quality.
- **3DTopia, OpenLRM** — explored, lower quality than SF3D or TRELLIS.
- **Closed services (Meshy, CSM)** — disqualified on local-execution.

### The view-quality contract

Both SF3D and TRELLIS work from a single 2D image. They internally compute multi-view representations but the input is one image. This means the 2D prompt has to convey enough 3D form information:

- **3/4 view** is dramatically better than pure front or pure side
- **Clean white/neutral background** reduces background-bleed into geometry
- **Even diffuse lighting** avoids baked-in shadows that read as geometry
- **Single subject, centered** — multi-subject scenes confuse the back-projection

The default game-asset prompt suffix in `concept.sh` encodes these — "3/4 view, full subject centered, clean white background, even studio lighting, no harsh shadows, game asset, detailed". This is intentionally opinionated for game-asset use; the `--no-game-prompt` flag disables it.

---

## 06 · Cleanup & repair

Both SF3D and TRELLIS produce meshes that are *almost* game-ready but not quite. Cleanup happens via headless Blender Python scripts. Two distinct cleanup paths exist:

### Game-asset cleanup — `clean_asset.py`

Invoked automatically by `generate.sh` unless `--no-clean` is passed. Five-pass cleanup:

1. **Import** raw GLB
2. **Remove duplicate vertices** (often produced by the 3D model's mesh extraction)
3. **Recalculate normals** (outside, consistent)
4. **Decimate to target polycount** (default 3000, configurable via `-p`)
5. **Apply transforms** + normalize scale + center at origin
6. **Export** as Y-up GLB (Unity / Unreal convention)

### Print prep — `prepare_for_print.py`

Invoked by `print.sh`. Different concerns from game cleanup — game assets care about polycount and texturing; print assets care about manifold geometry and physical dimensions.

1. **Import** clean GLB
2. **Merge by distance** (vertex weld)
3. **Recalculate normals + face orientation**
4. **Fill holes** (size limit to avoid filling intentional gaps)
5. **3D Print Toolbox `print3d_clean_non_manifold`** if available — handles overlapping faces, self-intersections, internal walls
6. **Scale to mm** — resize longest axis to `--size` in millimeters
7. **Translate** lowest vertex to Z=0 (so Snapmaker Orca places it flat on the bed)
8. **Export** binary STL

### Why Blender, not pure Python (trimesh, open3d)?

Three reasons:

- **Blender's mesh editing operators are battle-tested.** Edge-collapse decimation, manifold repair, hole-filling — pure-Python equivalents exist but each has edge cases. Blender's been refined over decades.
- **The 3D Print Toolbox** ships with Blender and handles real-world print failure modes (zero-area faces, intersecting volumes, thin walls) better than anything else free.
- **One install, two scripts.** Adding trimesh + open3d + their dependencies (which conflict with the SF3D venv) just to avoid a Blender call isn't worth it.

Tradeoff: Blender's startup time adds ~3–5 seconds per cleanup call. Acceptable in a pipeline where the model inference is the dominant cost.

### Blender version compatibility

Both scripts handle the API differences between Blender 4.x (uses `wm.stl_export`) and 3.x (uses `export_mesh.stl`) with try/except blocks. Tested on 4.0–4.3.

---

## 07 · 3D print stack

The print path produces single-mesh STL files; coloring happens in the slicer, not the mesh.

### Why STL, not 3MF or OBJ

- **STL is universally supported** — every slicer handles it. 3MF is technically richer (embeds color, metadata) but adoption is uneven across slicers and the workflow benefit is small when Snapmaker Orca handles painting in-slicer anyway.
- **Snapmaker Orca's per-region paint workflow** means the source mesh doesn't need to carry color information — the user paints regions onto the imported model with a brush. So whatever color we'd encode in a 3MF would get thrown away.
- **STL is simpler to debug** — opens cleanly in Quick Look, in Preview, in countless online viewers.

### Why Snapmaker U1 / Snapmaker Orca specifically

| | |
|---|---|
| **Hardware** | Ken owns a Snapmaker U1 — 4-toolhead, multi-color FDM printer. 270×270×270 mm build volume. Up to 300°C hotends supporting PLA, PETG, TPU, PVA. |
| **Slicer** | Snapmaker Orca is based on OrcaSlicer with U1-specific machine profiles. Plain OrcaSlicer works but loses the auto-calibration features. |
| **Multi-color workflow** | Paint regions of the imported STL with brush/triangle/fill tools. Each painted region maps to one filament. This is why the print script copies the original concept image alongside the STL — it's a visual reference for the painting step. |

### Build-volume guardrails

The print script enforces U1's 270 mm build limit:

- Above 270 mm on the longest axis: reject with error
- Above 250 mm: warn but proceed (some non-longest axis might still exceed if the asset is awkward-shaped)
- Below 250 mm: proceed silently

The script does *not* currently check whether the non-longest axis exceeds 270 mm. This is a known gap — if a model is 200mm tall but 280mm wide, the script accepts it but the user finds out only in Orca. A future improvement would query the GLB's bounding box pre-scale and validate all three axes.

---

## 08 · Licensing landscape

This is the part most easily gotten wrong. The pipeline is engineered around a specific licensing thesis — commercial-safe by default, with explicit opt-in for non-commercial paths.

| Component | License | Commercial use? |
|---|---|---|
| Z-Image Turbo | Apache 2.0 | **Yes**, unrestricted |
| FLUX schnell | Apache 2.0 | **Yes**, unrestricted |
| FLUX dev | FLUX.1 NC | **No** — non-commercial only |
| SF3D | Stability Community License | **Yes**, up to $1M ARR |
| TRELLIS.2 | CC BY-NC 4.0 | **No** — non-commercial only |
| mflux runtime | MIT | Yes, unrestricted |
| Blender | GPL | Yes — outputs are not infected (free use of files Blender produced) |
| 3D Print Toolbox | GPL (Blender add-on) | Yes — same as Blender; outputs aren't GPL'd |
| FLUX LoRAs | varies — usually CC-BY or MIT, sometimes NC | Per-LoRA review required |

### The commercial-safe default path

Pipeline defaults are chosen so that running with no options produces commercial-safe output:

- 2D default: Z-Image Turbo (Apache 2.0)
- 3D default: SF3D (Stability Community License, well under $1M)
- Cleanup: Blender + 3D Print Toolbox (GPL, outputs not infected)

The user has to explicitly opt into FLUX dev or TRELLIS to leave the commercial-safe zone. The SKILL.md instructs Claude to refuse these for Ken's commercial projects (Grithkin, GripCraft) or to warn loudly if asked.

### What the SKILL.md says vs. what Ken can override

The skill is opinionated — if asked to "make a 3D model for Grithkin" using FLUX dev, the skill should either refuse or pivot to a commercial-safe alternative. If Ken explicitly says "use FLUX dev, I know it's non-commercial, this is just for me," the skill complies but notes the constraint. The default is protective.

> **🟢 Decision — Why we don't include high-quality non-commercial options as defaults**
>
> A pipeline that produces non-commercial output by default is a footgun. Even if the user knows the license today, an asset generated three months ago and used a year later in a commercial context creates legal risk. The asset manifest tracks which model produced each asset, so the constraint is queryable — but defaults still need to be safe.

---

## 09 · System overview

The pipeline is structured as three independent halves that chain, each with a CLI wrapper. The wrappers know about each other only through file outputs and the shared library.

```
    user / Claude Code
           │
           ▼
   ┌───────────────────┐
   │  concept.sh       │  text → 2D image
   │  generate.sh      │  2D image → 3D mesh (chained)
   │  print.sh         │  3D mesh → STL (chained)
   └───────────────────┘
           │   sources
           ▼
   ┌───────────────────┐
   │  _pipeline_lib.sh │  project detection, path resolution, config
   └───────────────────┘
           │   invokes
           ▼
   ┌──────────┬────────────┬──────────┐
   │ mflux    │ SF3D       │ Blender  │
   │ venv     │ TRELLIS.2  │ headless │
   │          │ venv(s)    │          │
   └──────────┴────────────┴──────────┘
           │   produces
           ▼
   ┌───────────────────────────────────────────┐
   │  outputs/
   │    concept/  raw/  clean/  print/         │
   │    asset_manifest.json                    │
   └───────────────────────────────────────────┘
           │   stages to (project mode only)
           ▼
   ┌──────────────────────────┐
   │  Unity: Assets/Models/AI/
   │  Unreal: Content/Models/AI/
   └──────────────────────────┘
```

### Component layers

1. **Drivers** — Claude Code skill (primary), CLI direct invocation (secondary). Both go through the wrappers.
2. **Wrappers** — `concept.sh`, `generate.sh`, `print.sh`. Provide CLI surface, parse args, resolve project context, invoke tool venvs, manage paths.
3. **Shared library** — `_pipeline_lib.sh`. Project detection, JSON parsing, config defaults, name resolution. Sourced by all three wrappers.
4. **Tool runtimes** — mflux (in mflux-env), SF3D (in stable-fast-3d/.venv), TRELLIS.2 (in trellis-mac/.venv), Blender (system-installed, called via subprocess). Each isolated.
5. **Blender helpers** — `clean_asset.py` and `prepare_for_print.py`. Python scripts invoked by `blender --background --python`. Not directly callable.
6. **Manifest** — `asset_manifest.json`. JSON index of every generated asset with provenance metadata.
7. **Auxiliary** — `migrate_assets.sh` for moving global assets into projects; `update_manifest.py` as the manifest updater (lives in skill).

### What flows where

- **Text → concept.sh** → PNG in `concept/`
- **PNG → generate.sh** → GLB in `raw/`, then cleaned GLB in `clean/`, then (project mode) copied to engine folder
- **GLB → print.sh** → STL in `print/`, color reference PNG copied alongside
- **Every generation → update_manifest.py** → row added to `asset_manifest.json`

---

## 10 · Bash wrappers

Three wrappers, each in `~/3d-pipeline/workspace/`. They follow a consistent structure.

### Common pattern

1. Parse args (long-form GNU-style: `--project`, `--model`, etc., with short aliases)
2. Source `_pipeline_lib.sh`
3. Call `resolve_project_context` to set output paths
4. Print context to stdout (so the user / AI sees where outputs go)
5. Activate the relevant tool venv
6. Invoke the underlying tool (mflux command, SF3D run.py, Blender)
7. Deactivate venv
8. (Optional) Copy outputs to engine path if Unity/Unreal detected
9. Print final output path on last stdout line for shell chaining

### `concept.sh` — text to 2D

| | |
|---|---|
| **Default model** | Z-Image Turbo (configurable via `-m` or config `defaults.generator_2d`) |
| **Default size** | 1024×1024 (configurable) |
| **Prompt suffix** | Appends game-asset suffix unless `--no-game-prompt` |
| **LoRA support** | FLUX models only, via `-l` path |
| **Output path** | `$ASSETS_ROOT/concept/<name>.png` |

### `generate.sh` — 2D to 3D

| | |
|---|---|
| **Default generator** | SF3D (configurable via `-g` or config `defaults.generator_3d`) |
| **Polycount** | 3000 default (configurable via `-p`) |
| **Texture resolution** | 2048 default (SF3D only, configurable via `-t`) |
| **Outputs** | `raw/<name>_raw.glb`, then `clean/<name>_clean.glb` |
| **Engine staging** | In project mode with Unity/Unreal detected, also copies clean GLB to `$ENGINE_PATH/<name>.glb`. Suppress with `--no-engine-stage`. |

### `print.sh` — clean GLB to printable STL

| | |
|---|---|
| **Required input** | Clean GLB (typically from `clean/`) |
| **Required size** | `-s` in mm (longest axis). No good default. |
| **Outputs** | `print/<name>.stl` + `print/<name>_color_ref.png` (copy of concept image if present) |
| **Hard limit** | 270 mm (U1 build volume); rejects sizes above |

### Why bash, not Python or a CLI framework

See [section 15](#15-why-bash-not-python).

---

## 11 · Shared library: `_pipeline_lib.sh`

Pure bash, sourced (not run) by all three wrappers. Encapsulates everything related to project detection and configuration.

### Exported functions

- `is_unity_project <dir>` — checks for `Assets/` and `ProjectSettings/`
- `is_unreal_project <dir>` — checks for `Content/` and `*.uproject`
- `find_project_root <starting_dir>` — walks up looking for any project marker
- `json_get <file> <dotted.path>` — reads JSON via embedded Python (no jq dep)
- `resolve_project_context <explicit_project> <pwd>` — main entry, sets all path globals
- `config_default <key> <fallback>` — read `defaults.X` from config with fallback
- `resolve_name <base> <dir> <ext>` — applies prefix + collision suffix
- `print_context` — prints the "Project:" / "Assets:" header

### Exported globals after `resolve_project_context`

- `PROJECT_ROOT` — absolute path, or empty in global mode
- `PROJECT_MODE` — `"project"` or `"global"`
- `PROJECT_ENGINE` — `"unity"`, `"unreal"`, or `"none"`
- `PROJECT_CONFIG` — path to `.asset-pipeline.json` (may not exist)
- `ASSETS_ROOT` — where to write concept/raw/clean/print
- `ENGINE_PATH` — final engine destination (empty if engine="none")
- `MANIFEST_PATH` — where to read/write the manifest
- `NAME_PREFIX` — optional filename prefix from config
- `AUTO_INCREMENT` — `"1"` or `"0"`

### Why Python-via-bash-heredoc for JSON, not jq?

jq is fast and elegant but requires a separate install. Python 3 is guaranteed to be present (the user already has it for SF3D / mflux). The `json_get` function embeds a small Python script via heredoc — adds maybe 50ms per call. Acceptable when called a handful of times per wrapper invocation.

> **🔵 Context — Performance note**
>
> Each `json_get` call spawns a Python interpreter. In a wrapper that reads 4-5 config values, that's ~250ms total. Not a problem for interactive use but would be if anything ran in a tight loop. The wrappers never do, so this is fine.

---

## 12 · Project awareness

The single biggest architectural decision after the initial pipeline shipped. The original version had hardcoded `~/3d-pipeline/workspace/` paths. Project awareness was added to support a more natural workflow when working on specific games.

### What problem it solves

Before: every asset went into one shared workspace. Names collided. Project boundaries didn't exist. Assets for Grithkin and the pickleball app mingled. Git couldn't version assets with their source project.

After: outputs land in `<project>/assets/`. Unity / Unreal projects also get auto-staging into their native engine folders. Each project gets its own manifest. Naming prefix lets projects assert ownership of their assets.

### Detection priority (in order)

1. `--project PATH` explicit flag
2. `PROJECT_ROOT` environment variable
3. Walk up from `$PWD` looking for `.asset-pipeline.json`
4. Walk up looking for Unity markers (`Assets/` + `ProjectSettings/`)
5. Walk up looking for Unreal markers (`Content/` + `*.uproject`)
6. Fall back to global workspace

Each step short-circuits on first match. "Closest match wins" — a nested `.asset-pipeline.json` beats a parent Unity project root.

### Configuration: `.asset-pipeline.json`

All fields optional. `{}` is valid and useful — it just marks a directory as a project.

```json
{
  "engine": "unity" | "unreal" | "none",
  "engine_path": "Assets/Models/AI",
  "defaults": {
    "generator_2d": "z-image-turbo",
    "generator_3d": "sf3d",
    "polycount": 3000,
    "texture_resolution": 2048,
    "lora": null
  },
  "naming": {
    "prefix": "",
    "auto_increment_collisions": true
  }
}
```

### Why Option A: `project/assets/...` + engine override

Three layouts were considered:

- **A** — `project/assets/{concept,raw,clean,print}/` with engine override hook (chosen)
- **B** — `project/.pipeline/...` hidden; clean GLBs go straight into engine folder
- **C** — `project/asset-pipeline/...` with explicit folder name

A won because:

- **Intermediates are inspectable.** A hidden `.pipeline/` folder makes "what did the AI generate?" harder.
- **Engine staging is additive.** Clean GLBs live in `assets/clean/` (the canonical version) *and* are copied into `Assets/Models/AI/`. Both files exist. The canonical one is preserved even if the user accidentally deletes the engine copy.
- **Non-engine projects work.** A folder with just `.asset-pipeline.json` and no engine markers still gets `assets/` structure.

### The auto-staging design

When `generate.sh` runs in project mode with Unity or Unreal detected, the cleaned GLB is automatically copied to the engine's native folder. The user doesn't need to do a separate copy step. This is a meaningful UX win — the file appears in the Unity / Unreal editor's Project window without intervention.

The engine copy is named `<name>.glb` (without the `_clean` suffix) — the engine doesn't care about internal naming and the cleaner filename is what'll show up in the editor.

`--no-engine-stage` opts out per-invocation; `"engine": "none"` in config opts out per-project.

### Cross-project sharing

Currently not supported. Ken noted this as a future possibility but said "most projects are in one git repo each, sharing is uncommon." When the need arises, the right solution is probably symlinks or a shared `~/3d-pipeline/library/` that projects reference by symlink. Don't build this until there's a clear use case — symlinks complicate migration scripts and manifest paths.

---

## 13 · The Claude Code skill

Lives at `~/.claude/skills/asset-pipeline/`. Two files: `SKILL.md` and `scripts/update_manifest.py`.

### SKILL.md role

SKILL.md is what Claude Code loads when the skill triggers. It's *opinionated documentation* aimed at Claude itself — describing when to use the skill, what flows exist, how to handle project context, what defaults to apply, and what to refuse.

Critical things SKILL.md tells Claude:

- **Don't try to detect projects yourself** — the wrappers do this; let them.
- **Tell the user where outputs land** before running, so they can object before files are created in the wrong place.
- **Refuse non-commercial models** for Ken's commercial projects (Grithkin, GripCraft) unless explicitly overridden.
- **Suggest `.asset-pipeline.json` creation** when the user repeats the same overrides multiple times.
- **Update the manifest after every generation** via `update_manifest.py`.
- **Ask about print size** before running `print.sh` — don't default silently to 50mm without confirmation.

### Why a skill, not a wrapper Claude calls?

See [section 17](#17-why-a-claude-code-skill-not-a-cli-claude-can-call).

### Skill triggers

The `description` field in SKILL.md frontmatter determines when Claude activates the skill. It includes triggers for:

- Direct asset-generation requests: "make a 3D X", "generate a 2D X", "convert this image to 3D"
- Print requests: "make me an STL", "print this", "Snapmaker"
- Tool mentions: "SF3D", "FLUX", "Z-Image", "TRELLIS"
- Engine-related: "import this into Unity", "put this in Unreal"

The skill is intentionally hungry — it activates broadly because the cost of activating when the user didn't mean to is small (Claude can decide not to use the wrappers), but the cost of *not* activating when the user wanted it is meaningful (Claude tries to do everything by hand and gets it wrong).

---

## 14 · The asset manifest

`asset_manifest.json` is a JSON index of every generated asset. Lives in `$ASSETS_ROOT/asset_manifest.json` — global workspace in global mode, project's `assets/` in project mode.

### Schema

```json
{
  "version": 1,
  "assets": [
    {
      "name": "treasure_chest",
      "concept_path": "concept/treasure_chest.png",
      "raw_path": "raw/treasure_chest_raw.glb",
      "clean_path": "clean/treasure_chest_clean.glb",
      "stl_path": "print/treasure_chest.stl",
      "stl_size_mm": 50,
      "engine_path": "Assets/Models/AI/treasure_chest.glb",
      "generator": "sf3d",
      "polycount": 3000,
      "category": "prop",
      "notes": "Wooden chest with iron bands",
      "created": "2026-05-18T20:13:42Z"
    }
  ]
}
```

### Updater: `update_manifest.py`

Lives in the skill, not the workspace. Called by Claude after each generation. Idempotent — re-running with the same `--name` updates the existing entry rather than duplicating. Optional fields (e.g., `stl_path` on a 2D-only asset) are omitted.

### Why it lives in the skill, not the workspace

The manifest updater is part of the AI driver layer, not the pipeline tools. The wrappers don't update the manifest themselves — they just write asset files. The skill makes the call. This separation lets the user run wrappers manually without polluting the manifest if they're just experimenting.

Downside: the skill needs to know the manifest path, which means the skill needs to know about project context. SKILL.md describes the manifest-path-resolution logic in plain prose so Claude can construct the right path.

---

## 15 · Why bash, not Python

The wrappers are written in bash. This is a deliberate choice. Three reasons.

**✅ Why bash wins**
- Bash is the lingua franca of CLI tools — every developer reads it
- Activating venvs is trivial (`source venv/bin/activate`) vs. Python's `subprocess.run` dance
- No "which Python version does this wrapper run with" question
- Chaining outputs across tools is idiomatic (`$(concept.sh ...)`)
- Bash heredocs let us embed Python snippets for JSON parsing inline
- The pipeline crosses Python venvs that have *different* Python versions and conflicting deps — orchestrating from outside any of them is cleaner

**⚠️ What we sacrifice**
- Type safety on args (we get strings, period)
- Sophisticated arg parsing (no argparse / click — we hand-roll case statements)
- Cross-platform portability (we're macOS-only anyway)
- Easy unit testing (bash is harder to test than Python)
- Helper libraries (no requests, no pathlib — we use coreutils)

The decisive factor: orchestrating across multiple isolated Python venvs is awkward from any single one of them. Bash sits outside all of them and activates each as needed.

### What about a Python "outer" wrapper?

Considered. The objection is that the outer wrapper would itself need a Python install with its own deps (yaml? toml? click?), creating a fifth Python environment for users to set up. The benefit is marginal — we don't have complex enough arg parsing to need argparse. Bash's `case` on long options is verbose but readable.

### What about Just / Make / Task?

Also considered. They'd add a tool dependency for users to install. For three wrappers that are mostly straight-line scripts, the indirection isn't worth it.

### When this would change

If the wrappers grew significantly more complex — say, parallel sub-tasks, progress tracking, retry logic, structured output — Python with click would start to win. We're well below that threshold today.

---

## 16 · Why one venv per tool

The pipeline maintains separate venvs for SF3D, TRELLIS.2, and mflux. Not one shared "asset pipeline" venv. Reasons:

### Dependency conflicts

SF3D pins `setuptools==69.5.1`, `numpy==1.26.4`, `gpytoolbox==0.3.3`, and a specific torch version. mflux is built on MLX and prefers more recent numpy. TRELLIS has its own constraints. Putting them in one venv hits version conflicts immediately.

### Failure isolation

If SF3D's install breaks (and it often does — see [section 20](#20-setup-failures-weve-already-hit)), it doesn't affect mflux. The user can have a working 2D generator while debugging the 3D side.

### Upgrade independence

Each tool ships releases on its own schedule. Upgrading SF3D shouldn't risk breaking the FLUX install. Independent venvs make per-tool upgrade safe.

### Cost

Three venvs ≈ 4-5 GB of disk for duplicated PyTorch installs. Negligible on a Mac with 4 TB SSD. Worth it for the isolation.

> **🧠 Rationale — Why not a single fat venv with extras_require?**
>
> Considered. The blocker is that some of these tools (notably SF3D) have unstable installs that need workarounds (gpytoolbox version bump, --no-build-isolation flag, cmake prerequisite). Asking users to run all of those during a single shared install is far more error-prone than three independent install steps. Plus, mflux uses MLX which depends on Apple's specific Python build — mixing it with vendored CUDA-flavor torch wheels gets weird fast.

---

## 17 · Why a Claude Code skill, not a CLI Claude can call

The pipeline could be exposed to Claude in two ways:

- **As tool calls** — Claude invokes `concept.sh` / `generate.sh` / `print.sh` directly via bash tool. No skill needed.
- **As a skill** — SKILL.md sits in `~/.claude/skills/` and provides Claude with structured instructions about *when* and *how* to use the pipeline.

We chose the skill approach.

### Why

- **The pipeline has opinions.** "Refuse FLUX dev for commercial projects." "Ask about print size before running print.sh." "Don't try to detect projects yourself — the wrappers do it." Without a skill, Claude has to derive these opinions from context every time. With a skill, they're encoded once and apply consistently.
- **The flows have implicit structure.** Text → 2D → 3D → STL is five distinct flows that share intermediates. A skill can describe them as a coherent set. Tool-call-only would force Claude to re-derive the flow structure each time.
- **The skill becomes documentation.** Even when not actively driving, SKILL.md is the canonical description of how to use the pipeline. The setup guide tells humans; SKILL.md tells AIs.
- **Triggers extend reach.** SKILL.md's description field tells Claude when to engage. Without it, Claude needs explicit "use the pipeline for this" prompts.

### The hybrid reality

Inside the skill, Claude still does tool calls — it runs the wrappers via bash. The skill provides structured guidance; the bash tool provides execution. Skill + tools is the right composition.

---

## 18 · Why mflux, not diffusers

HuggingFace's `diffusers` library is the standard for running Stable Diffusion-family models in Python. We use `mflux` instead. Reasons:

### MLX-native vs. MPS

diffusers runs on PyTorch with the MPS backend. MPS is Apple's PyTorch backend that delegates to Metal — but it's incomplete. Many ops fall back to CPU silently, dragging down performance. mflux uses Apple's MLX directly, which is purpose-built for Apple Silicon.

Concrete impact: FLUX schnell takes ~5-15s per image on mflux. On diffusers with MPS, it's 30-60s for the same image. The speed difference is the whole reason the workflow feels interactive.

### Quantization built-in

mflux ships with int4 / int8 quantization that just works (`-q 4` or `-q 8`). diffusers requires bitsandbytes which has spotty Mac support.

### Memory efficiency

mflux is engineered for unified memory. It releases weights aggressively between generation steps. diffusers tends to hold more state and can OOM on Mac with smaller RAM.

### Coverage

mflux supports FLUX schnell, FLUX dev, Z-Image Turbo, Qwen Image, and a growing list of models. The maintainer is responsive to new releases — Z-Image support landed within weeks of the model's release.

> **🔵 Context — What we lose**
>
> diffusers has more knobs (advanced schedulers, custom pipelines, attention mechanisms). mflux is opinionated about what it exposes. For our use case (text-to-image with optional LoRA), that's fine — the simpler API helps more than the missing knobs hurt.

---

## 19 · Why TRELLIS is optional

TRELLIS.2 is listed as "Step 04 (optional)" in the setup guide. Three reasons it's not default:

### License blocks commercial use

CC BY-NC 4.0. Can't ship TRELLIS-generated assets in Grithkin or GripCraft. For Ken's primary use case, it's blocked.

### Mac port is incomplete

The original TRELLIS uses nvdiffrast for texture baking. nvdiffrast has no Mac port. The Mac fork stubs it out, falling back to vertex colors. The result is sharper geometry but visibly worse surface appearance than SF3D's full PBR. For most game-asset uses, this is a meaningful step down.

### 15 GB+ of weights to download

SF3D ships ~2 GB. TRELLIS is closer to 15 GB. Including TRELLIS by default would significantly extend first-run setup time. Making it optional means users who don't need it don't pay the cost.

### When TRELLIS still earns its keep

- Personal / non-commercial art projects where geometry matters more than texture
- Organic shapes (creatures, characters) where TRELLIS's denser triangulation reads better
- Source meshes for further sculpting in Blender / ZBrush — when texture won't survive anyway

---

## 20 · Setup failures we've already hit

These are real failure modes encountered during Ken's setup. Each is now baked into the setup guide as either a prerequisite step or a troubleshooting card. Future AIs should know these are *not* hypothetical — they will happen again.

### PEP 668 — "externally-managed-environment"

> **🔴 Gotcha — Symptom**
>
> `pip3 install --user huggingface_hub` fails with "externally-managed-environment" error on modern macOS.

**Cause:** Homebrew's Python now enforces PEP 668, blocking system-wide pip installs.

**Fix:** Use `pipx install huggingface_hub` instead. After `brew install pipx && pipx ensurepath`, the user must **close and reopen Terminal** for the new PATH to take effect.

### Python 3.11 not found by Homebrew

> **🔴 Gotcha — Symptom**
>
> `python3.11 -m venv .venv` reports command not found, even after `brew install python@3.11`.

**Cause:** Homebrew installed Python 3.12, 3.13, or 3.14 instead of 3.11, or installed 3.11 as keg-only.

**Fix:** Check what's available with `ls /opt/homebrew/bin/python3*` and use whichever Python 3.10-3.12 is on PATH. SF3D works with all three. The setup guide is version-agnostic.

### SF3D fails: "No module named 'torch'" during texture_baker build

> **🔴 Gotcha — Symptom**
>
> `pip install -r requirements.txt` fails compiling `texture_baker` with ModuleNotFoundError: torch.

**Cause:** texture_baker's build script imports torch at compile time but doesn't declare torch as a build dependency. PEP 517 build isolation hides the venv's torch from the build subprocess.

**Fix:** Add `--no-build-isolation` to the pip command.

### gpytoolbox build fails: "CMake must be installed"

> **🔴 Gotcha — Symptom**
>
> Building wheel for gpytoolbox fails with CMake not found.

**Cause:** gpytoolbox uses CMake for its C++ extensions. CMake isn't a default Homebrew install.

**Fix:** `brew install cmake` before retrying pip install.

### gpytoolbox 0.2.0 sdist missing CMakeLists.txt

> **🔴 Gotcha — Symptom**
>
> Even with CMake installed, gpytoolbox 0.2.0 build fails with "no CMakeLists.txt" — the PyPI sdist is incomplete.

**Cause:** SF3D pins gpytoolbox 0.2.0, but that version's PyPI tarball is missing its C++ source files. Known upstream packaging bug.

**Fix:** Before running pip install, `sed -i '' 's/gpytoolbox==0.2.0/gpytoolbox==0.3.3/' requirements.txt` to bump to a version with prebuilt wheels. 0.3.3 is API-compatible with what SF3D needs.

### zsh: comment-line parse errors when pasting multi-line blocks

> **🔴 Gotcha — Symptom**
>
> Pasting a code block with `#` comments and brace expansions (`{a,b}`) into zsh produces "command not found: #" and "unknown file attribute" errors.

**Cause:** zsh's `INTERACTIVE_COMMENTS` is off by default, so `#` at the prompt is parsed as a command. And brace expansion mid-line-continuation confuses zsh.

**Fix:** `echo 'setopt INTERACTIVE_COMMENTS' >> ~/.zshrc && source ~/.zshrc`. The setup guide now recommends single-line forms for commands that need to be pasted directly.

> **🧠 Rationale — Pattern**
>
> These failures share a common theme: **modern macOS and Homebrew have gotten stricter about Python installs, and SF3D's build system has accumulated bit-rot**. The setup guide bakes every workaround into the linear instructions — users following the guide top-to-bottom shouldn't hit any of these. Users improvising will.

---

## 21 · Runtime failure modes

### Wrong project detected

User is in a nested git checkout inside a Unity project. The wrapper detects the outer Unity project but the user wanted assets to land in the nested directory. Solutions:

- Pass `--project /correct/path` explicitly
- Drop `.asset-pipeline.json` in the intended project root (closer match wins)
- Tell Claude "use the global workspace for this" to bypass detection

### Engine path collision

Auto-staging copies cleaned GLB to `Assets/Models/AI/<name>.glb`. If the user already has a hand-authored asset there with the same name, the copy overwrites it. There's no warning. **This is a known sharp edge.**

The intended mitigation: `auto_increment_collisions` in the config (which currently applies to intermediate filenames but not engine-staged copies). A future improvement would extend collision-checking to the engine path too.

### Out-of-memory during generation

On a 16 GB Mac, FLUX schnell q8 + Blender background process can push past RAM. Symptoms: macOS aggressively swaps, generation takes 5-10x longer than expected.

Mitigations: use q4 quantization, close Blender between runs, or accept the slowdown. The 128 GB target machine doesn't have this problem.

### SF3D texture-baker stalls

Rare but seen: SF3D's texture baking stage hangs indefinitely. Cause unknown — possibly a Metal kernel bug. Killing the process and re-running usually works.

### Mesh comes out flat / 1D

SF3D and TRELLIS both occasionally produce degenerate output — a flat plane or a thin sliver instead of a recognizable 3D shape. Causes:

- 2D input has too little 3D form information (pure front view, complex background)
- 2D input is a clipart-style image with hard edges and no gradients
- Subject is at an unusual scale relative to the frame

Fix: regenerate the 2D concept with the game-asset prompt suffix, ensure 3/4 view, clean background, even lighting. The default `concept.sh` suffix encodes these.

### STL won't slice in Snapmaker Orca

Symptoms: Orca reports "model is not manifold," refuses to slice, or produces a path with visible gaps. Cause: the 3D Print Toolbox repair pass didn't catch all non-manifold geometry.

Mitigations: try Orca's own "Repair Model" right-click action, or regenerate with a higher polycount (lower decimation = fewer manifold issues).

---

## 22 · Known limitations

Things the pipeline doesn't do, by current design. Knowing these prevents an AI from making promises it can't keep.

### Architectural limits

- **No cross-project asset sharing.** One project, one assets folder. Symlinks aren't built in.
- **No multi-image input.** Both SF3D and TRELLIS take a single 2D image. There's no way to feed multiple views.
- **No animation.** Static meshes only. No rigging, no skinning, no keyframes.
- **No texture editing.** Generated textures are use-as-is. No upscaling pass, no detail enhancement.
- **No "regenerate variation" of a 3D asset.** If the chest came out wrong, you regenerate from a new 2D concept. There's no img2img-equivalent for 3D.

### Hardware limits

- **Mac only.** No Linux, no Windows. PyTorch CUDA paths aren't supported.
- **Tested on M-series.** Intel Macs not supported (and would be too slow to be useful anyway).
- **Snapmaker U1 only for print sizing.** Other printers work fine for slicing the produced STLs but the 270mm build-volume check is U1-specific.

### Software limits

- **No web UI.** CLI + AI driver only.
- **No batch processing** beyond `-n <count>` on concept generation.
- **No undo.** Generated files are real files. Manifest tracks them, but reverting to a previous state requires manual git.
- **No remote execution.** Pipeline runs on the local machine; no way to offload to a different machine.
- **No incremental texture detail.** Texture resolution is set once per generation. Want higher detail? Regenerate from scratch.

### Print-quality limits

- **The print prep does manifold repair, not artistic enhancement.** If a model has thin filaments or impossible overhangs, the print prep won't fix them — it'll just make them manifold. The user has to design around print constraints in the 2D prompt.
- **Color is slicer-side.** Multi-color prints require manual painting in Snapmaker Orca. The pipeline doesn't auto-segment the mesh by color.

---

## 23 · How to help the user effectively

If you're an AI assistant tasked with helping Ken use, modify, or extend this pipeline, here's the operational guidance distilled from everything above.

### When generating an asset

1. **Don't try to detect projects yourself.** The wrappers do this. Just run them and let them report context.
2. **Announce where outputs will land** before generating. "I'll route this into your Grithkin project under `assets/concept/`." Gives the user a chance to object before files are written.
3. **Use Z-Image Turbo for 2D unless there's a specific reason for FLUX.** It's commercial-safe, fast, and the highest-leverage default.
4. **Use SF3D for 3D unless the user explicitly wants TRELLIS.** Same reasoning.
5. **Ask about print size** before running `print.sh`. Don't assume 50mm silently — it's a creative choice.
6. **Update the manifest** after every generation via `update_manifest.py`.

### When the user wants to modify the pipeline

1. **Read this document first.** Many "modifications" the user might request are actually already supported (config file, env vars, flags). Check before building.
2. **Preserve the commercial-safe default path.** Adding a new 3D model with a permissive license? Great. Adding one with a non-commercial restriction? It can be supported but should be opt-in, not default.
3. **Don't break the wrapper interfaces.** Existing flags and behaviors are relied upon by both Ken's manual use and Claude's automated use. Additive changes are safe; subtractive changes break workflows.
4. **Test in both global and project modes.** Any change to the wrappers should work in both. The library handles routing; the wrapper invokes it once and uses the resolved paths.
5. **Keep failure modes explicit.** If a new feature can fail, document the failure in the troubleshooting cards in the setup guide.

### When the user is debugging

1. **Check the wrapper's context header first.** The first lines of stdout tell you which mode the wrapper detected and where it'll write. Half of "wrong output location" issues are project-detection surprises.
2. **Validate `.asset-pipeline.json` with `python3 -m json.tool`** — malformed config silently falls back to defaults, which looks like "config is ignored."
3. **Check the manifest.** The manifest knows what was generated, with what model, at what size. Use it to retrace history.
4. **Don't suggest reinstalling everything.** The setup is fragile to recreate (see [section 20](#20-setup-failures-weve-already-hit)). Diagnose surgically.
5. **For SF3D weirdness, regenerate the 2D first.** Most 3D issues trace back to a low-quality 2D input.

### When the user is exploring

1. **Generate inside a temporary directory or /tmp** for experiments — keeps the project's assets folder clean.
2. **The global workspace is your friend for one-offs.** `cd ~` + run wrappers = falls back to global.
3. **Use `-n <count>` for cheap variations.** Z-Image at 8 steps is fast; trying 4 variations costs about a minute.

---

## 24 · Extension points

Places the pipeline is designed to be extended cleanly. If Ken wants to add functionality, here's where it should slot in.

### Adding a new 2D model

1. Confirm it's supported by mflux (or accept that you'll bypass mflux and have a separate wrapper path)
2. Add a case to `concept.sh`'s model validation and dispatch
3. Add the model to the SKILL.md description for licensing context
4. Document in the setup guide's Reference R1 (Model selection)
5. Pin its license clearly — commercial-safe goes to default tier; non-commercial gets opt-in tier

### Adding a new 3D model

1. Install its venv at `~/3d-pipeline/<tool-name>/.venv`
2. Add a case to `generate.sh`'s generator dispatch
3. If the tool has Mac compatibility issues, document them in section 19's pattern
4. Update SKILL.md to know when to choose it over SF3D / TRELLIS

### Adding a new config field

1. Add it to `_pipeline_lib.sh`'s schema (read via `json_get`)
2. Wire it through `resolve_project_context` if it affects routing
3. Wire it through `config_default` if it's a default override
4. Document in setup guide Reference R3
5. Remember: validation is permissive — typos silently fail. Mention the field name verbatim in docs.

### Adding a new engine target (e.g., Godot)

1. Add detection function to `_pipeline_lib.sh` (`is_godot_project` — check for `project.godot`)
2. Add to the detection cascade in `resolve_project_context`
3. Set a default `ENGINE_PATH` for the new engine type
4. Test that `generate.sh`'s engine staging works without changes (it should — it's engine-agnostic given a path)

### Adding a new output type (e.g., turntable video)

1. Create a new wrapper `turntable.sh` following the existing pattern
2. Source `_pipeline_lib.sh`; respect project detection
3. Add a `turntable/` subdirectory in `resolve_project_context`'s mkdir call
4. Add a flow to SKILL.md ("Flow 6: Clean GLB → turntable video")
5. Update `update_manifest.py` if turntable_path should be tracked

### What not to extend without thinking carefully

- **The detection cascade order.** Changing priority can break existing users' setups.
- **The default model selections.** They're chosen for commercial safety. Don't change defaults to non-commercial models even if quality is "better."
- **The wrapper CLI interface.** Breaking changes require migration paths and SKILL.md updates.
- **The manifest schema.** Adding fields is fine. Removing or renaming requires migration logic.

---

> ## 🎯 North star
>
> The pipeline serves a single user who works through an AI driver. Every extension should make that workflow more capable without making it more brittle. When in doubt, optimize for "the AI doesn't have to think about it" rather than "the AI has more options."
