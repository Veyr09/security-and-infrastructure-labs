#!/usr/bin/env bash
# Small, human-readable demonstration: 200 rows in, clean and rejects out.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$HERE/sample"
python3 "$HERE/make_sample.py" --rows 200 --out "$OUT/orders.csv"

set +e
"$HERE/target/release/csvguard" \
  --input "$OUT/orders.csv" \
  --clean "$OUT/clean.csv" \
  --rejects "$OUT/rejects.csv" \
  --rule order_id:req --rule qty:int --rule price:dec \
  --rule ordered_on:date --rule status:enum:new\|paid\|void --rule notes:max:200 \
  2> "$OUT/summary.txt"
echo "exit code: $?" >> "$OUT/summary.txt"
set -e
cat "$OUT/summary.txt"
