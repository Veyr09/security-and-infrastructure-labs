"""Fetch daily exchange rates from the Frankfurter API and merge them into a table without duplicates.

Pure functions apart from the HTTP call, which takes an injectable session so tests need no network.
"""
from __future__ import annotations

import logging
import time
from datetime import date

import pandas as pd
import requests

API_URL = "https://api.frankfurter.dev/v1"
REQUEST_TIMEOUT_SECONDS = 15
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
DATE_COLUMN = "date"
BASE_COLUMN = "base"


class SyncError(Exception):
    """The API could not be read, or the data does not fit the existing table."""


def fetch_rates(base: str, symbols: list[str], start: date, end: date, session, sleep=time.sleep) -> pd.DataFrame:
    """One request for the whole range. Columns: date, base, then one column per symbol."""
    url = f"{API_URL}/{start.isoformat()}..{end.isoformat()}"
    params = {"base": base, "symbols": ",".join(symbols)}
    payload = _get_json(session, url, params, sleep)
    rows = []
    for day, rates in payload.get("rates", {}).items():
        when = date.fromisoformat(day)
        # A range that starts on a weekend comes back padded with the previous business day.
        if when < start:
            continue
        missing = [symbol for symbol in symbols if symbol not in rates]
        if missing:
            raise SyncError(f"API response for {day} lacks {', '.join(missing)}")
        rows.append({DATE_COLUMN: when, BASE_COLUMN: base, **{symbol: float(rates[symbol]) for symbol in symbols}})
    frame = pd.DataFrame(rows, columns=[DATE_COLUMN, BASE_COLUMN, *symbols])
    frame[DATE_COLUMN] = pd.to_datetime(frame[DATE_COLUMN])
    return frame


def _get_json(session, url: str, params: dict, sleep) -> dict:
    """GET with retries on network errors, 5xx and 429. Any other 4xx fails immediately."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, params=params, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logging.warning("attempt %d for %s failed: %s", attempt, url, exc)
        else:
            if response.status_code == 200:
                try:
                    return response.json()
                except ValueError as exc:
                    raise SyncError(f"{url} returned invalid JSON") from exc
            if response.status_code != 429 and 400 <= response.status_code < 500:
                raise SyncError(f"{url} returned HTTP {response.status_code}: {response.text[:200]}")
            logging.warning("attempt %d for %s returned HTTP %d", attempt, url, response.status_code)
        if attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_SECONDS * attempt)
    raise SyncError(f"gave up on {url} after {MAX_ATTEMPTS} attempts")


def merge(existing: pd.DataFrame | None, fresh: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Append rows for dates not already present. Existing rows win, so a re-run never rewrites history."""
    if existing is None or existing.empty:
        combined = fresh.copy()
        previous = 0
    elif fresh.empty:
        # A weekend or holiday run: nothing new, and concatenating an empty frame would only trip pandas warnings.
        combined = existing.copy()
        previous = len(existing)
    else:
        combined = pd.concat([existing, fresh], ignore_index=True)
        previous = len(existing)
    combined = combined.drop_duplicates(subset=DATE_COLUMN, keep="first").sort_values(DATE_COLUMN).reset_index(drop=True)
    return combined, len(combined) - previous


def summarise(rates: pd.DataFrame, symbols: list[str]) -> pd.DataFrame:
    """Per symbol: the span covered, first and latest values, the low and high, and the change over the span."""
    if rates.empty:
        raise SyncError("no rates to summarise")
    rows = []
    for symbol in symbols:
        series = rates[symbol]
        first, latest = float(series.iloc[0]), float(series.iloc[-1])
        rows.append(
            {
                "symbol": symbol,
                "from": rates[DATE_COLUMN].iloc[0],
                "to": rates[DATE_COLUMN].iloc[-1],
                "first": first,
                "latest": latest,
                "low": float(series.min()),
                "high": float(series.max()),
                "change_pct": round((latest / first - 1) * 100, 2),
            }
        )
    return pd.DataFrame(rows)
