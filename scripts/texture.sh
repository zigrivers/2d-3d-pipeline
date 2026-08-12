#!/usr/bin/env bash
#
# texture.sh — texture inspection + upscale wrapper (v0.2, experimental).
#
# Modes:
#   inspect   Report stats about an input image, GLB, or texture folder.
#             No filesystem changes.
#   upscale   Run a 2x / 4x upscale via --engine realesrgan (default) or
#             seedvr2 (item 24: SeedVR2 3B/7B natively in mflux).
#   paint     Paint PBR textures onto an existing GLB via Hunyuan3D-Paint
#             (item 19: dgrauet/Hunyuan3D-2.1-mlx, Apple Silicon MLX port).
#             License bucket commercial_threshold; see
#             docs/license-review-hunyuan3d-paint.md. Requires --image.
#   pbr       Item 24: albedo -> StableDelight -> Marigold-IID roughness +
#             metallic decomposition, written into a new GLB. Refuses on a
#             mesh that already has a real metallic-roughness map.

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
ENGINE="realesrgan"
ESRGAN_BIN=""
IMAGE_ARG=""
ENGINE_STAGE=0
JSON_MODE=0

usage() {
    cat <<EOF
Usage: $(basename "$0") -i INPUT [options]

Required:
  -i, --input PATH         GLB / image / directory to inspect or upscale;
                           a .glb/.gltf mesh in paint mode.

Project context:
  --project PATH           Force a project root (skips auto-detection).

Mode:
      --mode MODE          inspect (default) | upscale | paint | pbr
      --scale N            2 or 4 (default: 4) — used in upscale mode.
      --engine NAME        realesrgan (default) | seedvr2 — used in
                           upscale mode. seedvr2 runs natively in mflux
                           (item 24; 3B on laptop tier, 7B on studio).
      --image PATH         Reference image for the multiview diffusion
                           pass — required in paint mode.

I/O:
  -o, --output NAME_OR_PATH  Output name or path. Defaults to a name
                              derived from the input filename in upscale
                              mode; ignored in inspect mode.
      --engine-stage       Copy upscaled outputs into the engine's texture
                              folder if it can be inferred. Off by default.
      --json               Emit a final JSON object on stdout. Human logs
                              are routed to stderr.

  -h, --help               This help.

Paint mode (item 19): Hunyuan3D-Paint via the dgrauet/Hunyuan3D-2.1-mlx
Apple Silicon port. License bucket commercial_threshold (Tencent Hunyuan
3D 2.1 Community License — does NOT apply in the EU, UK, or South Korea).
Refuses to paint over a mesh that already has baked textures — use
--mode upscale to improve an existing texture instead.

PBR mode (item 24): albedo -> StableDelight -> Marigold-IID roughness +
metallic decomposition. License bucket commercial_safe for both models
(StableDelight: apache-2.0 code + weights; Marigold-IID: CreativeML
OpenRAIL++-M, commercial use allowed with narrow behavioral-use
restrictions — see docs/decision-marigold-bucket.md). Same refusal rule
as paint mode: refuses on a mesh that already has a metallic-roughness
map.

Examples:
  # Quick inspection of a GLB
  $(basename "$0") -i assets/clean/chest_clean.glb

  # Inspect a texture folder
  $(basename "$0") -i assets/textures/

  # 4x upscale a concept image
  $(basename "$0") -i assets/concept/chest.png --mode upscale --scale 4

  # SeedVR2 upscale instead of Real-ESRGAN
  $(basename "$0") -i assets/concept/chest.png --mode upscale --engine seedvr2

  # PBR pass on an SF3D output (adds roughness + metallic)
  $(basename "$0") -i assets/clean/chest_clean.glb --mode pbr

  # Paint a vertex-color-only TRELLIS output
  $(basename "$0") -i assets/raw/chest_trellis.glb --mode paint \\
      --image assets/concept/chest.png
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)         EXPLICIT_PROJECT="$2"; shift 2 ;;
        -i|--input)        INPUT="$2";            shift 2 ;;
        -o|--output)       OUTPUT="$2";           shift 2 ;;
        --mode)            MODE="$2";             shift 2 ;;
        --scale)           SCALE="$2";            shift 2 ;;
        --engine)          ENGINE="$2";           shift 2 ;;
        --image)           IMAGE_ARG="$2";        shift 2 ;;
        --engine-stage)    ENGINE_STAGE=1;        shift   ;;
        --json)            JSON_MODE=1;           shift   ;;
        -h|--help)         usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

[[ -z "$INPUT" ]] && { echo "ERROR: -i/--input is required" >&2; usage; exit 1; }
[[ -e "$INPUT" ]] || { echo "ERROR: input does not exist: $INPUT" >&2; exit 1; }
case "$MODE"  in inspect|upscale|paint|pbr) ;;
    *) echo "ERROR: --mode must be inspect, upscale, paint, or pbr (got: $MODE)" >&2; exit 1 ;;
esac
case "$SCALE" in 2|4) ;;
    *) echo "ERROR: --scale must be 2 or 4 (got: $SCALE)" >&2; exit 1 ;;
esac
case "$ENGINE" in realesrgan|seedvr2) ;;
    *) echo "ERROR: --engine must be realesrgan or seedvr2 (got: $ENGINE)" >&2; exit 1 ;;
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

# ---------- paint mode (Hunyuan3D-Paint via MLX port, item 19) ----------
# Retargeted from item 7's original CUDA-only design: upstream
# Hunyuan3D-Paint needs CUDA custom_rasterizer/differentiable_renderer,
# unavailable on Mac. Uses dgrauet/Hunyuan3D-2.1-mlx instead (community
# MLX port, pinned commit per principle P-B). Bucket `commercial_threshold`
# (Tencent Hunyuan 3D 2.1 Community License; does NOT apply in the EU, UK,
# or South Korea — see docs/license-review-hunyuan3d-paint.md).
# Install layout assumed (override with $HUNYUAN3D_PAINT_DIR):
#   $HUNYUAN3D_PAINT_DIR/.venv                                pinned-commit venv
#   $HUNYUAN3D_PAINT_DIR/hy3dpaint/textureGenPipeline_mlx.py  pipeline module
HUNYUAN3D_PAINT_DIR="${HUNYUAN3D_PAINT_DIR:-$PIPELINE_ROOT/hunyuan3d-paint-mlx}"
HUNYUAN3D_PAINT_VENV="${HUNYUAN3D_PAINT_VENV:-$HUNYUAN3D_PAINT_DIR/.venv}"

if [[ "$MODE" == "paint" ]]; then
    # Sanity-check inputs: paint mode requires a GLB. Case-insensitive
    # glob classes, not ${VAR,,} — macOS ships bash 3.2 (no ,, support)
    # as /usr/bin/env bash unless the user has Homebrew bash on PATH.
    case "$INPUT_ABS" in
        *.[Gg][Ll][Bb]|*.[Gg][Ll][Tt][Ff]) ;;
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

    if [[ -z "$IMAGE_ARG" ]]; then
        err "paint mode requires --image PATH (a reference image for the multiview diffusion pass)"
        if [[ "$JSON_MODE" == "1" ]]; then
            json_mode_end
            python3 "$SCRIPT_DIR/json_emit.py" \
                status=error stage=texture_paint \
                error=missing_image tool=hunyuan3d-paint \
                license_bucket=commercial_threshold \
                input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
        fi
        exit 2
    fi
    [[ -f "$IMAGE_ARG" ]] || { err "reference image not found: $IMAGE_ARG"; exit 2; }
    IMAGE_ABS="$(cd "$(dirname "$IMAGE_ARG")" && pwd)/$(basename "$IMAGE_ARG")"

    # Refusal path (item 7 routing rules, elevated from soft skill-level
    # guidance to a hard check): refuse only when a REAL metallic-roughness
    # map already exists (e.g. TRELLIS.2's real PBR bake). SF3D's own output
    # commonly has albedo+normal but bakes metallic/roughness as flat
    # material factors, not textures — that case should still get painted
    # (this is exactly what makes a "canned SF3D GLB" a valid paint-smoke
    # fixture: painting genuinely ADDS a metallic-roughness map that wasn't
    # there before, rather than redundantly replacing one that was).
    # Runs the same live check generate.sh already runs post-generation
    # (texture_quality_check.py), not a possibly-stale meta.json field.
    PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
    TEXQUAL_SCRIPT="$SCRIPT_DIR/texture_quality_check.py"
    [[ -f "$TEXQUAL_SCRIPT" ]] || TEXQUAL_SCRIPT="$PIPELINE_ROOT/workspace/texture_quality_check.py"
    INPUT_META_PATH="${INPUT_ABS}.meta.json"
    if [[ -f "$TEXQUAL_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
        TEXQUAL_JSON="$("$PIPELINE_TOOLS_ENV/bin/python" "$TEXQUAL_SCRIPT" \
            --input "$INPUT_ABS" --meta "$INPUT_META_PATH" --json 2>/dev/null || echo '{}')"
        HAS_MR_MAP="$(python3 -c "
import json, sys
present = json.loads(sys.argv[1]).get('textures_present', [])
print('1' if ('metallic' in present or 'roughness' in present) else '0')
" "$TEXQUAL_JSON" 2>/dev/null || echo 0)"
        if [[ "$HAS_MR_MAP" == "1" ]]; then
            TEXTURES_PRESENT="$(python3 -c "import json,sys; print(', '.join(json.loads(sys.argv[1]).get('textures_present', [])))" "$TEXQUAL_JSON" 2>/dev/null || echo '')"
            err "Input already has a real metallic-roughness map ($TEXTURES_PRESENT) -- refusing to paint over existing PBR textures."
            err "Paint mode is for meshes with no metallic-roughness map yet (vertex-color-only or"
            err "SF3D-style scalar-factor output) or a degenerate texture pass, not a re-texture of an"
            err "already-full-PBR mesh (e.g. TRELLIS.2 output). Use 'texture.sh --mode upscale' instead."
            if [[ "$JSON_MODE" == "1" ]]; then
                json_mode_end
                python3 "$SCRIPT_DIR/json_emit.py" \
                    status=error stage=texture_paint \
                    error=already_textured tool=hunyuan3d-paint \
                    license_bucket=commercial_threshold \
                    existing_textures="$TEXTURES_PRESENT" \
                    input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                    machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
            fi
            exit 2
        fi
    fi

    DRIVER_SCRIPT="$SCRIPT_DIR/hunyuan_paint_run.py"
    [[ -f "$DRIVER_SCRIPT" ]] || DRIVER_SCRIPT="$PIPELINE_ROOT/workspace/hunyuan_paint_run.py"
    if [[ ! -x "$HUNYUAN3D_PAINT_VENV/bin/python" \
          || ! -f "$HUNYUAN3D_PAINT_DIR/hy3dpaint/textureGenPipeline_mlx.py" \
          || ! -f "$DRIVER_SCRIPT" ]]; then
        err "Hunyuan3D-Paint (MLX port) not installed (expected $HUNYUAN3D_PAINT_DIR with .venv + hy3dpaint/)."
        err "  Override location:  export HUNYUAN3D_PAINT_DIR=/path/to/Hunyuan3D-2.1-mlx"
        err "  License:            Tencent Hunyuan 3D 2.1 Community License (approved 2026-05-20;"
        err "                      does NOT apply in EU/UK/South Korea)"
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
    info "Painting textures via Hunyuan3D-Paint MLX port (license: $LICENSE_BUCKET_PAINT)"
    info "Input mesh:  $INPUT_ABS"
    info "Ref image:   $IMAGE_ABS"

    TEXTURES_DIR="$ASSETS_ROOT/textures"
    mkdir -p "$TEXTURES_DIR"
    out_base="$(basename "${INPUT_ABS%.*}")"
    PAINTED_OBJ="$TEXTURES_DIR/${out_base}_painted.obj"
    PAINTED_PATH="$TEXTURES_DIR/${out_base}_painted.glb"

    PAINT_START=$(date +%s)
    PAINT_LOG="$(mktemp)"
    "$HUNYUAN3D_PAINT_VENV/bin/python" "$DRIVER_SCRIPT" \
        --port-dir "$HUNYUAN3D_PAINT_DIR" \
        --mesh "$INPUT_ABS" \
        --image "$IMAGE_ABS" \
        --output "$PAINTED_OBJ" 2>&1 | tee "$PAINT_LOG" || {
        err "Hunyuan3D-Paint inference failed"
        rm -f "$PAINT_LOG"
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
    # Library progress bars share stdout with our driver's own result line —
    # pull just that one back out (edit.sh uses the same tee+grep pattern).
    PAINT_RESULT_LINE="$(grep '^PAINT_RESULT ' "$PAINT_LOG" | tail -1 || true)"
    rm -f "$PAINT_LOG"
    PAINT_END=$(date +%s)
    PAINT_DURATION=$((PAINT_END - PAINT_START))

    [[ -n "$PAINT_RESULT_LINE" ]] || { err "Hunyuan3D-Paint driver did not emit a result line"; exit 1; }
    [[ -f "$PAINTED_PATH" ]] || { err "Hunyuan3D-Paint did not produce $PAINTED_PATH"; exit 1; }
    done_ "Painted in ${PAINT_DURATION}s -> $PAINTED_PATH"

    META_PATH="${PAINTED_PATH}.meta.json"
    META_HELPER_SCRIPT="$SCRIPT_DIR/meta_helper.py"
    [[ -f "$META_HELPER_SCRIPT" ]] || META_HELPER_SCRIPT="$PIPELINE_ROOT/workspace/meta_helper.py"
    PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
    if [[ -f "$META_HELPER_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
        "$PIPELINE_TOOLS_ENV/bin/python" "$META_HELPER_SCRIPT" merge "$META_PATH" \
            --section generation \
            --data "{\"backend\": \"hunyuan3d-paint\", \"model_role\": \"paint\", \"texture_backend\": \"hunyuan3d-paint\", \"license_bucket\": \"$LICENSE_BUCKET_PAINT\", \"inputs\": [{\"path\": \"$INPUT_ABS\"}, {\"path\": \"$IMAGE_ABS\"}], \"duration_seconds\": $PAINT_DURATION}" \
            > /dev/null 2>&1 || true
    fi

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

# ---------- pbr mode (StableDelight -> Marigold-IID, item 24) ----------
# License buckets both commercial_safe: StableDelight (code + weights
# apache-2.0, verified directly at implementation time) and Marigold-IID
# (CreativeML OpenRAIL++-M, gate G4 -- see docs/decision-marigold-bucket.md).
PBR_PASS_ENV="${PBR_PASS_ENV:-$PIPELINE_ROOT/pbr-pass-env}"

if [[ "$MODE" == "pbr" ]]; then
    case "$INPUT_ABS" in
        *.[Gg][Ll][Bb]|*.[Gg][Ll][Tt][Ff]) ;;
        *)
            err "pbr mode requires a .glb or .gltf input (got: $INPUT_ABS)"
            if [[ "$JSON_MODE" == "1" ]]; then
                json_mode_end
                python3 "$SCRIPT_DIR/json_emit.py" \
                    status=error stage=texture_pbr \
                    error=unsupported_input tool=pbr-pass \
                    license_bucket=commercial_safe \
                    input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                    machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
            fi
            exit 2
            ;;
    esac

    # Same refusal rule and mechanism as paint mode: refuse when a real
    # metallic-roughness map already exists (TRELLIS.2 output, a prior
    # paint pass) -- a PBR pass on an already-PBR mesh is redundant/wrong.
    PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
    TEXQUAL_SCRIPT="$SCRIPT_DIR/texture_quality_check.py"
    [[ -f "$TEXQUAL_SCRIPT" ]] || TEXQUAL_SCRIPT="$PIPELINE_ROOT/workspace/texture_quality_check.py"
    INPUT_META_PATH="${INPUT_ABS}.meta.json"
    if [[ -f "$TEXQUAL_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
        TEXQUAL_JSON="$("$PIPELINE_TOOLS_ENV/bin/python" "$TEXQUAL_SCRIPT" \
            --input "$INPUT_ABS" --meta "$INPUT_META_PATH" --json 2>/dev/null || echo '{}')"
        HAS_MR_MAP="$(python3 -c "
import json, sys
present = json.loads(sys.argv[1]).get('textures_present', [])
print('1' if ('metallic' in present or 'roughness' in present) else '0')
" "$TEXQUAL_JSON" 2>/dev/null || echo 0)"
        if [[ "$HAS_MR_MAP" == "1" ]]; then
            TEXTURES_PRESENT="$(python3 -c "import json,sys; print(', '.join(json.loads(sys.argv[1]).get('textures_present', [])))" "$TEXQUAL_JSON" 2>/dev/null || echo '')"
            err "Input already has a real metallic-roughness map ($TEXTURES_PRESENT) -- refusing to run the PBR pass over existing PBR textures."
            err "PBR mode is for meshes with no metallic-roughness map yet (SF3D-style"
            err "scalar-factor output), not a re-pass of an already-full-PBR mesh (e.g."
            err "TRELLIS.2 output or a prior paint/pbr pass)."
            if [[ "$JSON_MODE" == "1" ]]; then
                json_mode_end
                python3 "$SCRIPT_DIR/json_emit.py" \
                    status=error stage=texture_pbr \
                    error=already_textured tool=pbr-pass \
                    license_bucket=commercial_safe \
                    existing_textures="$TEXTURES_PRESENT" \
                    input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                    machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
            fi
            exit 2
        fi
    fi

    DRIVER_SCRIPT="$SCRIPT_DIR/pbr_pass.py"
    [[ -f "$DRIVER_SCRIPT" ]] || DRIVER_SCRIPT="$PIPELINE_ROOT/workspace/pbr_pass.py"
    if [[ ! -x "$PBR_PASS_ENV/bin/python" || ! -f "$DRIVER_SCRIPT" ]]; then
        err "pbr-pass-env (StableDelight + Marigold-IID) not installed (expected $PBR_PASS_ENV)."
        err "  Override location: export PBR_PASS_ENV=/path/to/venv"
        err "  License: StableDelight apache-2.0; Marigold-IID CreativeML OpenRAIL++-M"
        err "           (commercial_safe with a use-restriction note; see"
        err "           docs/decision-marigold-bucket.md)"
        if [[ "$JSON_MODE" == "1" ]]; then
            json_mode_end
            python3 "$SCRIPT_DIR/json_emit.py" \
                status=error stage=texture_pbr \
                error=not_installed tool=pbr-pass \
                license_bucket=commercial_safe \
                input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
        fi
        exit 2
    fi

    out_base="$(basename "${INPUT_ABS%.*}")"
    PBR_PATH="$TEXTURES_DIR/${out_base}_pbr.glb"
    PBR_META_PATH="${PBR_PATH}.meta.json"
    info "Running PBR pass (StableDelight -> Marigold-IID, license: commercial_safe)"
    info "Input mesh:  $INPUT_ABS"
    info "Output:      $PBR_PATH"

    PBR_START=$(date +%s)
    "$PBR_PASS_ENV/bin/python" "$DRIVER_SCRIPT" \
        --input "$INPUT_ABS" --output "$PBR_PATH" --meta "$PBR_META_PATH" 2>&1 \
        | { while IFS= read -r line; do printf "[pbr] %s\n" "${line#\[pbr\] }" >&"$HUMAN_FD"; done; } || {
        err "PBR pass failed"
        if [[ "$JSON_MODE" == "1" ]]; then
            json_mode_end
            python3 "$SCRIPT_DIR/json_emit.py" \
                status=error stage=texture_pbr \
                error=inference_failed tool=pbr-pass \
                license_bucket=commercial_safe \
                input="$INPUT_ABS" assets_root="$ASSETS_ROOT" \
                machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
        fi
        exit 1
    }
    PBR_END=$(date +%s)
    PBR_DURATION=$((PBR_END - PBR_START))

    [[ -f "$PBR_PATH" ]] || { err "PBR pass did not produce $PBR_PATH"; exit 1; }
    done_ "PBR pass complete in ${PBR_DURATION}s -> $PBR_PATH"

    if [[ "$JSON_MODE" == "1" ]]; then
        json_mode_end
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=ok stage=texture_pbr \
            tool=pbr-pass \
            license_bucket=commercial_safe \
            input="$INPUT_ABS" output="$PBR_PATH" \
            assets_root="$ASSETS_ROOT" \
            --int duration_seconds="$PBR_DURATION" \
            machine="$MACHINE" hardware_tier="$HW_TIER" created="$CREATED_AT"
    else
        echo "$PBR_PATH"
    fi
    exit 0
fi

# ---------- upscale mode ----------
# Refuse to upscale directories / GLBs (both engines need an image input).
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

if [[ "$ENGINE" == "realesrgan" ]]; then
    # Detect a real-esrgan-ncnn-vulkan binary. Different distributions name
    # it differently; check both common forms.
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
        err "  Or use --engine seedvr2 instead (item 24, no ncnn-vulkan dependency)."
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

    info "Engine:  realesrgan ($ESRGAN_BIN)"
    info "Scale:   ${SCALE}x"
    info "Output:  $OUT_PATH"

    # Run the upscaler. Both common builds accept -i / -o / -s.
    "$ESRGAN_BIN" -i "$INPUT_ABS" -o "$OUT_PATH" -s "$SCALE"
else
    # seedvr2 (item 24): runs natively via mflux's mflux-upscale-seedvr2
    # console script. --resolution takes an absolute target, not a ratio,
    # so translate --scale into one from the input's own longest side.
    MFLUX_VENV="${MFLUX_VENV:-$PIPELINE_ROOT/mflux-env}"
    if [[ ! -x "$MFLUX_VENV/bin/mflux-upscale-seedvr2" ]]; then
        err "mflux-upscale-seedvr2 not found (expected in $MFLUX_VENV)."
        err "  SeedVR2 ships in mflux >= 0.18; run the mflux setup from the setup guide."
        if [[ "$JSON_MODE" == "1" ]]; then
            json_mode_end
            python3 "$SCRIPT_DIR/json_emit.py" \
                status=error \
                stage=texture_upscale \
                error=not_installed \
                tool=seedvr2 \
                license_bucket=commercial_safe \
                input="$INPUT_ABS" \
                assets_root="$ASSETS_ROOT" \
                machine="$MACHINE" \
                hardware_tier="$HW_TIER" \
                created="$CREATED_AT"
        fi
        exit 2
    fi

    INPUT_W="$(echo "$INSPECT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("width") or 0)')"
    INPUT_H="$(echo "$INSPECT_JSON" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("height") or 0)')"
    LONG_SIDE=$(( INPUT_W > INPUT_H ? INPUT_W : INPUT_H ))
    TARGET_RES=$(( LONG_SIDE * SCALE ))

    # Item 24: SeedVR2 3B on laptop tier, 7B on studio tier.
    SEEDVR2_MODEL_ARGS=()
    [[ "$HW_TIER" == "studio" ]] && SEEDVR2_MODEL_ARGS=(--model seedvr2-7b)

    info "Engine:  seedvr2 (${SEEDVR2_MODEL_ARGS[1]:-seedvr2-3b}, license: commercial_safe)"
    info "Scale:   ${SCALE}x (target resolution ${TARGET_RES}px)"
    info "Output:  $OUT_PATH"

    source "$MFLUX_VENV/bin/activate"
    mflux-upscale-seedvr2 \
        --image-path "$INPUT_ABS" \
        --resolution "$TARGET_RES" \
        --output "$OUT_PATH" \
        "${SEEDVR2_MODEL_ARGS[@]}"
    deactivate
fi

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

UPSCALE_TOOL="$ESRGAN_BIN"
UPSCALE_LICENSE_BUCKET=""
[[ "$ENGINE" == "seedvr2" ]] && { UPSCALE_TOOL="seedvr2"; UPSCALE_LICENSE_BUCKET="commercial_safe"; }

# Item 24 — record which upscale engine produced this output.
OUT_META_PATH="${OUT_PATH}.meta.json"
PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
META_HELPER_SCRIPT="$SCRIPT_DIR/meta_helper.py"
[[ -f "$META_HELPER_SCRIPT" ]] || META_HELPER_SCRIPT="$PIPELINE_ROOT/workspace/meta_helper.py"
if [[ -f "$META_HELPER_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
    "$PIPELINE_TOOLS_ENV/bin/python" "$META_HELPER_SCRIPT" merge "$OUT_META_PATH" \
        --section quality --data "{\"textures\": {\"upscale_engine\": \"$ENGINE\"}}" \
        > /dev/null 2>&1 || true
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
        engine="$ENGINE" \
        tool="$UPSCALE_TOOL" \
        license_bucket="$UPSCALE_LICENSE_BUCKET" \
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
