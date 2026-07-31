# -*- coding: utf-8 -*-
"""Customer metric catalog — PRD §5 metrics #25, #26, #34 (BR-12).

BR-12 in one sentence: **new-to-file is a pure function of
`customer.first_purchase_date`.** There is no second definition anywhere —
the omni panels' new-buyer lines call `new_buyers()` with an omni-scoped set
of customers, not a parallel formula, so the customer panel and the omni panel
cannot disagree.

Total buyers are the day's transactions. One transaction is one buyer, which
makes `repeat = total − new` exact and keeps the buyer count consistent with
every basket metric that already divides by transactions.

The New Customer block (#34) reads `customer.first_basket`, which the seed
ALLOCATES out of the same day's posted net sales. New-customer sales are
therefore a slice of the headline, never an addition to it.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from flash.catalog import THRESHOLDS

D = dt.date


def _new_index(da):
    """(date, entity_id) -> (count, first_basket sum in local ccy, units)."""
    if getattr(da, "_cust_idx", None) is None:
        idx = {}
        for d, e, n, amt, un in da.conn.execute(
                "SELECT first_purchase_date, home_entity_id, COUNT(*), "
                "SUM(first_basket), SUM(first_units) FROM customer "
                "GROUP BY 1, 2"):
            idx[(d, e)] = (n, amt or 0.0, un or 0)
        da._cust_idx = idx
    return da._cust_idx


def buyers(da, day: D, **scope) -> Dict[str, object]:
    """#25 New buyers / total buyers / % new-to-file for one day."""
    idx = _new_index(da)
    iso = day.isoformat()
    total = new = 0
    for eid in da.scope_ids(**scope):
        row = da.sales_row(eid, day)
        if row is None:
            continue                      # unposted: missing, never zero (BR-3)
        total += row["transactions"]
        new += idx.get((iso, eid), (0, 0.0, 0))[0]
    return {
        "date": iso, "total_buyers": total, "new_buyers": new,
        "repeat_buyers": total - new,
        "pct_new_to_file": (new / float(total)) if total else None,
        "repeat_rate": ((total - new) / float(total)) if total else None,
        "basis": "one transaction is one buyer; new-to-file is derived only "
                 "from customer.first_purchase_date (BR-12)",
    }


def buyers_vs_ly(da, day: D, **scope) -> Dict[str, object]:
    ly = da.ly_date(day)
    ty, lyv = buyers(da, day, **scope), buyers(da, ly, **scope)
    ty_p, ly_p = ty["pct_new_to_file"], lyv["pct_new_to_file"]
    return {
        "ty": ty, "ly": lyv, "ly_date": ly.isoformat(),
        "new_pct_vs_ly": (ty["new_buyers"] / float(lyv["new_buyers"]) - 1.0
                          if lyv["new_buyers"] else None),
        "ntf_bps_vs_ly": (round((ty_p - ly_p) * 10000.0, 1)
                          if (ty_p is not None and ly_p is not None) else None),
    }


def buyers_window(da, day: D, window: str, **scope) -> Dict[str, object]:
    """#25 across a fiscal window, and #26 repeat-buyer rate window-scoped."""
    total = new = 0
    for d in da.window_dates(day, window):
        b = buyers(da, d, **scope)
        total += b["total_buyers"]
        new += b["new_buyers"]
    return {
        "window": window, "end": day.isoformat(),
        "total_buyers": total, "new_buyers": new,
        "repeat_buyers": total - new,
        "pct_new_to_file": (new / float(total)) if total else None,
        "repeat_rate": ((total - new) / float(total)) if total else None,
    }


def repeat_rate(da, day: D, window: str = "WTD", **scope) -> Optional[float]:
    """#26 Repeat-buyer rate = 1 − new-to-file share, window-scoped."""
    return buyers_window(da, day, window, **scope)["repeat_rate"]


def new_customer_block(da, day: D, **scope) -> Dict[str, object]:
    """#34 The deck's store-page block: count, net sales, % of net sales, AST.

    Sales come from `customer.first_basket`, allocated by the seed out of the
    day's posted net sales — so the % of net sales is a genuine share of the
    headline and the AST is a real basket, not the fleet average recycled."""
    idx = _new_index(da)
    iso = day.isoformat()
    count = units = 0
    sales = 0.0
    for eid in da.scope_ids(**scope):
        if da.sales_row(eid, day) is None:
            continue
        n, amt, un = idx.get((iso, eid), (0, 0.0, 0))
        count += n
        units += un
        sales += da.convert(amt, da.entity(eid)["currency"])
    net = da.net_sales(day, **scope)
    b = da.basket(day, **scope)
    return {
        "date": iso, "new_customers": count, "net_sales": round(sales, 2),
        "units": units,
        "pct_of_net_sales": (sales / net) if net else None,
        "ast": (sales / count) if count else None,
        "aus": (sales / units) if units else None,
        "fleet_ast": b["ast"],
        "ast_index_vs_fleet": ((sales / count) / b["ast"]
                               if (count and b["ast"]) else None),
        "attribution": "new-customer sales are a slice of the same day's net "
                       "sales, not an addition to them (BR-9)",
    }


def omni_new_buyers(da, day: D, family: str, **scope) -> Dict[str, object]:
    """Omni BRD #15–17 / #27–29: new-buyer capture inside an omni family.

    Uses the SAME first-purchase-date rule as `buyers()` — the omni panel and
    the customer panel are the same definition read through a different
    filter, which is what BR-12 requires."""
    from flash import omni
    by_created, by_fulfilled = omni._omni_index(da)
    ids = set(da.scope_ids(**da._narrow(scope, channel="STORE")))
    iso = day.isoformat()
    firsts = dict(da.conn.execute(
        "SELECT customer_id, first_purchase_date FROM customer"))
    seen, new = set(), set()
    for r in by_fulfilled.get((iso, family), []):
        if r["store_id"] not in ids:
            continue
        seen.add(r["customer_id"])
        if firsts.get(r["customer_id"]) == iso:
            new.add(r["customer_id"])
    return {
        "date": iso, "family": family,
        "total_buyers": len(seen), "new_buyers": len(new),
        "pct_new_to_file": (len(new) / float(len(seen))) if seen else None,
        "basis": "recognized basis; new-to-file from first_purchase_date (BR-12)",
    }


def ntf_exception(da, day: D, window: str = "WTD", **scope) -> Optional[dict]:
    """CRM flag: new-to-file share below its own trailing baseline by more
    than the threshold (PRD §10: baseline − 5pts, WTD)."""
    cur = buyers_window(da, day, window, **scope)["pct_new_to_file"]
    if cur is None:
        return None
    base_total = base_new = 0
    for wk in (1, 2, 3, 4):
        for d in da.window_dates(day - dt.timedelta(days=7 * wk), window):
            b = buyers(da, d, **scope)
            base_total += b["total_buyers"]
            base_new += b["new_buyers"]
    if not base_total:
        return None
    baseline = base_new / float(base_total)
    thr = THRESHOLDS["ntf_below_baseline_pts"]
    return {
        "window": window, "as_of": day.isoformat(),
        "pct_new_to_file": cur, "baseline": baseline,
        "gap_pts": cur - baseline, "threshold_pts": thr,
        "fires": (baseline - cur) >= thr,
        "message": ("new-to-file %.1f%% is %.1f pts below the trailing "
                    "4-week baseline of %.1f%%"
                    % (cur * 100, (baseline - cur) * 100, baseline * 100)),
    }


def file_size(da, as_of: D) -> Dict[str, object]:
    """Customer file depth as of a date — the CRM's own denominator."""
    n = da.conn.execute(
        "SELECT COUNT(*) FROM customer WHERE first_purchase_date<=?",
        (as_of.isoformat(),)).fetchone()[0]
    by_aff = dict(da.conn.execute(
        "SELECT affiliate_id, COUNT(*) FROM customer "
        "WHERE first_purchase_date<=? GROUP BY 1", (as_of.isoformat(),)))
    return {"as_of": as_of.isoformat(), "customers": n, "by_affiliate": by_aff}
