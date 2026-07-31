# -*- coding: utf-8 -*-
"""Compute tests — the per-day ops object and its invariants.

The object is the contract between the catalog and every surface. If a field
is missing, a renderer improvises; if a field is wrong, three surfaces are
wrong together and agree with each other. So these tests check both shape and
arithmetic, and they check that the invariants actually fire when the object
is tampered with — an assertion nobody has ever seen fail is an assertion
nobody knows works.

Run: python3 -m unittest tests.test_compute
"""
import copy
import datetime as dt
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import dbfixture                       # noqa: E402
import seed                                       # noqa: E402
from flash import compute, customer, merch, omni  # noqa: E402

D = dt.date
ANCHOR = seed.LATEST_COMPLETE


class ObjectShapeCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.da = dbfixture.da()
        cls.obj = dbfixture.site_objects()[-1]        # full depth, the anchor
        cls.summary = dbfixture.site_objects()[0]     # summary depth

    def test_depth_is_validated(self):
        with self.assertRaises(ValueError):
            compute.build_flash(self.da, ANCHOR, depth="medium")

    def test_summary_and_full_carry_the_same_headline(self):
        s = compute.build_flash(self.da, ANCHOR, depth="summary")
        f = compute.build_flash(self.da, ANCHOR, depth="full")
        self.assertEqual(s["headline"], f["headline"])
        self.assertEqual(s["display"]["net_sales"], f["display"]["net_sales"])
        self.assertEqual(s["narrative"], f["narrative"])

    def test_full_depth_adds_the_drill_layers(self):
        for key in ("drill", "stores", "ranks", "extract", "personas"):
            self.assertIn(key, self.obj, key)
            self.assertNotIn(key, self.summary, key)

    def test_headline_carries_the_decks_kpi_row(self):
        h = self.obj["headline"]
        for key in ("net_sales", "comp_pct", "plan_attainment", "transactions",
                    "ast", "aus", "upt", "traffic", "conversion",
                    "new_customers", "returns", "discounts",
                    "omni_penetration", "portfolio", "trading"):
            self.assertIn(key, h, key)

    def test_windows_cover_the_full_family(self):
        self.assertEqual(sorted(self.obj["windows"]),
                         sorted(("LW", "WTD", "MTD", "QTD", "YTD")))

    def test_no_wall_clock_in_the_compute_source(self):
        path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "flash", "compute.py")
        with open(path, encoding="utf-8") as fh:
            code = "\n".join(l for l in fh.read().splitlines()
                             if not l.lstrip().startswith("#"))
        for banned in ("datetime.now(", "date.today(", "time.time(",
                       "import random", "utcnow("):
            self.assertNotIn(banned, code, banned)

    def test_as_of_is_the_send_morning_not_now(self):
        self.assertEqual(self.obj["as_of"],
                         (D.fromisoformat(self.obj["date"])
                          + dt.timedelta(days=1)).isoformat())

    def test_object_is_json_serializable_and_stable(self):
        from flash import archive
        a = archive.serialize(self.obj)
        b = archive.serialize(copy.deepcopy(self.obj))
        self.assertEqual(a, b)


class InvariantCase(unittest.TestCase):
    """The invariants must fire. Each test breaks one field and expects the
    named rule to catch it."""

    @classmethod
    def setUpClass(cls):
        cls.da = dbfixture.da()
        cls.obj = dbfixture.site_objects()[-1]

    def _tamper(self, mutate):
        obj = copy.deepcopy(self.obj)
        mutate(obj)
        with self.assertRaises(AssertionError) as ctx:
            compute._assert_invariants(self.da, obj, D.fromisoformat(obj["date"]))
        return str(ctx.exception)

    def test_br6_catches_a_broken_focus_decomposition(self):
        msg = self._tamper(lambda o: o["focus"].__setitem__("remainder", 0.0))
        self.assertIn("BR-6", msg)

    def test_br9_catches_a_moved_headline(self):
        msg = self._tamper(
            lambda o: o["omni"]["invariance"].__setitem__("headline_omni_on", 1.0))
        self.assertIn("BR-9", msg)

    def test_br9_catches_omni_exceeding_the_headline(self):
        msg = self._tamper(
            lambda o: o["omni"]["invariance"].__setitem__(
                "attributed_exceeds_headline", True))
        self.assertIn("BR-9", msg)

    def test_br11_catches_slices_that_do_not_sum(self):
        msg = self._tamper(
            lambda o: o["slices"]["region"][0].__setitem__("net_sales", 1.0))
        self.assertIn("BR-11", msg)

    def test_br11_catches_a_broken_drill_level(self):
        msg = self._tamper(
            lambda o: o["drill"].__setitem__("children_sum", 1.0))
        self.assertIn("BR-11", msg)

    def test_br12_catches_a_buyer_count_that_drifts(self):
        msg = self._tamper(
            lambda o: o["customer"]["day"]["ty"].__setitem__("total_buyers", 7))
        self.assertIn("BR-12", msg)

    def test_br20_catches_a_tree_that_does_not_compose(self):
        eid = sorted(k for k, v in self.obj["stores"].items()
                     if v.get("tree", {}).get("available"))[0]
        msg = self._tamper(
            lambda o: o["stores"][eid]["tree"].__setitem__("gap", 1.0))
        self.assertIn("BR-20", msg)

    def test_narrative_ceiling_is_enforced(self):
        msg = self._tamper(
            lambda o: o.__setitem__("narrative", ". ".join(["A 1"] * 9)))
        self.assertIn("sentences", msg)


class PanelCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.da = dbfixture.da()
        cls.obj = dbfixture.site_objects()[-1]

    def test_omni_panel_carries_both_bases_for_every_family(self):
        fams = self.obj["omni"]["families"]
        for key in ("BOPIS", "RTD", "OOFIS", "CR"):
            self.assertIn("recognized", fams[key])
            self.assertIn("all_inclusive", fams[key])
            self.assertIn("basis_warning", fams[key])
        self.assertIn("BORIS", fams)

    def test_omni_invariance_equals_the_headline(self):
        inv = self.obj["omni"]["invariance"]
        self.assertEqual(inv["headline_omni_on"], self.obj["headline"]["net_sales"])
        self.assertEqual(inv["headline_omni_off"], inv["headline_omni_on"])

    def test_customer_panel_and_headline_agree(self):
        self.assertEqual(self.obj["customer"]["day"]["ty"]["new_buyers"],
                         self.obj["headline"]["new_customers"])
        self.assertEqual(self.obj["customer"]["day"]["ty"]["total_buyers"],
                         self.obj["headline"]["transactions"])

    def test_merch_categories_sum_to_the_posted_total(self):
        r = self.obj["merch"]["categories"]["reconciliation"]
        self.assertAlmostEqual(r["sum_of_categories"], r["entity_day_total"],
                               places=2)

    def test_plan_status_shows_all_three_grains(self):
        ps = self.obj["plan_status"]
        self.assertEqual(set(ps["grain_mix"]), {"DAY", "WEEK", "NONE"})
        self.assertIsNone(ps["no_plan"]["attainment"])

    def test_exceptions_are_ordered_deterministically(self):
        a = compute.build_flash(self.da, ANCHOR)["exceptions"]
        b = compute.build_flash(self.da, ANCHOR)["exceptions"]
        self.assertEqual([e["title"] for e in a], [e["title"] for e in b])
        severities = [compute.__dict__ and e["severity"] for e in a]
        order = {"escalation": 0, "adverse": 1, "watch": 2, "favourable": 3}
        self.assertEqual(severities, sorted(severities, key=lambda s: order[s]))

    def test_all_four_new_exception_families_can_fire(self):
        kinds = set(e["kind"] for e in self.obj["exceptions"])
        for kind in ("omni", "category", "new_to_file", "conversion"):
            self.assertIn(kind, kinds, kind)

    def test_exception_thresholds_come_from_the_catalog(self):
        from flash.catalog import THRESHOLDS
        for e in self.obj["exceptions"]:
            if e["kind"] == "omni":
                self.assertEqual(e["threshold"], THRESHOLDS["omni_family_vs_ly"])
            if e["kind"] == "category":
                self.assertEqual(e["threshold"],
                                 THRESHOLDS["category_vs_fleet_pts"])


class UptLeverCase(unittest.TestCase):
    """UPT is a lever the field can move, so it carries a comparison, a rank,
    an exception and a storyline — the same treatment conversion gets."""

    @classmethod
    def setUpClass(cls):
        cls.da = dbfixture.da()
        cls.obj = dbfixture.site_objects()[-1]

    def test_headline_carries_upt_against_ly(self):
        h = self.obj["headline"]
        for key in ("upt_pct_vs_ly", "ast_pct_vs_ly", "aus_pct_vs_ly",
                    "ly_upt", "units_pct_vs_ly"):
            self.assertIn(key, h, key)
            self.assertIsNotNone(h[key], key)

    def test_upt_vs_ly_is_the_comp_basis_not_the_reported_basis(self):
        cb = self.da.comp_basket(ANCHOR)
        self.assertAlmostEqual(self.obj["headline"]["upt_pct_vs_ly"],
                               cb["upt_pct"], places=12)
        self.assertEqual(cb["members"], len(self.da.comp_set(ANCHOR)))

    def test_comp_basket_identities_hold(self):
        cb = self.da.comp_basket(ANCHOR)
        self.assertAlmostEqual(cb["upt"], cb["ty_units"] / cb["ty_transactions"],
                               places=12)
        self.assertAlmostEqual(cb["ast"] / cb["aus"], cb["upt"], places=9)
        self.assertAlmostEqual(cb["ly_ast"] / cb["ly_aus"], cb["ly_upt"],
                               places=9)

    def test_window_upt_is_aggregated_not_averaged(self):
        w = self.da.basket_window(ANCHOR, "WTD")
        hand_u = hand_t = 0
        for d in self.da.window_dates(ANCHOR, "WTD"):
            ids = self.da.scope_ids()
            hand_u += self.da._sum_col("units", d, ids)
            hand_t += self.da._sum_col("transactions", d, ids)
        self.assertAlmostEqual(w["upt"], hand_u / float(hand_t), places=12)

    def test_upt_is_a_selectable_rank_kpi(self):
        self.assertIn("upt", self.obj["ranks"])
        top = self.obj["ranks"]["upt"]["top"]
        self.assertTrue(top)
        self.assertEqual([r["value"] for r in top],
                         sorted([r["value"] for r in top], reverse=True))

    def test_upt_movers_rank_the_move_not_the_level(self):
        mv = self.obj["upt_movers"]
        self.assertEqual(mv["top"][0]["entity_id"], seed.ATTACH_STORE)
        self.assertGreater(mv["top"][0]["upt_pct"],
                           mv["top"][1]["upt_pct"] * 2)

    def test_the_upt_exception_fires_once_and_favourably(self):
        upt = [e for e in self.obj["exceptions"] if e["kind"] == "upt"]
        self.assertEqual(len(upt), 1)
        self.assertEqual(upt[0]["severity"], "favourable")
        self.assertEqual(upt[0]["entities"], [seed.ATTACH_STORE])

    def test_the_upt_threshold_comes_from_the_catalog(self):
        from flash.catalog import THRESHOLDS
        upt = [e for e in self.obj["exceptions"] if e["kind"] == "upt"][0]
        self.assertEqual(upt["threshold"], THRESHOLDS["upt_vs_baseline_pct"])

    def test_storyline_22_is_the_basket_lever_not_the_footfall_lever(self):
        eid = seed.ATTACH_STORE
        b = self.obj["stores"][eid]["headline"]
        self.assertGreater(b["upt_pct_vs_ly"], 0.10)
        self.assertGreater(b["ast_pct_vs_ly"], 0.08)
        self.assertLess(abs(b["conversion_bps_vs_ly"]), 120)

    def test_storyline_22_tree_names_the_basket(self):
        t = self.obj["stores"][seed.ATTACH_STORE]["tree"]
        drivers = dict((x["driver"], x["contribution"]) for x in t["drivers"])
        split = dict((x["driver"], x["contribution"]) for x in t["ast_split"])
        self.assertGreater(t["gap"], 0)
        self.assertGreater(drivers["ast"], 0)
        self.assertGreater(split["upt"], 0)
        self.assertGreater(split["upt"], abs(split["aus"]))

    def test_extract_carries_upt_and_its_comparison(self):
        for key in ("upt", "upt_vs_ly", "ast_vs_ly", "aus_vs_ly"):
            self.assertIn(key, self.obj["extract"]["columns"], key)
        for row in self.obj["extract"]["rows"]:
            b = self.obj["stores"][row["entity_id"]]["headline"]
            self.assertEqual(row["upt"], b["upt"])
            self.assertEqual(row["upt_vs_ly"], b["upt_pct_vs_ly"])

    def test_upt_varies_by_day_so_a_coaching_signal_is_possible(self):
        """A constant UPT makes the exception unfireable and the AUS x UPT
        split decorative."""
        seen = set()
        for d in (ANCHOR, ANCHOR - dt.timedelta(days=1),
                  ANCHOR - dt.timedelta(days=2)):
            seen.add(round(self.da.basket(d, entity_id="LB-001")["upt"], 4))
        self.assertGreater(len(seen), 1)


class PersonaCase(unittest.TestCase):
    """BR-18: only the scope differs between personas, never the number."""

    @classmethod
    def setUpClass(cls):
        cls.da = dbfixture.da()
        cls.obj = dbfixture.site_objects()[-1]

    def test_the_owner_matrix_is_the_page_structure(self):
        want = {
            "corporate": ("brand", "region", "affiliate", "doors"),
            "brand": ("region", "affiliate", "district", "doors"),
            "region": ("brand", "affiliate", "district", "doors"),
            "affiliate": ("brand", "district", "doors"),
            "field": ("district", "doors"),
        }
        for key, p in self.obj["personas"].items():
            self.assertEqual(tuple(p["rollups"]), want[p["kind"]], key)

    def test_thirteen_landings_exist(self):
        kinds = {}
        for p in self.obj["personas"].values():
            kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
        self.assertEqual(kinds, {"corporate": 1, "brand": 3, "region": 6,
                                 "affiliate": 2, "field": 1})

    def test_corporate_headline_equals_the_day_headline(self):
        p = self.obj["personas"]["corporate/corporate"]
        self.assertEqual(p["headline"]["net_sales"],
                         self.obj["headline"]["net_sales"])
        self.assertEqual(p["display"]["net_sales"],
                         self.obj["display"]["net_sales"])

    def test_a_figure_is_identical_across_every_persona_that_shows_it(self):
        """West's net sales appear on the Region landing, inside Corporate's
        region rollup and inside the US affiliate's district rollup. All three
        must be the same number."""
        region = self.obj["personas"]["region/West"]["headline"]["net_sales"]
        corp = next(r for r in self.obj["personas"]["corporate/corporate"]
                    ["rollups"]["region"] if r["key"] == "West")
        self.assertAlmostEqual(region, corp["net_sales"], places=2)
        slice_row = next(r for r in self.obj["slices"]["region"]
                         if r["key"] == "West")
        self.assertAlmostEqual(region, slice_row["net_sales"], places=2)

    def test_brand_persona_matches_the_brand_slice(self):
        for b in ("LUM", "ATN", "BOT"):
            p = self.obj["personas"]["brand/%s" % b]["headline"]["net_sales"]
            s = next(r for r in self.obj["slices"]["brand"] if r["key"] == b)
            self.assertAlmostEqual(p, s["net_sales"], places=2, msg=b)

    def test_persona_exceptions_are_computed_in_the_personas_own_scope(self):
        """Not filtered from the fleet list — computed in the scope.

        Filtering gave a Canada page a headline reading 'Makeup comps −6.2%'
        over a move reading +16.9%, because the title came from the fleet and
        the figure came from Canada. Scoping makes the title and the figure the
        same computation, and it also lets a persona see a move that is an
        exception in its own scope but not fleet-wide — which is the whole
        point of having a persona view."""
        from flash import compute as _c, customer as _cu, merch as _m, omni as _o
        from flash.focus import build_exceptions
        for key, p in self.obj["personas"].items():
            want = build_exceptions(self.da, ANCHOR, _o, _cu, _m, **p["scope"])
            self.assertEqual([e["title"] for e in p["exceptions"]],
                             [e["title"] for e in want], key)

    def test_persona_exceptions_only_name_doors_the_persona_owns(self):
        for key, p in self.obj["personas"].items():
            ids = set(self.da.scope_ids(**p["scope"]))
            for e in p["exceptions"]:
                for eid in e["entities"]:
                    self.assertIn(eid, ids, "%s names %s" % (key, eid))


class ExtractCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.obj = dbfixture.site_objects()[-1]

    def test_extract_rows_come_from_the_store_blocks(self):
        ex = self.obj["extract"]
        for row in ex["rows"]:
            b = self.obj["stores"][row["entity_id"]]
            self.assertEqual(row["net_sales_usd"], b["headline"]["net_sales"])
            self.assertEqual(row["conversion"], b["headline"]["conversion"])
            self.assertEqual(row["new_customers"], b["headline"]["new_customers"])

    def test_extract_covers_every_posted_door_and_no_others(self):
        posted = sorted(k for k, v in self.obj["stores"].items() if v["posted"])
        self.assertEqual([r["entity_id"] for r in self.obj["extract"]["rows"]],
                         posted)

    def test_extract_doors_plus_ecom_equal_the_headline(self):
        doors = sum(r["net_sales_usd"] for r in self.obj["extract"]["rows"])
        ecom = sum(s["net_sales"] for s in self.obj["slices"]["channel"]
                   if s["key"] == "ECOM")
        self.assertAlmostEqual(doors + ecom, self.obj["headline"]["net_sales"],
                               places=2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
