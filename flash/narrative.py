# -*- coding: utf-8 -*-
"""The narrative paragraph — deterministic template composition, no LLM.

Owner default (PRD §11): factual, at most three sentences, numbers inline,
reads like the focus panel rather than like marketing. So the composition is
mechanical and the vocabulary is small. Three sentences, in a fixed order:

  1. What happened — the headline, with the LY date it was measured against.
  2. Why — the largest adverse mover and the bright spot, with receipts.
  3. What to be careful about — the single most material disclosure.

Sentence 3 is dropped when there is nothing to disclose, so a clean day reads
in two sentences rather than padding to three. A sentence is never emitted
without a number in it; adjectives do not survive here.

No `now()`, no randomness, no dict iteration order dependence (NFR-2). Input is
the computed object; the display strings come from `compute._display`, so the
narrative cannot round a number differently from the table above it (BR-5).
"""

from __future__ import annotations

from typing import Optional

from flash import fmt


def compose(obj) -> str:
    """Return the narrative for a computed flash object (call after display
    strings would be built — this uses raw values and formats via `fmt`)."""
    parts = [_headline_sentence(obj)]
    why = _why_sentence(obj)
    if why:
        parts.append(why)
    care = _disclosure_sentence(obj)
    if care:
        parts.append(care)
    return " ".join(parts)


def _headline_sentence(obj) -> str:
    h = obj["headline"]
    c = obj["comp"]
    basis = ("the same holiday last year" if c["override_in_effect"]
             else "the day-aligned LY")
    s = ("%s net sales were %s, comp %s against %s (%s), plan attainment %s"
         % (fmt.day_short(obj["date"]),
            fmt.money_compact(h["net_sales"]),
            fmt.pct(h["comp_pct"]),
            basis,
            fmt.day_short_year(c["ly_date"]),
            fmt.pct_plain(h["plan_attainment"])))
    if c["override_in_effect"]:
        s += (", versus %s on the raw week-aligned comparison"
              % fmt.pct(c["week_aligned"]["pct"]))
    return s + "."


def _why_sentence(obj) -> Optional[str]:
    f = obj["focus"]
    adverse = [e for e in f["entries"] if e["adverse"]]
    bright = next((e for e in f["entries"] if not e["adverse"]), None)
    if not adverse and not bright:
        return None
    clauses = []
    if adverse:
        top = adverse[0]
        noun = " region" if top["kind"] == "region" else ""
        verb = "took %s off the comp" if top["delta"] < 0 else "carried %s of the move"
        clause = "%s%s %s (%s)" % (
            top["label"], noun, verb % fmt.money_compact(abs(top["delta"])),
            fmt.pct(top["pct"]))
        if top["receipts"]:
            names = " and ".join(r["name"] for r in top["receipts"])
            share = sum(abs(r["delta"]) for r in top["receipts"]) / (abs(top["delta"]) or 1.0)
            clause += ", %s of it from %s" % (fmt.pct_plain(share, 0), names)
        clauses.append(clause)
        if len(adverse) > 1:
            clauses.append("%s cost a further %s"
                           % (adverse[1]["label"],
                              fmt.money_compact(abs(adverse[1]["delta"]))))
    if bright:
        clauses.append("%s was the bright spot at %s (%s)"
                       % (bright["label"], fmt.money_signed(bright["delta"]),
                          fmt.pct(bright["pct"])))
    body = "; ".join(clauses)
    return "%s%s." % (body[0].upper() + body[1:], "")


def _disclosure_sentence(obj) -> Optional[str]:
    """One sentence for the most material caveat, chosen by a fixed priority so
    the same day always yields the same sentence."""
    cm = obj["completeness"]
    ec = obj["ecom"]
    if cm["escalating"]:
        lp = cm["escalating"][0]
        others = len(cm["missing"]) - 1
        tail = (" and %d other store did not post" % others if others == 1
                else (" and %d other stores did not post" % others if others > 1 else ""))
        return ("%s has now missed %d consecutive days%s, so %s of %s stores are "
                "in today's totals and the rest are missing, not zero."
                % (lp["name"], lp["consecutive_days"], tail,
                   cm["reported"], cm["expected"]))
    if cm["missing"]:
        return ("%s did not post, so today's totals cover %s of %s stores and "
                "the gap is disclosed rather than zero-filled."
                % (", ".join(cm["missing_names"]), cm["reported"], cm["expected"]))
    if ec and not ec.get("matured", True) and ec.get("shipped_comp_pct") is not None \
            and ec.get("demand_comp_pct") is not None \
            and (ec["demand_comp_pct"] < 0) != (ec["shipped_comp_pct"] < 0):
        return ("E-commerce is shown on demand at %s and has not matured — "
                "shipped currently reads %s, and the archive will show both."
                % (fmt.pct(ec["demand_comp_pct"]), fmt.pct(ec["shipped_comp_pct"])))
    if obj["comp"]["restated_53_week"]:
        return ("Last year's weeks are shifted to the NRF restated calendar for "
                "this comparison (53-week year).")
    return None
