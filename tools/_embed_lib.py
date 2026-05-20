"""Shared logic for HTML embed regeneration and verification.

The user-facing HTML guide (`docs/asset-pipeline-guide.html`) embeds canonical
script files byte-for-byte inside `<pre>cat > path << 'PIPELINE_EOF' ...
PIPELINE_EOF</pre>` heredoc blocks so a user can paste the install into a
terminal. Scripts in /scripts and /skill are the source of truth; the HTML is
derived.

Both regenerate_embeds.py and verify_embeds.py rely on the helpers here.
"""
from __future__ import annotations

import html
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# v0.2: two user-facing guides — one for each hardware tier. Both embed the
# same canonical scripts, so the regen tool iterates over both.
GUIDE_PATHS = [
    PROJECT_ROOT / "docs" / "asset-pipeline-guide.html",
    PROJECT_ROOT / "docs" / "asset-pipeline-guide-studio.html",
]
# Back-compat alias — verify_embeds/regenerate_embeds historically used a
# single path. Kept so any external scripts still work.
GUIDE_PATH = GUIDE_PATHS[0]

# Map: project-relative canonical file -> path embedded in the HTML heredoc.
# Order matches the order the blocks appear in the guide for readability.
EMBEDS: dict[str, str] = {
    "scripts/_pipeline_lib.sh":          "~/3d-pipeline/workspace/_pipeline_lib.sh",
    "scripts/json_emit.py":              "~/3d-pipeline/workspace/json_emit.py",
    "scripts/concept.sh":                "~/3d-pipeline/workspace/concept.sh",
    "scripts/generate.sh":               "~/3d-pipeline/workspace/generate.sh",
    "scripts/print.sh":                  "~/3d-pipeline/workspace/print.sh",
    "scripts/clean_asset.py":            "~/3d-pipeline/workspace/clean_asset.py",
    "scripts/prepare_for_print.py":      "~/3d-pipeline/workspace/prepare_for_print.py",
    "scripts/migrate_assets.sh":         "~/3d-pipeline/workspace/migrate_assets.sh",
    "scripts/benchmark.sh":              "~/3d-pipeline/workspace/benchmark.sh",
    "scripts/model_bakeoff.py":          "~/3d-pipeline/workspace/model_bakeoff.py",
    "scripts/texture.sh":                "~/3d-pipeline/workspace/texture.sh",
    "scripts/texture_inspect.py":        "~/3d-pipeline/workspace/texture_inspect.py",
    "scripts/queue_submit.py":           "~/3d-pipeline/workspace/queue_submit.py",
    "scripts/queue_worker.py":           "~/3d-pipeline/workspace/queue_worker.py",
    "skill/SKILL.md":                    "~/.claude/skills/asset-pipeline/SKILL.md",
    "skill/scripts/update_manifest.py":  "~/.claude/skills/asset-pipeline/scripts/update_manifest.py",
    "scripts/meta_helper.py":           "~/3d-pipeline/workspace/meta_helper.py",
    "scripts/meta_schema.json":         "~/3d-pipeline/workspace/meta_schema.json",
    "scripts/pipeline_doctor.py":       "~/3d-pipeline/workspace/pipeline_doctor.py",
    "scripts/model_manifest.json":      "~/3d-pipeline/workspace/model_manifest.json",
    "scripts/input_quality_check.py":   "~/3d-pipeline/workspace/input_quality_check.py",
    "scripts/mesh_quality_check.py":    "~/3d-pipeline/workspace/mesh_quality_check.py",
    "scripts/texture_quality_check.py": "~/3d-pipeline/workspace/texture_quality_check.py",
    "scripts/rembg_preprocess.py":      "~/3d-pipeline/workspace/rembg_preprocess.py",
    "scripts/turntable_render.py":      "~/3d-pipeline/workspace/turntable_render.py",
    "scripts/game_asset_check.py":      "~/3d-pipeline/workspace/game_asset_check.py",
    "scripts/print_structural_check.py": "~/3d-pipeline/workspace/print_structural_check.py",
    "scripts/clip_score.py":             "~/3d-pipeline/workspace/clip_score.py",
    "scripts/clip_calibration.json":     "~/3d-pipeline/workspace/clip_calibration.json",
    "scripts/multiview_benchmark.py":    "~/3d-pipeline/workspace/multiview_benchmark.py",
    "scripts/calibrate_clip.py":         "~/3d-pipeline/workspace/calibrate_clip.py",
    "scripts/multiview.sh":              "~/3d-pipeline/workspace/multiview.sh",
    "scripts/consistency_pack_schema.json": "~/3d-pipeline/workspace/consistency_pack_schema.json",
    "scripts/comfyui_dispatch.py":          "~/3d-pipeline/workspace/comfyui_dispatch.py",
    "scripts/comfyui_workflows/consistency_sdxl.json": "~/3d-pipeline/workspace/comfyui_workflows/consistency_sdxl.json",
}

# Block pattern: opener line, body, closing PIPELINE_EOF on its own line.
# The opener uses literal `>`, `<`, `'` (safe in <pre>) — only the body is escaped.
BLOCK_RE = re.compile(
    r"(<pre>cat > (?P<path>\S+) << 'PIPELINE_EOF'\n)(?P<body>.*?)(\nPIPELINE_EOF)",
    re.DOTALL,
)


def file_body_for_embed(path: Path) -> str:
    """Read a canonical file and strip exactly one trailing newline (if any).

    The heredoc body in the HTML does not include a final newline before the
    `PIPELINE_EOF` marker — that newline is part of the heredoc terminator.
    Canonical files on disk end with a trailing newline (POSIX convention),
    so we drop one to keep the embed round-trippable.
    """
    text = path.read_text()
    if text.endswith("\n"):
        text = text[:-1]
    return text


def expected_escaped_body(path: Path) -> str:
    return html.escape(file_body_for_embed(path), quote=True)


def parse_blocks(html_text: str) -> dict[str, str]:
    """Return {embedded_path: current_escaped_body} for every block in the HTML."""
    return {m.group("path"): m.group("body") for m in BLOCK_RE.finditer(html_text)}
