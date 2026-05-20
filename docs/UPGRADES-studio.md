# v0.2 — Studio-tier changes

The v0.2 release adds the new wrapper features documented in
[`UPGRADES-laptop.md`](UPGRADES-laptop.md), **plus** the studio-only pieces
below. Read both files for the full picture; the laptop file covers
`--json`, license buckets, manifest v3, all-axis Snapmaker validation, safer
engine staging, `texture.sh`, and the SPAR3D lane.

This file focuses on what only matters at the studio tier: the
`hardware_tier=studio` config, the headroom narrative for 512&nbsp;GB unified
memory, full-suite bake-offs, and the two-machine job queue.

---

## Declare the studio tier

Every Mac Studio needs `~/3d-pipeline/.config` with:

```
hardware_tier = studio
```

This drives:

- `hardware_tier=studio` in every `--json` result.
- `generation.hardware_tier=studio` in manifest v3 entries.
- The Claude Code skill recommending the full default benchmark suite and
  the queue when relevant.
- `model_bakeoff.py` recording the right tier in
  `benchmarks/<timestamp>/benchmark_results.json` so studio-vs-laptop numbers
  stay comparable.

The wrappers do **not** sniff hostname — renaming a Studio would silently
change behaviour if they did. The config file is the only source of truth.

## Headroom narrative — what 512 GB unified memory unlocks

Memory pressure on the M3 Ultra Studios is dramatically lower than on the
laptop tier. None of the inference paths run concurrently in the current
wrappers, so it's still single-model memory that matters — but everything
fits with massive headroom:

| Model / stage                       | Approx. peak memory  | Comfortable on studio? |
| ----------------------------------- | -------------------- | ---------------------- |
| `mflux` + Z-Image Turbo (q8)        | ~10&nbsp;GB          | Trivially.             |
| `mflux` + FLUX schnell (q8)         | ~14&nbsp;GB          | Trivially.             |
| `mflux` + FLUX dev (q8, **non_commercial**) | ~16&nbsp;GB  | Trivially. Licence still matters. |
| SF3D inference                      | ~6&nbsp;GB           | Trivially.             |
| SPAR3D inference                    | ~8–10&nbsp;GB        | Trivially.             |
| TRELLIS.2 inference (**non_commercial** today) | ~10–14&nbsp;GB | Trivially. Licence still matters. |
| Blender headless cleanup            | ~2&nbsp;GB           | Trivially.             |

The lanes that become realistic at the studio tier are **lanes that were
already supported** — they just don't squeeze memory the way they do on a
laptop:

- **FLUX dev evaluation.** Slow on a laptop, comfortable on a Studio. Licence
  bucket `non_commercial` — output not usable for Grithkin / GripCraft.
- **TRELLIS.2.** Heavier than SF3D, viable at studio scale, also `non_commercial`.
- **SPAR3D.** Experimental but `commercial_threshold` — the most interesting
  opt-in lane for studio work. Still not the default; benchmark first.

Defaults remain commercial-safe: **Z-Image Turbo → SF3D → Blender**. Don't
adopt FLUX dev or TRELLIS as a default just because the memory fits.

---

## Two-machine queue (experimental)

A file-based job queue you can run across both Studios. Studio-tier only —
the queue works on a single laptop in principle but has no practical value
without two workers.

### Simplest deployment

1. Both Studios have the pipeline installed identically. Both have their own
   model caches (or can download independently).
2. Designate one Studio's `~/3d-pipeline/workspace/` as the shared store, or
   work inside a project (`~/games/grithkin/assets/`).
3. Make the shared store visible to both Studios:
   - **SMB share** of the host Studio's `workspace/` directory, mounted on the
     second Studio at the same path. POSIX `rename()` is atomic on SMB, which
     is what the worker relies on for claiming.
   - **OR** rsync the project tree both directions, but keep the
     `queue/pending/` directory under a single-writer policy or you'll get
     double-claims.
4. Run a worker on each Studio:

   ```bash
   python3 ~/3d-pipeline/workspace/queue_worker.py \
       --assets-root /shared/path/workspace \
       --script-dir ~/3d-pipeline/workspace
   ```

5. Submit jobs from any machine:

   ```bash
   python3 ~/3d-pipeline/workspace/queue_submit.py \
       --assets-root /shared/path/workspace \
       --stage image_to_3d \
       --input /shared/path/workspace/concept/chest.png \
       --generator sf3d \
       --polycount 3000 \
       --json
   ```

### Queue layout

```
<assets_root>/queue/
  pending/        # submitted, awaiting claim
  running/        # claimed atomically (mv from pending)
  done/           # success — file contains the wrapper's --json result
  failed/         # non-zero exit / malformed JSON / unknown stage
```

Each job is a single JSON file. `cat queue/done/<uuid>.json` is the entire
forensic record.

### Operational rules

- One worker per Studio is the recommended default.
- Workers honour `SIGINT` / `SIGTERM`: they finish the current job and exit
  cleanly; no half-claimed jobs.
- Failed jobs stay in `failed/` until you move them back. The queue
  intentionally has no automated retry; the only recovery is the
  reclaim flag (below) for jobs that got stuck in `running/`.
- For long-running deployments, wrap the worker in a launchd plist or a
  small supervisor script. The scaffold doesn't ship one.

### Stuck-job reclaim

If a worker is killed with `kill -9`, OS-crashes, or otherwise dies
mid-job, the job file sits in `running/` indefinitely. Two flags on the
worker make recovery cheap without a real supervisor:

```bash
python3 ~/3d-pipeline/workspace/queue_worker.py \
    --assets-root /shared/path/workspace \
    --script-dir ~/3d-pipeline/workspace \
    --reclaim-stuck-after 30 \
    --max-claims 3
```

- `--reclaim-stuck-after MINUTES` — at the start of every poll cycle,
  the worker scans `running/` for jobs whose mtime is older than
  MINUTES. Each gets its `claim_count` incremented and is moved back
  to `pending/` (resetting `started` and `machine` so the next worker
  picks it up fresh). 0 (the default) disables reclaim entirely.
- `--max-claims N` (default 3) — jobs that have been claimed this
  many times move to `failed/` instead of `pending/`, with a
  structured error describing the reclaim history.

Pick MINUTES based on your longest expected job. Typical mflux + SF3D +
Blender end-to-end is well under 5 minutes on a Studio, so
`--reclaim-stuck-after 30` is a conservative default that won't
prematurely re-claim a job that's just slow.

This is intentionally the **cheap** version of retry: no exponential
backoff, no per-stage policy, no dead-letter queue. Enough to recover
from worker crashes; not enough to call production-grade.

---

## Full-suite bake-offs

`benchmark.sh --suite default` runs the full 14-prompt suite. On the studio
tier this is a realistic workload:

```bash
~/3d-pipeline/workspace/benchmark.sh \
    --suite default \
    --generators sf3d,spar3d \
    --models-2d z-image-turbo,flux-schnell \
    --json
```

Results land in `<assets_root>/benchmarks/<YYYYMMDD-HHMMSS>/benchmark_results.json`.
Every row records `hardware_tier=studio` and `machine`, so a multi-machine
run produces a per-machine summary you can slice.

For really expensive comparisons, split the work across both Studios via the
queue: submit one job per (prompt, generator) combination and let two
workers chew through them.

Manual scoring fields (`prompt_match`, `front_accuracy`, `topology`,
`unity_import`, `print_prep`, etc.) are scaffolded as `null` /
`"not_tested"`. After a bake-off, ask Claude Code to walk you through them:

> "Open the latest benchmark and help me score the prop class. Z-Image Turbo
> concepts compared to FLUX schnell, both feeding SF3D."

---

## Shared storage / rsync recommendations

For a two-Studio setup you have three sensible options for sharing assets:

1. **One Studio is the host.** Share `~/3d-pipeline/workspace/` via SMB.
   The other Studio mounts at the same path. Simple, low-friction, works
   for the queue. Single point of failure: if the host is offline, the
   guest can't reach assets.

2. **Project-scoped sync.** Both Studios have local pipelines. The active
   project (e.g. `~/games/grithkin/`) is rsync'd between them on demand.
   Good for parallel solo work; needs a sync convention before using the
   queue (run sync only one direction, or coordinate `queue/pending/`).

3. **Network-attached share.** Both Studios mount a NAS at the same path.
   Atomic-rename safety holds on NFS. Most production-friendly; needs the
   NAS.

Model caches (HuggingFace, mflux, SF3D weights) can either live on the
shared store (single download, both Studios use it) or be downloaded
independently on each Studio (faster local reads, ~50&nbsp;GB-ish duplicate).
With 8&nbsp;TB local storage each, duplication is fine.

---

## What's deliberately unchanged (studio tier)

- 2D default: **Z-Image Turbo** (commercial_safe). The 512&nbsp;GB headroom
  doesn't promote FLUX dev to default — licence still matters.
- 3D default: **SF3D**. SPAR3D and TRELLIS.2 stay opt-in.
- Wrappers and the Claude Code skill are the same on both tiers — only the
  defaults that drive recommendations differ.

## Warnings worth repeating

- **`flux-dev` and `trellis` are `non_commercial`.** Don't let the studio
  headroom seduce you into making them defaults. The licence bucket is the
  reason, not the memory budget.
- **Queue is experimental.** Use for batch work, not for production
  pipelines. No retry policy ships.
- **`--allow-oversize` is for when you've decided to print in pieces.** Not
  a default to enable casually.

## What's coming next (v0.3 prep)

### `pipeline-tools-env` venv (optional, installable now)

v0.3 adds quality-check scripts (watertight + scale, texture quality,
input quality, background removal, CLIP scoring, pipeline doctor) that
share a single Python environment at `~/3d-pipeline/pipeline-tools-env/`.

The setup guide ships a new optional step (section 10) for installing
this venv. The venv is **unused** by v0.2 — nothing changes about how
your current pipeline runs. On studio tier you have the disk headroom to
install it preemptively; the v0.3 features will then be ready as soon as
they land.

Packages installed:

```
trimesh numpy scipy Pillow rembg[cpu] open_clip_torch torch tqdm requests
```

Disk impact: ~6 GB once populated. Caches at `~/3d-pipeline/models/rembg/`
(env: `U2NET_HOME`) and `~/3d-pipeline/models/clip/`
(env: `OPEN_CLIP_CACHE_DIR`). The pipeline doctor (item 10, ships in v0.3.0)
will eventually manage these caches and additional heavy models
(Hunyuan3D-Paint ~5 GB, ComfyUI stack ~10 GB) for the items beyond v0.3.0.

If a wheel fails to install: `pip install --upgrade pip setuptools wheel`
first, then retry. `torch` on Apple Silicon is the most common failure;
make sure you're on Python 3.10–3.12.

### Multi-view 2D generation (optional, for the multi-view backend benchmark)

A second optional step inside section 10 now adds `diffusers`,
`transformers`, and `accelerate` on top of `pipeline-tools-env`.
These unlock multi-view-aware 2D generators — models like Zero123++
(`sudo-ai/zero123plus-v1.2`) that take **one** image of a subject and
produce **N consistent views** of the same subject at canonical angles.

You only need them if you're going to build or re-run the multi-view
backend benchmark at `tests/multiview-bench/`. The benchmark uses
Zero123++ in its "Option B" path to test the full production chain
(`one concept image → multi-view 2D model → 3D backend`) rather than
just the 3D backend in isolation.

Studio tier has the disk headroom to install it preemptively even if
benchmarking isn't on your near-term plan. Disk impact: ~1.5 GB of
packages + ~3 GB of Zero123++ weights on first benchmark run.

Once a multi-view 3D backend is chosen (P3.1b in
`docs/improvement-plan.md`), the same install also unlocks a future
"auto multi-view from single concept" input mode for `generate.sh`.

Last updated: 2026-05-20
