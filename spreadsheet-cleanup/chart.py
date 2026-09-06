"""Draw the monthly revenue chart from a cleaned workbook.

Usage:
    python chart.py sample/orders_clean.xlsx --out sample/revenue_by_month.png
"""
from __future__ import annotations

import argparse
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402
from matplotlib.ticker import FuncFormatter, MaxNLocator  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = "#2a78d6"
BAR_PX = 22  # thin marks: the rest of each slot is air
CORNER_PX = 4
DPI = 150
FIGSIZE = (8, 4.2)
HEADROOM = 1.15


def draw(by_month: pd.DataFrame, path: str) -> None:
    if by_month.empty:
        raise ValueError("nothing to chart: the By month sheet is empty")
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Segoe UI", "DejaVu Sans", "Arial"]

    months = [pd.Timestamp(month).strftime("%b %Y") for month in by_month["month"]]
    revenue = by_month["revenue"].astype(float).tolist()

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.1, right=0.97, top=0.85, bottom=0.16)
    ax.set_xlim(-0.6, len(months) - 0.4)
    ax.set_ylim(0, (max(revenue) or 1.0) * HEADROOM)

    x_per_px, y_per_px = _data_units_per_pixel(ax)
    for x, value in enumerate(revenue):
        _bar(ax, x, value, BAR_PX * x_per_px, CORNER_PX * x_per_px, y_per_px / x_per_px)

    ax.set_xticks(range(len(months)))
    ax.set_xticklabels(months)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, steps=[1, 2, 5, 10]))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda value, _: f"{value:,.0f}"))
    ax.tick_params(axis="both", length=0, colors=INK_MUTED, labelsize=9)
    ax.grid(axis="y", color=GRIDLINE, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)

    # Label only the peak; the axis carries the rest.
    peak = max(range(len(revenue)), key=revenue.__getitem__)
    ax.annotate(
        f"{revenue[peak]:,.0f}", (peak, revenue[peak]), xytext=(0, 6), textcoords="offset points", ha="center", color=INK, fontsize=9
    )

    ax.set_title("Revenue by month, USD", loc="left", color=INK, fontsize=12, pad=12)
    fig.text(0.1, 0.03, "From the By month sheet of the cleaned workbook", color=INK_SECONDARY, fontsize=8)
    fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)


def _data_units_per_pixel(ax) -> tuple[float, float]:
    fig = ax.figure
    width_px, height_px = fig.get_size_inches() * fig.dpi
    box = ax.get_position()
    x0, x1 = ax.get_xlim()
    y0, y1 = ax.get_ylim()
    return (x1 - x0) / (box.width * width_px), (y1 - y0) / (box.height * height_px)


def _bar(ax, x: float, height: float, width: float, radius: float, aspect: float) -> None:
    """A column with a rounded data-end and a square base.

    A rounded box, plus a plain rectangle covering its bottom corners so only the top is rounded.
    `aspect` converts the x-unit radius into y units so the corners are circular on screen.
    """
    left = x - width / 2
    ax.add_patch(
        FancyBboxPatch(
            (left, 0),
            width,
            height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            mutation_aspect=aspect,
            facecolor=SERIES,
            edgecolor="none",
        )
    )
    ax.add_patch(Rectangle((left, 0), width, min(height, radius * aspect), facecolor=SERIES, edgecolor="none"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workbook", help="orders_clean.xlsx written by clean_orders.py")
    parser.add_argument("--out", default="revenue_by_month.png", help="PNG to write")
    args = parser.parse_args(argv)
    try:
        by_month = pd.read_excel(args.workbook, sheet_name="By month")
        draw(by_month, args.out)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
