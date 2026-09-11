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

