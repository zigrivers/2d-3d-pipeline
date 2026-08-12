#!/usr/bin/env python3
"""v0.4 — Hunyuan3D-Paint MLX port driver (item 19).

Thin CLI wrapper around Hunyuan3DPaintPipelineMLX (dgrauet/Hunyuan3D-2.1-mlx)
so texture.sh doesn't need an inline heredoc for the paint call. Must run
inside the port's own venv, with --port-dir pointing at the pinned checkout
(so hy3dpaint/ can be imported).

Mirrors the exact call shape verified working in the R0.2 spike
(run_paint_spike.py): Hunyuan3DPaintConfigMLX(max_num_view, resolution) then
pipe(mesh_path=, image_path=, output_mesh_path=, save_glb=True).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--port-dir", required=True, help="Pinned Hunyuan3D-2.1-mlx checkout")
    p.add_argument("--mesh", required=True)
    p.add_argument("--image", required=True)
    p.add_argument("--output", required=True, help="Output .obj path; sibling .glb also written")
    p.add_argument("--max-num-view", type=int, default=6)
    p.add_argument("--resolution", type=int, default=512)
    args = p.parse_args()

    if not args.output.endswith(".obj"):
        print(f"ERROR: --output must end in .obj (got {args.output})", file=sys.stderr)
        return 1

    sys.path.insert(0, str(Path(args.port_dir) / "hy3dpaint"))
    from textureGenPipeline_mlx import Hunyuan3DPaintConfigMLX, Hunyuan3DPaintPipelineMLX  # type: ignore

    t0 = time.time()
    cfg = Hunyuan3DPaintConfigMLX(max_num_view=args.max_num_view, resolution=args.resolution)
    pipe = Hunyuan3DPaintPipelineMLX(cfg)
    t_load = time.time()

    out_obj = pipe(
        mesh_path=args.mesh,
        image_path=args.image,
        output_mesh_path=args.output,
        save_glb=True,
    )
    t_done = time.time()

    # Prefixed and printed last so the caller can `tee` the whole run (library
    # progress bars included) to the terminal while still reliably pulling
    # just this one line back out via `grep '^PAINT_RESULT '`.
    print("PAINT_RESULT " + json.dumps({
        "output_obj": str(out_obj),
        "output_glb": args.output[: -len(".obj")] + ".glb",
        "load_seconds": round(t_load - t0, 1),
        "paint_seconds": round(t_done - t_load, 1),
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
