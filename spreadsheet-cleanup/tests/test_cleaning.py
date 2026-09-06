from datetime import date

import pandas as pd
import pytest

from cleaning import REQUIRED_COLUMNS, CleanError, clean, load_csv, parse_date, parse_money, parse_quantity, summarise

GOOD = {
    "order_id": "ORD-1",
    "order_date": "2026-03-05",
    "customer": "  acme   corp ",
    "email": " Orders@Acme.com ",
    "category": "electronics",
    "quantity": "3",
    "unit_price": "$1,234.50",
}


def frame(*rows: dict) -> pd.DataFrame:
    return pd.DataFrame(list(rows), columns=REQUIRED_COLUMNS)


@pytest.mark.parametrize(
    "text, expected",
    [
        ("2026-03-05", date(2026, 3, 5)),
        ("05/03/2026", date(2026, 3, 5)),
        ("05.03.2026", date(2026, 3, 5)),
        ("5 Mar 2026", date(2026, 3, 5)),
        ("5 March 2026", date(2026, 3, 5)),
        ("March 5, 2026", date(2026, 3, 5)),
        ("Mar 5, 2026", date(2026, 3, 5)),
        ("  2026-03-05  ", date(2026, 3, 5)),
    ],
)
def test_parse_date_accepts_common_formats(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["", "yesterday", "2026-13-40", "Q1", "n/a"])
def test_parse_date_rejects_garbage(text):
    assert parse_date(text) is None


@pytest.mark.parametrize(
    "text, expected",
    [("$1,234.50", 1234.5), ("USD 1,234.50", 1234.5), ("1234.5", 1234.5), ("$ 99", 99.0), ("-12.00", -12.0)],
)
def test_parse_money_accepts_common_formats(text, expected):
    assert parse_money(text) == expected


@pytest.mark.parametrize("text", ["", "TBD", "free", "-", ".", "call"])
def test_parse_money_rejects_garbage(text):
    assert parse_money(text) is None


def test_parse_quantity():
    assert parse_quantity(" 7 ") == 7
    assert parse_quantity("two") is None
    assert parse_quantity("1.5") is None
    assert parse_quantity("") is None


def test_clean_normalises_text_and_numbers():
    result = clean(frame(GOOD))
    row = result.clean.iloc[0]
    assert row["customer"] == "Acme Corp"
    assert row["email"] == "orders@acme.com"
    assert row["category"] == "Electronics"
    assert row["order_date"] == date(2026, 3, 5)
    assert row["quantity"] == 3
    assert row["unit_price"] == 1234.5
    assert row["line_total"] == 3703.5
    assert result.issues.empty


def test_clean_drops_exact_duplicates():
    result = clean(frame(GOOD, dict(GOOD)))
    assert len(result.clean) == 1
    assert result.exact_duplicates_dropped == 1
    assert result.issues.empty


def test_clean_moves_bad_rows_to_issues():
    bad = {**GOOD, "order_id": "ORD-2", "order_date": "yesterday", "unit_price": "TBD"}
    result = clean(frame(GOOD, bad))
    assert list(result.clean["order_id"]) == ["ORD-1"]
    assert sorted(result.issues["field"]) == ["order_date", "unit_price"]
    assert list(result.issues["row"]) == [3, 3]  # the bad line is spreadsheet row 3


def test_clean_keeps_first_of_conflicting_order_ids():
    second = {**GOOD, "quantity": "4"}
    result = clean(frame(GOOD, second))
    assert len(result.clean) == 1
    assert result.clean.iloc[0]["quantity"] == 3
    assert result.issues.iloc[0]["field"] == "order_id"
    assert result.issues.iloc[0]["row"] == 3


def test_bad_email_is_reported_but_row_is_kept():
    result = clean(frame({**GOOD, "email": "no email"}))
    assert len(result.clean) == 1
    assert list(result.issues["field"]) == ["email"]


def test_negative_price_is_blocking():
    result = clean(frame({**GOOD, "unit_price": "-12.00"}))
    assert result.clean.empty
    assert list(result.issues["problem"]) == ["negative price"]


def test_all_rows_bad_still_returns_frames():
    result = clean(frame({**GOOD, "quantity": "two"}))
    assert result.clean.empty
    assert list(result.clean.columns) == REQUIRED_COLUMNS + ["line_total"]


def test_load_csv_requires_columns(tmp_path):
    path = tmp_path / "orders.csv"
    path.write_text("order_id,customer\n1,a\n", encoding="utf-8")
    with pytest.raises(CleanError, match="order_date"):
        load_csv(str(path))


def test_summarise_groups_by_month_and_category():
    april = {**GOOD, "order_id": "ORD-2", "order_date": "2026-04-01", "category": "office", "quantity": "1", "unit_price": "10"}
    by_month, by_category = summarise(clean(frame(GOOD, april)).clean)
    assert list(by_month["month"]) == ["2026-03", "2026-04"]
    assert by_month["revenue"].tolist() == [3703.5, 10.0]
    assert by_category.iloc[0]["category"] == "Electronics"
    assert by_category["orders"].tolist() == [1, 1]
