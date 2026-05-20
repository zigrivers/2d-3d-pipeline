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
  -g, --generator NAME     sf3d (default) | spar3d | trellis
                           spar3d and trellis are experimental / opt-in.
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
        --json)              JSON_MODE=1;       shift ;;
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

# Resolve project context BEFORE setting output paths
resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

# Apply config defaults
[[ -z "$GENERATOR" ]]   && GENERATOR="$(config_default generator_3d sf3d)"
[[ -z "$POLYCOUNT" ]]   && POLYCOUNT="$(config_default polycount 3000)"
[[ -z "$TEXTURE_RES" ]] && TEXTURE_RES="$(config_default texture_resolution 2048)"

case "$GENERATOR" in
    sf3d|trellis|spar3d) ;;
    *) echo "ERROR: -g must be sf3d, spar3d, or trellis (got: $GENERATOR)" >&2; exit 1 ;;
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

COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
HUMAN_FD=1
[[ "$JSON_MODE" == "1" ]] && HUMAN_FD=2
info()  { printf "${COL_BLUE}[pipeline]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
done_() { printf "${COL_GREEN}[pipeline]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
err()   { printf "${COL_RED}[pipeline]${COL_RESET} %s\n" "$1" >&2; }

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
    python3 "$SCRIPT_DIR/json_emit.py" \
        status=ok \
        stage=image_to_3d \
        generator="$GENERATOR" \
        license_bucket="$LICENSE_BUCKET" \
        input="$INPUT" \
        raw_path="$RAW_PATH" \
        clean_path="$CLEAN_PATH" \
        engine_path="$ENGINE_STAGED_PATH" \
        --int polycount_target="$POLYCOUNT" \
        --int texture_resolution="$TEXTURE_RES" \
        remesh="$REMESH" \
        up_axis="$UP_AXIS" \
        --bool skip_clean=false \
        --bool engine_staged="$ENGINE_STAGED_BOOL" \
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
