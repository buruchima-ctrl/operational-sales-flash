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
        raise ReconciliationError(
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
