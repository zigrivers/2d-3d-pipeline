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
JSON_MODE=0
BACKEND="mflux"
CONSISTENCY_PACK=""
NEGATIVE=""
JUDGE=0
BEST_OF=""

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
  -m, --model NAME         z-image-turbo (default) | flux-schnell | flux-dev |
                           flux2-klein | ernie-image
                           flux2-klein (item 20): Apache 2.0, FLUX-ecosystem
                           LoRA + built-in instruction editing in one
                           checkpoint. ernie-image (item 20): Apache 2.0,
                           strongest-at-release open t2i for prompt
                           adherence. Both commercial_safe.
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
      --json               Emit a final JSON result line on stdout.
                           Human-readable logs are routed to stderr so
                           stdout contains only the JSON object.
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
        --backend)         BACKEND="$2";      shift 2 ;;
        --consistency-pack) CONSISTENCY_PACK="$2"; shift 2 ;;
        --negative)        NEGATIVE="$2";     shift 2 ;;
        --judge)           JUDGE=1;           shift   ;;
        --best-of)         BEST_OF="$2"; JUDGE=1; COUNT="$2"; shift 2 ;;
        --json)            JSON_MODE=1;       shift   ;;
        -h|--help)         usage; exit 0 ;;
        -*) echo "Unknown option: $1" >&2; usage; exit 1 ;;
        *)  if [[ -z "$PROMPT" ]]; then PROMPT="$1"; else PROMPT="$PROMPT $1"; fi; shift ;;
    esac
done

[[ -z "$PROMPT" ]] && { echo "ERROR: prompt is required" >&2; usage; exit 1; }

# Validate backend choice
case "$BACKEND" in
    mflux) ;;
    comfyui)
        [[ -n "$CONSISTENCY_PACK" ]] || { echo "ERROR: --backend comfyui requires --consistency-pack PATH" >&2; exit 1; }
        [[ -d "$CONSISTENCY_PACK" ]] || { echo "ERROR: --consistency-pack not a directory: $CONSISTENCY_PACK" >&2; exit 1; }
        ;;
    *)
        echo "ERROR: --backend must be mflux (default) or comfyui (got: $BACKEND)" >&2
        exit 1 ;;
esac

# Under --json, route all stdout (including subcommand output) to stderr;
# real stdout is preserved for the final JSON line via json_mode_end.
[[ "$JSON_MODE" == "1" ]] && json_mode_begin

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
    z-image-turbo|flux-schnell|flux-dev|flux2-klein|ernie-image) ;;
    *) echo "ERROR: model must be z-image-turbo, flux-schnell, flux-dev, flux2-klein, or ernie-image" >&2; exit 1 ;;
esac
case "$QUANTIZE" in 4|8) ;; *) echo "ERROR: -q must be 4 or 8" >&2; exit 1 ;; esac
if [[ -n "$LORA_PATH" ]]; then
    case "$MODEL" in
        z-image-turbo)
            echo "WARNING: LoRA support is FLUX-only; ignoring for Z-Image" >&2
            LORA_PATH=""
            ;;
        flux2-klein|ernie-image)
            # Item 20/21: FLUX.1 LoRAs (trained for flux-schnell/flux-dev)
            # are a different checkpoint architecture than FLUX.2 klein or
            # ERNIE-Image — loading one against the wrong model family
            # fails deep inside mflux with a confusing tensor-shape error,
            # or silently degrades output. Fail fast with a clear message
            # instead of forwarding the mismatch.
            echo "ERROR: --lora points at a FLUX.1-era LoRA path, but -m $MODEL is a" >&2
            echo "       different model family. FLUX.1 LoRAs (trained for flux-schnell" >&2
            echo "       or flux-dev) are not compatible with $MODEL. Pick a LoRA trained" >&2
            echo "       for $MODEL, or switch to -m flux-dev." >&2
            exit 1
            ;;
    esac
fi

# Default steps per model
if [[ -z "$STEPS" ]]; then
    case "$MODEL" in
        z-image-turbo) STEPS=9 ;;
        flux-schnell)  STEPS=4 ;;
        flux-dev)      STEPS=30 ;;
        flux2-klein)   STEPS=20 ;;
        ernie-image)   STEPS=20 ;;
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
# Under --json, human-readable lines go to stderr so stdout carries only
# the final JSON object. err is always on stderr.
COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
HUMAN_FD=1
[[ "$JSON_MODE" == "1" ]] && HUMAN_FD=2
info()  { printf "${COL_BLUE}[concept]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
done_() { printf "${COL_GREEN}[concept]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
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
CREATED_AT="$(iso_now)"
MACHINE="$(hostname_safe)"
HW_TIER="$(hardware_tier)"
LICENSE_BUCKET="$(license_bucket_for_model "$MODEL")"

# Non-commercial models: warn (but don't block — spec says proceed)
warn_if_non_commercial "$MODEL"

# Redirect print_context output through HUMAN_FD when --json is on. The
# function writes via printf to stdout, so we wrap it.
if [[ "$JSON_MODE" == "1" ]]; then
    print_context >&2
else
    print_context
fi
info "Model:    $MODEL  (license: $LICENSE_BUCKET)"
info "Tier:     $HW_TIER  (machine: $MACHINE)"
info "Prompt:   $FINAL_PROMPT"
info "Size:     ${WIDTH}x${HEIGHT}"
info "Steps:    $STEPS"
info "Count:    $COUNT"
info "Output:   $CONCEPT_DIR/"
[[ -n "$LORA_PATH" ]] && info "LoRA:     $LORA_PATH (scale $LORA_SCALE)"

# Track every produced output (used for the --json result and chaining).
OUTPUT_PATHS=()
FIRST_SEED=""

for i in $(seq 1 "$COUNT"); do
    if [[ -n "$SEED" ]]; then
        ITER_SEED=$((SEED + i - 1))
    else
        ITER_SEED=$RANDOM$RANDOM
    fi
    [[ -z "$FIRST_SEED" ]] && FIRST_SEED="$ITER_SEED"

    if [[ "$COUNT" -gt 1 ]]; then
        OUT_PATH="$CONCEPT_DIR/${OUTPUT_NAME}_v${i}.png"
    else
        OUT_PATH="$CONCEPT_DIR/${OUTPUT_NAME}.png"
    fi
    OUTPUT_PATHS+=( "$OUT_PATH" )

    info "Generating $i/$COUNT (seed=$ITER_SEED, backend=$BACKEND) -> $OUT_PATH"

    if [[ "$BACKEND" == "comfyui" ]]; then
        # ComfyUI consistency mode (item 11 / P3.2). Dispatch through the
        # consistency-pack + workflow. License bucket is derived from the
        # pack manifest by the dispatcher.
        PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
        DISPATCH="$SCRIPT_DIR/comfyui_dispatch.py"
        [[ -f "$DISPATCH" ]] || DISPATCH="$PIPELINE_ROOT/workspace/comfyui_dispatch.py"
        if [[ ! -f "$DISPATCH" || ! -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
            err "comfyui_dispatch.py or pipeline-tools-env missing — install both first"
            exit 1
        fi
        "$PIPELINE_TOOLS_ENV/bin/python" "$DISPATCH" \
            --pack "$CONSISTENCY_PACK" \
            --prompt "$FINAL_PROMPT" \
            --negative "$NEGATIVE" \
            --output "$OUT_PATH" \
            --seed "$ITER_SEED" \
            --steps "$STEPS" \
            --width "$WIDTH" --height "$HEIGHT" \
            --json > /tmp/comfyui-result-$$.json || {
            err "ComfyUI dispatch failed"
            cat /tmp/comfyui-result-$$.json >&2 2>/dev/null || true
            rm -f /tmp/comfyui-result-$$.json
            exit 1
        }
        # Override LICENSE_BUCKET from the dispatcher's result (it knows
        # the pack's actual bucket and resolves against the base model).
        DISPATCH_BUCKET="$(python3 -c "import json,sys; d=json.load(open('/tmp/comfyui-result-$$.json')); print(d.get('license_bucket', ''))" 2>/dev/null || echo "")"
        [[ -n "$DISPATCH_BUCKET" ]] && LICENSE_BUCKET="$DISPATCH_BUCKET"
        rm -f /tmp/comfyui-result-$$.json
    else
        # Default backend: mflux
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
            flux2-klein)
                # Item 20. flux2-klein-4b is the Apache 2.0 exception in the
                # FLUX.2 family (klein 9B/dev are BFL non-commercial) — do
                # not change this to a 9B variant without a license re-check.
                # mflux-generate itself refuses FLUX.2 Klein ("Use
                # mflux-generate-flux2 instead") — confirmed live.
                mflux-generate-flux2 \
                    --prompt "$FINAL_PROMPT" \
                    --model flux2-klein-4b \
                    --width "$WIDTH" --height "$HEIGHT" \
                    --steps "$STEPS" --seed "$ITER_SEED" \
                    -q "$QUANTIZE" \
                    --output "$OUT_PATH"
                ;;
            ernie-image)
                mflux-generate \
                    --prompt "$FINAL_PROMPT" \
                    --model ernie-image \
                    --width "$WIDTH" --height "$HEIGHT" \
                    --steps "$STEPS" --seed "$ITER_SEED" \
                    -q "$QUANTIZE" \
                    --output "$OUT_PATH"
                ;;
        esac
    fi

    [[ -f "$OUT_PATH" ]] || { err "Generation failed for $OUT_PATH"; deactivate; exit 1; }
done

deactivate

END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))
done_ "Generated $COUNT image(s) in ${DURATION}s"

FIRST_OUTPUT="${OUTPUT_PATHS[0]}"

# v0.3 — CLIP variant ranking / per-model soft signal. No-op when
# pipeline-tools-env or clip_score.py isn't installed.
PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
CLIP_SCRIPT="$SCRIPT_DIR/clip_score.py"
[[ -f "$CLIP_SCRIPT" ]] || CLIP_SCRIPT="$PIPELINE_ROOT/workspace/clip_score.py"
if [[ -f "$CLIP_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
    META_FOR_CONCEPT="${FIRST_OUTPUT}.meta.json"
    if [[ "$COUNT" -gt 1 ]]; then
        # Rank variants
        "$PIPELINE_TOOLS_ENV/bin/python" "$CLIP_SCRIPT" \
            --prompt "$PROMPT" --images "${OUTPUT_PATHS[@]}" \
            --meta "$META_FOR_CONCEPT" --model-name "$MODEL" --rank 2>&1 \
            | grep '^\[clip\]' | { while IFS= read -r line; do printf "[concept] %s\n" "${line#\[clip\] }" >&"$HUMAN_FD"; done; } || true
    else
        "$PIPELINE_TOOLS_ENV/bin/python" "$CLIP_SCRIPT" \
            --prompt "$PROMPT" --image "$FIRST_OUTPUT" \
            --meta "$META_FOR_CONCEPT" --model-name "$MODEL" 2>&1 \
            | grep '^\[clip\]' | { while IFS= read -r line; do printf "[concept] %s\n" "${line#\[clip\] }" >&"$HUMAN_FD"; done; } || true
    fi

    # v0.3.5 (item 16) — ImageReward human-preference score on the
    # top-ranked variant. No-op when preference_score.py isn't installed.
    PREF_SCRIPT="$SCRIPT_DIR/preference_score.py"
    [[ -f "$PREF_SCRIPT" ]] || PREF_SCRIPT="$PIPELINE_ROOT/workspace/preference_score.py"
    if [[ -f "$PREF_SCRIPT" ]]; then
        "$PIPELINE_TOOLS_ENV/bin/python" "$PREF_SCRIPT" \
            --prompt "$PROMPT" --image "$FIRST_OUTPUT" \
            --meta "$META_FOR_CONCEPT" 2>&1 \
            | grep '^\[image-reward\]' | { while IFS= read -r line; do printf "[concept] %s\n" "${line#\[image-reward\] }" >&"$HUMAN_FD"; done; } || true
    fi

    # v0.3.5 (item 16) — DreamSim near-duplicate detection across variants.
    # Only meaningful with more than one variant.
    if [[ "$COUNT" -gt 1 ]]; then
        DEDUP_SCRIPT="$SCRIPT_DIR/dedup_variants.py"
        [[ -f "$DEDUP_SCRIPT" ]] || DEDUP_SCRIPT="$PIPELINE_ROOT/workspace/dedup_variants.py"
        if [[ -f "$DEDUP_SCRIPT" ]]; then
            "$PIPELINE_TOOLS_ENV/bin/python" "$DEDUP_SCRIPT" \
                --images "${OUTPUT_PATHS[@]}" \
                --meta "$META_FOR_CONCEPT" 2>&1 \
                | grep '^\[dreamsim\]' | { while IFS= read -r line; do printf "[concept] %s\n" "${line#\[dreamsim\] }" >&"$HUMAN_FD"; done; } || true
        fi
    fi
fi

# v0.3.5 (item 17) — local VLM judge + best-of-N auto-select. No-op when
# vlm-env or vlm_judge.py isn't installed.
VLM_ENV="${VLM_ENV:-$PIPELINE_ROOT/vlm-env}"
JUDGE_SCRIPT="$SCRIPT_DIR/vlm_judge.py"
[[ -f "$JUDGE_SCRIPT" ]] || JUDGE_SCRIPT="$PIPELINE_ROOT/workspace/vlm_judge.py"
if [[ "$JUDGE" == "1" && -f "$JUDGE_SCRIPT" && -x "$VLM_ENV/bin/python" ]]; then
    META_FOR_CONCEPT="${FIRST_OUTPUT}.meta.json"
    if [[ "$COUNT" -gt 1 ]]; then
        JUDGE_RESULT_FILE="$(mktemp)"
        JUDGE_STDERR_FILE="$(mktemp)"
        "$VLM_ENV/bin/python" "$JUDGE_SCRIPT" \
            --mode image --images "${OUTPUT_PATHS[@]}" \
            --meta "$META_FOR_CONCEPT" --rank --json \
            > "$JUDGE_RESULT_FILE" 2> "$JUDGE_STDERR_FILE" || true
        grep '^\[judge\]' "$JUDGE_STDERR_FILE" | { while IFS= read -r line; do printf "[concept] %s\n" "${line#\[judge\] }" >&"$HUMAN_FD"; done; } || true
        rm -f "$JUDGE_STDERR_FILE"
        python3 -c "
import json
d = json.load(open('$JUDGE_RESULT_FILE'))
for r in d['results']:
    flag = ' (below floor)' if r['rejected'] else ''
    print(f\"[concept] Judge #{r['rank']} {r['verdict']:.0f}/10 {r['image']}{flag}\")
" >&"$HUMAN_FD" 2>/dev/null || true
        if [[ -n "$BEST_OF" ]]; then
            # Move every variant except the winner to concept/rejected/,
            # then collapse OUTPUT_PATHS to just the winner for downstream
            # (--json outputs, chaining into generate.sh).
            mkdir -p "$CONCEPT_DIR/rejected"
            WINNER_PATH="$(python3 -c "
import json, sys
d = json.load(open(sys.argv[1]))
picked = [r['image'] for r in d['results'] if r['rank'] == 1][0]
print(picked)
" "$JUDGE_RESULT_FILE")"
            NEW_OUTPUT_PATHS=()
            for path in "${OUTPUT_PATHS[@]}"; do
                if [[ "$path" == "$WINNER_PATH" ]]; then
                    NEW_OUTPUT_PATHS+=( "$path" )
                else
                    mv "$path" "$CONCEPT_DIR/rejected/$(basename "$path")"
                    [[ -f "${path}.meta.json" ]] && mv "${path}.meta.json" "$CONCEPT_DIR/rejected/$(basename "$path").meta.json"
                fi
            done
            OUTPUT_PATHS=( "${NEW_OUTPUT_PATHS[@]}" )
            FIRST_OUTPUT="$WINNER_PATH"
            info "Judge picked $(basename "$WINNER_PATH"); $((COUNT - 1)) variant(s) moved to concept/rejected/"
        fi
        rm -f "$JUDGE_RESULT_FILE"
    else
        "$VLM_ENV/bin/python" "$JUDGE_SCRIPT" \
            --mode image --image "$FIRST_OUTPUT" \
            --meta "$META_FOR_CONCEPT" 2>&1 \
            | grep '^\[judge\]' | { while IFS= read -r line; do printf "[concept] %s\n" "${line#\[judge\] }" >&"$HUMAN_FD"; done; } || true
    fi
fi

if [[ "$JSON_MODE" == "1" ]]; then
    # Build the JSON outputs array via Python so paths with special chars
    # round-trip cleanly.
    OUTPUTS_JSON="$(printf '%s\n' "${OUTPUT_PATHS[@]}" \
        | python3 -c 'import sys,json; print(json.dumps([l.rstrip("\n") for l in sys.stdin if l.rstrip("\n")]))')"
    json_mode_end
    python3 "$SCRIPT_DIR/json_emit.py" \
        status=ok \
        stage=text_to_image \
        model="$MODEL" \
        license_bucket="$LICENSE_BUCKET" \
        prompt="$PROMPT" \
        final_prompt="$FINAL_PROMPT" \
        --int width="$WIDTH" \
        --int height="$HEIGHT" \
        --int steps="$STEPS" \
        --int seed="$FIRST_SEED" \
        --int count="$COUNT" \
        --array outputs="$OUTPUTS_JSON" \
        assets_root="$ASSETS_ROOT" \
        manifest_path="$MANIFEST_PATH" \
        project_mode="$PROJECT_MODE" \
        project_root="$PROJECT_ROOT" \
        project_engine="$PROJECT_ENGINE" \
        --int duration_seconds="$DURATION" \
        machine="$MACHINE" \
        hardware_tier="$HW_TIER" \
        created="$CREATED_AT"
else
    # Last line is the first image path — preserves the existing chaining
    # contract for callers that haven't migrated to --json.
    echo "$FIRST_OUTPUT"
fi
