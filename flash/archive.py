# -*- coding: utf-8 -*-
"""The flash archive — BR-7, immutability and restatement.

The rule is one sentence: *a flash is immutable once written; a correction is a
new version, never an edit.* It is short because it is the whole credibility of
the product. The moment yesterday's flash can change under the reader, every
flash becomes provisional and the archive stops being evidence.

So `write_version` refuses to overwrite. It does not "upsert", it does not
`INSERT OR REPLACE`, and it does not take a force flag — those are the three
shapes this defect arrives in. A correction calls `restate()`, which reads the
highest existing version, writes version+1 with a reason string, and leaves
version 1 exactly as it was sent.

`created_at` is derived from the flash's own dates (send morning at 06:30 in
the single business timezone, PRD §11), never `now()` — an archive whose
timestamps move on every rebuild cannot be diffed, and NFR-2 requires the
reviewer to diff it.
"""

from __future__ import annotations

import datetime as dt
import json
from typing import Dict, List, Optional

D = dt.date

SEND_TIME = "T06:30:00-04:00"      # America/New_York, the single business TZ
ARCHIVE_DAYS = 60                  # PRD §11: 60 generated days
LATEST_COMPLETE = D(2026, 7, 23)   # never now() (NFR-2)
TODAY = D(2026, 7, 24)

# --- storyline 8: the planted restatement (PRD §7) ------------------------
RESTATE_DATE = D(2026, 7, 20)
RESTATE_DISCOVERED = D(2026, 7, 23)   # the day the fulfillment file closed


class ImmutabilityError(AssertionError):
    """BR-7 violation: something tried to rewrite a sent flash."""


def archive_dates(end: D = LATEST_COMPLETE, days: int = ARCHIVE_DAYS) -> List[D]:
    """The archive window: the `days` days ending on `end`, oldest first."""
    return [end - dt.timedelta(days=i) for i in range(days - 1, -1, -1)]


def created_at(obj) -> str:
    """The send timestamp, derived from the object's own as_of date."""
    return obj["as_of"] + SEND_TIME


def serialize(obj) -> str:
    """Stable JSON. sort_keys is not cosmetic — without it a dict rebuilt in a
    different insertion order produces a different byte string and the
    determinism check fails for a reason that has nothing to do with the data."""
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=1)


def versions(conn, day: D) -> List[Dict[str, object]]:
    rows = conn.execute(
        "SELECT version, computed_json, reason, created_at FROM flash_archive "
        "WHERE date=? ORDER BY version", (day.isoformat(),)).fetchall()
    return [{"version": v, "obj": json.loads(j), "reason": r, "created_at": c}
            for v, j, r, c in rows]


def latest_version_no(conn, day: D) -> int:
    row = conn.execute("SELECT MAX(version) FROM flash_archive WHERE date=?",
                       (day.isoformat(),)).fetchone()
    return row[0] or 0


def write_version(conn, obj, reason: Optional[str] = None) -> int:
    """Append one immutable archive row. Refuses to overwrite (BR-7)."""
    day = obj["date"]
    version = obj["version"]
    existing = conn.execute(
        "SELECT created_at FROM flash_archive WHERE date=? AND version=?",
        (day, version)).fetchone()
    if existing:
        raise ImmutabilityError(
            "BR-7 VIOLATED: flash %s version %d already exists in the archive "
            "(written %s) and a second write was attempted.\n"
            "  A flash is immutable once sent. If this figure needs to change, "
            "call archive.restate(conn, da, date, reason) — it appends version "
            "%d and leaves version %d exactly as it was sent.\n"
            "  If you are regenerating the archive from scratch, clear the "
            "table first (run_flash.py --all does this) rather than writing "
            "over individual rows."
            % (day, version, existing[0], version + 1, version))
    conn.execute(
        "INSERT INTO flash_archive (date, version, computed_json, reason, "
        "created_at) VALUES (?,?,?,?,?)",
        (day, version, serialize(obj), reason, created_at(obj)))
    return version


def restate(conn, obj_v_next, reason: str) -> int:
    """Write a restatement. The prior versions are read, never touched."""
    day = D.fromisoformat(obj_v_next["date"])
    prior = latest_version_no(conn, day)
    if prior == 0:
        raise ImmutabilityError(
            "BR-7: cannot restate %s — no version 1 exists in the archive yet. "
            "A restatement is version+1 of something that was actually sent; "
            "generate the archive before restating it." % day)
    if obj_v_next["version"] != prior + 1:
        raise ImmutabilityError(
            "BR-7: restatement of %s is numbered version %d but the archive is "
            "at version %d. A restatement must be exactly the next version — "
            "gaps and reuses both break the audit trail."
            % (day, obj_v_next["version"], prior))
    return write_version(conn, obj_v_next, reason=reason)


def restatement_reason(v1, v2) -> str:
    """The rendered reason string (BR-7 requires one, and a reason that does
    not carry the numbers is not a reason — it is an apology)."""
    from flash import fmt
    return (
        "E-commerce settled late. The flash sent on the morning of %s carried "
        "%s on the day-of DEMAND basis (orders placed), which is all the "
        "fulfillment file could support at send time. The file closed on %s "
        "and the SHIPPED figures for %s came in at %s. This version restates "
        "the day on the settled basis: net sales %s → %s and comp %s → %s. "
        "Stores are unchanged. Version 1 is preserved exactly as sent."
        % (fmt.day_long(v1["as_of"]),
           fmt.money_compact(v1["ecom"]["demand"]),
           fmt.day_long(RESTATE_DISCOVERED.isoformat()),
           fmt.day_short_year(v1["date"]),
           fmt.money_compact(v1["ecom"]["shipped"]),
           fmt.money_compact(v1["headline"]["net_sales"]),
           fmt.money_compact(v2["headline"]["net_sales"]),
           fmt.pct(v1["headline"]["comp_pct"]),
           fmt.pct(v2["headline"]["comp_pct"])))


def clear(conn) -> None:
    """Full regeneration wipes the table — the only sanctioned way to rewrite
    an archive row is to rebuild the whole archive from the seed."""
    conn.execute("DELETE FROM flash_archive")
