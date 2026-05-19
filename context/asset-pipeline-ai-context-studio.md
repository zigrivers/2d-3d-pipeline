# Asset Pipeline · AI Context Document · Studio tier

*A technical context document for AI assistants helping Ken with his local 2D/3D/print asset generation pipeline, specifically when the active machine is one of the M3 Ultra Mac Studios.*

---

> **For AI assistants**
>
> This is the *delta* document for the studio tier. The full pipeline architecture (project detection, wrappers, manifest, Claude Code skill, decisions about bash vs Python, one-venv-per-tool, etc.) lives in [`asset-pipeline-ai-context.md`](asset-pipeline-ai-context.md) and is unchanged on the studios. Read both — laptop first for the bulk of the system, then this file for what only matters when the active tier is `studio`.

---

## Table of contents

**Context**
- [00 · Audience & purpose](#00-audience-purpose)
- [01 · Hardware tier: studio](#01-hardware-tier-studio)
- [02 · How studio differs from laptop](#02-how-studio-differs-from-laptop)

**Stack**
- [03 · Memory budget at 512 GB](#03-memory-budget-at-512-gb)
- [04 · License buckets at studio scale](#04-license-buckets-at-studio-scale)

**Architecture**
- [05 · The two-machine queue](#05-the-two-machine-queue)
- [06 · Shared storage and rsync](#06-shared-storage-and-rsync)
- [07 · Full-suite bake-offs](#07-full-suite-bake-offs)

**Rough edges**
- [08 · Studio-specific failure modes](#08-studio-specific-failure-modes)

**Working with this**
- [09 · How to help the user effectively](#09-how-to-help-the-user-effectively)
- [10 · Cross-references](#10-cross-references)

---

## 00 · Audience & purpose

This document supplements the laptop-tier AI context with the studio-tier
deltas. The pipeline architecture, wrappers, project detection, manifest
schema, and the Claude Code skill are all **the same** on both tiers. The
differences are bounded:

- The `.config` setting (`hardware_tier=studio`).
- The default recommendations (which opt-in lanes become realistic).
- The queue, which only makes sense with two machines.
- The benchmark suite size you can sensibly run.
- Some operational concerns (shared storage, rsync).

If you find yourself wanting to re-derive the pipeline's decisions, read the
laptop AI context first. Don't duplicate that thinking here.

---

## 01 · Hardware tier: studio

Two Apple M3 Ultra Mac Studios. Each:

- 512 GB unified memory.
- 8 TB local NVMe storage.
- Apple Silicon (mflux/MLX-compatible).

The user identifies the active tier by adding `hardware_tier = studio` to
`~/3d-pipeline/.config` on each Studio. Wrappers and the Claude Code skill
read that file; they **never** sniff hostname. Cloning or renaming a Studio
should not silently change behaviour.

> **🧠 Rationale — Why an explicit config**
>
> Hostnames change. macOS image cloning, network rename, "we got a third Studio for the office" — any of these can silently flip behaviour if the system guesses. A single key=value file is trivially editable by the user and easy to audit.

---

## 02 · How studio differs from laptop

| Concern                      | Laptop                                      | Studio                                            |
| ---------------------------- | ------------------------------------------- | ------------------------------------------------- |
| Default 2D model             | Z-Image Turbo                                | Z-Image Turbo                                      |
| Default 3D generator         | SF3D                                         | SF3D                                               |
| Opt-in `non_commercial`      | Available but slow; rarely recommended       | Comfortable; still requires explicit user accept   |
| `flux-dev`, `trellis`        | Possible; memory-tight                       | Trivial fit; **still `non_commercial`**            |
| `spar3d`                     | Possible; memory-tight                       | Comfortable; benchmark before adopting             |
| Benchmark suite              | `quick` (3 prompts) is reasonable            | `default` (14 prompts) is the realistic choice     |
| Two-machine queue            | Documented as not applicable                 | Primary motivation                                 |
| Storage budget               | Constrained                                  | Liberal (8 TB local)                                |

> **🟢 Decision — Defaults stay the same across tiers**
>
> The user prefers commercial-safe assets for Grithkin and GripCraft. The studio's headroom doesn't change the licence on FLUX dev or TRELLIS — those remain `non_commercial`. Memory permits using them; the licence still constrains them. Do not silently promote them to defaults at the studio tier just because they "fit."

---

## 03 · Memory budget at 512 GB

Wrappers run sequentially — they activate a tool's venv, run, deactivate.
So memory pressure is still single-model, not concurrent. With 512 GB
available, none of the supported models come close:

| Tool / stage                    | Approx. peak | Headroom (single Studio) |
| ------------------------------- | ------------ | ------------------------ |
| `mflux` + Z-Image Turbo (q8)    | ~10 GB        | 50×                       |
| `mflux` + FLUX schnell (q8)     | ~14 GB        | 35×                       |
| `mflux` + FLUX dev (q8)         | ~16 GB        | 30×                       |
| SF3D inference                  | ~6 GB         | 80×                       |
| SPAR3D inference                | ~8–10 GB      | 50×                       |
| TRELLIS.2 inference             | ~10–14 GB     | 35×                       |
| Blender headless cleanup        | ~2 GB         | 250×                      |

> **🔵 Context — Why this matters less than it looks**
>
> Memory ceilings are no longer the limiting factor for model selection at the studio tier; latency and licence are. A model that takes 60 s on a Studio is still a 60-second wait if you need to chain 14 prompts × 2 generators. The queue exists partly to keep that wait usable.

---

## 04 · License buckets at studio scale

The bucket names are exact (used in code, JSON, manifest, docs):

- `commercial_safe`: z-image-turbo, flux-schnell, qwen-image
- `commercial_threshold`: sf3d, spar3d
- `non_commercial`: flux-dev, trellis
- `source_available_restricted`: reserved
- `unclear_risky` / `unknown`: LoRAs, anything untagged

> **🔴 Gotcha — Studio headroom does not change licensing**
>
> The whole reason the Studios exist is to make the pipeline faster, not to relax licensing. If a wrapper emits `[license] WARNING: flux-dev is non-commercial`, relay that warning. Do not interpret studio capacity as licence approval.

---

## 05 · The two-machine queue

`scripts/queue_submit.py` writes job JSON to
`<assets_root>/queue/pending/<uuid>.json`. `scripts/queue_worker.py` claims
pending jobs atomically via `os.rename()` (POSIX rename is atomic on the
same filesystem, including NFS), runs the appropriate wrapper under
`--json`, and finalises the job to `done/` or `failed/`.

Layout:

```
<assets_root>/queue/
  pending/     # awaiting claim
  running/     # claimed; in flight
  done/        # successful, with wrapper JSON inlined
  failed/      # non-zero exit or malformed JSON
```

The worker:

- Sorts pending by (`priority`, mtime). Lower priority value runs earlier.
- Inherits env so `PIPELINE_CONFIG_PATH`, `SPAR3D_DIR`, etc. flow through.
- Honours `SIGINT` / `SIGTERM`: finishes the current job then exits cleanly.
- Has `--once`, `--max-jobs N`, `--dry-run`, and `--json` modes.

> **🧠 Rationale — Why file-based and not SQLite**
>
> SQLite would buy us indexed queries and transactions, but introduce a dependency and a schema-migration concern. The queue is experimental scaffolding; the user wants to observe state with `ls` and `cat` and recover with `mv`. File-based wins on debuggability. If/when the queue graduates from experimental, SQLite is a reasonable upgrade path.

Limitations the docs are explicit about:

- No retry policy. Failed jobs sit in `failed/` until manually moved.
- Single filesystem only. Rsync-synced folders need a write-direction
  convention or a lock file to avoid double-claim.
- No supervisor. For continuous operation, wrap the worker in a launchd
  plist or `caffeinate` loop.

---

## 06 · Shared storage and rsync

Three sensible options. The wrappers and queue tolerate any of them as
long as the path is identical on both Studios:

1. **SMB share.** Host Studio shares its `~/3d-pipeline/workspace/`. The
   guest mounts at the same path. Simple, single-point-of-failure on the
   host. Atomic rename holds.
2. **Project rsync.** Both Studios run independent pipelines. The active
   project (e.g. `~/games/grithkin/`) is rsync'd between them. Good for
   solo work; needs care if you also use the queue.
3. **NAS / NFS.** Both Studios mount the same path from a NAS. Atomic
   rename holds on NFS. Most production-friendly, requires the NAS.

Model caches (HuggingFace, mflux, SF3D weights) can live on the shared
store (single download, ~50 GB savings) or be duplicated locally on each
Studio (faster reads, 8 TB local makes the duplication trivial).

> **🔵 Context — Why "same path" matters**
>
> The wrappers record absolute paths in `--json` and the manifest. If the same asset appears at different absolute paths on each Studio, the manifest is confusing and the queue's `input` field is unreliable. Pick one path, mount or symlink to it on both machines.

---

## 07 · Full-suite bake-offs

`benchmark.sh --suite default` is the primary tool. At studio scale, 14
prompts × {sf3d, spar3d} × 1 concept = 42 runs is a coffee-break job, not
an overnight job. The results structure (`benchmark_results.json`) records:

- Suite, hardware_tier, machine, project context.
- One entry per run with status, exit code, duration, paths, file sizes,
  license_bucket.
- A manual scoring scaffold (`prompt_match`, `front_accuracy`, ...)
  initialised to `null` / `"not_tested"`.

The harness deliberately does not auto-score. Subjective metrics
(topology, backside plausibility, UV quality) require a human or a
specialised tool that doesn't yet exist in the pipeline. The structure
exists so a later review pass (often via Claude Code) can fill it in
systematically.

For parallel bake-offs across both Studios:

1. Submit one job per (prompt, generator, model_2d) tuple to the queue.
2. Run a worker on each Studio.
3. Aggregate results from `queue/done/` after both workers idle.

---

## 08 · Studio-specific failure modes

> **🔴 Gotcha — Queue jobs stuck in `running/`**
>
> If a worker crashes or is killed with `kill -9`, the job file sits in `running/` forever. The pipeline has no health-check yet. Manual recovery: identify the stuck job's age, decide if it's actually stuck (vs slow), and `mv queue/running/X.json queue/pending/X.json` to resubmit.

> **🔴 Gotcha — Two workers double-claim on rsync**
>
> If both Studios independently rsync `queue/pending/` in both directions, two workers can see the same job and rename succeeds on each because they're operating on local copies. The shared-storage options above avoid this; the rsync option requires single-direction sync of `queue/pending/`.

> **🔴 Gotcha — Studio runs FLUX dev because it can**
>
> The wrappers warn but don't block. If the user picks `flux-dev` for a commercial project on the studio tier, the warning still fires; the output is still `non_commercial`. Don't let the studio's comfort with the model imply licence approval. Confirm with the user whenever a `non_commercial` model is selected.

> **🔴 Gotcha — Model cache divergence between Studios**
>
> Two Studios with independent caches will sometimes diverge on minor model version updates (HuggingFace re-uploads, etc.). Bake-off comparisons can be confused by this. Either use a shared cache, or pin model versions in each environment and re-pin in sync.

---

## 09 · How to help the user effectively

When the active tier is `studio`, prefer:

- The `default` suite over `quick` for benchmarks.
- SPAR3D as a realistic comparison candidate (always with benchmark evidence).
- The queue for batches of >5 generations.
- Full studio-doc references (`docs/asset-pipeline-guide-studio.html`,
  `docs/UPGRADES-studio.md`) when pointing the user at install or upgrade docs.

Avoid:

- Suggesting `flux-dev` or `trellis` as a default just because they fit.
- Skipping the licence-bucket call-out when recommending anything outside
  the default lane.
- Recommending the queue for single-asset work — it's overhead for nothing.

Always:

- Mention `hardware_tier=studio` is the only manual config required on each
  new Studio.
- Relay non-commercial warnings.
- Ask for print size on print.sh runs unless already specified.

---

## 10 · Cross-references

- [`asset-pipeline-ai-context.md`](asset-pipeline-ai-context.md) — the full
  pipeline architecture, decisions, and rationale. Unchanged for studio.
- [`docs/asset-pipeline-guide-studio.html`](../docs/asset-pipeline-guide-studio.html)
  — user-facing install guide for the studio tier.
- [`docs/UPGRADES-studio.md`](../docs/UPGRADES-studio.md) — the v0.2
  upgrade summary for the studio tier.
- [`~/.claude/skills/asset-pipeline/SKILL.md`](../skill/SKILL.md) — the
  Claude Code skill, tier-aware.
- The shared `~/3d-pipeline/workspace/` scripts — same on both tiers; the
  studio guide installs them identically to the laptop guide.

Last updated: 2026-05-19
