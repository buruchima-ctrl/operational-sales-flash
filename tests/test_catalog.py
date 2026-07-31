# -*- coding: utf-8 -*-
"""Catalog tests — formulas, comp-store rules, scope, currency and windows.

Ported from the executive flash's catalog tests and extended for the
operational metric set. Where a formula matters, the test re-derives it from
raw SQL rather than from another catalog call, so a wrong formula cannot agree
with itself.

Run: python3 -m unittest tests.test_catalog
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import dbfixture                      # noqa: E402
import seed                                      # noqa: E402
from flash import catalog                        # noqa: E402

D = dt.date
ANCHOR = seed.LATEST_COMPLETE


class CatalogCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = dbfixture.conn()
        cls.cal = dbfixture.cal()
        cls.da = dbfixture.da()

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    # -- inherited behaviour (must survive the fork) ----------------------

    def test_comp_reconciliation_to_the_cent(self):
        """BR-6: Σ per-entity contributions == scope comp%, every day, every
        scope. The original executive-flash test, widened to the new scopes."""
        for iso in ("2026-07-23", "2026-06-30", "2026-05-02", "2026-04-25"):
            day = D.fromisoformat(iso)
            for scope in ({}, {"region": "Southeast"}, {"region": "West"},
                          {"brand_id": "ATN"}, {"affiliate_id": "CA"},
                          {"district_id": "MW-1"}, {"channel": "STORE"}):
                contribs = self.da.contribution_to_comp_gap(day, **scope)
                if not contribs:
                    continue
                total = sum(c["contribution"] for c in contribs)
                comp = self.da.comp_pct(day, **scope)
                self.assertAlmostEqual(total, comp, places=9,
                                       msg="%s %s" % (iso, scope))

    def test_comp_eligibility_rules(self):
        self.assertTrue(self.da.comp_eligible("ECOM-US", ANCHOR))
        self.assertTrue(self.da.comp_eligible("ECOM-CA", ANCHOR))
        self.assertTrue(self.da.comp_eligible("LB-001", ANCHOR))
        self.assertFalse(self.da.comp_eligible("LB-025", ANCHOR))   # opened 2025-08
        self.assertFalse(self.da.comp_eligible("LB-013", ANCHOR))   # in remodel

    def test_hand_comp_matches_direct_sql(self):
        """Re-derive the day comp from raw SQL, converting currency by hand."""
        day = D(2026, 6, 17)
        ly = self.da.ly_date(day)
        members = self.da.comp_set(day)
        indep = []
        for e in self.da.entities():
            eid = e["entity_id"]
            if not self.da.comp_eligible(eid, day):
                continue
            if self.da._in_remodel(e, ly):
                continue
            ty = self.q("SELECT net_sales FROM sales_day "
                        "WHERE date=? AND entity_id=?", (day.isoformat(), eid))
            lyv = self.q("SELECT net_sales FROM sales_day "
                         "WHERE date=? AND entity_id=?", (ly.isoformat(), eid))
            if ty and lyv:
                indep.append(eid)
        self.assertEqual(set(members), set(indep))

        def total(d):
            rows = self.q(
                "SELECT s.currency, SUM(d.net_sales) FROM sales_day d "
                "JOIN stores s USING(entity_id) WHERE d.date=? AND "
                "d.entity_id IN (%s) GROUP BY 1" % ",".join("?" * len(indep)),
                [d.isoformat()] + indep)
            return sum(v if c == "USD" else v / seed.FX_CAD_PER_USD
                       for c, v in rows)

        self.assertAlmostEqual(self.da.comp_pct(day),
                               total(day) / total(ly) - 1.0, places=9)

    def test_missing_stores_excluded_not_zeroed(self):
        comp = self.da.completeness(ANCHOR)
        self.assertIn(seed.LATE_BOTH, comp["missing"])
        self.assertIn(seed.LATE_ONE, comp["missing"])
        self.assertIsNone(self.da.net_sales_of(seed.LATE_BOTH, ANCHOR))
        rows = self.q("SELECT s.currency, SUM(d.net_sales) FROM sales_day d "
                      "JOIN stores s USING(entity_id) WHERE d.date=? GROUP BY 1",
                      (ANCHOR.isoformat(),))
        hand = sum(v if c == "USD" else v / seed.FX_CAD_PER_USD for c, v in rows)
        self.assertAlmostEqual(self.da.net_sales(ANCHOR), round(hand, 2), places=2)

    def test_basket_metrics_consistent_and_ast_aus_are_aliases(self):
        b = self.da.basket(ANCHOR)
        self.assertAlmostEqual(b["aov"], b["net_sales"] / b["transactions"], places=9)
        self.assertAlmostEqual(b["upt"], b["units"] / b["transactions"], places=9)
        self.assertAlmostEqual(b["aur"], b["net_sales"] / b["units"], places=9)
        self.assertEqual(b["ast"], b["aov"])          # identity, not approximation
        self.assertEqual(b["aus"], b["aur"])

    # -- scope -------------------------------------------------------------

    def test_unknown_scope_key_raises_rather_than_widening(self):
        with self.assertRaises(catalog.CatalogError):
            self.da.net_sales(ANCHOR, brand="LUM")     # the key is brand_id
        with self.assertRaises(catalog.CatalogError):
            self.da.net_sales(ANCHOR, regoin="West")

    def test_scopes_partition_the_fleet(self):
        total = self.da.net_sales(ANCHOR)
        by_brand = sum(self.da.net_sales(ANCHOR, brand_id=b["brand_id"])
                       for b in self.da.brands())
        by_brand += self.da.net_sales(ANCHOR, channel="ECOM")
        self.assertAlmostEqual(total, by_brand, places=2)
        by_aff = sum(self.da.net_sales(ANCHOR, affiliate_id=a)
                     for a in ("US", "CA"))
        self.assertAlmostEqual(total, by_aff, places=2)
        by_region = sum(self.da.net_sales(ANCHOR, region=r)
                        for r in list(catalog.REGIONS) + ["ECOM"])
        self.assertAlmostEqual(total, by_region, places=2)
        by_district = sum(self.da.net_sales(ANCHOR, district_id=d["district_id"])
                          for d in self.da.districts())
        by_district += self.da.net_sales(ANCHOR, channel="ECOM")
        self.assertAlmostEqual(total, by_district, places=2)

    # -- currency (BR-16) --------------------------------------------------

    def test_conversion_is_explicit_and_reversible(self):
        cad = catalog.DataAccess(self.conn, self.cal, reporting_currency="CAD")
        usd_total = self.da.net_sales(ANCHOR, affiliate_id="CA")
        cad_total = cad.net_sales(ANCHOR, affiliate_id="CA")
        self.assertAlmostEqual(usd_total * seed.FX_CAD_PER_USD, cad_total, places=2)

    def test_local_total_refuses_a_mixed_currency_scope(self):
        with self.assertRaises(catalog.CatalogError):
            self.da.net_sales_local(ANCHOR)
        self.assertGreater(self.da.net_sales_local(ANCHOR, affiliate_id="CA"), 0)

    def test_currency_note_discloses_the_fixed_rate(self):
        note = self.da.currency_note(affiliate_id="CA")
        self.assertIn("CAD", note)
        self.assertIn("1.35", note)
        self.assertIsNone(self.da.currency_note(affiliate_id="US"))

    def test_comp_pct_is_invariant_to_reporting_currency(self):
        cad = catalog.DataAccess(self.conn, self.cal, reporting_currency="CAD")
        self.assertAlmostEqual(self.da.comp_pct(ANCHOR),
                               cad.comp_pct(ANCHOR), places=12)

    # -- windows (#4-6, #41) ----------------------------------------------

    def test_window_ranges(self):
        row = self.da.cal_row(ANCHOR)
        self.assertEqual(self.da.window_range(ANCHOR, "WTD"),
                         (D.fromisoformat(row["week_start"]), ANCHOR))
        lw_start, lw_end = self.da.window_range(ANCHOR, "LW")
        self.assertEqual((lw_end - lw_start).days, 6)
        self.assertLess(lw_end, D.fromisoformat(row["week_start"]))
        q_start, q_end = self.da.window_range(ANCHOR, "QTD")
        self.assertEqual(q_end, ANCHOR)
        self.assertEqual(self.da.cal_row(q_start)["quarter"], row["quarter"])
        self.assertEqual(self.da.cal_row(q_start)["week"] % 13, 1 % 13)

    def test_unknown_window_raises(self):
        with self.assertRaises(catalog.CatalogError):
            self.da.window_range(ANCHOR, "R12")

    def test_wtd_is_the_sum_of_its_days(self):
        w = self.da.window_metrics(ANCHOR, "WTD")
        hand = sum(self.da.net_sales(d) for d in self.da.window_dates(ANCHOR, "WTD"))
        self.assertAlmostEqual(w["net_sales"], round(hand, 2), places=2)

    # -- traffic and conversion (#30, #31 / BR-15) ------------------------

    def test_conversion_is_transactions_over_traffic(self):
        eid = "LB-001"
        c = self.da.conversion(ANCHOR, entity_id=eid)
        txn = self.q("SELECT transactions FROM sales_day WHERE date=? AND "
                     "entity_id=?", (ANCHOR.isoformat(), eid))[0][0]
        trf = self.q("SELECT traffic FROM traffic_day WHERE date=? AND "
                     "entity_id=?", (ANCHOR.isoformat(), eid))[0][0]
        self.assertAlmostEqual(c["conversion"], txn / float(trf), places=12)

    def test_missing_traffic_is_unavailable_not_zero(self):
        eid, day = sorted(seed.TRAFFIC_MISSING)[0]
        c = self.da.conversion(day, entity_id=eid)
        self.assertIsNone(c["conversion"])
        self.assertFalse(c["available"])
        self.assertIn(eid, c["stores_missing_traffic"])
        self.assertIsNotNone(c["unavailable_note"])
        self.assertIsNone(self.da.traffic_of(eid, day))

    def test_ecom_has_no_traffic_and_no_conversion(self):
        c = self.da.conversion(ANCHOR, channel="ECOM")
        self.assertIsNone(c["conversion"])
        t = self.da.traffic(ANCHOR, channel="ECOM")
        self.assertIsNone(t["traffic"])

    # -- plan (BR-19) ------------------------------------------------------

    def test_no_plan_brand_never_shows_an_attainment(self):
        ps = self.da.plan_status(ANCHOR, brand_id="BOT")
        self.assertIsNone(ps["day_grain"]["attainment"])
        self.assertIsNone(ps["no_plan"]["attainment"])
        self.assertGreater(ps["no_plan"]["actual"], 0)
        self.assertIsNone(self.da.plan_attainment(ANCHOR, brand_id="BOT"))

    def test_week_planned_brand_has_no_day_plan(self):
        self.assertIsNone(self.da.plan_of("LB-003", ANCHOR))
        self.assertIsNotNone(self.da.week_plan_of("LB-003", ANCHOR))
        ps = self.da.plan_status(ANCHOR, brand_id="ATN")
        self.assertIsNotNone(ps["week_grain"]["attainment"])
        self.assertEqual(ps["week_grain"]["week_days"], 7)

    def test_day_plan_matches_raw_rows(self):
        plan = self.da.plan_of("LB-001", ANCHOR)
        raw = self.q("SELECT plan_sales FROM plan_day WHERE entity_id='LB-001' "
                     "AND grain='DAY' AND period_start=?",
                     (ANCHOR.isoformat(),))[0][0]
        self.assertAlmostEqual(plan, raw, places=6)

    def test_plan_status_coverage_is_a_real_share(self):
        ps = self.da.plan_status(ANCHOR)
        self.assertGreater(ps["planned_share_of_actual"], 0.5)
        self.assertLess(ps["planned_share_of_actual"], 1.0)

    # -- discounts / returns / status / rank ------------------------------

    def test_gross_identity_holds_at_rollup(self):
        g = self.da.gross_pack(ANCHOR)
        self.assertAlmostEqual(g["identity_gap"], 0.0, places=1)
        self.assertAlmostEqual(g["net"], self.da.net_sales(ANCHOR), places=2)

    def test_discount_pct_is_of_gross(self):
        d = self.da.discounts(ANCHOR)
        self.assertAlmostEqual(d["pct_of_gross"], d["discounts"] / d["gross"],
                               places=12)
        self.assertTrue(0.05 < d["pct_of_gross"] < 0.20)

    def test_store_returns_exclude_ecom(self):
        r = self.da.store_returns(ANCHOR)
        store_gross = self.da.gross_pack(ANCHOR, channel="STORE")["gross"]
        self.assertAlmostEqual(r["gross"], store_gross, places=2)

    def test_store_status_funnel_narrows(self):
        s = self.da.store_status(ANCHOR)
        self.assertGreaterEqual(s["portfolio"], s["trading"])
        self.assertGreaterEqual(s["trading"], s["comp_trading"])
        self.assertAlmostEqual(s["pct_trading"],
                               s["trading"] / float(s["portfolio"]), places=12)

    def test_tiers_narrow_and_total_is_the_widest(self):
        total = self.da.tier_metrics(ANCHOR, "TOTAL")
        allt = self.da.tier_metrics(ANCHOR, "ALL_TRADING")
        comp = self.da.tier_metrics(ANCHOR, "COMP_TRADING")
        self.assertGreater(total["net_sales"], allt["net_sales"])
        self.assertGreaterEqual(allt["net_sales"], comp["net_sales"])
        self.assertEqual(total["net_sales"], self.da.net_sales(ANCHOR))

    def test_rank_rejects_an_undefined_kpi(self):
        with self.assertRaises(catalog.CatalogError):
            self.da.rank_stores(ANCHOR, kpi="vibes")

    def test_rank_separates_unavailable_from_bottom(self):
        r = self.da.rank_stores(ANCHOR, kpi="conversion", n=5)
        missing = set(e for e, d in seed.TRAFFIC_MISSING if d == ANCHOR)
        self.assertEqual(set(x["entity_id"] for x in r["unavailable"]), missing)
        self.assertTrue(all(x["value"] is not None for x in r["bottom"]))

    def test_fav_band_key(self):
        self.assertEqual(self.da.fav_band(0.08), "fav")
        self.assertEqual(self.da.fav_band(-0.08), "unfav")
        self.assertEqual(self.da.fav_band(0.01), "within")
        self.assertIsNone(self.da.fav_band(None))

    # -- hourly and tree ---------------------------------------------------

    def test_hourly_series_reconciles_to_the_day(self):
        for eid in ("LB-001", "LB-018", "LB-026"):
            s = self.da.hourly_series(eid, ANCHOR)
            self.assertEqual(len(s["hours"]), 11)
            self.assertAlmostEqual(s["reconciliation_gap"], 0.0, places=2)
            self.assertEqual(s["hourly_transactions"], s["day_transactions"])

    def test_tree_contributions_compose_to_the_gap(self):
        for eid in ("LB-001", "LB-015", "LB-022"):
            t = self.da.kpi_tree(eid, ANCHOR)
            self.assertTrue(t["available"])
            s = sum(d["contribution"] for d in t["drivers"])
            self.assertAlmostEqual(s, t["gap"], places=1)
            self.assertAlmostEqual(t["residual_interaction"], 0.0, places=2)
            ast = next(d for d in t["drivers"] if d["driver"] == "ast")
            split = sum(d["contribution"] for d in t["ast_split"])
            self.assertAlmostEqual(split, ast["contribution"], places=1)

    def test_tree_payload_reproduces_the_actual(self):
        """BR-20: the what-if calculator multiplies these numbers, so they must
        already multiply back to the catalog's own figure."""
        p = self.da.kpi_tree("LB-001", ANCHOR)["payload"]
        self.assertAlmostEqual(p["traffic"] * p["conversion"] * p["ast"],
                               p["net_sales"], places=2)
        self.assertAlmostEqual(p["aus"] * p["upt"], p["ast"], places=9)

    def test_tree_is_unavailable_without_traffic_never_faked(self):
        eid, day = sorted(seed.TRAFFIC_MISSING)[0]
        t = self.da.kpi_tree(eid, day)
        self.assertFalse(t["available"])
        self.assertIn("traffic", t["reason"])

    # -- e-commerce (BR-4) -------------------------------------------------

    def test_ecom_basis_switch_is_validated(self):
        with self.assertRaises(catalog.CatalogError):
            catalog.DataAccess(self.conn, self.cal, ecom_basis="whatever")

    def test_demand_and_settled_are_different_series(self):
        e = self.da.ecom_day(seed.ECOM_MATURATION_DAY, seed.TODAY)
        self.assertNotEqual(e["demand"], e["shipped"])
        settled = catalog.DataAccess(self.conn, self.cal, ecom_basis="settled")
        self.assertNotEqual(self.da.net_sales(seed.ECOM_MATURATION_DAY,
                                              channel="ECOM"),
                            settled.net_sales(seed.ECOM_MATURATION_DAY,
                                              channel="ECOM"))

    def test_settled_return_rate_uses_matured_days_only(self):
        r = self.da.ecom_settled_return_rate(seed.TODAY)
        self.assertTrue(0.03 < r < 0.15)


if __name__ == "__main__":
    unittest.main(verbosity=2)
