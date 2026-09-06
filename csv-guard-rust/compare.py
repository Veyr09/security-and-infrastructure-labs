"""The same rules in Python's csv module, for an honest comparison.

Not a strawman: this streams too, uses the standard library's C-backed reader,
and applies identical checks. It is the code most people would actually write
for this job, which is the point of comparing against it.
"""
import argparse
import csv
import sys

STATUSES = {"new", "paid", "void"}


def is_int(value: str) -> bool:
    try:
        int(value.strip())
        return True
    except ValueError:
        return False


def is_dec(value: str) -> bool:
    try:
        number = float(value.strip())
        return number == number and abs(number) != float("inf")
    except ValueError:
        return False


def is_date(value: str) -> bool:
    parts = value.strip().split("-")
    if len(parts) != 3 or len(parts[0]) != 4 or len(parts[1]) != 2 or len(parts[2]) != 2:
        return False
    try:
        year, month, day = (int(part) for part in parts)
    except ValueError:
        return False
    if not 1000 <= year <= 9999 or not 1 <= month <= 12:
        return False
    leap = (year % 4 == 0 and year % 100 != 0) or year % 400 == 0
    lengths = [31, 29 if leap else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    return 1 <= day <= lengths[month - 1]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True)
    parser.add_argument("--clean")
    args = parser.parse_args()

    read_rows = clean_rows = rejected_rows = 0
    with open(args.input, newline="", encoding="utf-8") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        index = {name: position for position, name in enumerate(header)}
        clean = open(args.clean, "w", newline="", encoding="utf-8") if args.clean else None
        # LF, so a byte comparison against the Rust output is meaningful.
        writer = csv.writer(clean, lineterminator="\n") if clean else None
        if writer:
            writer.writerow(header)
        for row in reader:
            read_rows += 1
            ok = (
                len(row) == len(header)
                and row[index["order_id"]].strip() != ""
                and is_int(row[index["qty"]])
                and is_dec(row[index["price"]])
                and is_date(row[index["ordered_on"]])
                and row[index["status"]].strip() in STATUSES
                and len(row[index["notes"]].strip()) <= 200
            )
            if ok:
                clean_rows += 1
                if writer:
                    writer.writerow(row)
            else:
                rejected_rows += 1
        if clean:
            clean.close()
    print(f"rows read      {read_rows}", file=sys.stderr)
    print(f"rows clean     {clean_rows}", file=sys.stderr)
    print(f"rows rejected  {rejected_rows}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
