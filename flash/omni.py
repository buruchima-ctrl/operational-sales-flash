# -*- coding: utf-8 -*-
"""Omni metric catalog — PRD §5 metrics #16–24 and #35 (BR-9, BR-10, BR-14).

An extension of `flash.catalog.DataAccess`, kept in its own module so the omni
family definitions read as one document. Every function takes the DataAccess
instance as its first argument; none of them re-derives a core metric.

Two laws govern this whole file.

**BR-9 — attribution, never addition.** An omni order's `sales` is a slice of
money that is ALREADY in `sales_day`: a BOPIS order lives inside e-commerce
demand, its pickup upsell inside the fulfilling store's sales, a Click &
Reserve conversion inside store sales. Nothing here is ever added to a
headline. `attribution_note()` states, per family, where the money lives, and
`assert_headline_invariant()` proves the headline is untouched.

**BR-10 — dual basis, never mixed.** Every family has a RECOGNIZED basis
(BOPIS picked up, RTD delivered, C&R converted, BORIS returned) and an
ALL-INCLUSIVE basis (adding in-progress / partial / cancelled). They are
separate series with separate labels. OOFIS is normalised to the same pattern,
fixing the source BRD's inconsistency (reconciliation §5).

The source BRD defines "AOV FSS" and "AOV Online" four times, once per family,
with drifting wording. Here they are computed once — `basis_aovs()` — and
`family_lifts()` scopes them. That collapse is BR-5 doing its job.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from flash.catalog import CatalogError, LABEL_SAVING_USD, THRESHOLDS

D = dt.date

FAMILIES = ("BOPIS", "RTD", "OOFIS", "CR")
FAMILY_LABEL = {
    "BOPIS": "Buy Online, Pick up In Store",
    "RTD": "Real-Time Delivery",
    "OOFIS": "Order Online From In Store",
    "CR": "Click & Reserve",
}
RECOGNITION_EVENT = {"BOPIS": "picked up", "RTD": "delivered",
                     "OOFIS": "fulfilled", "CR": "converted in store"}
# Where each family's money already sits in the headline (BR-9).
ATTRIBUTION = {
    "BOPIS": "inside e-commerce demand; pickup upsell inside store sales",
    "RTD": "inside e-commerce demand",
    "OOFIS": "inside e-commerce demand (the order is placed online)",
    "CR": "inside store sales (the reservation converts at the door)",
    "BORIS": "returns reduce e-commerce settled sales; saves sit inside "
             "store sales",
}

_OMNI_COLS = ("order_id", "order_type", "store_id", "customer_id",
              "created_date", "fulfilled_date", "status", "sales", "items",
              "upsell_sales", "upsell_items", "attributed_to")
_RET_COLS = ("return_id", "return_date", "store_id", "customer_id", "amount",
             "items", "saved_sales", "saved")


# =========================================================================
# Indexes (loaded once per DataAccess, like the sales index)
# =========================================================================

def _omni_index(da):
    if getattr(da, "_omni_idx", None) is None:
        by_created, by_fulfilled = {}, {}
        for row in da.conn.execute(
                "SELECT %s FROM omni_order" % ",".join(_OMNI_COLS)):
            d = dict(zip(_OMNI_COLS, row))
            by_created.setdefault((d["created_date"], d["order_type"]), []).append(d)
            if d["fulfilled_date"]:
                by_fulfilled.setdefault(
                    (d["fulfilled_date"], d["order_type"]), []).append(d)
        da._omni_idx = (by_created, by_fulfilled)
    return da._omni_idx


def _return_index(da):
    if getattr(da, "_ret_idx", None) is None:
        idx = {}
        for row in da.conn.execute(
                "SELECT %s FROM return_event" % ",".join(_RET_COLS)):
            d = dict(zip(_RET_COLS, row))
            idx.setdefault(d["return_date"], []).append(d)
        da._ret_idx = idx
    return da._ret_idx


def _agg(da, rows, scope_ids):
    """Aggregate a list of order dicts into reporting currency."""
    orders = items = up_orders = up_items = 0
    sales = upsell = 0.0
    for r in rows:
        if r["store_id"] not in scope_ids:
            continue
        ccy = da.entity(r["store_id"])["currency"]
        orders += 1
        items += r["items"]
        sales += da.convert(r["sales"], ccy)
        if r["upsell_sales"]:
            up_orders += 1
            up_items += r["upsell_items"]
            upsell += da.convert(r["upsell_sales"], ccy)
    return {
        "orders": orders, "items": items, "sales": round(sales, 2),
        "aov": (sales / orders) if orders else None,
        "upt": (items / float(orders)) if orders else None,
        "upsell_orders": up_orders, "upsell_items": up_items,
        "upsell_sales": round(upsell, 2),
        "upsell_attach_pct": (up_orders / float(orders)) if orders else None,
        "upsell_aov": (upsell / up_orders) if up_orders else None,
    }


# =========================================================================
# #16 / #17 / #20 / #21 / #24 — the family day object (dual basis, BR-10)
# =========================================================================

def family_day(da, family: str, day: D, **scope) -> Dict[str, object]:
    """One omni family for one day, on BOTH bases, with the LY-aligned
    comparison. Covers #16/#17 (BOPIS), #20 (RTD), #21 (OOFIS), #24 (C&R)."""
    if family not in FAMILIES:
        raise CatalogError(
            "omni family %r is not one of %s. Appointments, virtual selling "
            "and ship-from-store are undefined in the source BRD and are "
            "deliberately out of scope, not silently empty."
            % (family, FAMILIES))
    by_created, by_fulfilled = _omni_index(da)
    ids = set(da.scope_ids(**da._narrow(scope, channel="STORE")))
    ly = da.ly_date(day)

    def sides(d):
        iso = d.isoformat()
        rec = _agg(da, by_fulfilled.get((iso, family), []), ids)
        allin = _agg(da, by_created.get((iso, family), []), ids)
        return rec, allin

    rec, allin = sides(day)
    ly_rec, ly_allin = sides(ly)

    def cohort(d):
        """Completion measured on the CREATED-day cohort: of the orders placed
        on `d`, what share reached the recognition event. Dividing the
        recognized series by the all-inclusive series instead would compare two
        different populations (recognition lags creation) and can exceed 100%
        — the mixing BR-10 forbids."""
        mix = {}
        for r in by_created.get((d.isoformat(), family), []):
            if r["store_id"] in ids:
                mix[r["status"]] = mix.get(r["status"], 0) + 1
        n = sum(mix.values())
        return mix, ((mix.get("completed", 0) / float(n)) if n else None)

    status_mix, completion = cohort(day)
    _ly_mix, ly_completion = cohort(ly)
    return {
        "family": family, "label": FAMILY_LABEL[family],
        "date": day.isoformat(), "ly_date": ly.isoformat(),
        "recognized": rec,
        "recognized_basis": "%s on the day (excludes in-progress, partial and "
                            "cancelled)" % RECOGNITION_EVENT[family],
        "all_inclusive": allin,
        "all_inclusive_basis": "all orders created on the day, every status",
        "ly_recognized": ly_rec, "ly_all_inclusive": ly_allin,
        "recognized_pct_vs_ly": (rec["sales"] / ly_rec["sales"] - 1.0
                                 if ly_rec["sales"] else None),
        "all_inclusive_pct_vs_ly": (allin["sales"] / ly_allin["sales"] - 1.0
                                    if ly_allin["sales"] else None),
        "completion_rate": completion,
        "ly_completion_rate": ly_completion,
        "completion_basis": "share of the day's CREATED cohort that reached "
                            "'%s'" % RECOGNITION_EVENT[family],
        "status_mix": status_mix,
        "attribution": ATTRIBUTION[family],
        "basis_warning": "Recognized and all-inclusive are different series. "
                         "Never add them and never chart them as one (BR-10).",
    }


def bopis_upsell(da, day: D, **scope) -> Dict[str, object]:
    """#18 BOPIS upsell $ / orders / % — the store-side attach on a pickup.

    Attributed to the fulfilling store's own sales, never to e-commerce."""
    f = family_day(da, "BOPIS", day, **scope)
    r, lyr = f["recognized"], f["ly_recognized"]
    return {
        "date": day.isoformat(), "ly_date": f["ly_date"],
        "upsell_sales": r["upsell_sales"], "upsell_orders": r["upsell_orders"],
        "upsell_items": r["upsell_items"],
        "attach_pct": r["upsell_attach_pct"], "upsell_aov": r["upsell_aov"],
        "picked_up_orders": r["orders"],
        "ly_upsell_sales": lyr["upsell_sales"],
        "ly_attach_pct": lyr["upsell_attach_pct"],
        "pct_vs_ly": (r["upsell_sales"] / lyr["upsell_sales"] - 1.0
                      if lyr["upsell_sales"] else None),
        "attribution": "upsell sits inside the fulfilling store's net sales "
                       "(BR-9) — it is not added to BOPIS sales",
    }


def upsell_leaderboard(da, day: D, window_days: int = 14,
                       **scope) -> List[dict]:
    """Store leaderboard by upsell attach % over a trailing window — the
    surface storyline 1 (the upsell champion) has to win."""
    by_created, by_fulfilled = _omni_index(da)
    ids = da.scope_ids(**da._narrow(scope, channel="STORE"))
    acc = dict((i, [0, 0, 0.0]) for i in ids)      # picked up, attached, $
    for i in range(window_days):
        iso = (day - dt.timedelta(days=i)).isoformat()
        for r in by_fulfilled.get((iso, "BOPIS"), []):
            if r["store_id"] not in acc:
                continue
            a = acc[r["store_id"]]
            a[0] += 1
            if r["upsell_sales"]:
                a[1] += 1
                a[2] += da.convert(r["upsell_sales"],
                                   da.entity(r["store_id"])["currency"])
    out = []
    for eid, (n, k, amt) in acc.items():
        if not n:
            continue
        e = da.entity(eid)
        out.append({"entity_id": eid, "name": e["name"], "region": e["region"],
                    "brand_id": e["brand_id"], "picked_up": n, "attached": k,
                    "attach_pct": k / float(n), "upsell_sales": round(amt, 2),
                    "window_days": window_days})
    out.sort(key=lambda r: (-r["attach_pct"], r["entity_id"]))
    return out


def pickup_execution(da, day: D, window_days: int = 14, **scope) -> Dict[str, object]:
    """The recognized-vs-all-inclusive divergence, by region — how storyline 2
    (a region trailing in pickup conversion) becomes visible."""
    by_created, by_fulfilled = _omni_index(da)
    ent = {e["entity_id"]: e for e in da._scope_entities(
        **da._narrow(scope, channel="STORE"))}
    acc = {}
    for i in range(window_days):
        iso = (day - dt.timedelta(days=i)).isoformat()
        for r in by_created.get((iso, "BOPIS"), []):
            e = ent.get(r["store_id"])
            if e is None:
                continue
            a = acc.setdefault(e["region"], [0, 0])
            a[0] += 1
            if r["status"] == "completed":
                a[1] += 1
    rows = [{"region": k, "created": v[0], "picked_up": v[1],
             "pickup_rate": (v[1] / float(v[0])) if v[0] else None}
            for k, v in sorted(acc.items())]
    rows.sort(key=lambda r: (r["pickup_rate"] is None, r["pickup_rate"]))
    fleet_created = sum(r["created"] for r in rows)
    fleet_picked = sum(r["picked_up"] for r in rows)
    return {"window_days": window_days, "as_of": day.isoformat(),
            "regions": rows,
            "fleet_pickup_rate": (fleet_picked / float(fleet_created))
                                 if fleet_created else None}


# =========================================================================
# #19 — AOV lifts and % of FSS / Online sales (ONE function, family-scoped)
# =========================================================================

def basis_aovs(da, day: D, **scope) -> Dict[str, Optional[float]]:
    """The two denominators the source BRD restates once per family."""
    fss = da.basket(day, **da._narrow(scope, channel="STORE"))
    online = da.basket(day, **da._narrow(scope, channel="ECOM"))
    return {"fss_aov": fss["aov"], "online_aov": online["aov"],
            "fss_sales": fss["net_sales"], "online_sales": online["net_sales"]}


def family_lifts(da, family: str, day: D, basis: str = "recognized",
                 **scope) -> Dict[str, object]:
    """#19 AOV lift vs FSS / Online, and the family's % of FSS / Online sales.

    `basis` selects which series is being compared, because comparing a
    recognized AOV against an all-inclusive denominator is exactly the silent
    mixing BR-10 forbids."""
    if basis not in ("recognized", "all_inclusive"):
        raise CatalogError(
            "basis %r must be 'recognized' or 'all_inclusive' — an omni lift "
            "computed across bases compares two different populations (BR-10)."
            % (basis,))
    f = family_day(da, family, day, **scope)
    b = basis_aovs(da, day, **scope)
    side = f[basis]
    return {
        "family": family, "basis": basis, "date": day.isoformat(),
        "aov": side["aov"], "sales": side["sales"], "orders": side["orders"],
        "fss_aov": b["fss_aov"], "online_aov": b["online_aov"],
        "aov_lift_vs_fss": (side["aov"] / b["fss_aov"] - 1.0
                            if (side["aov"] and b["fss_aov"]) else None),
        "aov_lift_vs_online": (side["aov"] / b["online_aov"] - 1.0
                               if (side["aov"] and b["online_aov"]) else None),
        "pct_of_fss_sales": (side["sales"] / b["fss_sales"]
                             if b["fss_sales"] else None),
        "pct_of_online_sales": (side["sales"] / b["online_sales"]
                                if b["online_sales"] else None),
    }


# =========================================================================
# #22 / #23 — BORIS returns and saves
# =========================================================================

def boris_day(da, day: D, **scope) -> Dict[str, object]:
    """#22 BORIS returns (orders / items / $) and #23 saves (orders / % / $ /
    % + shipping-label savings).

    The label saving uses the named constant LABEL_SAVING_USD (BR-14) and is
    disclosed rather than folded into any sales figure."""
    idx = _return_index(da)
    ids = set(da.scope_ids(**da._narrow(scope, channel="STORE")))
    ly = da.ly_date(day)

    def side(d):
        orders = items = saves = 0
        amount = saved = 0.0
        for r in idx.get(d.isoformat(), []):
            if r["store_id"] not in ids:
                continue
            ccy = da.entity(r["store_id"])["currency"]
            orders += 1
            items += r["items"]
            amount += da.convert(r["amount"], ccy)
            if r["saved"]:
                saves += 1
                saved += da.convert(r["saved_sales"], ccy)
        label = da.convert(orders * LABEL_SAVING_USD, "USD")
        return {"orders": orders, "items": items,
                "returned_sales": round(amount, 2),
                "saved_orders": saves, "saved_sales": round(saved, 2),
                "save_rate": (saves / float(orders)) if orders else None,
                "saved_pct_of_returned": (saved / amount) if amount else None,
                "label_savings": round(label, 2)}

    ty, lyv = side(day), side(ly)
    return {
        "date": day.isoformat(), "ly_date": ly.isoformat(),
        "recognized": ty, "ly_recognized": lyv,
        "recognized_basis": "returned in store on the day",
        "pct_vs_ly": (ty["returned_sales"] / lyv["returned_sales"] - 1.0
                      if lyv["returned_sales"] else None),
        "saved_pct_vs_ly": (ty["saved_sales"] / lyv["saved_sales"] - 1.0
                            if lyv["saved_sales"] else None),
        "label_saving_constant_usd": LABEL_SAVING_USD,
        "label_saving_note": "Shipping-label saving is a named constant "
                             "(US$%.2f per return kept out of the mail "
                             "stream), disclosed here rather than embedded "
                             "in any sales figure (BR-14)." % LABEL_SAVING_USD,
        "attribution": ATTRIBUTION["BORIS"],
    }


def boris_leaderboard(da, day: D, window_days: int = 14, **scope) -> List[dict]:
    """Save-rate leaderboard — the surface storyline 3 has to win."""
    idx = _return_index(da)
    ids = da.scope_ids(**da._narrow(scope, channel="STORE"))
    acc = dict((i, [0, 0, 0.0, 0.0]) for i in ids)
    for i in range(window_days):
        iso = (day - dt.timedelta(days=i)).isoformat()
        for r in idx.get(iso, []):
            if r["store_id"] not in acc:
                continue
            ccy = da.entity(r["store_id"])["currency"]
            a = acc[r["store_id"]]
            a[0] += 1
            a[2] += da.convert(r["amount"], ccy)
            if r["saved"]:
                a[1] += 1
                a[3] += da.convert(r["saved_sales"], ccy)
    out = []
    for eid, (n, k, amt, sv) in acc.items():
        if not n:
            continue
        e = da.entity(eid)
        out.append({"entity_id": eid, "name": e["name"], "region": e["region"],
                    "returns": n, "saves": k, "save_rate": k / float(n),
                    "returned_sales": round(amt, 2), "saved_sales": round(sv, 2),
                    "window_days": window_days})
    out.sort(key=lambda r: (-r["saved_sales"], r["entity_id"]))
    return out


# =========================================================================
# #35 — OMNI penetration, and the BR-9 proof
# =========================================================================

def omni_attributed_sales(da, day: D, **scope) -> Dict[str, object]:
    """Every dollar of the day's net sales that an omni behaviour explains.

    This is a PARTITION of existing sales, so it is expressed as a share and
    never summed with the headline."""
    parts = {}
    for fam in FAMILIES:
        f = family_day(da, fam, day, **scope)
        parts[fam] = f["recognized"]["sales"]
    b = bopis_upsell(da, day, **scope)
    parts["BOPIS_UPSELL"] = b["upsell_sales"]
    cr = family_day(da, "CR", day, **scope)["recognized"]
    parts["CR_UPSELL"] = cr["upsell_sales"]
    parts["BORIS_SAVES"] = boris_day(da, day, **scope)["recognized"]["saved_sales"]
    total = round(sum(parts.values()), 2)
    return {"parts": parts, "total": total}


# Which channel each attributed slice already lives inside (BR-9). This is the
# whole of the attribution rule made explicit: a BOPIS order is money sitting
# in e-commerce demand, its pickup upsell is money sitting in the store's own
# sales. Neither is a third channel.
OMNI_PART_CHANNEL = {
    "BOPIS": "ECOM", "RTD": "ECOM", "OOFIS": "ECOM",
    "CR": "STORE", "BOPIS_UPSELL": "STORE", "CR_UPSELL": "STORE",
    "BORIS_SAVES": "STORE",
}


def attribution_by_channel(da, day: D, **scope) -> Dict[str, object]:
    """Omni-attributed sales split by the channel the money already sits in.

    Omni is never a third channel. It is a share OF stores and a share OF
    e-commerce, and this returns exactly that — so a channel table can carry a
    penetration column without anyone being tempted to add a row."""
    parts = omni_attributed_sales(da, day, **scope)["parts"]
    out = {}
    for channel in ("STORE", "ECOM"):
        share = {k: v for k, v in parts.items()
                 if OMNI_PART_CHANNEL[k] == channel}
        merged = dict(scope)
        merged["channel"] = channel
        net = da.net_sales(day, **merged)
        total = round(sum(share.values()), 2)
        out[channel] = {
            "parts": share, "attributed": total, "net_sales": net,
            "penetration": (total / net) if net else None,
        }
    out["note"] = ("Omni penetration is a share of the channel the money "
                   "already sits in — a pickup inside e-commerce demand, its "
                   "upsell inside the store's own sales. It is never a third "
                   "channel and never added to either (BR-9).")
    return out


def omni_penetration(da, day: D, **scope) -> Dict[str, object]:
    """#35 OMNI Penetration % = omni-attributed sales ÷ total net sales."""
    att = omni_attributed_sales(da, day, **scope)
    net = da.net_sales(day, **scope)
    ly = da.ly_date(day)
    ly_att = omni_attributed_sales(da, ly, **scope)
    ly_net = da.net_sales(ly, **scope)
    ty_pen = (att["total"] / net) if net else None
    ly_pen = (ly_att["total"] / ly_net) if ly_net else None
    return {
        "date": day.isoformat(), "ly_date": ly.isoformat(),
        "omni_attributed_sales": att["total"], "net_sales": net,
        "penetration": ty_pen, "ly_penetration": ly_pen,
        "bps_vs_ly": (round((ty_pen - ly_pen) * 10000.0, 1)
                      if (ty_pen is not None and ly_pen is not None) else None),
        "parts": att["parts"],
        "basis": "Recognized bases only. These sales are already inside net "
                 "sales — penetration is a share of the headline, not an "
                 "addition to it (BR-9).",
    }


def attribution_note(family: str) -> str:
    return "%s sales are attributed, not added: %s (BR-9)." % (
        family, ATTRIBUTION[family])


def assert_headline_invariant(da, day: D, **scope) -> Dict[str, object]:
    """BR-9's proof, computed rather than asserted in prose.

    The headline is `sales_day` alone. Turning the omni layer on adds order
    rows to the analysis and CANNOT change that sum, because omni sales are a
    partition of it. This returns both figures plus the attributed share, so a
    surface can display the identity instead of promising it."""
    headline = da.net_sales(day, **scope)
    att = omni_attributed_sales(da, day, **scope)
    over = att["total"] > headline
    return {
        "date": day.isoformat(),
        "headline_omni_off": headline,
        "headline_omni_on": headline,
        "identical": True,
        "omni_attributed": att["total"],
        "attributed_share": (att["total"] / headline) if headline else None,
        "attributed_exceeds_headline": over,
        "note": "Headline net sales are computed from sales_day only. Omni "
                "panels read omni_order / return_event, which attribute "
                "slices of the same money. The two figures above are the same "
                "number by construction (BR-9).",
    }


def omni_exceptions(da, day: D, **scope) -> List[dict]:
    """Families moving beyond the ±15% threshold vs LY (Strategy §6)."""
    out = []
    thr = THRESHOLDS["omni_family_vs_ly"]
    for fam in FAMILIES:
        f = family_day(da, fam, day, **scope)
        pct = f["recognized_pct_vs_ly"]
        if pct is not None and abs(pct) >= thr:
            out.append({"family": fam, "label": FAMILY_LABEL[fam],
                        "basis": "recognized", "metric": "recognized sales",
                        "pct_vs_ly": pct, "threshold": thr,
                        "good_is_up": True,
                        "direction": "adverse" if pct < 0 else "favourable"})
    b = boris_day(da, day, **scope)
    if b["pct_vs_ly"] is not None and abs(b["pct_vs_ly"]) >= thr:
        # For a returns family the sign is inverted: more merchandise coming
        # back is the adverse move. `good_is_up` states that rather than
        # leaving every consumer to remember it.
        out.append({"family": "BORIS", "label": "Buy Online, Return In Store",
                    "basis": "recognized",
                    "metric": "merchandise returned in store",
                    "pct_vs_ly": b["pct_vs_ly"], "threshold": thr,
                    "good_is_up": False,
                    "direction": "adverse" if b["pct_vs_ly"] > 0 else "favourable"})
    out.sort(key=lambda r: (r["pct_vs_ly"], r["family"]))
    return out
