#!/usr/bin/env bash
#
# texture.sh — texture inspection + upscale wrapper (v0.2, experimental).
#
# Modes:
#   inspect   Report stats about an input image, GLB, or texture folder.
#             No filesystem changes.
#   upscale   Run a 2x / 4x upscale via real-esrgan-ncnn-vulkan if installed.
#             Fails clearly when the binary is missing — does NOT silently
#             degrade to a different upscaler.
#
# This wrapper is deliberately scoped. PBR generation, normal-map synthesis,
# and Hunyuan3D-Paint are NOT here yet — they require separate licence review
# and have higher failure rates. See SKILL.md and the studio docs for the
# longer-term plan.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_pipeline_lib.sh"

PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"

EXPLICIT_PROJECT=""
INPUT=""
OUTPUT=""
MODE="inspect"
SCALE=4
ENGINE_STAGE=0
JSON_MODE=0

usage() {
    cat <<EOF
Usage: $(basename "$0") -i INPUT [options]

Required:
  -i, --input PATH         GLB / image / directory to inspect or upscale.

Project context:
  --project PATH           Force a project root (skips auto-detection).

Mode:
      --mode MODE          inspect (default) | upscale | paint
                           paint is a placeholder for Hunyuan3D-Paint and
                           currently fails with needs_license_review; do
                           NOT enable this until the licence has been
                           reviewed.
      --scale N            2 or 4 (default: 4) — used in upscale mode.

I/O:
  -o, --output NAME_OR_PATH  Output name or path. Defaults to a name
                              derived from the input filename in upscale
                              mode; ignored in inspect mode.
      --engine-stage       Copy upscaled outputs into the engine's texture
                              folder if it can be inferred. Off by default.
      --json               Emit a final JSON object on stdout. Human logs
                              are routed to stderr.

  -h, --help               This help.

Examples:
  # Quick inspection of a GLB
  $(basename "$0") -i assets/clean/chest_clean.glb

  # Inspect a texture folder
  $(basename "$0") -i assets/textures/

  # 4x upscale a concept image
  $(basename "$0") -i assets/concept/chest.png --mode upscale --scale 4
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)         EXPLICIT_PROJECT="$2"; shift 2 ;;
        -i|--input)        INPUT="$2";            shift 2 ;;
        -o|--output)       OUTPUT="$2";           shift 2 ;;
        --mode)            MODE="$2";             shift 2 ;;
        --scale)           SCALE="$2";            shift 2 ;;
        --engine-stage)    ENGINE_STAGE=1;        shift   ;;
        --json)            JSON_MODE=1;           shift   ;;
        -h|--help)         usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

[[ -z "$INPUT" ]] && { echo "ERROR: -i/--input is required" >&2; usage; exit 1; }
[[ -e "$INPUT" ]] || { echo "ERROR: input does not exist: $INPUT" >&2; exit 1; }
case "$MODE"  in inspect|upscale|paint) ;;
    *) echo "ERROR: --mode must be inspect, upscale, or paint (got: $MODE)" >&2; exit 1 ;;
esac
case "$SCALE" in 2|4) ;;
    *) echo "ERROR: --scale must be 2 or 4 (got: $SCALE)" >&2; exit 1 ;;
esac

# Under --json: route subcommand stdout to stderr so the JSON line is alone.
[[ "$JSON_MODE" == "1" ]] && json_mode_begin

resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

# Always make sure the textures directory exists for the project / global root.
TEXTURES_DIR="$ASSETS_ROOT/textures"
mkdir -p "$TEXTURES_DIR"

COL_BLUE='\033[0;34m'; COL_GREEN='\033[0;32m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
HUMAN_FD=1
[[ "$JSON_MODE" == "1" ]] && HUMAN_FD=2
info()  { printf "${COL_BLUE}[texture]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
done_() { printf "${COL_GREEN}[texture]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
err()   { printf "${COL_RED}[texture]${COL_RESET} %s\n" "$1" >&2; }

START_TS=$(date +%s)
CREATED_AT="$(iso_now)"
MACHINE="$(hostname_safe)"
HW_TIER="$(hardware_tier)"

if [[ "$JSON_MODE" == "1" ]]; then
    print_context >&2
else
    print_context
fi
info "Mode:    $MODE"
info "Input:   $INPUT"
info "Tier:    $HW_TIER  (machine: $MACHINE)"

# Convert input to absolute so the JSON has stable paths.
if [[ -d "$INPUT" ]]; then
    INPUT_ABS="$(cd "$INPUT" && pwd)"
else
    INPUT_ABS="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"
fi

# Always run inspect first so we have stats for the JSON output (and so
# upscale mode doesn't try to scale something that isn't an image).
INSPECT_JSON="$(python3 "$SCRIPT_DIR/texture_inspect.py" --input "$INPUT_ABS")"

if [[ "$MODE" == "inspect" ]]; then
    END_TS=$(date +%s)
    DURATION=$((END_TS - START_TS))
    done_ "Inspect complete in ${DURATION}s"

    if [[ "$JSON_MODE" == "1" ]]; then
        json_mode_end
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=ok \
            stage=texture_inspect \
            mode=inspect \
            input="$INPUT_ABS" \
            --object inspect="$INSPECT_JSON" \
            --int duration_seconds="$DURATION" \
            assets_root="$ASSETS_ROOT" \
            machine="$MACHINE" \
            hardware_tier="$HW_TIER" \
            created="$CREATED_AT"
    else
        # Pretty-print to stdout for human eyes.
        echo "$INSPECT_JSON" | python3 -m json.tool
    fi
    exit 0
fi

# ---------- paint mode (Hunyuan3D-Paint, approved 2026-05-20) ----------
# Hunyuan3D-Paint generates PBR maps for an input mesh. License review
# completed 2026-05-20 (Tencent Hunyuan Community License, bucket
# `commercial_threshold`; see docs/license-review-hunyuan3d-paint.md).
# Install layout assumed (override with $HUNYUAN3D_PAINT_DIR):
#   $HUNYUAN3D_PAINT_DIR/.venv             one venv per tool
#   $HUNYUAN3D_PAINT_DIR/run.py            inference entrypoint
# If the upstream uses a different entrypoint, update the python
# invocation below to match — the wrapper is intentionally close to
# the SF3D / SPAR3D shape.
HUNYUAN3D_PAINT_DIR="${HUNYUAN3D_PAINT_DIR:-$PIPELINE_ROOT/hunyuan3d-paint}"
HUNYUAN3D_PAINT_VENV="${HUNYUAN3D_PAINT_VENV:-$HUNYUAN3D_PAINT_DIR/.venv}"

if [[ "$MODE" == "paint" ]]; then
    # Sanity-check inputs: paint mode requires a GLB.
    case "${INPUT_ABS,,}" in
        *.glb|*.gltf) ;;
        *)
            err "paint mode requires a .glb or .gltf input (got: $INPUT_ABS)"
            if [[ "$JSON_MODE" == "1" ]]; then
                json_mode_end
                python3 "$SCRIPT_DIR/json_emit.py" \
                    status=error stage=texture_paint \
                    error=unsupported_input tool=hunyuan3d-paint \
                    license_bucket=commercial_threshold \
                    input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                    machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
            fi
            exit 2
            ;;
    esac

    if [[ ! -d "$HUNYUAN3D_PAINT_DIR" || ! -d "$HUNYUAN3D_PAINT_VENV" || ! -f "$HUNYUAN3D_PAINT_DIR/run.py" ]]; then
        err "Hunyuan3D-Paint not installed (expected $HUNYUAN3D_PAINT_DIR with .venv + run.py)."
        err "  Override location:  export HUNYUAN3D_PAINT_DIR=/path/to/Hunyuan3D-2"
        err "  License:            Tencent Hunyuan Community License (approved 2026-05-20)"
        err "                      see docs/license-review-hunyuan3d-paint.md"
        if [[ "$JSON_MODE" == "1" ]]; then
            json_mode_end
            python3 "$SCRIPT_DIR/json_emit.py" \
                status=error stage=texture_paint \
                error=not_installed tool=hunyuan3d-paint \
                license_bucket=commercial_threshold \
                input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
        fi
        exit 2
    fi

    LICENSE_BUCKET_PAINT="$(license_bucket_for_model hunyuan3d-paint)"
    info "Painting textures via Hunyuan3D-Paint (license: $LICENSE_BUCKET_PAINT)"
    info "Input mesh:  $INPUT_ABS"

    TEXTURES_DIR="$ASSETS_ROOT/textures"
    mkdir -p "$TEXTURES_DIR"
    out_base="$(basename "${INPUT_ABS%.*}")"
    PAINTED_PATH="$TEXTURES_DIR/${out_base}_painted.glb"

    PAINT_START=$(date +%s)
    (
        cd "$HUNYUAN3D_PAINT_DIR"
        # shellcheck source=/dev/null
        source "$HUNYUAN3D_PAINT_VENV/bin/activate"
        PYTORCH_ENABLE_MPS_FALLBACK=1 python run.py \
            "$INPUT_ABS" \
            --output "$PAINTED_PATH"
        deactivate
    ) || {
        err "Hunyuan3D-Paint inference failed"
        if [[ "$JSON_MODE" == "1" ]]; then
            json_mode_end
            python3 "$SCRIPT_DIR/json_emit.py" \
                status=error stage=texture_paint \
                error=inference_failed tool=hunyuan3d-paint \
                license_bucket="$LICENSE_BUCKET_PAINT" \
                input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
        fi
        exit 1
    }
    PAINT_END=$(date +%s)
    PAINT_DURATION=$((PAINT_END - PAINT_START))

    [[ -f "$PAINTED_PATH" ]] || { err "Hunyuan3D-Paint did not produce $PAINTED_PATH"; exit 1; }
    done_ "Painted in ${PAINT_DURATION}s -> $PAINTED_PATH"

    if [[ "$JSON_MODE" == "1" ]]; then
        json_mode_end
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=ok stage=texture_paint \
            tool=hunyuan3d-paint \
            license_bucket="$LICENSE_BUCKET_PAINT" \
            input="$INPUT_ABS" output="$PAINTED_PATH" \
            assets_root="$ASSETS_ROOT" \
            --int duration_seconds="$PAINT_DURATION" \
            machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
    else
        # Last line is the painted GLB path — preserves chaining.
        echo "$PAINTED_PATH"
    fi
    exit 0
fi

# ---------- upscale mode ----------
# Detect a real-esrgan-ncnn-vulkan binary. Different distributions name it
# differently; check both common forms.
ESRGAN_BIN=""
for candidate in real-esrgan-ncnn-vulkan realesrgan-ncnn-vulkan; do
    if command -v "$candidate" >/dev/null 2>&1; then
        ESRGAN_BIN="$candidate"
        break
    fi
done

if [[ -z "$ESRGAN_BIN" ]]; then
    err "real-esrgan-ncnn-vulkan binary not found in PATH."
    err "  Install one of:"
    err "    https://github.com/xinntao/Real-ESRGAN-ncnn-vulkan/releases"
    err "    https://github.com/nihui/realesrgan-ncnn-vulkan/releases"
    err "  Place the binary on your PATH as one of:"
    err "    real-esrgan-ncnn-vulkan"
    err "    realesrgan-ncnn-vulkan"
    if [[ "$JSON_MODE" == "1" ]]; then
        json_mode_end
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=error \
            stage=texture_upscale \
            error=not_installed \
            tool=real-esrgan-ncnn-vulkan \
            input="$INPUT_ABS" \
            assets_root="$ASSETS_ROOT" \
            machine="$MACHINE" \
            hardware_tier="$HW_TIER" \
            created="$CREATED_AT"
    fi
    exit 2
fi

# Refuse to upscale directories / GLBs.
KIND="$(echo "$INSPECT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("kind",""))')"
if [[ "$KIND" != "image" ]]; then
    err "Upscale mode currently supports image inputs only (got kind=$KIND)."
    err "Run inspect mode first to confirm the input is an image."
    exit 2
fi

# Resolve the output path.
INPUT_BASE="$(basename "$INPUT_ABS")"
INPUT_STEM="${INPUT_BASE%.*}"
INPUT_EXT="${INPUT_BASE##*.}"
if [[ -z "$OUTPUT" ]]; then
    OUT_PATH="$TEXTURES_DIR/${INPUT_STEM}_x${SCALE}.${INPUT_EXT}"
elif [[ "$OUTPUT" == */* ]]; then
    OUT_PATH="$OUTPUT"
else
    OUT_PATH="$TEXTURES_DIR/${OUTPUT}.${INPUT_EXT}"
fi
mkdir -p "$(dirname "$OUT_PATH")"

info "Tool:    $ESRGAN_BIN"
info "Scale:   ${SCALE}x"
info "Output:  $OUT_PATH"

# Run the upscaler. Both common builds accept -i / -o / -s.
"$ESRGAN_BIN" -i "$INPUT_ABS" -o "$OUT_PATH" -s "$SCALE"

[[ -f "$OUT_PATH" ]] || { err "upscaler did not produce $OUT_PATH"; exit 1; }

# Optional engine staging.
ENGINE_STAGED=""
if [[ $ENGINE_STAGE -eq 1 && -n "${ENGINE_PATH:-}" ]]; then
    ENGINE_TEX_DIR="$ENGINE_PATH/Textures"
    mkdir -p "$ENGINE_TEX_DIR"
    ENGINE_STAGED="$ENGINE_TEX_DIR/$(basename "$OUT_PATH")"
    cp "$OUT_PATH" "$ENGINE_STAGED"
    info "Engine-staged: $ENGINE_STAGED"
fi

END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))
done_ "Upscale complete in ${DURATION}s"
done_ "Output: $OUT_PATH"

if [[ "$JSON_MODE" == "1" ]]; then
    OUT_INSPECT_JSON="$(python3 "$SCRIPT_DIR/texture_inspect.py" --input "$OUT_PATH")"
    json_mode_end
    python3 "$SCRIPT_DIR/json_emit.py" \
        status=ok \
        stage=texture_upscale \
        mode=upscale \
        tool="$ESRGAN_BIN" \
        --int scale="$SCALE" \
        input="$INPUT_ABS" \
        output="$OUT_PATH" \
        engine_path="$ENGINE_STAGED" \
        --object input_inspect="$INSPECT_JSON" \
        --object output_inspect="$OUT_INSPECT_JSON" \
        --int duration_seconds="$DURATION" \
        assets_root="$ASSETS_ROOT" \
        machine="$MACHINE" \
        hardware_tier="$HW_TIER" \
        created="$CREATED_AT"
else
    echo "$OUT_PATH"
fi
