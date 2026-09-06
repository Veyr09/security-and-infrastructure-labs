# Spreadsheet cleanup

Turns a messy orders export into an Excel workbook you can actually use, and never loses a row quietly: anything it cannot trust goes to an Issues sheet with the row number and the reason.

## What it fixes
- Whitespace, casing and double spaces in customer names, categories and emails.
- Dates written seven different ways (`2026-03-05`, `05/03/2026`, `05.03.2026`, `5 Mar 2026`, `March 5, 2026`, ...) become real dates. Slash and dot forms are read day-first; the list is one constant in `cleaning.py`.
- Prices written as `$1,234.50`, `USD 1,234.50` or `1234.5` become numbers.
- Quantities become whole numbers.
- Exact duplicate rows are dropped.
- Two rows with the same order id but different details: the first is kept, the second is reported.
- A row with an unreadable date, price or quantity, or a negative price, goes to Issues instead of Clean. A bad email is reported but the order is kept.

## What comes out
One workbook with four sheets:
- **Clean**: the tidy rows plus a `line_total` column, sorted by date.
- **By month**: orders, units and revenue per month.
- **By category**: the same per category, biggest first.
- **Issues**: spreadsheet row number, order id, field, problem, and the original value.

## Run it
    pip install -r requirements.txt
    python make_sample.py
    python clean_orders.py sample/orders_raw.csv --out sample/orders_clean.xlsx
    python chart.py sample/orders_clean.xlsx --out sample/revenue_by_month.png

`make_sample.py` writes a seeded 311-row export with the kinds of mess above, so the result below is reproducible:

    311 rows in, 8 exact duplicates dropped, 17 rows with problems, 288 clean rows out

## Adapting it to another export
Column names live in `REQUIRED_COLUMNS` and date formats in `DATE_FORMATS`, both at the top of `cleaning.py`. The rules themselves are small functions (`parse_date`, `parse_money`, `parse_quantity`, `_normalise`), each with its own tests.

## Tests
    python -m pytest -q

37 tests cover every parser, every rule, the Issues bookkeeping, the workbook writer and the error paths (missing file, missing columns).
