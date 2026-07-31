# -*- coding: utf-8 -*-
"""CLI entry point for the Lumière Ops Flash.

  --date YYYY-MM-DD    Render one day. Defaults to the latest complete day
                       (2026-07-23 — from the data, never now()). If the day is
                       already archived it is rendered FROM the archive (BR-7:
                       the site shows what was sent, not a fresh recompute).
  --all                Regenerate everything: the 60-day archive ending
                       2026-07-23, the tiered site, the morning digests, the
                       door extracts and the planted restatement.
  --check              Build the DB, assert every storyline, run the whole test
                       suite and verify a deterministic rebuild. Zero manual
                       steps.

Archive tiering (owner decision, 2026-07-31): all 60 days get a flash page,
a morning digest and their restatement history. The last 14 days additionally
get the full drill-down — persona landings, districts, doors, hourly views,
KPI trees, category and SKU pages, omni panels, rank tables and extracts. All
60 days are in the database at the same depth; only page generation is tiered.

Determinism (NFR-2): nothing here reads the wall clock. Dates come from
`flash/archive.py`'s fixed anchors and timestamps from the flash's own `as_of`.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import shutil
import sqlite3
import sys
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import seed                                              # noqa: E402
from flash import archive, catalog, compute               # noqa: E402
from flash import render_email, render_site               # noqa: E402
from flash.calendar import NRFCalendar                    # noqa: E402

D = dt.date
RENDER_DIR = os.path.join(HERE, "render")
SITE_DIR = os.path.join(RENDER_DIR, "site")
DB_PATH = os.path.join(HERE, "ops.db")
REGEN_BUDGET_S = 60.0


def full_depth_dates():
    """The last FULL_DEPTH_DAYS of the archive — the drill-down window."""
    end = archive.LATEST_COMPLETE
    return [end - dt.timedelta(days=i)
            for i in range(archive.FULL_DEPTH_DAYS - 1, -1, -1)]


# -- the storyline index (PRD §7) -------------------------------------------

def storyline_index():
    """One list, two consumers: the archive index page and README.md. If the
    two ever disagreed about where a storyline is visible, the README would be
    the thing that rots — so neither owns it."""
    a = archive.LATEST_COMPLETE.isoformat()
    return [
        {"n": 1, "rule": "PRD §7.1", "title": "BOPIS upsell champion",
         "note": "Coral Bay Galleria attaches an upsell to roughly half its "
                 "pickups against a fleet rate near one in six. The upsell "
                 "leaderboard on the BOPIS panel ranks it first.",
         "where": "omni/BOPIS/%s.html — upsell leaderboard, trailing 14 days" % a,
         "href": "omni/BOPIS/%s.html" % a},
        {"n": 2, "rule": "BR-10", "title": "BOPIS execution gap — Southwest",
         "note": "Southwest's pickup rate has run roughly 15 points below the "
                 "fleet for two weeks. Recognized and all-inclusive diverge "
                 "visibly, which is the whole point of carrying both bases.",
         "where": "omni/BOPIS/%s.html — pickup execution by region" % a,
         "href": "omni/BOPIS/%s.html" % a},
        {"n": 3, "rule": "BR-14", "title": "BORIS save story — Copper Row",
         "note": "High return volume turned into measurable saved sales: the "
                 "door leads the save leaderboard on both rate and dollars, "
                 "with the shipping-label constant disclosed beside it.",
         "where": "omni/BORIS/%s.html — save leaderboard" % a,
         "href": "omni/BORIS/%s.html" % a},
        {"n": 4, "rule": "BR-11", "title": "Fragrance category slide",
         "note": "Fragrance has comped negative for 14 consecutive days, "
                 "driven by three identifiable SKUs. The category exception "
                 "fires on the day flash and drills straight to them.",
         "where": "category/fragrance/%s.html — the SKU table, bottom rows" % a,
         "href": "category/fragrance/%s.html" % a},
        {"n": 5, "rule": "PRD §5 #29", "title": "SKU breakout — a new Skincare line",
         "note": "A Skincare SKU launched fewer than 90 days ago sits in the "
                 "top movers on most days of the window; its own page shows "
                 "the daily series behind that.",
         "where": "sku/%s.html — the daily series" % seed.BREAKOUT_SKU,
         "href": "sku/%s.html" % seed.BREAKOUT_SKU},
        {"n": 6, "rule": "BR-12", "title": "New-to-file dip — e-commerce",
         "note": "New-buyer share on the e-commerce channel fell below its own "
                 "trailing baseline by more than five points this week. The "
                 "CRM flag fires on the customer panel.",
         "where": "customer/%s.html — the CRM flag and the channel table" % a,
         "href": "customer/%s.html" % a},
        {"n": 7, "rule": "BR-9", "title": "Omni invariance demo day",
         "note": "A heavy-BOPIS day where the flash prints the headline with "
                 "the omni layer on and with it off, side by side. They are "
                 "the same number, because omni attributes rather than adds.",
         "where": "day/%s.html — the green omni-invariance band"
                  % seed.OMNI_HEAVY_DAY.isoformat(),
         "href": "day/%s.html" % seed.OMNI_HEAVY_DAY.isoformat()},
        {"n": 8, "rule": "BR-10", "title": "Click & Reserve conversion win",
         "note": "C&R conversion steps up sharply after a planted date and "
                 "holds. Visible as the family's completion rate across the "
                 "archive.",
         "where": "omni/CR/%s.html — completion rate on the created cohort" % a,
         "href": "omni/CR/%s.html" % a},
        {"n": 9, "rule": "BR-15", "title": "Traffic up, conversion down",
         "note": "Riverbend Square has taken more traffic and converted less "
                 "of it for two weeks — the classic staffing signal. The "
                 "conversion exception fires and the Field Leadership view "
                 "surfaces the door.",
         "where": "store/%s/%s.html — the KPI row and the windows table"
                  % (seed.CONV_STORE, a),
         "href": "store/%s/%s.html" % (seed.CONV_STORE, a)},
        {"n": 10, "rule": "BR-17", "title": "Lost midday peak",
         "note": "Desert Bloom Galleria's midday hours collapsed against the "
                 "door's own trailing hourly curve on one day, with the volume "
                 "pushed into the evening.",
         "where": "store/%s/hourly/%s.html — Δ share against its own baseline"
                  % (seed.HOURLY_STORE, seed.HOURLY_DAY.isoformat()),
         "href": "store/%s/hourly/%s.html" % (seed.HOURLY_STORE,
                                              seed.HOURLY_DAY.isoformat())},
        {"n": 11, "rule": "BR-18", "title": "Brand divergence inside one region",
         "note": "In the West, Lumière comps positive while Atelier Noir comps "
                 "negative on the same day. Corporate, Brand and Region views "
                 "all show it, and all show the same numbers.",
         "where": "region/west/%s.html — the brand rollup" % a,
         "href": "region/west/%s.html" % a},
        {"n": 12, "rule": "BR-16", "title": "Canada beats plan, smaller in USD",
         "note": "The Canadian affiliate beats its plan in CAD and contributes "
                 "less in USD, at the seeded fixed rate, disclosed wherever a "
                 "converted figure appears.",
         "where": "affiliate/CA/%s.html — the currency band and the KPI row" % a,
         "href": "affiliate/CA/%s.html" % a},
        {"n": 13, "rule": "BR-19", "title": "Three plan grains on one page",
         "note": "The same trading day reads three ways: day-planned Lumière "
                 "against the day plan, week-planned Atelier Noir week-to-date "
                 "against the weekly plan, no-plan Botanica showing actuals "
                 "only — never a fabricated 100%.",
         "where": "day/%s.html — 'Plan, at each brand's own grain'" % a,
         "href": "day/%s.html" % a},
        {"n": 14, "rule": "BR-20", "title": "The tree explains the conversion story",
         "note": "For the traffic-up/conversion-down door, the KPI tree shows a "
                 "positive traffic contribution overwhelmed by a negative "
                 "conversion contribution, composing exactly to the gap. The "
                 "what-if calculator answers 'what conversion matches LY?'.",
         "where": "store/%s/tree/%s.html — contributions and the calculator"
                  % (seed.CONV_STORE, a),
         "href": "store/%s/tree/%s.html" % (seed.CONV_STORE, a)},
        {"n": 22, "rule": "BR-20", "title": "Attach-rate winner — the basket lever",
         "note": "The mirror image of storyline 9. Harborlight Galleria grew "
                 "sales with traffic flat and conversion steady, by selling "
                 "more units per transaction. The UPT exception fires "
                 "favourably, the door leads the UPT movers table, and its KPI "
                 "tree shows AST carrying a positive gap with UPT — not AUS — "
                 "underneath it.",
         "where": "store/%s/tree/%s.html — the AST split, and rank/upt/%s.html"
                  % (seed.ATTACH_STORE, a, a),
         "href": "store/%s/tree/%s.html" % (seed.ATTACH_STORE, a)},
        {"n": 15, "rule": "BR-7", "title": "Restatement — version 2",
         "note": "2026-07-20 was re-issued on the settled basis with a reason "
                 "string. Version 1 is preserved byte for byte at its own URL.",
         "where": "day/%s-history.html — both versions and the reason"
                  % archive.RESTATE_DATE.isoformat(),
         "href": "day/%s-history.html" % archive.RESTATE_DATE.isoformat()},
        {"n": 16, "rule": "BR-1", "title": "Holiday shift — July 4",
         "note": "Week-aligned, holiday-aligned and same-calendar-date comps "
                 "all differ. The adjusted figure leads and all three are "
                 "stated.",
         "where": "day/2026-07-04.html — the gold banner and the disclosures",
         "href": "day/2026-07-04.html"},
        {"n": 17, "rule": "BR-3", "title": "Late posters, one escalating",
         "note": "Santa Rosa Plaza missed two days running and escalates; "
                 "Granite Hill Commons missed one. Neither is zero-filled.",
         "where": "day/%s.html — the red completeness banner" % a,
         "href": "day/%s.html" % a},
        {"n": 18, "rule": "BR-2", "title": "Remodel closure and a new door",
         "note": "Lakeview Arcade is dark for remodel and out of comp on both "
                 "sides; Silver Mesa Mall is in total sales but not in comp. "
                 "Both exclusions are disclosed by name.",
         "where": "day/%s.html — disclosures, the two BR-2 lines" % a,
         "href": "day/%s.html" % a},
        {"n": 19, "rule": "BR-4", "title": "E-commerce maturation",
         "note": "Demand read soft on the send morning and the shipped series "
                 "settled positive. The flash is unchanged; the settled view "
                 "is the restatement.",
         "where": "day/%s-history.html — version 1 against version 2"
                  % archive.RESTATE_DATE.isoformat(),
         "href": "day/%s-history.html" % archive.RESTATE_DATE.isoformat()},
        {"n": 20, "rule": "BR-6", "title": "Soft Southeast region",
         "note": "Two Southeast doors have run soft for two weeks. The focus "
                 "panel names them and the named contributions plus 'all "
                 "other' equal the headline gap to the cent.",
         "where": "day/%s.html — the focus panel" % a,
         "href": "day/%s.html" % a},
        {"n": 21, "rule": "BR-15", "title": "A door with no traffic posted",
         "note": "Bluegrass Commons posted sales but no traffic on two days. "
                 "Its conversion is shown as unavailable, it is excluded from "
                 "the fleet rate on both sides, and it is listed under the "
                 "conversion rank rather than sorted last as zero.",
         "where": "rank/conversion/%s.html — the 'not ranked' table" % a,
         "href": "rank/conversion/%s.html" % a},
    ]


# -- helpers ---------------------------------------------------------------

def _db(rebuild_if_missing: bool = True):
    if not os.path.isfile(DB_PATH):
        if not rebuild_if_missing:
            raise SystemExit("ops.db is missing. Run: python3 seed.py")
        print("ops.db not found — building it from the seed first ...")
        conn, _e, _p, _s = seed.build(DB_PATH)
        return conn
    return sqlite3.connect(DB_PATH)


def _reset_render():
    """A full regeneration starts from an empty tree. Rendering over the top of
    an old run leaves orphans behind, and an archive with a stale page in it is
    exactly the quiet inconsistency this product exists to remove."""
    if os.path.isdir(SITE_DIR):
        shutil.rmtree(SITE_DIR)


def _write_digest(obj, stem: str) -> str:
    return render_site.write(
        os.path.join(SITE_DIR, "email", "%s.html" % stem),
        render_email.render(obj))


def _archive_days(conn):
    rows = conn.execute(
        "SELECT DISTINCT date FROM flash_archive ORDER BY date").fetchall()
    out = []
    for (iso,) in rows:
        out.append({"date": iso, "versions": archive.versions(conn, D.fromisoformat(iso))})
    return out


def _build_site(conn):
    days = _archive_days(conn)
    full_objs = [e["versions"][0]["obj"] for e in days
                 if e["versions"][0]["obj"].get("depth") == "full"]
    sku_index = render_site.build_sku_index(full_objs)
    return render_site.build_site(
        SITE_DIR, days, storylines=storyline_index(),
        today=archive.TODAY.isoformat(),
        anchor=archive.LATEST_COMPLETE.isoformat(), sku_index=sku_index)


def _count_files(root) -> int:
    n = 0
    for _r, _d, files in os.walk(root):
        n += len(files)
    return n


def _tree_size(root) -> int:
    total = 0
    for r, _d, files in os.walk(root):
        for f in files:
            total += os.path.getsize(os.path.join(r, f))
    return total


# -- --all ------------------------------------------------------------------

def cmd_all() -> int:
    t0 = time.time()
    conn = _db()
    cal = NRFCalendar()
    da = catalog.DataAccess(conn, cal)
    da_settled = catalog.DataAccess(conn, cal, ecom_basis="settled")

    dates = archive.archive_dates()
    deep = set(d.isoformat() for d in full_depth_dates())
    print("[1/4] Computing %d days, %s .. %s (%d at full drill-down depth)"
          % (len(dates), dates[0], dates[-1], len(deep)))
    _reset_render()
    archive.clear(conn)

    anchor = archive.LATEST_COMPLETE.isoformat()
    for day in dates:
        depth = "full" if day.isoformat() in deep else "summary"
        obj = compute.build_flash(da, day, depth=depth)
        archive.write_version(conn, obj)
        render_site.tag_depth(obj, deep, anchor)
        _write_digest(obj, day.isoformat())
    print("      %d objects computed, archived and digested" % len(dates))

    print("[2/4] Issuing the planted restatement (BR-7) ...")
    rd = archive.RESTATE_DATE
    v1 = archive.versions(conn, rd)[0]["obj"]
    rd_depth = "full" if rd.isoformat() in deep else "summary"
    draft = compute.build_flash(da_settled, rd, version=2, depth=rd_depth)
    reason = archive.restatement_reason(v1, draft)
    v2 = compute.build_flash(da_settled, rd, version=2, reason=reason,
                             depth=rd_depth)
    archive.restate(conn, v2, reason)
    render_site.tag_depth(v2, deep, anchor)
    _write_digest(v2, "%s-v2" % rd.isoformat())
    print("      %s version 2 written; version 1 untouched (%s -> %s)"
          % (rd, v1["display"]["net_sales"], v2["display"]["net_sales"]))

    conn.commit()
    print("[3/4] Rendering the site ...")
    paths = _build_site(conn)
    conn.close()
    print("      %d site files written" % len(paths))

    print("[4/4] Checking the budget ...")
    files = _count_files(RENDER_DIR)
    size = _tree_size(RENDER_DIR)
    elapsed = time.time() - t0
    biggest = _biggest_page()
    print("\nDone in %.2fs — %d files, %.1f MB under render/ (budget %.0fs)."
          % (elapsed, files, size / 1024.0 / 1024.0, REGEN_BUDGET_S))
    print("Largest page: %s (%.0f KB; budget 150 KB)" % biggest)
    print("Browse it:  python3 app.py   then open http://127.0.0.1:8765/")
    rc = 0
    if elapsed > REGEN_BUDGET_S:
        print("NFR FAILED: full regeneration took %.1fs, budget is %.0fs."
              % (elapsed, REGEN_BUDGET_S))
        rc = 1
    if biggest[1] > 150:
        print("NFR FAILED: %s is %.0f KB, over the 150 KB page budget." % biggest)
        rc = 1
    return rc


def _biggest_page():
    worst = ("", 0.0)
    for r, _d, files in os.walk(SITE_DIR):
        for f in files:
            if not f.endswith(".html"):
                continue
            kb = os.path.getsize(os.path.join(r, f)) / 1024.0
            if kb > worst[1]:
                worst = (os.path.relpath(os.path.join(r, f), SITE_DIR), kb)
    return worst


# -- --date -----------------------------------------------------------------

def cmd_date(iso: str) -> int:
    day = archive.LATEST_COMPLETE if not iso else D.fromisoformat(iso)
    conn = _db()
    da = catalog.DataAccess(conn, NRFCalendar())
    deep = set(d.isoformat() for d in full_depth_dates())

    existing = archive.versions(conn, day)
    if existing:
        print("%s is already in the archive (%d version%s) — rendering what was "
              "sent, not a recompute (BR-7)."
              % (day, len(existing), "" if len(existing) == 1 else "s"))
        objs = [(v["obj"], day.isoformat() if v["obj"]["version"] == 1
                 else "%s-v%d" % (day.isoformat(), v["obj"]["version"]))
                for v in existing]
    else:
        depth = "full" if day.isoformat() in deep else "summary"
        obj = compute.build_flash(da, day, depth=depth)
        archive.write_version(conn, obj)
        conn.commit()
        print("%s was not in the archive — computed at %s depth and archived as "
              "version 1." % (day, depth))
        objs = [(obj, day.isoformat())]

    for obj, stem in objs:
        render_site.tag_depth(obj, deep, archive.LATEST_COMPLETE.isoformat())
        _write_digest(obj, stem)
        print("  %s  net %s · comp %s · plan %s · %d exceptions"
              % (obj["display"]["date_short"], obj["display"]["net_sales"],
                 obj["display"]["comp_pct"], obj["display"]["plan_attainment"],
                 len(obj["exceptions"])))
        print("  subject: %s" % obj["subject"])

    written = _build_site(conn)
    conn.close()
    print("  wrote %d site files, including render/site/day/%s.html"
          % (len(written), day.isoformat()))
    return 0


# -- --check ----------------------------------------------------------------

def cmd_check() -> int:
    print("[1/4] Building ops.db from schema + seed ...")
    conn, _e, _p, _s = seed.build()
    cal = NRFCalendar()

    print("[2/4] Asserting the planted storylines manifest in the data ...")
    A = seed.assert_all(conn, cal)
    conn.close()
    print("      ok — %d seed assertions passed" % A.count())

    print("[3/4] Running the test suite ...")
    loader = unittest.TestLoader()
    suite = loader.discover(os.path.join(HERE, "tests"), pattern="test_*.py",
                            top_level_dir=HERE)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful():
        print("CHECK FAILED: the test suite did not pass")
        return 1

    print("[4/4] Verifying a deterministic rebuild (NFR-2) ...")
    if not _deterministic():
        print("CHECK FAILED: the rebuild was not byte-identical")
        return 1
    print("      ok — the rebuild is byte-identical")
    print("\nALL CHECKS PASSED.")
    return 0


def _deterministic() -> bool:
    def content_hash(path):
        seed.build(path)
        c = sqlite3.connect(path)
        h = hashlib.sha256()
        for line in c.iterdump():
            h.update(line.encode("utf-8"))
        c.close()
        os.remove(path)
        return h.hexdigest()

    return content_hash(os.path.join(HERE, "_det1.db")) == \
        content_hash(os.path.join(HERE, "_det2.db"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Lumière Ops Flash")
    ap.add_argument("--check", action="store_true",
                    help="build, assert storylines, run tests, verify determinism")
    ap.add_argument("--date", nargs="?", const="", default=None,
                    help="flash date YYYY-MM-DD (default: the latest complete day)")
    ap.add_argument("--all", action="store_true",
                    help="regenerate the 60-day archive, the tiered site and "
                         "the morning digests")
    args = ap.parse_args(argv)

    if args.check:
        return cmd_check()
    if args.all:
        return cmd_all()
    if args.date is not None:
        return cmd_date(args.date)
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
