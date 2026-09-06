"""Write sample/orders_raw.csv: 300 orders with the kinds of mess real exports have.

Seeded, so the same file comes out every time and the README numbers stay true.
"""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

from cleaning import REQUIRED_COLUMNS

SEED = 42
ROWS = 300
OUT = Path(__file__).parent / "sample" / "orders_raw.csv"
START = date(2026, 1, 1)
DAYS = 181  # January to June
CUSTOMERS = [
    "Acme Corp", "Blue Ridge Bakery", "Cobalt Studio", "Delta Freight", "Evergreen Foods", "Fox and Finch",
    "Granite Tools", "Harbor Lights", "Iris Optics", "Juniper Labs", "Kestrel Media", "Lumen Print",
]
CATEGORIES = ["Electronics", "Office", "Furniture", "Software", "Services"]
EXACT_DUPLICATES = 8
CONFLICTING_DUPLICATES = 3
BAD_DATES = 5
BAD_PRICES = 4
BAD_QUANTITIES = 3
BAD_EMAILS = 2


def messy_name(rng: random.Random, name: str) -> str:
    return rng.choice([name, name.upper(), name.lower(), f"  {name}", f"{name}  ", name.replace(" ", "  ")])


def messy_date(rng: random.Random, when: date) -> str:
    return rng.choice(
        [when.isoformat(), when.strftime("%d/%m/%Y"), when.strftime("%d %b %Y"), when.strftime("%B %d, %Y"), when.strftime("%d.%m.%Y")]
    )


def messy_money(rng: random.Random, amount: float) -> str:
    return rng.choice([f"{amount:.2f}", f"${amount:,.2f}", f"USD {amount:,.2f}", f"$ {amount:.2f}"])


def messy_category(rng: random.Random, category: str) -> str:
    return rng.choice([category, category.lower(), category.upper(), f"{category} "])


def messy_email(rng: random.Random, name: str) -> str:
    domain = name.lower().replace(" ", "") + ".com"
    return rng.choice([f"orders@{domain}", f"ORDERS@{domain}", f" orders@{domain} "])


def build_rows(rng: random.Random) -> list[dict]:
    rows = []
    for number in range(1, ROWS + 1):
        name = rng.choice(CUSTOMERS)
        rows.append(
            {
                "order_id": f"ORD-{number:04d}",
                "order_date": messy_date(rng, START + timedelta(days=rng.randrange(DAYS))),
                "customer": messy_name(rng, name),
                "email": messy_email(rng, name),
                "category": messy_category(rng, rng.choice(CATEGORIES)),
                "quantity": str(rng.randint(1, 20)),
                "unit_price": messy_money(rng, rng.randrange(500, 250000) / 100),
            }
        )
    return rows


def inject_problems(rng: random.Random, rows: list[dict]) -> list[dict]:
    originals = rows[:ROWS]
    for row in rng.sample(originals, BAD_DATES):
        row["order_date"] = rng.choice(["yesterday", "2026-13-40", "n/a", "", "Q1"])
    for row in rng.sample(originals, BAD_PRICES):
        row["unit_price"] = rng.choice(["", "TBD", "free", "call"])
    for row in rng.sample(originals, BAD_QUANTITIES):
        row["quantity"] = rng.choice(["", "two", "1.5"])
    for row in rng.sample(originals, BAD_EMAILS):
        row["email"] = "no email"
    rng.choice(originals)["unit_price"] = "-12.00"
    # Copies come after the corruption above so they really are exact duplicates.
    for row in rng.sample(originals, EXACT_DUPLICATES):
        rows.append(dict(row))
    for row in rng.sample(originals, CONFLICTING_DUPLICATES):
        conflict = dict(row)
        conflict["quantity"] = "99"
        rows.append(conflict)
    rng.shuffle(rows)
    return rows


def main() -> None:
    rng = random.Random(SEED)
    rows = inject_problems(rng, build_rows(rng))
    OUT.parent.mkdir(exist_ok=True)
    with open(OUT, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {OUT}")


if __name__ == "__main__":
    main()
