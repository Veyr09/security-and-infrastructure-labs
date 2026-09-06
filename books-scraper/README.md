# Book catalogue scraper

Scrapes the paginated catalogue at books.toscrape.com (a site built for scraping practice) into a CSV: title, price, star rating, stock status, product URL. The structure is the one I use for real listing sites: change the URL and the selectors in `parse_listing`, and the paging, retries, and output stay as they are.

## What it does
- Walks the listing one page at a time with a one-second pause between pages.
- Retries network errors, 5xx and 429 responses three times with backoff. A 404 stops immediately with a clear error.
- Checks robots.txt before starting.
- Fails loudly if the page layout changes, instead of quietly writing an empty file.

## Run it
    pip install -r requirements.txt
    python scrape_books.py --out books.csv --max-pages 3

Drop `--max-pages` to fetch all 50 pages (about a minute at the default delay).

## Output
    title,price_gbp,rating,in_stock,url
    A Light in the Attic,51.77,3,True,https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html
    Tipping the Velvet,53.74,1,True,https://books.toscrape.com/catalogue/tipping-the-velvet_999/index.html

## Tests
    python -m pytest -q

The tests run against saved HTML pages in `tests/fixtures`, so they need no network. They cover retries, the 404 path, pagination, the page limit, a changed layout, and robots.txt.

## Preview image
    python preview.py sample/books.csv --out sample/books_preview.png --rows 12

Renders the first rows of the CSV as a PNG table, which is what the portfolio card shows.
