#!/usr/bin/env bash
# Render Mermaid diagrams to SVG.
#   tools/diagram.sh                       # every docs/diagrams/*.mmd -> .svg next to it
#   tools/diagram.sh path/a.mmd [b.mmd]    # specific files
#   FORMAT=png tools/diagram.sh ...        # png instead of svg
set -euo pipefail
MMDC_VERSION="12.0.0"
FORMAT="${FORMAT:-svg}"
cd "$(dirname "$0")/.."

files=("$@")
if [ ${#files[@]} -eq 0 ]; then
  shopt -s nullglob
  files=(docs/diagrams/*.mmd)
fi
[ ${#files[@]} -eq 0 ] && { echo "diagram: no .mmd files found"; exit 0; }

status=0
for f in "${files[@]}"; do
  out="${f%.mmd}.${FORMAT}"
  if npx -y "@mermaid-js/mermaid-cli@${MMDC_VERSION}" -q -i "$f" -o "$out" -b transparent; then
    echo "diagram: $f -> $out"
  else
    echo "diagram: FAILED $f" >&2; status=1
  fi
done
exit $status
