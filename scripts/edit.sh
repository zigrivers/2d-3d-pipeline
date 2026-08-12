#!/usr/bin/env bash
#
# Instruction-based image editing + parametric camera-angle views
# (item 21 of the 2026-08 generation-quality refresh).
#
# Two modes, mutually exclusive:
#   edit.sh -i concept/chest.png "make the wood darker"
#       -> concept/chest_edit1.png (Qwen-Image-Edit-2511, Apache 2.0)
#   edit.sh -i concept/chest.png --angle 90,0
#       -> concept/chest_090deg.png (+ the official Multiple-Angles
#          LoRA, gate G3: commercial_safe, Apache 2.0)
#
# Both write into the same project/global concept/ dir concept.sh uses,
# so angle outputs are ready to feed multiview.sh directly.
#
# Project detection: same as concept.sh (--project, PROJECT_ROOT env,
# .asset-pipeline.json, Unity/Unreal markers, global workspace fallback).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_pipeline_lib.sh"

PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"
MFLUX_VENV="${MFLUX_VENV:-$PIPELINE_ROOT/mflux-env}"
# Explicit, not mflux's own default: mflux-generate-qwen-edit defaults to
# Qwen-Image-Edit-2509 (confirmed live), not 2511. The spec calls for 2511
# specifically, and the Multiple-Angles LoRA below is trained against
# 2511's architecture — passing a raw HF repo string overrides mflux's
# built-in --model enum, which has no 2511-specific entry.
QWEN_EDIT_MODEL="${QWEN_EDIT_MODEL:-Qwen/Qwen-Image-Edit-2511}"
ANGLE_LORA="${ANGLE_LORA:-fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA}"
ANGLE_LORA_SCALE="${ANGLE_LORA_SCALE:-0.9}"

EXPLICIT_PROJECT=""
INPUT=""
INSTRUCTION=""
ANGLE=""
OUTPUT_NAME=""
SEED=""
QUANTIZE=8
NO_DRIFT_CHECK=0
JSON_MODE=0

usage() {
    cat <<EOF
Usage: $(basename "$0") -i IMAGE "instruction" [options]
       $(basename "$0") -i IMAGE --angle H,V [options]

Required:
  -i, --input PATH         Source image to edit (an existing concept)

One of these (not both):
  INSTRUCTION               Positional text instruction, e.g.
                            "make the wood darker"
  --angle H,V               Camera-angle view via the Multiple-Angles
                            LoRA. H is azimuth in degrees (0=front,
                            90=right, 180=back, 270=left — snapped to
                            the nearest 45°). V is elevation in degrees
                            (-30, 0, 30, or 60 — snapped to nearest).

Project context:
  --project PATH            Force a project root (skips auto-detection)

Generation options:
  -o, --output NAME         Output base name (default: derived from input)
  -S, --seed N               Random seed (default: random)
  -q, --quantize N           Quantization: 4 or 8 (default: 8)
      --no-drift-check       Skip the DreamSim source-vs-result check
      --json                 Emit a final JSON result line on stdout
  -h, --help                 This help

License: Qwen-Image-Edit-2511 and the Multiple-Angles LoRA are both
commercial_safe (Apache 2.0; LoRA verified at gate G3).

Examples:
  edit.sh -i concept/chest.png "make the wood darker"
  edit.sh -i concept/chest.png --angle 90,0
  edit.sh -i concept/chest.png --angle 180,30 -o chest_hero
EOF
}

if [[ $# -eq 0 ]]; then usage; exit 1; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)         EXPLICIT_PROJECT="$2"; shift 2 ;;
        -i|--input)        INPUT="$2";        shift 2 ;;
        --angle)           ANGLE="$2";        shift 2 ;;
        -o|--output)       OUTPUT_NAME="$2";  shift 2 ;;
        -S|--seed)         SEED="$2";         shift 2 ;;
        -q|--quantize)     QUANTIZE="$2";     shift 2 ;;
        --no-drift-check)  NO_DRIFT_CHECK=1;  shift   ;;
        --json)            JSON_MODE=1;       shift   ;;
        -h|--help)         usage; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; usage; exit 1 ;;
        *)  if [[ -z "$INSTRUCTION" ]]; then INSTRUCTION="$1"; else INSTRUCTION="$INSTRUCTION $1"; fi; shift ;;
    esac
done

[[ -z "$INPUT" ]] && { echo "ERROR: -i/--input is required" >&2; usage; exit 1; }
[[ -f "$INPUT" ]] || { echo "ERROR: input file not found: $INPUT" >&2; exit 1; }
if [[ -n "$INSTRUCTION" && -n "$ANGLE" ]]; then
    echo "ERROR: pass an instruction OR --angle, not both" >&2; exit 1
fi
if [[ -z "$INSTRUCTION" && -z "$ANGLE" ]]; then
    echo "ERROR: provide an instruction (positional) or --angle H,V" >&2; usage; exit 1
fi
case "$QUANTIZE" in 4|8) ;; *) echo "ERROR: -q must be 4 or 8" >&2; exit 1 ;; esac

INPUT="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"

COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
HUMAN_FD=1
[[ "$JSON_MODE" == "1" ]] && HUMAN_FD=2
info()  { printf "${COL_BLUE}[edit]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
done_() { printf "${COL_GREEN}[edit]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
err()   { printf "${COL_RED}[edit]${COL_RESET} %s\n" "$1" >&2; }

[[ "$JSON_MODE" == "1" ]] && json_mode_begin

resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

if [[ ! -d "$MFLUX_VENV" ]]; then
    err "mflux venv not found at $MFLUX_VENV"
    err "Run the mflux setup from the setup guide first."
    exit 1
fi

if [[ -z "$OUTPUT_NAME" ]]; then
    OUTPUT_NAME="$(basename "$INPUT" | sed 's/\.[^.]*$//')"
fi

CONCEPT_DIR="$ASSETS_ROOT/concept"
mkdir -p "$CONCEPT_DIR"

START_TS=$(date +%s)
CREATED_AT="$(iso_now)"
MACHINE="$(hostname_safe)"
HW_TIER="$(hardware_tier)"
LICENSE_BUCKET="$(license_bucket_for_model qwen-image-edit)"

ITER_SEED="$SEED"
[[ -z "$ITER_SEED" ]] && ITER_SEED=$RANDOM$RANDOM

GENERATION_EXTRA=""

if [[ -n "$ANGLE" ]]; then
    IFS=',' read -r RAW_H RAW_V <<< "$ANGLE"
    [[ -n "$RAW_H" && -n "$RAW_V" ]] || { err "--angle needs H,V (e.g. --angle 90,0)"; exit 1; }

    # Snap the requested angle to the LoRA's real 8-azimuth x 4-elevation
    # grid (see docs/model-review-trellis2.md-style evidence trail — this
    # mapping was read directly from the LoRA's model card, not guessed)
    # and build its exact required prompt: "<sks> [azimuth] [elevation]
    # [distance]".
    ANGLE_INFO="$(python3 -c "
import sys
h = float(sys.argv[1]) % 360
v = float(sys.argv[2])

azimuths = [0, 45, 90, 135, 180, 225, 270, 315]
azimuth_desc = {
    0: 'front view', 45: 'front-right quarter view', 90: 'right side view',
    135: 'back-right quarter view', 180: 'back view', 225: 'back-left quarter view',
    270: 'left side view', 315: 'front-left quarter view',
}
elevations = [-30, 0, 30, 60]
elevation_desc = {
    -30: 'low-angle shot', 0: 'eye-level shot', 30: 'elevated shot', 60: 'high-angle shot',
}

snapped_h = min(azimuths, key=lambda a: min(abs(a - h), abs(a - h + 360), abs(a - h - 360)))
snapped_v = min(elevations, key=lambda e: abs(e - v))

prompt = f'<sks> {azimuth_desc[snapped_h]} {elevation_desc[snapped_v]} medium shot'
print(snapped_h)
print(snapped_v)
print(prompt)
" "$RAW_H" "$RAW_V")"
    SNAPPED_H="$(echo "$ANGLE_INFO" | sed -n '1p')"
    SNAPPED_V="$(echo "$ANGLE_INFO" | sed -n '2p')"
    LORA_PROMPT="$(echo "$ANGLE_INFO" | sed -n '3p')"

    ELEV_SUFFIX=""
    [[ "$SNAPPED_V" != "0" ]] && ELEV_SUFFIX="_ev${SNAPPED_V}"
    OUT_PATH="$CONCEPT_DIR/${OUTPUT_NAME}_$(printf '%03d' "$SNAPPED_H")deg${ELEV_SUFFIX}.png"

    info "Mode:     angle view (requested ${RAW_H},${RAW_V} -> snapped ${SNAPPED_H},${SNAPPED_V})"
    info "Prompt:   $LORA_PROMPT"
    info "Tier:     $HW_TIER  (machine: $MACHINE)"
    info "Output:   $OUT_PATH"

    source "$MFLUX_VENV/bin/activate"
    LORA_LOG="$(mktemp)"
    mflux-generate-qwen-edit \
        --model "$QWEN_EDIT_MODEL" \
        --image-paths "$INPUT" \
        --prompt "$LORA_PROMPT" \
        --lora "$ANGLE_LORA" "$ANGLE_LORA_SCALE" \
        --seed "$ITER_SEED" \
        -q "$QUANTIZE" \
        --output "$OUT_PATH" 2>&1 | tee "$LORA_LOG"
    deactivate

    # mflux prints "Applied to N layers (M/K keys matched)" for each LoRA it
    # loads, then a blanket "All LoRA weights applied successfully" even when
    # N/M are 0 — that second line is not trustworthy on its own. Known
    # mflux/Qwen-Image-Edit-2511 LoRA key-naming gap (see
    # https://github.com/filipstrand/mflux/issues/298); the angle LoRA's
    # diffusers-style "transformer_blocks.N.attn.*.lora_A/B" keys currently
    # don't match mflux's internal names, so it silently applies zero weight.
    LORA_MATCH_LINE="$(grep -oE 'Applied to [0-9]+ layers \([0-9]+/[0-9]+ keys matched\)' "$LORA_LOG" | tail -1 || true)"
    rm -f "$LORA_LOG"
    LORA_APPLIED=true
    [[ "$LORA_MATCH_LINE" == "Applied to 0 layers"* ]] && LORA_APPLIED=false

    if [[ "$LORA_APPLIED" == "false" ]]; then
        err "WARNING: the Multiple-Angles LoRA did not apply ($LORA_MATCH_LINE)."
        err "This is a known mflux/Qwen-Image-Edit-2511 LoRA compatibility gap"
        err "(github.com/filipstrand/mflux/issues/298), not a bug in this script."
        err "The image below was still generated, but it does NOT show the"
        err "requested camera angle -- treat --angle as non-functional until"
        err "mflux adds key remapping for this LoRA's diffusers-style naming."
    fi

    GENERATION_EXTRA="\"angle_azimuth_deg\": $SNAPPED_H, \"angle_elevation_deg\": $SNAPPED_V, \"angle_lora_applied\": $LORA_APPLIED"
else
    N=1
    OUT_PATH="$CONCEPT_DIR/${OUTPUT_NAME}_edit${N}.png"
    while [[ -f "$OUT_PATH" ]]; do
        N=$((N + 1))
        OUT_PATH="$CONCEPT_DIR/${OUTPUT_NAME}_edit${N}.png"
    done

    info "Mode:     instruction edit"
    info "Instruction: $INSTRUCTION"
    info "Tier:     $HW_TIER  (machine: $MACHINE)"
    info "Output:   $OUT_PATH"

    source "$MFLUX_VENV/bin/activate"
    mflux-generate-qwen-edit \
        --model "$QWEN_EDIT_MODEL" \
        --image-paths "$INPUT" \
        --prompt "$INSTRUCTION" \
        --seed "$ITER_SEED" \
        -q "$QUANTIZE" \
        --output "$OUT_PATH"
    deactivate

    ESCAPED_INSTRUCTION="$(python3 -c "import json,sys; print(json.dumps(sys.argv[1]))" "$INSTRUCTION")"
    GENERATION_EXTRA="\"edit_instruction\": $ESCAPED_INSTRUCTION"
fi

[[ -f "$OUT_PATH" ]] || { err "Edit did not produce $OUT_PATH"; exit 1; }

END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))
done_ "Generated in ${DURATION}s -> $OUT_PATH"

META_PATH="${OUT_PATH}.meta.json"
META_HELPER_SCRIPT="$SCRIPT_DIR/meta_helper.py"
[[ -f "$META_HELPER_SCRIPT" ]] || META_HELPER_SCRIPT="$PIPELINE_ROOT/workspace/meta_helper.py"
PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
if [[ -f "$META_HELPER_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
    "$PIPELINE_TOOLS_ENV/bin/python" "$META_HELPER_SCRIPT" merge "$META_PATH" \
        --section generation \
        --data "{\"backend\": \"qwen-image-edit\", \"model_role\": \"edit\", \"license_bucket\": \"$LICENSE_BUCKET\", \"inputs\": [{\"path\": \"$INPUT\"}], $GENERATION_EXTRA, \"duration_seconds\": $DURATION}" \
        > /dev/null 2>&1 || true
fi

# Item 21 — DreamSim drift check (item 16 infra): flags an edit that had
# no visible effect, or one that drifted too far from the source subject.
DRIFT_SCRIPT="$SCRIPT_DIR/edit_drift_check.py"
[[ -f "$DRIFT_SCRIPT" ]] || DRIFT_SCRIPT="$PIPELINE_ROOT/workspace/edit_drift_check.py"
if [[ "$NO_DRIFT_CHECK" != "1" && -f "$DRIFT_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
    "$PIPELINE_TOOLS_ENV/bin/python" "$DRIFT_SCRIPT" \
        --source "$INPUT" --edited "$OUT_PATH" --meta "$META_PATH" 2>&1 \
        | grep '^\[dreamsim\]' | { while IFS= read -r line; do printf "[edit] %s\n" "${line#\[dreamsim\] }" >&"$HUMAN_FD"; done; } || true
fi

if [[ "$JSON_MODE" == "1" ]]; then
    json_mode_end
    python3 "$SCRIPT_DIR/json_emit.py" \
        status=ok \
        stage=edit \
        input="$INPUT" \
        output="$OUT_PATH" \
        license_bucket="$LICENSE_BUCKET" \
        --int seed="$ITER_SEED" \
        --int duration_seconds="$DURATION" \
        assets_root="$ASSETS_ROOT" \
        project_mode="$PROJECT_MODE" \
        project_root="$PROJECT_ROOT" \
        machine="$MACHINE" \
        hardware_tier="$HW_TIER" \
        created="$CREATED_AT"
fi
