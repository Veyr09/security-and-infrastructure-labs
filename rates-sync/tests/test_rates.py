from datetime import date

import pandas as pd
import pytest
import requests

from rates import SyncError, fetch_rates, merge, summarise
from sync_rates import load_existing, sync, write_workbook

SYMBOLS = ["EUR", "GBP"]
NO_SLEEP = lambda seconds: None  # noqa: E731


class FakeResponse:
    def __init__(self, status_code: int, payload=None, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


class FakeSession:
    """Serves canned responses in order and records every request."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requested = []

    def get(self, url, params, timeout):
        self.requested.append((url, params))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def payload(days: dict) -> dict:
    return {"amount": 1.0, "base": "USD", "rates": {day: {"EUR": eur, "GBP": gbp} for day, (eur, gbp) in days.items()}}


def ok(days: dict) -> FakeResponse:
    return FakeResponse(200, payload(days))


def test_fetch_rates_builds_one_row_per_day():
    session = FakeSession([ok({"2026-08-25": (0.857, 0.733), "2026-08-26": (0.856, 0.734)})])
    frame = fetch_rates("USD", SYMBOLS, date(2026, 8, 25), date(2026, 8, 26), session, sleep=NO_SLEEP)
    assert list(frame.columns) == ["date", "base", "EUR", "GBP"]
    assert frame["EUR"].tolist() == [0.857, 0.856]
    assert frame["date"].dt.date.tolist() == [date(2026, 8, 25), date(2026, 8, 26)]
    url, params = session.requested[0]
    assert url.endswith("/2026-08-25..2026-08-26")
    assert params == {"base": "USD", "symbols": "EUR,GBP"}


def test_fetch_rates_drops_padding_before_start():
    # Asking from Sunday the 23rd: the API pads with Friday the 21st, which must not be kept.
    session = FakeSession([ok({"2026-08-21": (0.85, 0.73), "2026-08-24": (0.86, 0.74)})])
    frame = fetch_rates("USD", SYMBOLS, date(2026, 8, 23), date(2026, 8, 24), session, sleep=NO_SLEEP)
    assert frame["date"].dt.date.tolist() == [date(2026, 8, 24)]


def test_fetch_rates_rejects_missing_symbol():
    session = FakeSession([FakeResponse(200, {"rates": {"2026-08-25": {"EUR": 0.85}}})])
    with pytest.raises(SyncError, match="lacks GBP"):
        fetch_rates("USD", SYMBOLS, date(2026, 8, 25), date(2026, 8, 25), session, sleep=NO_SLEEP)


def test_fetch_retries_transient_errors_then_gives_up():
    session = FakeSession([FakeResponse(503), requests.ConnectionError("boom"), FakeResponse(500)])
    naps = []
    with pytest.raises(SyncError, match="gave up"):
        fetch_rates("USD", SYMBOLS, date(2026, 8, 25), date(2026, 8, 25), session, sleep=naps.append)
    assert len(session.requested) == 3
    assert naps == [2.0, 4.0]


def test_fetch_fails_fast_on_4xx():
    session = FakeSession([FakeResponse(404, text="not found")])
    with pytest.raises(SyncError, match="HTTP 404"):
        fetch_rates("USD", SYMBOLS, date(2026, 8, 25), date(2026, 8, 25), session, sleep=NO_SLEEP)
    assert len(session.requested) == 1


def test_fetch_rejects_invalid_json():
    session = FakeSession([FakeResponse(200, None)])
    with pytest.raises(SyncError, match="invalid JSON"):
        fetch_rates("USD", SYMBOLS, date(2026, 8, 25), date(2026, 8, 25), session, sleep=NO_SLEEP)


def test_merge_adds_only_new_dates_and_keeps_existing_values():
    existing = pd.DataFrame({"date": pd.to_datetime(["2026-08-25", "2026-08-26"]), "base": "USD", "EUR": [0.85, 0.86], "GBP": [0.73, 0.74]})
    fresh = pd.DataFrame({"date": pd.to_datetime(["2026-08-26", "2026-08-27"]), "base": "USD", "EUR": [0.99, 0.87], "GBP": [0.99, 0.75]})
    combined, added = merge(existing, fresh)
    assert added == 1
    assert combined["EUR"].tolist() == [0.85, 0.86, 0.87]


def test_summarise_reports_span_and_change():
    rates = pd.DataFrame({"date": pd.to_datetime(["2026-08-25", "2026-08-27"]), "base": "USD", "EUR": [0.80, 0.88], "GBP": [0.75, 0.70]})
    summary = summarise(rates, SYMBOLS)
    eur = summary.iloc[0]
    assert eur["symbol"] == "EUR"
    assert eur["change_pct"] == 10.0
    assert summary.iloc[1]["low"] == 0.70


def test_summarise_refuses_empty_table():
    with pytest.raises(SyncError, match="no rates"):
        summarise(pd.DataFrame(columns=["date", "base", "EUR", "GBP"]), SYMBOLS)


def test_sync_creates_then_appends_without_duplicates(tmp_path):
    path = tmp_path / "rates.xlsx"
    first = FakeSession([ok({"2026-08-25": (0.85, 0.73), "2026-08-26": (0.86, 0.74)})])
    rates, added = sync(path, "USD", SYMBOLS, None, date(2026, 8, 26), first)
    assert added == 2

    # Same day again: nothing to fetch, no request made.
    idle = FakeSession([])
    rates, added = sync(path, "USD", SYMBOLS, None, date(2026, 8, 26), idle)
    assert added == 0
    assert idle.requested == []

    # Next day: only the missing day is requested and appended.
    later = FakeSession([ok({"2026-08-26": (0.99, 0.99), "2026-08-27": (0.87, 0.75)})])
    rates, added = sync(path, "USD", SYMBOLS, None, date(2026, 8, 27), later)
    assert added == 1
    assert later.requested[0][0].endswith("/2026-08-27..2026-08-27")
    saved = pd.read_excel(path, sheet_name="Rates")
    assert saved["EUR"].tolist() == [0.85, 0.86, 0.87]
    assert list(pd.read_excel(path, sheet_name=None)) == ["Rates", "Summary"]


def test_sync_uses_since_for_a_new_file(tmp_path):
    session = FakeSession([ok({"2026-08-03": (0.85, 0.73)})])
    sync(tmp_path / "rates.xlsx", "USD", SYMBOLS, date(2026, 8, 1), date(2026, 8, 3), session)
    assert session.requested[0][0].endswith("/2026-08-01..2026-08-03")


def test_sync_refuses_workbook_for_other_currencies(tmp_path):
    path = tmp_path / "rates.xlsx"
    rates = pd.DataFrame({"date": pd.to_datetime(["2026-08-25"]), "base": "USD", "EUR": [0.85]})
    write_workbook(rates, summarise(rates, ["EUR"]), path)
    with pytest.raises(SyncError, match="lacks columns GBP"):
        load_existing(path, SYMBOLS)


def test_sync_refuses_workbook_without_rates_sheet(tmp_path):
    path = tmp_path / "other.xlsx"
    pd.DataFrame({"a": [1]}).to_excel(path, sheet_name="Other", index=False)
    with pytest.raises(SyncError, match="no 'Rates' sheet"):
        load_existing(path, SYMBOLS)
