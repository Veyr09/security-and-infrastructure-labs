"""Generate a CSV with a known, seeded share of bad rows.

Deterministic, so the numbers quoted in README.md can be reproduced exactly.

Written through csv.writer rather than string formatting. An earlier version
built the lines by hand and emitted `1,000` unquoted, which turned an intended
"this value is not an integer" defect into a row with an extra column and shifted
every field after it. Two conforming parsers then disagreed about the file. The
defects below are meant to be semantic, so the file itself has to be valid.
"""
import argparse
import csv
import random
import sys

SEED = 20260906
STATUSES = ["new", "paid", "void"]
BAD_EVERY = 20          # one row in twenty carries a defect
DEFECT_KINDS = 6
AWKWARD_NOTES_EVERY = 997
HEADER = ["order_id", "qty", "price", "ordered_on", "status", "notes"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--out", default="-")
    args = parser.parse_args()

    rng = random.Random(SEED)
    handle = sys.stdout if args.out == "-" else open(args.out, "w", encoding="utf-8", newline="")
    writer = csv.writer(handle, lineterminator="\n")
    try:
        writer.writerow(HEADER)
        for row_number in range(1, args.rows + 1):
            row = [
                f"ORD-{row_number:08d}",
                str(rng.randint(1, 40)),
                f"{rng.uniform(1, 500):.2f}",
                f"2026-0{rng.randint(1, 9)}-{rng.randint(1, 28):02d}",
                rng.choice(STATUSES),
                "ok",
            ]

            if row_number % AWKWARD_NOTES_EVERY == 0:
                # Quote, comma and newline in one field: the three things that
                # break a naive split-on-comma reader.
                row[5] = 'has "quotes", a comma and\na newline'

            if row_number % BAD_EVERY == 0:
                match row_number // BAD_EVERY % DEFECT_KINDS:
                    case 0:
                        row[0] = ""                     # required but empty
                    case 1:
                        row[1] = "1,000"                # thousands separator
                    case 2:
                        row[2] = f"${row[2]}"           # currency symbol
                    case 3:
                        row[3] = "2026-02-30"           # day that does not exist
                    case 4:
                        row[4] = "PAID"                 # wrong case for the enum
                    case _:
                        row = row[:3]                   # ragged: columns missing
            writer.writerow(row)
    finally:
        if handle is not sys.stdout:
            handle.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
