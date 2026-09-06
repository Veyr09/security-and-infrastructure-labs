"""Render the portfolio card for this piece as a PNG.

Usage:
    python summary.py --out sample/aws_cost_summary.png
    python summary.py --full --out sample/aws_cost_cover.png

--full keeps the supersampled canvas instead of downscaling it, for uses with a
minimum size - the Upwork Project Catalog rejects covers under 1000x750.

Every figure below is copied from sample/report-untuned.txt and
sample/report-tuned.txt, which are captured runs.
"""
from __future__ import annotations

import argparse

from PIL import Image, ImageDraw, ImageFont

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
RED = "#a4262c"
GREEN = "#1f7a3f"
RULE = "#e1e0d9"
FONT_CANDIDATES = [
    r"C:\Windows\Fonts\consola.ttf",
    r"C:\Windows\Fonts\cour.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
]
FONT_SIZE = 15
PADDING = 28
LINE_HEIGHT = 25
SCALE = 2
COLUMNS = 94

TITLE = "the same stack, planned twice"
SUBTITLE = "read from the terraform plan, before anything is built; 26 tests, 0 failures"

# (rule, untuned, tuned, colour of the tuned cell)
MATRIX = [
    ("rds-cost-drivers", "$1,322.52/mo", "$340.22/mo", GREEN),
    ("nat-gateway-per-az", "$113.88/mo", "silent", GREEN),
    ("ebs-gp2-not-gp3", "$23.80/mo", "silent", GREEN),
    ("log-group-never-expires", "2 groups", "silent", GREEN),
    ("lambda-memory-reserved", "3008 MB", "silent", GREEN),
    ("elastic-ip-idle", "silent", "silent", INK_SECONDARY),
]

TOTALS = [
    ("fixed monthly cost identified", "$1,460.20", "$340.22"),
    ("of which avoidable outright", "$80.68", "$0.00"),
]

NOTES = [
    ("elastic-ip-idle stays silent in both: three addresses, three gateways.", INK),
    ("A checker that flags everything says nothing about what to change, so the", INK_MUTED),
    ("rule that should not fire is tested as carefully as the ones that do.", INK_MUTED),
    ("", None),
    ("Rates are a JSON input with a provenance line and a date, printed in the", INK),
    ("report. Usage-dependent lines show the rate and stay out of the totals.", INK_MUTED),
]


def load_font(size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    raise SystemExit("no monospace font found; tried: " + ", ".join(FONT_CANDIDATES))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="sample/aws_cost_summary.png")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    font = load_font(FONT_SIZE * SCALE)
    bold = load_font(int(FONT_SIZE * 1.25) * SCALE)
    pad = PADDING * SCALE
    line = LINE_HEIGHT * SCALE
    char = font.getlength("M")

    width = int(pad * 2 + char * COLUMNS)
    height = pad * 2 + line * (len(MATRIX) + len(TOTALS) + len(NOTES) + 12)
    image = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(image)

    y = pad
    draw.text((pad, y), TITLE, font=bold, fill=INK)
    y += line + 4 * SCALE
    draw.text((pad, y), SUBTITLE, font=font, fill=INK_SECONDARY)
    y += line + 8 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line

    col = [pad, pad + int(char * 40), pad + int(char * 60)]
    for x, head in zip(col, ("rule", "as written", "after review")):
        draw.text((x, y), head, font=font, fill=INK_MUTED)
    y += line
    for rule, untuned, tuned, tuned_colour in MATRIX:
        draw.text((col[0], y), rule, font=font, fill=INK)
        draw.text((col[1], y), untuned, font=font,
                  fill=INK_SECONDARY if untuned == "silent" else RED)
        draw.text((col[2], y), tuned, font=font, fill=tuned_colour)
        y += line

    y += 6 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line
    for label, untuned, tuned in TOTALS:
        draw.text((col[0], y), label, font=font, fill=INK)
        draw.text((col[1], y), untuned, font=font, fill=RED)
        draw.text((col[2], y), tuned, font=font, fill=GREEN)
        y += line

    y += 6 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line
    for text, colour in NOTES:
        if text:
            draw.text((pad, y), text, font=font, fill=colour)
        y += line

    if args.full:
        image = image.crop((0, 0, width, y + pad))
    else:
        image = image.resize((width // SCALE, y // SCALE + PADDING), Image.LANCZOS)
    image.save(args.out)
    print(f"wrote {args.out} at {image.size[0]}x{image.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
