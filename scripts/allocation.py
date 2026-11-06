"""Min/Max bike allocation: split a regional warehouse pool across stores, one unit at a time.

Rules, in order:
  1. Paid orders first: a store whose paid orders exceed its stock gets bikes to cover them.
  2. Fill every store up to Min, lowest coverage (level / Min) first.
  3. Spread what is left up to Max, lowest coverage first.
level = on_hand + allocated - paid_orders (stock left after paid orders are handed over), never above Max.
"""
import pandas as pd


def allocate(stores: pd.DataFrame, pool: pd.DataFrame) -> pd.DataFrame:
    out = stores.copy()
    out["allocated"], out["reason_paid"], out["reason_min"], out["reason_max"] = 0, 0, 0, 0
    left = pool.set_index(["region", "model"])["warehouse_qty"].to_dict()
    for (region, model), idx in out.groupby(["region", "model"]).groups.items():
        g = out.loc[idx]
        q = left.get((region, model), 0)
        level = (g["on_hand"] - g["paid_orders"]).to_dict()
        give = {i: 0 for i in idx}
        for step, cap in (("reason_paid", {i: 0 for i in idx}), ("reason_min", g["min_qty"].to_dict()),
                          ("reason_max", g["max_qty"].to_dict())):
            while q > 0:
                need = [i for i in idx if level[i] < cap[i] and level[i] < g.at[i, "max_qty"]]
                if not need:
                    break
                i = min(need, key=lambda k: (level[k] / max(g.at[k, "min_qty"], 1), k))
                level[i] += 1
                give[i] += 1
                out.at[i, step] += 1
                q -= 1
        out.loc[idx, "allocated"] = pd.Series(give)
        left[(region, model)] = q
    out["level_after"] = out["on_hand"] + out["allocated"] - out["paid_orders"]
    return out


def self_check():
    s = pd.DataFrame([("A", "N", "M", 0, 3, 2, 4), ("B", "N", "M", 5, 0, 2, 4), ("C", "N", "M", 1, 0, 3, 6)],
                     columns=["store", "region", "model", "on_hand", "paid_orders", "min_qty", "max_qty"])
    r = allocate(s, pd.DataFrame([("N", "M", 8)], columns=["region", "model", "warehouse_qty"])).set_index("store")
    assert r.at["A", "reason_paid"] == 3, r                      # paid orders covered first
    assert r.at["B", "allocated"] == 0                           # already above Max: gets nothing
    assert r["allocated"].sum() == 8 and ((r["level_after"] <= r["max_qty"]) | (r["allocated"] == 0)).all()
    assert r.at["C", "level_after"] >= r.at["C", "min_qty"]      # Min reached before anyone goes to Max
    big = allocate(s, pd.DataFrame([("N", "M", 99)], columns=["region", "model", "warehouse_qty"])).set_index("store")
    assert (big["level_after"] == big["max_qty"].where(big["on_hand"] - big["paid_orders"] < big["max_qty"],
                                                        big["on_hand"] - big["paid_orders"])).all()   # surplus stops at Max
    print("allocation self-check ok")


if __name__ == "__main__":
    self_check()
