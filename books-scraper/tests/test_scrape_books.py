import csv
from pathlib import Path

import pytest
import requests

import scrape_books
from scrape_books import Book, ScrapeError, fetch, parse_listing, parse_price, scrape, write_csv

FIXTURES = Path(__file__).parent / "fixtures"
PAGE_1_URL = "https://books.toscrape.com/catalogue/page-1.html"
PAGE_2_URL = "https://books.toscrape.com/catalogue/page-2.html"
PAGE_50_URL = "https://books.toscrape.com/catalogue/page-50.html"
POUND = "£"
MOJIBAKE_POUND = "Â£"


def read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code: int, body: str = ""):
        self.status_code = status_code
        self.content = body.encode("utf-8")


class FakeSession:
    """Serves canned responses in order and records every URL requested."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requested = []

    def get(self, url, timeout):
        self.requested.append(url)
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def allow_all(monkeypatch):
    monkeypatch.setattr(scrape_books, "allowed_by_robots", lambda url: True)


def test_first_page_parses_all_books_and_next_link():
    books, next_url = parse_listing(read_fixture("page-1.html"), PAGE_1_URL)
    assert len(books) == 20
    first = books[0]
    assert first.title == "A Light in the Attic"
    assert first.price_gbp == 51.77
    assert first.rating == 3
    assert first.in_stock is True
    assert first.url == "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert next_url == PAGE_2_URL


def test_last_page_has_no_next_link():
    books, next_url = parse_listing(read_fixture("page-50.html"), PAGE_50_URL)
    assert len(books) == 20
    assert next_url is None


def test_parse_price_handles_encoding_glitch():
    assert parse_price(POUND + "51.77") == 51.77
    assert parse_price(MOJIBAKE_POUND + "51.77") == 51.77


def test_parse_price_rejects_garbage():
    with pytest.raises(ValueError):
        parse_price("free")


def test_fetch_retries_transient_errors_then_gives_up():
    session = FakeSession([FakeResponse(503), requests.ConnectionError("boom"), FakeResponse(500)])
    naps = []
    with pytest.raises(ScrapeError, match="gave up"):
        fetch(session, PAGE_1_URL, sleep=naps.append)
    assert len(session.requested) == 3
    assert naps == [2.0, 4.0]


def test_fetch_fails_fast_on_404():
    session = FakeSession([FakeResponse(404)])
    with pytest.raises(ScrapeError, match="HTTP 404"):
        fetch(session, PAGE_1_URL, sleep=lambda _: None)
    assert len(session.requested) == 1


def test_scrape_follows_pagination_until_last_page(monkeypatch):
    allow_all(monkeypatch)
    session = FakeSession(
        [FakeResponse(200, read_fixture("page-1.html")), FakeResponse(200, read_fixture("page-50.html"))]
    )
    naps = []
    books = scrape(max_pages=None, session=session, delay=0.5, sleep=naps.append)
    assert len(books) == 40
    # page-1 links to page-2; the fake serves the last page there, so the walk stops
    assert session.requested == [PAGE_1_URL, PAGE_2_URL]
    assert naps == [0.5]


def test_scrape_respects_max_pages(monkeypatch):
    allow_all(monkeypatch)
    session = FakeSession([FakeResponse(200, read_fixture("page-1.html"))])
    books = scrape(max_pages=1, session=session, sleep=lambda _: None)
    assert len(books) == 20
    assert session.requested == [PAGE_1_URL]


def test_scrape_fails_loudly_when_layout_changes(monkeypatch):
    allow_all(monkeypatch)
    session = FakeSession([FakeResponse(200, "<html><body>nothing here</body></html>")])
    with pytest.raises(ScrapeError, match="layout"):
        scrape(max_pages=None, session=session, sleep=lambda _: None)


def test_scrape_honours_robots(monkeypatch):
    monkeypatch.setattr(scrape_books, "allowed_by_robots", lambda url: False)
    with pytest.raises(ScrapeError, match="robots"):
        scrape(max_pages=None, session=FakeSession([]), sleep=lambda _: None)


def test_write_csv_round_trips(tmp_path):
    out = tmp_path / "books.csv"
    write_csv([Book("T", 1.5, 4, True, "https://x/y")], str(out))
    with open(out, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows == [{"title": "T", "price_gbp": "1.5", "rating": "4", "in_stock": "True", "url": "https://x/y"}]
