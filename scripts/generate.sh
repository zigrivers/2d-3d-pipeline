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
SPAR3D_DIR="${SPAR3D_DIR:-$PIPELINE_ROOT/stable-point-aware-3d}"
TRELLIS_DIR="$PIPELINE_ROOT/trellis-mac"
TRELLIS2_DIR="${TRELLIS2_DIR:-$PIPELINE_ROOT/trellis2-mac}"
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
OVERWRITE_ENGINE=0
JSON_MODE=0
BG_REMOVAL_MODE=""
PREVIEW_MODE=""
JUDGE_MESH=0

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
  -g, --generator NAME     sf3d (default) | spar3d | trellis | trellis2
                           spar3d, trellis, and trellis2 are experimental /
                           opt-in. trellis2 bakes real PBR textures (not
                           just scalar factors); see the generator matrix
                           in skill/SKILL.md before choosing it.
  -o, --output NAME        Output name (default: derived from input)
  -p, --polycount N        Target polycount after cleanup (default: 3000)
  -t, --texture-res N      SF3D texture resolution (default: 2048)
  -r, --remesh OPT         none | triangle | quad (default: quad)
  -u, --up AXIS            y (default) | z
      --no-clean           Skip Blender cleanup; raw mesh only
      --overwrite-engine   Allow overwriting an existing engine-staged file
                           (only relevant when auto_increment_collisions
                           is false in .asset-pipeline.json).
      --json               Emit a final JSON result line on stdout.
                           Human-readable logs are routed to stderr so
                           stdout contains only the JSON object.
      --judge-mesh         Render turntable views and score the mesh with
                           a local VLM judge (recognizable, back-face
                           plausibility, geometry artifacts, texture
                           coherence). Warn-don't-block: a below-floor
                           verdict flags the asset but does not fail the
                           run. No-op when vlm-env isn't installed.
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
        --overwrite-engine)  OVERWRITE_ENGINE=1; shift ;;
        --bg-removal)        BG_REMOVAL_MODE="$2"; shift 2 ;;
        --no-bg-removal)     BG_REMOVAL_MODE="off"; shift ;;
        --preview)           PREVIEW_MODE="$2"; shift 2 ;;
        --no-preview)        PREVIEW_MODE="none"; shift ;;
        --json)              JSON_MODE=1;       shift ;;
        --judge-mesh)        JUDGE_MESH=1;      shift ;;
        -h|--help)           usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

[[ -z "$INPUT" ]] && { echo "ERROR: -i/--input is required" >&2; usage; exit 1; }
[[ ! -f "$INPUT" ]] && { echo "ERROR: Input file not found: $INPUT" >&2; exit 1; }

INPUT="$(cd "$(dirname "$INPUT")" && pwd)/$(basename "$INPUT")"

# Under --json, route subcommand stdout (SF3D, TRELLIS, Blender) to stderr;
# real stdout is restored just before the final JSON line.
[[ "$JSON_MODE" == "1" ]] && json_mode_begin

# Defined here (not further down) because the background-removal step below
# can call info() on the "applied" path — moved up after a real trellis2 run
# hit `info: command not found` the first time BG_REMOVAL_MODE=on actually
# triggered rembg for a generator (previously always "auto", which the
# clean-background concept.sh fixtures used in testing never applied).
COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
HUMAN_FD=1
[[ "$JSON_MODE" == "1" ]] && HUMAN_FD=2
info()  { printf "${COL_BLUE}[pipeline]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
done_() { printf "${COL_GREEN}[pipeline]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
err()   { printf "${COL_RED}[pipeline]${COL_RESET} %s\n" "$1" >&2; }

# Resolve project context BEFORE setting output paths
resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

# Apply config defaults
[[ -z "$GENERATOR" ]]   && GENERATOR="$(config_default generator_3d sf3d)"
[[ -z "$POLYCOUNT" ]]   && POLYCOUNT="$(config_default polycount 3000)"
[[ -z "$TEXTURE_RES" ]] && TEXTURE_RES="$(config_default texture_resolution 2048)"

case "$GENERATOR" in
    sf3d|trellis|spar3d|trellis2) ;;
    *) echo "ERROR: -g must be sf3d, spar3d, trellis, or trellis2 (got: $GENERATOR)" >&2; exit 1 ;;
esac
case "$UP_AXIS" in y|z) ;; *) echo "ERROR: -u must be y or z" >&2; exit 1 ;; esac

if [[ -z "$OUTPUT_NAME" ]]; then
    OUTPUT_NAME="$(basename "$INPUT" | sed 's/\.[^.]*$//')"
fi

RAW_DIR="$ASSETS_ROOT/raw"
CLEAN_DIR="$ASSETS_ROOT/clean"
mkdir -p "$RAW_DIR" "$CLEAN_DIR"

RAW_PATH="$RAW_DIR/${OUTPUT_NAME}_raw.glb"
CLEAN_PATH="$CLEAN_DIR/${OUTPUT_NAME}_clean.glb"
META_PATH="${CLEAN_PATH}.meta.json"

# v0.3: input quality check + WebP/GIF normalisation. No-op when the
# helper script or pipeline-tools-env isn't installed (v0.2 behaviour).
check_and_normalize_input

# v0.3: conditional background removal. Reads input.background_uniformity
# from the meta.json that check_and_normalize_input just wrote. Updates
# $INPUT to the no-background PNG when the run actually applies.
[[ -z "$BG_REMOVAL_MODE" && "$GENERATOR" == "trellis2" ]] && BG_REMOVAL_MODE="on"
[[ -z "$BG_REMOVAL_MODE" ]] && BG_REMOVAL_MODE="$(read_pipeline_config bg_removal_mode auto 2>/dev/null || echo auto)"
PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
REMBG_SCRIPT="$SCRIPT_DIR/rembg_preprocess.py"
[[ -f "$REMBG_SCRIPT" ]] || REMBG_SCRIPT="$PIPELINE_ROOT/workspace/rembg_preprocess.py"
if [[ -f "$REMBG_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" && "$BG_REMOVAL_MODE" != "off" ]]; then
    REMBG_RESULT="$("$PIPELINE_TOOLS_ENV/bin/python" "$REMBG_SCRIPT" \
        --input "$INPUT" --output-dir "$ASSETS_ROOT/concept" --meta "$META_PATH" \
        --mode "$BG_REMOVAL_MODE" --name "$OUTPUT_NAME" --json 2>/dev/null || echo '{}')"
    NEW_INPUT="$(printf '%s' "$REMBG_RESULT" | python3 -c "
import json, sys
try: d = json.loads(sys.stdin.read())
except Exception: sys.exit(0)
if d.get('applied') and d.get('output_path'):
    print(d['output_path'])
" 2>/dev/null)"
    if [[ -n "$NEW_INPUT" && -f "$NEW_INPUT" ]]; then
        info "Background removed → $NEW_INPUT"
        INPUT="$NEW_INPUT"
    fi
fi

START_TS=$(date +%s)
CREATED_AT="$(iso_now)"
MACHINE="$(hostname_safe)"
HW_TIER="$(hardware_tier)"
LICENSE_BUCKET="$(license_bucket_for_model "$GENERATOR")"

warn_if_non_commercial "$GENERATOR"

if [[ "$JSON_MODE" == "1" ]]; then
    print_context >&2
else
    print_context
fi
info "Generator: $GENERATOR  (license: $LICENSE_BUCKET)"
info "Tier:      $HW_TIER  (machine: $MACHINE)"
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

elif [[ "$GENERATOR" == "spar3d" ]]; then
    # SPAR3D (Stable Point Aware 3D) — optional, experimental, commercial-threshold.
    # Install layout assumed (override with $SPAR3D_DIR):
    #   $SPAR3D_DIR/.venv             -- isolated venv per the one-venv-per-tool rule
    #   $SPAR3D_DIR/run.py            -- inference entrypoint (SF3D-style)
    # If your installed SPAR3D copy uses a different entrypoint, edit the
    # `python run.py ...` invocation below to match — the wrapper is intentionally
    # close to the SF3D shape because both repos converge on a similar CLI.
    if [[ ! -d "$SPAR3D_DIR" ]]; then
        err "SPAR3D not installed at $SPAR3D_DIR"
        err "  Expected directory:  $SPAR3D_DIR"
        err "  Expected venv:       $SPAR3D_DIR/.venv"
        err "  Override location:   export SPAR3D_DIR=/path/to/stable-point-aware-3d"
        err "  Install hint:        clone https://github.com/Stability-AI/stable-point-aware-3d"
        err "                       then create a venv and run its setup steps."
        err "  Note: SPAR3D is experimental and not the default 3D generator."
        exit 1
    fi
    if [[ ! -d "$SPAR3D_DIR/.venv" ]]; then
        err "SPAR3D venv not found at $SPAR3D_DIR/.venv"
        err "  Run the SPAR3D install steps and create a .venv inside it."
        exit 1
    fi
    if [[ ! -f "$SPAR3D_DIR/run.py" ]]; then
        err "SPAR3D inference script not found at $SPAR3D_DIR/run.py"
        err "  The wrapper expects an SF3D-style 'python run.py INPUT --output-dir DIR'"
        err "  interface. If your install uses a different entry point, edit"
        err "  generate.sh's spar3d branch to match."
        exit 1
    fi

    pushd "$SPAR3D_DIR" > /dev/null
    # shellcheck source=/dev/null
    source .venv/bin/activate

    TMP_OUT="$RAW_DIR/spar3d_tmp_$$"
    rm -rf "$TMP_OUT"

    # The CLI shape mirrors SF3D: positional image, --output-dir, optional
    # texture/remesh flags. Adjust here if your installed SPAR3D differs.
    PYTORCH_ENABLE_MPS_FALLBACK=1 python run.py \
        "$INPUT" \
        --output-dir "$TMP_OUT" \
        --texture-resolution "$TEXTURE_RES" \
        --remesh_option "$REMESH"

    # Locate the produced GLB. SF3D writes <dir>/0/mesh.glb; if SPAR3D writes
    # somewhere else, grab the first GLB under TMP_OUT.
    PRODUCED=""
    if [[ -f "$TMP_OUT/0/mesh.glb" ]]; then
        PRODUCED="$TMP_OUT/0/mesh.glb"
    else
        PRODUCED="$(find "$TMP_OUT" -name '*.glb' -print -quit 2>/dev/null || true)"
    fi
    [[ -n "$PRODUCED" && -f "$PRODUCED" ]] || { err "SPAR3D did not produce a GLB under $TMP_OUT"; exit 1; }
    mv "$PRODUCED" "$RAW_PATH"
    rm -rf "$TMP_OUT"
    deactivate
    popd > /dev/null

elif [[ "$GENERATOR" == "trellis" ]]; then
    # This is the legacy v1 TRELLIS port (non_commercial) — do not confuse
    # with `trellis2` below, a separate MIT-licensed port at a different path.
    [[ -d "$TRELLIS_DIR/.venv" ]] || { err "TRELLIS venv not found at $TRELLIS_DIR/.venv"; exit 1; }
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

elif [[ "$GENERATOR" == "trellis2" ]]; then
    # Item 15. rembg preprocessing (below, generic to all generators) is
    # forced "on" for this generator specifically so the input always has
    # a real alpha channel by the time we get here — Trellis2ImageTo3DPipeline
    # .preprocess_image() skips its own bundled RMBG-2.0 (CC BY-NC,
    # non-commercial) call whenever the input already has alpha. Without
    # that, RMBG-2.0 would silently run on any input the generic "auto"
    # background-removal heuristic decided to leave alone (e.g. an
    # already-clean concept.sh render), pulling a non-commercial model
    # into a run whose license bucket says commercial_safe.
    [[ -d "$TRELLIS2_DIR/.venv" ]] || { err "TRELLIS.2 venv not found at $TRELLIS2_DIR/.venv"; exit 1; }
    pushd "$TRELLIS2_DIR" > /dev/null
    # shellcheck source=/dev/null
    source .venv/bin/activate

    TMP_BASE="$RAW_DIR/${OUTPUT_NAME}_trellis2_tmp_$$"
    python generate.py "$INPUT" --output "$TMP_BASE" --texture-size "$TEXTURE_RES"
    [[ -f "${TMP_BASE}.glb" ]] || { err "TRELLIS.2 did not produce ${TMP_BASE}.glb"; exit 1; }
    mv "${TMP_BASE}.glb" "$RAW_PATH"
    [[ -f "${TMP_BASE}.obj" ]] && rm -f "${TMP_BASE}.obj"
    deactivate
    popd > /dev/null
fi

GEN_TS=$(date +%s)
done_ "Generation finished in $((GEN_TS - START_TS))s -> $RAW_PATH"

# Item 15 — record which generator produced this asset. meta_schema.json's
# `generation` section was reserved but nothing wrote it before this change.
META_HELPER_SCRIPT="$SCRIPT_DIR/meta_helper.py"
[[ -f "$META_HELPER_SCRIPT" ]] || META_HELPER_SCRIPT="$PIPELINE_ROOT/workspace/meta_helper.py"
if [[ -f "$META_HELPER_SCRIPT" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
    GENERATION_DATA="$(python3 "$SCRIPT_DIR/json_emit.py" \
        backend="$GENERATOR" \
        license_bucket="$LICENSE_BUCKET" \
        --int polycount_target="$POLYCOUNT" \
        --int texture_resolution="$TEXTURE_RES" \
        --int duration_seconds=$((GEN_TS - START_TS)) 2>/dev/null)"
    "$PIPELINE_TOOLS_ENV/bin/python" "$META_HELPER_SCRIPT" merge "$META_PATH" \
        --section generation --data "$GENERATION_DATA" > /dev/null 2>&1 || true
fi

if [[ $SKIP_CLEAN -eq 1 ]]; then
    info "Skipping cleanup (--no-clean). Final asset: $RAW_PATH"
    END_TS=$(date +%s)
    DURATION=$((END_TS - START_TS))
    if [[ "$JSON_MODE" == "1" ]]; then
        json_mode_end
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=ok \
            stage=image_to_3d \
            generator="$GENERATOR" \
            license_bucket="$LICENSE_BUCKET" \
            input="$INPUT" \
            raw_path="$RAW_PATH" \
            clean_path="" \
            engine_path="" \
            --int polycount_target="$POLYCOUNT" \
            --int texture_resolution="$TEXTURE_RES" \
            remesh="$REMESH" \
            up_axis="$UP_AXIS" \
            --bool skip_clean=true \
            --bool engine_staged=false \
            assets_root="$ASSETS_ROOT" \
            manifest_path="$MANIFEST_PATH" \
            project_mode="$PROJECT_MODE" \
            project_root="$PROJECT_ROOT" \
            project_engine="$PROJECT_ENGINE" \
            --int duration_seconds="$DURATION" \
            machine="$MACHINE" \
            hardware_tier="$HW_TIER" \
            created="$CREATED_AT"
    fi
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
    "$RAW_PATH" "$CLEAN_PATH" "$POLYCOUNT" "$UP_AXIS" "$META_PATH"

[[ -f "$CLEAN_PATH" ]] || { err "Cleanup did not produce $CLEAN_PATH"; exit 1; }

# v0.3 — mesh quality + texture quality checks (silent no-op when
# pipeline-tools-env isn't installed).
PIPELINE_TOOLS_ENV="${PIPELINE_TOOLS_ENV:-$PIPELINE_ROOT/pipeline-tools-env}"
run_pipeline_check() {
    local script_name="$1"; shift
    local script="$SCRIPT_DIR/$script_name"
    [[ -f "$script" ]] || script="$PIPELINE_ROOT/workspace/$script_name"
    if [[ -f "$script" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
        "$PIPELINE_TOOLS_ENV/bin/python" "$script" "$@" 2>&1 \
            | { while IFS= read -r line; do printf "[pipeline] %s\n" "${line#\[*\] }" >&"$HUMAN_FD"; done; } || true
    fi
}
run_pipeline_check mesh_quality_check.py --input "$CLEAN_PATH" --meta "$META_PATH" --mode normalized
run_pipeline_check texture_quality_check.py --input "$CLEAN_PATH" --meta "$META_PATH"
run_pipeline_check game_asset_check.py --input "$CLEAN_PATH" --meta "$META_PATH" --engine "$PROJECT_ENGINE"

# v0.3 — surface a user-friendly cleanup summary if clean_asset.py wrote
# its `cleanup` section into the meta.json. Silent when the section is
# missing (older clean_asset.py or meta_helper.py absent).
if [[ -f "$META_PATH" ]]; then
    python3 - "$META_PATH" <<'PY' 2>/dev/null || true
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
c = data.get("cleanup") or {}
if not c:
    sys.exit(0)
dec = c.get("decimate") or {}
parts = []
n = c.get("duplicate_vertices_removed")
if n:
    parts.append(f"removed {n:,} duplicate points")
n = c.get("holes_filled")
if n:
    parts.append(f"filled {n} small gap(s)")
b, a = dec.get("before"), dec.get("after")
if b and a and b != a:
    parts.append(f"simplified mesh: {b:,} → {a:,} polygons")
if parts:
    print("[pipeline] Cleanup: " + ", ".join(parts))
PY
fi

# --- Engine staging: copy clean GLB into project's engine folder if applicable ---
#
# Collision handling (Phase 5):
#   AUTO_INCREMENT=1 (default)            -> find next free <name>_N.glb
#   AUTO_INCREMENT=0 + --overwrite-engine -> warn, then overwrite
#   AUTO_INCREMENT=0 + no overwrite flag  -> warn, skip the stage so the
#                                            existing engine file is preserved
ENGINE_STAGED_PATH=""
if [[ "$PROJECT_MODE" == "project" && $SKIP_ENGINE_STAGE -eq 0 ]]; then
    if [[ "$PROJECT_ENGINE" == "unity" || "$PROJECT_ENGINE" == "unreal" || -n "${ENGINE_PATH:-}" ]]; then
        mkdir -p "$ENGINE_PATH"
        CANDIDATE="$ENGINE_PATH/${OUTPUT_NAME}.glb"

        if [[ ! -e "$CANDIDATE" ]]; then
            ENGINE_STAGED_PATH="$CANDIDATE"
        elif [[ "$AUTO_INCREMENT" == "1" ]]; then
            # Find the next unused suffix.
            n=2
            while [[ -e "$ENGINE_PATH/${OUTPUT_NAME}_${n}.glb" ]]; do
                n=$((n + 1))
            done
            ENGINE_STAGED_PATH="$ENGINE_PATH/${OUTPUT_NAME}_${n}.glb"
            info "Engine collision avoided: writing $(basename "$ENGINE_STAGED_PATH") instead of ${OUTPUT_NAME}.glb"
        elif [[ $OVERWRITE_ENGINE -eq 1 ]]; then
            ENGINE_STAGED_PATH="$CANDIDATE"
            info "Overwriting existing engine asset (--overwrite-engine): $ENGINE_STAGED_PATH"
        else
            info "Engine file already exists at $CANDIDATE; skipping stage."
            info "  Pass --overwrite-engine to replace it, or enable"
            info "  naming.auto_increment_collisions in .asset-pipeline.json."
            ENGINE_STAGED_PATH=""
        fi

        if [[ -n "$ENGINE_STAGED_PATH" ]]; then
            cp "$CLEAN_PATH" "$ENGINE_STAGED_PATH"
            info "Staged for engine: $ENGINE_STAGED_PATH"
        fi
    fi
fi

# v0.3 — turntable preview render (hero PNG + optional GIF).
# Tier-aware default: laptop = png, studio = gif. Queue forces none.
TURNTABLE_SCRIPT="$SCRIPT_DIR/turntable_render.py"
[[ -f "$TURNTABLE_SCRIPT" ]] || TURNTABLE_SCRIPT="$PIPELINE_ROOT/workspace/turntable_render.py"
if [[ -z "$PREVIEW_MODE" ]]; then
    if [[ "$HW_TIER" == "studio" ]]; then
        PREVIEW_MODE="$(read_pipeline_config preview_default_studio gif 2>/dev/null || echo gif)"
    else
        PREVIEW_MODE="$(read_pipeline_config preview_default_laptop png 2>/dev/null || echo png)"
    fi
fi
if [[ "$PREVIEW_MODE" != "none" && -f "$TURNTABLE_SCRIPT" && -x "$BLENDER" ]]; then
    PREVIEW_DIR="$ASSETS_ROOT/preview"
    FRAMES=1
    RESOLUTION=1024
    if [[ "$PREVIEW_MODE" == "gif" ]]; then
        FRAMES=12
        RESOLUTION=512
    fi
    info "Rendering preview ($PREVIEW_MODE mode, $FRAMES frame(s))..."
    "$BLENDER" --background --python "$TURNTABLE_SCRIPT" -- \
        "$CLEAN_PATH" "$PREVIEW_DIR" "$OUTPUT_NAME" "$PREVIEW_MODE" \
        "$FRAMES" "$RESOLUTION" 32 "$META_PATH" 2>&1 \
        | grep '^\[turntable\]' | { while IFS= read -r line; do printf "[pipeline] %s\n" "${line#\[turntable\] }" >&"$HUMAN_FD"; done; } || true
    # Assemble GIF if mode=gif using pipeline-tools-env Pillow
    if [[ "$PREVIEW_MODE" == "gif" && -x "$PIPELINE_TOOLS_ENV/bin/python" ]]; then
        "$PIPELINE_TOOLS_ENV/bin/python" - <<'PY' "$PREVIEW_DIR" "$OUTPUT_NAME" "$META_PATH" 2>/dev/null || true
import json, os, sys, glob, subprocess
preview_dir, name, meta_path = sys.argv[1], sys.argv[2], sys.argv[3]
manifest_path = os.path.join(preview_dir, f"{name}_preview_manifest.json")
try:
    m = json.load(open(manifest_path))
except Exception:
    sys.exit(0)
frames = m.get("frame_paths") or []
if not frames:
    sys.exit(0)
try:
    from PIL import Image
except ImportError:
    sys.exit(0)
imgs = [Image.open(f).convert("RGBA") for f in frames]
gif_path = os.path.join(preview_dir, f"{name}.gif")
imgs[0].save(gif_path, save_all=True, append_images=imgs[1:], duration=125, loop=0, disposal=2)
print(f"[pipeline] Preview: turntable GIF → {gif_path}")
# Update meta.json with the gif path
helper = os.path.expanduser(os.path.dirname(os.path.abspath(__file__)) + "/meta_helper.py")
if not os.path.exists(helper):
    helper = os.path.expanduser("~/3d-pipeline/workspace/meta_helper.py")
try:
    subprocess.run([sys.executable, helper, "merge", meta_path,
                    "--section", "preview", "--data", json.dumps({"gif_path": gif_path})], check=False)
except Exception:
    pass
PY
    fi
fi

# v0.3.6 (item 18) — opt-in mesh judge: render N turntable views
# (independent of the user-facing $PREVIEW_MODE/frame count) and score
# geometry/texture with the local VLM judge. Warn-don't-block: a
# below-floor verdict flags the asset but never fails the run. No-op when
# vlm-env or vlm_judge.py isn't installed.
JUDGE_MESH_VERDICT=""
JUDGE_MESH_REJECTED=""
if [[ "$JUDGE_MESH" == "1" ]]; then
    VLM_ENV="${VLM_ENV:-$PIPELINE_ROOT/vlm-env}"
    JUDGE_SCRIPT="$SCRIPT_DIR/vlm_judge.py"
    [[ -f "$JUDGE_SCRIPT" ]] || JUDGE_SCRIPT="$PIPELINE_ROOT/workspace/vlm_judge.py"
    if [[ -f "$JUDGE_SCRIPT" && -x "$VLM_ENV/bin/python" && -f "$TURNTABLE_SCRIPT" && -x "$BLENDER" ]]; then
        MESH_JUDGE_VIEWS="$(read_pipeline_config mesh_judge_views 8)"
        MESH_JUDGE_FLOOR="$(read_pipeline_config mesh_judge_floor 2.0)"
        MESH_JUDGE_DIR="$ASSETS_ROOT/preview/mesh_judge"
        info "Rendering $MESH_JUDGE_VIEWS view(s) for mesh judge..."
        # meta_path="" here (last arg) — this render's own manifest is a
        # scratch artifact; the judge writes its own meta.json section below.
        "$BLENDER" --background --python "$TURNTABLE_SCRIPT" -- \
            "$CLEAN_PATH" "$MESH_JUDGE_DIR" "${OUTPUT_NAME}_judge" gif \
            "$MESH_JUDGE_VIEWS" 640 16 "" 2>&1 \
            | grep '^\[turntable\]' | { while IFS= read -r line; do printf "[pipeline] %s\n" "${line#\[turntable\] }" >&"$HUMAN_FD"; done; } || true
        JUDGE_VIEW_MANIFEST="$MESH_JUDGE_DIR/${OUTPUT_NAME}_judge_preview_manifest.json"
        JUDGE_VIEW_PATHS=()
        if [[ -f "$JUDGE_VIEW_MANIFEST" ]]; then
            while IFS= read -r line; do
                [[ -n "$line" ]] && JUDGE_VIEW_PATHS+=( "$line" )
            done < <(python3 -c "
import json, sys
m = json.load(open(sys.argv[1]))
for p in (m.get('frame_paths') or []):
    print(p)
" "$JUDGE_VIEW_MANIFEST" 2>/dev/null)
        fi
        if [[ "${#JUDGE_VIEW_PATHS[@]}" -gt 0 ]]; then
            JUDGE_STDERR_FILE="$(mktemp)"
            JUDGE_JSON_FILE="$(mktemp)"
            "$VLM_ENV/bin/python" "$JUDGE_SCRIPT" \
                --mode mesh --images "${JUDGE_VIEW_PATHS[@]}" \
                --meta "$META_PATH" --floor "$MESH_JUDGE_FLOOR" --json \
                > "$JUDGE_JSON_FILE" 2> "$JUDGE_STDERR_FILE" || true
            grep '^\[judge\]' "$JUDGE_STDERR_FILE" | { while IFS= read -r line; do printf "[pipeline] %s\n" "${line#\[judge\] }" >&"$HUMAN_FD"; done; } || true
            rm -f "$JUDGE_STDERR_FILE"
            MESH_JUDGE_SUMMARY="$(python3 -c "
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    sys.exit(0)
verdict = d.get('verdict', 0)
rejected = bool(d.get('rejected', False))
notes = d.get('notes', '')
flag = ' — likely degenerate, regenerate recommended' if rejected else ''
line = f\"3D check: {verdict:.0f}/10{flag}\"
if notes:
    line += f\" ({notes})\"
print(line)
print(verdict)
print('1' if rejected else '0')
" "$JUDGE_JSON_FILE" 2>/dev/null || true)"
            if [[ -n "$MESH_JUDGE_SUMMARY" ]]; then
                info "$(printf '%s' "$MESH_JUDGE_SUMMARY" | sed -n '1p')"
                JUDGE_MESH_VERDICT="$(printf '%s' "$MESH_JUDGE_SUMMARY" | sed -n '2p')"
                JUDGE_MESH_REJECTED_RAW="$(printf '%s' "$MESH_JUDGE_SUMMARY" | sed -n '3p')"
                if [[ "$JUDGE_MESH_REJECTED_RAW" == "1" ]]; then
                    JUDGE_MESH_REJECTED=true
                else
                    JUDGE_MESH_REJECTED=false
                fi
                # Cross-check against clean_asset.py's loose-elements count
                # before the judge's floater note reads as a hard fact (item
                # 18 failure-mode note): cleanup may have already removed
                # what the judge is now flagging as floaters.
                LOOSE_DELETED="$(python3 -c "
import json
try:
    d = json.load(open('$META_PATH'))
    v = d.get('cleanup', {}).get('loose_elements_deleted')
    print(v if v is not None else '')
except Exception:
    pass
" 2>/dev/null || true)"
                if [[ -n "$LOOSE_DELETED" && "$LOOSE_DELETED" != "0" ]]; then
                    info "  (cleanup already removed $LOOSE_DELETED loose element(s) before this judge ran)"
                fi
            fi
            rm -f "$JUDGE_JSON_FILE"
        fi
    fi
fi

# v0.3 — also stage the hero preview PNG alongside the GLB in the engine
# folder when applicable. Useful for in-editor thumbnails / quick visual
# previews without opening the asset. Same naming as the GLB (just .png).
# Silent no-op when no engine stage happened or the PNG isn't there.
if [[ -n "$ENGINE_STAGED_PATH" ]]; then
    HERO_PNG="$ASSETS_ROOT/preview/${OUTPUT_NAME}.png"
    if [[ -f "$HERO_PNG" ]]; then
        ENGINE_PNG="${ENGINE_STAGED_PATH%.glb}.png"
        cp "$HERO_PNG" "$ENGINE_PNG" 2>/dev/null \
            && info "Staged hero PNG for engine: $ENGINE_PNG" || true
    fi
fi

END_TS=$(date +%s)
DURATION=$((END_TS - START_TS))
done_ "Pipeline complete in ${DURATION}s"
done_ "Raw:    $RAW_PATH"
done_ "Clean:  $CLEAN_PATH"
[[ -n "$ENGINE_STAGED_PATH" ]] && done_ "Engine: $ENGINE_STAGED_PATH"

if [[ "$JSON_MODE" == "1" ]]; then
    ENGINE_STAGED_BOOL=false
    [[ -n "$ENGINE_STAGED_PATH" ]] && ENGINE_STAGED_BOOL=true
    json_mode_end
    JSON_EMIT_ARGS=(
        status=ok
        stage=image_to_3d
        generator="$GENERATOR"
        license_bucket="$LICENSE_BUCKET"
        input="$INPUT"
        raw_path="$RAW_PATH"
        clean_path="$CLEAN_PATH"
        engine_path="$ENGINE_STAGED_PATH"
        --int polycount_target="$POLYCOUNT"
        --int texture_resolution="$TEXTURE_RES"
        remesh="$REMESH"
        up_axis="$UP_AXIS"
        --bool skip_clean=false
        --bool engine_staged="$ENGINE_STAGED_BOOL"
        assets_root="$ASSETS_ROOT"
        manifest_path="$MANIFEST_PATH"
        project_mode="$PROJECT_MODE"
        project_root="$PROJECT_ROOT"
        project_engine="$PROJECT_ENGINE"
        --int duration_seconds="$DURATION"
        machine="$MACHINE"
        hardware_tier="$HW_TIER"
        created="$CREATED_AT"
    )
    # Item 18 — additive-only: these keys only appear when --judge-mesh ran
    # and produced a verdict, so a no-flag run's --json output is unchanged.
    if [[ -n "$JUDGE_MESH_VERDICT" ]]; then
        JSON_EMIT_ARGS+=( --float judge_mesh_verdict="$JUDGE_MESH_VERDICT" )
        JSON_EMIT_ARGS+=( --bool judge_mesh_rejected="$JUDGE_MESH_REJECTED" )
    fi
    python3 "$SCRIPT_DIR/json_emit.py" "${JSON_EMIT_ARGS[@]}"
fi
