# -*- coding: utf-8 -*-
"""Merchandise metric catalog — PRD §5 metrics #27, #28, #29 (BR-11).

Category and brand are DERIVED here, by joining `sales_line` to `product`.
Neither is ever stored on a fact row, so "which brand is this SKU" has exactly
one answer (BR-5 applied to dimensions).

BR-11 — recursive reconciliation — is structural rather than checked after the
fact: the seed ALLOCATES each entity/day's posted net sales and units across
its SKUs, so Σ SKU = Σ category = the entity's day, to the cent, by
construction. `reconcile_lines()` re-derives the identity anyway, because a
rule you only assert in prose is a rule you do not have.

SKU grain exists over the seeded detail window (see `seed.DETAIL_DAYS`).
Outside it these functions return `available: False` with the window stated —
never a silent zero.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from flash.catalog import CatalogError, THRESHOLDS

D = dt.date


def detail_window(da) -> Dict[str, str]:
    if getattr(da, "_detail_window", None) is None:
        row = da.conn.execute(
            "SELECT MIN(date), MAX(date) FROM sales_line").fetchone()
        da._detail_window = {"start": row[0], "end": row[1]}
    return da._detail_window


def has_detail(da, day: D) -> bool:
    w = detail_window(da)
    if not w["start"]:
        return False
    return w["start"] <= day.isoformat() <= w["end"]


def _unavailable(da, day: D, what: str) -> Dict[str, object]:
    w = detail_window(da)
    return {
        "available": False, "date": day.isoformat(), "metric": what,
        "reason": ("SKU-grain data is seeded for %s..%s; %s is outside that "
                   "window. This is UNAVAILABLE, not zero — extend "
                   "seed.DETAIL_DAYS to widen it."
                   % (w["start"], w["end"], day.isoformat())),
    }


def _lines(da, day: D, ids) -> List[tuple]:
    """(sku_id, category, brand_id, entity_id, net_sales_local, units)."""
    if not ids:
        return []
    q = ("SELECT l.sku_id, p.category, p.brand_id, l.entity_id, l.net_sales, "
         "l.units FROM sales_line l JOIN product p ON p.sku_id=l.sku_id "
         "WHERE l.date=? AND l.entity_id IN (%s)" % ",".join("?" * len(ids)))
    return da.conn.execute(q, [day.isoformat()] + list(ids)).fetchall()


# =========================================================================
# #27 Category sales / comp / plan / mix
# =========================================================================

def category_day(da, day: D, **scope) -> Dict[str, object]:
    """#27 for one day: sales, mix, LY-aligned comp on the COMP entity set,
    and a derived category plan (disclosed as derived, never as planned)."""
    if not has_detail(da, day):
        return _unavailable(da, day, "category_day")
    ly = da.ly_date(day)
    all_ids = da.scope_ids(**scope)
    comp_ids = da.comp_set(day, **scope)

    def by_cat(d, ids):
        out = {}
        for sku, cat, _b, eid, net, units in _lines(da, d, ids):
            ccy = da.entity(eid)["currency"]
            a = out.setdefault(cat, [0.0, 0])
            a[0] += da.convert(net, ccy)
            a[1] += units
        return out

    ty_all = by_cat(day, all_ids)
    ty_comp = by_cat(day, comp_ids)
    ly_comp = by_cat(ly, comp_ids)
    ly_all = by_cat(ly, all_ids)
    total = sum(v[0] for v in ty_all.values())
    plan = _derived_category_plan(da, day, ly, all_ids, **scope)

    rows = []
    for cat in sorted(set(list(ty_all) + list(ly_comp) + list(ly_all))):
        sales, units = ty_all.get(cat, [0.0, 0])
        cty = ty_comp.get(cat, [0.0, 0])[0]
        cly = ly_comp.get(cat, [0.0, 0])[0]
        cat_plan = plan["plan"].get(cat, 0.0)
        planned_actual = plan["planned_actual"].get(cat, 0.0)
        rows.append({
            "category": cat, "brand_id": _brand_of(da, cat),
            "net_sales": round(sales, 2), "units": units,
            "mix_pct": (sales / total) if total else None,
            "comp_ty": round(cty, 2), "comp_ly": round(cly, 2),
            "comp_pct": (cty / cly - 1.0) if cly else None,
            "plan": round(cat_plan, 2) if cat_plan else None,
            "planned_actual": round(planned_actual, 2) if cat_plan else None,
            "plan_attainment": ((planned_actual / cat_plan) if cat_plan else None),
            "plan_coverage": ((planned_actual / sales) if (cat_plan and sales)
                              else None),
            "aur": (sales / units) if units else None,
            "aus": (sales / units) if units else None,
        })
    rows.sort(key=lambda r: (-r["net_sales"], r["category"]))
    _reconcile_display(rows, "net_sales", total)
    return {
        "available": True, "date": day.isoformat(), "ly_date": ly.isoformat(),
        "categories": rows, "total_net_sales": round(total, 2),
        "reconciliation": {
            "sum_of_categories": round(sum(r["net_sales"] for r in rows), 2),
            "entity_day_total": da.net_sales(day, **scope),
        },
        "plan_basis": "Category plan is DERIVED, not planned: each DAY-grain "
                      "entity's day plan is split by that entity's own "
                      "LY-aligned category mix. `planned_actual` restricts the "
                      "actual to the same entities, so attainment compares "
                      "like with like; `plan_coverage` states how much of the "
                      "category's sales sit inside a plan at all (BR-19).",
        "plan_entities": plan["entities"],
        "comp_basis": "Category comp uses the same comp entity set as the "
                      "headline, so categories sum to the headline comp (BR-11).",
    }


def _derived_category_plan(da, day: D, ly: D, all_ids, **scope):
    """Allocate each DAY-grain entity's plan across categories by its OWN
    LY-aligned category mix, and carry the matching restricted actual."""
    plan_ids = [e for e in all_ids if da.plan_grain_of(e) == "DAY"]
    plan, planned_actual = {}, {}
    if not plan_ids:
        return {"plan": plan, "planned_actual": planned_actual, "entities": []}
    ly_mix, ty_val = {}, {}
    for sku, cat, _b, eid, net, units in _lines(da, ly, plan_ids):
        ly_mix.setdefault(eid, {})
        ly_mix[eid][cat] = ly_mix[eid].get(cat, 0.0) + net       # local ccy
    for sku, cat, _b, eid, net, units in _lines(da, day, plan_ids):
        ty_val.setdefault(eid, {})
        ty_val[eid][cat] = ty_val[eid].get(cat, 0.0) + net
    for eid in plan_ids:
        p = da.plan_of(eid, day)
        mix = ly_mix.get(eid)
        if not p or not mix:
            continue
        tot = sum(mix.values())
        if not tot:
            continue
        for cat, v in mix.items():
            plan[cat] = plan.get(cat, 0.0) + p * (v / tot)
        ccy = da.entity(eid)["currency"]
        for cat, v in ty_val.get(eid, {}).items():
            planned_actual[cat] = planned_actual.get(cat, 0.0) + da.convert(v, ccy)
    return {"plan": plan, "planned_actual": planned_actual,
            "entities": sorted(plan_ids)}


def _reconcile_display(rows, key, total):
    """Make the DISPLAYED parts sum to the displayed whole.

    Five categories each rounded to cents can miss their own total by a penny.
    The underlying allocation is exact; this pushes the display residual onto
    the largest row so a reader never sees a column that does not add up.
    BR-11 is about what the reader can check, not only what the database
    knows."""
    if not rows:
        return
    cents = [int(round(r[key] * 100)) for r in rows]
    residual = int(round(total * 100)) - sum(cents)
    if residual:
        biggest = max(range(len(rows)), key=lambda i: (cents[i], -i))
        cents[biggest] += residual
    for r, c in zip(rows, cents):
        r[key] = round(c / 100.0, 2)


def _brand_of(da, category):
    for b in da.brands():
        if category in b["categories"]:
            return b["brand_id"]
    return None


def category_window(da, day: D, window: str, **scope) -> Dict[str, object]:
    """#27 across a fiscal window (built day by day, aligned-day discipline)."""
    days = [d for d in da.window_dates(day, window) if has_detail(da, d)]
    if not days:
        return _unavailable(da, day, "category_window")
    acc = {}
    for d in days:
        c = category_day(da, d, **scope)
        for r in c["categories"]:
            a = acc.setdefault(r["category"], [0.0, 0, 0.0, 0.0])
            a[0] += r["net_sales"]
            a[1] += r["units"]
            a[2] += r["comp_ty"]
            a[3] += r["comp_ly"]
    total = sum(v[0] for v in acc.values())
    rows = [{"category": k, "net_sales": round(v[0], 2), "units": v[1],
             "mix_pct": (v[0] / total) if total else None,
             "comp_ty": round(v[2], 2), "comp_ly": round(v[3], 2),
             "comp_pct": (v[2] / v[3] - 1.0) if v[3] else None,
             "aur": (v[0] / v[1]) if v[1] else None}
            for k, v in sorted(acc.items())]
    rows.sort(key=lambda r: (-r["net_sales"], r["category"]))
    return {"available": True, "window": window, "end": day.isoformat(),
            "days": len(days), "categories": rows,
            "total_net_sales": round(total, 2)}


# =========================================================================
# #28 Category AUR / UPT
# =========================================================================

def category_basket(da, day: D, **scope) -> Dict[str, object]:
    """#28 AUR (= AUS) and UPT by category.

    UPT needs transactions, which exist at entity grain only — a SKU line has
    no transaction count. Category UPT is therefore derived by allocating the
    entity's transactions across categories by that category's share of the
    entity's units, and is labelled as derived."""
    if not has_detail(da, day):
        return _unavailable(da, day, "category_basket")
    ids = da.scope_ids(**scope)
    per_entity_units, cat_units, cat_sales = {}, {}, {}
    for sku, cat, _b, eid, net, units in _lines(da, day, ids):
        ccy = da.entity(eid)["currency"]
        per_entity_units[eid] = per_entity_units.get(eid, 0) + units
        cat_units[cat] = cat_units.get(cat, 0) + units
        cat_sales[cat] = cat_sales.get(cat, 0.0) + da.convert(net, ccy)
    cat_txns = {}
    for sku, cat, _b, eid, net, units in _lines(da, day, ids):
        row = da.sales_row(eid, day)
        if not row or not per_entity_units.get(eid):
            continue
        cat_txns[cat] = cat_txns.get(cat, 0.0) + (
            row["transactions"] * units / float(per_entity_units[eid]))
    rows = []
    for cat in sorted(cat_sales):
        s, un, tx = cat_sales[cat], cat_units[cat], cat_txns.get(cat, 0.0)
        rows.append({"category": cat, "net_sales": round(s, 2), "units": un,
                     "aur": (s / un) if un else None,
                     "aus": (s / un) if un else None,
                     "upt": (un / tx) if tx else None,
                     "ast": (s / tx) if tx else None,
                     "derived_transactions": round(tx, 2)})
    return {"available": True, "date": day.isoformat(), "categories": rows,
            "upt_basis": "category transactions are DERIVED by allocating each "
                         "entity's transactions across categories by unit "
                         "share; transactions are not captured at SKU grain"}


# =========================================================================
# #29 Top / bottom SKU movers
# =========================================================================

def sku_movers(da, day: D, n: int = 10, category: Optional[str] = None,
               **scope) -> Dict[str, object]:
    """#29 Top/bottom-N SKU movers vs the LY-aligned day, in the contribution
    format metric #15 established: each SKU's delta over the LY total, so the
    listed contributions add up to the move they are explaining."""
    if not has_detail(da, day):
        return _unavailable(da, day, "sku_movers")
    ly = da.ly_date(day)
    ids = da.comp_set(day, **scope)

    def agg(d):
        out = {}
        for sku, cat, brand, eid, net, units in _lines(da, d, ids):
            if category and cat != category:
                continue
            a = out.setdefault(sku, [0.0, 0, cat, brand])
            a[0] += da.convert(net, da.entity(eid)["currency"])
            a[1] += units
        return out

    ty, lyv = agg(day), agg(ly)
    ly_total = sum(v[0] for v in lyv.values())
    prod = {p["sku_id"]: p for p in da.products()}
    rows = []
    for sku in sorted(set(list(ty) + list(lyv))):
        t = ty.get(sku, [0.0, 0, None, None])
        l = lyv.get(sku, [0.0, 0, None, None])
        p = prod[sku]
        rows.append({
            "sku_id": sku, "name": p["name"], "category": p["category"],
            "brand_id": p["brand_id"], "launch_date": p["launch_date"],
            "days_since_launch": (day - D.fromisoformat(p["launch_date"])).days,
            "ty": round(t[0], 2), "ly": round(l[0], 2),
            "ty_units": t[1], "ly_units": l[1],
            "delta": round(t[0] - l[0], 2),
            "contribution": ((t[0] - l[0]) / ly_total) if ly_total else 0.0,
            "pct_vs_ly": (t[0] / l[0] - 1.0) if l[0] else None,
        })
    rows.sort(key=lambda r: (-r["delta"], r["sku_id"]))
    return {
        "available": True, "date": day.isoformat(), "ly_date": ly.isoformat(),
        "category": category, "comp_entities": len(ids),
        "top": rows[:n], "bottom": list(reversed(rows[-n:])),
        "ly_total": round(ly_total, 2),
        "contribution_sum": round(sum(r["contribution"] for r in rows), 9),
        "basis": "comp entity set, LY-aligned day; contributions are each "
                 "SKU's delta over the LY total, so they sum to the group's "
                 "own comp % (BR-6 applied at SKU grain)",
    }


def sku_movers_window(da, day: D, window: str, n: int = 10,
                      category: Optional[str] = None, **scope):
    """#29 across a window — the form the category exception drills into."""
    days = [d for d in da.window_dates(day, window) if has_detail(da, d)]
    if not days:
        return _unavailable(da, day, "sku_movers_window")
    acc = {}
    for d in days:
        m = sku_movers(da, d, n=10 ** 6, category=category, **scope)
        for r in m["top"]:
            a = acc.setdefault(r["sku_id"], [0.0, 0.0, r])
            a[0] += r["ty"]
            a[1] += r["ly"]
    ly_total = sum(v[1] for v in acc.values())
    rows = []
    for sku, (t, l, meta) in acc.items():
        rows.append({"sku_id": sku, "name": meta["name"],
                     "category": meta["category"], "brand_id": meta["brand_id"],
                     "launch_date": meta["launch_date"],
                     "ty": round(t, 2), "ly": round(l, 2),
                     "delta": round(t - l, 2),
                     "contribution": ((t - l) / ly_total) if ly_total else 0.0,
                     "pct_vs_ly": (t / l - 1.0) if l else None})
    rows.sort(key=lambda r: (-r["delta"], r["sku_id"]))
    return {"available": True, "window": window, "end": day.isoformat(),
            "days": len(days), "category": category,
            "top": rows[:n], "bottom": list(reversed(rows[-n:])),
            "ly_total": round(ly_total, 2)}


# =========================================================================
# Category exception + reconciliation
# =========================================================================

def category_exceptions(da, day: D, **scope) -> List[dict]:
    """A category comping more than 3 pts below the fleet (PRD §10), with the
    adverse SKUs behind it attached so the exception drills in one hop."""
    c = category_day(da, day, **scope)
    if not c.get("available"):
        return []
    fleet = da.comp_pct(day, **scope)
    if fleet is None:
        return []
    thr = THRESHOLDS["category_vs_fleet_pts"]
    out = []
    for r in c["categories"]:
        if r["comp_pct"] is None:
            continue
        gap = r["comp_pct"] - fleet
        if gap <= -thr:
            movers = sku_movers(da, day, n=3, category=r["category"], **scope)
            out.append({
                "category": r["category"], "brand_id": r["brand_id"],
                "comp_pct": r["comp_pct"], "fleet_comp_pct": fleet,
                "gap_pts": gap, "threshold_pts": thr,
                "top_adverse_skus": movers["bottom"][:3],
                "message": ("%s comps %.1f%% against a fleet %.1f%% — %.1f pts "
                            "adverse" % (r["category"], r["comp_pct"] * 100,
                                         fleet * 100, gap * 100)),
            })
    out.sort(key=lambda r: r["gap_pts"])
    return out


def category_slide_run(da, day: D, category: str, max_days: int = 30,
                       **scope) -> Dict[str, object]:
    """How many consecutive days a category has comped negative, ending on
    `day` — the evidence a 'slide' is a trend, not a bad Tuesday."""
    run, checked = 0, []
    for i in range(max_days):
        d = day - dt.timedelta(days=i)
        if not has_detail(da, d):
            break
        c = category_day(da, d, **scope)
        row = next((r for r in c["categories"] if r["category"] == category), None)
        if row is None or row["comp_pct"] is None or row["comp_pct"] >= 0:
            break
        run += 1
        checked.append({"date": d.isoformat(), "comp_pct": row["comp_pct"]})
    return {"category": category, "as_of": day.isoformat(),
            "consecutive_negative_days": run, "days": checked}


def reconcile_lines(da, day: D, **scope) -> Dict[str, object]:
    """BR-11 re-derived: Σ sales_line = sales_day, per entity, to the cent."""
    ids = da.scope_ids(**scope)
    if not has_detail(da, day):
        return _unavailable(da, day, "reconcile_lines")
    rows = da.conn.execute(
        "SELECT entity_id, ROUND(SUM(net_sales),2), SUM(units) FROM sales_line "
        "WHERE date=? AND entity_id IN (%s) GROUP BY 1" % ",".join("?" * len(ids)),
        [day.isoformat()] + list(ids)).fetchall()
    breaks = []
    for eid, net, units in rows:
        d = da.sales_row(eid, day)
        if d is None:
            breaks.append({"entity_id": eid, "issue": "lines without a day row"})
            continue
        if abs(net - d["net_sales"]) > 0.005 or units != d["units"]:
            breaks.append({"entity_id": eid, "line_sales": net,
                           "day_sales": d["net_sales"], "line_units": units,
                           "day_units": d["units"]})
    return {"available": True, "date": day.isoformat(),
            "entities_checked": len(rows), "breaks": breaks,
            "reconciled": not breaks}
