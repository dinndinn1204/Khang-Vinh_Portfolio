"""Run the four portfolio projects on the synthetic data.

Writes result tables to output/, headline numbers to output/summary.json and the chart series to docs/data.js
(read by the dashboard docs/index.html; scripts/shoot.mjs turns its chart cards into charts/*.png).
"""
import json
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from allocation import allocate, self_check

ROOT = Path(__file__).resolve().parent.parent
DATA, OUT, DOCS, SQL = ROOT / "data", ROOT / "output", ROOT / "docs", ROOT / "sql"
OUT.mkdir(exist_ok=True)
summary, charts = {}, {}


def run_sql(con, file):
    return pd.read_sql_query((SQL / file).read_text(encoding="utf-8"), con)


def r1(s):
    return [None if pd.isna(v) else round(float(v), 1) for v in s]


# ---------- 1. Demand forecasting & replenishment ----------
def forecasting():
    d = pd.read_csv(DATA / "store_demand.csv", parse_dates=["week"]).sort_values(["store_id", "sku", "week"])
    test_from = d["week"].drop_duplicates().sort_values().iloc[52]
    g = d.groupby(["store_id", "sku"])["units"]
    d["Naive"] = g.shift(1)
    d["Moving avg (4w)"] = g.transform(lambda s: s.rolling(4).mean().shift(1))
    # promo uplift per category, learned on the training weeks only
    train = d[d["week"] < test_from]
    base = train[train["promo"] == 0].groupby(["store_id", "sku"])["units"].mean().rename("base")
    t = train.join(base, on=["store_id", "sku"])
    uplift = (t[t["promo"] == 1]["units"] / t[t["promo"] == 1]["base"]).groupby(t["category"]).mean()
    d["uplift"] = np.where(d["promo"] == 1, d["category"].map(uplift), 1.0)
    d["adj"] = d["units"] / d["uplift"]
    d["Smoothing + promo"] = d.groupby(["store_id", "sku"])["adj"].transform(lambda s: s.ewm(alpha=0.3).mean().shift(1)) * d["uplift"]
    m = ["Naive", "Moving avg (4w)", "Smoothing + promo"]
    test = d[d["week"] >= test_from].copy()

    res = []
    for k in m:
        wape = (test[k] - test["units"]).abs().sum() / test["units"].sum()
        stock_cap = np.ceil(test[k] * 1.15)   # order-up-to level: forecast + 15 % buffer, weekly delivery
        res.append({"method": k, "wape_pct": round(100 * wape, 1),
                    "stockout_pct": round(100 * (test["units"] > stock_cap).mean(), 1),
                    "avg_leftover_units": round((stock_cap - test["units"]).clip(lower=0).mean(), 1)})
    res = pd.DataFrame(res)
    res.to_csv(OUT / "forecast_accuracy.csv", index=False)
    summary["forecast"] = {"series": int(d.groupby(["store_id", "sku"]).ngroups), "weeks": int(d["week"].nunique()),
                           "uplift_by_category": uplift.round(2).to_dict(), "methods": res.to_dict("records")}

    chain = d.groupby("week")[["units", *m]].sum(min_count=1)
    test_mask = chain.index >= test_from
    charts["forecast"] = {"weeks": chain.index.strftime("%Y-%m-%d").tolist(), "test_from": test_from.strftime("%Y-%m-%d"),
                          "actual": chain["units"].astype(int).tolist(),
                          "ma4": r1(chain["Moving avg (4w)"].where(test_mask)), "es": r1(chain["Smoothing + promo"].where(test_mask)),
                          "methods": res.to_dict("records")}


# ---------- 2. Min/Max allocation ----------
def allocation():
    self_check()
    s = pd.read_csv(DATA / "allocation_stores.csv")
    p = pd.read_csv(DATA / "allocation_pool.csv")
    r = allocate(s, p)
    r.to_csv(OUT / "allocation_result.csv", index=False)
    summary["allocation"] = {"store_models": len(r), "pool": int(p["warehouse_qty"].sum()), "allocated": int(r["allocated"].sum()),
                             "below_min_before": int((s["on_hand"] - s["paid_orders"] < s["min_qty"]).sum()),
                             "below_min_after": int((r["level_after"] < r["min_qty"]).sum()),
                             "paid_orders_uncovered_after": int((r["on_hand"] + r["allocated"] < r["paid_orders"]).sum())}
    charts["allocation"] = r[["store", "region", "model", "on_hand", "paid_orders", "min_qty", "max_qty", "allocated",
                              "reason_paid", "reason_min", "reason_max"]].to_dict("records")


# ---------- 3. Freight cost estimator ----------
TIER_BINS, TIER_LABELS = [0, 1, 4, 9, 20, 39, 10 ** 6], ["1", "2-4", "5-9", "10-20", "21-39", "40+"]
FUEL_BANDS = [(21_000, 1.00), (23_000, 1.05), (10 ** 9, 1.10)]   # diesel VND/litre at pick-up: <21K base, <23K +5 %, else +10 %


def fuel_factor(price):
    return next(f for cap, f in FUEL_BANDS if price < cap)


def freight(con):
    sh = pd.read_csv(DATA / "shipments.csv", parse_dates=["picked_up"])
    tariff = pd.read_csv(DATA / "freight_tariff.csv", dtype={"tier": str})
    diesel = pd.read_csv(DATA / "diesel_price.csv", parse_dates=["week"])
    sh["tier"] = pd.cut(sh["bikes"], TIER_BINS, labels=TIER_LABELS).astype(str)
    sh = pd.merge_asof(sh.sort_values("picked_up"), diesel.sort_values("week"), left_on="picked_up", right_on="week")
    sh = sh.merge(tariff, on=["province", "hub", "tier"], how="left")
    assert sh["price_per_bike"].notna().all(), "every route has a tariff row"
    sh["fuel_factor"] = sh["price_per_litre"].map(fuel_factor)
    sh["freight_vnd"] = (sh["bikes"] * sh["price_per_bike"] * sh["fuel_factor"]).round(-3).astype(int)
    sh["picked_up"] = sh["picked_up"].dt.strftime("%Y-%m-%d")
    sh = sh.drop(columns="week")
    sh.to_csv(OUT / "freight_priced.csv", index=False)
    sh.to_sql("freight_priced", con, index=False)
    m = run_sql(con, "04_freight_by_month_channel.sql")
    m.to_csv(OUT / "freight_by_month_channel.csv", index=False)
    summary["freight"] = {"trips": len(sh), "bikes": int(sh["bikes"].sum()), "freight_bn_vnd": round(sh["freight_vnd"].sum() / 1e9, 2),
                          "vnd_per_bike": int(sh["freight_vnd"].sum() / sh["bikes"].sum()),
                          "fuel_surcharge_trips_pct": round(100 * (sh["fuel_factor"] > 1).mean(), 1)}

    pv = m.pivot(index="month", columns="channel", values="freight_vnd").fillna(0) / 1e6
    dz = diesel.set_index("week")["price_per_litre"].resample("MS").mean().reindex(pd.to_datetime(pv.index + "-01"))
    t = sh.groupby(["tier", "hub"]).apply(lambda g: g["freight_vnd"].sum() / g["bikes"].sum(), include_groups=False).unstack()
    t = t.reindex(TIER_LABELS) / 1000
    prov = sh.groupby("province").agg(trips=("shipment_id", "size"), bikes=("bikes", "sum"), freight=("freight_vnd", "sum"))
    prov = prov.assign(per_bike=prov["freight"] / prov["bikes"]).sort_values("freight", ascending=False)
    charts["freight"] = {"months": pv.index.tolist(), "channels": {c: r1(pv[c]) for c in ("Store", "Dealer", "Customer")},
                         "diesel": [round(v / 1000, 2) for v in dz.values], "tiers": TIER_LABELS,
                         "per_bike": {h: r1(t[h]) for h in ("HCM", "HN")},
                         "provinces": [{"province": k, "trips": int(v.trips), "bikes": int(v.bikes), "freight_m": round(v.freight / 1e6, 1),
                                        "per_bike_k": round(v.per_bike / 1000, 1)} for k, v in prov.iterrows()]}


# ---------- 4. Warehouse & delivery KPIs (SQL) ----------
def warehouse(con):
    o = pd.read_csv(DATA / "warehouse_orders.csv")
    o.to_sql("warehouse_orders", con, index=False)
    a, b, c = (run_sql(con, f) for f in ("01_ontime_by_bu_month.sql", "02_picker_ranking.sql", "03_issue_pareto.sql"))
    for df, n in ((a, "ontime_by_bu_month"), (b, "picker_ranking"), (c, "issue_pareto")):
        df.to_csv(OUT / f"{n}.csv", index=False)
    summary["warehouse"] = {"orders": len(o), "on_time_pct": round(100 * (o["delivered_date"] <= o["promised_date"]).mean(), 1),
                            "top2_issue_share_pct": float(c["cumulative_pct"].iloc[1]),
                            "best_picker": b.iloc[0]["picker_id"],
                            "picker_spread_lines_per_day": round(b["lines_per_day"].max() - b["lines_per_day"].min(), 1)}

    o["order_date"] = pd.to_datetime(o["order_date"])
    per_day = o.groupby("order_date").size()
    end = per_day.index.day >= 25
    ok = o["delivered_date"] <= o["promised_date"]
    summary["warehouse"]["month_end_lift_pct"] = round(100 * (per_day[end].mean() / per_day[~end].mean() - 1), 1)
    summary["warehouse"]["on_time_month_end_pct"] = round(100 * ok[o["order_date"].dt.day >= 25].mean(), 1)
    summary["warehouse"]["on_time_rest_pct"] = round(100 * ok[o["order_date"].dt.day < 25].mean(), 1)
    daily = o.pivot_table(index="order_date", columns="business_unit", values="order_id", aggfunc="count").fillna(0).rolling(7).mean()
    ot = o.assign(ok=o["delivered_date"] <= o["promised_date"]).set_index("order_date")["ok"].resample("W-MON").mean() * 100
    charts["warehouse"] = {"days": daily.index.strftime("%Y-%m-%d").tolist(), "bu": {k: r1(daily[k]) for k in daily.columns},
                           "weeks": ot.index.strftime("%Y-%m-%d").tolist(), "on_time": r1(ot),
                           "issues": c.to_dict("records"), "pickers": b.to_dict("records")}


if __name__ == "__main__":
    con = sqlite3.connect(":memory:")
    forecasting()
    allocation()
    freight(con)
    warehouse(con)
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    (DOCS / "data.js").write_text("window.DATA = " + json.dumps({"summary": summary, **charts}, ensure_ascii=False) + ";\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, ensure_ascii=False))
