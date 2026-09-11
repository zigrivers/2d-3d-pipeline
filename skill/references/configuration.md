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

