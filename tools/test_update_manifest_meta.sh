#!/usr/bin/env bash
# Smoke tests for the v0.3 --meta-json flag on update_manifest.py.
# Run from anywhere: bash tools/test_update_manifest_meta.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
UPDATER="$REPO_ROOT/skill/scripts/update_manifest.py"
HELPER="$REPO_ROOT/scripts/meta_helper.py"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

MANIFEST="$TMP/asset_manifest.json"
META="$TMP/dragon_clean.glb.meta.json"

fail() { echo "FAIL: $1" >&2; exit 1; }
pass() { echo "PASS: $1"; }

# Build a representative meta.json using meta_helper.py
python3 "$HELPER" merge "$META" --section input \
    --data '{"width": 1024, "height": 1024, "format_original": "PNG", "issues": []}'
python3 "$HELPER" merge "$META" --section preprocessing \
    --data '{"bg_removal": {"applied": true, "model": "u2net", "alpha_mean": 0.42}}'
python3 "$HELPER" merge "$META" --section generation \
    --data '{"backend": "sf3d", "license_bucket": "commercial_threshold", "polycount_target": 3000, "duration_seconds": 18.4}'
python3 "$HELPER" merge "$META" --section cleanup \
    --data '{"duplicate_vertices_removed": 47, "holes_filled": 2}'
python3 "$HELPER" merge "$META" --section quality \
    --data '{"manifold": {"is_watertight": true, "hole_count": 0}, "textures": {"issues": []}}'
python3 "$HELPER" merge "$META" --section preview \
    --data '{"mode": "png", "hero_png_path": "/tmp/dragon.png", "duration_seconds": 1.1}'
python3 "$HELPER" merge "$META" --section clip \
    --data '{"similarity": 0.84, "model": "ViT-L-14"}'

# 1. Manifest doesn't exist -> updater creates it + entry with meta-merged data
python3 "$UPDATER" \
    --manifest "$MANIFEST" \
    --name dragon \
    --concept /tmp/dragon_concept.png \
    --generator sf3d \
    --category prop \
    --meta-json "$META" >/dev/null

test -f "$MANIFEST" || fail "manifest not created"

# 2. Check that the merged sections landed in the right places
python3 -c "
import json, sys
m = json.load(open('$MANIFEST'))
e = m['assets']['dragon']

# generation.input from meta.input
assert e['generation']['input']['width'] == 1024, e['generation']
# generation.input.preprocessing from meta.preprocessing
assert e['generation']['input']['preprocessing']['bg_removal']['applied'] is True, e['generation']
# generation field-level merge
assert e['generation']['backend'] == 'sf3d', e['generation']
assert e['generation']['polycount_target'] == 3000, e['generation']
# model.license_bucket from generation.license_bucket
assert e['model']['license_bucket'] == 'commercial_threshold', e.get('model')
# quality consolidates cleanup, quality.*, preview, clip
assert e['quality']['cleanup']['duplicate_vertices_removed'] == 47, e['quality']
assert e['quality']['manifold']['is_watertight'] is True, e['quality']
assert e['quality']['textures']['issues'] == [], e['quality']
assert e['quality']['preview']['mode'] == 'png', e['quality']
assert e['quality']['clip']['similarity'] == 0.84, e['quality']
print('all merged fields present')
" || fail "meta merge did not land in expected places"
pass "meta-json sections merge into expected manifest fields"

# 3. Explicit --license-bucket arg wins over meta.generation.license_bucket
MANIFEST2="$TMP/asset_manifest2.json"
python3 "$UPDATER" \
    --manifest "$MANIFEST2" \
    --name dragon \
    --concept /tmp/dragon_concept.png \
    --generator sf3d \
    --category prop \
    --license-bucket non_commercial \
    --meta-json "$META" >/dev/null
python3 -c "
import json
m = json.load(open('$MANIFEST2'))
b = m['assets']['dragon']['model']['license_bucket']
assert b == 'non_commercial', f'explicit arg should have won, got {b}'
" || fail "explicit license-bucket arg should override meta.generation.license_bucket"
pass "explicit --license-bucket beats meta-derived value"

# 4. Missing meta.json file -> warning + manifest still updates with existing flags
MANIFEST3="$TMP/asset_manifest3.json"
python3 "$UPDATER" \
    --manifest "$MANIFEST3" \
    --name dragon \
    --concept /tmp/dragon_concept.png \
    --generator sf3d \
    --category prop \
    --meta-json "$TMP/does-not-exist.json" 2>/dev/null >/dev/null
test -f "$MANIFEST3" || fail "missing meta.json should not abort the update"
pass "missing meta.json file is non-fatal (warning only)"

# 5. Re-running with the same meta.json is idempotent
SIZE_BEFORE=$(wc -c < "$MANIFEST")
python3 "$UPDATER" \
    --manifest "$MANIFEST" \
    --name dragon \
    --concept /tmp/dragon_concept.png \
    --generator sf3d \
    --category prop \
    --meta-json "$META" >/dev/null
SIZE_AFTER=$(wc -c < "$MANIFEST")
test "$SIZE_BEFORE" = "$SIZE_AFTER" || fail "idempotent re-run changed manifest size ($SIZE_BEFORE -> $SIZE_AFTER)"
pass "re-running with the same meta.json is idempotent"

# 6. Existing v3 manifest from before --meta-json still works
LEGACY="$TMP/legacy_v3.json"
cat > "$LEGACY" <<'EOF'
{
  "version": 3,
  "assets": {
    "existing": {
      "name": "existing",
      "concept_path": "/tmp/existing.png",
      "generator": "sf3d",
      "category": "prop",
      "raw_path": "/tmp/raw.glb",
      "clean_path": "/tmp/clean.glb",
      "polycount_target": 3000,
      "created": "2026-01-01T00:00:00",
      "updated": "2026-01-01T00:00:00",
      "model": {"license_bucket": "commercial_threshold"}
    }
  }
}
EOF
python3 "$UPDATER" \
    --manifest "$LEGACY" \
    --name newentry \
    --concept /tmp/dragon_concept.png \
    --generator sf3d \
    --category prop \
    --meta-json "$META" >/dev/null
python3 -c "
import json
m = json.load(open('$LEGACY'))
assert 'existing' in m['assets'], 'old entry was wiped'
assert m['assets']['existing']['generator'] == 'sf3d'
assert 'newentry' in m['assets']
assert m['assets']['newentry']['quality']['manifold']['is_watertight'] is True
" || fail "backward-compat with existing v3 manifest broken"
pass "merging into an existing v3 manifest preserves prior entries"

echo
echo "All update_manifest --meta-json tests passed."
