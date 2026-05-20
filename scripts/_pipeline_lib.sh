#!/usr/bin/env bash
# _pipeline_lib.sh — shared functions for asset-pipeline wrappers.
# Sourced by concept.sh, generate.sh, print.sh.
#
# Provides:
#   resolve_project_context "$EXPLICIT_PROJECT" "$PWD"
#   config_default <key> <fallback>
#   resolve_name <base_name> <directory> <extension>
#   print_context
#
# Sets these globals after resolve_project_context succeeds:
#   PROJECT_ROOT      Absolute path to project root, or "" for global mode
#   PROJECT_MODE      "project" or "global"
#   PROJECT_ENGINE    "unity", "unreal", or "none"
#   PROJECT_CONFIG    Path to .asset-pipeline.json (may not exist on disk)
#   ASSETS_ROOT       Where to put concept/raw/clean/print directories
#   ENGINE_PATH       Engine-specific final destination (Unity/Unreal only, else "")
#   MANIFEST_PATH     Path to asset_manifest.json
#   NAME_PREFIX       Optional prefix for all output filenames
#   AUTO_INCREMENT    "1" if names should auto-suffix on collision, else "0"

# --- detection helpers ---

is_unity_project() {
    local dir="$1"
    [[ -d "$dir/Assets" && -d "$dir/ProjectSettings" ]]
}

is_unreal_project() {
    local dir="$1"
    [[ -d "$dir/Content" ]] && ls "$dir"/*.uproject >/dev/null 2>&1
}

has_asset_pipeline_config() {
    local dir="$1"
    [[ -f "$dir/.asset-pipeline.json" ]]
}

# Walk up from $1 (starting dir), echo the first directory that looks like
# a project root. Echoes empty string if nothing found.
find_project_root() {
    local dir="$1"
    while [[ "$dir" != "/" && "$dir" != "" ]]; do
        if has_asset_pipeline_config "$dir" \
            || is_unity_project "$dir" \
            || is_unreal_project "$dir"; then
            echo "$dir"
            return 0
        fi
        dir="$(dirname "$dir")"
    done
    echo ""
}

# --- JSON helper: read a value from .asset-pipeline.json by dotted path ---
# Uses python3 so no jq dependency. Returns the value as a string on stdout,
# empty string if missing or unset.
# Usage: json_get path/to/config.json "defaults.polycount"

json_get() {
    local file="$1"
    local key_path="$2"
    [[ -f "$file" ]] || { echo ""; return 0; }
    KEY_PATH="$key_path" python3 - "$file" <<'PY' 2>/dev/null
import json, os, sys
try:
    with open(sys.argv[1]) as f:
        d = json.load(f)
    for k in os.environ["KEY_PATH"].split("."):
        d = d[k]
    if d is None:
        print("")
    elif isinstance(d, bool):
        print("true" if d else "false")
    else:
        print(d)
except (KeyError, TypeError, ValueError):
    print("")
PY
}

# Apply config default: look up a value in defaults.<key>, fall back to $2.
# Usage: VAL=$(config_default polycount 3000)
config_default() {
    local key="$1"
    local fallback="$2"
    local val
    val="$(json_get "$PROJECT_CONFIG" "defaults.$key")"
    if [[ -n "$val" ]]; then
        echo "$val"
    else
        echo "$fallback"
    fi
}

# --- main entry point ---
# Args: $1 = explicit --project path (may be empty), $2 = $PWD
# Reads env: PROJECT_ROOT may be set externally

resolve_project_context() {
    local explicit_project="${1:-}"
    local pwd_arg="${2:-$PWD}"

    # Priority 1: --project flag
    # Priority 2: PROJECT_ROOT env var
    # Priority 3: walk up from $PWD looking for markers
    # Priority 4: fall back to global workspace
    if [[ -n "$explicit_project" ]]; then
        PROJECT_ROOT="$(cd "$explicit_project" 2>/dev/null && pwd)" || {
            echo "ERROR: --project path does not exist: $explicit_project" >&2
            return 1
        }
    elif [[ -n "${PROJECT_ROOT:-}" ]]; then
        PROJECT_ROOT="$(cd "$PROJECT_ROOT" 2>/dev/null && pwd)" || {
            echo "ERROR: PROJECT_ROOT env var points to nonexistent dir: $PROJECT_ROOT" >&2
            return 1
        }
    else
        PROJECT_ROOT="$(find_project_root "$pwd_arg")"
    fi

    if [[ -n "$PROJECT_ROOT" ]]; then
        PROJECT_MODE="project"
        ASSETS_ROOT="$PROJECT_ROOT/assets"
        MANIFEST_PATH="$ASSETS_ROOT/asset_manifest.json"
        PROJECT_CONFIG="$PROJECT_ROOT/.asset-pipeline.json"

        # Detect engine type
        if is_unity_project "$PROJECT_ROOT"; then
            PROJECT_ENGINE="unity"
            ENGINE_PATH="$PROJECT_ROOT/Assets/Models/AI"
        elif is_unreal_project "$PROJECT_ROOT"; then
            PROJECT_ENGINE="unreal"
            ENGINE_PATH="$PROJECT_ROOT/Content/Models/AI"
        else
            PROJECT_ENGINE="none"
            ENGINE_PATH=""
        fi

        # Config can override engine_path. Relative paths are resolved
        # against PROJECT_ROOT; absolute paths used as-is.
        local config_engine_path
        config_engine_path="$(json_get "$PROJECT_CONFIG" engine_path)"
        if [[ -n "$config_engine_path" ]]; then
            if [[ "$config_engine_path" = /* ]]; then
                ENGINE_PATH="$config_engine_path"
            else
                ENGINE_PATH="$PROJECT_ROOT/$config_engine_path"
            fi
        fi

        # Config can also override engine type (e.g. "none" to disable staging)
        local config_engine
        config_engine="$(json_get "$PROJECT_CONFIG" engine)"
        if [[ -n "$config_engine" ]]; then
            PROJECT_ENGINE="$config_engine"
            if [[ "$PROJECT_ENGINE" == "none" ]]; then
                ENGINE_PATH=""
            fi
        fi

        # Naming options
        NAME_PREFIX="$(json_get "$PROJECT_CONFIG" naming.prefix)"
        local auto_inc
        auto_inc="$(json_get "$PROJECT_CONFIG" naming.auto_increment_collisions)"
        if [[ "$auto_inc" == "false" || "$auto_inc" == "0" ]]; then
            AUTO_INCREMENT="0"
        else
            AUTO_INCREMENT="1"
        fi

    else
        # Global mode fallback
        PROJECT_MODE="global"
        PROJECT_ENGINE="none"
        PROJECT_CONFIG=""
        ASSETS_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}/workspace"
        MANIFEST_PATH="$ASSETS_ROOT/asset_manifest.json"
        ENGINE_PATH="$ASSETS_ROOT/engine"
        NAME_PREFIX=""
        AUTO_INCREMENT="0"
    fi

    # Make sure all needed dirs exist (textures/ + preview/ added in v0.3).
    mkdir -p "$ASSETS_ROOT/concept" "$ASSETS_ROOT/raw" \
             "$ASSETS_ROOT/clean" "$ASSETS_ROOT/print" \
             "$ASSETS_ROOT/textures" "$ASSETS_ROOT/preview"
    [[ -n "$ENGINE_PATH" ]] && mkdir -p "$ENGINE_PATH"

    return 0
}

# Apply name prefix + collision-avoidance suffix to a base name.
# Args: $1 = base, $2 = directory to check, $3 = extension (e.g. ".png")
# Echoes the final unique name (without extension).
resolve_name() {
    local base="$1"
    local dir="$2"
    local ext="$3"
    local prefixed="${NAME_PREFIX}${base}"
    local candidate="$prefixed"
    local i=2

    if [[ "$AUTO_INCREMENT" == "1" ]]; then
        while [[ -e "$dir/${candidate}${ext}" ]]; do
            candidate="${prefixed}_${i}"
            i=$((i + 1))
        done
    fi

    echo "$candidate"
}

# --- v0.2: hardware tier, license buckets, ISO timestamps ---

# Path to the per-machine pipeline config (key=value, NOT JSON, to keep it
# distinct from per-project .asset-pipeline.json). Override with $PIPELINE_CONFIG.
PIPELINE_CONFIG_PATH="${PIPELINE_CONFIG_PATH:-$HOME/3d-pipeline/.config}"

# Read a key from PIPELINE_CONFIG_PATH; echo the value or the fallback ($2).
# Lines starting with '#' are comments. Whitespace around '=' is tolerated.
read_pipeline_config() {
    local key="$1"
    local fallback="${2:-}"
    [[ -f "$PIPELINE_CONFIG_PATH" ]] || { echo "$fallback"; return 0; }
    local val
    val="$(awk -F= -v k="$key" '
        /^[[:space:]]*#/ { next }
        {
            n = $1; sub(/^[[:space:]]+/, "", n); sub(/[[:space:]]+$/, "", n)
            if (n == k) {
                v = $0; sub(/^[^=]*=/, "", v)
                sub(/^[[:space:]]+/, "", v); sub(/[[:space:]]+$/, "", v)
                print v; exit
            }
        }
    ' "$PIPELINE_CONFIG_PATH")"
    if [[ -n "$val" ]]; then
        echo "$val"
    else
        echo "$fallback"
    fi
}

# Hardware tier — laptop (default) or studio. Read from ~/3d-pipeline/.config.
# NEVER guess from hostname; renaming a machine would silently change behaviour.
hardware_tier() {
    local tier
    tier="$(read_pipeline_config hardware_tier laptop)"
    case "$tier" in
        laptop|studio) echo "$tier" ;;
        *) echo laptop ;;
    esac
}

# Hostname, safe-ish for inclusion in JSON.
hostname_safe() {
    local h
    h="$(hostname 2>/dev/null || true)"
    [[ -n "$h" ]] || h="unknown"
    echo "$h"
}

# ISO-8601 UTC timestamp.
iso_now() {
    date -u +"%Y-%m-%dT%H:%M:%SZ"
}

# Exact license bucket for a given model name. Returns one of:
#   commercial_safe | commercial_threshold | source_available_restricted
#   non_commercial  | unclear_risky        | unknown
# These names are stable — used in code, JSON, manifest, and docs.
license_bucket_for_model() {
    case "$1" in
        z-image-turbo|flux-schnell|qwen-image) echo commercial_safe ;;
        sf3d|spar3d)                            echo commercial_threshold ;;
        flux-dev|trellis)                       echo non_commercial ;;
        # Hunyuan3D-Paint: licensed under the Tencent Hunyuan Community
        # License, which has revenue thresholds and region exclusions
        # that the user hasn't reviewed yet. Reported as unclear_risky
        # so it never accidentally becomes a default before that review.
        hunyuan3d-paint)                        echo unclear_risky ;;
        "")                                     echo unknown ;;
        *)                                      echo unknown ;;
    esac
}

# --- JSON-mode stdout redirection ---
#
# Under --json, every subcommand (mflux, SF3D, TRELLIS, Blender) prints
# progress to stdout, which would corrupt the final JSON line. The wrappers
# call json_mode_begin once after parsing --json, and json_mode_end right
# before emitting the JSON object. Between them, fd 1 is silently routed to
# stderr; the real stdout is preserved on fd 4 and restored at the end so
# only the JSON object lands on stdout.
json_mode_begin() {
    # Save real stdout to fd 4, then route fd 1 to stderr.
    exec 4>&1 1>&2
}
json_mode_end() {
    # Restore real stdout from fd 4 and close fd 4.
    exec 1>&4 4>&-
}

# Print a non-commercial-licence warning to stderr if the model is restricted.
# Does not block; the spec says warn then proceed when explicitly chosen.
warn_if_non_commercial() {
    local model="$1"
    local bucket
    bucket="$(license_bucket_for_model "$model")"
    if [[ "$bucket" == "non_commercial" ]]; then
        printf "[license] WARNING: %s is non-commercial. Output must not be used for\n" "$model" >&2
        printf "[license]          commercial projects (Grithkin, GripCraft, etc.) unless you\n" >&2
        printf "[license]          have explicitly accepted the licence restrictions.\n" >&2
    fi
}

# --- v0.3: quality-check helpers ---

# Run the input image quality check + format normalisation (item 4 in
# improvement-spec.md). On success, may update $INPUT to point at a
# normalised PNG (when the input was WebP or GIF). Writes the
# `input` section of the per-asset meta.json at $META_PATH.
#
# Requires: scripts/input_quality_check.py + pipeline-tools-env venv
# present. If either is missing, this function is a no-op so v0.2
# behaviour is preserved (this is the documented graceful fallback).
#
# Reads:  $INPUT, $ASSETS_ROOT, $OUTPUT_NAME, $META_PATH
# Writes: $INPUT (may be reassigned to the normalised path)
check_and_normalize_input() {
    local pipeline_tools="${PIPELINE_TOOLS_ENV:-${PIPELINE_ROOT:-$HOME/3d-pipeline}/pipeline-tools-env}"
    local helper="${SCRIPT_DIR:-$(dirname "${BASH_SOURCE[0]}")}/input_quality_check.py"
    if [[ ! -f "$helper" ]]; then
        helper="${PIPELINE_ROOT:-$HOME/3d-pipeline}/workspace/input_quality_check.py"
    fi
    if [[ ! -f "$helper" ]]; then
        return 0  # v0.3 feature absent — v0.2 behaviour preserved
    fi
    if [[ ! -x "$pipeline_tools/bin/python" ]]; then
        printf '[pipeline] input quality check skipped (pipeline-tools-env missing)\n' >&2
        return 0
    fi

    local result_json
    if ! result_json="$("$pipeline_tools/bin/python" "$helper" \
            --input "$INPUT" \
            --output-dir "$ASSETS_ROOT/concept" \
            --meta "$META_PATH" \
            --name "$OUTPUT_NAME" \
            --json 2>/tmp/input-check-$$.err)"; then
        local err
        err="$(cat /tmp/input-check-$$.err 2>/dev/null || true)"
        rm -f /tmp/input-check-$$.err
        printf '[pipeline] input quality check failed (continuing): %s\n' "$err" >&2
        return 0
    fi
    rm -f /tmp/input-check-$$.err

    # Update $INPUT to the normalised path if a conversion happened.
    local normalized
    normalized="$(printf '%s\n' "$result_json" \
        | python3 -c "import json,sys; d=json.loads(sys.stdin.read()); print(d.get('normalized_path') or '')" \
        2>/dev/null)"
    if [[ -n "$normalized" && -f "$normalized" ]]; then
        INPUT="$normalized"
    fi

    # Surface issues to stderr.
    printf '%s\n' "$result_json" | python3 -c "
import json, sys
d = json.loads(sys.stdin.read())
if 'error' in d:
    sys.stderr.write(f'[pipeline] input-check error: {d[\"error\"]}\n')
    if 'notes' in d:
        sys.stderr.write(f'[pipeline]   {d[\"notes\"]}\n')
for tag in d.get('issues', []):
    sys.stderr.write(f'[pipeline] input ⚠ {tag}\n')
" 2>&1 >&2 || true
}

# Print a friendly context summary at the top of each run.
print_context() {
    if [[ "$PROJECT_MODE" == "project" ]]; then
        printf "Project:  %s (%s)\n" "$PROJECT_ROOT" "$PROJECT_ENGINE"
        printf "Assets:   %s\n" "$ASSETS_ROOT"
        [[ -n "$ENGINE_PATH" ]] && printf "Engine:   %s\n" "$ENGINE_PATH"
        [[ -f "$PROJECT_CONFIG" ]] && printf "Config:   %s\n" "$PROJECT_CONFIG"
    else
        printf "Mode:     global workspace\n"
        printf "Assets:   %s\n" "$ASSETS_ROOT"
    fi
}
