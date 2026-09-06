"""Draw the indexed exchange-rate chart from a synced workbook.

Each currency is indexed to 100 on the first day in the table, so rates of very
different size (EUR near 0.86, PLN near 3.7) share one honest axis instead of
needing a second y-axis.

Usage:
    python chart.py sample/rates.xlsx --out sample/rates_indexed.png
"""
from __future__ import annotations

import argparse
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

from rates import BASE_COLUMN, DATE_COLUMN  # noqa: E402

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_SECONDARY = "#52514e"
INK_MUTED = "#898781"
GRIDLINE = "#e1e0d9"
BASELINE = "#c3c2b7"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # fixed slot order; more than three lines belong in small multiples
INDEX_BASE = 100.0
LINE_WIDTH = 2
MARKER_SIZE = 7
RING_WIDTH = 2
LABEL_GAP_FRACTION = 0.05  # end labels closer than this share of the y-range would collide
RIGHT_MARGIN_FRACTION = 0.14
Y_PAD_FRACTION = 0.15
DPI = 150
FIGSIZE = (8, 4.2)


def draw(rates: pd.DataFrame, symbols: list[str], path: str) -> None:
    if rates.empty:
        raise ValueError("nothing to chart: the Rates sheet is empty")
    if len(symbols) > len(SERIES):
        raise ValueError(f"one chart holds up to {len(SERIES)} currencies; put the rest in a second chart")
    plt.rcParams["font.family"] = "sans-serif"
    plt.rcParams["font.sans-serif"] = ["Segoe UI", "DejaVu Sans", "Arial"]

    dates = pd.to_datetime(rates[DATE_COLUMN]).reset_index(drop=True)
    values = rates[symbols].astype(float).reset_index(drop=True)
    indexed = values / values.iloc[0] * INDEX_BASE
    base = str(rates[BASE_COLUMN].iloc[0])

    fig, ax = plt.subplots(figsize=FIGSIZE, dpi=DPI)
    fig.patch.set_facecolor(SURFACE)
    ax.set_facecolor(SURFACE)
    fig.subplots_adjust(left=0.08, right=0.97, top=0.85, bottom=0.16)

    ax.axhline(INDEX_BASE, color=BASELINE, linewidth=1)
    last_date = dates.iloc[-1]
    for color, symbol in zip(SERIES, symbols):
        ax.plot(dates, indexed[symbol], color=color, linewidth=LINE_WIDTH, solid_joinstyle="round", solid_capstyle="round", label=symbol)
        # End marker with a surface-colored ring so it stays legible where lines cross.
        ax.plot(
            [last_date],
            [indexed[symbol].iloc[-1]],
            marker="o",
            markersize=MARKER_SIZE,
            markerfacecolor=color,
            markeredgecolor=SURFACE,
            markeredgewidth=RING_WIDTH,
            linestyle="none",
        )

    span = last_date - dates.iloc[0]
    ax.set_xlim(dates.iloc[0], last_date + span * RIGHT_MARGIN_FRACTION)
    low, high = float(indexed.min().min()), float(indexed.max().max())
    pad = (high - low) * Y_PAD_FRACTION or 1.0
    ax.set_ylim(low - pad, high + pad)

    # Direct end labels only when they will not collide; the legend carries identity either way.
    ends = indexed.iloc[-1]
    if _labels_fit(ends.tolist(), (high - low) + 2 * pad):
        for symbol in symbols:
            ax.annotate(
                f"{symbol} {ends[symbol]:.1f}", (last_date, ends[symbol]), xytext=(10, 0), textcoords="offset points", va="center", color=INK, fontsize=9
            )

    ax.legend(frameon=False, loc="upper left", fontsize=9, labelcolor=INK_SECONDARY, handlelength=1.4, ncol=len(symbols))
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=4, maxticks=7))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.tick_params(axis="both", length=0, colors=INK_MUTED, labelsize=9)
    ax.grid(axis="y", color=GRIDLINE, linewidth=1, linestyle="-")
    ax.set_axisbelow(True)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(BASELINE)

    ax.set_title(
        f"{base} against {', '.join(symbols)}, indexed to {INDEX_BASE:.0f} on {dates.iloc[0]:%Y-%m-%d}", loc="left", color=INK, fontsize=12, pad=12
    )
    fig.text(
        0.08,
        0.03,
        "Source: Frankfurter API (European Central Bank reference rates). Above 100: the dollar buys more of that currency than on day one.",
        color=INK_SECONDARY,
        fontsize=8,
    )
    fig.savefig(path, dpi=DPI, facecolor=SURFACE)
    plt.close(fig)


def _labels_fit(values: list[float], y_range: float) -> bool:
    ordered = sorted(values)
    return all(upper - lower >= y_range * LABEL_GAP_FRACTION for lower, upper in zip(ordered, ordered[1:]))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("workbook", help="rates.xlsx written by sync_rates.py")
    parser.add_argument("--out", default="rates_indexed.png", help="PNG to write")
    args = parser.parse_args(argv)
    try:
        rates = pd.read_excel(args.workbook, sheet_name="Rates")
        symbols = [column for column in rates.columns if column not in (DATE_COLUMN, BASE_COLUMN)]
        draw(rates, symbols, args.out)
    except (FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
