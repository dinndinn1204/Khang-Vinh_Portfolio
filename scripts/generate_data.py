"""Generate the synthetic datasets used by every project in this repo (fixed seed, so the output is reproducible).

All data here is fake: store names, SKUs, prices and volumes are random draws, not figures from any employer.
"""
from pathlib import Path

import numpy as np
import pandas as pd

rng = np.random.default_rng(2026)
DATA = Path(__file__).resolve().parent.parent / "data"
DATA.mkdir(exist_ok=True)


# ---------- 1. Store demand (weekly, 12 stores x 15 SKUs x 78 weeks) ----------
def demand():
    weeks = pd.date_range("2024-07-01", periods=78, freq="W-MON")
    cats = {"Beverage": 6, "Snack": 5, "Instant food": 4}
    skus = [(f"{c[:3].upper()}-{i + 1:02d}", c) for c, n in cats.items() for i in range(n)]
    rows = []
    for s in range(1, 13):
        store_size = rng.uniform(0.6, 1.6)
        for sku, cat in skus:
            base = rng.lognormal(3.6, 0.45) * store_size
            promo = rng.random(len(weeks)) < 0.08
            for w, p in zip(weeks, promo):
                season = 1 + 0.18 * np.sin(2 * np.pi * (w.dayofyear - 100) / 365)   # hot season lifts drinks
                if cat != "Beverage":
                    season = 1 + 0.06 * np.sin(2 * np.pi * w.dayofyear / 365)
                tet = 1.35 if (w.month == 1 and w.day >= 15) or (w.month == 2 and w.day <= 10) else 1.0
                mu = base * season * tet * (1.45 if p else 1.0) * (1 + 0.002 * (w - weeks[0]).days / 7)
                rows.append((w.date(), f"S{s:02d}", sku, cat, int(p), int(rng.poisson(mu))))
    return pd.DataFrame(rows, columns=["week", "store_id", "sku", "category", "promo", "units"])


# ---------- 2. Bike allocation inputs (24 stores x 3 models, one warehouse pool per region) ----------
def allocation():
    models = ["Model A", "Model B", "Model C"]
    rows = []
    for s in range(1, 25):
        region = "North" if s <= 10 else "South"
        size = rng.choice([1, 2, 3], p=[0.4, 0.4, 0.2])   # small / medium / flagship
        for m in models:
            mn = int(size * rng.integers(2, 4))
            mx = mn * 2 + int(rng.integers(0, 3))
            rows.append((f"Store {s:02d}", region, m, int(rng.integers(0, mx + 1)), int(rng.poisson(size * 0.8)), mn, mx))
    stores = pd.DataFrame(rows, columns=["store", "region", "model", "on_hand", "paid_orders", "min_qty", "max_qty"])
    pool = pd.DataFrame([(r, m, int(rng.integers(25, 60))) for r in ("North", "South") for m in models],
                        columns=["region", "model", "warehouse_qty"])
    return stores, pool


# ---------- 3. Freight: shipments, tariff, weekly diesel price ----------
PROVINCES = {   # province: (hub, distance km) - rough road distances, used only to shape the fake tariff
    "Ho Chi Minh": ("HCM", 15), "Binh Duong": ("HCM", 35), "Dong Nai": ("HCM", 40), "Long An": ("HCM", 50),
    "Tien Giang": ("HCM", 75), "Can Tho": ("HCM", 170), "Vung Tau": ("HCM", 95), "Tay Ninh": ("HCM", 100),
    "Lam Dong": ("HCM", 300), "Khanh Hoa": ("HCM", 430), "Dak Lak": ("HCM", 350), "Kien Giang": ("HCM", 250),
    "Ha Noi": ("HN", 15), "Hai Phong": ("HN", 120), "Bac Ninh": ("HN", 35), "Quang Ninh": ("HN", 160),
    "Nghe An": ("HN", 290), "Thanh Hoa": ("HN", 160), "Thai Nguyen": ("HN", 80), "Da Nang": ("HN", 760),
}
TIERS = ["1", "2-4", "5-9", "10-20", "21-39", "40+"]


def freight():
    tariff = []
    for p, (hub, km) in PROVINCES.items():
        per_bike = 180_000 + km * 1_900   # VND per bike for a single-bike trip
        for t, disc in zip(TIERS, (1.0, 0.82, 0.68, 0.55, 0.47, 0.42)):
            tariff.append((p, hub, t, int(round(per_bike * disc, -3))))
    tariff = pd.DataFrame(tariff, columns=["province", "hub", "tier", "price_per_bike"])

    days = pd.date_range("2025-05-01", "2025-10-31", freq="D")
    diesel = pd.DataFrame({"week": pd.date_range("2025-04-28", "2025-10-27", freq="W-MON")})
    diesel["price_per_litre"] = (20_300 + np.cumsum(rng.normal(0, 350, len(diesel)))).round(-1).astype(int)

    names = list(PROVINCES)
    weight = np.array([12, 6, 5, 4, 3, 4, 3, 2, 2, 2, 2, 2, 10, 4, 4, 3, 2, 2, 2, 2], float)
    rows = []
    for i in range(1800):
        p = rng.choice(names, p=weight / weight.sum())
        ch = rng.choice(["Store", "Dealer", "Customer"], p=[0.45, 0.35, 0.2])
        bikes = 1 if ch == "Customer" else int(np.clip(rng.lognormal(1.6, 0.9), 1, 45))
        rows.append((f"SHP{i + 1:05d}", days[rng.integers(len(days))].date(), PROVINCES[p][0], p, ch, bikes))
    ship = pd.DataFrame(rows, columns=["shipment_id", "picked_up", "hub", "province", "channel", "bikes"])
    return ship.sort_values("picked_up").reset_index(drop=True), tariff, diesel


# ---------- 4. Warehouse & delivery orders (4 business units, 180 days) ----------
def orders():
    days = pd.date_range("2025-01-01", periods=180, freq="D")
    bus = {"AA": 38, "BBC": 22, "POSM": 12, "NFG": 16}   # average orders per day
    pickers = [f"P{i:02d}" for i in range(1, 13)]
    skill = dict(zip(pickers, rng.uniform(0.85, 1.15, len(pickers))))
    reasons = ["Address change", "Wrong item", "Damaged", "Customer not available", "Late pickup"]
    rows, n = [], 0
    for d in days:
        peak = 1.3 if d.day >= 25 else 1.0   # month-end push
        for bu, avg in bus.items():
            for _ in range(rng.poisson(avg * peak * (0.6 if d.dayofweek == 6 else 1.0))):
                n += 1
                pk = rng.choice(pickers)
                late = rng.random() < (0.16 if peak > 1 else 0.07) / skill[pk]
                issue = rng.choice(reasons, p=[0.32, 0.22, 0.12, 0.24, 0.10]) if rng.random() < 0.05 else ""
                rows.append((f"ORD{n:06d}", bu, d.date(), (d + pd.Timedelta(days=2)).date(),
                             (d + pd.Timedelta(days=int(rng.integers(3, 6)) if late else int(rng.integers(1, 3)))).date(),
                             pk, int(rng.integers(1, 12)), issue))
    return pd.DataFrame(rows, columns=["order_id", "business_unit", "order_date", "promised_date", "delivered_date",
                                       "picker_id", "lines", "issue_reason"])


if __name__ == "__main__":
    demand().to_csv(DATA / "store_demand.csv", index=False)
    s, p = allocation()
    s.to_csv(DATA / "allocation_stores.csv", index=False)
    p.to_csv(DATA / "allocation_pool.csv", index=False)
    sh, t, dz = freight()
    sh.to_csv(DATA / "shipments.csv", index=False)
    t.to_csv(DATA / "freight_tariff.csv", index=False)
    dz.to_csv(DATA / "diesel_price.csv", index=False)
    orders().to_csv(DATA / "warehouse_orders.csv", index=False)
    for f in sorted(DATA.glob("*.csv")):
        print(f"{f.name:28s} {sum(1 for _ in f.open()) - 1:>7,} rows")
