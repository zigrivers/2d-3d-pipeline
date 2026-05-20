#!/usr/bin/env python3
"""Option B in P3.1a.1 — build a multi-view benchmark subject from a
single concept image via a multi-view-aware 2D model.

Given a source GLB (for ground truth) and either an existing concept
image or render-it-from-the-GLB instruction, dispatches the chosen
multi-view-2D adapter, collects the generated views, and prepares the
subject directory the benchmark harness expects.

Pipeline:

  source.glb                 (ground truth)
    │
    └─→ concept.png          (one rendered view at 45°, elev 15°)
          │
          └─→ MV-2D adapter  (Zero123++, MVDream, Wonder3D, …)
                │
                └─→ subject-N-X-mvgen-<model>/
                      {view-name}.png × N      (the multi-view output)
                      ground_truth.glb         (copy of source)
                      meta.json                (input_pipeline=mvgen)

Usage:
    build_mvgen_dataset.py \
        --source PATH.glb \
        --output-dir tests/multiview-bench/subjects/subject-1-character-mvgen-zero123/ \
        --mv-2d-model zero123_plus_plus \
        [--concept PATH.png]                    (skip the auto-render if supplied)
        [--render-helper tools/render_benchmark_views.py]
        [--blender /Applications/Blender.app/Contents/MacOS/Blender]
        [--adapter-python ~/3d-pipeline/pipeline-tools-env/bin/python]

This is a maintainer tool; lives in /tools, NOT subject to the
canonical-vs-embedded rule.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADAPTERS_DIR = Path(__file__).resolve().parent / "multiview_2d_adapters"
DEFAULT_BLENDER = "/Applications/Blender.app/Contents/MacOS/Blender"


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kwargs)


def _render_concept(blender: str, render_helper: Path, source: Path, output_dir: Path) -> Path:
    """Use render_benchmark_views.py but only keep the concept.png. Cheap."""
    # Render into a temp dir using the canonical view config (we only want the
    # 45° concept image; the 4 cardinal views are byproducts and we discard them).
    view_config = REPO_ROOT / "tests" / "multiview-bench" / "view_configs" / "canonical_4view.json"
    with tempfile.TemporaryDirectory() as tmp:
        cmd = [
            blender, "--background", "--python", str(render_helper), "--",
            "--source", str(source),
            "--output-dir", tmp,
            "--view-config", str(view_config),
        ]
        cp = _run(cmd, timeout=300)
        if cp.returncode != 0:
            raise RuntimeError(
                f"render helper failed (exit {cp.returncode}):\n"
                f"{cp.stdout}\n{cp.stderr}"
            )
        concept_src = Path(tmp) / "concept.png"
        if not concept_src.exists():
            raise RuntimeError(f"render helper did not produce concept.png in {tmp}")
        # Move concept into the OUTPUT subject directory.
        output_dir.mkdir(parents=True, exist_ok=True)
        target = output_dir / "concept.png"
        shutil.copyfile(concept_src, target)
        return target


def _dispatch_adapter(adapter_python: str, adapter_path: Path, concept: Path,
                      output_dir: Path) -> dict:
    cmd = [
        adapter_python, str(adapter_path),
        "--concept", str(concept),
        "--output-dir", str(output_dir),
        "--json",
    ]
    cp = _run(cmd, timeout=600)
    if cp.returncode != 0 and not cp.stdout.strip():
        raise RuntimeError(
            f"adapter failed with no JSON output (exit {cp.returncode}):\n"
            f"{cp.stderr}"
        )
    # The adapter prints exactly one JSON line on success.
    last_line = (cp.stdout.strip().splitlines() or [""])[-1]
    try:
        return json.loads(last_line)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"adapter emitted non-JSON on stdout:\n{cp.stdout}\n{cp.stderr}"
        ) from e


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--source", required=True, help="Path to source GLB (ground truth)")
    p.add_argument("--output-dir", required=True,
                   help="Subject directory under tests/multiview-bench/subjects/")
    p.add_argument("--mv-2d-model", required=True,
                   help="MV-2D adapter name; expects "
                        "tools/multiview_2d_adapters/<name>.py")
    p.add_argument("--concept", default="",
                   help="Pre-existing concept image (skip auto-render)")
    p.add_argument("--render-helper",
                   default=str(REPO_ROOT / "tools" / "render_benchmark_views.py"))
    p.add_argument("--blender", default=os.environ.get("BLENDER", DEFAULT_BLENDER))
    p.add_argument("--adapter-python",
                   default=os.environ.get("PIPELINE_TOOLS_PYTHON",
                                          os.path.expanduser("~/3d-pipeline/pipeline-tools-env/bin/python")))
    args = p.parse_args()

    source = Path(os.path.expanduser(args.source))
    output_dir = Path(os.path.expanduser(args.output_dir))
    adapter = ADAPTERS_DIR / f"{args.mv_2d_model}.py"
    render_helper = Path(os.path.expanduser(args.render_helper))

    if not source.exists():
        print(f"ERROR: source not found: {source}", file=sys.stderr)
        return 2
    if not adapter.exists():
        print(f"ERROR: adapter not found: {adapter}", file=sys.stderr)
        print(f"       Available adapters: "
              f"{sorted(p.stem for p in ADAPTERS_DIR.glob('*.py') if not p.stem.startswith('_'))}",
              file=sys.stderr)
        return 2
    if not os.path.exists(args.adapter_python):
        print(f"ERROR: pipeline-tools-env python not found: {args.adapter_python}",
              file=sys.stderr)
        print("       Run the v0.3 install step (section 10 in the setup guides),",
              file=sys.stderr)
        print("       then add diffusers + transformers + accelerate to that venv.",
              file=sys.stderr)
        return 2

    output_dir.mkdir(parents=True, exist_ok=True)

    # 1) Acquire the concept image
    if args.concept:
        concept_path = Path(os.path.expanduser(args.concept))
        if not concept_path.exists():
            print(f"ERROR: --concept not found: {concept_path}", file=sys.stderr)
            return 2
        # Copy into the subject directory for self-containment
        target_concept = output_dir / "concept.png"
        shutil.copyfile(concept_path, target_concept)
        concept_path = target_concept
        concept_source = "supplied"
    else:
        if not Path(args.blender).exists():
            print(f"ERROR: Blender not found at {args.blender}", file=sys.stderr)
            return 2
        if not render_helper.exists():
            print(f"ERROR: render helper not found: {render_helper}", file=sys.stderr)
            return 2
        print(f"[build-mvgen] rendering concept from {source}…")
        concept_path = _render_concept(args.blender, render_helper, source, output_dir)
        concept_source = "rendered"

    # 2) Dispatch the multi-view-2D adapter
    print(f"[build-mvgen] dispatching adapter {args.mv_2d_model}…")
    try:
        adapter_result = _dispatch_adapter(args.adapter_python, adapter, concept_path, output_dir)
    except Exception as e:
        print(f"ERROR: adapter dispatch failed: {e}", file=sys.stderr)
        return 1
    if adapter_result.get("status") != "ok":
        print(f"ERROR: adapter reported error: {json.dumps(adapter_result, indent=2)}",
              file=sys.stderr)
        return 1

    # 3) Copy the source GLB as ground_truth.glb
    gt_path = output_dir / "ground_truth.glb"
    shutil.copyfile(source, gt_path)

    # 4) Write the subject meta.json
    meta = {
        "input_pipeline": "mvgen",
        "mv_2d_model": adapter_result.get("model", args.mv_2d_model),
        "mv_2d_license_bucket": adapter_result.get("license_bucket"),
        "mv_2d_device": adapter_result.get("device"),
        "mv_2d_duration_seconds": adapter_result.get("duration_seconds"),
        "concept_source": concept_source,
        "concept_path": str(concept_path),
        "source_glb": str(source.name),
        "ground_truth_glb": str(gt_path),
        "views": adapter_result.get("views", []),
    }
    with open(output_dir / "meta.json", "w") as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)
        fh.write("\n")

    n_views = len(adapter_result.get("views", []))
    print(f"[build-mvgen] wrote {n_views} views to {output_dir}")
    print(f"[build-mvgen]   model:       {meta['mv_2d_model']}")
    print(f"[build-mvgen]   license:     {meta['mv_2d_license_bucket']}")
    print(f"[build-mvgen]   ground-truth: {gt_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
