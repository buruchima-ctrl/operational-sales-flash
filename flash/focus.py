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
            ty=reg["ty"], ly=reg["ly"], delta=reg["delta_exact"],
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
    # The check runs on UNROUNDED deltas against the unrounded headline gap,
    # because Σ round(x) and round(Σ x) differ by a cent often enough that a
    # rounded check would fail on arithmetic rather than on a real overlap —
    # and a rule that cries wolf gets deleted. The remainder is still computed
    # by summing the entities nobody named, never by subtracting the named ones
    # from the total, which would make the assertion tautological.
    remainder_ids = sorted(set(by_id) - claimed)
    remainder_raw = sum(by_id[i]["delta"] for i in remainder_ids)
    displayed_raw = sum(e["delta_raw"] for e in entries)
    _assert_reconciles(day, entries, round(remainder_raw, 2), remainder_ids,
                       headline["gap_raw"], displayed_raw, headline)
    # Display: the parts a reader can add up must add up. Any sub-cent
    # rounding residual lands on "all other", which is where an unnamed
    # fraction of a cent honestly belongs.
    remainder = round(total_gap - sum(e["delta"] for e in entries), 2)
    display_rounding = round(remainder - round(remainder_raw, 2), 2)

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
        "remainder_exact": round(remainder_raw, 2),
        "display_rounding": display_rounding,
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
        "delta_raw": delta,
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
        b["delta_exact"] = b["delta"]
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
    check = displayed + sum(0.0 for _ in ()) + remainder
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
         threshold=None, entities=None, driver=None, subject=None):
    """`subject` names what the exception is about — ("category", "Fragrance"),
    ("omni", "BOPIS"), ("channel", "ECOM") — so a consumer never has to parse
    it back out of the title. A headline that re-derives its subject from
    display text is one wording change away from silently pointing at the
    wrong thing."""
    return {
        "kind": kind, "severity": severity, "title": title, "detail": detail,
        "href": href, "rule": rule, "value": value, "threshold": threshold,
        "entities": sorted(entities or []), "driver": driver,
        "subject": subject,
    }


def build_exceptions(da, day: D, omni_mod, customer_mod, merch_mod,
                     **scope) -> List[dict]:
    """Memoised per (day, scope): thirteen persona views all filter the same
    fleet list, and rebuilding it thirteen times produced thirteen identical
    answers at thirteen times the cost."""
    key = (day, da._skey(scope))
    if getattr(da, "_exc_cache", None) is None:
        da._exc_cache = {}
    hit = da._exc_cache.get(key)
    if hit is None:
        hit = _build_exceptions_uncached(da, day, omni_mod, customer_mod,
                                         merch_mod, **scope)
        da._exc_cache[key] = hit
    return hit


def _build_exceptions_uncached(da, day: D, omni_mod, customer_mod, merch_mod,
                               **scope) -> List[dict]:
    """The day's calls to action, in one list, most urgent first.

    Ordering is severity then a stable key, never insertion order — two runs of
    the same day must produce the same list in the same order (NFR-2).
    """
    out: List[dict] = []
    out += _late_poster_exceptions(da, day, **scope)
    out += _two_day_negative_comp(da, day, **scope)
    out += _omni_exceptions(da, day, omni_mod, **scope)
    out += _category_exceptions(da, day, merch_mod, **scope)
    out += _ntf_exceptions(da, day, customer_mod, **scope)
    out += _conversion_exceptions(da, day, **scope)
    out += _upt_exceptions(da, day, **scope)
    out.sort(key=lambda e: (SEVERITY_ORDER.get(e["severity"], 9),
                            e["kind"], e["title"]))
    return out


def _late_poster_exceptions(da, day: D, **scope) -> List[dict]:
    out = []
    for lp in da.late_posters(day, **scope):
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
            "%s — %s %s vs LY" % (e["label"], e["metric"],
                                  fmt.pct(e["pct_vs_ly"])),
            "Recognized basis, %s vs the day-aligned LY — beyond the ±%s "
            "family threshold. Recognized and all-inclusive are separate "
            "series and are never mixed (BR-10)."
            % (fmt.pct(e["pct_vs_ly"]), fmt.pct_plain(e["threshold"], 0)),
            href="omni/%s/%s.html" % (e["family"], day.isoformat()),
            rule="BR-10", value=e["pct_vs_ly"], threshold=e["threshold"],
            subject=("omni", e["family"], e["good_is_up"])))
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
            rule="BR-11", value=e["gap_pts"], threshold=e["threshold_pts"],
            subject=("category", e["category"])))
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
            rule="BR-12", value=e["gap_pts"], threshold=e["threshold_pts"],
            subject=("channel", ch["channel"])))
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
        move = da.conversion_window_move(day, "WTD", entity_id=eid)
        # The title states no basis-point figure on purpose. The threshold is
        # measured in bp against the door's own baseline, but a bp number is a
        # conversion MOVEMENT, and BR-22 says a movement travels with its
        # drivers. The baseline comparison is stated as two levels instead, and
        # the only bp figure on the line is the vs-LY move, which carries them.
        out.append(_exc(
            "conversion", "adverse",
            "%s conversion below its own baseline" % e["name"],
            "WTD conversion %s against a trailing 4-week baseline of %s. "
            "Against last year, %s — so this is an execution move, not a "
            "footfall one, and it is coachable."
            % (fmt.pct_plain(cur["conversion"], 2), fmt.pct_plain(baseline, 2),
               move["annotation"]),
            href="store/%s/tree/%s.html" % (eid, day.isoformat()),
            rule="BR-15", value=bp, threshold=-thr_bp, entities=[eid],
            driver=move["annotation"]))
    out.sort(key=lambda x: (x["value"], x["entities"]))
    return out[:5]


def _upt_exceptions(da, day: D, **scope) -> List[dict]:
    """Units per transaction against the door's own trailing baseline, WTD.

    UPT is a lever, not a by-product: a door grows either by pulling more
    people through the door or by selling them more once they are in. The
    conversion exception covers the first. This covers the second, and it fires
    in BOTH directions — below baseline is a coaching signal, above it is an
    attach-rate winner the field should be copying rather than ignoring."""
    from flash.catalog import THRESHOLDS
    thr = THRESHOLDS["upt_vs_baseline_pct"]
    adverse, favourable = [], []
    for e in da._scope_entities(**scope):
        if e["channel"] != "STORE":
            continue
        eid = e["entity_id"]
        cur = da.basket_window(day, "WTD", entity_id=eid)
        if not cur["upt"]:
            continue
        base_un = base_tx = 0
        for wk in (1, 2, 3, 4):
            w = da.basket_window(day - dt.timedelta(days=7 * wk), "WTD",
                                 entity_id=eid)
            base_un += w["units"]
            base_tx += w["transactions"]
        if not base_tx:
            continue
        baseline = base_un / float(base_tx)
        move = cur["upt"] / baseline - 1.0
        if abs(move) < thr:
            continue
        rec = _exc(
            "upt", "adverse" if move < 0 else "favourable",
            "%s basket %s to %s units per transaction"
            % (e["name"], "thinning" if move < 0 else "building",
               fmt.ratio(cur["upt"])),
            "WTD UPT %s against a trailing 4-week baseline of %s (%s). AST %s "
            "on %s transactions. %s"
            % (fmt.ratio(cur["upt"]), fmt.ratio(baseline), fmt.pct(move),
               fmt.money_plain(cur["ast"]), fmt.count(cur["transactions"]),
               "Units per transaction is a lever — this door is losing attach."
               if move < 0 else
               "This door is growing sales through the basket, not the door "
               "count. Worth copying."),
            href="store/%s/tree/%s.html" % (eid, day.isoformat()),
            rule="BR-20", value=move, threshold=thr, entities=[eid])
        (adverse if move < 0 else favourable).append(rec)
    adverse.sort(key=lambda x: (x["value"], x["entities"]))
    favourable.sort(key=lambda x: (-x["value"], x["entities"]))
    return adverse[:5] + favourable[:3]


# =========================================================================
# Persona headline blocks — needs attention / worth celebrating
# =========================================================================
#
# RANKING RULE, stated once and applied to every item type:
#
#   items are ranked by the ABSOLUTE DOLLAR IMPACT of the move they name,
#   measured against the day-aligned LY, in the reporting currency, restricted
#   to the persona's own scope.
#
# One rule for doors, categories, omni families and customer signals, so a
# Region page and the Corporate page order the same two items the same way and
# neither has to explain itself. A door that has not posted is scored on the
# money its own trailing four same-weekday averages say is unaccounted for —
# the honest size of "we do not know", rather than zero.
#
# A celebration is a threshold-clearing favourable move, never editorial: it
# comes from the same machinery, the same thresholds and the same catalog
# calls as an exception. The only difference is the sign.

HEADLINE_MAX = 3


def _item(kind, key, label, severity, headline, move, driver, impact,
          href, rule, ty=None, ly=None, entities=None):
    return {
        "kind": kind, "key": key, "label": label, "severity": severity,
        "headline": headline, "move": move, "driver": driver,
        "impact": round(abs(impact or 0.0), 2),
        "impact_signed": round(impact or 0.0, 2),
        "href": href, "rule": rule, "ty": ty, "ly": ly,
        "entities": sorted(entities or ([key] if kind == "door" else [])),
    }


# What each persona can ACT on. Scope answers "whose numbers are these"; this
# answers "whose problem is this". A district manager cannot re-buy Fragrance
# or fix e-commerce acquisition, so putting either at the top of the Field
# Leadership page spends the one block they read on someone else's job.
ACTIONABLE_KINDS = {
    "corporate": None,                 # None = every kind
    "brand": None,
    "region": None,
    "affiliate": None,
    "field": ("door", "omni"),         # doors and door-level omni execution
}


def build_headlines(da, day: D, omni_mod, customer_mod, merch_mod,
                    kinds=None, **scope) -> Dict[str, object]:
    """The two blocks every persona landing opens with.

    Computed in the persona's own scope (BR-18: same arithmetic, different
    filter) and then narrowed to the item kinds that persona can act on."""
    # Scoped, not filtered. Filtering a fleet list gives a Canada page a
    # headline that says "Makeup comps −6.2%" over a move that reads +16.9%,
    # because the title came from the fleet and the figure came from Canada.
    # Building the exceptions in the persona's own scope makes that
    # impossible — the title and the move are the same computation.
    exceptions = build_exceptions(da, day, omni_mod, customer_mod, merch_mod,
                                  **scope)
    attention, celebration = [], []

    for e in exceptions:
        item = _item_from_exception(da, day, e, omni_mod, customer_mod,
                                    merch_mod, **scope)
        if item is None:
            continue
        (attention if e["severity"] in ("escalation", "adverse")
         else celebration).append(item)

    attention += _band_movers(da, day, "adverse", **scope)
    celebration += _band_movers(da, day, "favourable", **scope)
    attention += _plan_movers(da, day, "adverse", **scope)
    celebration += _plan_movers(da, day, "favourable", **scope)

    if kinds:
        attention = [i for i in attention if i["kind"] in kinds]
        celebration = [i for i in celebration if i["kind"] in kinds]
    attention = _rank(attention)
    claimed = set()
    for it in attention:
        claimed.update(it["entities"] or [it["key"]])
    celebration = _rank([c for c in celebration
                         if not (set(c["entities"] or [c["key"]]) & claimed)])
    return {
        "attention": attention[:HEADLINE_MAX],
        "celebration": celebration[:HEADLINE_MAX],
        "max_items": HEADLINE_MAX,
        "kinds": sorted(kinds) if kinds else None,
        "scope_rule": (
            "Narrowed to %s — the moves this view can act on. Scope answers "
            "whose numbers these are; this answers whose problem it is."
            % ", ".join(sorted(kinds)) if kinds else
            "Every kind of move in this view's scope."),
        "ranking_rule": (
            "Ranked by the absolute dollar impact of the move against the "
            "day-aligned LY, in %s, within this view's own scope. One rule for "
            "doors, categories, omni families and customer signals, so no two "
            "views order the same pair differently."
            % da.reporting_currency),
        "celebration_rule": (
            "A celebration is a threshold-clearing favourable move — the same "
            "machinery, thresholds and catalog calls as an exception, with the "
            "sign reversed. Nothing here is chosen editorially."),
    }


def _rank(items):
    """Highest dollar impact first; one item per entity; deterministic ties."""
    items = sorted(items, key=lambda i: (-i["impact"], i["kind"], str(i["key"])))
    out, seen = [], set()
    for it in items:
        keys = frozenset(it["entities"] or [it["key"]])
        if keys & seen:
            continue
        seen |= keys
        out.append(it)
    return out


def _door_pair(da, day: D, eid: str):
    """(TY, LY-aligned) net sales for a door, in reporting currency."""
    ly = da.ly_date(day)
    return da.net_sales_of(eid, day), da.net_sales_of(eid, ly)


def _door_driver(da, day: D, eid: str) -> str:
    """BR-22: the diagnosis, not just the symptom."""
    move = da.conversion_move(day, entity_id=eid)
    if not move["available"]:
        return move["annotation"]
    cb = da.comp_basket(day, entity_id=eid)
    if cb["upt_pct"] is None:
        return move["annotation"]
    return "%s; basket UPT %s, AST %s" % (move["annotation"],
                                          fmt.pct(cb["upt_pct"]),
                                          fmt.pct(cb["ast_pct"]))


def _item_from_exception(da, day: D, e, omni_mod, customer_mod, merch_mod,
                         **scope):
    kind = e["kind"]
    if kind in ("conversion", "upt", "two_day_comp"):
        eid = e["entities"][0]
        ty, ly = _door_pair(da, day, eid)
        if ty is None:
            return None
        delta = (ty - ly) if ly is not None else 0.0
        return _item(
            "door", eid, da.entity(eid)["name"], e["severity"], e["title"],
            "net sales %s vs LY %s (%s)" % (fmt.money_compact(ty),
                                            fmt.money_compact(ly),
                                            fmt.money_signed(delta)),
            e.get("driver") or _door_driver(da, day, eid), delta,
            "store/%s/%s.html" % (eid, day.isoformat()), e["rule"], ty, ly,
            [eid])
    if kind == "late_poster":
        eid = e["entities"][0]
        expected = da.trailing_same_weekday_avg(day, 4, entity_id=eid)
        return _item(
            "door", eid, da.entity(eid)["name"], e["severity"], e["title"],
            "nothing posted; a normal %s is about %s"
            % (fmt.WEEKDAYS[day.weekday()], fmt.money_compact(expected)),
            "missing, never zero — the door is out of every total and out of "
            "comp on both sides (BR-3)", expected or 0.0,
            "store/%s/%s.html" % (eid, day.isoformat()), e["rule"], None, None,
            [eid])
    if kind == "category":
        cat = e["subject"][1]
        c = merch_mod.category_day(da, day, **scope)
        row = next((r for r in c.get("categories", [])
                    if r["category"] == cat), None)
        if row is None:
            return None
        delta = row["comp_ty"] - row["comp_ly"]
        skus = merch_mod.sku_movers(da, day, n=3, category=cat, **scope)
        worst = skus["bottom"] if e["severity"] == "adverse" else skus["top"]
        return _item(
            "category", cat, cat, e["severity"], e["title"],
            "comp %s on %s against %s LY (%s)"
            % (fmt.pct(row["comp_pct"]), fmt.money_compact(row["comp_ty"]),
               fmt.money_compact(row["comp_ly"]), fmt.money_signed(delta)),
            "; ".join("%s %s" % (x["name"], fmt.money_signed(x["delta"]))
                      for x in worst[:3]) or "no SKU detail",
            delta, "category/%s/%s.html" % (_slug(cat), day.isoformat()),
            e["rule"], row["comp_ty"], row["comp_ly"], [])
    if kind == "omni":
        family = e["subject"][1]
        good_is_up = e["subject"][2] if len(e["subject"]) > 2 else True
        if family == "BORIS":
            f = omni_mod.boris_day(da, day, **scope)
            ty = f["recognized"]["returned_sales"]
            ly = f["ly_recognized"]["returned_sales"]
            r = f["recognized"]
            driver = ("%s returns on %s items; %s saved back into store sales "
                      "(%s save rate) and %s of shipping labels avoided"
                      % (fmt.count(r["orders"]), fmt.count(r["items"]),
                         fmt.money_compact(r["saved_sales"]),
                         fmt.pct_plain(r["save_rate"]),
                         fmt.money_compact(r["label_savings"])))
            move = ("%s of merchandise returned vs LY %s (%s)"
                    % (fmt.money_compact(ty), fmt.money_compact(ly),
                       fmt.money_signed(ty - ly)))
            impact = -(ty - ly)          # fewer returns is a gain
            return _item("omni", family,
                         omni_mod.FAMILY_LABEL.get(family, family),
                         e["severity"], e["title"], move, driver, impact,
                         "omni/%s/%s.html" % (family, day.isoformat()),
                         e["rule"], ty, ly, [])
        else:
            f = omni_mod.family_day(da, family, day, **scope)
            ty = f["recognized"]["sales"]
            ly = f["ly_recognized"]["sales"]
            driver = ("%s orders picked up or delivered on the day; %s "
                      "created, %s of them completing"
                      % (fmt.count(f["recognized"]["orders"]),
                         fmt.count(f["all_inclusive"]["orders"]),
                         fmt.pct_plain(f["completion_rate"])))
        return _item(
            "omni", family, omni_mod.FAMILY_LABEL.get(family, family),
            e["severity"], e["title"],
            "recognized %s vs LY %s (%s)"
            % (fmt.money_compact(ty), fmt.money_compact(ly),
               fmt.money_signed(ty - ly)),
            driver, ty - ly, "omni/%s/%s.html" % (family, day.isoformat()),
            e["rule"], ty, ly, [])
    if kind == "new_to_file":
        ly = da.ly_date(day)
        ch = e["subject"][1]
        merged = dict(scope)
        merged["channel"] = ch
        nb = customer_mod.new_customer_block(da, day, **merged)
        nl = customer_mod.new_customer_block(da, ly, **merged)
        b_ = customer_mod.buyers(da, day, **merged)
        return _item(
            "customer", ch, _channel_label(ch), e["severity"], e["title"],
            "new-customer sales %s vs LY %s (%s)"
            % (fmt.money_compact(nb["net_sales"]),
               fmt.money_compact(nl["net_sales"]),
               fmt.money_signed(nb["net_sales"] - nl["net_sales"])),
            "%s new of %s buyers (%s new to file)"
            % (fmt.count(b_["new_buyers"]), fmt.count(b_["total_buyers"]),
               fmt.pct_plain(b_["pct_new_to_file"])),
            nb["net_sales"] - nl["net_sales"],
            "customer/%s.html" % day.isoformat(), e["rule"],
            nb["net_sales"], nl["net_sales"], [])
    return None


def _band_movers(da, day: D, direction: str, **scope) -> List[dict]:
    """Doors clearing the ±5% favourable/unfavourable band on comp — the same
    band the ops tables key, so a headline and a triangle never disagree."""
    from flash.catalog import THRESHOLDS
    band = THRESHOLDS["fav_unfav_band"]
    out = []
    for c in da.contribution_to_comp_gap(day, **scope):
        if c["channel"] != "STORE" or c["pct"] is None:
            continue
        if direction == "adverse" and c["pct"] > -band:
            continue
        if direction == "favourable" and c["pct"] < band:
            continue
        out.append(_item(
            "door", c["entity_id"], c["name"], direction,
            "%s comp %s" % (c["name"], fmt.pct(c["pct"])),
            "net sales %s vs LY %s (%s)"
            % (fmt.money_compact(c["ty"]), fmt.money_compact(c["ly"]),
               fmt.money_signed(c["delta"])),
            _door_driver(da, day, c["entity_id"]), c["delta"],
            "store/%s/%s.html" % (c["entity_id"], day.isoformat()),
            "BR-6", c["ty"], c["ly"], [c["entity_id"]]))
    return out


def _plan_movers(da, day: D, direction: str, **scope) -> List[dict]:
    """Doors beating or missing their DAY-grain plan by more than the same
    band. Week-planned and no-plan doors are not scored here, because they have
    no day plan to beat and inventing one is what BR-19 forbids."""
    from flash.catalog import THRESHOLDS
    band = THRESHOLDS["fav_unfav_band"]
    out = []
    for e in da._scope_entities(**scope):
        eid = e["entity_id"]
        if e["channel"] != "STORE" or da.plan_grain_of(eid) != "DAY":
            continue
        pair = da.plan_pair(day, entity_id=eid)
        if not pair["plan"] or not pair["actual"]:
            continue
        att = pair["actual"] / pair["plan"]
        gap = pair["actual"] - pair["plan"]
        if direction == "adverse" and att > 1.0 - band:
            continue
        if direction == "favourable" and att < 1.0 + band:
            continue
        out.append(_item(
            "door", eid, e["name"], direction,
            "%s %s plan at %s" % (e["name"],
                                  "missed" if gap < 0 else "beat",
                                  fmt.pct_plain(att)),
            "actual %s against a day plan of %s (%s)"
            % (fmt.money_compact(pair["actual"]),
               fmt.money_compact(pair["plan"]), fmt.money_signed(gap)),
            _door_driver(da, day, eid), gap,
            "store/%s/%s.html" % (eid, day.isoformat()), "BR-19",
            pair["actual"], pair["plan"], [eid]))
    return out


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
