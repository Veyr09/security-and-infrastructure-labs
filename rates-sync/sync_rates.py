"""Keep a spreadsheet of daily exchange rates up to date. Each run fetches only the days that are missing.

Usage:
    python sync_rates.py --out rates.xlsx --base USD --symbols EUR,GBP,PLN
    python sync_rates.py --out rates.xlsx --base USD --symbols EUR,GBP,PLN --since 2026-01-01

Run it again tomorrow, or from a scheduler, and it appends the new day without touching earlier rows.
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests
from openpyxl.utils import get_column_letter

from rates import BASE_COLUMN, DATE_COLUMN, SyncError, fetch_rates, merge, summarise

SHEET_RATES = "Rates"
SHEET_SUMMARY = "Summary"
DEFAULT_LOOKBACK_DAYS = 90
USER_AGENT = "rates-sync/1.0 (portfolio sample)"
RATE_FORMAT = "0.0000"
DATE_FORMAT = "yyyy-mm-dd"
COLUMN_WIDTH = 13


def load_existing(path: Path, symbols: list[str]) -> pd.DataFrame | None:
    """The Rates sheet of an earlier run, or None for a new file. Refuses a file built for other currencies."""
    if not path.exists():
        return None
    try:
        frame = pd.read_excel(path, sheet_name=SHEET_RATES)
    except ValueError as exc:
        raise SyncError(f"{path} has no '{SHEET_RATES}' sheet") from exc
    missing = [column for column in [DATE_COLUMN, BASE_COLUMN, *symbols] if column not in frame.columns]
    if missing:
        raise SyncError(f"{path} lacks columns {', '.join(missing)}; use a new file for a different base or symbols")
    frame[DATE_COLUMN] = pd.to_datetime(frame[DATE_COLUMN])
    return frame


def sync(path: Path, base: str, symbols: list[str], since: date | None, today: date, session) -> tuple[pd.DataFrame, int]:
    """Bring the workbook up to `today`. Returns the full table and how many days were added."""
    existing = load_existing(path, symbols)
    if existing is not None and not existing.empty:
        start = existing[DATE_COLUMN].max().date() + timedelta(days=1)
    else:
        start = since or today - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    if start > today:
        logging.info("already up to date through %s", start - timedelta(days=1))
        return existing, 0

    fresh = fetch_rates(base, symbols, start, today, session)
    rates, added = merge(existing, fresh)
    if rates.empty:
        raise SyncError(f"the API returned no rates between {start} and {today}")
    write_workbook(rates, summarise(rates, symbols), path)
    return rates, added


def write_workbook(rates: pd.DataFrame, summary: pd.DataFrame, path: Path) -> None:
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in ((SHEET_RATES, rates), (SHEET_SUMMARY, summary)):
            frame.to_excel(writer, sheet_name=name, index=False)
            _format_sheet(writer.sheets[name], frame)


def _format_sheet(sheet, frame: pd.DataFrame) -> None:
    sheet.freeze_panes = "A2"
    for index, column in enumerate(frame.columns, start=1):
        letter = get_column_letter(index)
        sheet.column_dimensions[letter].width = COLUMN_WIDTH
        if pd.api.types.is_datetime64_any_dtype(frame[column]):
            number_format = DATE_FORMAT
        elif pd.api.types.is_float_dtype(frame[column]):
            number_format = RATE_FORMAT
        else:
            continue
        for cell in sheet[letter][1:]:
            cell.number_format = number_format


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="rates.xlsx", help="workbook to create or update (default: rates.xlsx)")
    parser.add_argument("--base", default="USD", help="base currency (default: USD)")
    parser.add_argument("--symbols", default="EUR,GBP,PLN", help="comma-separated currencies to track (default: EUR,GBP,PLN)")
    parser.add_argument(
        "--since",
        type=date.fromisoformat,
        default=None,
        help="first date to fetch for a new file, YYYY-MM-DD (default: 90 days ago; ignored once the file exists)",
    )
    args = parser.parse_args(argv)
    symbols = [symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip()]
    if not symbols:
        parser.error("--symbols needs at least one currency code")
    today = date.today()
    if args.since and args.since > today:
        parser.error("--since cannot be in the future")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        rates, added = sync(Path(args.out), args.base.upper(), symbols, args.since, today, session)
    except SyncError as exc:
        logging.error("%s", exc)
        return 1
    logging.info(
        "%d new day(s) added; %s holds %d rows from %s to %s",
        added,
        args.out,
        len(rates),
        rates[DATE_COLUMN].min().date(),
        rates[DATE_COLUMN].max().date(),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
