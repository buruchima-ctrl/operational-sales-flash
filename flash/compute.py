# -*- coding: utf-8 -*-
"""The computed ops object — one per day, two surfaces (BR-5, BR-13).

This module builds a plain, JSON-serializable dict. It computes nothing itself:
every figure comes from the catalog (`catalog`, `omni`, `customer`, `merch` —
the formula homes) and every display string from `fmt`. Renderers read this
object and print it. If a renderer ever needs a number that is not in here, the
fix is to add it here — not to compute it in the renderer, which is how two
surfaces start disagreeing.

Two depths, because the archive is tiered (owner decision, 2026-07-31):

  ``summary``  every day in the 60-day archive. Headline, comps, windows,
               plan at three grains, slices, panels in summary form,
               completeness, focus, exceptions, narrative.
  ``full``     the last 14 days. Everything above plus the drill tree
               (region → district → store → category → SKU), per-store manager
               blocks with hourly series and KPI trees, omni family panels,
               rank tables and the door-level extract rows.

The depth changes how much is computed, never how anything is computed: a
figure that appears at both depths is the same call in the same place.

The one piece of real judgement in this file is the **holiday override**
(BR-1). The catalog computes comps against whatever LY date it is handed; the
calendar knows two candidate LY dates for a holiday. Deciding which leads is a
business rule, so it lives here, once, and the object carries both with the
adjusted one in the lead slot — never one without the other.

Determinism (NFR-2): `as_of` comes from the caller (the send morning, derived
from the flash date), never `now()`. Every dict is built in a stable order and
the archive serializes with sort_keys.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from flash import customer as customer_mod
from flash import fmt, merch, narrative, omni
from flash.calendar import ly_holiday_aligned_date
from flash.catalog import THRESHOLDS, reconcile_display
from flash.focus import build_exceptions, build_focus, build_headlines, _slug

D = dt.date

SCHEMA_VERSION = 2
COMPANY = "Lumière Beauty Group"
PRODUCT = "Operational Sales Flash"
CHANNELS = ("STORE", "ECOM")
WINDOW_KEYS = ("LW", "WTD", "MTD", "QTD", "YTD")
WINDOW_LABELS = {"LW": "Last week", "WTD": "Week to date",
                 "MTD": "Period to date", "QTD": "Quarter to date",
                 "YTD": "Year to date"}
OMNI_PANELS = ("BOPIS", "RTD", "OOFIS", "CR", "BORIS")
RANK_KPIS = ("net_sales", "comp_pct", "conversion", "plan_attainment",
             "traffic", "transactions", "ast", "upt")
MAX_NARRATIVE_SENTENCES = 4


def send_morning(day: D) -> D:
    """The flash for `day` is sent the following morning. Derived from the
    data's own date — the reason nothing here calls now() (NFR-2)."""
    return day + dt.timedelta(days=1)


def build_flash(da, day: D, as_of: Optional[D] = None, version: int = 1,
                reason: Optional[str] = None,
                depth: str = "summary") -> Dict[str, object]:
    """Build the computed ops object for one day."""
    if depth not in ("summary", "full"):
        raise ValueError(
            "depth %r is not 'summary' or 'full'. The archive is tiered: every "
            "day gets a summary object, the last 14 get the full drill-down. "
            "A third depth would mean a third set of numbers." % (depth,))
    as_of = as_of or send_morning(day)
    cal = da.cal
    fy, period_no, week, dow = cal.coordinates(day)
    per = cal.period_for_date(day)
    week_aligned_ly, restated = cal.ly_aligned_date(day)
    holiday = da.cal_row(day)["holiday_code"]

    obj: Dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "company": COMPANY,
        "product": PRODUCT,
        "date": day.isoformat(),
        "as_of": as_of.isoformat(),
        "version": version,
        "reason": reason,
        "basis": da.ecom_basis,
        "depth": depth,
        "reporting_currency": da.reporting_currency,
        "calendar": {
            "fiscal_year": fy,
            "period": period_no,
            "period_label": per.label,
            "quarter": per.quarter,
            "week": week,
            "day_of_week": dow,
            "weekday": fmt.WEEKDAYS[day.weekday()],
            "holiday_code": holiday,
            "restated_53_week": bool(restated),
            "week_start": da.cal_row(day)["week_start"],
            "week_end": da.cal_row(day)["week_end"],
            "period_start": per.start.isoformat(),
            "period_end": per.end.isoformat(),
            "year_start": cal.fy_start_date(fy).isoformat(),
        },
    }

    obj["comp"] = _comp_block(da, day, week_aligned_ly, holiday, restated)
    ly_override = (D.fromisoformat(obj["comp"]["ly_date"])
                   if obj["comp"]["override_in_effect"] else None)

    obj["headline"] = _headline(da, day, obj["comp"])
    obj["plan_status"] = da.plan_status(day)
    obj["windows"] = {w: _window(da, day, w) for w in WINDOW_KEYS}
    obj["status"] = da.store_status(day)
    obj["tiers"] = {t: da.tier_metrics(day, t) for t in da.TIERS}
    obj["slices"] = _slices(da, day, ly_override)
    obj["omni"] = _omni_block(da, day)
    obj["customer"] = _customer_block(da, day)
    obj["merch"] = _merch_block(da, day, full=(depth == "full"))
    obj["ecom"] = _ecom(da, day, as_of)
    obj["completeness"] = _completeness(da, day)
    obj["focus"] = build_focus(da, day, ly_override=ly_override)
    obj["exceptions"] = build_exceptions(da, day, omni, customer_mod, merch)
    obj["headlines"] = build_headlines(da, day, omni, customer_mod, merch)
    obj["conversion_move"] = da.conversion_move(day)
    obj["recap"] = _recap(da, day, dow)
    obj["currency_note"] = da.currency_note()
    obj["fx"] = _fx_block(da)

    if depth == "full":
        obj["personas"] = _personas(da, day, ly_override)
        obj["drill"] = _drill(da, day, ly_override)
        obj["stores"] = _store_blocks(da, day)
        obj["ranks"] = {k: da.rank_stores(day, kpi=k, n=10) for k in RANK_KPIS}
        obj["upt_movers"] = da.upt_movers(day, n=10)
        obj["extract"] = _extract_rows(da, day, obj)

    obj["disclosures"] = _disclosures(da, day, obj)
    obj["method"] = _method()
    obj["narrative"] = _narrative(obj)
    obj["display"] = _display(obj)
    obj["subject"] = _subject(obj)
    _assert_invariants(da, obj, day)
    return obj


# =========================================================================
# Comp, and the holiday override (BR-1)
# =========================================================================

def _fx_block(da) -> Dict[str, object]:
    """The rate table, carried on every object so no surface has to look it up.

    BR-16 says the rate is disclosed *wherever a converted figure appears* —
    which means a store page and a tree page need the numeric rate as much as
    the corporate landing does, and a renderer that has to go and find it will
    eventually not bother."""
    rates = da.fx()
    return {
        "reporting_currency": da.reporting_currency,
        "rates": {c: r for c, r in sorted(rates.items())},
        "disclosures": {c: da.fx_disclosure(c) for c in sorted(rates)},
    }


def _comp_block(da, day: D, week_aligned_ly: D, holiday: Optional[str],
                restated: bool) -> Dict[str, object]:
    """#2 with the BR-1 lead/raw discipline made explicit.

    Three comparisons exist for any day. Only the first is allowed to lead:

      holiday-aligned   same holiday code last year        (holidays only)
      week-aligned      same fiscal week + same weekday     (the default)
      calendar-date     the same calendar date last year    (never leads)

    The calendar-date figure is carried because BR-1 says the raw comparison
    never appears without the aligned figure leading — the honest way to honour
    that is to show what the spreadsheet flash would have printed, next to the
    number that is actually right.
    """
    week_pair = da.comp_pair(day)
    week_pct = da.comp_pct(day)

    holiday_ly = ly_holiday_aligned_date(day) if holiday else None
    override = bool(holiday_ly and holiday_ly != week_aligned_ly)

    block: Dict[str, object] = {
        "holiday_code": holiday,
        "override_in_effect": override,
        "restated_53_week": bool(restated),
        "week_aligned": _side(week_pair, week_pct, "week-aligned", week_aligned_ly),
    }

    if override:
        pair = da.comp_pair(day, ly_override=holiday_ly)
        pct = da.comp_pct(day, ly_override=holiday_ly)
        block["holiday_aligned"] = _side(pair, pct, "holiday-aligned", holiday_ly)
        lead = block["holiday_aligned"]
    else:
        block["holiday_aligned"] = None
        lead = block["week_aligned"]

    cal_date_ly = _same_calendar_date_ly(day)
    cal_pair = cal_pct = None
    try:
        cal_pair = da.comp_pair(day, ly_override=cal_date_ly)
        cal_pct = da.comp_pct(day, ly_override=cal_date_ly)
    except Exception:                      # outside the materialized calendar
        pass
    block["calendar_date"] = (_side(cal_pair, cal_pct, "calendar-date", cal_date_ly)
                              if cal_pair else None)

    block.update({
        "basis": lead["basis"], "ly_date": lead["ly_date"], "pct": lead["pct"],
        "ty": lead["ty"], "ly": lead["ly"], "gap": lead["gap"],
        "members": lead["members"],
    })
    return block


def _side(pair, pct, basis, ly_date) -> Dict[str, object]:
    return {
        "basis": basis,
        "ly_date": ly_date.isoformat() if hasattr(ly_date, "isoformat") else ly_date,
        "pct": pct, "ty": pair["ty"], "ly": pair["ly"], "gap": pair["gap"],
        "members": len(pair["members"]),
    }


def _same_calendar_date_ly(day: D) -> D:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:                     # Feb 29
        return day.replace(year=day.year - 1, day=28)

# =========================================================================
# Headline — the deck's KPI row, once, for every persona page (BR-18)
# =========================================================================

def _headline(da, day: D, comp: Dict[str, object], **scope) -> Dict[str, object]:
    """The KPI headline row the reference deck puts on every level's landing:
    Net Sales · Transactions · AST · AUS · UPT · Traffic · Conversion · New
    Customers · Returns · Discounts, plus OMNI penetration and door counts.

    Computed once and carried, so Corporate, Brand, Region, Affiliate and Field
    read the same numbers for the same scope — the whole of BR-18."""
    ly_override = (D.fromisoformat(comp["ly_date"])
                   if comp and comp.get("override_in_effect") else None)
    basket = da.basket(day, **scope)
    cbasket = da.comp_basket(day, ly_override=ly_override, **scope)
    plan = da.plan_pair(day, **scope)
    txn = da.comp_transactions(day, ly_override=ly_override, **scope)
    conv = da.conversion(day, **scope)
    cmove = da.conversion_move(day, **scope)
    trf = da.traffic(day, **scope)
    disc = da.discounts(day, **scope)
    rets = da.store_returns(day, **scope)
    nb = customer_mod.new_customer_block(da, day, **scope)
    pen = omni.omni_penetration(da, day, **scope)
    status = da.store_status(day, **scope)
    return {
        "net_sales": basket["net_sales"],
        "comp_pct": (comp["pct"] if comp else da.comp_pct(day, **scope)),
        "comp_basis": (comp["basis"] if comp else "week-aligned"),
        "plan": plan["plan"],
        "plan_attainment": (plan["actual"] / plan["plan"]) if plan["plan"] else None,
        "plan_gap": round(plan["actual"] - plan["plan"], 2),
        "transactions": basket["transactions"],
        "units": basket["units"],
        "ast": basket["ast"], "aus": basket["aus"], "upt": basket["upt"],
        "aov": basket["aov"], "aur": basket["aur"],
        # The basket is a lever, so it carries a movement. Showing UPT with no
        # comparison makes a thing you can change look like a thing you have.
        "ast_pct_vs_ly": cbasket["ast_pct"],
        "aus_pct_vs_ly": cbasket["aus_pct"],
        "upt_pct_vs_ly": cbasket["upt_pct"],
        "ly_ast": cbasket["ly_ast"], "ly_aus": cbasket["ly_aus"],
        "ly_upt": cbasket["ly_upt"],
        "units_pct_vs_ly": cbasket["units_pct"],
        "comp_basket_members": cbasket["members"],
        "comp_transactions": txn,
        "traffic": trf["traffic"],
        "traffic_pct_vs_ly": trf["pct_vs_ly"],
        "traffic_missing": trf["stores_missing_traffic"],
        "conversion": conv["conversion"],
        "conversion_available": conv["available"],
        "conversion_bps_vs_ly": conv["bps_vs_ly"],
        "conversion_note": conv["unavailable_note"],
        "conversion_move": cmove["annotation_bare"],
        "conversion_move_full": cmove["annotation"],
        "conversion_traffic_pct": cmove["traffic_pct"],
        "conversion_txns_pct": cmove["txns_pct"],
        "new_customers": nb["new_customers"],
        "new_customer_sales": nb["net_sales"],
        "new_customer_pct": nb["pct_of_net_sales"],
        "new_customer_ast": nb["ast"],
        "returns": rets["returns"],
        "returns_pct_of_gross": rets["pct_of_gross"],
        "returns_pct_vs_ly": rets["pct_vs_ly"],
        "discounts": disc["discounts"],
        "discounts_pct_of_gross": disc["pct_of_gross"],
        "discounts_pct_vs_ly": disc["pct_vs_ly"],
        "gross_sales": disc["gross"],
        "omni_penetration": pen["penetration"],
        "omni_penetration_bps_vs_ly": pen["bps_vs_ly"],
        "portfolio": status["portfolio"],
        "trading": status["trading"],
        "comp_trading": status["comp_trading"],
        "pct_trading": status["pct_trading"],
        "pct_comp_of_trading": status["pct_comp_of_trading"],
        "demand_pct_of_gross": da.demand_pct_of_gross(day, **scope),
    }


def _window(da, day: D, window: str, **scope) -> Dict[str, object]:
    m = da.window_metrics(day, window, **scope)
    m["label"] = WINDOW_LABELS[window]
    c = da.conversion_window(day, window, **scope)
    m["conversion"] = c["conversion"]
    m["ly_conversion"] = c["ly_conversion"]
    m["conversion_bps_vs_ly"] = c["bps_vs_ly"]
    m["conversion_move"] = da.conversion_window_move(
        day, window, **scope)["annotation_bare"]
    m["traffic"] = c["traffic"]
    bw = da.basket_window(day, window, **scope)
    m["upt"] = bw["upt"]
    m["ly_upt"] = bw["ly_upt"]
    m["upt_pct_vs_ly"] = bw["upt_pct_vs_ly"]
    m["ast"] = bw["ast"]
    m["aus"] = bw["aus"]
    b = customer_mod.buyers_window(da, day, window, **scope)
    m["new_buyers"] = b["new_buyers"]
    m["total_buyers"] = b["total_buyers"]
    m["pct_new_to_file"] = b["pct_new_to_file"]
    return m


def _slices(da, day: D, ly_override) -> Dict[str, List[dict]]:
    """The same day cut five ways. Each slice carries its own comp-set size, so
    a reader can see why a scope's comp base is smaller than its door count
    (remodel and new-store exclusions, BR-2)."""
    out = {}
    out["channel"] = [_slice(da, day, ly_override, {"channel": k},
                             _slice_label(k), k) for k in CHANNELS]
    regions = sorted(set(e["region"] for e in da.entities()))
    out["region"] = [_slice(da, day, ly_override, {"region": r},
                            _slice_label(r), r) for r in regions]
    out["brand"] = [_slice(da, day, ly_override, {"brand_id": b["brand_id"]},
                           b["name"], b["brand_id"]) for b in da.brands()]
    out["brand"].append(_slice(da, day, ly_override, {"channel": "ECOM"},
                               "E-commerce (multi-brand)", "ECOM"))
    out["affiliate"] = [_slice(da, day, ly_override, {"affiliate_id": a},
                               {"US": "United States", "CA": "Canada"}[a], a)
                        for a in ("US", "CA")]
    out["district"] = [_slice(da, day, ly_override,
                              {"district_id": d["district_id"]},
                              d["name"], d["district_id"], region=d["region"])
                       for d in da.districts()]
    # Make the DISPLAYED parts sum to the displayed whole. Each slice is
    # rounded to cents independently, so five of them can miss their own total
    # by a penny; the residual lands on the largest slice. The underlying
    # figures are unchanged — this is BR-11 as the reader can check it, not
    # only as the database knows it.
    total = da.net_sales(day)
    store_total = da.net_sales(day, channel="STORE")
    for dim in ("channel", "region", "affiliate", "brand"):
        reconcile_display(out[dim], "net_sales", total)
    reconcile_display(out["district"], "net_sales", store_total)
    return out


def _slice(da, day: D, ly_override, kw: dict, label: str, key: str,
           region: Optional[str] = None) -> Dict[str, object]:
    pair = da.comp_pair(day, ly_override=ly_override, **kw)
    plan = da.plan_pair(day, **kw)
    scope_entities = da._scope_entities(**kw)
    open_ids = [e["entity_id"] for e in scope_entities if da.is_open_on(e, day)]
    reported = [e for e in open_ids if da.sales_row(e, day) is not None]
    conv = da.conversion(day, **kw)
    move = da.conversion_move(day, **kw)
    cb = da.comp_basket(day, ly_override=ly_override, **kw)
    return {
        "key": key, "label": label, "region": region,
        "currencies": da.currencies_in_scope(**kw),
        "currency_note": da.currency_note(**kw),
        "net_sales": da.net_sales(day, **kw),
        "comp_pct": da.comp_pct(day, ly_override=ly_override, **kw),
        "comp_ty": pair["ty"], "comp_ly": pair["ly"], "comp_gap": pair["gap"],
        "comp_members": len(pair["members"]),
        "open_entities": len(open_ids), "reported_entities": len(reported),
        "plan": plan["plan"],
        "plan_attainment": (plan["actual"] / plan["plan"]) if plan["plan"] else None,
        "plan_grain_mix": da.plan_status(day, **kw)["grain_mix"],
        "conversion": conv["conversion"],
        "conversion_bps_vs_ly": conv["bps_vs_ly"],
        "conversion_move": move["annotation_bare"],
        "conversion_move_full": move["annotation"],
        "traffic": conv["traffic"] or None,
        "upt": cb["upt"], "ly_upt": cb["ly_upt"],
        "upt_pct_vs_ly": cb["upt_pct"], "ast_pct_vs_ly": cb["ast_pct"],
        "entity_ids": sorted(e["entity_id"] for e in scope_entities),
    }


def _slice_label(key: str) -> str:
    return {"STORE": "Stores", "ECOM": "E-commerce"}.get(key, key)

# =========================================================================
# Panels — omni, customer, merchandise
# =========================================================================

def _omni_block(da, day: D, **scope) -> Dict[str, object]:
    """Every omni family on both bases, plus the BR-9 invariance proof.

    `invariance` is not a claim, it is a computation: the headline with the
    omni layer on and the headline with it off, side by side, on every day."""
    families = {}
    for fam in omni.FAMILIES:
        f = omni.family_day(da, fam, day, **scope)
        f["lifts"] = omni.family_lifts(da, fam, day, "recognized", **scope)
        families[fam] = f
    families["BORIS"] = omni.boris_day(da, day, **scope)
    return {
        "families": families,
        "family_order": list(OMNI_PANELS),
        "upsell": omni.bopis_upsell(da, day, **scope),
        "penetration": omni.omni_penetration(da, day, **scope),
        "invariance": omni.assert_headline_invariant(da, day, **scope),
        "exceptions": omni.omni_exceptions(da, day, **scope),
        "pickup_execution": omni.pickup_execution(da, day, 14, **scope),
        "upsell_leaderboard": omni.upsell_leaderboard(da, day, 14, **scope)[:10],
        "boris_leaderboard": omni.boris_leaderboard(da, day, 14, **scope)[:10],
        "attribution_notes": {f: omni.attribution_note(f)
                              for f in sorted(omni.ATTRIBUTION)},
    }


def _customer_block(da, day: D, **scope) -> Dict[str, object]:
    windows = {}
    for w in WINDOW_KEYS:
        windows[w] = customer_mod.buyers_window(da, day, w, **scope)
    channels = []
    for ch in CHANNELS:
        merged = dict(scope)
        merged["channel"] = ch
        channels.append({
            "key": ch, "label": _slice_label(ch),
            "buyers": customer_mod.buyers(da, day, **merged),
            "new_block": customer_mod.new_customer_block(da, day, **merged),
            "ntf_exception": customer_mod.ntf_exception(da, day, "WTD", **merged),
        })
    return {
        "day": customer_mod.buyers_vs_ly(da, day, **scope),
        "new_block": customer_mod.new_customer_block(da, day, **scope),
        "windows": windows,
        "channels": channels,
        "ntf_exception": customer_mod.ntf_exception(da, day, "WTD", **scope),
        "file_size": customer_mod.file_size(da, day),
        "omni_capture": {f: customer_mod.omni_new_buyers(da, day, f, **scope)
                         for f in omni.FAMILIES},
    }


def _merch_block(da, day: D, full: bool = False, **scope) -> Dict[str, object]:
    cats = merch.category_day(da, day, **scope)
    movers = merch.sku_movers(da, day, n=10, **scope)
    out = {
        "categories": cats,
        "basket": merch.category_basket(da, day, **scope),
        "movers": movers,
        "exceptions": merch.category_exceptions(da, day, **scope),
        "reconciliation": merch.reconcile_lines(da, day, **scope),
        "available": bool(cats.get("available")),
    }
    if cats.get("available"):
        out["slide_runs"] = {
            c["category"]: merch.category_slide_run(da, day, c["category"], **scope)
            for c in cats["categories"] if (c["comp_pct"] or 0) < 0}
    else:
        out["slide_runs"] = {}
    out["category_skus"] = {}
    if full and cats.get("available"):
        # Every SKU in every category, ranked by contribution — the leaf of the
        # drill path. Only at full depth: 120 SKUs a day across 60 days would
        # triple the archive for pages that are not generated.
        for c in cats["categories"]:
            mv = merch.sku_movers(da, day, n=10 ** 6, category=c["category"],
                                  **scope)
            out["category_skus"][c["category"]] = mv["top"]
    return out


def _ecom(da, day: D, as_of: D) -> Dict[str, object]:
    e = da.ecom_day(day, as_of) or {}
    e["basis_in_headline"] = ("shipped (settled)" if da.ecom_basis == "settled"
                              else "demand (ordered)")
    e["settled_return_rate"] = da.ecom_settled_return_rate(as_of)
    lag = e.get("settle_lag_days", 3)
    e["return_rate_window_end"] = (as_of - dt.timedelta(days=lag)).isoformat()
    e["return_rate_window_days"] = 28
    return e


def _completeness(da, day: D) -> Dict[str, object]:
    c = da.completeness(day)
    c["late_posters"] = da.late_posters(day)
    c["escalating"] = [lp for lp in c["late_posters"] if lp["escalate"]]
    t = da.traffic(day)
    c["traffic_missing"] = t["stores_missing_traffic"]
    c["traffic_missing_names"] = t["missing_names"]
    return c


def _recap(da, day: D, dow: int) -> Optional[Dict[str, object]]:
    """The recap rides the flash sent on a Monday morning.

    NRF weeks run Sunday..Saturday, so the week closes on Saturday and the
    first flash of the new week reports Sunday and is sent Monday. That flash —
    dow == 1 — carries the closed week and the gap-to-go for the new one."""
    if dow != 1:
        return None
    closed_end = day - dt.timedelta(days=1)
    closed = da.window_metrics(closed_end, "WTD")
    cats = merch.category_window(da, closed_end, "WTD")
    return {
        "edition": "Monday trade recap",
        "closed_week_start": closed["start"],
        "closed_week_end": closed["end"],
        "closed_week": closed,
        "gap_to_go": da.gap_to_go(day),
        "categories": cats if cats.get("available") else None,
    }

# =========================================================================
# Drill tree — total → region → district → store → category → SKU (BR-11)
# =========================================================================

def _drill(da, day: D, ly_override) -> Dict[str, object]:
    """Each level carries its children's sum and its own total, so every page
    can print the reconciliation line rather than assert it."""
    total = da.net_sales(day)
    regions = []
    for r in sorted(set(e["region"] for e in da.entities())):
        districts = [d for d in da.districts() if d["region"] == r]
        child_ids = []
        rows = []
        for d in districts:
            s = _slice(da, day, ly_override, {"district_id": d["district_id"]},
                       d["name"], d["district_id"], region=r)
            s["stores"] = [_slice(da, day, ly_override, {"entity_id": eid},
                                  da.entity(eid)["name"], eid, region=r)
                           for eid in s["entity_ids"]]
            s["children_sum"] = round(sum(x["net_sales"] for x in s["stores"]), 2)
            rows.append(s)
            child_ids += s["entity_ids"]
        loose = [e["entity_id"] for e in da._scope_entities(region=r)
                 if e["entity_id"] not in child_ids]
        loose_rows = [_slice(da, day, ly_override, {"entity_id": eid},
                             da.entity(eid)["name"], eid, region=r)
                      for eid in sorted(loose)]
        reg = _slice(da, day, ly_override, {"region": r}, _slice_label(r), r)
        reg["districts"] = rows
        reg["unassigned"] = loose_rows
        reg["children_sum"] = round(
            sum(x["net_sales"] for x in rows)
            + sum(x["net_sales"] for x in loose_rows), 2)
        regions.append(reg)
    return {
        "total": total,
        "regions": regions,
        "children_sum": round(sum(r["net_sales"] for r in regions), 2),
        "reconciliation_note": "Every level's children sum to it, to the cent "
                               "(BR-11). The figures below are the same catalog "
                               "calls the headline uses, scoped down.",
    }


# =========================================================================
# Personas — the owner's scoping matrix, as data (BR-18)
# =========================================================================
#
# Every persona view renders from THIS object. The scope differs; the numbers
# cannot. A figure that appears on the Corporate page and the Region page is
# the same catalog call with a different filter, computed here once.

PERSONA_MATRIX = {
    "corporate": ("brand", "region", "affiliate", "doors"),
    "brand": ("region", "affiliate", "district", "doors"),
    "region": ("brand", "affiliate", "district", "doors"),
    "affiliate": ("brand", "district", "doors"),
    "field": ("district", "doors"),
}
PERSONA_LABELS = {
    "corporate": "Corporate", "brand": "Brand", "region": "Region",
    "affiliate": "Affiliate", "field": "Field Leadership",
}


def _persona_specs(da) -> List[dict]:
    """The 13 landing pages, in a fixed order."""
    out = [{"kind": "corporate", "key": "corporate",
            "label": "Corporate", "scope": {}}]
    for b in da.brands():
        out.append({"kind": "brand", "key": b["brand_id"], "label": b["name"],
                    "scope": {"brand_id": b["brand_id"]}})
    for r in sorted(set(d["region"] for d in da.districts())):
        out.append({"kind": "region", "key": r, "label": r,
                    "scope": {"region": r}})
    for a, name in (("US", "United States"), ("CA", "Canada")):
        out.append({"kind": "affiliate", "key": a, "label": name,
                    "scope": {"affiliate_id": a}})
    out.append({"kind": "field", "key": "field", "label": "Field Leadership",
                "scope": {}})
    return out


def _personas(da, day: D, ly_override) -> Dict[str, object]:
    out = {}
    for spec in _persona_specs(da):
        scope = spec["scope"]
        h = _headline(da, day, None, **scope)
        rollups = {}
        for dim in PERSONA_MATRIX[spec["kind"]]:
            rollups[dim] = _persona_rollup(da, day, ly_override, dim, scope)
        doors = da.rank_stores(day, kpi="net_sales", n=10, **scope)
        out["%s/%s" % (spec["kind"], spec["key"])] = {
            "kind": spec["kind"], "key": spec["key"], "label": spec["label"],
            "persona_label": PERSONA_LABELS[spec["kind"]],
            "scope": scope,
            "scope_note": _scope_note(spec["kind"]),
            "headline": h,
            "display": _display_kpis(h),
            "rollups": rollups,
            "top_doors": doors["top"], "bottom_doors": doors["bottom"],
            "unavailable_doors": doors["unavailable"],
            "currency_note": da.currency_note(**scope),
            "plan_status": da.plan_status(day, **scope),
            "exceptions": build_exceptions(da, day, omni, customer_mod,
                                           merch, **scope),
            "headlines": build_headlines(da, day, omni, customer_mod, merch,
                                         **scope),
            "conversion_move": da.conversion_move(day, **scope),
        }
    return out


def _scope_note(kind: str) -> str:
    return {
        "corporate": "Brand · Region · Affiliate · top doors",
        "brand": "Region · Affiliate · Field Leadership · Doors",
        "region": "Brand · Affiliate · Field Leadership · Districts · Doors",
        "affiliate": "Brands · Field Leadership · Districts · Doors",
        "field": "Districts · Doors",
    }[kind]


def _persona_rollup(da, day: D, ly_override, dim: str, scope: dict) -> List[dict]:
    """One dimension of a persona's landing view, scoped to that persona."""
    rows = []
    if dim == "brand":
        for b in da.brands():
            merged = dict(scope)
            merged["brand_id"] = b["brand_id"]
            if not da.scope_ids(**merged):
                continue
            rows.append(_slice(da, day, ly_override, merged, b["name"],
                               b["brand_id"]))
        merged = dict(scope)
        merged["channel"] = "ECOM"
        if da.scope_ids(**merged):
            rows.append(_slice(da, day, ly_override, merged,
                               "E-commerce (multi-brand)", "ECOM"))
    elif dim == "region":
        for r in sorted(set(e["region"] for e in da._scope_entities(**scope))):
            merged = dict(scope)
            merged["region"] = r
            rows.append(_slice(da, day, ly_override, merged, _slice_label(r), r))
    elif dim == "affiliate":
        for a, name in (("US", "United States"), ("CA", "Canada")):
            merged = dict(scope)
            merged["affiliate_id"] = a
            if not da.scope_ids(**merged):
                continue
            rows.append(_slice(da, day, ly_override, merged, name, a))
    elif dim == "district":
        for d_ in da.districts():
            merged = dict(scope)
            merged["district_id"] = d_["district_id"]
            if not da.scope_ids(**merged):
                continue
            rows.append(_slice(da, day, ly_override, merged, d_["name"],
                               d_["district_id"], region=d_["region"]))
    elif dim == "doors":
        for e in da._scope_entities(**scope):
            if e["channel"] != "STORE":
                continue
            rows.append(_slice(da, day, ly_override, {"entity_id": e["entity_id"]},
                               e["name"], e["entity_id"], region=e["region"]))
        rows.sort(key=lambda r: (-r["net_sales"], r["key"]))
    return rows


def _display_kpis(h) -> Dict[str, str]:
    """The KPI headline row as display strings, for any scope."""
    return {
        "net_sales": fmt.money_compact(h["net_sales"]),
        "net_sales_exact": fmt.money_exact(h["net_sales"]),
        "comp_pct": fmt.pct(h["comp_pct"]),
        "plan_attainment": fmt.pct_plain(h["plan_attainment"]),
        "plan_gap": fmt.money_signed(h["plan_gap"]),
        "transactions": fmt.count(h["transactions"]),
        "txn_comp": fmt.pct(h["comp_transactions"]["pct"]),
        "units": fmt.count(h["units"]),
        "ast": fmt.money_plain(h["ast"]), "aus": fmt.money_plain(h["aus"]),
        "upt": fmt.ratio(h["upt"]),
        "ast_vs_ly": fmt.pct(h["ast_pct_vs_ly"]),
        "aus_vs_ly": fmt.pct(h["aus_pct_vs_ly"]),
        "upt_vs_ly": fmt.pct(h["upt_pct_vs_ly"]),
        "ly_upt": fmt.ratio(h["ly_upt"]),
        "traffic": fmt.count(h["traffic"]),
        "traffic_pct": fmt.pct(h["traffic_pct_vs_ly"]),
        "conversion": (fmt.pct_plain(h["conversion"], 2)
                       if h["conversion_available"] else "unavailable"),
        "conversion_bps": _bps(h["conversion_bps_vs_ly"]),
        "conversion_move": h["conversion_move"],
        "conversion_move_full": h["conversion_move_full"],
        "new_customers": fmt.count(h["new_customers"]),
        "new_customer_pct": fmt.pct_plain(h["new_customer_pct"]),
        "new_customer_ast": fmt.money_plain(h["new_customer_ast"]),
        "returns": fmt.money_compact(h["returns"]),
        "returns_pct_of_gross": fmt.pct_plain(h["returns_pct_of_gross"]),
        "returns_vs_ly": fmt.pct(h["returns_pct_vs_ly"]),
        "discounts": fmt.money_compact(h["discounts"]),
        "discounts_pct_of_gross": fmt.pct_plain(h["discounts_pct_of_gross"]),
        "discounts_vs_ly": fmt.pct(h["discounts_pct_vs_ly"]),
        "omni_penetration": fmt.pct_plain(h["omni_penetration"], 2),
        "omni_penetration_bps": _bps(h["omni_penetration_bps_vs_ly"]),
        "portfolio": fmt.count(h["portfolio"]),
        "trading": fmt.count(h["trading"]),
        "comp_trading": fmt.count(h["comp_trading"]),
        "pct_trading": fmt.pct_plain(h["pct_trading"]),
        "pct_comp_of_trading": fmt.pct_plain(h["pct_comp_of_trading"]),
    }


def _store_blocks(da, day: D) -> Dict[str, object]:
    """One block per trading door — the unified Store Manager page's data."""
    out = {}
    for e in da.entities():
        if e["channel"] != "STORE":
            continue
        eid = e["entity_id"]
        posted = da.sales_row(eid, day) is not None
        scope = {"entity_id": eid}
        block = {
            "entity_id": eid,
            "name": e["name"],
            "store_number": e["store_number"],
            "region": e["region"],
            "district_id": e["district_id"],
            "brand_id": e["brand_id"],
            "brand_name": (da.brand(e["brand_id"])["name"] if e["brand_id"] else None),
            "affiliate_id": e["affiliate_id"],
            "currency": e["currency"],
            "city": e["city"],
            "state_province": e["state_province"],
            "store_status": e["store_status"],
            "open_date": e["open_date"],
            "currency_note": da.currency_note(entity_id=eid),
            "fx_units_per_usd": da.fx().get(e["currency"]),
            "fx_disclosure": da.fx_disclosure(e["currency"]),
            "converted": e["currency"] != da.reporting_currency,
            "posted": posted,
            "comp_eligible": da.comp_eligible(eid, day),
            "plan_grain": da.plan_grain_of(eid),
        }
        if not posted:
            block["missing_note"] = (
                "%s had not posted at generation time. It is MISSING from every "
                "total on this flash — never zero-filled (BR-3)." % e["name"])
            out[eid] = block
            continue
        block["headline"] = _headline(da, day, None, **scope)
        block["net_sales_local"] = da.net_sales_local(day, **scope)
        block["windows"] = {w: _window(da, day, w, **scope)
                            for w in ("WTD", "MTD", "QTD")}
        block["plan_status"] = da.plan_status(day, **scope)
        block["conversion_move"] = da.conversion_move(day, **scope)
        block["hourly"] = da.hourly_series(eid, day)
        block["hourly_profile"] = da.hourly_profile(eid, day, weeks=4)
        block["tree"] = da.kpi_tree(eid, day)
        block["categories"] = merch.category_day(da, day, **scope)
        block["movers"] = merch.sku_movers(da, day, n=5, **scope)
        block["omni"] = {
            "families": {f: omni.family_day(da, f, day, **scope)
                         for f in omni.FAMILIES},
            "boris": omni.boris_day(da, day, **scope),
            "penetration": omni.omni_penetration(da, day, **scope),
            "upsell": omni.bopis_upsell(da, day, **scope),
        }
        block["customer"] = {
            "day": customer_mod.buyers_vs_ly(da, day, **scope),
            "new_block": customer_mod.new_customer_block(da, day, **scope),
            "wtd": customer_mod.buyers_window(da, day, "WTD", **scope),
        }
        block["contribution"] = _store_contribution(da, day, eid)
        out[eid] = block
    return out


def _store_contribution(da, day: D, eid: str) -> Optional[Dict[str, object]]:
    for c in da.contribution_to_comp_gap(day):
        if c["entity_id"] == eid:
            return {"ty": c["ty"], "ly": c["ly"], "delta": c["delta"],
                    "contribution": c["contribution"]}
    return None


EXTRACT_COLUMNS = (
    "date", "entity_id", "store_number", "store_name", "brand_id", "brand_name",
    "district_id", "region", "affiliate_id", "currency", "store_status",
    "comp_eligible", "plan_grain", "net_sales_local", "net_sales_usd",
    "gross_sales_usd", "discounts_usd", "returns_usd", "comp_pct",
    "plan_usd", "plan_attainment", "transactions", "units", "ast_usd",
    "aus_usd", "upt", "upt_vs_ly", "ast_vs_ly", "aus_vs_ly",
    "traffic", "conversion", "new_customers",
    "new_customer_sales_usd", "omni_penetration",
)


def _extract_rows(da, day: D, obj) -> Dict[str, object]:
    """BR-21: the door-level extract, built from the SAME per-store blocks the
    site prints. There is no second query path, so a CSV cell cannot disagree
    with the page it came from."""
    rows = []
    for eid in sorted(obj["stores"]):
        b = obj["stores"][eid]
        if not b["posted"]:
            continue
        h = b["headline"]
        rows.append({
            "date": obj["date"], "entity_id": eid,
            "store_number": b["store_number"], "store_name": b["name"],
            "brand_id": b["brand_id"], "brand_name": b["brand_name"],
            "district_id": b["district_id"], "region": b["region"],
            "affiliate_id": b["affiliate_id"], "currency": b["currency"],
            "store_status": b["store_status"],
            "comp_eligible": "Y" if b["comp_eligible"] else "N",
            "plan_grain": b["plan_grain"],
            "net_sales_local": b["net_sales_local"],
            "net_sales_usd": h["net_sales"],
            "gross_sales_usd": h["gross_sales"],
            "discounts_usd": h["discounts"], "returns_usd": h["returns"],
            "comp_pct": h["comp_pct"], "plan_usd": h["plan"],
            "plan_attainment": h["plan_attainment"],
            "transactions": h["transactions"], "units": h["units"],
            "ast_usd": h["ast"], "aus_usd": h["aus"], "upt": h["upt"],
            "upt_vs_ly": h["upt_pct_vs_ly"], "ast_vs_ly": h["ast_pct_vs_ly"],
            "aus_vs_ly": h["aus_pct_vs_ly"],
            "traffic": h["traffic"], "conversion": h["conversion"],
            "new_customers": h["new_customers"],
            "new_customer_sales_usd": h["new_customer_sales"],
            "omni_penetration": h["omni_penetration"],
        })
    return {"columns": list(EXTRACT_COLUMNS), "rows": rows,
            "note": "Every figure equals the corresponding site figure for this "
                    "day; both are read from the same computed object (BR-21)."}

# =========================================================================
# Disclosures — every rule that touched this day, said out loud
# =========================================================================

def _disclosures(da, day: D, obj) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    c = obj["comp"]

    if c["override_in_effect"]:
        out.append({"rule": "BR-1", "text":
                    "Holiday alignment in effect (%s). The comp above compares "
                    "%s with %s, the same holiday last year. The week-aligned "
                    "comparison (%s) reads %s and is shown for reference only."
                    % (_holiday_name(c["holiday_code"]), fmt.day_short_year(day),
                       fmt.day_short_year(c["holiday_aligned"]["ly_date"]),
                       fmt.day_short_year(c["week_aligned"]["ly_date"]),
                       fmt.pct(c["week_aligned"]["pct"]))})
        ty_wd = fmt.WEEKDAYS[day.weekday()]
        ly_wd = fmt.WEEKDAYS[D.fromisoformat(
            c["holiday_aligned"]["ly_date"]).weekday()]
        if ty_wd != ly_wd:
            out.append({"rule": "BR-1", "text":
                        "Holiday alignment buys the holiday and gives up the "
                        "weekday: %s falls on a %s this year and a %s last year, "
                        "so part of the movement above is the weekday, not the "
                        "trade. Both comparisons are shown because neither is "
                        "complete on its own."
                        % (_holiday_name(c["holiday_code"]), ty_wd, ly_wd)})
    if c["restated_53_week"]:
        out.append({"rule": "BR-8", "text":
                    "53-week restatement in effect: the prior fiscal year's "
                    "weeks are shifted to the NRF restated calendar before "
                    "alignment."})

    ex = _comp_exclusions(da, day)
    if ex["remodel"]:
        out.append({"rule": "BR-2", "text":
                    "Excluded from comp on both sides — closed for remodel: %s."
                    % _names(da, ex["remodel"])})
    if ex["immature"]:
        out.append({"rule": "BR-2", "text":
                    "In total sales but not in comp — fewer than 13 full fiscal "
                    "periods of trading: %s." % _names(da, ex["immature"])})

    cm = obj["completeness"]
    if cm["missing"]:
        out.append({"rule": "BR-3", "text":
                    "%d of %d doors had not posted at generation time and are "
                    "MISSING, not zero: %s. Totals are reported-door figures; no "
                    "imputation." % (len(cm["missing"]), cm["expected"],
                                     ", ".join(cm["missing_names"]))})
    for lp in cm["escalating"]:
        out.append({"rule": "BR-3", "text":
                    "ESCALATION — %s (%s) has not posted for %d consecutive days "
                    "(since %s). Store operations action required."
                    % (lp["name"], lp["region"], lp["consecutive_days"],
                       fmt.day_short_year(lp["since"]))})
    if cm["traffic_missing"]:
        out.append({"rule": "BR-15", "text":
                    "No traffic posted for %s. Conversion is UNAVAILABLE for "
                    "those doors and they are excluded from the fleet "
                    "conversion on both sides — a missing measurement is never "
                    "shown as 0%%." % ", ".join(cm["traffic_missing_names"])})

    ps = obj["plan_status"]
    out.append({"rule": "BR-19", "text":
                "%s Day-planned brands are measured against the day plan; the "
                "week-planned brand shows %s and is never spread to days; the "
                "no-plan brand shows actuals only and never a fabricated 100%%. "
                "%s of the day's sales sit inside a plan of any grain."
                % (ps["disclosure"], ps["week_grain"]["label"],
                   fmt.pct_plain(ps["planned_share_of_actual"]))})

    if obj["currency_note"]:
        out.append({"rule": "BR-16", "text":
                    "%s Facts are held in each door's local currency and "
                    "converted once, at the seeded fixed rate, for every "
                    "cross-market total on this flash. Nothing is mixed."
                    % obj["currency_note"]})

    inv = obj["omni"]["invariance"]
    out.append({"rule": "BR-9", "text":
                "Omni attributes, it never adds. %s of today's net sales is "
                "explained by an omni behaviour; the headline is %s with the "
                "omni layer on and %s with it off — the same number, because "
                "omni panels partition the headline rather than extend it."
                % (fmt.pct_plain(inv["attributed_share"]),
                   fmt.money_compact(inv["headline_omni_on"]),
                   fmt.money_compact(inv["headline_omni_off"]))})

    if obj["merch"]["available"]:
        out.append({"rule": "BR-11", "text":
                    "Category and SKU figures are derived from sales lines and "
                    "sum to the door totals above, to the cent. Region, "
                    "district and door levels each sum to their parent."})
    else:
        out.append({"rule": "BR-11", "text":
                    "SKU-grain detail is not seeded for this day, so category "
                    "and SKU panels are UNAVAILABLE rather than empty."})

    ec = obj["ecom"]
    if ec:
        if obj["basis"] == "settled":
            out.append({"rule": "BR-4", "text":
                        "E-commerce is on the SETTLED (shipped) basis in this "
                        "version; both years read shipped. The day-of flash "
                        "used demand."})
        else:
            out.append({"rule": "BR-4", "text":
                        "E-commerce comp is demand-based day-of (orders placed, "
                        "not shipped). Demand %s vs shipped %s; the day matures "
                        "after %d days and the archive shows both without "
                        "rewriting this flash."
                        % (fmt.money_compact(ec.get("demand")),
                           fmt.money_compact(ec.get("shipped")),
                           ec.get("settle_lag_days", 3))})
    out.append({"rule": "BR-17", "text":
                "Hourly views are intraday and unaudited. The posted daily "
                "figure is the system of record; hourly buckets sum to it "
                "exactly because they are an allocation of it."})
    out.append({"rule": "BR-5 / BR-13", "text":
                "Every figure here is computed once in the metric catalog and "
                "rendered to the site, the email digest and the door extract "
                "from one object. The three cannot disagree."})
    if obj["version"] > 1:
        out.append({"rule": "BR-7", "text":
                    "This is version %d — a restatement. Version 1 is preserved "
                    "unchanged in the archive." % obj["version"]})
    return out


def _comp_exclusions(da, day: D) -> Dict[str, List[str]]:
    remodel, immature = [], []
    members = set(da.comp_set(day))
    for e in da.entities():
        if e["channel"] != "STORE":
            continue
        eid = e["entity_id"]
        if eid in members:
            continue
        if da._in_remodel(e, day):
            remodel.append(eid)
        elif da.is_open_on(e, day) and not da.comp_eligible(eid, day):
            immature.append(eid)
    return {"remodel": sorted(remodel), "immature": sorted(immature)}


def _names(da, ids) -> str:
    return ", ".join("%s (%s, opened %s)"
                     % (da.entity(i)["name"], i,
                        fmt.day_short_year(da.entity(i)["open_date"]))
                     for i in ids)


def _holiday_name(code: Optional[str]) -> str:
    return code.replace("_", " ").title() if code else ""


def _method() -> List[Dict[str, str]]:
    """The formula key the email footer and every panel footnote carry."""
    return [
        {"metric": "Net sales", "formula":
         "Σ net_sales over REPORTED entities, converted once to the reporting "
         "currency at the seeded fixed rate. A door that has not posted is "
         "excluded, never zero-filled."},
        {"metric": "Comp %", "formula":
         "(Σ comp-door TY ÷ Σ comp-door LY-aligned) − 1. LY-aligned = same "
         "fiscal week, same weekday; holiday codes override week alignment."},
        {"metric": "Plan attainment", "formula":
         "Σ reported actual ÷ Σ plan at each brand's native plan grain. A "
         "week-planned brand reads WTD against the weekly plan; a brand with "
         "no plan reads 'no plan'."},
        {"metric": "AST / AUS / UPT", "formula":
         "net ÷ transactions, net ÷ units, units ÷ transactions. AST is the "
         "field's name for AOV and AUS for AUR — one formula, two labels."},
        {"metric": "Conversion", "formula":
         "transactions ÷ traffic, expressed as a percentage of visits and "
         "compared to LY in basis points. Stores only; a door with no traffic "
         "posted is UNAVAILABLE, never 0%."},
        {"metric": "Discounts / Returns", "formula":
         "discounts ÷ gross and store-side returns ÷ gross. Net sales = gross "
         "− discounts − returns, asserted per row."},
        {"metric": "OMNI penetration", "formula":
         "omni-attributed sales ÷ net sales, recognized bases only. These "
         "sales are already inside net sales; penetration is a share of the "
         "headline, not an addition to it."},
        {"metric": "Contribution to comp gap", "formula":
         "(entity TY − entity LY-aligned) ÷ total comp LY-aligned. Named "
         "contributions plus 'all other' equal the headline gap exactly."},
        {"metric": "KPI tree", "formula":
         "Sales = Traffic × Conversion × AST, AST = AUS × UPT. Driver "
         "contributions use sequential attribution in the fixed order traffic "
         "→ conversion → AST, which telescopes to the gap exactly."},
    ]

# =========================================================================
# Display strings (BR-5, second half)
# =========================================================================
#
# Every figure that appears on MORE THAN ONE surface is formatted once, here,
# and the renderers print the string. That is what stops the email rounding
# $412,449 to "$412K" while the site prints "$412.4K" — the same defect as a
# second formula, wearing a different hat.
#
# Site-only deep tables format through `fmt` in the renderer. They may format,
# they may never compute: no renderer divides, sums or compares a number.

def _narrative(obj) -> str:
    return narrative.compose_ops(obj)


def _display(obj) -> Dict[str, object]:
    h = obj["headline"]
    c = obj["comp"]
    cm = obj["completeness"]
    ps = obj["plan_status"]
    d: Dict[str, object] = {
        "date_long": fmt.day_long(obj["date"]),
        "date_short": fmt.day_short(obj["date"]),
        "date_short_year": fmt.day_short_year(obj["date"]),
        "as_of": fmt.day_long(obj["as_of"]),
        "period_label": obj["calendar"]["period_label"],
        "week_label": "FY%d W%02d" % (obj["calendar"]["fiscal_year"],
                                      obj["calendar"]["week"]),
        "quarter_label": "Q%d" % obj["calendar"]["quarter"],
        # -- the deck's KPI headline row, one string each -------------------
        "net_sales": fmt.money_compact(h["net_sales"]),
        "net_sales_exact": fmt.money_exact(h["net_sales"]),
        "comp_pct": fmt.pct(h["comp_pct"]),
        "comp_ly_date": fmt.day_short_year(c["ly_date"]),
        "comp_ty": fmt.money_exact(c["ty"]),
        "comp_ly": fmt.money_exact(c["ly"]),
        "comp_gap": fmt.money_signed(c["gap"]),
        "comp_gap_exact": fmt.money_exact(c["gap"]),
        "comp_members": "%d comp entities" % c["members"],
        "plan": fmt.money_compact(h["plan"]),
        "plan_attainment": fmt.pct_plain(h["plan_attainment"]),
        "plan_gap": fmt.money_signed(h["plan_gap"]),
        "transactions": fmt.count(h["transactions"]),
        "txn_comp": fmt.pct(h["comp_transactions"]["pct"]),
        "units": fmt.count(h["units"]),
        "ast": fmt.money_plain(h["ast"]),
        "ast_vs_ly": fmt.pct(h["ast_pct_vs_ly"]),
        "aus": fmt.money_plain(h["aus"]),
        "aus_vs_ly": fmt.pct(h["aus_pct_vs_ly"]),
        "upt": fmt.ratio(h["upt"]),
        "upt_vs_ly": fmt.pct(h["upt_pct_vs_ly"]),
        "ly_upt": fmt.ratio(h["ly_upt"]),
        "units_vs_ly": fmt.pct(h["units_pct_vs_ly"]),
        "traffic": fmt.count(h["traffic"]),
        "traffic_pct": fmt.pct(h["traffic_pct_vs_ly"]),
        "conversion": (fmt.pct_plain(h["conversion"], 2)
                       if h["conversion_available"] else "unavailable"),
        "conversion_bps": _bps(h["conversion_bps_vs_ly"]),
        "conversion_move": h["conversion_move"],
        "conversion_move_full": h["conversion_move_full"],
        "new_customers": fmt.count(h["new_customers"]),
        "new_customer_sales": fmt.money_compact(h["new_customer_sales"]),
        "new_customer_pct": fmt.pct_plain(h["new_customer_pct"]),
        "new_customer_ast": fmt.money_plain(h["new_customer_ast"]),
        "returns": fmt.money_compact(h["returns"]),
        "returns_pct_of_gross": fmt.pct_plain(h["returns_pct_of_gross"]),
        "returns_vs_ly": fmt.pct(h["returns_pct_vs_ly"]),
        "discounts": fmt.money_compact(h["discounts"]),
        "discounts_pct_of_gross": fmt.pct_plain(h["discounts_pct_of_gross"]),
        "discounts_vs_ly": fmt.pct(h["discounts_pct_vs_ly"]),
        "gross_sales": fmt.money_compact(h["gross_sales"]),
        "omni_penetration": fmt.pct_plain(h["omni_penetration"], 2),
        "omni_penetration_bps": _bps(h["omni_penetration_bps_vs_ly"]),
        "portfolio": fmt.count(h["portfolio"]),
        "trading": fmt.count(h["trading"]),
        "comp_trading": fmt.count(h["comp_trading"]),
        "pct_trading": fmt.pct_plain(h["pct_trading"]),
        "pct_comp_of_trading": fmt.pct_plain(h["pct_comp_of_trading"]),
        "demand_pct_of_gross": fmt.pct_plain(h["demand_pct_of_gross"]),
        # -- completeness / comp bases ------------------------------------
        "completeness": "%d of %d doors reported" % (cm["reported"], cm["expected"]),
        "completeness_pct": fmt.pct_plain(cm["pct"]),
        "posted_pct": fmt.pct_plain(cm["posted_pct"]),
        "week_aligned_pct": fmt.pct(c["week_aligned"]["pct"]),
        "week_aligned_ly_date": fmt.day_short_year(c["week_aligned"]["ly_date"]),
        "holiday_aligned_pct": (fmt.pct(c["holiday_aligned"]["pct"])
                                if c["holiday_aligned"] else None),
        "holiday_aligned_ly_date": (fmt.day_short_year(c["holiday_aligned"]["ly_date"])
                                    if c["holiday_aligned"] else None),
        "calendar_date_pct": (fmt.pct(c["calendar_date"]["pct"])
                              if c["calendar_date"] else None),
        "calendar_date_ly_date": (fmt.day_short_year(c["calendar_date"]["ly_date"])
                                  if c["calendar_date"] else None),
        # -- plan grain (BR-19) --------------------------------------------
        "plan_day_attainment": fmt.pct_plain(ps["day_grain"]["attainment"]),
        "plan_week_attainment": fmt.pct_plain(ps["week_grain"]["attainment"]),
        "plan_week_label": ps["week_grain"]["label"],
        "plan_no_plan_actual": fmt.money_compact(ps["no_plan"]["actual"]),
        "plan_coverage": fmt.pct_plain(ps["planned_share_of_actual"]),
    }
    d["windows"] = {}
    for key, w in sorted(obj["windows"].items()):
        d["windows"][key] = {
            "label": w["label"],
            "range": "%s – %s" % (fmt.day_short(w["start"]), fmt.day_short(w["end"])),
            "net_sales": fmt.money_compact(w["net_sales"]),
            "comp_pct": fmt.pct(w["comp_pct"]),
            "plan_attainment": fmt.pct_plain(w["plan_attainment"]),
            "transactions": fmt.count(w["transactions"]),
            "conversion": fmt.pct_plain(w["conversion"], 2),
            "conversion_bps": _bps(w["conversion_bps_vs_ly"]),
            "conversion_move": w["conversion_move"],
            "upt": fmt.ratio(w["upt"]),
            "upt_vs_ly": fmt.pct(w["upt_pct_vs_ly"]),
            "ast": fmt.money_plain(w["ast"]),
            "traffic": fmt.count(w["traffic"]),
            "new_buyers": fmt.count(w["new_buyers"]),
            "pct_new_to_file": fmt.pct_plain(w["pct_new_to_file"]),
            "days": str(w["days"]),
        }
    d["slices"] = {}
    for dim, rows in sorted(obj["slices"].items()):
        d["slices"][dim] = [_display_slice(r) for r in rows]
    d["tiers"] = {k: {
        "tier": _tier_label(k), "entities": str(v["entities"]),
        "net_sales": fmt.money_compact(v["net_sales"]),
        "comp_pct": fmt.pct(v["comp_pct"]),
        "plan": fmt.money_compact(v["plan"]),
        "plan_attainment": fmt.pct_plain(v["plan_attainment"]),
    } for k, v in sorted(obj["tiers"].items())}
    d["focus"] = {
        "headline_gap": fmt.money_signed(obj["focus"]["headline_gap"]),
        "remainder": fmt.money_signed(obj["focus"]["remainder"]),
        "remainder_label": "All other (%d entities)" % obj["focus"]["remainder_count"],
        "entries": [_display_entry(e) for e in obj["focus"]["entries"]],
        "trailing_label": "Trailing %d days" % obj["focus"]["trailing_days"],
        "trailing_regions": [_display_region(r)
                             for r in obj["focus"]["trailing_regions"]],
        "wtd_regions": [_display_region(r) for r in obj["focus"]["wtd_regions"]],
    }
    d["exceptions"] = [{
        "kind": e["kind"], "severity": e["severity"], "title": e["title"],
        "detail": e["detail"], "href": e["href"], "rule": e["rule"],
        "mark": {"escalation": "!", "adverse": "▼", "watch": "•",
                 "favourable": "▲"}.get(e["severity"], "•"),
    } for e in obj["exceptions"]]
    d["omni"] = _display_omni(obj)
    d["customer"] = _display_customer(obj)
    d["merch"] = _display_merch(obj)
    ec = obj["ecom"]
    if ec:
        d["ecom"] = {
            "demand": fmt.money_compact(ec.get("demand")),
            "shipped": fmt.money_compact(ec.get("shipped")),
            "returns": fmt.money_compact(ec.get("returns")),
            "demand_comp": fmt.pct(ec.get("demand_comp_pct")),
            "shipped_comp": fmt.pct(ec.get("shipped_comp_pct")),
            "return_rate": fmt.pct_plain(ec.get("settled_return_rate")),
            "matured": "matured" if ec.get("matured") else "not yet matured",
            "basis": ec.get("basis_in_headline"),
        }
    if obj["recap"]:
        g = obj["recap"]["gap_to_go"]
        cw = obj["recap"]["closed_week"]
        d["recap"] = {
            "range": "%s – %s" % (fmt.day_short(cw["start"]), fmt.day_short(cw["end"])),
            "net_sales": fmt.money_compact(cw["net_sales"]),
            "comp_pct": fmt.pct(cw["comp_pct"]),
            "plan_attainment": fmt.pct_plain(cw["plan_attainment"]),
            "remaining_plan": fmt.money_compact(g["remaining_plan"]),
            "remaining_days": str(g["remaining_days"]),
            "run_rate": fmt.money_compact(g["required_run_rate"]),
            "period_label": g["period_label"],
        }
    return d


def _tier_label(key: str) -> str:
    return {"COMP_TRADING": "Comp trading", "ALL_TRADING": "All trading",
            "TOTAL": "Total"}[key]


def _bps(v) -> str:
    if v is None:
        return fmt.NA
    sign = "+" if v >= 0 else fmt.MINUS
    return "%s%d bp" % (sign, abs(int(round(v))))


def _display_slice(r) -> Dict[str, object]:
    return {
        "key": r["key"], "label": r["label"], "region": r["region"],
        "net_sales": fmt.money_compact(r["net_sales"]),
        "net_sales_exact": fmt.money_exact(r["net_sales"]),
        "comp_pct": fmt.pct(r["comp_pct"]),
        "comp_gap": fmt.money_signed(r["comp_gap"]),
        "plan_attainment": fmt.pct_plain(r["plan_attainment"]),
        "plan_grain_mix": "/".join(r["plan_grain_mix"]) or "no plan",
        "conversion": fmt.pct_plain(r["conversion"], 2),
        "conversion_bps": _bps(r["conversion_bps_vs_ly"]),
        "conversion_move": r["conversion_move"],
        "upt": fmt.ratio(r["upt"]),
        "upt_vs_ly": fmt.pct(r["upt_pct_vs_ly"]),
        "traffic": fmt.count(r["traffic"]),
        "coverage": "%d/%d" % (r["reported_entities"], r["open_entities"]),
        "adverse": (r["comp_pct"] or 0) < 0,
    }


def _display_region(r) -> Dict[str, object]:
    return {
        "label": r["label"], "ty": fmt.money_compact(r["ty"]),
        "ly": fmt.money_compact(r["ly"]), "delta": fmt.money_signed(r["delta"]),
        "pct": fmt.pct(r["pct"]), "entities": str(r["entities"]),
        "adverse": r["delta"] < 0,
    }


def _display_entry(e) -> Dict[str, object]:
    return {
        "kind": e["kind"], "key": e["key"], "label": e["label"],
        "region": e["region"], "delta": fmt.money_signed(e["delta"]),
        "delta_exact": fmt.money_exact(e["delta"]), "pct": fmt.pct(e["pct"]),
        "share": fmt.pct(e["contribution"]), "adverse": e["adverse"],
        "receipts": ["%s %s (%s)" % (r["name"], fmt.money_signed(r["delta"]),
                                     fmt.pct(r["pct"])) for r in e["receipts"]],
        "line": _entry_line(e),
    }


def _entry_line(e) -> str:
    head = "%s %s vs LY (%s)" % (e["label"], fmt.money_signed(e["delta"]),
                                 fmt.pct(e["pct"]))
    if e["kind"] == "region":
        head = "%s region %s vs LY (%s)" % (e["label"],
                                            fmt.money_signed(e["delta"]),
                                            fmt.pct(e["pct"]))
    if e["receipts"]:
        share = sum(abs(r["delta"]) for r in e["receipts"])
        total = abs(e["delta"]) or 1.0
        names = " and ".join(r["name"] for r in e["receipts"])
        head += " — %s drove %s of it" % (names, fmt.pct_plain(share / total, 0))
    elif e["region"] and e["kind"] == "store":
        head += " — %s" % e["region"]
    return head + "."


def _display_omni(obj) -> Dict[str, object]:
    o = obj["omni"]
    fams = []
    for key in OMNI_PANELS:
        f = o["families"][key]
        rec = f["recognized"]
        if key == "BORIS":
            fams.append({
                "key": key, "label": "Buy Online, Return In Store",
                "orders": fmt.count(rec["orders"]),
                "sales": fmt.money_compact(rec["returned_sales"]),
                "aov": fmt.NA, "vs_ly": fmt.pct(f["pct_vs_ly"]),
                "all_orders": fmt.NA, "all_sales": fmt.NA,
                "completion": fmt.pct_plain(rec["save_rate"]),
                "extra": "%s saved on %s of returns; %s of shipping labels"
                         % (fmt.money_compact(rec["saved_sales"]),
                            fmt.pct_plain(rec["save_rate"]),
                            fmt.money_compact(rec["label_savings"])),
            })
            continue
        ai = f["all_inclusive"]
        fams.append({
            "key": key, "label": f["label"],
            "orders": fmt.count(rec["orders"]),
            "sales": fmt.money_compact(rec["sales"]),
            "aov": fmt.money_plain(rec["aov"]),
            "vs_ly": fmt.pct(f["recognized_pct_vs_ly"]),
            "all_orders": fmt.count(ai["orders"]),
            "all_sales": fmt.money_compact(ai["sales"]),
            "completion": fmt.pct_plain(f["completion_rate"]),
            "extra": f["attribution"],
        })
    up = o["upsell"]
    return {
        "families": fams,
        "penetration": fmt.pct_plain(o["penetration"]["penetration"], 2),
        "penetration_bps": _bps(o["penetration"]["bps_vs_ly"]),
        "attributed": fmt.money_compact(o["penetration"]["omni_attributed_sales"]),
        "upsell_sales": fmt.money_compact(up["upsell_sales"]),
        "upsell_attach": fmt.pct_plain(up["attach_pct"]),
        "upsell_orders": fmt.count(up["upsell_orders"]),
        "invariance_on": fmt.money_exact(o["invariance"]["headline_omni_on"]),
        "invariance_off": fmt.money_exact(o["invariance"]["headline_omni_off"]),
        "attributed_share": fmt.pct_plain(o["invariance"]["attributed_share"]),
    }


def _display_customer(obj) -> Dict[str, object]:
    c = obj["customer"]
    ty = c["day"]["ty"]
    nb = c["new_block"]
    return {
        "total_buyers": fmt.count(ty["total_buyers"]),
        "new_buyers": fmt.count(ty["new_buyers"]),
        "repeat_buyers": fmt.count(ty["repeat_buyers"]),
        "pct_new_to_file": fmt.pct_plain(ty["pct_new_to_file"]),
        "repeat_rate": fmt.pct_plain(ty["repeat_rate"]),
        "ntf_bps_vs_ly": _bps(c["day"]["ntf_bps_vs_ly"]),
        "new_sales": fmt.money_compact(nb["net_sales"]),
        "new_pct_of_sales": fmt.pct_plain(nb["pct_of_net_sales"]),
        "new_ast": fmt.money_plain(nb["ast"]),
        "new_ast_index": fmt.pct_plain(nb["ast_index_vs_fleet"]),
        "file_size": fmt.count(c["file_size"]["customers"]),
        "wtd_ntf": fmt.pct_plain(c["windows"]["WTD"]["pct_new_to_file"]),
        "mtd_ntf": fmt.pct_plain(c["windows"]["MTD"]["pct_new_to_file"]),
    }


def _display_merch(obj) -> Dict[str, object]:
    m = obj["merch"]
    if not m["available"]:
        return {"available": False,
                "reason": m["categories"].get("reason", "SKU grain unavailable")}
    cats = [{
        "category": r["category"], "brand_id": r["brand_id"],
        "net_sales": fmt.money_compact(r["net_sales"]),
        "net_sales_exact": fmt.money_exact(r["net_sales"]),
        "mix_pct": fmt.pct_plain(r["mix_pct"]),
        "comp_pct": fmt.pct(r["comp_pct"]),
        "plan": fmt.money_compact(r["plan"]),
        "plan_attainment": fmt.pct_plain(r["plan_attainment"]),
        "plan_coverage": fmt.pct_plain(r["plan_coverage"]),
        "aur": fmt.money_plain(r["aur"]),
        "units": fmt.count(r["units"]),
        "adverse": (r["comp_pct"] or 0) < 0,
    } for r in m["categories"]["categories"]]
    return {
        "available": True,
        "categories": cats,
        "total": fmt.money_compact(m["categories"]["total_net_sales"]),
        "reconciliation": "%s of categories = %s of doors"
                          % (fmt.money_exact(m["categories"]["reconciliation"]["sum_of_categories"]),
                             fmt.money_exact(m["categories"]["reconciliation"]["entity_day_total"])),
        "top": [_display_mover(r) for r in m["movers"]["top"]],
        "bottom": [_display_mover(r) for r in m["movers"]["bottom"]],
    }


def _display_mover(r) -> Dict[str, object]:
    return {
        "sku_id": r["sku_id"], "name": r["name"], "category": r["category"],
        "brand_id": r["brand_id"],
        "ty": fmt.money_compact(r["ty"]), "ly": fmt.money_compact(r["ly"]),
        "delta": fmt.money_signed(r["delta"]),
        "pct": fmt.pct(r["pct_vs_ly"]),
        "share": fmt.pct(r["contribution"]),
        "days_since_launch": str(r["days_since_launch"]),
        "new": r["days_since_launch"] < 90,
        "adverse": r["delta"] < 0,
    }


def _subject(obj) -> str:
    """The digest subject, built from the same display strings the body prints —
    so it can never disagree with the flash it announces."""
    d = obj["display"]
    n = len([e for e in obj["exceptions"]
             if e["severity"] in ("escalation", "adverse")])
    return "Ops Flash — %s · %s · comp %s · plan %s · %d exception%s" % (
        d["date_short"], d["net_sales"], d["comp_pct"], d["plan_attainment"],
        n, "" if n == 1 else "s")

# =========================================================================
# Per-day invariants (PRD §4 — BR-6, BR-9, BR-11, BR-12)
# =========================================================================

CENT = 0.005


def _assert_invariants(da, obj, day) -> None:
    """Run on EVERY generated day, at object-assembly time.

    The seed asserts the data is right; these assert the object built from it
    is right. A renderer can then print without checking, because a broken
    object never reaches one."""
    # -- BR-6: the focus panel decomposes the headline gap exactly ---------
    f = obj["focus"]
    check = round(sum(e["delta"] for e in f["entries"]) + f["remainder"], 2)
    if abs(check - f["headline_gap"]) > CENT:
        raise AssertionError(
            "BR-6 broken on %s after object assembly: entries + remainder = %s "
            "but the headline comp gap = %s. Fix in flash/focus.py — an entry's "
            "`covers` set overlaps another's, so one door is counted twice."
            % (day, check, f["headline_gap"]))

    # -- BR-1: the adjusted comp leads and the raw one is still stated -----
    c = obj["comp"]
    if c["week_aligned"] is None:
        raise AssertionError(
            "BR-1 broken on %s: the week-aligned comp is missing. A raw "
            "comparison may never appear without the aligned figure." % day)
    if c["override_in_effect"]:
        if c["holiday_aligned"] is None or c["pct"] != c["holiday_aligned"]["pct"]:
            raise AssertionError(
                "BR-1 broken on %s: a holiday override is in effect but the "
                "leading comp is not the holiday-aligned figure. The adjusted "
                "number leads and both are stated." % day)

    # -- BR-9: omni attributes, it never adds ------------------------------
    inv = obj["omni"]["invariance"]
    if inv["headline_omni_on"] != inv["headline_omni_off"]:
        raise AssertionError(
            "BR-9 broken on %s: headline is %s with the omni layer on and %s "
            "with it off. Omni panels must partition the headline, never "
            "extend it." % (day, inv["headline_omni_on"], inv["headline_omni_off"]))
    if inv["headline_omni_on"] != obj["headline"]["net_sales"]:
        raise AssertionError(
            "BR-9 broken on %s: the invariance proof reads %s but the headline "
            "reads %s. They must be the same call."
            % (day, inv["headline_omni_on"], obj["headline"]["net_sales"]))
    if inv["attributed_exceeds_headline"]:
        raise AssertionError(
            "BR-9 broken on %s: omni-attributed sales (%s) exceed the net sales "
            "(%s) they are supposed to be a slice of. Lower the omni volume "
            "shares in seed.py." % (day, inv["omni_attributed"],
                                    inv["headline_omni_off"]))

    # -- BR-11: every level sums to its parent -----------------------------
    m = obj["merch"]
    if m["available"]:
        r = m["categories"]["reconciliation"]
        if abs(r["sum_of_categories"] - r["entity_day_total"]) > 0.01:
            raise AssertionError(
                "BR-11 broken on %s: categories sum to %s but the doors sum to "
                "%s. Fix in flash/merch.py — the category rollup is not reading "
                "the same entity scope as the headline."
                % (day, r["sum_of_categories"], r["entity_day_total"]))
        if not m["reconciliation"].get("reconciled", True):
            raise AssertionError(
                "BR-11 broken on %s: SKU lines do not sum to the posted day for "
                "%s. Fix in seed.gen_sales_lines() — lines are an allocation of "
                "the day, never an independent draw."
                % (day, m["reconciliation"]["breaks"][:2]))
    total_slices = round(sum(s["net_sales"] for s in obj["slices"]["region"]), 2)
    if abs(total_slices - obj["headline"]["net_sales"]) > 0.01:
        raise AssertionError(
            "BR-11 broken on %s: region slices sum to %s but the headline is "
            "%s. A door is in two regions or in none."
            % (day, total_slices, obj["headline"]["net_sales"]))
    if obj["depth"] == "full":
        dr = obj["drill"]
        if abs(dr["children_sum"] - dr["total"]) > 0.01:
            raise AssertionError(
                "BR-11 broken on %s: the drill tree's regions sum to %s against "
                "a total of %s." % (day, dr["children_sum"], dr["total"]))
        for reg in dr["regions"]:
            if abs(reg["children_sum"] - reg["net_sales"]) > 0.01:
                raise AssertionError(
                    "BR-11 broken on %s: region %s children sum to %s against "
                    "its own %s. A door is missing from every district, or in "
                    "two." % (day, reg["key"], reg["children_sum"],
                              reg["net_sales"]))

    # -- BR-12: buyer counts are consistent wherever they appear -----------
    cust = obj["customer"]["day"]["ty"]
    if cust["total_buyers"] != obj["headline"]["transactions"]:
        raise AssertionError(
            "BR-12 broken on %s: the customer panel counts %d buyers and the "
            "headline counts %d transactions. One transaction is one buyer; "
            "the two cannot diverge."
            % (day, cust["total_buyers"], obj["headline"]["transactions"]))
    if cust["new_buyers"] != obj["headline"]["new_customers"]:
        raise AssertionError(
            "BR-12 broken on %s: the customer panel counts %d new buyers and "
            "the New Customer block counts %d. Both must derive from "
            "customer.first_purchase_date."
            % (day, cust["new_buyers"], obj["headline"]["new_customers"]))
    if obj["customer"]["new_block"]["net_sales"] > obj["headline"]["net_sales"]:
        raise AssertionError(
            "BR-9/BR-12 broken on %s: new-customer sales (%s) exceed the day's "
            "net sales (%s). The New Customer block attributes, it does not add."
            % (day, obj["customer"]["new_block"]["net_sales"],
               obj["headline"]["net_sales"]))

    # -- BR-15: conversion is never a fabricated zero ----------------------
    h = obj["headline"]
    if not h["conversion_available"] and h["conversion"] not in (None,):
        raise AssertionError(
            "BR-15 broken on %s: conversion is flagged unavailable but carries "
            "the value %r." % (day, h["conversion"]))

    # -- BR-20: the tree composes exactly, on every store it is built for --
    for eid, b in sorted(obj.get("stores", {}).items()):
        t = b.get("tree")
        if not t or not t.get("available"):
            continue
        s = sum(x["contribution"] for x in t["drivers"])
        if abs(s - t["gap"]) > 0.02:
            raise AssertionError(
                "BR-20 broken on %s for %s: driver contributions sum to %.2f "
                "against a gap of %.2f. Fix in catalog.kpi_tree()."
                % (day, eid, s, t["gap"]))

    # -- headline blocks: item 1's three promises, checked ----------------
    scopes = [("headlines", obj["headlines"])]
    for key in sorted(obj.get("personas", {})):
        scopes.append((key, obj["personas"][key]["headlines"]))
    for name, h in scopes:
        for block in ("attention", "celebration"):
            if len(h[block]) > h["max_items"]:
                raise AssertionError(
                    "%s on %s lists %d %s items; the ceiling is %d. Three is "
                    "what a district manager reads before breakfast; a fourth "
                    "is a list, not a headline."
                    % (name, day, len(h[block]), block, h["max_items"]))
        att = set()
        for it in h["attention"]:
            att |= set(it["entities"] or [it["key"]])
        for it in h["celebration"]:
            overlap = att & set(it["entities"] or [it["key"]])
            if overlap:
                raise AssertionError(
                    "%s on %s puts %s in both 'needs attention' and 'worth "
                    "celebrating'. One entity, one verdict — a page that says "
                    "both has said nothing."
                    % (name, day, sorted(overlap)))
        for it in h["attention"] + h["celebration"]:
            if it["kind"] != "door" or it["ty"] is None:
                continue
            eid = it["key"]
            if it["rule"] == "BR-19":
                continue          # plan items carry actual vs plan, not vs LY
            actual = da.net_sales_of(eid, day)
            if actual is None or abs(actual - it["ty"]) > 0.01:
                raise AssertionError(
                    "%s on %s: headline item for %s carries TY %r but the door "
                    "page reads %r. A headline must be the same call as the "
                    "page it links to (BR-18)."
                    % (name, day, eid, it["ty"], actual))
            if it["ly"] is not None:
                ly_actual = da.net_sales_of(eid, da.ly_date(day))
                if ly_actual is None or abs(ly_actual - it["ly"]) > 0.01:
                    raise AssertionError(
                        "%s on %s: headline item for %s carries LY %r but the "
                        "aligned day reads %r."
                        % (name, day, eid, it["ly"], ly_actual))

    # -- BR-22: a conversion movement never travels without its drivers ----
    cm = obj["conversion_move"]
    if cm["available"]:
        if abs(cm["identity_gap"]) > 1e-9:
            raise AssertionError(
                "BR-22 broken on %s: (1 + txns%%) / (1 + traffic%%) misses the "
                "conversion ratio by %r. The annotation's three figures must "
                "come off one comparable set." % (day, cm["identity_gap"]))
        if "traffic" not in cm["annotation"] or "txns" not in cm["annotation"]:
            raise AssertionError(
                "BR-22 broken on %s: the annotation %r states a movement "
                "without its drivers." % (day, cm["annotation"]))
    elif "bp" in cm["annotation"]:
        raise AssertionError(
            "BR-22 broken on %s: conversion is unavailable but the annotation "
            "%r still states a basis-point move." % (day, cm["annotation"]))

    # -- narrative discipline ---------------------------------------------
    sentences = [s for s in obj["narrative"].split(". ") if s.strip()]
    if len(sentences) > MAX_NARRATIVE_SENTENCES:
        raise AssertionError(
            "Narrative on %s runs to %d sentences; the ops ceiling is %d. Trim "
            "flash/narrative.py — the exception list carries the detail."
            % (day, len(sentences), MAX_NARRATIVE_SENTENCES))
