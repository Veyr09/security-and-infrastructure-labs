# Rates sync

Keeps an Excel workbook of daily exchange rates up to date from the Frankfurter API (European Central Bank reference rates). Each run fetches only the days missing since the last row, so it is safe to run every day from a scheduler: a second run on the same day adds nothing, and earlier rows are never rewritten.

## What it does
- New file: fetches the last 90 days (or from `--since`) in one request and writes a **Rates** sheet (date, base, one column per currency) and a **Summary** sheet (first, latest, low, high and change over the period, per currency).
- Existing file: reads the last date, asks the API only for the days after it, appends them, and refuses to duplicate a date.
- Refuses to write into a workbook built for a different base or set of currencies, so two jobs cannot corrupt each other's file.
- Retries network errors and 5xx responses with backoff; any other error stops with a clear message and a non-zero exit code, which a scheduler can alert on.

## Run it
    pip install -r requirements.txt
    python sync_rates.py --out sample/rates.xlsx --base USD --symbols EUR,GBP,PLN --since 2026-06-01
    python sync_rates.py --out sample/rates.xlsx --base USD --symbols EUR,GBP,PLN
    python chart.py sample/rates.xlsx --out sample/rates_indexed.png

The first command builds the file; the second is what a daily schedule runs. Sample output from a run on 2026-09-05:

    70 new day(s) added; sample/rates.xlsx holds 70 rows from 2026-06-01 to 2026-09-04
    0 new day(s) added; sample/rates.xlsx holds 70 rows from 2026-06-01 to 2026-09-04

## The chart
`chart.py` indexes every currency to 100 on the first day, so EUR (about 0.86 per dollar) and PLN (about 3.7) share one axis honestly. It deliberately does not use a second y-axis, which would invent a relationship between the two scales.

## Scheduling
Windows Task Scheduler: run `python C:\path\to\sync_rates.py --out C:\path\to\rates.xlsx` daily. Cron: `15 7 * * * cd /path/to/rates-sync && python sync_rates.py --out rates.xlsx`. The exit code is 0 on success and 1 on any failure.

## Tests
    python -m pytest -q

13 tests cover the API parsing (including the weekend padding the API adds), retries, the 404 and bad-JSON paths, merging without duplicates, the summary, and the create-then-append cycle against a real workbook in a temp folder. No network needed.
