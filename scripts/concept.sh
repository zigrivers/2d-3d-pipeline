#!/usr/bin/env bash
#
# 2D Concept Art Generator (project-aware)
# Generates a 2D image via mflux (Z-Image Turbo, FLUX schnell, FLUX dev),
# saves it to the project's assets/concept/ — or the global workspace if no
# project context is detected.
#
# Project detection (in order):
#   1. --project PATH flag
#   2. PROJECT_ROOT env var
#   3. .asset-pipeline.json found walking up from $PWD
#   4. Unity / Unreal project markers found walking up from $PWD
#   5. Falls back to ~/3d-pipeline/workspace/
#
# Usage:
#   concept.sh "your prompt here" [options]

set -euo pipefail

# Load the shared project-detection library
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_pipeline_lib.sh"

# --- defaults ---
PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"
MFLUX_VENV="${MFLUX_VENV:-$PIPELINE_ROOT/mflux-env}"

EXPLICIT_PROJECT=""
MODEL=""            # populated from config after context resolution
WIDTH=1024
HEIGHT=1024
STEPS=""
SEED=""
OUTPUT_NAME=""
LORA_PATH=""
LORA_SCALE="1.0"
QUANTIZE=8
COUNT=1
GAME_PROMPT=1
PROMPT=""

GAME_SUFFIX=", 3/4 view, full subject centered, clean white background, even studio lighting, no harsh shadows, game asset, detailed"

usage() {
    cat <<EOF
Usage: $(basename "$0") "PROMPT" [options]

Required:
  PROMPT                   The text prompt (positional, in quotes)

Project context:
  --project PATH           Force a project root (skips auto-detection)
                           Without it, walks up from \$PWD looking for
                           .asset-pipeline.json or Unity/Unreal markers.
                           Falls back to ~/3d-pipeline/workspace/

Generation options:
  -m, --model NAME         z-image-turbo (default) | flux-schnell | flux-dev
  -w, --width N            Width in pixels (default: 1024)
  -H, --height N           Height in pixels (default: 1024)
  -s, --steps N            Inference steps (default per model: 9 / 4 / 30)
  -S, --seed N             Random seed (default: random)
  -o, --output NAME        Output name without extension
  -l, --lora PATH          Path to LoRA .safetensors file (FLUX only)
  -L, --lora-scale F       LoRA strength (default: 1.0)
  -q, --quantize N         Quantization: 4 or 8 (default: 8)
  -n, --count N            Generate N variations (default: 1)
      --no-game-prompt     Skip the game-asset prompt suffix
  -h, --help               This help

Examples:
  # Inside a Unity/Unreal project → auto-routes to project/assets/concept/
  $(basename "$0") "ornate treasure chest"

  # Explicit project, even if you're cd'd elsewhere
  $(basename "$0") "stylized dagger" --project ~/games/grithkin

  # Outside any project → falls back to global workspace
  $(basename "$0") "test render"
EOF
}

# --- parse args ---
if [[ $# -eq 0 ]]; then usage; exit 1; fi

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)         EXPLICIT_PROJECT="$2"; shift 2 ;;
        -m|--model)        MODEL="$2";        shift 2 ;;
        -w|--width)        WIDTH="$2";        shift 2 ;;
        -H|--height)       HEIGHT="$2";       shift 2 ;;
        -s|--steps)        STEPS="$2";        shift 2 ;;
        -S|--seed)         SEED="$2";         shift 2 ;;
        -o|--output)       OUTPUT_NAME="$2";  shift 2 ;;
        -l|--lora)         LORA_PATH="$2";    shift 2 ;;
        -L|--lora-scale)   LORA_SCALE="$2";   shift 2 ;;
        -q|--quantize)     QUANTIZE="$2";     shift 2 ;;
        -n|--count)        COUNT="$2";        shift 2 ;;
        --no-game-prompt)  GAME_PROMPT=0;     shift   ;;
        -h|--help)         usage; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; usage; exit 1 ;;
        *)  if [[ -z "$PROMPT" ]]; then PROMPT="$1"; else PROMPT="$PROMPT $1"; fi; shift ;;
    esac
done

[[ -z "$PROMPT" ]] && { echo "ERROR: prompt is required" >&2; usage; exit 1; }

# --- Resolve project context (sets ASSETS_ROOT, MANIFEST_PATH, etc.) ---
resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

# Apply config defaults that weren't overridden on the command line
[[ -z "$MODEL" ]] && MODEL="$(config_default generator_2d z-image-turbo)"
# Optional LoRA from config (only if user didn't pass one)
if [[ -z "$LORA_PATH" ]]; then
    cfg_lora="$(json_get "$PROJECT_CONFIG" defaults.lora)"
    [[ -n "$cfg_lora" ]] && LORA_PATH="$cfg_lora"
fi

# Validate model
case "$MODEL" in
    z-image-turbo|flux-schnell|flux-dev) ;;
    *) echo "ERROR: model must be z-image-turbo, flux-schnell, or flux-dev" >&2; exit 1 ;;
esac
case "$QUANTIZE" in 4|8) ;; *) echo "ERROR: -q must be 4 or 8" >&2; exit 1 ;; esac
if [[ -n "$LORA_PATH" && "$MODEL" == "z-image-turbo" ]]; then
    echo "WARNING: LoRA support is FLUX-only; ignoring for Z-Image" >&2
    LORA_PATH=""
fi

# Default steps per model
if [[ -z "$STEPS" ]]; then
    case "$MODEL" in
        z-image-turbo) STEPS=9 ;;
        flux-schnell)  STEPS=4 ;;
        flux-dev)      STEPS=30 ;;
    esac
fi

FINAL_PROMPT="$PROMPT"
[[ $GAME_PROMPT -eq 1 ]] && FINAL_PROMPT="${PROMPT}${GAME_SUFFIX}"

# Derive output name from prompt if not provided
if [[ -z "$OUTPUT_NAME" ]]; then
    OUTPUT_NAME="$(echo "$PROMPT" \
        | tr '[:upper:]' '[:lower:]' \
        | sed -E 's/[^a-z0-9]+/_/g' \
        | sed -E 's/^_+|_+$//g' \
        | cut -c1-50)"
fi

CONCEPT_DIR="$ASSETS_ROOT/concept"
mkdir -p "$CONCEPT_DIR"

# Resolve name (applies prefix and collision suffix from config)
OUTPUT_NAME="$(resolve_name "$OUTPUT_NAME" "$CONCEPT_DIR" ".png")"

# --- output helpers ---
COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
info()  { printf "${COL_BLUE}[concept]${COL_RESET} %s\n" "$1"; }
done_() { printf "${COL_GREEN}[concept]${COL_RESET} %s\n" "$1"; }
err()   { printf "${COL_RED}[concept]${COL_RESET} %s\n" "$1" >&2; }

# --- venv check ---
if [[ ! -d "$MFLUX_VENV" ]]; then
    err "mflux venv not found at $MFLUX_VENV"
    err "Run the mflux setup from the setup guide first."
    exit 1
fi

# shellcheck source=/dev/null
source "$MFLUX_VENV/bin/activate"

# --- generate ---
START_TS=$(date +%s)
print_context
info "Model:    $MODEL"
info "Prompt:   $FINAL_PROMPT"
info "Size:     ${WIDTH}x${HEIGHT}"
info "Steps:    $STEPS"
info "Count:    $COUNT"
info "Output:   $CONCEPT_DIR/"
[[ -n "$LORA_PATH" ]] && info "LoRA:     $LORA_PATH (scale $LORA_SCALE)"

for i in $(seq 1 "$COUNT"); do
    if [[ -n "$SEED" ]]; then
        ITER_SEED=$((SEED + i - 1))
    else
        ITER_SEED=$RANDOM$RANDOM
    fi

    if [[ "$COUNT" -gt 1 ]]; then
        OUT_PATH="$CONCEPT_DIR/${OUTPUT_NAME}_v${i}.png"
    else
        OUT_PATH="$CONCEPT_DIR/${OUTPUT_NAME}.png"
    fi

    info "Generating $i/$COUNT (seed=$ITER_SEED) -> $OUT_PATH"

    case "$MODEL" in
        z-image-turbo)
            mflux-generate-z-image-turbo \
                --prompt "$FINAL_PROMPT" \
                --width "$WIDTH" --height "$HEIGHT" \
                --steps "$STEPS" --seed "$ITER_SEED" \
                -q "$QUANTIZE" \
                --output "$OUT_PATH"
            ;;
        flux-schnell|flux-dev)
            FLUX_MODEL="${MODEL#flux-}"
            LORA_ARGS=()
            [[ -n "$LORA_PATH" ]] && LORA_ARGS+=( --lora-paths "$LORA_PATH" --lora-scales "$LORA_SCALE" )
            mflux-generate \
                --prompt "$FINAL_PROMPT" \
                --model "$FLUX_MODEL" \
                --width "$WIDTH" --height "$HEIGHT" \
                --steps "$STEPS" --seed "$ITER_SEED" \
                -q "$QUANTIZE" \
                --output "$OUT_PATH" \
                "${LORA_ARGS[@]}"
            ;;
    esac

    [[ -f "$OUT_PATH" ]] || { err "Generation failed for $OUT_PATH"; deactivate; exit 1; }
done

deactivate

END_TS=$(date +%s)
done_ "Generated $COUNT image(s) in $((END_TS - START_TS))s"

# Print absolute path of first image for chaining (last line of stdout)
if [[ "$COUNT" -gt 1 ]]; then
    echo "$CONCEPT_DIR/${OUTPUT_NAME}_v1.png"
else
    echo "$CONCEPT_DIR/${OUTPUT_NAME}.png"
fi
