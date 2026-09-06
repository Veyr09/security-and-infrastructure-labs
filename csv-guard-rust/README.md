# csvguard — validate a CSV against column rules, in one streaming pass

A command-line tool in Rust, no dependencies. It splits a CSV into the rows that
satisfy every rule and the rows that do not, and explains each rejection by line,
column, value and reason. Memory is bounded by the widest single record rather
than by the size of the file, so a 50 GB export costs about what a 50 KB one does.

The point of the piece is not that Rust is fast. It is that the rejects file is
the deliverable: a client opens that, not the source.

## Run it

```
cargo test                 # 18 tests
cargo build --release

./target/release/csvguard \
  --input orders.csv --clean clean.csv --rejects rejects.csv \
  --rule order_id:req --rule qty:int --rule price:dec \
  --rule ordered_on:date --rule status:enum:new\|paid\|void --rule notes:max:200
```

Exit codes: `0` every row clean, `1` some rejected, `2` bad usage, `3` I/O error.
A scheduled job that pipes a supplier feed through this fails loudly instead of
quietly writing a short file.

Rules: `req` non-empty · `int` whole number · `dec` number · `date` YYYY-MM-DD and
the day must exist · `enum:a|b|c` · `max:N` characters.

## What a rejection looks like

From `sample/rejects.csv`, produced by `sample_run.sh` over 200 generated rows:

```
line,column,value,reason
21,qty,"1,000","not a whole number: ""1,000"""
41,price,$130.60,"not a number: ""$130.60"""
61,ordered_on,2026-02-30,"day 30 does not exist in that month: ""2026-02-30"""
81,status,PAID,"""PAID"" is not one of new, paid, void"
101,ordered_on,,"row has 3 fields, expected at least 4"
121,order_id,,required but empty
```

200 rows in, 190 clean, 10 rejected. Line 101 is a ragged row and reports once per
missing column. `2026-02-30` is the kind of value that passes a regex and then
breaks a database insert three steps later, so the date rule checks the calendar.

## Measured, on 5,000,000 rows

`bench.sh` generates a 196 MB file with one defective row in twenty and runs both
implementations over it. Ubuntu on WSL2, Rust 1.98.1, Python 3.13.

| | wall clock | peak resident memory |
|---|---|---|
| csvguard (Rust) | **1.66 s** | **2,308 KB** |
| Python `csv` module, same rules | 6.99 s | 15,664 KB |

Both read 5,000,000 rows, kept 4,750,000 and rejected 250,000. Roughly 4× the
throughput and a seventh of the memory.

The Python side is not a strawman: it streams, uses the standard library's
C-backed reader, and applies identical checks. It is the code most people would
actually write for this job, which is what makes the comparison worth anything.

**Cross-check:** `cross_check.sh` compares the two clean files byte for byte. They
are **identical** across 4,754,766 lines. Two independent implementations agreeing
exactly is worth more as evidence of correctness than either one's test suite.

(4,754,766 lines for 4,750,000 rows, because one row in 997 carries an embedded
newline and therefore occupies two physical lines. That is also why counting lines
in a CSV to count records is unreliable.)

## The CSV reader

`src/csv.rs` is a byte-level RFC 4180 reader rather than a line splitter, because
splitting on commas is wrong the moment a field contains a comma, a quote, or a
newline — and real exports contain all three. It handles quoted fields, doubled
quotes inside them, embedded newlines, CRLF, a final row with no trailing newline,
and blank lines. Nine tests cover exactly those cases, including a round trip
through the writer.

Invalid UTF-8 is replaced rather than fatal. One bad byte in a 10 GB export should
not end the run; the row lands in the rejects file with the rest.

## Two bugs found in the test data, which is the honest part

Both were in `make_sample.py`, and both were caught by the cross-check rather than
by a test:

1. The generator wrote the awkward `notes` field with its inner quotes not
   doubled. The file was invalid CSV, the two parsers read it differently, and the
   clean outputs disagreed by 4,765 rows.
2. It then wrote `1,000` unquoted for the "thousands separator" defect. That is an
   extra column, not a bad integer, so every field after it shifted and the
   rejects file blamed `ordered_on` for holding `316.61`.

The generator now writes through `csv.writer`. Both defects are the sort that look
like a tool bug and are actually a data bug, which is the entire reason a rejects
file has to name the value it rejected.

## Files

- `src/csv.rs` — streaming RFC 4180 reader and writer, 9 tests
- `src/rules.rs` — the six rules and their failure messages, 9 tests
- `src/main.rs` — argument parsing, column resolution, the streaming loop
- `make_sample.py` — deterministic generator, seeded
- `compare.py` — the same rules in Python, for the comparison and cross-check
- `bench.sh`, `cross_check.sh`, `sample_run.sh`
- `sample/` — captured output from the runs quoted above

## Honest scope

Built for this portfolio, not client work. The measurements are from the scripts
in this folder on one machine; they will differ on other hardware. Nothing here
was run against anyone else's system or data.
