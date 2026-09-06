"""Render the portfolio card for this piece as a PNG.

Usage:
    python summary.py --out sample/c_memory_safety_summary.png
    python summary.py --full --out sample/c_memory_safety_cover.png

Everything on the card is copied from a real run; nothing here is illustrative.
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

TITLE = "hdrparse - five memory-safety defects, demonstrated and fixed"
SUBTITLE = "the same six inputs through a vulnerable copy and a fixed one; 14 assertions, 0 failures"

DEFECTS = [
    ("CWE-787", "strcpy into a 32-byte buffer", "heap-buffer-overflow", "Name is 80 characters, limit is 31"),
    ("CWE-193", "limit forgets the terminator", "heap-buffer-overflow", "Tag is 16 characters, limit is 15"),
    ("CWE-122", "Roles: count taken on trust", "heap-buffer-overflow", "more Role lines than the Roles count of 2"),
    ("CWE-416", "pointer kept past the free", "heap-use-after-free", "keeps both notes, exits 0"),
    ("CWE-134", "value used as a format string", "rejected at compile time", "passes -Werror=format-security"),
]

REPORT = [
    "==791==ERROR: AddressSanitizer: heap-buffer-overflow on address 0x7c264a3e0060",
    "WRITE of size 81 at 0x7c264a3e0060 thread T0",
    "    #0 in strcpy",
    "    #2 in main vulnerable/hdrparse.c:66",
    "",
    "0x7c264a3e0060 is located 0 bytes after 32-byte region",
    "                          [0x7c264a3e0040,0x7c264a3e0060)",
    "allocated by thread T0 here:",
    "    #1 in main vulnerable/hdrparse.c:49",
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
    parser.add_argument("--out", default="sample/c_memory_safety_summary.png")
    # Upwork Project Catalog rejects cover images under 1000x750, which the
    # downscaled card is. --full keeps the supersampled canvas instead.
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    font = load_font(FONT_SIZE * SCALE)
    bold = load_font(int(FONT_SIZE * 1.25) * SCALE)
    pad = PADDING * SCALE
    line = LINE_HEIGHT * SCALE
    char = font.getlength("M")

    width = int(pad * 2 + char * 92)
    height = pad * 2 + line * (len(DEFECTS) * 2 + len(REPORT) + 8)
    image = Image.new("RGB", (width, height), SURFACE)
    draw = ImageDraw.Draw(image)

    y = pad
    draw.text((pad, y), TITLE, font=bold, fill=INK)
    y += line + 4 * SCALE
    draw.text((pad, y), SUBTITLE, font=font, fill=INK_SECONDARY)
    y += line + 8 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line

    draw.text((pad, y), "defect".ljust(10) + "vulnerable copy".ljust(34) + "fixed copy", font=font, fill=INK_MUTED)
    y += line
    for cwe, what, caught, handled in DEFECTS:
        draw.text((pad, y), cwe.ljust(10), font=font, fill=INK)
        draw.text((pad + char * 10, y), caught.ljust(34)[:34], font=font, fill=RED)
        draw.text((pad + char * 44, y), handled[:48], font=font, fill=GREEN)
        y += line
        draw.text((pad + char * 10, y), what, font=font, fill=INK_MUTED)
        y += line

    y += 4 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line

    for text in REPORT:
        draw.text((pad, y), text, font=font, fill=INK_SECONDARY if text.startswith(" ") else INK)
        y += line

    if args.full:
        image = image.crop((0, 0, width, y + PADDING * SCALE))
    else:
        image = image.resize((width // SCALE, y // SCALE + PADDING), Image.LANCZOS)
    image.save(args.out)
    print(f"wrote {args.out} at {image.size[0]}x{image.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
