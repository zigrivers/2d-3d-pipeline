#!/usr/bin/env bash
#
# 3D Print Preparation Wrapper (project-aware)
# Converts a clean GLB into a Snapmaker U1-ready STL.
# Reads from and writes to the project's assets/print/ when in project
# context, or the global workspace otherwise.
#
# Snapmaker U1 build volume: 270 x 270 x 270 mm

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_pipeline_lib.sh"

PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"

U1_BUILD_MAX=270
U1_BUILD_WARN=250

EXPLICIT_PROJECT=""
INPUT=""
OUTPUT_NAME=""
TARGET_SIZE_MM=50
ORIENTATION="auto"
COPY_COLOR_REF=1
JSON_MODE=0
ALLOW_OVERSIZE=0

usage() {
    cat <<EOF
Usage: $(basename "$0") -i CLEAN_GLB [options]

Required:
  -i, --input PATH         Input clean GLB (from generate.sh)

Project context:
  --project PATH           Force a project root (skips auto-detection)

Options:
  -o, --output NAME        Output name (default: derived from input)
  -s, --size MM            Longest dimension in millimeters (default: 50)
                           Snapmaker U1 max: 270 mm
                           Common sizes: 25 (small), 50 (figure), 100 (large),
                           200 (display)
      --no-color-ref       Don't copy the concept image alongside the STL
      --allow-oversize     Continue even if final dimensions exceed 270 mm on
                           any axis (Phase 4 — full enforcement)
      --json               Emit a final JSON result line on stdout. Human
                           logs are routed to stderr.
  -h, --help               This help

Examples:
  # In a project context — reads from project's clean/, writes to print/
  $(basename "$0") -i assets/clean/chest_clean.glb

  # Outside any project — uses global workspace
  $(basename "$0") -i ~/3d-pipeline/workspace/clean/dragon_clean.glb -s 150
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)         EXPLICIT_PROJECT="$2"; shift 2 ;;
        -i|--input)        INPUT="$2";          shift 2 ;;
        -o|--output)       OUTPUT_NAME="$2";    shift 2 ;;
        -s|--size)         TARGET_SIZE_MM="$2"; shift 2 ;;
        --no-color-ref)    COPY_COLOR_REF=0;    shift   ;;
        --allow-oversize)  ALLOW_OVERSIZE=1;    shift   ;;
        --json)            JSON_MODE=1;         shift   ;;
        -h|--help)         usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

[[ -z "$INPUT" ]] && { echo "ERROR: -i/--input is required" >&2; usage; exit 1; }
[[ ! -f "$INPUT" ]] && { echo "ERROR: Input file not found: $INPUT" >&2; exit 1; }
[[ "$TARGET_SIZE_MM" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "ERROR: --size must be a positive number" >&2; exit 1; }
awk "BEGIN { exit !($TARGET_SIZE_MM > $U1_BUILD_MAX) }" && { echo "ERROR: --size $TARGET_SIZE_MM mm exceeds Snapmaker U1 build volume ($U1_BUILD_MAX mm)" >&2; exit 1; }

INPUT="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"

# STL is the supported (and only) print format by design. The Snapmaker U1's
# multi-color capability comes from Orca's paint tool, not from mesh data, so
# 3MF would add format complexity without unlocking new capability. If a
# future printer ever needs 3MF, add the export here.

# Under --json, route subcommand stdout (Blender) to stderr.
[[ "$JSON_MODE" == "1" ]] && json_mode_begin

# Resolve project context (sets ASSETS_ROOT)
resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

if [[ -z "$OUTPUT_NAME" ]]; then
    BASE="$(basename "$INPUT")"
    OUTPUT_NAME="${BASE%_clean.glb}"
    OUTPUT_NAME="${OUTPUT_NAME%.glb}"
fi

PRINT_DIR="$ASSETS_ROOT/print"
mkdir -p "$PRINT_DIR"
OUTPUT_PATH="$PRINT_DIR/${OUTPUT_NAME}.stl"

PREPARE_SCRIPT="$SCRIPT_DIR/prepare_for_print.py"
if [[ ! -f "$PREPARE_SCRIPT" ]]; then
    PREPARE_SCRIPT="$PIPELINE_ROOT/workspace/prepare_for_print.py"
fi
[[ -f "$PREPARE_SCRIPT" ]] || { echo "ERROR: prepare_for_print.py not found" >&2; exit 1; }
[[ -x "$BLENDER" ]] || { echo "ERROR: Blender not found at $BLENDER" >&2; exit 1; }

COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_YELLOW='\033[0;33m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
HUMAN_FD=1
[[ "$JSON_MODE" == "1" ]] && HUMAN_FD=2
info()  { printf "${COL_BLUE}[print]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
done_() { printf "${COL_GREEN}[print]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
warn()  { printf "${COL_YELLOW}[print]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }

if awk "BEGIN { exit !($TARGET_SIZE_MM > $U1_BUILD_WARN) }"; then
    warn "Target ${TARGET_SIZE_MM}mm is close to U1 build limit. If the model is wider than tall, it may not fit."
fi

START_TS=$(date +%s)
CREATED_AT="$(iso_now)"
MACHINE="$(hostname_safe)"
HW_TIER="$(hardware_tier)"

if [[ "$JSON_MODE" == "1" ]]; then
    print_context >&2
else
    print_context
fi
info "Tier:     $HW_TIER  (machine: $MACHINE)"
info "Input:    $INPUT"
info "Output:   $OUTPUT_PATH"
info "Size:     ${TARGET_SIZE_MM} mm"

ALLOW_OVERSIZE_FLAG="false"
[[ $ALLOW_OVERSIZE -eq 1 ]] && ALLOW_OVERSIZE_FLAG="true"

# prepare_for_print.py exit codes:
#   0  success (may or may not fit; if fits=false then --allow-oversize was set)
#   3  oversize and --allow-oversize NOT set (no STL produced)
#   non-zero otherwise: real failure (Blender crash, mesh issue)
set +e
"$BLENDER" --background --python "$PREPARE_SCRIPT" -- \
    "$INPUT" "$OUTPUT_PATH" "$TARGET_SIZE_MM" "$ORIENTATION" "$ALLOW_OVERSIZE_FLAG"
BLENDER_EXIT=$?
set -e

if [[ $BLENDER_EXIT -eq 3 ]]; then
    echo "ERROR: STL would exceed Snapmaker U1 build volume on at least one axis." >&2
    echo "       Re-run with --allow-oversize to write it anyway, or lower --size." >&2
    META="${OUTPUT_PATH}.print_meta.json"
    if [[ "$JSON_MODE" == "1" && -f "$META" ]]; then
        # Emit a structured error so consumers can react.
        json_mode_end
        DIMS_JSON=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(json.dumps(m["final_dimensions_mm"]))' "$META")
        OVER_JSON=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(json.dumps(m["oversized_axes"]))' "$META")
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=error \
            stage=glb_to_print \
            error=oversize \
            input="$INPUT" \
            stl_path="" \
            format=stl \
            --float target_size_mm="$TARGET_SIZE_MM" \
            --object final_dimensions_mm="$DIMS_JSON" \
            --bool fits_snapmaker_u1=false \
            --array oversized_axes="$OVER_JSON" \
            color_ref_path="" \
            assets_root="$ASSETS_ROOT" \
            manifest_path="$MANIFEST_PATH" \
            project_mode="$PROJECT_MODE" \
            machine="$MACHINE" \
            hardware_tier="$HW_TIER" \
            created="$CREATED_AT"
    fi
    exit 3
fi

if [[ $BLENDER_EXIT -ne 0 ]]; then
    echo "ERROR: Blender exited $BLENDER_EXIT" >&2
    exit $BLENDER_EXIT
fi

[[ -f "$OUTPUT_PATH" ]] || { echo "ERROR: Blender did not produce $OUTPUT_PATH" >&2; exit 1; }

# Copy color reference image alongside the STL
if [[ $COPY_COLOR_REF -eq 1 ]]; then
    CONCEPT_NAME="$(basename "$INPUT")"
    CONCEPT_NAME="${CONCEPT_NAME%_clean.glb}"
    CONCEPT_NAME="${CONCEPT_NAME%.glb}"
    for ext in png jpg jpeg; do
        CANDIDATE="$ASSETS_ROOT/concept/${CONCEPT_NAME}.${ext}"
        if [[ -f "$CANDIDATE" ]]; then
            cp "$CANDIDATE" "$PRINT_DIR/${OUTPUT_NAME}_color_ref.${ext}"
            info "Color reference: $PRINT_DIR/${OUTPUT_NAME}_color_ref.${ext}"
            break
        fi
    done
fi

END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))
SIZE_MB=$(awk "BEGIN { printf \"%.1f\", $(stat -f%z "$OUTPUT_PATH" 2>/dev/null || stat -c%s "$OUTPUT_PATH") / 1048576 }")
done_ "Print-ready in ${DURATION}s"
done_ "STL: $OUTPUT_PATH (${SIZE_MB} MB)"
done_ ""
done_ "Next: open in Snapmaker Orca, paint colors, slice, print."

# Resolve the final color reference path for the JSON emission (might be "").
COLOR_REF_PATH=""
if [[ $COPY_COLOR_REF -eq 1 ]]; then
    for ext in png jpg jpeg; do
        c="$PRINT_DIR/${OUTPUT_NAME}_color_ref.${ext}"
        if [[ -f "$c" ]]; then COLOR_REF_PATH="$c"; break; fi
    done
fi

if [[ "$JSON_MODE" == "1" ]]; then
    # Read the sidecar JSON that prepare_for_print.py just wrote.
    META="${OUTPUT_PATH}.print_meta.json"
    if [[ -f "$META" ]]; then
        DIMS_JSON=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(json.dumps(m.get("final_dimensions_mm", {})))' "$META")
        FITS=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print("true" if m.get("fits_snapmaker_u1") else "false")' "$META")
        OVER_JSON=$(python3 -c 'import json,sys; m=json.load(open(sys.argv[1])); print(json.dumps(m.get("oversized_axes", [])))' "$META")
    else
        # Should not happen — but fall back to honest defaults.
        DIMS_JSON='{"x":0.0,"y":0.0,"z":0.0}'
        FITS=true
        OVER_JSON='[]'
    fi
    json_mode_end
    python3 "$SCRIPT_DIR/json_emit.py" \
        status=ok \
        stage=glb_to_print \
        input="$INPUT" \
        stl_path="$OUTPUT_PATH" \
        format=stl \
        --float target_size_mm="$TARGET_SIZE_MM" \
        --object final_dimensions_mm="$DIMS_JSON" \
        --bool fits_snapmaker_u1="$FITS" \
        --array oversized_axes="$OVER_JSON" \
        color_ref_path="$COLOR_REF_PATH" \
        assets_root="$ASSETS_ROOT" \
        manifest_path="$MANIFEST_PATH" \
        project_mode="$PROJECT_MODE" \
        --int duration_seconds="$DURATION" \
        machine="$MACHINE" \
        hardware_tier="$HW_TIER" \
        created="$CREATED_AT"
else
    echo "$OUTPUT_PATH"
fi
