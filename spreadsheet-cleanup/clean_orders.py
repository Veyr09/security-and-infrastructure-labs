"""Clean a messy orders CSV into an Excel workbook with Clean, By month, By category and Issues sheets.

Usage:
    python clean_orders.py sample/orders_raw.csv --out orders_clean.xlsx
"""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd
from openpyxl.utils import get_column_letter

from cleaning import CleanError, CleanResult, clean, load_csv, summarise

MONEY_COLUMNS = {"unit_price", "line_total", "revenue"}
MONEY_FORMAT = "#,##0.00"
DATE_FORMAT = "yyyy-mm-dd"
MAX_COLUMN_WIDTH = 40
WIDTH_SAMPLE_ROWS = 200


def write_workbook(result: CleanResult, by_month: pd.DataFrame, by_category: pd.DataFrame, path: str) -> None:
    sheets = {"Clean": result.clean, "By month": by_month, "By category": by_category, "Issues": result.issues}
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, sheet_name=name, index=False)
            _format_sheet(writer.sheets[name], frame)


def _format_sheet(sheet, frame: pd.DataFrame) -> None:
    sheet.freeze_panes = "A2"
    for index, column in enumerate(frame.columns, start=1):
        letter = get_column_letter(index)
        longest = max([len(str(column))] + [len(str(value)) for value in frame[column].head(WIDTH_SAMPLE_ROWS)])
        sheet.column_dimensions[letter].width = min(longest + 2, MAX_COLUMN_WIDTH)
        number_format = None
        if column in MONEY_COLUMNS:
            number_format = MONEY_FORMAT
        elif column == "order_date":
            number_format = DATE_FORMAT
        if number_format:
            for cell in sheet[letter][1:]:
                cell.number_format = number_format


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", help="the messy orders export")
    parser.add_argument("--out", default="orders_clean.xlsx", help="workbook to write (default: orders_clean.xlsx)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    try:
        raw = load_csv(args.csv)
        result = clean(raw)
    except (CleanError, FileNotFoundError, pd.errors.EmptyDataError) as exc:
        logging.error("%s", exc)
        return 1
    if result.clean.empty:
        logging.warning("no rows survived cleaning; see the Issues sheet")

    by_month, by_category = summarise(result.clean)
    write_workbook(result, by_month, by_category, args.out)
    logging.info(
        "%d rows in, %d exact duplicates dropped, %d rows with problems, %d clean rows out -> %s",
        len(raw),
        result.exact_duplicates_dropped,
        result.issues["row"].nunique(),
        len(result.clean),
        args.out,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
