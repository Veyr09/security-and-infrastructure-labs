"""Render the portfolio card for the Java XXE piece as a PNG.

Usage:
    python summary.py --out sample/c_memory_safety_summary.png

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

TITLE = "XXE in Java: what the default parser does, and the fix"
SUBTITLE = "the same documents through factory defaults and hardened factories; 16 assertions, 0 failures"

DEFECTS = [
    ("good.xml", "a well-formed order", "returns Acme Ltd", "returns Acme Ltd"),
    ("xxe-file", "entity reads a local file", "DISCLOSES 82 chars", "both refuse"),
    ("xxe-dtd", "entity hidden in a fetched DTD", "DISCLOSES 82 chars", "both refuse"),
    ("laughs", "10M-character entity expansion", "refused by the JDK itself", "both refuse"),
]

REPORT = [
    "the JDK stops billion-laughs on its own, at 64000 entity expansions,",
    "and ships no equivalent defence against entity-driven file disclosure.",
    "",
    "DOM:   setFeature(\"...disallow-doctype-decl\", true)   + six more",
    "StAX:  setProperty(SUPPORT_DTD, false)",
    "       setProperty(IS_SUPPORTING_EXTERNAL_ENTITIES, false)",
    "",
    "the two APIs share no settings, so hardening one factory and",
    "missing the other leaves a working hole.",
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
    parser.add_argument("--out", default="sample/java_xxe_summary.png")
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

    draw.text((pad, y), "document".ljust(10) + "factory defaults".ljust(34) + "hardened", font=font, fill=INK_MUTED)
    y += line
    for cwe, what, caught, handled in DEFECTS:
        draw.text((pad, y), cwe.ljust(10), font=font, fill=INK)
        draw.text((pad + char * 10, y), caught.ljust(34)[:34], font=font, fill=RED if "DISCLOSES" in caught else INK_SECONDARY)
        draw.text((pad + char * 44, y), handled[:48], font=font, fill=GREEN if "refuse" in handled or "returns" in handled else INK)
        y += line
        draw.text((pad + char * 10, y), what, font=font, fill=INK_MUTED)
        y += line

    y += 4 * SCALE
    draw.line([(pad, y), (width - pad, y)], fill=RULE, width=SCALE)
    y += line

    for text in REPORT:
        draw.text((pad, y), text, font=font, fill=INK_SECONDARY if text.startswith(" ") else INK)
        y += line

    image = image.resize((width // SCALE, y // SCALE + PADDING), Image.LANCZOS)
    image.save(args.out)
    print(f"wrote {args.out} at {image.size[0]}x{image.size[1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
