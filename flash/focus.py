# -*- coding: utf-8 -*-
"""Focus panel — the "why" behind the headline (PRD §6, BR-6).

Three ideas, in order of how much they matter:

1. **Reconciliation is a proof, not a hope.** Every entry the panel displays
   carries a dollar gap; the entries plus an explicit "all other" remainder
   equal the headline comp gap to the cent. The remainder is computed by
   *summing the entities nobody named* — not by subtracting the named ones from
   the total, which would make the assertion tautological and worthless.

2. **Name the highest level that explains the movement** (§6.3). If one region
   carries more than REGION_ROLLUP_SHARE of the gap, the panel names the region
   and puts its two worst doors inside it as receipts, instead of listing ten
   stores and making the reader do the grouping.

3. **Entries never overlap.** A named region owns every store inside it; those
   stores can never also appear as their own entries. Overlap is the classic
   way a decomposition double-counts and still "reconciles" against a total
   that was inflated by the same double count.

Late posters (BR-3) are appended regardless of rank with a zero gap — they are
out of the comp set by definition (missing, never zero), so they change nothing
about reconciliation and everything about whether the reader trusts the number.

Stdlib only. No formulas live here: every figure comes from
`catalog.contribution_to_comp_gap` (#15) and `catalog.comp_pair` (#2).
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from flash import fmt

D = dt.date

MAX_ADVERSE = 3                  # §6.2 "up to three"
REGION_ROLLUP_SHARE = 0.60       # §6.3 ">60% of the gap"
RECEIPTS_PER_REGION = 2          # §6.3 "its worst two stores"
CENT = 0.005                     # BR-6 tolerance: half a cent


class ReconciliationError(AssertionError):
    """BR-6 violation. Carries the offending figures and the fix."""


def build_focus(da, day: D, ly_override: Optional[D] = None) -> Dict[str, object]:
    """The focus panel for one day.

    `ly_override` is passed straight through so a holiday day decomposes
    against the same LY date its headline comp leads with (BR-1) — a panel that
    decomposed a different comparison than the headline would reconcile to a
    gap the reader never saw.
    """
    contributions = da.contribution_to_comp_gap(day, ly_override=ly_override)
    headline = da.comp_pair(day, ly_override=ly_override)
    total_gap = headline["gap"]
    # Adverse means "cost the company money against LY" — a negative dollar
    # delta, on a beat day as much as on a miss day. §6.2's "sign against the
    # headline" is the beat-day case: the doors that held a good day back are
    # exactly the ones worth naming, and on a miss day they are the miss.
    # Making the test depend on the headline's sign would invert the panel on
    # every positive day and print a loss as the "bright spot".
    by_id = {c["entity_id"]: c for c in contributions}
    regions = _region_rollup(contributions)
    adverse_mass = sum(c["delta"] for c in contributions if c["delta"] < 0)

    entries: List[dict] = []
    claimed = set()               # entity_ids already explained by an entry

    # --- 1. region-level roll-up (§6.3) ----------------------------------
    for reg in _ranked(regions):
        if reg["region"] == "ECOM":
            # ECOM is one entity and a channel, not a geography. Rolling it up
            # would print "region E-commerce" and add no information.
            continue
        if reg["delta"] >= 0:
            continue
        # §6.3 measured against the ADVERSE MASS, not the net headline gap.
        # Against the net gap, a day that nets out near zero would let a $2K
        # region "explain 60% of the gap" and trigger a roll-up that explains
        # nothing. The adverse mass is the thing the panel is decomposing.
        if adverse_mass == 0 or abs(reg["delta"]) < abs(adverse_mass) * REGION_ROLLUP_SHARE:
            continue
        receipts = [c for c in reg["members"] if c["delta"] < 0]
        receipts = _ranked_list(receipts)[:RECEIPTS_PER_REGION]
        entries.append(_entry(
            kind="region", key=reg["region"], label=reg["region"],
            ty=reg["ty"], ly=reg["ly"], delta=reg["delta"],
            contribution=reg["contribution"],
            covers=[c["entity_id"] for c in reg["members"]],
            receipts=receipts, adverse=True))
        claimed.update(c["entity_id"] for c in reg["members"])
        break                     # at most one region roll-up per panel

    # --- 2. store/channel-level adverse movers ---------------------------
    for c in _ranked_list(contributions):
        if len([e for e in entries if e["adverse"]]) >= MAX_ADVERSE:
            break
        if c["entity_id"] in claimed:
            continue
        if c["delta"] >= 0:
            continue
        entries.append(_entry(
            kind="ecom" if c["channel"] == "ECOM" else "store",
            key=c["entity_id"], label=c["name"],
            ty=c["ty"], ly=c["ly"], delta=c["delta"],
            contribution=c["contribution"], covers=[c["entity_id"]],
            receipts=[], adverse=True, region=c["region"]))
        claimed.add(c["entity_id"])

    # --- 3. one bright spot (§6.2) ---------------------------------------
    favorable = [c for c in contributions
                 if c["entity_id"] not in claimed and c["delta"] > 0]
    favorable = sorted(favorable, key=lambda c: (-abs(c["delta"]), c["entity_id"]))
    bright = None
    if favorable:
        c = favorable[0]
        bright = _entry(
            kind="ecom" if c["channel"] == "ECOM" else "store",
            key=c["entity_id"], label=c["name"], ty=c["ty"], ly=c["ly"],
            delta=c["delta"], contribution=c["contribution"],
            covers=[c["entity_id"]], receipts=[], adverse=False,
            region=c["region"])
        entries.append(bright)
        claimed.add(c["entity_id"])

    # --- 4. reconciliation (BR-6) ----------------------------------------
    remainder_ids = sorted(set(by_id) - claimed)
    remainder = round(sum(by_id[i]["delta"] for i in remainder_ids), 2)
    displayed = round(sum(e["delta"] for e in entries), 2)
    _assert_reconciles(day, entries, remainder, remainder_ids, total_gap,
                       displayed, headline)

    # --- 5. late-poster escalation (BR-3, §6.6) --------------------------
    escalations = []
    for lp in da.late_posters(day):
        escalations.append({
            "kind": "late_poster",
            "key": lp["entity_id"],
            "label": lp["name"],
            "region": lp["region"],
            "consecutive_days": lp["consecutive_days"],
            "escalate": lp["escalate"],
            "since": lp["since"],
            "delta": 0.0,
            "adverse": True,
        })

    return {
        "headline_gap": total_gap,
        "headline_ty": headline["ty"],
        "headline_ly": headline["ly"],
        "ly_date": headline["ly_date"],
        "adverse_mass": round(adverse_mass, 2),
        "entries": entries,
        "remainder": remainder,
        "remainder_count": len(remainder_ids),
        "remainder_ids": remainder_ids,
        "escalations": escalations,
        "reconciled": True,
        "comp_members": len(by_id),
        "wtd_regions": region_movers(da, day, window="WTD"),
        "trailing_regions": region_movers(da, day, days=TRAILING_DAYS),
        "trailing_days": TRAILING_DAYS,
    }


TRAILING_DAYS = 14        # §7 storyline 2 plays out over "the trailing two weeks"


def region_movers(da, day: D, window: Optional[str] = None,
                  days: Optional[int] = None) -> List[dict]:
    """§6.1: #15 rolled to region over a multi-day window.

    A single day is noisy — a soft region only reads as *soft* over a run of
    days, which is why §6.1 asks for the WTD cut alongside the day cut. Each
    day inside the window contributes its own comp set against its own aligned
    LY date; the window is never a shifted total (PRD §5 #5).
    """
    if window:
        dates = da.window_dates(day, window)
    else:
        dates = [day - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]
    buckets: Dict[str, dict] = {}
    for d in dates:
        try:
            da.ly_date(d)
        except ValueError:
            continue
        for c in da.contribution_to_comp_gap(d):
            b = buckets.setdefault(c["region"], {
                "region": c["region"], "ty": 0.0, "ly": 0.0, "stores": set()})
            b["ty"] += c["ty"]
            b["ly"] += c["ly"]
            b["stores"].add(c["entity_id"])
    out = []
    for key in sorted(buckets):
        b = buckets[key]
        out.append({
            "region": key,
            "label": "E-commerce" if key == "ECOM" else key,
            "ty": round(b["ty"], 2),
            "ly": round(b["ly"], 2),
            "delta": round(b["ty"] - b["ly"], 2),
            "pct": (b["ty"] / b["ly"] - 1.0) if b["ly"] else None,
            "entities": len(b["stores"]),
            "start": dates[0].isoformat(),
            "end": dates[-1].isoformat(),
            "days": len(dates),
        })
    out.sort(key=lambda r: (r["delta"], r["region"]))
    return out


# -- helpers ---------------------------------------------------------------

def _entry(kind, key, label, ty, ly, delta, contribution, covers, receipts,
           adverse, region=None):
    return {
        "kind": kind,
        "key": key,
        "label": label,
        "region": region if region is not None else (key if kind == "region" else None),
        "ty": round(ty, 2),
        "ly": round(ly, 2),
        "delta": round(delta, 2),
        "contribution": contribution,
        "pct": (ty / ly - 1.0) if ly else None,
        "covers": sorted(covers),
        "receipts": [{
            "entity_id": r["entity_id"], "name": r["name"],
            "ty": round(r["ty"], 2), "ly": round(r["ly"], 2),
            "delta": round(r["delta"], 2),
            "pct": (r["ty"] / r["ly"] - 1.0) if r["ly"] else None,
        } for r in receipts],
        "adverse": adverse,
    }


def _region_rollup(contributions: List[dict]) -> List[dict]:
    """Aggregate store contributions to region. ECOM is its own bucket — it is
    a channel, not a geography, and folding it into a region would hide it."""
    buckets: Dict[str, dict] = {}
    for c in contributions:
        b = buckets.setdefault(c["region"], {
            "region": c["region"], "ty": 0.0, "ly": 0.0, "delta": 0.0,
            "contribution": 0.0, "members": []})
        b["ty"] += c["ty"]
        b["ly"] += c["ly"]
        b["delta"] += c["delta"]
        b["contribution"] += c["contribution"]
        b["members"].append(c)
    for b in buckets.values():
        b["ty"] = round(b["ty"], 2)
        b["ly"] = round(b["ly"], 2)
        b["delta"] = round(b["delta"], 2)
    return [buckets[k] for k in sorted(buckets)]


def _ranked(items):
    return _ranked_list(items)


def _ranked_list(items):
    """Most adverse (most negative dollars) first; ties broken by a stable
    identifier so output is byte-identical across runs (NFR-2)."""
    def key(c):
        ident = c.get("entity_id") or c.get("region")
        return (c["delta"], ident)
    return sorted(items, key=key)


def _assert_reconciles(day, entries, remainder, remainder_ids, total_gap,
                       displayed, headline):
    """BR-6, named and actionable on failure (NFR-4)."""
    check = round(displayed + remainder, 2)
    if abs(check - total_gap) > CENT:
        lines = ["  %-10s %-34s %14s" % (e["kind"], e["label"],
                                         fmt.money_exact(e["delta"]))
                 for e in entries]
        raise _recon_error(
            "BR-6 FOCUS RECONCILIATION FAILED for %s.\n"
            "  displayed entries  %s\n"
            "  all-other (%d entities: %s)  %s\n"
            "  entries + remainder %s\n"
            "  headline comp gap   %s  (TY %s vs LY-aligned %s on %s)\n"
            "  difference          %s\n"
            "%s\n"
            "  Fix: an entry is overlapping another entry's `covers` set, or a "
            "comp member is being counted in both a named entry and the "
            "remainder. Every comp entity must appear in exactly one of "
            "entries[].covers or remainder_ids."
            % (day, fmt.money_exact(displayed), len(remainder_ids),
               ", ".join(remainder_ids) or "none", fmt.money_exact(remainder),
               fmt.money_exact(check), fmt.money_exact(total_gap),
               fmt.money_exact(headline["ty"]), fmt.money_exact(headline["ly"]),
               headline["ly_date"], fmt.money_exact(check - total_gap),
               "\n".join(lines)))


def _recon_error(msg):
    return ReconciliationError(msg)


# =========================================================================
# Operational exceptions (Strategy §6)
# =========================================================================
#
# The executive flash had one exception family: a door or region moving against
# LY. The operational flash inherits that and adds four more, each with a
# threshold that lives in the catalog (`catalog.THRESHOLDS`) rather than here,
# so a renderer, a test and this module cannot disagree about what "beyond
# threshold" means.
#
# Every exception carries the same shape — kind, severity, headline, detail,
# and a `href` fragment naming where the reader can go to see it — because the
# email digest, the persona pages and the day flash all render the same list.

SEVERITY_ORDER = {"escalation": 0, "adverse": 1, "watch": 2, "favourable": 3}


def _exc(kind, severity, title, detail, href=None, rule=None, value=None,
         threshold=None, entities=None):
    return {
        "kind": kind, "severity": severity, "title": title, "detail": detail,
        "href": href, "rule": rule, "value": value, "threshold": threshold,
        "entities": sorted(entities or []),
    }


def build_exceptions(da, day: D, omni_mod, customer_mod, merch_mod,
                     **scope) -> List[dict]:
    """The day's calls to action, in one list, most urgent first.

    Ordering is severity then a stable key, never insertion order — two runs of
    the same day must produce the same list in the same order (NFR-2).
    """
    out: List[dict] = []
    out += _late_poster_exceptions(da, day)
    out += _two_day_negative_comp(da, day, **scope)
    out += _omni_exceptions(da, day, omni_mod, **scope)
    out += _category_exceptions(da, day, merch_mod, **scope)
    out += _ntf_exceptions(da, day, customer_mod, **scope)
    out += _conversion_exceptions(da, day, **scope)
    out.sort(key=lambda e: (SEVERITY_ORDER.get(e["severity"], 9),
                            e["kind"], e["title"]))
    return out


def _late_poster_exceptions(da, day: D) -> List[dict]:
    out = []
    for lp in da.late_posters(day):
        if not lp["escalate"]:
            continue
        out.append(_exc(
            "late_poster", "escalation",
            "%s has not posted for %d consecutive days"
            % (lp["name"], lp["consecutive_days"]),
            "Unposted since %s. The door is MISSING from every total on this "
            "flash, never zero-filled. Store operations action required."
            % fmt.day_short_year(lp["since"]),
            href="store/%s/%s.html" % (lp["entity_id"], day.isoformat()),
            rule="BR-3", entities=[lp["entity_id"]]))
    return out


def _two_day_negative_comp(da, day: D, **scope) -> List[dict]:
    """The executive flash's own trigger, kept: a door negative two days running
    is a trend; one day is weather."""
    prev = day - dt.timedelta(days=1)
    out = []
    for e in da._scope_entities(**scope):
        eid = e["entity_id"]
        if e["channel"] != "STORE":
            continue
        a = da.comp_pct(day, entity_id=eid)
        b = da.comp_pct(prev, entity_id=eid)
        if a is None or b is None or a >= 0 or b >= 0:
            continue
        out.append(_exc(
            "two_day_comp", "adverse",
            "%s negative two days running" % e["name"],
            "Comp %s on %s after %s on %s."
            % (fmt.pct(a), fmt.day_short(day), fmt.pct(b), fmt.day_short(prev)),
            href="store/%s/%s.html" % (eid, day.isoformat()),
            rule="BR-2", value=a, entities=[eid]))
    out.sort(key=lambda x: (x["value"], x["entities"]))
    return out[:5]


def _omni_exceptions(da, day: D, omni_mod, **scope) -> List[dict]:
    out = []
    for e in omni_mod.omni_exceptions(da, day, **scope):
        out.append(_exc(
            "omni", "adverse" if e["direction"] == "adverse" else "favourable",
            "%s %s vs LY" % (e["label"], fmt.pct(e["pct_vs_ly"])),
            "Recognized basis, %s vs the day-aligned LY — beyond the ±%s "
            "family threshold. Recognized and all-inclusive are separate "
            "series and are never mixed (BR-10)."
            % (fmt.pct(e["pct_vs_ly"]), fmt.pct_plain(e["threshold"], 0)),
            href="omni/%s/%s.html" % (e["family"], day.isoformat()),
            rule="BR-10", value=e["pct_vs_ly"], threshold=e["threshold"]))
    return out


def _category_exceptions(da, day: D, merch_mod, **scope) -> List[dict]:
    out = []
    for e in merch_mod.category_exceptions(da, day, **scope):
        skus = ", ".join("%s (%s)" % (s["name"], fmt.money_signed(s["delta"]))
                         for s in e["top_adverse_skus"])
        out.append(_exc(
            "category", "adverse", e["message"],
            "Adverse SKUs: %s." % skus if skus else "No SKU detail available.",
            href="category/%s/%s.html" % (_slug(e["category"]), day.isoformat()),
            rule="BR-11", value=e["gap_pts"], threshold=e["threshold_pts"]))
    return out


def _ntf_exceptions(da, day: D, customer_mod, **scope) -> List[dict]:
    out = []
    channels = [{"channel": "STORE"}, {"channel": "ECOM"}]
    for ch in channels:
        merged = dict(scope)
        merged.update(ch)
        e = customer_mod.ntf_exception(da, day, "WTD", **merged)
        if not e or not e["fires"]:
            continue
        out.append(_exc(
            "new_to_file", "adverse",
            "New-to-file share falling — %s" % _channel_label(ch["channel"]),
            "%s WTD. CRM flag: acquisition is running below its own trailing "
            "4-week baseline by more than %s."
            % (e["message"], fmt.pct_plain(e["threshold_pts"], 0)),
            href="customer/%s.html" % day.isoformat(),
            rule="BR-12", value=e["gap_pts"], threshold=e["threshold_pts"]))
    return out


def _conversion_exceptions(da, day: D, **scope) -> List[dict]:
    """Conversion below its own trailing baseline by more than the threshold,
    WTD, per door. A door with no traffic is UNAVAILABLE and cannot fire — a
    missing measurement is not a bad measurement (BR-15)."""
    from flash.catalog import THRESHOLDS
    thr_bp = THRESHOLDS["conversion_below_baseline_bp"]
    out = []
    for e in da._scope_entities(**scope):
        if e["channel"] != "STORE":
            continue
        eid = e["entity_id"]
        cur = da.conversion_window(day, "WTD", entity_id=eid)
        if cur["conversion"] is None:
            continue
        base_t = base_x = 0
        for wk in (1, 2, 3, 4):
            w = da.conversion_window(day - dt.timedelta(days=7 * wk), "WTD",
                                     entity_id=eid)
            base_t += w["traffic"]
            base_x += w["transactions"]
        if not base_t:
            continue
        baseline = base_x / float(base_t)
        bp = (cur["conversion"] - baseline) * 10000.0
        if bp > -thr_bp:
            continue
        out.append(_exc(
            "conversion", "adverse",
            "%s conversion %d bp below its own baseline" % (e["name"], round(bp)),
            "WTD conversion %s against a trailing 4-week baseline of %s on "
            "traffic of %s. Traffic is not the problem — the door is."
            % (fmt.pct_plain(cur["conversion"], 2), fmt.pct_plain(baseline, 2),
               fmt.count(cur["traffic"])),
            href="store/%s/tree/%s.html" % (eid, day.isoformat()),
            rule="BR-15", value=bp, threshold=-thr_bp, entities=[eid]))
    out.sort(key=lambda x: (x["value"], x["entities"]))
    return out[:5]


def _channel_label(key: str) -> str:
    return {"STORE": "Stores", "ECOM": "E-commerce"}.get(key, key)


def _slug(text: str) -> str:
    """URL-safe slug for a category name. One home, because the renderer and
    the exception's href must agree or the link 404s."""
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")
