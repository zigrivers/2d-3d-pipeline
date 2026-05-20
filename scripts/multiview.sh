#!/usr/bin/env bash
#
# Multi-view 3D Asset Generator Wrapper (project-aware)
# v0.3.2 — Flow 9. Takes 3+ views of a subject and runs them through a
# multi-view reconstruction backend, then the same Blender cleanup + v0.3
# quality checks the single-image pipeline uses.
#
# Inputs (one of):
#   -i v0.png,v1.png,v2.png[,v3.png]   comma-separated view paths
#                                       (recommended canonical order:
#                                        front, right, back, left when 4
#                                        cardinal-angle views are used)
#   -m views.json                       explicit per-view manifest for
#                                       non-cardinal angles; see
#                                       --help for the schema
#
# Backend choice:
#   --backend trellis (default; non_commercial — same as the existing
#                      TRELLIS single-image lane) | instantmesh | openlrm
#
# The backend adapters live in tools/multiview_backends/<name>.py and
# are dispatched via system python. They write the raw GLB to
# $ASSETS_ROOT/raw/<name>_raw.glb; from there the flow is identical to
# generate.sh: clean_asset.py, mesh/texture/game-asset quality checks,
# turntable preview, engine staging.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_pipeline_lib.sh"

PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"
BLENDER="${BLENDER:-/Applications/Blender.app/Contents/MacOS/Blender}"

EXPLICIT_PROJECT=""
VIEWS=""
MANIFEST=""
BACKEND="trellis"
OUTPUT_NAME=""
POLYCOUNT=""
TEXTURE_RES=""
REMESH="quad"
UP_AXIS="y"
SKIP_CLEAN=0
SKIP_ENGINE_STAGE=0
OVERWRITE_ENGINE=0
JSON_MODE=0
PREVIEW_MODE=""

usage() {
    cat <<EOF
Usage: $(basename "$0") -i v0.png,v1.png,v2.png[,v3.png] [options]
       $(basename "$0") -m views.json [options]

One input mode is required.

Required:
  -i, --views CSV          Comma-separated view image paths (3+).
                           Canonical order when using 4 cardinal-angle
                           views: front, right, back, left.
  -m, --manifest PATH      JSON manifest of {path, view, azimuth_deg,
                           elevation_deg} per view (for non-cardinal
                           angles). One of -i or -m is required.

Project context:
  --project PATH           Force a project root (skips auto-detection)
      --no-engine-stage    Skip copying clean GLB into engine folder

Generation options:
      --backend NAME       trellis (default, non_commercial) |
                           instantmesh (unclear_risky — DQ in benchmark
                           until license review) | openlrm (commercial_safe).
  -o, --output NAME        Output name (default: derived from first view)
  -p, --polycount N        Target polycount after cleanup (default: 3000)
  -t, --texture-res N      Backend texture resolution (default: 2048)
  -r, --remesh OPT         none | triangle | quad (default: quad)
  -u, --up AXIS            y (default) | z
      --no-clean           Skip Blender cleanup; raw mesh only
      --overwrite-engine   Allow overwriting an existing engine-staged file
      --preview MODE       none | png | gif (default: tier-dependent)
      --no-preview         Alias for --preview none
      --json               Emit a final JSON result line on stdout
  -h, --help               This help

License-bucket notes (always stated in the JSON result):
  trellis      → non_commercial (CC BY-NC)
  instantmesh  → unclear_risky (auto-DQ in benchmark scoring until reviewed)
  openlrm      → commercial_safe (Apache 2.0)

Examples:
  # 4 cardinal-angle views in canonical order (front, right, back, left):
  $(basename "$0") -i front.png,right.png,back.png,left.png

  # 6 views from Zero123++ (non-cardinal angles) via a manifest:
  $(basename "$0") -m my_views.json

  # Same input, force OpenLRM instead of the default TRELLIS:
  $(basename "$0") -i front.png,right.png,back.png,left.png --backend openlrm

  # Chain into the JSON-emitting print path:
  RESULT=\$($(basename "$0") -i ... --json | tail -1)
  CLEAN=\$(printf '%s' "\$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin)['clean_path'])")
  print.sh -i "\$CLEAN" -s 50
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)           EXPLICIT_PROJECT="$2"; shift 2 ;;
        -i|--views)          VIEWS="$2";        shift 2 ;;
        -m|--manifest)       MANIFEST="$2";     shift 2 ;;
        --backend)           BACKEND="$2";      shift 2 ;;
        -o|--output)         OUTPUT_NAME="$2";  shift 2 ;;
        -p|--polycount)      POLYCOUNT="$2";    shift 2 ;;
        -t|--texture-res)    TEXTURE_RES="$2";  shift 2 ;;
        -r|--remesh)         REMESH="$2";       shift 2 ;;
        -u|--up)             UP_AXIS="$2";      shift 2 ;;
        --no-clean)          SKIP_CLEAN=1;      shift ;;
        --no-engine-stage)   SKIP_ENGINE_STAGE=1; shift ;;
        --overwrite-engine)  OVERWRITE_ENGINE=1; shift ;;
        --preview)           PREVIEW_MODE="$2"; shift 2 ;;
        --no-preview)        PREVIEW_MODE="none"; shift ;;
        --json)              JSON_MODE=1;       shift ;;
        -h|--help)           usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

# Validate input mode
if [[ -z "$VIEWS" && -z "$MANIFEST" ]]; then
    echo "ERROR: one of -i/--views or -m/--manifest is required" >&2
    usage; exit 1
fi
if [[ -n "$VIEWS" && -n "$MANIFEST" ]]; then
    echo "ERROR: pass -i OR -m, not both" >&2
    exit 1
fi

# If a manifest was supplied, expand it into a comma-separated VIEWS list.
if [[ -n "$MANIFEST" ]]; then
    [[ -f "$MANIFEST" ]] || { echo "ERROR: manifest not found: $MANIFEST" >&2; exit 1; }
    VIEWS="$(python3 -c "
import json, sys
m = json.load(open('$MANIFEST'))
items = m if isinstance(m, list) else m.get('views', [])
print(','.join(item['path'] for item in items if 'path' in item))
")"
    [[ -n "$VIEWS" ]] || { echo "ERROR: manifest produced no view paths" >&2; exit 1; }
fi

# Validate view count + existence
IFS=',' read -r -a VIEW_ARRAY <<< "$VIEWS"
if [[ "${#VIEW_ARRAY[@]}" -lt 3 ]]; then
    echo "ERROR: multi-view backends need at least 3 views (got ${#VIEW_ARRAY[@]})" >&2
    exit 1
fi
for v in "${VIEW_ARRAY[@]}"; do
    [[ -f "$v" ]] || { echo "ERROR: view not found: $v" >&2; exit 1; }
done

# Validate backend
case "$BACKEND" in
    trellis|instantmesh|openlrm) ;;
    *) echo "ERROR: --backend must be trellis, instantmesh, or openlrm (got: $BACKEND)" >&2; exit 1 ;;
esac

# Under --json, route subcommand stdout to stderr; restore at end.
[[ "$JSON_MODE" == "1" ]] && json_mode_begin

resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

# Defaults
[[ -z "$POLYCOUNT" ]]   && POLYCOUNT="$(config_default polycount 3000)"
[[ -z "$TEXTURE_RES" ]] && TEXTURE_RES="$(config_default texture_resolution 2048)"

# Derive output name from the first view's basename if not specified.
if [[ -z "$OUTPUT_NAME" ]]; then
    OUTPUT_NAME="$(basename "${VIEW_ARRAY[0]}" | sed -E 's/\.[^.]*$//; s/_(front|right|back|left|v[0-9]+)$//')"
fi

RAW_DIR="$ASSETS_ROOT/raw"
CLEAN_DIR="$ASSETS_ROOT/clean"
mkdir -p "$RAW_DIR" "$CLEAN_DIR"
RAW_PATH="$RAW_DIR/${OUTPUT_NAME}_raw.glb"
CLEAN_PATH="$CLEAN_DIR/${OUTPUT_NAME}_clean.glb"
META_PATH="${CLEAN_PATH}.meta.json"

# License bucket per backend (matches the adapter)
case "$BACKEND" in
    trellis)     LICENSE_BUCKET="non_commercial" ;;
    instantmesh) LICENSE_BUCKET="unclear_risky" ;;
    openlrm)     LICENSE_BUCKET="commercial_safe" ;;
esac

# Output helpers (mirror generate.sh)
COL_GREEN='\033[0;32m'; COL_BLUE='\033[0;34m'; COL_RED='\033[0;31m'; COL_RESET='\033[0m'
HUMAN_FD=1
[[ "$JSON_MODE" == "1" ]] && HUMAN_FD=2
info()  { printf "${COL_BLUE}[multiview]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
done_() { printf "${COL_GREEN}[multiview]${COL_RESET} %s\n" "$1" >&"$HUMAN_FD"; }
err()   { printf "${COL_RED}[multiview]${COL_RESET} %s\n" "$1" >&2; }

START_TS=$(date +%s)
CREATED_AT="$(iso_now)"
MACHINE="$(hostname_safe)"
HW_TIER="$(hardware_tier)"

if [[ "$JSON_MODE" == "1" ]]; then print_context >&2; else print_context; fi
info "Backend:  $BACKEND  (license: $LICENSE_BUCKET)"
info "Tier:     $HW_TIER  (machine: $MACHINE)"
info "Views:    ${#VIEW_ARRAY[@]}"
info "Raw:      $RAW_PATH"

# Locate the backend adapter (lives in tools/, off the embed path)
REPO_ROOT="$(cd "$SCRIPT_DIR/.." 2>/dev/null && pwd)"
BACKEND_ADAPTER="$REPO_ROOT/tools/multiview_backends/${BACKEND}.py"
if [[ ! -f "$BACKEND_ADAPTER" ]]; then
    # Installed layout (post-bundle) — adapters under workspace/multiview_backends/
    BACKEND_ADAPTER="$PIPELINE_ROOT/workspace/multiview_backends/${BACKEND}.py"
fi
[[ -f "$BACKEND_ADAPTER" ]] || {
    err "Backend adapter not found at $BACKEND_ADAPTER"
    err "  Adapters live in tools/multiview_backends/<name>.py in the repo, or"
    err "  in workspace/multiview_backends/ in a bundle install. Check your install."
    exit 1
}

# Dispatch the backend adapter; it writes the GLB to RAW_PATH.
BACKEND_START=$(date +%s)
ADAPTER_RESULT="$(python3 "$BACKEND_ADAPTER" \
    --views "$VIEWS" \
    --output-glb "$RAW_PATH" \
    --json 2>&1 || true)"
BACKEND_END=$(date +%s)

# Parse the adapter's final JSON line
ADAPTER_JSON="$(printf '%s' "$ADAPTER_RESULT" | tail -n 1)"
ADAPTER_STATUS="$(printf '%s' "$ADAPTER_JSON" | python3 -c "
import json, sys
try: print(json.loads(sys.stdin.read()).get('status', 'unknown'))
except Exception: print('unparseable')
" 2>/dev/null)"

if [[ "$ADAPTER_STATUS" != "ok" ]]; then
    err "$BACKEND backend failed: $(printf '%s' "$ADAPTER_JSON" | head -c 500)"
    if [[ "$JSON_MODE" == "1" ]]; then
        json_mode_end
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=error \
            stage=multiview \
            error=backend_failed \
            backend="$BACKEND" \
            license_bucket="$LICENSE_BUCKET" \
            views="$VIEWS" \
            adapter_result="$ADAPTER_JSON" \
            machine="$MACHINE" \
            hardware_tier="$HW_TIER" \
            created="$CREATED_AT"
    fi
    exit 1
fi

[[ -f "$RAW_PATH" ]] || { err "$BACKEND did not produce $RAW_PATH"; exit 1; }
done_ "Backend finished in $((BACKEND_END - BACKEND_START))s → $RAW_PATH"

# --- Cleanup + quality checks (identical to generate.sh from here) ---
if [[ $SKIP_CLEAN -eq 1 ]]; then
    info "Skipping cleanup (--no-clean). Final asset: $RAW_PATH"
    END_TS=$(date +%s)
    DURATION=$((END_TS - START_TS))
    if [[ "$JSON_MODE" == "1" ]]; then
        json_mode_end
        python3 "$SCRIPT_DIR/json_emit.py" \
            status=ok \
            stage=multiview \
            backend="$BACKEND" \
            license_bucket="$LICENSE_BUCKET" \
            views="$VIEWS" \
            raw_path="$RAW_PATH" \
            clean_path="" \
            --bool skip_clean=true \
            machine="$MACHINE" \
            hardware_tier="$HW_TIER" \
            --int duration_seconds="$DURATION" \
            created="$CREATED_AT"
    fi
    exit 0
fi

CLEAN_SCRIPT="$SCRIPT_DIR/clean_asset.py"
[[ -f "$CLEAN_SCRIPT" ]] || CLEAN_SCRIPT="$PIPELINE_ROOT/workspace/clean_asset.py"
[[ -f "$CLEAN_SCRIPT" ]] || { err "clean_asset.py not found"; exit 1; }
[[ -x "$BLENDER" ]] || { err "Blender not found at $BLENDER"; exit 1; }

info "Cleaning with Blender (target $POLYCOUNT polys, $UP_AXIS-up)..."
"$BLENDER" --background --python "$CLEAN_SCRIPT" -- \
    "$RAW_PATH" "$CLEAN_PATH" "$POLYCOUNT" "$UP_AXIS" "$META_PATH"
[[ -f "$CLEAN_PATH" ]] || { err "Cleanup did not produce $CLEAN_PATH"; exit 1; }

# Quality checks (mirror generate.sh)
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

# Cleanup summary (same as generate.sh)
if [[ -f "$META_PATH" ]]; then
    python3 - "$META_PATH" <<'PY' 2>/dev/null || true
import json, sys
try: data = json.load(open(sys.argv[1]))
except Exception: sys.exit(0)
c = data.get("cleanup") or {}
if not c: sys.exit(0)
dec = c.get("decimate") or {}
parts = []
n = c.get("duplicate_vertices_removed")
if n: parts.append(f"removed {n:,} duplicate points")
n = c.get("holes_filled")
if n: parts.append(f"filled {n} small gap(s)")
b, a = dec.get("before"), dec.get("after")
if b and a and b != a: parts.append(f"simplified mesh: {b:,} → {a:,} polygons")
if parts: print("[pipeline] Cleanup: " + ", ".join(parts))
PY
fi

# Engine staging (mirror generate.sh's logic)
ENGINE_STAGED_PATH=""
if [[ "$PROJECT_MODE" == "project" && $SKIP_ENGINE_STAGE -eq 0 ]]; then
    if [[ "$PROJECT_ENGINE" == "unity" || "$PROJECT_ENGINE" == "unreal" || -n "${ENGINE_PATH:-}" ]]; then
        mkdir -p "$ENGINE_PATH"
        CANDIDATE="$ENGINE_PATH/${OUTPUT_NAME}.glb"
        if [[ ! -e "$CANDIDATE" ]]; then
            ENGINE_STAGED_PATH="$CANDIDATE"
        elif [[ "$AUTO_INCREMENT" == "1" ]]; then
            n=2
            while [[ -e "$ENGINE_PATH/${OUTPUT_NAME}_${n}.glb" ]]; do n=$((n + 1)); done
            ENGINE_STAGED_PATH="$ENGINE_PATH/${OUTPUT_NAME}_${n}.glb"
            info "Engine collision avoided: writing $(basename "$ENGINE_STAGED_PATH") instead of ${OUTPUT_NAME}.glb"
        elif [[ $OVERWRITE_ENGINE -eq 1 ]]; then
            ENGINE_STAGED_PATH="$CANDIDATE"
            info "Overwriting existing engine asset (--overwrite-engine): $ENGINE_STAGED_PATH"
        else
            info "Engine file already exists at $CANDIDATE; skipping stage."
        fi
        if [[ -n "$ENGINE_STAGED_PATH" ]]; then
            cp "$CLEAN_PATH" "$ENGINE_STAGED_PATH"
            info "Staged for engine: $ENGINE_STAGED_PATH"
        fi
    fi
fi

# Turntable preview (mirror generate.sh)
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
    FRAMES=1; RESOLUTION=1024
    [[ "$PREVIEW_MODE" == "gif" ]] && { FRAMES=12; RESOLUTION=512; }
    info "Rendering preview ($PREVIEW_MODE, $FRAMES frame(s))..."
    "$BLENDER" --background --python "$TURNTABLE_SCRIPT" -- \
        "$CLEAN_PATH" "$PREVIEW_DIR" "$OUTPUT_NAME" "$PREVIEW_MODE" \
        "$FRAMES" "$RESOLUTION" 32 "$META_PATH" 2>&1 \
        | grep '^\[turntable\]' | { while IFS= read -r line; do printf "[pipeline] %s\n" "${line#\[turntable\] }" >&"$HUMAN_FD"; done; } || true
fi

# Hero PNG stage into engine (same as generate.sh)
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
    python3 "$SCRIPT_DIR/json_emit.py" \
        status=ok \
        stage=multiview \
        backend="$BACKEND" \
        license_bucket="$LICENSE_BUCKET" \
        views="$VIEWS" \
        --int view_count="${#VIEW_ARRAY[@]}" \
        raw_path="$RAW_PATH" \
        clean_path="$CLEAN_PATH" \
        engine_path="$ENGINE_STAGED_PATH" \
        meta_path="$META_PATH" \
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
