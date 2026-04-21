#!/usr/bin/env bash
#
# Zip a skill directory into a .skill archive with the folder at the zip root.
# Usage: scripts/package_skill.sh <skill-name>

set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SKILL_NAME="${1:?usage: package_skill.sh <skill-name>}"
SKILL_DIR="$ROOT/skills/$SKILL_NAME"

[[ -d "$SKILL_DIR" ]] || { echo "skill dir not found: $SKILL_DIR"; exit 1; }

OUT="$ROOT/skills/${SKILL_NAME}.skill"
rm -f "$OUT"

# Zip from the skills/ parent so the folder is at the root of the zip
( cd "$ROOT/skills" && zip -r "${SKILL_NAME}.skill" "$SKILL_NAME/" \
  --exclude "*.pyc" --exclude "*__pycache__*" --exclude "*.DS_Store" )

echo
echo "Packaged: $OUT"
echo
echo "Contents (every path must start with $SKILL_NAME/):"
unzip -l "$OUT"
