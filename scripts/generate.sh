#!/usr/bin/env bash
#
# 3D Asset Generator Wrapper (project-aware)
# Runs a 2D image through SF3D or TRELLIS.2, then Blender cleanup, and
# optionally stages the final GLB into the engine's native assets folder.
#
# Project detection (same as concept.sh):
#   1. --project PATH
#   2. PROJECT_ROOT env var
#   3. .asset-pipeline.json walking up from $PWD
#   4. Unity / Unreal markers walking up from $PWD
#   5. Falls back to ~/3d-pipeline/workspace/
#
# In project mode with Unity/Unreal detected, the cleaned GLB is also
# copied to the engine's native folder (default: Assets/Models/AI for
# Unity, Content/Models/AI for Unreal). Override with .asset-pipeline.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_pipeline_lib.sh"

PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"
SF3D_DIR="$PIPELINE_ROOT/stable-fast-3d"
TRELLIS_DIR="$PIPELINE_ROOT/trellis-mac"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"

EXPLICIT_PROJECT=""
GENERATOR=""
INPUT=""
OUTPUT_NAME=""
POLYCOUNT=""
TEXTURE_RES=""
REMESH="quad"
UP_AXIS="y"
SKIP_CLEAN=0
SKIP_ENGINE_STAGE=0

usage() {
    cat <<EOF
Usage: $(basename "$0") -i IMAGE [options]

Required:
  -i, --input PATH         Input 2D image (PNG/JPG)

Project context:
  --project PATH           Force a project root (skips auto-detection)
      --no-engine-stage    Skip copying clean GLB into engine folder
                           (project mode with Unity/Unreal only)

Generation options:
  -g, --generator NAME     sf3d (default) | trellis
  -o, --output NAME        Output name (default: derived from input)
  -p, --polycount N        Target polycount after cleanup (default: 3000)
  -t, --texture-res N      SF3D texture resolution (default: 2048)
  -r, --remesh OPT         none | triangle | quad (default: quad)
  -u, --up AXIS            y (default) | z
      --no-clean           Skip Blender cleanup; raw mesh only
  -h, --help               This help

Examples:
  # Auto-detect project (Unity/Unreal). Cleaned GLB also lands in
  # Assets/Models/AI/ (Unity) or Content/Models/AI/ (Unreal).
  $(basename "$0") -i assets/concept/chest.png

  # Chain from concept.sh output:
  CONCEPT=\$(concept.sh "treasure chest" | tail -n 1) && \\
    $(basename "$0") -i "\$CONCEPT"

  # Force a particular project regardless of cwd:
  $(basename "$0") -i ~/Downloads/chest.png --project ~/games/grithkin
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)           EXPLICIT_PROJECT="$2"; shift 2 ;;
        -i|--input)          INPUT="$2";        shift 2 ;;
        -g|--generator)      GENERATOR="$2";    shift 2 ;;
        -o|--output)         OUTPUT_NAME="$2";  shift 2 ;;
        -p|--polycount)      POLYCOUNT="$2";    shift 2 ;;
        -t|--texture-res)    TEXTURE_RES="$2";  shift 2 ;;
        -r|--remesh)         REMESH="$2";       shift 2 ;;
        -u|--up)             UP_AXIS="$2";      shift 2 ;;
        --no-clean)          SKIP_CLEAN=1;      shift ;;
        --no-engine-stage)   SKIP_ENGINE_STAGE=1; shift ;;
        -h|--help)           usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

[[ -z "$INPUT" ]] && { echo "ERROR: -i/--input is required" >&2; usage; exit 1; }
[[ ! -f "$INPUT" ]] && { echo "ERROR: Input file not found: $INPUT" >&2; exit 1; }

INPUT="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"

# Resolve project context BEFORE setting output paths
resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

# Apply config defaults
[[ -z "$GENERATOR" ]]   && GENERATOR="$(config_default generator_3d sf3d)"
[[ -z "$POLYCOUNT" ]]   && POLYCOUNT="$(config_default polycount 3000)"
[[ -z "$TEXTURE_RES" ]] && TEXTURE_RES="$(config_default texture_resolution 2048)"

case "$GENERATOR" in sf3d|trellis) ;; *) echo "ERROR: -g must be sf3d or trellis" >&2; exit 1 ;; esac
case "$UP_AXIS" in y|z) ;; *) echo "ERROR: -u must be y or z" >&2; exit 1 ;; esac

if [[ -z "$OUTPUT_NAME" ]]; then
    OUTPUT_NAME="$(basename "$INPUT" | sed 's/\.[^.]*$//')"
fi

RAW_DIR="$ASSETS_ROOT/raw"
CLEAN_DIR="$ASSETS_ROOT/clean"
mkdir -p "$RAW_DIR" "$CLEAN_DIR"

RAW_PATH="$RAW_DIR/${OUTPUT_NAME}_raw.glb"
CLEAN_PATH="$CLEAN_DIR/${OUTPUT_NAME}_clean.glb"

COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
info()  { printf "${COL_BLUE}[pipeline]${COL_RESET} %s\n" "$1"; }
done_() { printf "${COL_GREEN}[pipeline]${COL_RESET} %s\n" "$1"; }
err()   { printf "${COL_RED}[pipeline]${COL_RESET} %s\n" "$1" >&2; }

START_TS=$(date +%s)
print_context
info "Generator: $GENERATOR"
info "Input:     $INPUT"
info "Raw:       $RAW_PATH"

if [[ "$GENERATOR" == "sf3d" ]]; then
    [[ -d "$SF3D_DIR/.venv" ]] || { err "SF3D venv not found at $SF3D_DIR/.venv"; exit 1; }
    pushd "$SF3D_DIR" > /dev/null
    # shellcheck source=/dev/null
    source .venv/bin/activate

    TMP_OUT="$RAW_DIR/sf3d_tmp_$$"
    rm -rf "$TMP_OUT"

    PYTORCH_ENABLE_MPS_FALLBACK=1 python run.py \
        "$INPUT" \
        --output-dir "$TMP_OUT" \
        --texture-resolution "$TEXTURE_RES" \
        --remesh_option "$REMESH"

    [[ -f "$TMP_OUT/0/mesh.glb" ]] || { err "SF3D did not produce mesh.glb"; exit 1; }
    mv "$TMP_OUT/0/mesh.glb" "$RAW_PATH"
    rm -rf "$TMP_OUT"
    deactivate
    popd > /dev/null

elif [[ "$GENERATOR" == "trellis" ]]; then
    [[ -d "$TRELLIS_DIR/.venv" ]] || { err "TRELLIS.2 venv not found at $TRELLIS_DIR/.venv"; exit 1; }
    pushd "$TRELLIS_DIR" > /dev/null
    # shellcheck source=/dev/null
    source .venv/bin/activate

    TMP_BASE="$RAW_DIR/${OUTPUT_NAME}_trellis_tmp_$$"
    python generate.py "$INPUT" --output "$TMP_BASE"
    [[ -f "${TMP_BASE}.glb" ]] || { err "TRELLIS did not produce ${TMP_BASE}.glb"; exit 1; }
    mv "${TMP_BASE}.glb" "$RAW_PATH"
    [[ -f "${TMP_BASE}.obj" ]] && rm -f "${TMP_BASE}.obj"
    deactivate
    popd > /dev/null
fi

GEN_TS=$(date +%s)
done_ "Generation finished in $((GEN_TS - START_TS))s -> $RAW_PATH"

if [[ $SKIP_CLEAN -eq 1 ]]; then
    info "Skipping cleanup (--no-clean). Final asset: $RAW_PATH"
    exit 0
fi

# Find clean_asset.py — it should be in the same directory as this script
CLEAN_SCRIPT="$SCRIPT_DIR/clean_asset.py"
if [[ ! -f "$CLEAN_SCRIPT" ]]; then
    # Fall back to global workspace
    CLEAN_SCRIPT="$PIPELINE_ROOT/workspace/clean_asset.py"
fi
[[ -f "$CLEAN_SCRIPT" ]] || { err "clean_asset.py not found"; exit 1; }
[[ -x "$BLENDER" ]] || { err "Blender not found at $BLENDER"; exit 1; }

info "Cleaning with Blender (target $POLYCOUNT polys, $UP_AXIS-up)..."
"$BLENDER" --background --python "$CLEAN_SCRIPT" -- \
    "$RAW_PATH" "$CLEAN_PATH" "$POLYCOUNT" "$UP_AXIS"

[[ -f "$CLEAN_PATH" ]] || { err "Cleanup did not produce $CLEAN_PATH"; exit 1; }

# --- Engine staging: copy clean GLB into project's engine folder if applicable ---
ENGINE_STAGED_PATH=""
if [[ "$PROJECT_MODE" == "project" && $SKIP_ENGINE_STAGE -eq 0 ]]; then
    if [[ "$PROJECT_ENGINE" == "unity" || "$PROJECT_ENGINE" == "unreal" || -n "${ENGINE_PATH:-}" ]]; then
        mkdir -p "$ENGINE_PATH"
        ENGINE_STAGED_PATH="$ENGINE_PATH/${OUTPUT_NAME}.glb"
        cp "$CLEAN_PATH" "$ENGINE_STAGED_PATH"
        info "Staged for engine: $ENGINE_STAGED_PATH"
    fi
fi

END_TS=$(date +%s)
done_ "Pipeline complete in $((END_TS - START_TS))s"
done_ "Raw:    $RAW_PATH"
done_ "Clean:  $CLEAN_PATH"
[[ -n "$ENGINE_STAGED_PATH" ]] && done_ "Engine: $ENGINE_STAGED_PATH"
