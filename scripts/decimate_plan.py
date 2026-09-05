#!/usr/bin/env python3
"""Decide how far a mesh may be decimated before it stops looking like itself.

Collapse decimation is safe on props: a crate at 3,000 polygons is still a
crate. It is not safe on dense organic meshes — a face loses its nose long
before a crate loses its corners. Worse, Blender's decimator silently floors
out well above an unreachable target instead of failing, so the pipeline would
otherwise record a polycount it never actually hit.

Measured on this pipeline's own output:

    source    target    result    verdict
    19,059     3,000     3,000    clean  (SF3D prop)
    32,383     3,000     2,999    clean  (SF3D prop)
    48,530     3,000     2,999    clean  (SF3D prop)
   187,974    12,000    47,626    face destroyed, target never reached
   187,974   100,000   100,000    clean  (TRELLIS.2 character)

So the discriminator is not the ratio alone — props legitimately decimate to
6% of source. It is a dense source mesh *combined with* an aggressive target.
Props arrive under 50k polys; organic generators arrive near 190k.
"""

DENSE_MESH_POLYS = 100_000
MIN_SAFE_RATIO = 0.25


def plan_decimate(source_polys, requested_target,
                  min_ratio=MIN_SAFE_RATIO, dense_threshold=DENSE_MESH_POLYS):
    """Return the decimation plan for a mesh.

    Keys: target (int, what to actually decimate to), requested_target (int,
    what the caller asked for), clamped (bool), reason (str or None).

    Pass min_ratio=0 to disable the guard entirely.
    """
    plan = {
        "target": requested_target,
        "requested_target": requested_target,
        "clamped": False,
        "reason": None,
    }

    if requested_target >= source_polys:
        return plan  # nothing to decimate
    if min_ratio <= 0 or source_polys < dense_threshold:
        return plan  # guard disabled, or a prop-density mesh

    floor = int(source_polys * min_ratio)
    if requested_target >= floor:
        return plan

    plan["target"] = floor
    plan["clamped"] = True
    plan["reason"] = (
        f"target {requested_target:,} is below {min_ratio:.0%} of a dense "
        f"{source_polys:,}-poly mesh; collapse decimation cannot reach it "
        f"without destroying surface detail. Using {floor:,} instead. "
        f"For a genuinely low-poly version use --retopo quad, or pass "
        f"--no-clean and decimate deliberately."
    )
    return plan


def target_met(decimate_after, effective_target, tolerance=1.05):
    """True when the decimator actually reached the target it was given."""
    return decimate_after <= effective_target * tolerance
