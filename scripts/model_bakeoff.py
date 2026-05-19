#!/usr/bin/env python3
"""Model bake-off orchestrator (v0.2).

Invoked by benchmark.sh; not intended to be called directly. Reads a list
of prompts, calls concept.sh / generate.sh under `--json` to produce
structured per-run results, and writes a combined JSON to
`<assets_root>/benchmarks/<timestamp>/benchmark_results.json`.

The harness deliberately does NOT try to auto-score outputs (subjective
fields like prompt_match are scaffolded as `null` for a manual review
pass later). It DOES record everything needed to make ranking possible:
runtime, paths, file sizes, license bucket, hardware tier, machine,
exit status, and the wrapper's own JSON.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

DEFAULT_SUITE = [
    "wooden treasure chest",
    "fantasy sword",
    "shield with emblem",
    "potion bottle",
    "barrel crate prop",
    "stylized creature bust",
    "small creature",
    "character bust",
    "modular stone wall segment",
    "statue or terrain decoration",
    "product prototype stand",
    "printable figurine",
    "text logo plaque",
    "simple game environment object",
]

QUICK_SUITE = [
    "wooden treasure chest",
    "fantasy sword",
    "printable figurine",
]

LICENSE_BUCKET = {
    "z-image-turbo": "commercial_safe",
    "flux-schnell": "commercial_safe",
    "flux-dev": "non_commercial",
    "qwen-image": "commercial_safe",
    "sf3d": "commercial_threshold",
    "spar3d": "commercial_threshold",
    "trellis": "non_commercial",
}

EVAL_SCAFFOLD = {
    "prompt_match": None,
    "front_accuracy": None,
    "backside_plausibility": None,
    "topology": None,
    "uv_quality": None,
    "texture_quality": None,
    "pbr_maps_present": None,
    "unity_import": "not_tested",
    "unreal_import": "not_tested",
    "print_prep": "not_tested",
    "slicer_check": "not_tested",
    "failure_type": "",
    "review_notes": "",
}


def _file_size(path: str) -> int | None:
    if not path:
        return None
    p = Path(os.path.expanduser(path))
    return p.stat().st_size if p.exists() else None


def _slug(text: str) -> str:
    out = []
    last_underscore = True
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
            last_underscore = False
        elif not last_underscore:
            out.append("_")
            last_underscore = True
    s = "".join(out).strip("_")
    return s[:50] or "prompt"


def _load_prompts(args) -> list[str]:
    if args.prompts_file:
        text = Path(os.path.expanduser(args.prompts_file)).read_text()
        return [line.strip() for line in text.splitlines()
                if line.strip() and not line.startswith("#")]
    if args.suite == "default":
        return list(DEFAULT_SUITE)
    if args.suite == "quick":
        return list(QUICK_SUITE)
    # `custom` without --prompts-file is an error caught upstream.
    return []


def _run_wrapper(cmd: list[str], dry_run: bool) -> tuple[int, dict[str, Any] | None, str]:
    """Run a wrapper under --json. Returns (exit_code, parsed_json_or_None, stderr_tail)."""
    if dry_run:
        return 0, {"status": "dry_run", "cmd": cmd}, ""
    proc = subprocess.run(cmd, capture_output=True, text=True)
    parsed: dict[str, Any] | None = None
    # Last non-empty line of stdout should be the JSON object.
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            parsed = json.loads(line)
        except json.JSONDecodeError:
            parsed = None
        break
    stderr_tail = "\n".join(proc.stderr.splitlines()[-20:])
    return proc.returncode, parsed, stderr_tail


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--assets-root", required=True)
    p.add_argument("--manifest-path", required=True)
    p.add_argument("--project-mode", required=True)
    p.add_argument("--project-root", default="")
    p.add_argument("--project-engine", default="none")
    p.add_argument("--hardware-tier", required=True)
    p.add_argument("--machine", required=True)
    p.add_argument("--script-dir", required=True,
                   help="Directory containing concept.sh / generate.sh")
    p.add_argument("--suite", default="default",
                   choices=["default", "quick", "custom"])
    p.add_argument("--prompts-file", default="")
    p.add_argument("--generators", default="sf3d")
    p.add_argument("--models-2d", default="z-image-turbo")
    p.add_argument("--count", type=int, default=1)
    p.add_argument("--polycount", type=int, default=0)
    p.add_argument("--texture-resolution", type=int, default=0)
    p.add_argument("--skip-2d", action="store_true")
    p.add_argument("--skip-3d", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args()

    if args.suite == "custom" and not args.prompts_file:
        print("ERROR: --suite custom requires --prompts-file", file=sys.stderr)
        return 2

    prompts = _load_prompts(args)
    if not prompts:
        print("ERROR: no prompts to run", file=sys.stderr)
        return 2

    models_2d = [m.strip() for m in args.models_2d.split(",") if m.strip()]
    generators = [g.strip() for g in args.generators.split(",") if g.strip()]

    for m in models_2d:
        if m not in LICENSE_BUCKET:
            print(f"ERROR: unknown 2D model: {m}", file=sys.stderr)
            return 2
    for g in generators:
        if g not in {"sf3d", "spar3d", "trellis"}:
            print(f"ERROR: unknown 3D generator: {g}", file=sys.stderr)
            return 2

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = Path(args.assets_root) / "benchmarks" / stamp
    out_dir.mkdir(parents=True, exist_ok=True)
    results_path = out_dir / "benchmark_results.json"

    concept_sh = Path(args.script_dir) / "concept.sh"
    generate_sh = Path(args.script_dir) / "generate.sh"

    overall = {
        "schema_version": 1,
        "suite": args.suite,
        "started": datetime.now().isoformat(timespec="seconds"),
        "hardware_tier": args.hardware_tier,
        "machine": args.machine,
        "project_mode": args.project_mode,
        "project_root": args.project_root,
        "project_engine": args.project_engine,
        "models_2d": models_2d,
        "generators": generators,
        "polycount": args.polycount,
        "texture_resolution": args.texture_resolution,
        "skip_2d": args.skip_2d,
        "skip_3d": args.skip_3d,
        "dry_run": args.dry_run,
        "prompts": prompts,
        "runs": [],
    }

    def add_run(record: dict[str, Any]):
        record.setdefault("eval", dict(EVAL_SCAFFOLD))
        overall["runs"].append(record)

    # ---- 2D pass ----
    concept_paths: dict[tuple[str, str], list[str]] = {}
    if not args.skip_2d:
        for prompt in prompts:
            for model_2d in models_2d:
                cmd = [str(concept_sh), prompt,
                       "-m", model_2d,
                       "-n", str(args.count),
                       "-o", f"bench_{stamp}_{_slug(prompt)}_{model_2d}",
                       "--json"]
                if args.project_root:
                    cmd.extend(["--project", args.project_root])
                t0 = time.time()
                rc, j, stderr_tail = _run_wrapper(cmd, args.dry_run)
                dt = time.time() - t0
                outputs = (j or {}).get("outputs", []) if j else []
                concept_paths[(prompt, model_2d)] = outputs
                add_run({
                    "stage": "text_to_image",
                    "prompt": prompt,
                    "model": model_2d,
                    "license_bucket": LICENSE_BUCKET.get(model_2d, "unknown"),
                    "exit_code": rc,
                    "duration_seconds": round(dt, 2),
                    "outputs": outputs,
                    "output_sizes_bytes": [_file_size(o) for o in outputs],
                    "status": "ok" if rc == 0 else "error",
                    "stderr_tail": stderr_tail if rc != 0 else "",
                    "wrapper_json": j,
                })

    # ---- 3D pass ----
    if not args.skip_3d:
        for prompt in prompts:
            input_path = ""
            input_model = ""
            for model_2d in models_2d:
                paths = concept_paths.get((prompt, model_2d), [])
                if paths:
                    input_path = paths[0]
                    input_model = model_2d
                    break
            if not input_path:
                add_run({
                    "stage": "image_to_3d",
                    "prompt": prompt,
                    "status": "skipped",
                    "reason": "no concept image (skip-2d set and no cached input given)",
                })
                continue

            for gen in generators:
                cmd = [str(generate_sh),
                       "-i", input_path,
                       "-g", gen,
                       "-o", f"bench_{stamp}_{_slug(prompt)}_{gen}",
                       "--json"]
                if args.project_root:
                    cmd.extend(["--project", args.project_root])
                if args.polycount:
                    cmd.extend(["-p", str(args.polycount)])
                if args.texture_resolution:
                    cmd.extend(["-t", str(args.texture_resolution)])
                t0 = time.time()
                rc, j, stderr_tail = _run_wrapper(cmd, args.dry_run)
                dt = time.time() - t0
                clean_path = (j or {}).get("clean_path", "")
                raw_path = (j or {}).get("raw_path", "")
                add_run({
                    "stage": "image_to_3d",
                    "prompt": prompt,
                    "input_concept": input_path,
                    "input_concept_model": input_model,
                    "generator": gen,
                    "license_bucket": LICENSE_BUCKET.get(gen, "unknown"),
                    "exit_code": rc,
                    "duration_seconds": round(dt, 2),
                    "raw_path": raw_path,
                    "clean_path": clean_path,
                    "raw_size_bytes": _file_size(raw_path),
                    "clean_size_bytes": _file_size(clean_path),
                    "status": "ok" if rc == 0 else "error",
                    "stderr_tail": stderr_tail if rc != 0 else "",
                    "wrapper_json": j,
                })

    overall["finished"] = datetime.now().isoformat(timespec="seconds")
    overall["run_count"] = len(overall["runs"])
    overall["summary"] = {
        "ok": sum(1 for r in overall["runs"] if r.get("status") == "ok"),
        "errors": sum(1 for r in overall["runs"] if r.get("status") == "error"),
        "skipped": sum(1 for r in overall["runs"] if r.get("status") == "skipped"),
        "total": len(overall["runs"]),
    }

    with open(results_path, "w") as f:
        json.dump(overall, f, indent=2, sort_keys=True)
        f.write("\n")

    if args.json:
        print(json.dumps({
            "status": "ok",
            "stage": "benchmark",
            "results_path": str(results_path),
            "run_count": overall["run_count"],
            "summary": overall["summary"],
            "hardware_tier": args.hardware_tier,
            "machine": args.machine,
        }))
    else:
        print(f"[benchmark] wrote {overall['run_count']} runs to {results_path}")
        print(f"[benchmark] summary: {overall['summary']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
