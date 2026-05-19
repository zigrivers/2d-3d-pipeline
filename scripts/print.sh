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
        -h|--help)         usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

[[ -z "$INPUT" ]] && { echo "ERROR: -i/--input is required" >&2; usage; exit 1; }
[[ ! -f "$INPUT" ]] && { echo "ERROR: Input file not found: $INPUT" >&2; exit 1; }
[[ "$TARGET_SIZE_MM" =~ ^[0-9]+(\.[0-9]+)?$ ]] || { echo "ERROR: --size must be a positive number" >&2; exit 1; }
awk "BEGIN { exit !($TARGET_SIZE_MM > $U1_BUILD_MAX) }" && { echo "ERROR: --size $TARGET_SIZE_MM mm exceeds Snapmaker U1 build volume ($U1_BUILD_MAX mm)" >&2; exit 1; }

INPUT="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"

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
info()  { printf "${COL_BLUE}[print]${COL_RESET} %s\n" "$1"; }
done_() { printf "${COL_GREEN}[print]${COL_RESET} %s\n" "$1"; }
warn()  { printf "${COL_YELLOW}[print]${COL_RESET} %s\n" "$1"; }

if awk "BEGIN { exit !($TARGET_SIZE_MM > $U1_BUILD_WARN) }"; then
    warn "Target ${TARGET_SIZE_MM}mm is close to U1 build limit. If the model is wider than tall, it may not fit."
fi

START_TS=$(date +%s)
print_context
info "Input:    $INPUT"
info "Output:   $OUTPUT_PATH"
info "Size:     ${TARGET_SIZE_MM} mm"

"$BLENDER" --background --python "$PREPARE_SCRIPT" -- \
    "$INPUT" "$OUTPUT_PATH" "$TARGET_SIZE_MM" "$ORIENTATION"

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
SIZE_MB=$(awk "BEGIN { printf \"%.1f\", $(stat -f%z "$OUTPUT_PATH" 2>/dev/null || stat -c%s "$OUTPUT_PATH") / 1048576 }")
done_ "Print-ready in $((END_TS - START_TS))s"
done_ "STL: $OUTPUT_PATH (${SIZE_MB} MB)"
done_ ""
done_ "Next: open in Snapmaker Orca, paint colors, slice, print."

echo "$OUTPUT_PATH"
