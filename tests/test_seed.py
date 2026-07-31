# -*- coding: utf-8 -*-
"""Seed tests — determinism, and the planted storylines the flash must surface.

The storyline assertions themselves live in `seed.assert_all()` so a plain
`python3 seed.py` refuses to produce a database the acceptance material is
missing from. These tests prove that machinery runs, that it is not vacuous,
and that regeneration is byte-identical.

Run: python3 -m unittest tests.test_seed
"""
import datetime as dt
import hashlib
import os
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import dbfixture                      # noqa: E402
import seed                                      # noqa: E402
from flash import catalog, customer, merch, omni  # noqa: E402

D = dt.date
ANCHOR = seed.LATEST_COMPLETE


def _dump_hash(path):
    h = hashlib.sha256()
    conn = sqlite3.connect(path)
    try:
        for line in conn.iterdump():
            h.update(line.encode("utf-8"))
    finally:
        conn.close()
    return h.hexdigest()


class DeterminismCase(unittest.TestCase):
    """NFR-2: same source -> byte-identical database, twice, in two places."""

    def test_two_builds_are_byte_identical(self):
        paths, hashes, file_hashes = [], [], []
        for _ in range(2):
            fd, p = tempfile.mkstemp(suffix=".ops.db")
            os.close(fd)
            paths.append(p)
            conn, _e, _pr, _s = seed.build(p)
            conn.close()
            hashes.append(_dump_hash(p))
            with open(p, "rb") as fh:
                file_hashes.append(hashlib.sha256(fh.read()).hexdigest())
        for p in paths:
            os.remove(p)
        self.assertEqual(hashes[0], hashes[1], "SQL dump differs between builds")
        self.assertEqual(file_hashes[0], file_hashes[1],
                         "database file differs between builds")

    def test_no_wall_clock_calls_in_the_seed_source(self):
        """NFR-2 enforced against the source, not just the output: a single
        now() would make regeneration non-reproducible on the next day rather
        than on the next run, which no output check would catch today."""
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "seed.py")
        with open(path, encoding="utf-8") as fh:
            src = fh.read()
        body = src.split("def main(", 1)[0]      # main() times the build only
        code = "\n".join(l for l in body.splitlines()
                         if not l.lstrip().startswith("#"))
        for banned in ("datetime.now(", "date.today(", "time.time(",
                       "import random", "random.random", "random.seed",
                       "utcnow(", "os.urandom", "id("):
            self.assertNotIn(banned, code,
                             "%s appears in the seed's data path" % banned)

    def test_hash_uniform_is_stable_and_in_range(self):
        vals = [seed.u("LB-001", "2026-07-23", "noise"),
                seed.u("LB-001", "2026-07-23", "noise"),
                seed.u("LB-002", "2026-07-23", "noise")]
        self.assertEqual(vals[0], vals[1])
        self.assertNotEqual(vals[0], vals[2])
        for v in vals:
            self.assertTrue(0.0 <= v < 1.0)


class AssertionMachineryCase(unittest.TestCase):
    """The assertions must actually run and must actually be able to fail."""

    def test_assert_all_passes_and_is_not_vacuous(self):
        st = dbfixture.state()
        A = seed.assert_all(st["conn"], st["cal"])
        self.assertGreaterEqual(A.count(), 40)
        tags = " ".join(A.passed)
        for expected in ("STORYLINE 1", "STORYLINE 14", "BR-6", "BR-9",
                         "BR-11", "BR-12", "BR-15", "BR-16", "BR-17", "BR-19"):
            self.assertIn(expected, tags, "%s is never asserted" % expected)

    def test_a_failed_assertion_names_storyline_rows_and_fix(self):
        A = seed.Assertions()
        with self.assertRaises(AssertionError) as ctx:
            A.require("STORYLINE X 'demo'", False,
                      "rows LB-001 on 2026-07-23 show 5", "change CONST in seed.py")
        msg = str(ctx.exception)
        self.assertIn("STORYLINE X", msg)
        self.assertIn("LB-001", msg)
        self.assertIn("fix:", msg)


class StorylineCase(unittest.TestCase):
    """Independent re-derivation of a sample of the planted storylines — the
    seed asserts them; these tests check them a second way."""

    @classmethod
    def setUpClass(cls):
        cls.da = dbfixture.da()
        cls.conn = dbfixture.conn()

    def test_s1_upsell_champion_leads_the_leaderboard(self):
        lb = omni.upsell_leaderboard(self.da, ANCHOR, window_days=14)
        self.assertEqual(lb[0]["entity_id"], seed.UPSELL_STAR)
        self.assertGreater(lb[0]["attach_pct"], lb[1]["attach_pct"])

    def test_s2_pickup_gap_region_is_worst_and_diverges_from_recognized(self):
        pe = omni.pickup_execution(self.da, ANCHOR, window_days=14)
        self.assertEqual(pe["regions"][0]["region"], seed.PICKUP_GAP_REGION)
        f = omni.family_day(self.da, "BOPIS", ANCHOR,
                            region=seed.PICKUP_GAP_REGION)
        self.assertNotEqual(f["recognized"]["orders"],
                            f["all_inclusive"]["orders"])

    def test_s4_fragrance_slides_for_at_least_ten_days(self):
        run = merch.category_slide_run(self.da, ANCHOR, "Fragrance")
        self.assertGreaterEqual(run["consecutive_negative_days"], 10)
        exc = merch.category_exceptions(self.da, ANCHOR)
        self.assertIn("Fragrance", [e["category"] for e in exc])

    def test_s4_slide_drills_to_the_three_planted_skus(self):
        mv = merch.sku_movers_window(self.da, ANCHOR, "WTD", n=6,
                                     category="Fragrance")
        worst = set(r["sku_id"] for r in mv["bottom"])
        for sku in seed.SLIDE_SKUS:
            self.assertIn(sku, worst)

    def test_s5_breakout_sku_is_young_and_a_top_mover(self):
        mv = merch.sku_movers(self.da, ANCHOR, n=10)
        row = next(r for r in mv["top"] if r["sku_id"] == seed.BREAKOUT_SKU)
        self.assertLess(row["days_since_launch"], 90)
        self.assertGreater(row["delta"], 0)

    def test_s6_new_to_file_dip_fires_the_crm_flag(self):
        exc = customer.ntf_exception(self.da, ANCHOR, "WTD",
                                     entity_id=seed.NTF_DIP_ENTITY)
        self.assertTrue(exc["fires"])
        self.assertLess(exc["pct_new_to_file"], exc["baseline"])

    def test_s7_omni_heavy_day_leaves_the_headline_untouched(self):
        inv = omni.assert_headline_invariant(self.da, seed.OMNI_HEAVY_DAY)
        self.assertEqual(inv["headline_omni_on"], inv["headline_omni_off"])
        self.assertFalse(inv["attributed_exceeds_headline"])

    def test_s8_click_and_reserve_steps_up_after_the_planted_date(self):
        before = omni.family_day(self.da, "CR",
                                 seed.CR_STEP_DATE - dt.timedelta(days=10))
        after = omni.family_day(self.da, "CR",
                                seed.CR_STEP_DATE + dt.timedelta(days=10))
        self.assertGreater(after["completion_rate"] - before["completion_rate"],
                           0.15)

    def test_s9_traffic_up_conversion_down_over_the_planted_window(self):
        c = self.da.conversion_window(ANCHOR, "MTD", entity_id=seed.CONV_STORE)
        self.assertGreater(c["traffic"], c["ly_traffic"])
        self.assertLess(c["conversion"], c["ly_conversion"])
        self.assertLess(c["bps_vs_ly"], -150)

    def test_s10_hourly_shape_loses_its_midday_peak(self):
        prof = self.da.hourly_profile(seed.HOURLY_STORE, seed.HOURLY_DAY)
        midday = sum(prof["delta_share"][h] for h in (12, 13, 14, 15))
        self.assertLess(midday, -0.05)

    def test_s11_two_brands_diverge_inside_one_region(self):
        lum = self.da.comp_pct(ANCHOR, region=seed.DIVERGE_REGION, brand_id="LUM")
        atn = self.da.comp_pct(ANCHOR, region=seed.DIVERGE_REGION, brand_id="ATN")
        self.assertGreater(lum, 0)
        self.assertLess(atn, 0)

    def test_s12_canada_beats_plan_and_converts_smaller_in_usd(self):
        ca = catalog.DataAccess(self.conn, dbfixture.cal(),
                                reporting_currency="CAD")
        self.assertGreater(ca.plan_attainment(ANCHOR, affiliate_id="CA"), 1.0)
        cad = ca.net_sales(ANCHOR, affiliate_id="CA")
        usd = self.da.net_sales(ANCHOR, affiliate_id="CA")
        self.assertAlmostEqual(usd, cad / seed.FX_CAD_PER_USD, places=2)
        self.assertLess(usd, cad)

    def test_s13_three_plan_grains_read_together_without_confusion(self):
        ps = self.da.plan_status(ANCHOR)
        self.assertEqual(set(ps["grain_mix"]), {"DAY", "WEEK", "NONE"})
        self.assertIsNotNone(ps["day_grain"]["attainment"])
        self.assertIsNotNone(ps["week_grain"]["attainment"])
        self.assertIsNone(ps["no_plan"]["attainment"])
        self.assertIn("not spread to days", ps["week_grain"]["label"] +
                      ps["disclosure"])

    def test_s14_tree_explains_the_conversion_store(self):
        t = self.da.kpi_tree(seed.CONV_STORE, ANCHOR)
        d = dict((x["driver"], x["contribution"]) for x in t["drivers"])
        self.assertGreater(d["traffic"], 0)
        self.assertLess(d["conversion"], 0)
        self.assertGreater(abs(d["conversion"]), abs(d["traffic"]))

    def test_inherited_late_posters_and_remodel_survive_the_fork(self):
        comp = self.da.completeness(ANCHOR)
        self.assertIn(seed.LATE_BOTH, comp["missing"])
        self.assertIn(seed.LATE_ONE, comp["missing"])
        self.assertFalse(self.da.comp_eligible(seed.REMODEL_STORE, ANCHOR))


if __name__ == "__main__":
    unittest.main(verbosity=2)
