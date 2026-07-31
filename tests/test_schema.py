# -*- coding: utf-8 -*-
"""Schema integrity — the dimensions, keys and grains the PRD §3 specifies.

Run: python3 -m unittest tests.test_schema
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import dbfixture                      # noqa: E402
import seed                                      # noqa: E402


class SchemaCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.conn = dbfixture.conn()
        cls.da = dbfixture.da()

    def q(self, sql, args=()):
        return self.conn.execute(sql, args).fetchall()

    # -- dimensions --------------------------------------------------------

    def test_three_brands_with_distinct_plan_grains(self):
        rows = self.q("SELECT brand_id, plan_grain FROM brand ORDER BY brand_id")
        self.assertEqual(len(rows), 3)
        self.assertEqual(sorted(g for _, g in rows), ["DAY", "NONE", "WEEK"])

    def test_two_affiliates_two_currencies(self):
        rows = dict(self.q("SELECT affiliate_id, currency FROM affiliate"))
        self.assertEqual(rows, {"US": "USD", "CA": "CAD"})

    def test_eleven_districts_two_per_us_region_one_for_canada(self):
        rows = self.q("SELECT region, COUNT(*) FROM district GROUP BY 1")
        counts = dict(rows)
        self.assertEqual(sum(counts.values()), 11)
        for r in ("Northeast", "Southeast", "Midwest", "Southwest", "West"):
            self.assertEqual(counts[r], 2, r)
        self.assertEqual(counts["Canada"], 1)

    def test_fleet_shape(self):
        stores = self.q("SELECT COUNT(*) FROM stores WHERE channel='STORE'")[0][0]
        ecom = self.q("SELECT COUNT(*) FROM stores WHERE channel='ECOM'")[0][0]
        self.assertEqual((stores, ecom), (29, 2))

    def test_brand_partition_matches_the_prd_split(self):
        rows = dict(self.q("SELECT brand_id, COUNT(*) FROM stores "
                           "WHERE channel='STORE' GROUP BY 1"))
        self.assertEqual(rows, {"LUM": 14, "ATN": 9, "BOT": 6})

    def test_four_canadian_stores_are_deterministic_and_cad(self):
        rows = self.q("SELECT entity_id, currency, region FROM stores "
                      "WHERE affiliate_id='CA' AND channel='STORE' "
                      "ORDER BY entity_id")
        self.assertEqual([r[0] for r in rows],
                         ["LB-026", "LB-027", "LB-028", "LB-029"])
        self.assertTrue(all(r[1] == "CAD" and r[2] == "Canada" for r in rows))

    def test_every_store_has_a_district_and_ecom_has_none(self):
        bad = self.q("SELECT COUNT(*) FROM stores "
                     "WHERE channel='STORE' AND district_id IS NULL")[0][0]
        self.assertEqual(bad, 0)
        bad = self.q("SELECT COUNT(*) FROM stores "
                     "WHERE channel='ECOM' AND district_id IS NOT NULL")[0][0]
        self.assertEqual(bad, 0)

    def test_ecom_carries_no_brand_because_brand_lives_on_the_sku(self):
        self.assertEqual(
            self.q("SELECT COUNT(*) FROM stores "
                   "WHERE channel='ECOM' AND brand_id IS NOT NULL")[0][0], 0)
        self.assertEqual(
            self.q("SELECT COUNT(*) FROM stores "
                   "WHERE channel='STORE' AND brand_id IS NULL")[0][0], 0)

    def test_fx_rate_is_fixed_and_disclosed(self):
        rows = dict(self.q("SELECT currency, units_per_usd FROM fx_rate"))
        self.assertEqual(rows["USD"], 1.0)
        self.assertEqual(rows["CAD"], seed.FX_CAD_PER_USD)
        self.assertTrue(self.da.fx_disclosure("CAD"))

    # -- product / merchandise --------------------------------------------

    def test_product_catalogue_shape(self):
        self.assertEqual(self.q("SELECT COUNT(*) FROM product")[0][0], 120)
        cats = dict(self.q("SELECT category, COUNT(*) FROM product GROUP BY 1"))
        self.assertEqual(sorted(cats), sorted(seed.CATEGORIES))

    def test_categories_are_partitioned_by_brand(self):
        """A category belongs to exactly one brand, so category rollups
        partition cleanly by brand (BR-11)."""
        rows = self.q("SELECT category, COUNT(DISTINCT brand_id) "
                      "FROM product GROUP BY 1")
        for cat, n in rows:
            self.assertEqual(n, 1, "%s spans %d brands" % (cat, n))

    def test_sku_names_are_unique(self):
        n, distinct = self.q(
            "SELECT COUNT(*), COUNT(DISTINCT name) FROM product")[0]
        self.assertEqual(n, distinct)

    # -- grain / keys ------------------------------------------------------

    def test_sales_line_never_stores_brand_or_category(self):
        cols = [r[1] for r in self.q("PRAGMA table_info(sales_line)")]
        self.assertNotIn("brand_id", cols)
        self.assertNotIn("category", cols)

    def test_traffic_is_store_only(self):
        bad = self.q("SELECT COUNT(*) FROM traffic_day t JOIN stores s "
                     "USING(entity_id) WHERE s.channel<>'STORE'")[0][0]
        self.assertEqual(bad, 0)
        bad = self.q("SELECT COUNT(*) FROM traffic_hour t JOIN stores s "
                     "USING(entity_id) WHERE s.channel<>'STORE'")[0][0]
        self.assertEqual(bad, 0)

    def test_hourly_grain_is_eleven_trading_hours(self):
        lo, hi, n = self.q("SELECT MIN(hour), MAX(hour), COUNT(DISTINCT hour) "
                           "FROM traffic_hour")[0]
        self.assertEqual((lo, hi, n), (10, 20, 11))

    def test_plan_rows_exist_only_at_native_grain(self):
        rows = self.q("""SELECT s.brand_id, p.grain, COUNT(*)
                         FROM plan_day p JOIN stores s USING(entity_id)
                         WHERE s.channel='STORE' GROUP BY 1,2""")
        got = dict(((b, g), n) for b, g, n in rows)
        self.assertTrue(any(k == ("LUM", "DAY") for k in got))
        self.assertTrue(any(k == ("ATN", "WEEK") for k in got))
        self.assertFalse(any(k[0] == "ATN" and k[1] == "DAY" for k in got))
        self.assertFalse(any(k[0] == "BOT" for k in got))

    def test_week_grain_plan_rows_span_a_full_fiscal_week(self):
        rows = self.q("SELECT period_start, period_end FROM plan_day "
                      "WHERE grain='WEEK' LIMIT 50")
        import datetime as dt
        for a, b in rows:
            span = (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days
            self.assertEqual(span, 6)

    def test_calendar_carries_quarter_and_week_bounds(self):
        cols = [r[1] for r in self.q("PRAGMA table_info(calendar)")]
        for c in ("quarter", "week_start", "week_end", "ly_aligned_date",
                  "restated"):
            self.assertIn(c, cols)

    def test_customer_first_purchase_dates_are_within_the_seeded_history(self):
        lo, hi = self.q("SELECT MIN(first_purchase_date), "
                        "MAX(first_purchase_date) FROM customer")[0]
        self.assertGreaterEqual(lo, seed.SALES_START.isoformat())
        self.assertLessEqual(hi, seed.LATEST_COMPLETE.isoformat())

    def test_omni_orders_carry_a_declared_attribution_target(self):
        bad = self.q("SELECT COUNT(*) FROM omni_order o LEFT JOIN stores s "
                     "ON s.entity_id=o.attributed_to "
                     "WHERE s.entity_id IS NULL")[0][0]
        self.assertEqual(bad, 0)

    def test_recognized_omni_orders_have_a_fulfilment_date(self):
        bad = self.q("SELECT COUNT(*) FROM omni_order "
                     "WHERE status='completed' AND fulfilled_date IS NULL")[0][0]
        self.assertEqual(bad, 0)
        bad = self.q("SELECT COUNT(*) FROM omni_order "
                     "WHERE status<>'completed' AND fulfilled_date IS NOT NULL")[0][0]
        self.assertEqual(bad, 0)

    def test_no_wall_clock_in_the_seeded_timestamps(self):
        rows = self.q("SELECT DISTINCT SUBSTR(posted_at, 11) FROM sales_day")
        self.assertEqual([r[0] for r in rows], ["T06:30:00" + seed.TZ_SUFFIX])


if __name__ == "__main__":
    unittest.main(verbosity=2)
