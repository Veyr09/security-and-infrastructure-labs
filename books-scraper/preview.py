"""Render the first rows of a books CSV as a PNG table, for the portfolio card.

Usage:
    python preview.py sample/books.csv --out sample/books_preview.png --rows 12
"""
from __future__ import annotations

import argparse
import csv
import sys

from PIL import Image, ImageDraw, ImageFont

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
RULE = "#e1e0d9"
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
FONT_SIZE = 15
PADDING = 24
COLUMN_GAP = 28
LINE_HEIGHT = 26
SCALE = 2  # render at 2x so the text stays crisp when the card is shrunk
COLUMN_LIMITS = {"title": 34, "url": 46}
DEFAULT_LIMIT = 80


def load_font(size: int):
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def shorten(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 3] + "..."


def render(rows: list[dict], total: int, path: str) -> None:
    if not rows:
        raise ValueError("nothing to render: the CSV has no rows")
    columns = list(rows[0])
    cells = [[shorten(row[column], COLUMN_LIMITS.get(column, DEFAULT_LIMIT)) for column in columns] for row in rows]
    font = load_font(FONT_SIZE * SCALE)
    widths = [max(font.getlength(text) for text in [column] + [line[i] for line in cells]) for i, column in enumerate(columns)]
    gap = COLUMN_GAP * SCALE
    margin = PADDING * SCALE
    width = int(2 * margin + sum(widths) + gap * (len(columns) - 1))
    height = (2 * PADDING + LINE_HEIGHT * (len(rows) + 3)) * SCALE
    image = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(image)

    y = margin
    draw.text((margin, y), f"books.csv: first {len(rows)} of {total} rows", fill=INK, font=font)
    y += LINE_HEIGHT * SCALE * 2
    x = margin
    for i, column in enumerate(columns):
        draw.text((x, y), column, fill=INK_MUTED, font=font)
        x += widths[i] + gap
    y += LINE_HEIGHT * SCALE
    draw.line([(margin, y - 6 * SCALE), (width - margin, y - 6 * SCALE)], fill=RULE, width=SCALE)
    for line in cells:
        x = margin
        for i, text in enumerate(line):
            draw.text((x, y), text, fill=INK if i == 0 else INK_SECONDARY, font=font)
            x += widths[i] + gap
        y += LINE_HEIGHT * SCALE
    image.save(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("csv", help="books.csv written by scrape_books.py")
    parser.add_argument("--out", default="books_preview.png", help="PNG to write")
    parser.add_argument("--rows", type=int, default=12, help="how many rows to show (default: 12)")
    args = parser.parse_args(argv)
    try:
        with open(args.csv, newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        render(rows[: args.rows], len(rows), args.out)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
