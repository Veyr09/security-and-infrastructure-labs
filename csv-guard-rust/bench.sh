#!/usr/bin/env bash
# Generate a large CSV, then time csvguard and the Python equivalent on it.
# Run inside Linux; uses /usr/bin/time -v for peak resident memory.
set -euo pipefail
ROWS="${1:-5000000}"
WORK="${2:-/tmp/csvguard-bench}"
HERE="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$WORK"
echo "generating $ROWS rows ..."
python3 "$HERE/make_sample.py" --rows "$ROWS" --out "$WORK/orders.csv"
ls -lh "$WORK/orders.csv" | awk '{print "input size:", $5}'

RULES=(--rule order_id:req --rule qty:int --rule price:dec
       --rule ordered_on:date --rule status:enum:new\|paid\|void --rule notes:max:200)

echo
echo "===== csvguard (Rust) ====="
/usr/bin/time -v "$HERE/target/release/csvguard" --input "$WORK/orders.csv" \
    --clean "$WORK/clean-rs.csv" --rejects "$WORK/rejects-rs.csv" "${RULES[@]}" \
    2>&1 | grep -E 'rows |Elapsed \(wall|Maximum resident' || true

echo
echo "===== python csv module, same rules ====="
/usr/bin/time -v python3 "$HERE/compare.py" --input "$WORK/orders.csv" \
    --clean "$WORK/clean-py.csv" \
    2>&1 | grep -E 'rows |Elapsed \(wall|Maximum resident' || true

echo
echo "outputs identical:"
if cmp -s "$WORK/clean-rs.csv" "$WORK/clean-py.csv"; then echo "  yes"; else echo "  NO - differ"; fi
