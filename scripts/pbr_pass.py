#!/usr/bin/env python3
"""v0.4 item 24 — PBR texture pass (albedo -> StableDelight -> Marigold-IID).

Extracts a GLB's existing baseColorTexture, runs it through StableDelight
(removes baked-in specular highlights) then Marigold-IID Appearance
(roughness + metallic decomposition), and writes a new GLB with the
delighted albedo as baseColorTexture and a packed roughness/metallic as
metallicRoughnessTexture (glTF convention: G=roughness, B=metallic).

Caller (texture.sh --mode pbr) is responsible for refusing to run this
on a mesh that already has a metallicRoughnessTexture — this script
always overwrites whatever material state the mesh has.

Two real upstream bugs worked around here, both confirmed live on this
Studio (R3.2 spike, 2026-08):

1. StableDelight's dynamically-downloaded custom pipeline module
   (`controlnetvae.py`) imports `from diffusers.models.controlnet import
   ControlNetOutput` — that path was reorganized into
   `diffusers.models.controlnets.controlnet` in the diffusers version
   this pipeline uses. Patching the downloaded cache file doesn't stick
   (diffusers re-syncs it against the remote hash on each load), so the
   fix is a `sys.modules` alias registered before the dynamic import
   fires — same technique as R0.4's MV-Adapter nvdiffrast/triton stub.
2. `torch.hub.load(..., "StableDelight_turbo")` defaults to
   `device="cuda:0"` — pass `device="mps"` explicitly (a real, accepted
   kwarg on the hub entry point, not a hack).

Usage:
    pbr_pass.py --input PATH.glb --output PATH.glb --meta PATH [--json]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
META_HELPER = SCRIPT_DIR / "meta_helper.py"


def _imports():
    try:
        import numpy as np
        import torch
        import trimesh
        from diffusers import MarigoldIntrinsicsPipeline
        return np, torch, trimesh, MarigoldIntrinsicsPipeline
    except ImportError as e:
        print(f"ERROR: missing dep ({e}); install the pbr-pass-env venv.", file=sys.stderr)
        sys.exit(2)


def _load_stabledelight(torch, device: str):
    import diffusers.models.controlnets.controlnet as _cn
    sys.modules["diffusers.models.controlnet"] = _cn
    return torch.hub.load("Stable-X/StableDelight", "StableDelight_turbo", trust_repo=True, device=device)


def _merge_meta(meta_path: Path, payload: dict) -> None:
    subprocess.run(
        [sys.executable, str(META_HELPER), "merge", str(meta_path),
         "--section", "quality", "--data", json.dumps({"textures": payload})],
        check=False, capture_output=True,
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    p.add_argument("--meta", required=True)
    p.add_argument("--device", default="mps")
    p.add_argument("--marigold-steps", type=int, default=10)
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    np, torch, trimesh, MarigoldIntrinsicsPipeline = _imports()

    t0 = time.time()
    mesh = trimesh.load(Path(args.input).expanduser(), force="mesh")
    material = getattr(mesh.visual, "material", None)
    albedo_tex = getattr(material, "baseColorTexture", None) if material is not None else None
    if albedo_tex is None:
        print("ERROR: input has no baseColorTexture to process.", file=sys.stderr)
        return 2
    albedo_img = albedo_tex.convert("RGB") if hasattr(albedo_tex, "convert") else albedo_tex

    delight_predictor = _load_stabledelight(torch, args.device)
    delighted = delight_predictor(albedo_img)
    t_delight = time.time()

    marigold = MarigoldIntrinsicsPipeline.from_pretrained(
        "prs-eth/marigold-iid-appearance-v1-1", variant="fp16", torch_dtype=torch.float16,
    ).to(args.device)
    output = marigold(delighted, num_inference_steps=args.marigold_steps)
    t_marigold = time.time()

    # prediction shape (2, H, W, 3): [0]=albedo (sRGB), [1]=material stack
    # (roughness, metallicity, unused) per Marigold's own target_properties.
    final_albedo = output.prediction[0]
    material_stack = output.prediction[1]
    roughness = material_stack[..., 0]
    metallic = material_stack[..., 1]

    h, w = roughness.shape
    mr = np.zeros((h, w, 3), dtype=np.uint8)
    mr[..., 1] = (np.clip(roughness, 0, 1) * 255).astype(np.uint8)  # glTF: G=roughness
    mr[..., 2] = (np.clip(metallic, 0, 1) * 255).astype(np.uint8)   # glTF: B=metallic

    from PIL import Image
    final_albedo_img = Image.fromarray((np.clip(final_albedo, 0, 1) * 255).astype(np.uint8))
    mr_img = Image.fromarray(mr)

    uv = getattr(mesh.visual, "uv", None)
    new_mesh = trimesh.Trimesh(vertices=mesh.vertices, faces=mesh.faces, process=False)
    new_mesh.visual = trimesh.visual.TextureVisuals(
        uv=uv,
        material=trimesh.visual.material.PBRMaterial(
            baseColorTexture=final_albedo_img,
            metallicRoughnessTexture=mr_img,
            metallicFactor=1.0,
            roughnessFactor=1.0,
        ),
    )
    new_mesh.export(Path(args.output).expanduser())
    duration = round(time.time() - t0, 2)

    payload = {
        "pbr_pass": {
            "applied": True,
            "maps_added": ["albedo", "roughness", "metallic"],
            "delight_seconds": round(t_delight - t0, 2),
            "marigold_seconds": round(t_marigold - t_delight, 2),
            "duration_seconds": duration,
        }
    }
    _merge_meta(Path(args.meta).expanduser(), payload)

    if args.json:
        print(json.dumps(payload["pbr_pass"], sort_keys=True))
    else:
        print(f"[pbr] albedo + roughness + metallic written in {duration}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
