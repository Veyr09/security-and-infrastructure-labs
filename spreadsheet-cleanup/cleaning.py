"""Rules for turning a messy orders export into tidy rows.

Everything here is pure: DataFrame in, DataFrame out, no files.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

REQUIRED_COLUMNS = ["order_id", "order_date", "customer", "email", "category", "quantity", "unit_price"]
OUTPUT_COLUMNS = REQUIRED_COLUMNS + ["line_total"]
ISSUE_COLUMNS = ["row", "order_id", "field", "problem", "value"]
# Day-first for the slash and dot forms. For a US-style export, swap in %m/%d/%Y.
DATE_FORMATS = ["%Y-%m-%d", "%d/%m/%Y", "%d.%m.%Y", "%d %b %Y", "%d %B %Y", "%B %d, %Y", "%b %d, %Y"]
EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
NON_NUMERIC = re.compile(r"[^0-9.\-]")
WHITESPACE = re.compile(r"\s+")


class CleanError(Exception):
    """The input cannot be cleaned as-is, for example because a required column is missing."""


@dataclass
class CleanResult:
    clean: pd.DataFrame
    issues: pd.DataFrame
    exact_duplicates_dropped: int


def load_csv(path: str) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise CleanError(f"{path} is missing required columns: {', '.join(missing)}")
    return frame


def tidy_text(text: str) -> str:
    return WHITESPACE.sub(" ", text.strip())


def parse_date(text: str) -> date | None:
    text = tidy_text(text)
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_money(text: str) -> float | None:
    """Accepts '$1,234.50', 'USD 1,234.50', '1234.5'. Assumes a dot as the decimal separator."""
    digits = NON_NUMERIC.sub("", text)
    if not digits or digits in {"-", ".", "-."}:
        return None
    try:
        return float(digits)
    except ValueError:
        return None


def parse_quantity(text: str) -> int | None:
    text = text.strip()
    return int(text) if re.fullmatch(r"\d+", text) else None


def _normalise(record: dict) -> tuple[dict | None, list[dict]]:
    """Return the cleaned row (None if it cannot be kept) and every problem found in it."""
    problems: list[dict] = []

    def problem(field: str, text: str) -> None:
        problems.append({"field": field, "problem": text, "value": record[field]})

    order_id = tidy_text(record["order_id"])
    if not order_id:
        problem("order_id", "blank")
    order_date = parse_date(record["order_date"])
    if order_date is None:
        problem("order_date", "unrecognised date")
    customer = tidy_text(record["customer"]).title()
    if not customer:
        problem("customer", "blank")
    quantity = parse_quantity(record["quantity"])
    if quantity is None:
        problem("quantity", "not a whole number")
    unit_price = parse_money(record["unit_price"])
    if unit_price is None:
        problem("unit_price", "unrecognised price")
    elif unit_price < 0:
        problem("unit_price", "negative price")
    email = tidy_text(record["email"]).lower()
    if email and not EMAIL_PATTERN.fullmatch(email):
        problem("email", "does not look like an email address; kept as typed")

    # A bad email is worth reporting but not worth losing the order over.
    if any(item["field"] != "email" for item in problems):
        return None, problems
    row = {
        "order_id": order_id,
        "order_date": order_date,
        "customer": customer,
        "email": email,
        "category": tidy_text(record["category"]).title(),
        "quantity": quantity,
        "unit_price": unit_price,
    }
    return row, problems


def clean(frame: pd.DataFrame) -> CleanResult:
    """Apply every rule. Rows with a blocking problem go to `issues` instead of `clean`."""
    frame = frame[REQUIRED_COLUMNS].copy()
    frame["row"] = frame.index + 2  # spreadsheet row numbers: 1-based, after the header
    before = len(frame)
    frame = frame.drop_duplicates(subset=REQUIRED_COLUMNS)
    exact_duplicates_dropped = before - len(frame)

    issues: list[dict] = []
    kept: list[dict] = []
    for record in frame.to_dict("records"):
        row, problems = _normalise(record)
        issues.extend({"row": record["row"], "order_id": record["order_id"], **item} for item in problems)
        if row is not None:
            row["row"] = record["row"]
            kept.append(row)

    clean_frame = pd.DataFrame(kept, columns=REQUIRED_COLUMNS + ["row"])
    conflicting = clean_frame.duplicated(subset="order_id", keep="first")
    for record in clean_frame[conflicting].to_dict("records"):
        issues.append(
            {
                "row": record["row"],
                "order_id": record["order_id"],
                "field": "order_id",
                "problem": "same order_id as an earlier row with different details; kept the earlier one",
                "value": record["order_id"],
            }
        )
    clean_frame = clean_frame[~conflicting].sort_values(["order_date", "row"]).drop(columns="row")
    clean_frame = clean_frame.reset_index(drop=True)
    clean_frame["line_total"] = (clean_frame["quantity"].astype(float) * clean_frame["unit_price"].astype(float)).round(2)

    issues_frame = pd.DataFrame(issues, columns=ISSUE_COLUMNS).sort_values("row", kind="stable").reset_index(drop=True)
    return CleanResult(clean=clean_frame[OUTPUT_COLUMNS], issues=issues_frame, exact_duplicates_dropped=exact_duplicates_dropped)


def summarise(clean_frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Revenue and order counts by month and by category."""
    dated = clean_frame.assign(month=pd.to_datetime(clean_frame["order_date"]).dt.strftime("%Y-%m"))
    by_month = dated.groupby("month", as_index=False).agg(
        orders=("order_id", "count"), units=("quantity", "sum"), revenue=("line_total", "sum")
    )
    by_category = (
        clean_frame.groupby("category", as_index=False)
        .agg(orders=("order_id", "count"), units=("quantity", "sum"), revenue=("line_total", "sum"))
        .sort_values("revenue", ascending=False)
        .reset_index(drop=True)
    )
    return by_month, by_category
