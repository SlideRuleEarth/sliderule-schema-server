#!/usr/bin/env bash
#
# Stage the publishable content into build/.
#
# Runs merge.py to refresh schema-endpoints/merged/ from authored/ + generated/,
# then copies merged/ verbatim into build/ for s3 sync. No content shaping
# happens here — build.sh is pure staging.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "Running merge..."
python3 "$ROOT/schema-endpoints/merge.py"

echo "Staging merged/ -> build/..."
rm -rf "$ROOT/build"
mkdir -p "$ROOT/build"
cp -R "$ROOT/schema-endpoints/merged/"* "$ROOT/build/"

echo
echo "Build tree:"
find "$ROOT/build" -type f | sed "s|^$ROOT/build/||" | sort | sed 's/^/  /'
