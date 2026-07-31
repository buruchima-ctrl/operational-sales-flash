# -*- coding: utf-8 -*-
"""Reconciliation tests — the business rules that make the numbers trustable.

BR-6 (drivers reconcile), BR-9 (omni attributes, never adds), BR-11 (every
level sums to its parent, to the cent), BR-12 (buyer counts consistent),
BR-15 (missing traffic is unavailable, not 0%), BR-16 (currency honesty),
BR-17 (hourly reconciles to the day), BR-19 (plan-grain honesty) and BR-20
(tree contributions compose exactly).

Where possible these re-derive by hand-SQL rather than through the catalog, so
a wrong implementation cannot confirm itself.

Run: python3 -m unittest tests.test_reconciliation
"""
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import dbfixture                      # noqa: E402
import seed                                      # noqa: E402
from flash import catalog, customer, merch, omni  # noqa: E402

D = dt.date
ANCHOR = seed.LATEST_COMPLETE
SAMPLE_DAYS = [ANCHOR, ANCHOR - dt.timedelta(days=5),
               ANCHOR - dt.timedelta(days=21), ANCHOR - dt.timedelta(days=60)]


class ReconciliationCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = dbfixture.conn()
        cls.cal = dbfixture.cal()
        cls.da = dbfixture.da()

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    # -- BR-11: every level sums to its parent ----------------------------

    def test_br11_sku_lines_sum_to_the_day_every_day(self):
        bad = self.q("""SELECT COUNT(*) FROM (
                          SELECT date, entity_id, ROUND(SUM(net_sales),2) s,
                                 SUM(units) u FROM sales_line GROUP BY 1,2) x
                        JOIN sales_day d ON d.date=x.date
                          AND d.entity_id=x.entity_id
                        WHERE ABS(x.s-d.net_sales)>0.005 OR x.u<>d.units""")[0][0]
        self.assertEqual(bad, 0)

    def test_br11_full_drill_path_total_region_store_category_sku(self):
        """The acceptance-checklist drill, by hand, in one currency scope."""
        day = ANCHOR
        total = self.da.net_sales(day)
        regions = sum(self.da.net_sales(day, region=r)
                      for r in list(catalog.REGIONS) + ["ECOM"])
        self.assertAlmostEqual(total, regions, places=2)

        region = "Midwest"
        stores = sum(self.da.net_sales(day, entity_id=e["entity_id"])
                     for e in self.da._scope_entities(region=region))
        self.assertAlmostEqual(self.da.net_sales(day, region=region), stores,
                               places=2)

        eid = "LB-014"
        store_total = self.da.net_sales(day, entity_id=eid)
        cats = merch.category_day(self.da, day, entity_id=eid)
        self.assertAlmostEqual(sum(r["net_sales"] for r in cats["categories"]),
                               store_total, places=2)

        cat = cats["categories"][0]["category"]
        skus = self.q("""SELECT ROUND(SUM(l.net_sales),2) FROM sales_line l
                         JOIN product p USING(sku_id)
                         WHERE l.date=? AND l.entity_id=? AND p.category=?""",
                      (day.isoformat(), eid, cat))[0][0]
        self.assertAlmostEqual(skus, cats["categories"][0]["net_sales"], places=2)

    def test_br11_districts_sum_to_regions(self):
        for r in ("Northeast", "Southeast", "Midwest", "Southwest", "West",
                  "Canada"):
            ds = [d for d in self.da.districts() if d["region"] == r]
            s = sum(self.da.net_sales(ANCHOR, district_id=d["district_id"])
                    for d in ds)
            self.assertAlmostEqual(self.da.net_sales(ANCHOR, region=r), s,
                                   places=2, msg=r)

    def test_br11_sku_movers_contributions_sum_to_the_group_comp(self):
        m = merch.sku_movers(self.da, ANCHOR, n=10)
        comp = self.da.comp_pct(ANCHOR)
        self.assertAlmostEqual(m["contribution_sum"], comp, places=6)

    # -- BR-6: driver decomposition ---------------------------------------

    def test_br6_contributions_reconcile_on_every_sampled_day_and_scope(self):
        for day in SAMPLE_DAYS:
            for scope in ({}, {"region": "West"}, {"brand_id": "BOT"},
                          {"affiliate_id": "US"}):
                cs = self.da.contribution_to_comp_gap(day, **scope)
                if not cs:
                    continue
                self.assertAlmostEqual(
                    sum(c["contribution"] for c in cs),
                    self.da.comp_pct(day, **scope), places=9,
                    msg="%s %s" % (day, scope))

    # -- BR-9: omni attributes, never adds --------------------------------

    def test_br9_headline_is_identical_with_omni_on_and_off(self):
        for day in SAMPLE_DAYS:
            inv = omni.assert_headline_invariant(self.da, day)
            self.assertEqual(inv["headline_omni_on"], inv["headline_omni_off"])
            self.assertEqual(inv["headline_omni_on"], self.da.net_sales(day))

    def test_br9_attributed_omni_never_exceeds_the_money_it_partitions(self):
        for day in SAMPLE_DAYS:
            inv = omni.assert_headline_invariant(self.da, day)
            self.assertFalse(inv["attributed_exceeds_headline"], str(day))
            self.assertLess(inv["attributed_share"], 0.5)

    def test_br9_omni_sales_never_appear_in_sales_day(self):
        """The structural guarantee: the headline reads one table, omni reads
        another, and no join adds the second to the first."""
        headline_tables = self.q(
            "SELECT COUNT(*) FROM sales_day WHERE date=?", (ANCHOR.isoformat(),))
        self.assertGreater(headline_tables[0][0], 0)
        pen = omni.omni_penetration(self.da, ANCHOR)
        self.assertEqual(pen["net_sales"], self.da.net_sales(ANCHOR))
        self.assertLess(pen["omni_attributed_sales"], pen["net_sales"])

    def test_br10_recognized_and_all_inclusive_are_distinct_series(self):
        seen = 0
        for fam in omni.FAMILIES:
            for day in SAMPLE_DAYS:
                f = omni.family_day(self.da, fam, day)
                if f["recognized"]["orders"] != f["all_inclusive"]["orders"]:
                    seen += 1
        self.assertGreaterEqual(seen, len(omni.FAMILIES),
                                "each family must diverge on at least one day")

    def test_br10_lift_refuses_a_mixed_basis(self):
        with self.assertRaises(catalog.CatalogError):
            omni.family_lifts(self.da, "BOPIS", ANCHOR, basis="both")

    def test_br14_label_saving_is_a_named_constant(self):
        b = omni.boris_day(self.da, ANCHOR)
        self.assertEqual(b["label_saving_constant_usd"], 7.46)
        self.assertAlmostEqual(b["recognized"]["label_savings"],
                               b["recognized"]["orders"] * 7.46, places=2)

    # -- BR-12: buyer counts ----------------------------------------------

    def test_br12_buyer_counts_match_the_underlying_rows(self):
        for day in SAMPLE_DAYS:
            b = customer.buyers(self.da, day)
            txn = self.q("SELECT COALESCE(SUM(transactions),0) FROM sales_day "
                         "WHERE date=?", (day.isoformat(),))[0][0]
            new = self.q("""SELECT COUNT(*) FROM customer c
                            JOIN sales_day s ON s.date=c.first_purchase_date
                             AND s.entity_id=c.home_entity_id
                            WHERE c.first_purchase_date=?""",
                         (day.isoformat(),))[0][0]
            self.assertEqual(b["total_buyers"], txn, str(day))
            self.assertEqual(b["new_buyers"], new, str(day))
            self.assertEqual(b["repeat_buyers"], txn - new)

    def test_br12_customer_and_omni_panels_use_the_same_definition(self):
        day = ANCHOR
        panel = customer.buyers(self.da, day)
        family = customer.omni_new_buyers(self.da, day, "BOPIS")
        firsts = set(r[0] for r in self.q(
            "SELECT customer_id FROM customer WHERE first_purchase_date=?",
            (day.isoformat(),)))
        buyers_in_family = set(r[0] for r in self.q(
            "SELECT customer_id FROM omni_order WHERE fulfilled_date=? "
            "AND order_type='BOPIS' AND status='completed'", (day.isoformat(),)))
        self.assertEqual(family["new_buyers"],
                         len(firsts & buyers_in_family))
        self.assertLessEqual(family["new_buyers"], panel["new_buyers"] +
                             panel["repeat_buyers"])

    def test_br12_new_customer_block_is_a_slice_of_the_day(self):
        for day in SAMPLE_DAYS:
            nb = customer.new_customer_block(self.da, day)
            self.assertLess(nb["net_sales"], self.da.net_sales(day))
            self.assertLess(nb["pct_of_net_sales"], 0.30)
            self.assertEqual(nb["new_customers"],
                             customer.buyers(self.da, day)["new_buyers"])

    def test_repeat_rate_complements_new_to_file(self):
        w = customer.buyers_window(self.da, ANCHOR, "WTD")
        self.assertAlmostEqual(w["repeat_rate"] + w["pct_new_to_file"], 1.0,
                               places=12)

    # -- BR-15: missing traffic -------------------------------------------

    def test_br15_missing_traffic_never_becomes_zero_percent(self):
        for eid, day in sorted(seed.TRAFFIC_MISSING):
            c = self.da.conversion(day, entity_id=eid)
            self.assertIsNone(c["conversion"])
            self.assertNotEqual(c["conversion"], 0.0)
            self.assertIn(eid, c["stores_missing_traffic"])

    def test_br15_rollup_excludes_the_dark_door_from_both_sides(self):
        day = ANCHOR
        c = self.da.conversion(day)
        missing = set(e for e, d in seed.TRAFFIC_MISSING if d == day)
        hand_txn = self.q("""SELECT SUM(d.transactions) FROM sales_day d
                             JOIN traffic_day t
                               ON t.date=d.date AND t.entity_id=d.entity_id
                             WHERE d.date=?""", (day.isoformat(),))[0][0]
        hand_trf = self.q("""SELECT SUM(t.traffic) FROM traffic_day t
                             JOIN sales_day d
                               ON t.date=d.date AND t.entity_id=d.entity_id
                             WHERE t.date=?""", (day.isoformat(),))[0][0]
        self.assertEqual(c["transactions"], hand_txn)
        self.assertEqual(c["traffic"], hand_trf)
        self.assertEqual(set(c["stores_missing_traffic"]), missing)

    # -- BR-16: currency ---------------------------------------------------

    def test_br16_facts_are_stored_local_and_converted_once(self):
        rows = self.q("""SELECT s.currency, SUM(d.net_sales) FROM sales_day d
                         JOIN stores s USING(entity_id)
                         WHERE d.date=? GROUP BY 1""", (ANCHOR.isoformat(),))
        by_ccy = dict(rows)
        hand = by_ccy["USD"] + by_ccy["CAD"] / seed.FX_CAD_PER_USD
        self.assertAlmostEqual(self.da.net_sales(ANCHOR), round(hand, 2), places=2)
        # the CAD figure is genuinely larger in its own currency
        cad_da = catalog.DataAccess(self.conn, self.cal, reporting_currency="CAD")
        self.assertGreater(cad_da.net_sales(ANCHOR, affiliate_id="CA"),
                           self.da.net_sales(ANCHOR, affiliate_id="CA"))

    def test_br16_no_silent_mixing(self):
        with self.assertRaises(catalog.CatalogError):
            self.da.net_sales_local(ANCHOR)
        with self.assertRaises(catalog.CatalogError):
            self.da.convert(100.0, "EUR")

    def test_br16_disclosure_appears_wherever_conversion_does(self):
        self.assertIsNotNone(self.da.currency_note())
        self.assertIsNotNone(self.da.currency_note(affiliate_id="CA"))
        self.assertIsNone(self.da.currency_note(affiliate_id="US"))

    # -- BR-17: hourly ------------------------------------------------------

    def test_br17_hourly_reconciles_for_every_store_day_in_the_window(self):
        bad = self.q("""SELECT COUNT(*) FROM (
                          SELECT date, entity_id, ROUND(SUM(net_sales),2) s,
                                 SUM(transactions) t, SUM(traffic) f
                          FROM traffic_hour GROUP BY 1,2) x
                        JOIN sales_day d ON d.date=x.date
                          AND d.entity_id=x.entity_id
                        WHERE ABS(x.s-d.net_sales)>0.005
                           OR x.t<>d.transactions""")[0][0]
        self.assertEqual(bad, 0)

    def test_br17_hourly_traffic_reconciles_to_daily_traffic(self):
        bad = self.q("""SELECT COUNT(*) FROM (
                          SELECT date, entity_id, SUM(traffic) f
                          FROM traffic_hour GROUP BY 1,2) x
                        JOIN traffic_day t ON t.date=x.date
                          AND t.entity_id=x.entity_id
                        WHERE x.f<>t.traffic""")[0][0]
        self.assertEqual(bad, 0)

    def test_br17_hourly_is_labelled_intraday(self):
        s = self.da.hourly_series("LB-001", ANCHOR)
        self.assertIn("unaudited", s["governance"])
        self.assertIn("system of record", s["governance"])

    # -- BR-19: plan grain --------------------------------------------------

    def test_br19_each_grain_is_measured_on_its_own_terms(self):
        ps = self.da.plan_status(ANCHOR)
        self.assertIsNotNone(ps["day_grain"]["attainment"])
        self.assertIsNotNone(ps["week_grain"]["attainment"])
        self.assertIsNone(ps["no_plan"]["attainment"])
        self.assertIn("day", ps["disclosure"])
        self.assertIn("week", ps["disclosure"])
        self.assertIn("without a plan", ps["disclosure"])

    def test_br19_week_plan_is_never_spread_across_days(self):
        """A spread weekly plan would make the day plan and 1/7th of the week
        plan agree. They must not: no daily plan exists for that brand."""
        self.assertIsNone(self.da.plan_of("LB-003", ANCHOR))
        rows = self.q("SELECT COUNT(*) FROM plan_day p JOIN stores s "
                      "USING(entity_id) WHERE s.brand_id='ATN' AND p.grain='DAY'")
        self.assertEqual(rows[0][0], 0)

    def test_br19_day_grain_attainment_matches_hand_sql(self):
        rows = self.q("""SELECT SUM(p.plan_sales), s.currency
                         FROM plan_day p JOIN stores s USING(entity_id)
                         WHERE p.grain='DAY' AND p.period_start=?
                           AND EXISTS (SELECT 1 FROM sales_day d
                                       WHERE d.date=p.period_start
                                         AND d.entity_id=p.entity_id)
                         GROUP BY s.currency""", (ANCHOR.isoformat(),))
        plan = sum(v if c == "USD" else v / seed.FX_CAD_PER_USD for v, c in rows)
        self.assertAlmostEqual(self.da.plan_pair(ANCHOR)["plan"],
                               round(plan, 2), places=2)

    # -- BR-20: the tree ----------------------------------------------------

    def test_br20_tree_composes_exactly_for_three_sampled_store_days(self):
        for eid in ("LB-002", "LB-015", "LB-026"):
            for day in (ANCHOR, ANCHOR - dt.timedelta(days=9)):
                t = self.da.kpi_tree(eid, day)
                if not t["available"]:
                    continue
                s = sum(d["contribution"] for d in t["drivers"])
                self.assertAlmostEqual(s, t["gap"], places=1,
                                       msg="%s %s" % (eid, day))
                self.assertAlmostEqual(t["residual_interaction"], 0.0, places=2)

    def test_br20_the_calculator_payload_is_the_catalogs_own_arithmetic(self):
        for eid in ("LB-002", "LB-015"):
            p = self.da.kpi_tree(eid, ANCHOR)["payload"]
            self.assertAlmostEqual(p["traffic"] * p["conversion"] * p["ast"],
                                   p["net_sales"], places=2)
            self.assertAlmostEqual(p["ly_traffic"] * p["ly_conversion"]
                                   * p["ly_ast"], p["ly_net_sales"], places=2)
            # a what-if scenario reproduces the catalog rather than re-deriving
            scenario = p["traffic"] * (p["conversion"] * 1.10) * p["ast"]
            self.assertAlmostEqual(scenario / p["net_sales"], 1.10, places=6)

    # -- deck identities ----------------------------------------------------

    def test_net_equals_gross_less_discounts_and_returns_every_row(self):
        bad = self.q("SELECT COUNT(*) FROM sales_day WHERE "
                     "ABS(net_sales-(gross_sales-discount_sales-return_sales))"
                     ">0.005")[0][0]
        self.assertEqual(bad, 0)

    def test_omni_penetration_is_a_share_not_an_addition(self):
        p = omni.omni_penetration(self.da, ANCHOR)
        self.assertAlmostEqual(
            p["penetration"], p["omni_attributed_sales"] / p["net_sales"],
            places=12)
        self.assertAlmostEqual(sum(p["parts"].values()),
                               p["omni_attributed_sales"], places=2)

    def test_merch_reconciler_confirms_itself_on_sampled_days(self):
        for day in SAMPLE_DAYS:
            r = merch.reconcile_lines(self.da, day)
            if r.get("available"):
                self.assertTrue(r["reconciled"], "%s: %s" % (day, r["breaks"]))

    def test_sku_grain_outside_the_window_is_unavailable_not_zero(self):
        old = D(2024, 6, 1)
        c = merch.category_day(self.da, old)
        self.assertFalse(c["available"])
        self.assertIn("UNAVAILABLE", c["reason"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
