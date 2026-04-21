#!/usr/bin/env bash
#
# Smoke test the deployed schema distribution.
# Usage: DOMAIN=schema.testsliderule.org ./scripts/smoketest.sh

set -uo pipefail

DOMAIN="${DOMAIN:-schema.testsliderule.org}"
BASE="https://$DOMAIN"

pass=0
fail=0

check() {
  local name="$1" url="$2" expect_status="$3" expect_ctype="$4"
  local status ctype
  read -r status ctype < <(
    curl -sS -o /dev/null -D - "$url" \
      | awk 'BEGIN{s="";c=""} /^HTTP\//{s=$2} tolower($1)=="content-type:"{c=$2} END{print s" "c}'
  )
  if [[ "$status" == "$expect_status" && "$ctype" == *"$expect_ctype"* ]]; then
    echo "  PASS  $name  ($status $ctype)  $url"
    pass=$((pass+1))
  else
    echo "  FAIL  $name  got='$status $ctype' want='$expect_status *$expect_ctype*'  $url"
    fail=$((fail+1))
  fi
}

echo "Smoke-testing $BASE"

check "schema.json"             "$BASE/source/schema.json"                             200 "application/json"
check "schema/core.json"        "$BASE/source/schema/core.json"                        200 "application/json"
check "schema/icesat2.json"     "$BASE/source/schema/icesat2.json"                     200 "application/json"
check "schema/gedi.json"        "$BASE/source/schema/gedi.json"                        200 "application/json"

# icesat2: field selectors + listing
check "icesat2/fields.json"     "$BASE/source/schema/icesat2/fields.json"              200 "application/json"
check "fields/atl03_ph.json"    "$BASE/source/schema/icesat2/fields/atl03_ph.json"     200 "application/json"
check "fields/atl03_geo.json"   "$BASE/source/schema/icesat2/fields/atl03_geo.json"    200 "application/json"
check "fields/atl03_corr.json"  "$BASE/source/schema/icesat2/fields/atl03_corr.json"   200 "application/json"
check "fields/atl03_bckgrd.json" "$BASE/source/schema/icesat2/fields/atl03_bckgrd.json" 200 "application/json"
check "fields/atl06.json"       "$BASE/source/schema/icesat2/fields/atl06.json"        200 "application/json"
check "fields/atl08.json"       "$BASE/source/schema/icesat2/fields/atl08.json"        200 "application/json"
check "fields/atl09.json"       "$BASE/source/schema/icesat2/fields/atl09.json"        200 "application/json"
check "fields/atl13.json"       "$BASE/source/schema/icesat2/fields/atl13.json"        200 "application/json"

# icesat2: per-API output column schemas
check "output/atl03x.json"      "$BASE/source/schema/icesat2/output/atl03x.json"       200 "application/json"
check "output/atl06x.json"      "$BASE/source/schema/icesat2/output/atl06x.json"       200 "application/json"
check "output/atl08x.json"      "$BASE/source/schema/icesat2/output/atl08x.json"       200 "application/json"
check "output/atl13x.json"      "$BASE/source/schema/icesat2/output/atl13x.json"       200 "application/json"
check "output/atl24x.json"      "$BASE/source/schema/icesat2/output/atl24x.json"       200 "application/json"

# gedi: per-API output column schemas
check "gedi/output/gedil4ax.json" "$BASE/source/schema/gedi/output/gedil4ax.json"      200 "application/json"

# Not-yet-generated domains should 404 with the JSON error body.
check "schema/swot.json (404)"  "$BASE/source/schema/swot.json"                        404 "application/json"
check "schema/cre.json  (404)"  "$BASE/source/schema/cre.json"                         404 "application/json"

# Content sanity checks (require jq; non-fatal if missing).
if command -v jq >/dev/null 2>&1; then
  echo
  echo "Body sanity checks:"
  echo "  schema.json domains + apis:"
  curl -sS "$BASE/source/schema.json" | jq -c '{version, domains: (.domains | keys), apis: (.apis | keys)}' || fail=$((fail+1))
  echo "  icesat2/fields.json:"
  curl -sS "$BASE/source/schema/icesat2/fields.json" | jq -c '{selectors: (.selectors | length)}' || fail=$((fail+1))
  echo "  fields/atl06.json field_count:"
  curl -sS "$BASE/source/schema/icesat2/fields/atl06.json" | jq -c '{field_count: (.field_count // (.fields | length? // null))}' || fail=$((fail+1))
  echo "  output/atl06x.json columns:"
  curl -sS "$BASE/source/schema/icesat2/output/atl06x.json" | jq -c '{columns: (.columns | length)}' || fail=$((fail+1))
fi

# Real OPTIONS preflight — the request a browser sends before a
# cross-origin GET. Must return 2xx with Access-Control-Allow-Origin:*
# and Access-Control-Allow-Methods containing GET.
echo
echo "CORS preflight (OPTIONS):"
preflight="$(curl -sS -X OPTIONS \
  -H 'Origin: https://example.com' \
  -H 'Access-Control-Request-Method: GET' \
  -H 'Access-Control-Request-Headers: content-type' \
  -D - "$BASE/source/schema.json" -o /dev/null)"
status=$(printf '%s\n' "$preflight" | awk '/^HTTP\//{print $2; exit}')
acao=$(  printf '%s\n' "$preflight" | awk 'tolower($1)=="access-control-allow-origin:"{print $2}'                                    | tr -d '\r')
acam=$(  printf '%s\n' "$preflight" | awk 'tolower($1)=="access-control-allow-methods:"{print substr($0, index($0,$2))}'             | tr -d '\r')

if [[ "$status" =~ ^2 && "$acao" == "*" && "$acam" == *GET* ]]; then
  echo "  PASS  OPTIONS -> status=$status, ACAO=$acao, ACAM='$acam'"
  pass=$((pass+1))
else
  echo "  FAIL  OPTIONS -> status='$status' ACAO='$acao' ACAM='$acam' (expected 2xx, ACAO=*, ACAM containing GET)"
  fail=$((fail+1))
fi

echo
echo "Summary: $pass passed, $fail failed."
exit $(( fail > 0 ? 1 : 0 ))
