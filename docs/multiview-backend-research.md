# Multi-view backend research

**Status:** PARTIAL DATA — evidence-backed, reduced scope (see §0) ·
**P3.1b / item 22 — recommendation deliverable**

This doc closes P3.1b in [`docs/improvement-plan.md`](improvement-plan.md)
and item 22 in
[`docs/spec-generation-refresh-2026.md`](spec-generation-refresh-2026.md).
The original P3.1's candidate slate (TRELLIS multi-view, InstantMesh,
OpenLRM) is dead on this hardware/license combination — item 22
replaces it. See §2 for the corrected candidate table (two of the
three original entries were **mislabeled in this repo's own code** —
corrected here, see §2 notes).

## 0. Scope of this round (2026-08, item 22)

The full formal methodology in §1 (3 subjects × 2 input pipelines ×
3 runs, with curated `ground_truth.glb` sources) requires source GLBs
that were never provided — `tests/multiview-bench/sources/` is still
empty; item 12 Phase 1's dataset-curation step is a real, separate,
unscoped prerequisite, not something to fabricate placeholder data
for. Running the full harness this round would mean inventing "source"
assets and back-filling plausible-looking scores, which is worse than
being honest about the gap.

Instead, this round ships:

- **§2**: corrected candidate table + citations (real work, no
  generation needed) — includes fixing two mislabeled license
  buckets found while researching this doc (see notes).
- **§3**: a real, reduced-scope (n=1 subject, no synthetic/mvgen
  delta, no repeated runs) end-to-end comparison, using the exact
  chain the R0.4/R0.5 spikes validated: MV-Adapter view generation →
  Hunyuan3D-2mv shape reconstruction, versus TRELLIS.2 single-image
  (item 15) on the identical source image. Real timings, real mesh
  stats, real mesh-judge (item 18) scores — just not the full 3×2×3
  rubric-scored grid.
- **§6 recommendation**: based on this reduced-scope evidence plus
  the R0.4/R0.5 spike findings, not a formal 6.5/10 rubric pass —
  **PR 10 (wiring `multiview.sh`) is deferred**, per item 22's own
  conditional ("only if a backend clears the 6.5/10 rubric"). The
  full formal benchmark (§1) is the followup that would unblock it —
  tracked in §7.

## 1. Full methodology (deferred — not run this round; kept for when §0's prerequisite lands)

Per [`docs/improvement-spec.md`](improvement-spec.md) item 12 Phase 1:

- 3 subjects (character / hard-surface / organic), 4 calibrated views
  each at 1024×1024 PNG, plus a ground_truth.glb per subject
- Two input pipelines per logical subject (P3.1a.1):
  - **synthetic** (Option C): rendered from the source GLB
  - **mvgen** (Option B): one rendered concept → Zero123++ → 6 views
- 3 runs per (backend × subject × pipeline) for variance
- Scoring rubric in
  [`tests/multiview-bench/scoring_rubric.json`](../tests/multiview-bench/scoring_rubric.json)
  — six weighted dimensions, pass threshold 6.5 / 10

## 2. Candidate backends (item 22 slate)

| Backend | Role | License bucket | Status |
|---|---|---|---|
| TRELLIS.2 single-image | Baseline ("is multi-view even worth it") | `commercial_safe` | Already shipped (item 15/R1.4) — the comparison point, not a multi-view backend itself |
| `edit.sh --angle` (Multiple-Angles LoRA) | Commercial-safe multi-angle-view wildcard | `commercial_safe` | Already shipped (item 21/R2.2) — but LoRA currently applies zero weight under mflux 0.18.1 (known upstream gap, see R2.2), so it is not yet a working view-generation source |
| MV-Adapter (view generation) | Feeds a multi-view consumer | `commercial_safe` | R0.4 spike PASS — real packaging fix required (see §2 notes) |
| Hunyuan3D-2mv (multi-view → shape) | Multi-view consumer | `commercial_threshold` | R0.5 spike PASS — real one-line MPS fix required (see §2 notes) |
| Zero123++ | View generation, **research-comparison only** | `non_commercial` | Never wired as a shipped lane — weights CC-BY-NC 4.0 |
| SPAR3D | Already-wired alternate single-image generator | Official experimental MPS support | Stays in slate; not this doc's focus |
| ~~InstantMesh~~ | ~~Multi-view → shape~~ | ~~`unclear_risky`~~ | **DISQUALIFIED** — hard CUDA≥12.1 + `nvdiffrast` requirement, no MPS path at all (adapter kept, marked DQ, not deleted — `tools/multiview_backends/instantmesh.py`) |
| ~~OpenLRM~~ | ~~Multi-view → shape~~ | ~~`commercial_safe`~~ → **`non_commercial`** | **DISQUALIFIED** — weights CC-BY-NC 4.0, research-only (adapter kept, marked DQ — `tools/multiview_backends/openlrm.py`) |

**License corrections found while researching this doc (both fixed
in this PR):**

- `tools/multiview_backends/openlrm.py` claimed "OpenLRM is Apache
  2.0 — `commercial_safe`. The only fully commercial-safe path in the
  benchmark." **This was wrong** — only the *code* is Apache 2.0; the
  *weights* are CC-BY-NC 4.0, research-only, per
  [OpenLRM's own model_card.md](https://github.com/3DTopia/OpenLRM/blob/main/model_card.md),
  quoted verbatim: "The model weights are released under the Creative
  Commons Attribution-NonCommercial 4.0 International License. They
  are provided for research purposes only, and CANNOT be used
  commercially." Corrected to `non_commercial`.
- `tools/multiview_2d_adapters/zero123_plus_plus.py` carried an
  unverified placeholder (`commercial_threshold`, its own comment
  admitted "verify the current text upstream" — never done). Verified
  directly: [SUDO-AI-3D/zero123plus](https://github.com/SUDO-AI-3D/zero123plus)'s
  repo `LICENSE` file is Apache 2.0 (code only); its README states
  "the code is released under Apache 2.0 and the model weights are
  released under CC-BY-NC 4.0." Corrected to `non_commercial`.

**InstantMesh citation** (unchanged from item 22's own text, verified
against the [InstantMesh README](https://github.com/TencentARC/InstantMesh)):
hard CUDA≥12.1 + `nvdiffrast` requirement, no Mac wheel exists.
Contrast with R0.4's MV-Adapter finding below — that was a packaging
mistake (unrelated CUDA-only code eagerly imported alongside a
portable path), not a load-bearing algorithmic CUDA dependency like
InstantMesh's.

## 3. Reduced-scope real comparison (this round, n=1 subject)

Real chain, real timings, run fresh on this Studio 2026-08-12. Source
image: the MV-Adapter repo's own bundled demo image (a striped tabby
cat, sitting upright, 3/4 front view) — reused from R0.4/R0.5 for
continuity with those spikes' already-verified evidence.

**Chain A — MV-Adapter (view gen) → Hunyuan3D-2mv (multi-view → shape):**

| Step | Duration | Notes |
|---|---|---|
| MV-Adapter: 6 views, 30 steps, 768×768 | 113.4s (17.1s load + 96.3s gen) | Fresh run, not reused from R0.4. Visually confirmed: full 360° rotation (0/45/90/180/270/315°), consistent subject identity/pose/texture across all 6 views — genuinely high quality |
| Crop to 4 cardinal tiles (front/right/back/left) | <1s | Manual step this round — not yet automated into a harness adapter (see §7) |
| Hunyuan3D-2mv: 4-view → shape, 20 steps, octree 256 | 87.7s (27.9s load + 0.6s rembg + 59.1s shape gen) | `tencent/Hunyuan3D-2mv`, subfolder `hunyuan3d-dit-v2-mv-turbo` |
| **Chain A total** | **~201s** | Shape only — see gap below |
| Output mesh (raw, uncleaned) | 190,742 vertices / 381,424 faces | **Watertight: True** (trimesh) |

**Real, honest gap:** this chain produces **shape only** — no texture/
PBR pass. R0.5's spike scope was deliberately shape-only
(`hy3dgen/shapegen`; `hy3dgen/texgen` is CUDA-only and out of scope).
A real production chain would need a *third* stage — plausibly
R2.3's Hunyuan3D-Paint MLX port, chained after shape generation — which
has not been tested in this combination. Chain A's real total cost for
a *textured* output is unknown, not just "~201s".

**Chain B — TRELLIS.2 single-image (item 15), same source image:**

| Step | Duration | Notes |
|---|---|---|
| Full `generate.sh -g trellis2` (shape + PBR bake + Blender cleanup) | 180s wall clock | Includes background removal, generation, texture bake, decimation to target polycount, hole-filling |
| Output mesh (cleaned, textured) | 20,325 vertices / 14,020 faces | **Watertight: False** — 5,083 small gaps reported by the cleanup pass itself |
| Texture quality check (item 3, `texture_quality_check.py`) | — | `textures_present: [albedo, roughness, metallic]`, but flagged issues: `uniform-roughness`, `uniform-metallic` |
| Turntable hero preview | — | Visually: plausible cat silhouette, but pose differs noticeably from the single reference view (crouching vs. the input's upright sit) — single-image reconstruction visibly under-constrained for the unseen side/back, and the flagged uniform-roughness/metallic issue shows as a washed-out, low-detail material in this render |

**Caveat on this comparison:** not perfectly apples-to-apples. Chain
A's mesh is raw/uncleaned (full density, no decimation); Chain B's
went through the full `generate.sh` cleanup pipeline (94% face
reduction). The watertight delta (True vs. False) is a real,
directly-observed result, but some of it may be an artifact of
Blender's decimate step introducing gaps rather than TRELLIS.2's
shape latent being inherently less clean — not disentangled here.

## 4. What this reduced-scope evidence actually shows

- **Both R0.4 and R0.5's spike-level PASSes reproduce on a fresh run**
  — not a one-off. MV-Adapter's view consistency and Hunyuan3D-2mv's
  watertight shape output are both real and repeatable.
- **TRELLIS.2 single-image is dramatically simpler**: one wrapper
  call, one venv, shape+PBR texture together, already shipped
  (item 15/R1.4) and battle-tested (R1.5's 14-prompt bake-off). Chain
  A needs three separately-installed, separately-pinned forks (MV-
  Adapter, Hunyuan3D-2mv, and an as-yet-untested paint stage) with
  real packaging bugs already found in two of the three (R0.4's
  nvdiffrast/triton coupling, R0.5's float64 MPS crash).
- **Chain A's single-image-constrained-view problem is real but
  different from TRELLIS.2's**: TRELLIS.2 hallucinates unseen
  geometry from *zero* additional views; Chain A's Hunyuan3D-2mv
  consumes 4 *AI-generated* views from MV-Adapter, which are
  themselves a single-image extrapolation one step removed — the
  "is multi-view even worth it" question (item 22's stated priority)
  isn't cleanly answered by this n=1 sample, because Chain A's
  4 input views are not independent ground truth, they're MV-
  Adapter's own guesses. A synthetic-pipeline run (Option C: real
  calibrated renders from a known GLB, no MV-2D guessing) is exactly
  what §1's full methodology would add and this reduced round did
  not.
- **No formal 6.5/10 rubric score exists for any backend** in this
  round — the rubric needs the synthetic-pipeline ground-truth
  comparison (Hausdorff distance to `ground_truth.glb`) that only
  the full methodology in §1 provides.

## 5. Disqualifications

Per the rubric (`tests/multiview-bench/scoring_rubric.json`), license
score < 4 auto-DQs regardless of any quality score:

- **InstantMesh** — DQ'd on hardware grounds alone (hard CUDA≥12.1 +
  `nvdiffrast` requirement, no MPS path exists), license uncertainty
  is secondary. See §2.
- **OpenLRM** — DQ'd: weights are CC-BY-NC 4.0, research-only (this
  repo's own adapter previously claimed the opposite — corrected in
  this PR, see §2).
- **Zero123++** — not DQ'd from the *research* comparison (it's the
  MV-2D model used in §1's Option B pipeline and in this round's
  Chain A precedent-setting), but confirmed `non_commercial` and
  therefore never eligible to be wired as a shipped lane, per item 22's
  explicit design ("research comparison only, never wired").

## 6. Recommendation

**Defer PR 10 (wiring `multiview.sh`'s new backend case).** Item 22's
own AC is explicit: wiring happens "only if a backend clears the
6.5/10 rubric." No backend has a formal rubric score this round (§0,
§4) — claiming one would mean fabricating it. This is not the "both
spikes fail" failure mode item 22 anticipated (both spikes *passed* —
R0.4, R0.5); it's a different, narrower gap: the *comparison
methodology* needs real curated ground-truth data that doesn't exist
yet (item 12 Phase 1, §1).

**What ships instead, this round:** nothing new from this PR's own
work — but the multi-view-*adjacent* story is already real and
already shipped from earlier rounds:

- `edit.sh --angle` (item 21/R2.2) for commercial-safe camera-angle
  views, once mflux ships key remapping for the Multiple-Angles LoRA
  (currently a documented no-op — see R2.2's CHANGELOG entry).
- TRELLIS.2 single-image (item 15/R1.4) as the default single-image
  path, now with real evidence (§3-4) that it's simpler and already
  working, versus a 3-stage multi-view chain that isn't fully tested
  end-to-end (no texture stage validated for Chain A).

**Followup that would unblock PR 10:** run §1's full methodology
once source GLBs exist (§7). If that shows a multi-view backend
clearing 6.5/10 and meaningfully beating TRELLIS.2 single-image on
the synthetic pipeline specifically (the apples-to-apples comparison
this round's evidence couldn't provide), wire it then.

## 7. Open follow-ups

- **Unblock the full benchmark**: source 3 GLBs into
  `tests/multiview-bench/sources/` (character / hard-surface /
  organic — item 12 Phase 1, genuinely unscoped work, not a quick
  add). This is the single highest-leverage next step; everything
  else in this doc is downstream of it.
- **Automate Chain A's tile-cropping step** into a real
  `tools/multiview_backends/`-style adapter (or a
  `tools/multiview_2d_adapters/mv_adapter.py` matching Zero123++'s
  interface) if/when Chain A gets wired — this round's crop was a
  one-off manual step, not harness-integrated.
- **Test the missing texture stage for Chain A**: chain R2.3's
  Hunyuan3D-Paint MLX port after Hunyuan3D-2mv's shape output and
  re-measure total time + quality — Chain A's real cost/quality vs.
  TRELLIS.2 is unknown until this exists.
- **Vendor the two real fixes found in R0.4/R0.5** before any
  production wiring: MV-Adapter's `mesh_utils/__init__.py`
  nvdiffrast/triton lazy-import patch, and Hunyuan3D-2mv's
  `schedulers.py` float64→float32 MPS cast — both documented in
  `docs/spike-report-generation-refresh.md`, neither yet applied
  anywhere outside the throwaway spike installs.
- If InstantMesh's hardware situation ever changes (unlikely) or a
  license review clears it independently: re-evaluate, but hardware
  is the harder blocker of the two.

---

*This doc closes P3.1b / item 22's PR 9 (research) with an
evidence-backed deferral, per item 22's own AC. It does not gate
PR 10, because PR 10 is not landing this round — the followup in §7
is what would unblock it.*
