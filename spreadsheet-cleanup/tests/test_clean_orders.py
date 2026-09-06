import pandas as pd

from clean_orders import main

CSV = (
    "order_id,order_date,customer,email,category,quantity,unit_price\n"
    "ORD-1,2026-03-05,acme corp,orders@acme.com,electronics,3,\"$1,234.50\"\n"
    "ORD-2,yesterday,acme corp,orders@acme.com,office,1,10\n"
)


def test_main_writes_all_four_sheets(tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text(CSV, encoding="utf-8")
    out = tmp_path / "clean.xlsx"
    assert main([str(source), "--out", str(out)]) == 0
    sheets = pd.read_excel(out, sheet_name=None)
    assert list(sheets) == ["Clean", "By month", "By category", "Issues"]
    assert sheets["Clean"]["order_id"].tolist() == ["ORD-1"]
    assert sheets["Clean"]["line_total"].tolist() == [3703.5]
    assert sheets["Issues"]["order_id"].tolist() == ["ORD-2"]


def test_main_reports_missing_file(tmp_path):
    assert main([str(tmp_path / "nope.csv"), "--out", str(tmp_path / "x.xlsx")]) == 1


def test_main_reports_missing_columns(tmp_path):
    source = tmp_path / "orders.csv"
    source.write_text("order_id,customer\n1,a\n", encoding="utf-8")
    assert main([str(source), "--out", str(tmp_path / "x.xlsx")]) == 1
