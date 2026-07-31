# -*- coding: utf-8 -*-
"""Render tests — the surfaces, and whether they agree with each other.

A renderer bug is worse than a catalog bug: the catalog fails loudly, a
renderer fails by printing a plausible wrong number on one surface and the
right one on another. So the tests here mostly compare surfaces to each other
and to the object they were built from, rather than checking that HTML exists.

Run: python3 -m unittest tests.test_render
"""
import csv
import datetime as dt
import hashlib
import io
import json
import os
import posixpath
import re
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tests import dbfixture                             # noqa: E402
import seed                                             # noqa: E402
from flash import render_email, render_site             # noqa: E402

HREF_RE = re.compile(r'(?:href|src)="([^"]+)"')
SITE_PAGE_KB = 150
EMAIL_KB = 120


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return fh.read()


class SiteStructureCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.objs = dbfixture.site_objects()
        cls.anchor = cls.objs[-1]["date"]

    def _pages(self):
        for r, _d, files in os.walk(self.dir):
            for f in files:
                if f.endswith(".html"):
                    yield os.path.join(r, f)

    def test_every_page_type_is_generated(self):
        for rel in ("index.html", "assets/site.css",
                    "day/%s.html" % self.anchor,
                    "email/%s.html" % self.anchor,
                    "corporate/%s.html" % self.anchor,
                    "field/%s.html" % self.anchor,
                    "brand/LUM/%s.html" % self.anchor,
                    "region/west/%s.html" % self.anchor,
                    "affiliate/CA/%s.html" % self.anchor,
                    "district/MW-1/%s.html" % self.anchor,
                    "store/LB-015/%s.html" % self.anchor,
                    "store/LB-015/hourly/%s.html" % self.anchor,
                    "store/LB-015/tree/%s.html" % self.anchor,
                    "category/fragrance/%s.html" % self.anchor,
                    "sku/%s.html" % seed.BREAKOUT_SKU,
                    "omni/BOPIS/%s.html" % self.anchor,
                    "omni/BORIS/%s.html" % self.anchor,
                    "customer/%s.html" % self.anchor,
                    "merch/%s.html" % self.anchor,
                    "rank/conversion/%s.html" % self.anchor,
                    "extracts/%s-doors.csv" % self.anchor):
            self.assertTrue(os.path.exists(os.path.join(self.dir, rel)), rel)

    def test_every_relative_link_resolves(self):
        bad, checked = [], 0
        for p in self._pages():
            base = os.path.relpath(os.path.dirname(p), self.dir).replace(os.sep, "/")
            for h in HREF_RE.findall(_read(p)):
                if h.startswith(("http://", "https://", "mailto:", "#", "data:")):
                    continue
                checked += 1
                t = posixpath.normpath(posixpath.join(base, h.split("#")[0]))
                if t.startswith("..") or not os.path.exists(
                        os.path.join(self.dir, t)):
                    bad.append((os.path.relpath(p, self.dir), h))
        self.assertGreater(checked, 500)
        self.assertEqual(bad[:5], [], "%d dead links" % len(bad))

    def test_no_page_references_an_external_asset(self):
        for p in self._pages():
            txt = _read(p)
            self.assertNotIn("http://", txt, p)
            self.assertNotIn("https://", txt, p)

    def test_every_page_declares_utf8(self):
        for p in self._pages():
            self.assertIn('<meta charset="utf-8">', _read(p), p)

    def test_page_size_budgets(self):
        for p in self._pages():
            kb = os.path.getsize(p) / 1024.0
            budget = EMAIL_KB if "/email/" in p.replace(os.sep, "/") else SITE_PAGE_KB
            self.assertLess(kb, budget, "%s is %.0f KB" % (p, kb))

    def test_the_calculator_is_the_only_javascript(self):
        for p in self._pages():
            txt = _read(p)
            scripts = txt.count("<script")
            rel = os.path.relpath(p, self.dir).replace(os.sep, "/")
            if "/tree/" in rel:
                if "Tree unavailable" in txt:
                    # No traffic, no tree, no calculator to check itself
                    # against — the page says so instead (BR-15).
                    self.assertEqual(scripts, 0, rel)
                else:
                    # one JSON data block + one behaviour script
                    self.assertEqual(scripts, 2, rel)
            else:
                self.assertEqual(scripts, 0, rel)

    def test_summary_days_do_not_link_to_pages_that_do_not_exist(self):
        summary = [o for o in self.objs if o["depth"] == "summary"]
        self.assertTrue(summary)
        for o in summary:
            txt = _read(os.path.join(self.dir, "day", "%s.html" % o["date"]))
            self.assertIn("Drill-down tier", txt)
            self.assertNotIn("corporate/%s.html" % o["date"], txt)


class DeterminismCase(unittest.TestCase):
    def test_two_renders_are_byte_identical(self):
        hashes = []
        for _ in range(2):
            path = tempfile.mkdtemp(prefix="opsflash-det-")
            try:
                dbfixture.build_site_into(path)
                h = hashlib.sha256()
                for r, dirs, files in os.walk(path):
                    dirs.sort()
                    for f in sorted(files):
                        full = os.path.join(r, f)
                        h.update(os.path.relpath(full, path).encode("utf-8"))
                        with open(full, "rb") as fh:
                            h.update(fh.read())
                hashes.append(h.hexdigest())
            finally:
                shutil.rmtree(path, ignore_errors=True)
        self.assertEqual(hashes[0], hashes[1])

    def test_no_wall_clock_in_the_renderers(self):
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("render_site.py", "render_email.py"):
            with open(os.path.join(root, "flash", name), encoding="utf-8") as fh:
                code = "\n".join(l for l in fh.read().splitlines()
                                 if not l.lstrip().startswith("#"))
            for banned in ("datetime.now(", "date.today(", "time.time(",
                           "import random", "utcnow("):
                self.assertNotIn(banned, code, "%s: %s" % (name, banned))


class CrossSurfaceCase(unittest.TestCase):
    """BR-13 / BR-21: the site, the digest and the extract read one object."""

    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]
        cls.day = _read(os.path.join(cls.dir, "day", "%s.html" % cls.date))
        cls.email = _read(os.path.join(cls.dir, "email", "%s.html" % cls.date))
        cls.corp = _read(os.path.join(cls.dir, "corporate", "%s.html" % cls.date))
        with open(os.path.join(cls.dir, "extracts",
                               "%s-doors.csv" % cls.date), encoding="utf-8") as fh:
            cls.rows = list(csv.DictReader(fh))

    def test_headline_display_string_appears_on_every_surface(self):
        s = self.obj["display"]["net_sales"]
        for name, txt in (("day", self.day), ("email", self.email),
                          ("corporate", self.corp)):
            self.assertIn(s, txt, name)

    def test_comp_and_plan_strings_agree_between_site_and_digest(self):
        for key in ("comp_pct", "plan_attainment", "transactions", "ast",
                    "conversion", "omni_penetration"):
            s = self.obj["display"][key]
            self.assertIn(s, self.day, key)
            self.assertIn(s, self.email, key)

    def test_extract_cells_equal_the_object_and_the_store_page(self):
        for row in self.rows[:6]:
            eid = row["entity_id"]
            b = self.obj["stores"][eid]
            self.assertAlmostEqual(float(row["net_sales_usd"]),
                                   b["headline"]["net_sales"], places=2)
            page = _read(os.path.join(self.dir, "store", eid, "%s.html" % self.date))
            from flash import fmt
            self.assertIn(fmt.money_compact(b["headline"]["net_sales"]), page)

    def test_extract_reconciles_to_the_headline(self):
        doors = sum(float(r["net_sales_usd"]) for r in self.rows)
        ecom = sum(s["net_sales"] for s in self.obj["slices"]["channel"]
                   if s["key"] == "ECOM")
        self.assertAlmostEqual(doors + ecom, self.obj["headline"]["net_sales"],
                               places=2)

    def test_extract_is_byte_stable(self):
        a = render_site.render_extract_csv(self.obj)
        b = render_site.render_extract_csv(self.obj)
        self.assertEqual(a, b)
        self.assertEqual(a, _read(os.path.join(
            self.dir, "extracts", "%s-doors.csv" % self.date)))

    def test_a_door_with_no_traffic_has_an_empty_conversion_cell(self):
        dark = set(e for e, d in seed.TRAFFIC_MISSING
                   if d.isoformat() == self.date)
        for row in self.rows:
            if row["entity_id"] in dark:
                self.assertEqual(row["conversion"], "")
                self.assertNotEqual(row["conversion"], "0")

    def test_digest_subject_matches_the_body(self):
        d = self.obj["display"]
        self.assertEqual(render_email.subject_line(self.obj), self.obj["subject"])
        for token in (d["date_short"], d["net_sales"], d["comp_pct"],
                      d["plan_attainment"]):
            self.assertIn(token, self.obj["subject"])
            self.assertIn(token, self.email)

    def test_digest_is_inline_only_and_phone_shaped(self):
        self.assertNotIn("<style", self.email)
        self.assertNotIn("<script", self.email)
        self.assertNotIn("http://", self.email)
        self.assertNotIn("https://", self.email)
        self.assertLess(len(self.email.encode("utf-8")) / 1024.0, EMAIL_KB)

    def test_digest_deep_links_resolve_into_the_site(self):
        base = "email"
        found = 0
        for h in HREF_RE.findall(self.email):
            if h.startswith(("http", "#", "mailto:")):
                continue
            found += 1
            t = posixpath.normpath(posixpath.join(base, h))
            self.assertTrue(os.path.exists(os.path.join(self.dir, t)), h)
        self.assertGreater(found, 5)


class TreeCalculatorCase(unittest.TestCase):
    """BR-20: the calculator consumes catalog values and holds no formula."""

    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]
        cls.page = _read(os.path.join(cls.dir, "store", seed.CONV_STORE,
                                      "tree", "%s.html" % cls.date))
        m = re.search(r'<script id="tree-payload" type="application/json">'
                      r'(.*?)</script>', cls.page, re.S)
        cls.payload = json.loads(m.group(1))

    def test_payload_is_the_catalogs_own_driver_values(self):
        t = self.obj["stores"][seed.CONV_STORE]["tree"]["payload"]
        for key in ("traffic", "conversion", "ast", "aus", "upt", "net_sales",
                    "ly_traffic", "ly_conversion", "ly_ast", "ly_net_sales"):
            self.assertAlmostEqual(self.payload[key], t[key], places=9, msg=key)

    def test_the_identity_reproduces_the_catalog_figure(self):
        p = self.payload
        self.assertAlmostEqual(p["traffic"] * p["conversion"] * p["ast"],
                               p["net_sales"], places=2)
        self.assertAlmostEqual(p["aus"] * p["upt"], p["ast"], places=9)
        self.assertAlmostEqual(p["ly_traffic"] * p["ly_conversion"] * p["ly_ast"],
                               p["ly_net_sales"], places=2)

    def test_the_javascript_holds_no_business_numbers(self):
        """Any numeric literal in the calculator must be arithmetic scaffolding
        (0, 1, 100, rounding factors, slider bounds) — never a figure that
        belongs to the catalog."""
        js = render_site.WHATIF_JS
        allowed = {
            "0", "1", "2",          # identity / sign scaffolding
            "10", "50", "100",      # slider bounds and percent scaling
            "1000", "1000000",      # K and M thresholds in the formatter
            "0.01",                 # the cent tolerance of the self-check
        }
        for lit in re.findall(r"(?<![\w.])\d+(?:\.\d+)?", js):
            self.assertIn(lit, allowed, "unexpected literal %s in the calculator" % lit)

    def test_the_page_states_its_self_check(self):
        self.assertIn("wi-check", self.page)
        self.assertIn("SELF-CHECK FAILED", render_site.WHATIF_JS)

    def test_tree_contributions_are_printed_and_compose(self):
        from flash import fmt
        t = self.obj["stores"][seed.CONV_STORE]["tree"]
        for driver in t["drivers"]:
            self.assertIn(fmt.money_signed_exact(driver["contribution"]), self.page)
        self.assertIn(fmt.money_signed_exact(t["gap"]), self.page)

    def test_three_sampled_store_days_compose_exactly(self):
        n = 0
        for obj in dbfixture.site_objects():
            if obj["depth"] != "full":
                continue
            for eid in sorted(obj["stores"])[:3]:
                t = obj["stores"][eid].get("tree") or {}
                if not t.get("available"):
                    continue
                n += 1
                s = sum(x["contribution"] for x in t["drivers"])
                self.assertAlmostEqual(s, t["gap"], places=1)
        self.assertGreaterEqual(n, 3)


TAG_RE = re.compile(r"<[^>]+>")
JSON_RE = re.compile(r'<script id="tree-payload"[^>]*>.*?</script>', re.S)
MONEY_RE = re.compile(r"^[+\u2212-]?\$[\d,]+(?:\.\d+)?$")


def _visible(html):
    """Page text with tags and the JSON payload removed — what a reader sees.

    The payload block is stripped deliberately: a currency stated only inside a
    machine-readable blob is not a disclosure to a human, which is exactly the
    defect this helper exists to catch."""
    return TAG_RE.sub(" ", JSON_RE.sub(" ", html))


def _money(text):
    return float(text.replace("\u2212", "-").replace("+", "")
                 .replace("$", "").replace(",", ""))


class CurrencyDisclosureCase(unittest.TestCase):
    """BR-16: a converted figure without its rate cannot be checked, so the
    NUMERIC rate appears on every page that shows one."""

    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]
        cls.ca_doors = sorted(
            eid for eid, b in cls.obj["stores"].items()
            if b["currency"] != cls.obj["reporting_currency"])
        cls.rate = str(seed.FX_CAD_PER_USD)

    def test_the_fixture_actually_has_foreign_currency_doors(self):
        self.assertGreaterEqual(len(self.ca_doors), 4)

    def test_every_ca_door_page_states_the_numeric_rate(self):
        for eid in self.ca_doors:
            txt = _visible(_read(os.path.join(self.dir, "store", eid,
                                              "%s.html" % self.date)))
            self.assertIn(self.rate, txt, "%s door page omits the rate" % eid)
            self.assertIn("CAD", txt, eid)
            self.assertIn("USD", txt, eid)

    def test_every_ca_tree_page_states_the_numeric_rate(self):
        for eid in self.ca_doors:
            path = os.path.join(self.dir, "store", eid, "tree",
                                "%s.html" % self.date)
            if not os.path.exists(path):
                continue
            txt = _visible(_read(path))
            self.assertIn(self.rate, txt, "%s tree page omits the rate" % eid)

    def test_every_ca_hourly_page_states_the_numeric_rate(self):
        for eid in self.ca_doors:
            path = os.path.join(self.dir, "store", eid, "hourly",
                                "%s.html" % self.date)
            if not os.path.exists(path):
                continue
            self.assertIn(self.rate, _visible(_read(path)), eid)

    def test_the_canadian_district_page_states_the_numeric_rate(self):
        ca_districts = sorted(set(
            self.obj["stores"][eid]["district_id"] for eid in self.ca_doors))
        self.assertTrue(ca_districts)
        for d in ca_districts:
            txt = _visible(_read(os.path.join(self.dir, "district", d,
                                              "%s.html" % self.date)))
            self.assertIn(self.rate, txt, d)

    def test_the_affiliate_landing_states_the_numeric_rate(self):
        txt = _visible(_read(os.path.join(self.dir, "affiliate", "CA",
                                          "%s.html" % self.date)))
        self.assertIn(self.rate, txt)

    def test_a_us_door_page_does_not_carry_a_conversion_note(self):
        txt = _visible(_read(os.path.join(self.dir, "store", "LB-001",
                                          "%s.html" % self.date)))
        self.assertNotIn("converted at", txt)

    def test_tree_payload_roundtrips_to_the_native_figure(self):
        """A reader converting the tree's USD figure back at the stated rate
        must land on the door's own posted total, not a cent away from it."""
        for eid in self.ca_doors:
            path = os.path.join(self.dir, "store", eid, "tree",
                                "%s.html" % self.date)
            if not os.path.exists(path):
                continue
            payload = json.loads(re.search(
                r'<script id="tree-payload"[^>]*>(.*?)</script>',
                _read(path), re.S).group(1))
            self.assertTrue(payload["converted"], eid)
            self.assertAlmostEqual(
                payload["net_sales"] * payload["fx_units_per_usd"],
                payload["net_sales_local"], places=2, msg=eid)
            self.assertAlmostEqual(
                payload["ly_net_sales"] * payload["fx_units_per_usd"],
                payload["ly_net_sales_local"], places=2, msg=eid)


class DisplayedColumnsAddUpCase(unittest.TestCase):
    """A column a reader adds up has to add up. The object's arithmetic being
    right is not enough if the printed figures round apart."""

    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.obj = dbfixture.site_objects()[-1]

    def _tables_with_totals(self, html):
        for tbl in re.findall(r"<table[^>]*>(.*?)</table>", html, re.S):
            if 'class="tot"' not in tbl:
                continue
            rows = []
            for m in re.finditer(r"<tr([^>]*)>(.*?)</tr>", tbl, re.S):
                attrs, body = m.group(1), m.group(2)
                cells = [TAG_RE.sub("", c).strip()
                         for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", body, re.S)]
                if cells:
                    rows.append(('class="tot"' in attrs, cells))
            yield rows

    def test_every_tree_pages_contribution_columns_sum_to_their_totals(self):
        checked = 0
        for r, _d, files in os.walk(os.path.join(self.dir, "store")):
            if os.path.basename(r) != "tree":
                continue
            for f in sorted(files):
                html = _read(os.path.join(r, f))
                if "Tree unavailable" in html:
                    continue
                for rows in self._tables_with_totals(html):
                    parts, total = [], None
                    for is_total, cells in rows:
                        if len(cells) < 2 or not MONEY_RE.match(cells[1]):
                            continue
                        if is_total:
                            total = _money(cells[1])
                        elif cells[0] != "Residual interaction":
                            parts.append(_money(cells[1]))
                    if total is None or not parts:
                        continue
                    checked += 1
                    self.assertAlmostEqual(
                        sum(parts), total, places=2,
                        msg="%s: parts %s sum to %.2f against a printed total "
                            "of %.2f" % (os.path.join(r, f), parts,
                                         sum(parts), total))
        self.assertGreater(checked, 20)

    def test_the_tree_column_matches_the_objects_own_gap(self):
        from flash import render_site as rs
        for eid in sorted(self.obj["stores"]):
            t = self.obj["stores"][eid].get("tree") or {}
            if not t.get("available"):
                continue
            contribs, split = rs.tree_contributions(t)
            self.assertAlmostEqual(sum(c["contribution"] for c in contribs),
                                   t["gap"], places=2, msg=eid)
            ast = next(c["contribution"] for c in contribs
                       if c["driver"] == "ast")
            self.assertAlmostEqual(sum(c["contribution"] for c in split),
                                   ast, places=2, msg=eid)

    def test_contributions_are_displayed_at_cent_precision(self):
        """Compact money rounds under $1,000 to whole dollars, which is what
        broke the column. Every contribution must carry cents."""
        page = _read(os.path.join(self.dir, "store", seed.CONV_STORE, "tree",
                                  "%s.html" % self.obj["date"]))
        t = self.obj["stores"][seed.CONV_STORE]["tree"]
        from flash import fmt
        for driver in t["drivers"]:
            exact = fmt.money_signed_exact(driver["contribution"])
            self.assertIn(exact, page, exact)
            self.assertIn(".", exact)

    def test_category_grid_total_matches_its_rows(self):
        html = _read(os.path.join(self.dir, "merch",
                                  "%s.html" % self.obj["date"]))
        for rows in self._tables_with_totals(html):
            parts, total = [], None
            for is_total, cells in rows:
                if len(cells) < 3 or not MONEY_RE.match(cells[2]):
                    continue
                if is_total:
                    total = _money(cells[2])
                else:
                    parts.append(_money(cells[2]))
            if total is not None and parts:
                self.assertAlmostEqual(sum(parts), total, places=2)


class PersonaPageCase(unittest.TestCase):
    """BR-18 on the surface: the same figure, wherever it appears."""

    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]

    def _page(self, rel):
        return _read(os.path.join(self.dir, rel))

    def test_every_persona_page_carries_the_kpi_headline_row(self):
        pages = ["corporate/%s.html" % self.date, "field/%s.html" % self.date,
                 "brand/LUM/%s.html" % self.date,
                 "region/west/%s.html" % self.date,
                 "affiliate/US/%s.html" % self.date]
        for rel in pages:
            txt = self._page(rel)
            for label in ("Net sales", "Comp", "Plan attainment", "AST", "AUS",
                          "UPT", "Traffic", "Conversion", "New customers",
                          "Returns", "Discounts", "OMNI penetration",
                          "Portfolio / trading"):
                self.assertIn(label, txt, "%s missing %s" % (rel, label))

    def test_each_persona_opens_on_the_owners_scoping_matrix(self):
        want = {
            "corporate/%s.html": "Brand · Region · Affiliate · top doors",
            "brand/LUM/%s.html": "Region · Affiliate · Field Leadership · Doors",
            "region/west/%s.html":
                "Brand · Affiliate · Field Leadership · Districts · Doors",
            "affiliate/US/%s.html": "Brands · Field Leadership · Districts · Doors",
            "field/%s.html": "Districts · Doors",
        }
        for rel, note in want.items():
            self.assertIn(note, self._page(rel % self.date), rel)

    def test_a_regions_figure_is_identical_on_three_pages(self):
        from flash import fmt
        s = fmt.money_compact(
            self.obj["personas"]["region/West"]["headline"]["net_sales"])
        for rel in ("region/west/%s.html", "corporate/%s.html",
                    "day/%s.html"):
            self.assertIn(s, self._page(rel % self.date), rel)

    def test_canada_page_discloses_the_fixed_rate(self):
        txt = self._page("affiliate/CA/%s.html" % self.date)
        self.assertIn("CAD", txt)
        self.assertIn("1.35", txt)

    def test_corporate_landing_has_the_deck_visuals(self):
        txt = self._page("corporate/%s.html" % self.date)
        self.assertIn("Timeframe grid", txt)
        self.assertGreaterEqual(txt.count("<svg"), 4)      # 3 donuts + trends
        self.assertIn("<details class=\"rank\"", txt)


class OpsTableCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.day = _read(os.path.join(cls.dir, "day", "%s.html" % cls.obj["date"]))

    def test_three_tier_table_and_status_funnel_are_present(self):
        for token in ("Comp trading", "All trading", "Total", "Portfolio",
                      "% trading", "% comp of trading"):
            self.assertIn(token, self.day, token)

    def test_the_fav_unfav_key_is_stated(self):
        self.assertIn("within ±5%", self.day)
        self.assertIn("unfavourable", self.day)

    def test_plan_grain_block_names_all_three_grains(self):
        for token in ("Day-planned", "Week-planned", "No-plan", "no plan"):
            self.assertIn(token, self.day, token)

    def test_omni_invariance_is_shown_not_claimed(self):
        from flash import fmt
        v = fmt.money_exact(self.obj["headline"]["net_sales"])
        self.assertIn("Omni invariance", self.day)
        self.assertGreaterEqual(self.day.count(v), 2)

    def test_hourly_page_states_its_reconciliation(self):
        txt = _read(os.path.join(self.dir, "store", "LB-018", "hourly",
                                 "%s.html" % self.obj["date"]))
        self.assertIn("unaudited", txt)
        self.assertIn("system of record", txt)
        self.assertIn("reconciliation gap", txt.lower())

    def test_rank_page_separates_unavailable_doors(self):
        txt = _read(os.path.join(self.dir, "rank", "conversion",
                                 "%s.html" % self.obj["date"]))
        self.assertIn("Not ranked", txt)
        self.assertIn("no traffic posted", txt)


if __name__ == "__main__":
    unittest.main(verbosity=2)
