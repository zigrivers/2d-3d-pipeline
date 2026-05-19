#!/usr/bin/env bash
#
# migrate_assets.sh — move generated assets from the global workspace into a
# project's assets/ directory. Useful when transitioning from "everything in
# ~/3d-pipeline/workspace/" to per-project organization.
#
# Usage:
#   migrate_assets.sh --project PATH [--names NAME1,NAME2,...] [--dry-run]
#
# Examples:
#   # Move all assets named "chest*" into the Grithkin project
#   migrate_assets.sh --project ~/games/grithkin --names chest
#
#   # Move multiple specific assets, see what would happen first
#   migrate_assets.sh --project ~/games/grithkin --names chest,sword,dragon --dry-run
#   migrate_assets.sh --project ~/games/grithkin --names chest,sword,dragon
#
#   # Move everything (careful)
#   migrate_assets.sh --project ~/games/grithkin --names "*"

set -euo pipefail

PIPELINE_ROOT="${PIPELINE_ROOT:-$HOME/3d-pipeline}"
SOURCE_WORKSPACE="$PIPELINE_ROOT/workspace"

PROJECT=""
NAMES=""
DRY_RUN=0

usage() {
    cat <<EOF
Usage: $(basename "$0") --project PATH --names NAME[,NAME...] [--dry-run]

Moves assets matching the given name patterns from the global workspace
(~/3d-pipeline/workspace/) into a project's assets/ directory.

Required:
  --project PATH        Target project root
  --names NAMES         Comma-separated list of asset name prefixes.
                        Each is matched as a prefix against filenames in
                        concept/, raw/, clean/, and print/.
                        Use "*" to move everything (be careful).

Options:
  --dry-run             Print what would be moved, don't actually move.
  -h, --help            This help.

Examples:
  $(basename "$0") --project ~/games/grithkin --names chest
  $(basename "$0") --project ~/games/grithkin --names chest,sword --dry-run
  $(basename "$0") --project ~/games/grithkin --names "*"
EOF
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --project)  PROJECT="$2";    shift 2 ;;
        --names)    NAMES="$2";      shift 2 ;;
        --dry-run)  DRY_RUN=1;       shift   ;;
        -h|--help)  usage; exit 0 ;;
        *) echo "Unknown option: $1" >&2; usage; exit 1 ;;
    esac
done

[[ -z "$PROJECT" ]] && { echo "ERROR: --project is required" >&2; usage; exit 1; }
[[ -z "$NAMES" ]] && { echo "ERROR: --names is required" >&2; usage; exit 1; }
[[ -d "$PROJECT" ]] || { echo "ERROR: project path does not exist: $PROJECT" >&2; exit 1; }
[[ -d "$SOURCE_WORKSPACE" ]] || { echo "ERROR: source workspace not found: $SOURCE_WORKSPACE" >&2; exit 1; }

PROJECT="$(cd "$PROJECT" && pwd)"

mkdir -p "$PROJECT/assets"/{concept,raw,clean,print}

COL_GREEN='\033[0;32m'
COL_BLUE='\033[0;34m'
COL_YELLOW='\033[0;33m'
COL_RESET='\033[0m'

info()  { printf "${COL_BLUE}[migrate]${COL_RESET} %s\n" "$1"; }
done_() { printf "${COL_GREEN}[migrate]${COL_RESET} %s\n" "$1"; }
plan()  { printf "${COL_YELLOW}[migrate]${COL_RESET} %s\n" "$1"; }

# Convert comma-separated names into bash patterns
IFS=',' read -ra NAME_LIST <<< "$NAMES"

# Count matches across all subdirs
TOTAL_MOVED=0

for SUBDIR in concept raw clean print; do
    SRC="$SOURCE_WORKSPACE/$SUBDIR"
    DST="$PROJECT/assets/$SUBDIR"
    [[ ! -d "$SRC" ]] && continue

    for PATTERN in "${NAME_LIST[@]}"; do
        # "*" means move everything; otherwise use prefix matching
        if [[ "$PATTERN" == "*" ]]; then
            GLOB="$SRC/*"
        else
            GLOB="$SRC/${PATTERN}*"
        fi

        # Skip silently if no matches
        compgen -G "$GLOB" >/dev/null 2>&1 || continue

        for FILE in $GLOB; do
            [[ -e "$FILE" ]] || continue
            BASENAME="$(basename "$FILE")"
            TARGET="$DST/$BASENAME"

            if [[ -e "$TARGET" ]]; then
                plan "SKIP (already exists): $TARGET"
                continue
            fi

            if [[ "$DRY_RUN" -eq 1 ]]; then
                plan "would move: $FILE -> $TARGET"
            else
                mv "$FILE" "$TARGET"
                info "moved: $BASENAME -> $SUBDIR/"
            fi
            TOTAL_MOVED=$((TOTAL_MOVED + 1))
        done
    done
done

# Manifest migration is non-trivial — print guidance rather than auto-modify
if [[ "$DRY_RUN" -eq 1 ]]; then
    done_ "Dry run complete. $TOTAL_MOVED file(s) would be moved."
else
    done_ "Migration complete. $TOTAL_MOVED file(s) moved."
fi

GLOBAL_MANIFEST="$SOURCE_WORKSPACE/asset_manifest.json"
PROJECT_MANIFEST="$PROJECT/assets/asset_manifest.json"

if [[ -f "$GLOBAL_MANIFEST" ]]; then
    cat <<EOF

The asset manifest is not auto-migrated (paths differ; one entry might be
shared with assets still in the global workspace). To migrate manifest
entries manually:

  1. Open $GLOBAL_MANIFEST
  2. Find entries for the assets you just moved
  3. Update their concept_path / raw_path / clean_path / stl_path fields
     to point at $PROJECT/assets/...
  4. Cut them from the global manifest and paste them into
     $PROJECT_MANIFEST (creating it if needed)

Or just regenerate the assets in-project — that automatically populates the
project manifest correctly.
EOF
fi
