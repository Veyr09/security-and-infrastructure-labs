#!/usr/bin/env bash
# Re-run the Python implementation and compare its output byte for byte with the
# Rust one. Same rules, same input: the files should be identical, and if they
# are not, one of the two parsers is wrong.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
WORK="${1:-/tmp/csvguard-bench}"
cd "$WORK"
python3 "$HERE/compare.py" --input orders.csv --clean clean-py.csv 2>&1 | tail -3
echo
if cmp -s clean-rs.csv clean-py.csv; then
  echo "cross-check: outputs are byte-for-byte identical"
  wc -l clean-rs.csv clean-py.csv | head -2
else
  echo "cross-check: outputs DIFFER"
  cmp clean-rs.csv clean-py.csv | head -2
fi
