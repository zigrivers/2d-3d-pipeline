#!/usr/bin/env bash
# Smoke tests for scripts/meta_helper.py.
# Run from anywhere: bash tools/test_meta_helper.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
HELPER="$REPO_ROOT/scripts/meta_helper.py"
SCHEMA="$REPO_ROOT/scripts/meta_schema.json"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

META="$TMP/dragon.meta.json"

fail() { echo "FAIL: $1" >&2; exit 1; }
pass() { echo "PASS: $1"; }

# 1. Merge creates the file with schema_version + asset_name
python3 "$HELPER" merge "$META" --section input \
    --data '{"width": 1024, "height": 1024, "format_original": "PNG"}'
test -f "$META" || fail "merge did not create file"
python3 -c "
import json, sys
d = json.load(open('$META'))
assert d.get('schema_version') == 1, d
assert d.get('asset_name') == 'dragon', d
assert d.get('input', {}).get('width') == 1024, d
" || fail "skeleton not seeded correctly"
pass "merge creates file with skeleton"

# 2. Second merge into the same section adds fields without clobbering
python3 "$HELPER" merge "$META" --section input \
    --data '{"aspect_ratio": 1.0, "issues": []}'
python3 -c "
import json, sys
d = json.load(open('$META'))
assert d['input']['width'] == 1024, d['input']  # preserved
assert d['input']['aspect_ratio'] == 1.0, d['input']  # added
" || fail "section update clobbered prior fields"
pass "section update preserves prior fields"

# 3. Merge into a different section doesn't touch the first
python3 "$HELPER" merge "$META" --section quality \
    --data '{"manifold": {"is_watertight": true, "hole_count": 0}}'
python3 -c "
import json, sys
d = json.load(open('$META'))
assert d['input']['width'] == 1024
assert d['quality']['manifold']['is_watertight'] is True
" || fail "cross-section write clobbered other section"
pass "cross-section writes are isolated"

# 4. Unknown section is rejected without flag
if python3 "$HELPER" merge "$META" --section bogus --data '{}' 2>/dev/null; then
    fail "unknown section should have been rejected"
fi
pass "unknown sections rejected by default"

# 5. Unknown section is allowed with --allow-unknown-section
python3 "$HELPER" merge "$META" --section future_feature \
    --data '{"placeholder": true}' --allow-unknown-section
pass "unknown sections allowed via flag"

# 6. get prints the section
OUT="$(python3 "$HELPER" get "$META" --section input)"
echo "$OUT" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d['width']==1024" \
    || fail "get section returned wrong data"
pass "get section returns expected data"

# 7. validate detects an unknown section as a structural issue (because we
#    forced future_feature in step 5, the schema check will flag it)
if python3 "$HELPER" validate "$META" --schema "$SCHEMA" >/dev/null 2>&1; then
    # Without jsonschema installed, the helper only does structural checks;
    # future_feature is detected as "unknown top-level section". Either way
    # we expect non-zero exit here.
    fail "validate should have flagged the unknown section"
fi
pass "validate catches unknown sections"

# 8. After removing the offending section, validate passes
python3 -c "
import json
d = json.load(open('$META'))
d.pop('future_feature', None)
json.dump(d, open('$META', 'w'), indent=2, sort_keys=True)
"
python3 "$HELPER" validate "$META" --schema "$SCHEMA" >/dev/null \
    || fail "validate failed on a known-good meta.json"
pass "validate passes on known-good meta.json"

# 9. Concurrent merges from two subshells preserve both writes (lock test)
META2="$TMP/concurrent.meta.json"
(
    python3 "$HELPER" merge "$META2" --section input --data '{"width": 512}' &
    python3 "$HELPER" merge "$META2" --section quality --data '{"manifold": {"is_watertight": true}}' &
    wait
)
python3 -c "
import json
d = json.load(open('$META2'))
assert d['input']['width'] == 512, d
assert d['quality']['manifold']['is_watertight'] is True, d
" || fail "concurrent merges lost data"
pass "concurrent merges are safe"

echo
echo "All meta_helper tests passed."
