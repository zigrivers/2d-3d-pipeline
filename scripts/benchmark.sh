#!/usr/bin/env bash
#
# Model bake-off harness (v0.2).
#
# Runs the same prompts through one or more 2D models and one or more 3D
# generators and writes a structured results file you can review later
# (or hand to Claude Code for ranking). The actual orchestration lives in
# scripts/model_bakeoff.py — this wrapper exists so you can run it the
# same way you run the rest of the pipeline.
#
# Output:
#   <assets_root>/benchmarks/<timestamp>/benchmark_results.json
#
# Per-result fields include status / model / license_bucket / paths /
# duration / hardware_tier / machine, plus a manual scoring scaffold
# (prompt_match, front_accuracy, …) initialised to null so a later
# review pass can fill them in.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=/dev/null
source "$SCRIPT_DIR/_pipeline_lib.sh"

PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"

EXPLICIT_PROJECT=""
SUITE="default"
PROMPTS_FILE=""
GENERATORS="sf3d"
MODELS_2D="z-image-turbo"
COUNT=1
POLYCOUNT=""
TEXTURE_RES=""
SKIP_2D=0
SKIP_3D=0
JSON_MODE=0
DRY_RUN=0

usage() {
    cat <<EOF
Usage: $(basename "$0") [options]

Run a model bake-off across one or more 2D models and 3D generators.

Project context:
  --project PATH               Force a project root (skips auto-detection)

Suite selection:
  --suite NAME                 default | quick | custom (default: default)
  --prompts-file PATH          One prompt per line; overrides the built-in
                               suite. Implies --suite custom.

Models:
  --generators LIST            Comma-separated list (default: sf3d).
                               Allowed: sf3d, spar3d, trellis
  --models-2d LIST             Comma-separated list (default: z-image-turbo).
                               Allowed: z-image-turbo, flux-schnell, flux-dev

Generation knobs (forwarded to wrappers):
  --count N                    Concept images per prompt (default: 1)
  --polycount N                Override target polycount for the 3D pass
  --texture-resolution N       Override SF3D texture resolution

Skip flags:
  --skip-2d                    Reuse existing concept images instead of
                               regenerating them
  --skip-3d                    Concept-only bake-off (2D models only)

Output / behaviour:
  --json                       Emit the path to the results JSON on stdout
  --dry-run                    Print the work plan; do not run anything
  -h, --help                   This help

Examples:
  # Quick studio sanity check
  $(basename "$0") --suite quick

  # Full bake-off across sf3d + spar3d
  $(basename "$0") --suite default --generators sf3d,spar3d

  # Concept-only sanity across both 2D models
  $(basename "$0") --models-2d z-image-turbo,flux-schnell --skip-3d
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)              EXPLICIT_PROJECT="$2"; shift 2 ;;
        --suite)                SUITE="$2";             shift 2 ;;
        --prompts-file)         PROMPTS_FILE="$2";      shift 2 ;;
        --generators)           GENERATORS="$2";        shift 2 ;;
        --models-2d)            MODELS_2D="$2";         shift 2 ;;
        --count)                COUNT="$2";             shift 2 ;;
        --polycount)            POLYCOUNT="$2";         shift 2 ;;
        --texture-resolution)   TEXTURE_RES="$2";       shift 2 ;;
        --skip-2d)              SKIP_2D=1;              shift   ;;
        --skip-3d)              SKIP_3D=1;              shift   ;;
        --json)                 JSON_MODE=1;            shift   ;;
        --dry-run)              DRY_RUN=1;              shift   ;;
        -h|--help)              usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

case "$SUITE" in default|quick|custom) ;;
    *) echo "ERROR: --suite must be default, quick, or custom" >&2; exit 1 ;;
esac

resolve_project_context "$EXPLICIT_PROJECT" "$PWD"

BAKEOFF_PY="$SCRIPT_DIR/model_bakeoff.py"
[[ -f "$BAKEOFF_PY" ]] || { echo "ERROR: model_bakeoff.py not found at $BAKEOFF_PY" >&2; exit 1; }

# Build the python invocation. The harness reads the same env (PIPELINE_ROOT,
# hardware_tier via _pipeline_lib.sh) and calls back into concept.sh /
# generate.sh under --json for structured results.
ARGS=(
    --assets-root "$ASSETS_ROOT"
    --manifest-path "$MANIFEST_PATH"
    --project-mode "$PROJECT_MODE"
    --project-root "$PROJECT_ROOT"
    --project-engine "$PROJECT_ENGINE"
    --hardware-tier "$(hardware_tier)"
    --machine "$(hostname_safe)"
    --script-dir "$SCRIPT_DIR"
    --suite "$SUITE"
    --generators "$GENERATORS"
    --models-2d "$MODELS_2D"
    --count "$COUNT"
)
[[ -n "$PROMPTS_FILE" ]] && ARGS+=( --prompts-file "$PROMPTS_FILE" )
[[ -n "$POLYCOUNT" ]]    && ARGS+=( --polycount "$POLYCOUNT" )
[[ -n "$TEXTURE_RES" ]]  && ARGS+=( --texture-resolution "$TEXTURE_RES" )
[[ $SKIP_2D -eq 1 ]]     && ARGS+=( --skip-2d )
[[ $SKIP_3D -eq 1 ]]     && ARGS+=( --skip-3d )
[[ $DRY_RUN -eq 1 ]]     && ARGS+=( --dry-run )
[[ $JSON_MODE -eq 1 ]]   && ARGS+=( --json )

exec python3 "$BAKEOFF_PY" "${ARGS[@]}"
