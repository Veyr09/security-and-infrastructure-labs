"""Render the portfolio card for this piece as a PNG.

Usage:
    python summary.py --out sample/multi_tenant_summary.png
    python summary.py --full --out sample/multi_tenant_cover.png

--full keeps the supersampled canvas instead of downscaling it, for uses with a
minimum size - the Upwork Project Catalog rejects covers under 1000x750.

Every line below is copied from a captured run in sample/.
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
COLUMNS = 96

TITLE = "one timesheet service, two tenants, three deployments"
SUBTITLE = "each stack probed against what its compose file claims; 12 probes, 0 mismatches"

# (probe, (value, colour) for shared-vulnerable / shared-fixed / isolated).
# The colour is stated per cell rather than derived: "yes" is a defect in the
# first two rows and the correct answer in the last one, and a shared database
# path is a deliberate trade-off rather than a fault, so it is neither.
MATRIX = [
    ("tenant A reads tenant B's row by id", ("yes", RED), ("404", GREEN), ("404", GREEN)),
    ("tenant A's session accepted by B", ("yes", RED), ("401", GREEN), ("401", GREEN)),
    ("tenant A's app can reach B's database",
     ("yes", INK_SECONDARY), ("yes", INK_SECONDARY), ("no", GREEN)),
    ("only the proxy publishes a port", ("yes", GREEN), ("yes", GREEN), ("yes", GREEN)),
]

EVIDENCE = [
    ("shared, as usually first deployed", RED),
    ("  tenant-a read entry 4: tenant-b / M. Dubois / Roofing, site 3", None),
    ("  tenant-b accepted tenant-a's token:", None),
    ('    {\"tenant\": \"tenant-b\", \"session\": {\"tenant\": \"tenant-a\"}}', None),
    ("", None),
    ("one database, boundary enforced in the query", GREEN),
    ("  tenant-a asked for entry 4 and got HTTP 404", None),
    ("  tenant-b rejected tenant-a's token with HTTP 401", None),
    ("", None),
    ("database and network per tenant", GREEN),
    ("  app-a -> db-b:5432 : gaierror: Name or service not known", None),
]

FOOTER = [
    (INK, "The code difference is two predicates. Everything else is the deployment."),
    (INK_MUTED, "Every database is seeded with both tenants' rows, including the isolated"),
    (INK_MUTED, "one, so the 404 is the tenant predicate and not a missing row."),
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
    parser.add_argument("--out", default="sample/multi_tenant_summary.png")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    font = load_font(FONT_SIZE * SCALE)
    bold = load_font(int(FONT_SIZE * 1.25) * SCALE)
    pad = PADDING * SCALE
    line = LINE_HEIGHT * SCALE
    char = font.getlength("M")

    width = int(pad * 2 + char * COLUMNS)
    height = pad * 2 + line * (len(MATRIX) + len(EVIDENCE) + len(FOOTER) + 10)
    image = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(image)

    y = pad
    draw.text((pad, y), TITLE, font=bold, fill=INK)
    y += line + 4 * SCALE
    draw.text((pad, y), SUBTITLE, font=font, fill=INK_SECONDARY)
    y += line + 8 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line

    col = [pad, pad + int(char * 42), pad + int(char * 58), pad + int(char * 74)]
    for x, head in zip(col, ("probe", "shared", "shared+fix", "isolated")):
        draw.text((x, y), head, font=font, fill=INK_MUTED)
    y += line
    for probe, *cells in MATRIX:
        draw.text((col[0], y), probe, font=font, fill=INK)
        for x, (value, colour) in zip(col[1:], cells):
            draw.text((x, y), value, font=font, fill=colour)
        y += line

    y += 6 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line

    for text, colour in EVIDENCE:
        draw.text((pad, y), text, font=font,
                  fill=colour if colour else INK_SECONDARY)
        y += line

    y += 4 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line
    for colour, text in FOOTER:
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
