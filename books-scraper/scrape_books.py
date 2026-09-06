"""Scrape the book catalogue at books.toscrape.com into a CSV file.

Walks the paginated listing one request at a time with a polite delay,
retries transient failures, and writes title, price, rating, stock and URL.

Usage:
    python scrape_books.py --out books.csv                # all 50 pages
    python scrape_books.py --out books.csv --max-pages 3
"""
from __future__ import annotations

import argparse
import csv
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass, fields
from urllib import robotparser
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://books.toscrape.com/"
FIRST_PAGE_URL = urljoin(BASE_URL, "catalogue/page-1.html")
USER_AGENT = "books-scraper/1.0 (portfolio sample)"
REQUEST_DELAY_SECONDS = 1.0
REQUEST_TIMEOUT_SECONDS = 15
MAX_ATTEMPTS = 3
BACKOFF_SECONDS = 2.0
RATING_WORDS = {"One": 1, "Two": 2, "Three": 3, "Four": 4, "Five": 5}
PRICE_PATTERN = re.compile(r"\d+(?:\.\d+)?")


class ScrapeError(Exception):
    """The site could not be fetched, or no longer looks the way this scraper expects."""


@dataclass
class Book:
    title: str
    price_gbp: float
    rating: int
    in_stock: bool
    url: str


def parse_price(text: str) -> float:
    # The pound sign arrives either as one character or as two mis-decoded ones; the digits are what matter.
    match = PRICE_PATTERN.search(text)
    if not match:
        raise ValueError(f"no price in {text!r}")
    return float(match.group())


def parse_listing(html: str, page_url: str) -> tuple[list[Book], str | None]:
    """Return the books on one listing page and the absolute URL of the next page, if any."""
    soup = BeautifulSoup(html, "lxml")
    books = []
    for pod in soup.select("article.product_pod"):
        link = pod.select_one("h3 a")
        rating_classes = [c for c in pod.select_one("p.star-rating")["class"] if c != "star-rating"]
        availability = pod.select_one("p.availability").get_text(strip=True)
        books.append(
            Book(
                title=link["title"],
                price_gbp=parse_price(pod.select_one("p.price_color").get_text(strip=True)),
                rating=RATING_WORDS[rating_classes[0]],
                in_stock=availability.lower().startswith("in stock"),
                url=urljoin(page_url, link["href"]),
            )
        )
    next_link = soup.select_one("li.next a")
    next_url = urljoin(page_url, next_link["href"]) if next_link else None
    return books, next_url


def fetch(session: requests.Session, url: str, sleep=time.sleep) -> str:
    """GET a page, retrying network errors, 5xx and 429. Any other 4xx fails immediately."""
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = session.get(url, timeout=REQUEST_TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            logging.warning("attempt %d for %s failed: %s", attempt, url, exc)
        else:
            if response.status_code == 200:
                return response.content.decode("utf-8")
            if response.status_code != 429 and 400 <= response.status_code < 500:
                raise ScrapeError(f"{url} returned HTTP {response.status_code}")
            logging.warning("attempt %d for %s returned HTTP %d", attempt, url, response.status_code)
        if attempt < MAX_ATTEMPTS:
            sleep(BACKOFF_SECONDS * attempt)
    raise ScrapeError(f"gave up on {url} after {MAX_ATTEMPTS} attempts")


def allowed_by_robots(url: str) -> bool:
    parser = robotparser.RobotFileParser(urljoin(BASE_URL, "robots.txt"))
    parser.read()
    return parser.can_fetch(USER_AGENT, url)


def scrape(
    max_pages: int | None,
    session: requests.Session,
    delay: float = REQUEST_DELAY_SECONDS,
    sleep=time.sleep,
) -> list[Book]:
    if not allowed_by_robots(FIRST_PAGE_URL):
        raise ScrapeError("robots.txt disallows fetching the catalogue")
    books: list[Book] = []
    url: str | None = FIRST_PAGE_URL
    page_number = 0
    while url and (max_pages is None or page_number < max_pages):
        page_number += 1
        page_books, next_url = parse_listing(fetch(session, url), url)
        if not page_books:
            raise ScrapeError(f"no books found on {url}; the page layout may have changed")
        books.extend(page_books)
        logging.info("page %d: %d books", page_number, len(page_books))
        url = next_url
        if url:
            sleep(delay)
    return books


def write_csv(books: list[Book], path: str) -> None:
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=[field.name for field in fields(Book)])
        writer.writeheader()
        writer.writerows(asdict(book) for book in books)


def make_session() -> requests.Session:
    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    return session


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", default="books.csv", help="CSV file to write (default: books.csv)")
    parser.add_argument("--max-pages", type=int, default=None, help="stop after this many pages (default: all)")
    parser.add_argument("--delay", type=float, default=REQUEST_DELAY_SECONDS, help="seconds to wait between pages")
    args = parser.parse_args(argv)
    if args.max_pages is not None and args.max_pages < 1:
        parser.error("--max-pages must be at least 1")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        books = scrape(args.max_pages, make_session(), delay=args.delay)
    except ScrapeError as exc:
        logging.error("%s", exc)
        return 1
    write_csv(books, args.out)
    logging.info("wrote %d books to %s", len(books), args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
