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


class UptSurfaceCase(unittest.TestCase):
    """UPT vs LY has to appear wherever UPT appears, on every surface."""

    @classmethod
    def setUpClass(cls):
        cls.dir = dbfixture.site_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]

    def _page(self, rel):
        return _read(os.path.join(self.dir, rel))

    def test_upt_vs_ly_appears_on_every_persona_page(self):
        s = self.obj["display"]["upt_vs_ly"]
        for rel in ("day/%s.html", "corporate/%s.html", "field/%s.html",
                    "email/%s.html"):
            txt = self._page(rel % self.date)
            self.assertIn("UPT", txt, rel)
            self.assertIn(s, txt, "%s omits the fleet UPT vs LY" % rel)

    def test_upt_vs_ly_appears_on_a_store_page(self):
        from flash import fmt
        eid = seed.ATTACH_STORE
        b = self.obj["stores"][eid]["headline"]
        txt = self._page("store/%s/%s.html" % (eid, self.date))
        self.assertIn(fmt.ratio(b["upt"]), txt)
        self.assertIn(fmt.pct(b["upt_pct_vs_ly"]), txt)

    def test_the_upt_rank_page_exists_and_carries_the_movers_table(self):
        txt = self._page("rank/upt/%s.html" % self.date)
        self.assertIn("Biggest UPT movers vs LY", txt)
        self.assertIn("Doors losing basket", txt)
        self.assertIn(self.obj["upt_movers"]["top"][0]["name"], txt)

    def test_upt_appears_in_the_extract_csv_and_matches_the_page(self):
        from flash import fmt
        with open(os.path.join(self.dir, "extracts",
                               "%s-doors.csv" % self.date), encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        self.assertIn("upt_vs_ly", rows[0])
        eid = seed.ATTACH_STORE
        row = next(r for r in rows if r["entity_id"] == eid)
        b = self.obj["stores"][eid]["headline"]
        self.assertAlmostEqual(float(row["upt"]), b["upt"], places=6)
        self.assertAlmostEqual(float(row["upt_vs_ly"]), b["upt_pct_vs_ly"],
                               places=6)
        page = self._page("store/%s/%s.html" % (eid, self.date))
        self.assertIn(fmt.pct(b["upt_pct_vs_ly"]), page)

    def test_storyline_22_surfaces_as_a_favourable_exception(self):
        txt = self._page("day/%s.html" % self.date)
        exc = [e for e in self.obj["exceptions"] if e["kind"] == "upt"][0]
        self.assertIn(exc["title"], txt)
        self.assertIn("basket building", txt)

    def test_storyline_22_tree_shows_the_upt_contribution_driving_the_gap(self):
        from flash import fmt
        t = self.obj["stores"][seed.ATTACH_STORE]["tree"]
        txt = self._page("store/%s/tree/%s.html" % (seed.ATTACH_STORE, self.date))
        # The page prints the RECONCILED contributions, so the assertion reads
        # them the same way — the sub-cent residual lands on the largest row.
        _c, split_rows = render_site.tree_contributions(t)
        split = dict((x["driver"], x["contribution"]) for x in split_rows)
        self.assertIn("AST splits into", txt)
        self.assertIn(fmt.money_signed_exact(split["upt"]), txt)
        self.assertGreater(split["upt"], abs(split["aus"]))


class CompanionCase(unittest.TestCase):
    """The summary companion: fewer pages, the same numbers, and no link that
    goes nowhere."""

    @classmethod
    def setUpClass(cls):
        cls.site = dbfixture.site_dir()
        cls.comp = dbfixture.companion_dir()
        cls.base = dbfixture.COMPANION_BASE
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]

    def _files(self, root):
        out = []
        for r, _d, fs in os.walk(root):
            for f in fs:
                out.append(os.path.relpath(os.path.join(r, f), root)
                           .replace(os.sep, "/"))
        return sorted(out)

    def test_the_companion_is_a_strict_subset_of_the_site(self):
        site, comp = set(self._files(self.site)), set(self._files(self.comp))
        self.assertTrue(comp.issubset(site),
                        "companion has paths the site does not: %s"
                        % sorted(comp - site)[:5])
        self.assertLess(len(comp), len(site))

    def test_it_carries_the_summary_tier_and_drops_the_drill_tier(self):
        comp = self._files(self.comp)
        for prefix in ("day/", "email/", "corporate/", "brand/", "region/",
                       "affiliate/", "field/", "omni/", "customer/", "merch/",
                       "category/", "rank/", "extracts/", "assets/"):
            self.assertTrue(any(f.startswith(prefix) for f in comp), prefix)
        for prefix in ("store/", "district/", "sku/"):
            self.assertFalse(any(f.startswith(prefix) for f in comp), prefix)
        self.assertIn("index.html", comp)

    def test_every_link_either_resolves_locally_or_goes_to_the_complete_site(self):
        local = set(self._files(self.comp))
        checked = external = 0
        for r, _d, fs in os.walk(self.comp):
            for f in fs:
                if not f.endswith(".html"):
                    continue
                base = os.path.relpath(r, self.comp).replace(os.sep, "/")
                base = "" if base == "." else base
                for h in HREF_RE.findall(_read(os.path.join(r, f))):
                    if h.startswith(("#", "mailto:", "data:")):
                        continue
                    if h.startswith(("http://", "https://")):
                        external += 1
                        self.assertTrue(h.startswith(self.base),
                                        "unsanctioned external link %s" % h)
                        continue
                    checked += 1
                    t = posixpath.normpath(posixpath.join(base, h.split("#")[0]))
                    self.assertIn(t, local, "%s -> %s is dead" % (f, h))
        self.assertGreater(checked, 200)
        self.assertGreater(external, 100)

    def test_pages_carrying_an_external_link_disclose_it(self):
        for rel in ("index.html", "day/%s.html" % self.date,
                    "corporate/%s.html" % self.date,
                    "rank/net_sales/%s.html" % self.date):
            txt = _read(os.path.join(self.comp, rel))
            if self.base not in txt:
                continue
            self.assertIn("complete site", txt, rel)

    def test_the_figures_are_the_sites_figures(self):
        """BR-13/BR-18/BR-21: same computed object, so any figure present on
        both sites is the same figure."""
        num = re.compile(r"[\u2212+]?\$[\d,]+(?:\.\d+)?|[\u2212+]?\d+\.\d+%")
        for rel in ("day/%s.html" % self.date, "merch/%s.html" % self.date,
                    "customer/%s.html" % self.date,
                    "corporate/%s.html" % self.date,
                    "omni/BOPIS/%s.html" % self.date):
            a_ = set(num.findall(_read(os.path.join(self.site, rel))))
            b_ = set(num.findall(_read(os.path.join(self.comp, rel))))
            self.assertEqual(a_, b_, rel)

    def test_the_extract_csvs_are_byte_identical(self):
        for f in sorted(os.listdir(os.path.join(self.comp, "extracts"))):
            a_ = os.path.join(self.site, "extracts", f)
            b_ = os.path.join(self.comp, "extracts", f)
            with open(a_, "rb") as fa, open(b_, "rb") as fb:
                self.assertEqual(fa.read(), fb.read(), f)

    def test_the_companion_renders_byte_identically(self):
        hashes = []
        for _ in range(2):
            path = tempfile.mkdtemp(prefix="opsflash-compdet-")
            try:
                dbfixture.build_companion_into(path)
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

    def test_it_stays_well_under_the_host_file_cap(self):
        import run_flash
        n = len(self._files(self.comp))
        self.assertLess(n, run_flash.COMPANION_FILE_BUDGET)


class PageClaimsCase(unittest.TestCase):
    """A page must not assert a property it does not have.

    This is the same discipline as a column that adds up: the product's whole
    argument is that what it prints is checkable, so a sentence claiming
    something the file itself contradicts is a defect of the same class as a
    number that does not reconcile — not a copy edit.

    The claims below are assertions about the FILE, so each one is paired with
    a predicate that reads the file and decides whether it is true."""

    # (regex the page might claim, predicate that must hold if it claims it)
    CLAIMS = (
        ("every link is relative",
         lambda t: 'href="http' not in t,
         "the page carries an absolute link"),
        ("no live systems were queried",
         lambda t: True,
         "always true of a seeded demo"),
    )

    def _pages(self, root):
        for r, _d, fs in os.walk(root):
            for f in sorted(fs):
                if f.endswith(".html"):
                    yield os.path.join(r, f)

    def _check(self, root):
        broken = []
        for p in self._pages(root):
            txt = _read(p)
            for phrase, holds, why in self.CLAIMS:
                if re.search(phrase, txt, re.I) and not holds(txt):
                    broken.append((os.path.relpath(p, root), phrase, why))
        return broken

    def test_the_complete_site_makes_no_false_claim(self):
        broken = self._check(dbfixture.site_dir())
        self.assertEqual(broken[:5], [], "%d pages claim something untrue"
                         % len(broken))

    def test_the_companion_makes_no_false_claim(self):
        """The regression: companion digests carried absolute drill links while
        still printing the complete site's all-relative footer."""
        broken = self._check(dbfixture.companion_dir())
        self.assertEqual(broken[:5], [], "%d pages claim something untrue"
                         % len(broken))

    def test_companion_pages_with_absolute_links_disclose_them(self):
        comp = dbfixture.companion_dir()
        base = dbfixture.COMPANION_BASE
        seen = 0
        for p in self._pages(comp):
            txt = _read(p)
            if 'href="http' not in txt:
                continue
            seen += 1
            visible = _visible(txt)
            self.assertIn(base, visible,
                          "%s links out without naming where"
                          % os.path.relpath(p, comp))
            self.assertTrue(
                re.search(r"complete site", visible, re.I),
                "%s links out without saying so" % os.path.relpath(p, comp))
        self.assertGreater(seen, 50)

    def test_companion_digests_state_their_own_link_policy(self):
        comp = dbfixture.companion_dir()
        checked = 0
        for p in self._pages(os.path.join(comp, "email")):
            txt = _read(p)
            if 'href="http' not in txt:
                continue
            checked += 1
            self.assertIn("resolve inside this companion", txt)
            self.assertIn("open the complete site", txt)
            self.assertNotIn("Every link is relative", txt)
        # Only full-depth days carry exception links into the drill tier, so
        # the guard is derived from the fixture rather than guessed — it exists
        # to stop the loop passing vacuously, not to pin a magic number.
        self.assertGreaterEqual(checked, 1)
        self.assertLessEqual(checked, dbfixture.SITE_FULL)

    def test_the_complete_sites_digest_keeps_the_relative_claim(self):
        """Because there it is true, and weakening a true statement to make a
        test pass everywhere is its own kind of dishonesty."""
        site = dbfixture.site_dir()
        obj = dbfixture.site_objects()[-1]
        txt = _read(os.path.join(site, "email", "%s.html" % obj["date"]))
        self.assertIn("Every link is relative", txt)
        self.assertNotIn('href="http', txt)


TILES_RE = re.compile(r'<div class="tiles">.*?<!--/tiles-->', re.S)
BP_RE = re.compile(r"[\u2212+-]?\d+ bp")
# The two metrics that legitimately state basis points without being a
# conversion movement. Named explicitly so the rule cannot be widened by
# accident.
NON_CONVERSION_BP = ("omni penetration", "new-to-file", "new to file",
                     "penetration")


class ConversionDriverCase(unittest.TestCase):
    """BR-22: a conversion movement never travels without its drivers.

    'Conversion −264 bp' cannot tell a district manager whether fewer people
    came in or the same people bought less often — a demand problem and an
    execution problem with the same symptom. So every statement of the move
    carries `(traffic ±x%, txns ±y%)`, except inside a full KPI tile grid where
    traffic and transactions are already their own tiles."""

    @classmethod
    def setUpClass(cls):
        cls.site = dbfixture.site_dir()
        cls.comp = dbfixture.companion_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.da = dbfixture.da()

    def _offenders(self, root):
        bad = []
        for r, _d, fs in os.walk(root):
            for f in sorted(fs):
                if not f.endswith(".html"):
                    continue
                raw = _read(os.path.join(r, f))
                # A tile grid states traffic, transactions and conversion as
                # peers, so the drivers are present as data.
                stripped = TILES_RE.sub(" ", JSON_RE.sub(" ", raw))
                text = TAG_RE.sub(" ", stripped)
                for m in BP_RE.finditer(text):
                    before = text[max(0, m.start() - 70):m.start()].lower()
                    after = text[m.end():m.end() + 16]
                    if any(k in before for k in NON_CONVERSION_BP):
                        continue
                    if "(traffic" in after.replace(" (", "("):
                        continue
                    bad.append((os.path.relpath(os.path.join(r, f), root),
                                text[max(0, m.start() - 60):m.end() + 20]))
        return bad

    def test_the_complete_site_never_states_a_bare_conversion_move(self):
        bad = self._offenders(self.site)
        self.assertEqual(bad[:4], [], "%d bare conversion moves" % len(bad))

    def test_the_companion_never_states_a_bare_conversion_move(self):
        bad = self._offenders(self.comp)
        self.assertEqual(bad[:4], [], "%d bare conversion moves" % len(bad))

    def test_the_annotation_is_actually_present_and_not_vacuous(self):
        """Guard against the rule passing because nothing states a move."""
        found = 0
        for r, _d, fs in os.walk(self.site):
            for f in fs:
                if f.endswith(".html"):
                    found += _read(os.path.join(r, f)).count("(traffic ")
        self.assertGreater(found, 500)

    def test_the_annotation_arithmetic_is_internally_consistent(self):
        """(1 + txns%) ÷ (1 + traffic%) must be the conversion ratio."""
        for scope in ({}, {"region": "Midwest"}, {"entity_id": "LB-015"},
                      {"affiliate_id": "CA"}, {"brand_id": "LUM"}):
            m = self.da.conversion_move(dbfixture.ANCHOR, **scope)
            if not m["available"]:
                continue
            self.assertAlmostEqual(m["identity_gap"], 0.0, places=9, msg=str(scope))
            ratio = m["ty_conversion"] / m["ly_conversion"]
            self.assertAlmostEqual((1 + m["txns_pct"]) / (1 + m["traffic_pct"]),
                                   ratio, places=9, msg=str(scope))

    def test_a_door_with_no_traffic_says_so_rather_than_omitting(self):
        eid, day = sorted(seed.TRAFFIC_MISSING)[0]
        m = self.da.conversion_move(day, entity_id=eid)
        self.assertFalse(m["available"])
        self.assertIn("unavailable", m["annotation"])
        self.assertNotIn("bp", m["annotation"])
        self.assertIn("no traffic posted", m["annotation"])

    def test_the_annotation_has_one_home(self):
        """No renderer reassembles it from parts.

        The discriminator is the annotation's own separator: the catalog is the
        only module that may write ", txns ". A renderer that started
        formatting its own driver string would trip this before it shipped."""
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in ("render_site.py", "render_email.py", "compute.py",
                     "focus.py"):
            src = _read(os.path.join(root, "flash", name))
            self.assertNotIn(", txns ", src, name)
        self.assertIn(", txns ", _read(os.path.join(root, "flash", "catalog.py")))

    def test_the_exception_line_carries_the_driver(self):
        exc = [e for e in self.obj["exceptions"] if e["kind"] == "conversion"]
        self.assertTrue(exc)
        for e in exc:
            self.assertIn("(traffic ", e["detail"])
            self.assertIn("(traffic ", e["driver"] or "")


class HeadlineBlockCase(unittest.TestCase):
    """Needs attention / worth celebrating, on all five personas."""

    @classmethod
    def setUpClass(cls):
        cls.site = dbfixture.site_dir()
        cls.comp = dbfixture.companion_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]

    def test_every_persona_landing_opens_with_both_blocks(self):
        for key in sorted(self.obj["personas"]):
            kind, pkey = key.split("/", 1)
            rel = ("%s/%s.html" % (kind, self.date) if kind in
                   ("corporate", "field")
                   else "%s/%s/%s.html" % (kind, _slug_for(kind, pkey), self.date))
            txt = _read(os.path.join(self.site, rel))
            self.assertIn("Needs attention", txt, rel)
            self.assertIn("Worth celebrating", txt, rel)

    def test_the_day_flash_and_the_digest_carry_the_corporate_blocks(self):
        for rel in ("day/%s.html" % self.date, "email/%s.html" % self.date):
            txt = _read(os.path.join(self.site, rel))
            self.assertIn("Needs attention", txt, rel)
            self.assertIn("Worth celebrating", txt, rel)
            for it in self.obj["headlines"]["attention"]:
                self.assertIn(it["headline"], txt, "%s: %s" % (rel, it["headline"]))

    def test_the_companion_carries_them_too(self):
        txt = _read(os.path.join(self.comp, "day/%s.html" % self.date))
        self.assertIn("Needs attention", txt)
        self.assertIn("Worth celebrating", txt)

    def test_never_more_than_three_items_and_never_both_blocks(self):
        blocks = [self.obj["headlines"]]
        blocks += [p["headlines"] for p in self.obj["personas"].values()]
        for h in blocks:
            self.assertLessEqual(len(h["attention"]), 3)
            self.assertLessEqual(len(h["celebration"]), 3)
            att = set()
            for it in h["attention"]:
                att |= set(it["entities"] or [it["key"]])
            for it in h["celebration"]:
                self.assertFalse(att & set(it["entities"] or [it["key"]]))

    def test_items_are_scoped_to_what_the_persona_can_act_on(self):
        da = dbfixture.da()
        for key, p in self.obj["personas"].items():
            ids = set(da.scope_ids(**p["scope"]))
            for it in p["headlines"]["attention"] + p["headlines"]["celebration"]:
                if it["kind"] != "door":
                    continue
                self.assertIn(it["key"], ids, "%s shows %s" % (key, it["key"]))

    def test_every_item_figure_equals_the_page_it_links_to(self):
        da = dbfixture.da()
        checked = 0
        for h in [self.obj["headlines"]] + [p["headlines"] for p in
                                            self.obj["personas"].values()]:
            for it in h["attention"] + h["celebration"]:
                if it["kind"] != "door" or it["ty"] is None or it["rule"] == "BR-19":
                    continue
                checked += 1
                self.assertAlmostEqual(
                    it["ty"], da.net_sales_of(it["key"], dbfixture.ANCHOR), places=2)
                page = _read(os.path.join(self.site, "store", it["key"],
                                          "%s.html" % self.date))
                from flash import fmt
                self.assertIn(fmt.money_compact(it["ty"]), page)
        self.assertGreater(checked, 5)

    def test_items_are_ranked_by_absolute_dollar_impact(self):
        for h in [self.obj["headlines"]] + [p["headlines"] for p in
                                            self.obj["personas"].values()]:
            for block in ("attention", "celebration"):
                vals = [i["impact"] for i in h[block]]
                self.assertEqual(vals, sorted(vals, reverse=True))

    def test_the_ranking_rule_is_stated_on_the_page(self):
        txt = _read(os.path.join(self.site, "corporate/%s.html" % self.date))
        self.assertIn("absolute dollar impact", txt)
        self.assertIn("threshold-clearing favourable move", txt)

    def test_field_leadership_only_sees_what_a_district_manager_can_fix(self):
        """Scope says whose numbers these are; actionability says whose problem
        it is. A district manager cannot re-buy Fragrance or fix e-commerce
        acquisition, so neither belongs at the top of their one block."""
        h = self.obj["personas"]["field/field"]["headlines"]
        kinds = set(i["kind"] for i in h["attention"] + h["celebration"])
        self.assertTrue(kinds)
        self.assertTrue(kinds <= {"door", "omni"}, kinds)
        self.assertIn("act on", h["scope_rule"])

    def test_corporate_sees_every_kind_of_move(self):
        h = self.obj["personas"]["corporate/corporate"]["headlines"]
        self.assertIsNone(h["kinds"])

    def test_field_and_corporate_do_not_show_the_same_list(self):
        f = [i["headline"] for i in
             self.obj["personas"]["field/field"]["headlines"]["attention"]]
        c = [i["headline"] for i in
             self.obj["personas"]["corporate/corporate"]["headlines"]["attention"]]
        self.assertNotEqual(f, c)

    def test_every_item_carries_a_driver(self):
        for h in [self.obj["headlines"]] + [p["headlines"] for p in
                                            self.obj["personas"].values()]:
            for it in h["attention"] + h["celebration"]:
                self.assertTrue(it["driver"], it["headline"])

    def test_door_items_carry_the_conversion_driver_annotation(self):
        seen = 0
        for h in [self.obj["headlines"]] + [p["headlines"] for p in
                                            self.obj["personas"].values()]:
            for it in h["attention"] + h["celebration"]:
                if it["kind"] != "door" or it["rule"] == "BR-3":
                    continue
                seen += 1
                self.assertTrue("(traffic " in it["driver"]
                                or "unavailable" in it["driver"], it["driver"])
        self.assertGreater(seen, 5)


def _slug_for(kind, key):
    from flash.focus import _slug
    return _slug(key) if kind == "region" else key


ID_RE = re.compile(r'\sid="([^"]+)"')
HASH_RE = re.compile(r'href="#([^"]+)"')
H2_ID_RE = re.compile(r"<h2[^>]*>")
SUBMENU_RE = re.compile(r'<nav class="submenu".*?</nav>', re.S)


class SectionNavigationCase(unittest.TestCase):
    """In-page navigation: anchors only, no script.

    The sticky bar is CSS. A scroll-spy active state would need JavaScript, so
    the menu marks no current section — the calculator stays the only script on
    the site."""

    MIN_SECTIONS = 4

    @classmethod
    def setUpClass(cls):
        cls.site = dbfixture.site_dir()
        cls.comp = dbfixture.companion_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]

    def _pages(self, root):
        for r, _d, fs in os.walk(root):
            for f in sorted(fs):
                if f.endswith(".html"):
                    yield os.path.join(r, f)

    def test_every_hash_link_resolves_on_its_own_page(self):
        checked = 0
        for root in (self.site, self.comp):
            for p in self._pages(root):
                txt = _read(p)
                ids = set(ID_RE.findall(txt))
                for target in HASH_RE.findall(txt):
                    checked += 1
                    self.assertIn(target, ids,
                                  "%s links to #%s with no such id"
                                  % (os.path.relpath(p, root), target))
        self.assertGreater(checked, 2000)

    def test_long_pages_carry_the_menu_and_short_ones_do_not(self):
        with_menu = without = 0
        for root in (self.site, self.comp):
            for p in self._pages(root):
                txt = _read(p)
                if os.path.basename(os.path.dirname(p)) == "email":
                    continue
                n = len(H2_ID_RE.findall(txt))
                has = bool(SUBMENU_RE.search(txt))
                if n >= self.MIN_SECTIONS:
                    with_menu += 1
                    self.assertTrue(has, "%s has %d sections and no menu"
                                    % (os.path.relpath(p, root), n))
                else:
                    without += 1
                    self.assertFalse(has, "%s has only %d sections but a menu"
                                     % (os.path.relpath(p, root), n))
        self.assertGreater(with_menu, 200)
        self.assertGreater(without, 200)

    def test_the_menu_lists_every_section_on_the_page(self):
        for rel in ("day/%s.html" % self.date, "corporate/%s.html" % self.date,
                    "field/%s.html" % self.date,
                    "store/LB-015/%s.html" % self.date,
                    "merch/%s.html" % self.date,
                    "omni/BOPIS/%s.html" % self.date):
            txt = _read(os.path.join(self.site, rel))
            menu = SUBMENU_RE.search(txt)
            self.assertIsNotNone(menu, rel)
            linked = HASH_RE.findall(menu.group(0))
            heads = re.findall(r'<h2 id="([^"]+)"', txt)
            self.assertEqual(linked, heads, rel)

    def test_every_section_heading_has_an_id_even_without_a_menu(self):
        for p in self._pages(self.site):
            txt = _read(p)
            for tag in H2_ID_RE.findall(txt):
                self.assertIn(' id="', tag, "%s: %s" % (p, tag))

    def test_section_ids_are_stable_across_a_rebuild(self):
        path = tempfile.mkdtemp(prefix="opsflash-ids-")
        try:
            dbfixture.build_site_into(path)
            for rel in ("day/%s.html" % self.date,
                        "corporate/%s.html" % self.date):
                a_ = re.findall(r'<h2 id="([^"]+)"',
                                _read(os.path.join(self.site, rel)))
                b_ = re.findall(r'<h2 id="([^"]+)"',
                                _read(os.path.join(path, rel)))
                self.assertEqual(a_, b_, rel)
                self.assertEqual(len(a_), len(set(a_)), "duplicate ids in " + rel)
        finally:
            shutil.rmtree(path, ignore_errors=True)

    def test_pages_with_a_menu_offer_a_way_back_to_it(self):
        txt = _read(os.path.join(self.site, "day/%s.html" % self.date))
        self.assertEqual(txt.count('class="totop"'),
                         len(re.findall(r'<h2 id="', txt)))
        short = _read(os.path.join(self.site, "sku/%s.html" % seed.BREAKOUT_SKU))
        self.assertNotIn('class="totop"', short)

    def test_the_menu_adds_no_javascript(self):
        for rel in ("day/%s.html" % self.date, "corporate/%s.html" % self.date):
            self.assertEqual(_read(os.path.join(self.site, rel)).count("<script"), 0)

    def test_the_digest_opens_with_a_jump_list_and_no_sticky(self):
        txt = _read(os.path.join(self.site, "email/%s.html" % self.date))
        self.assertIn("In this digest", txt)
        self.assertNotIn("position:sticky", txt)
        ids = set(ID_RE.findall(txt))
        targets = HASH_RE.findall(txt)
        self.assertGreaterEqual(len(targets), 4)
        for t in targets:
            self.assertIn(t, ids)

    def test_the_digest_stays_inside_its_budget(self):
        for p in self._pages(os.path.join(self.site, "email")):
            self.assertLess(os.path.getsize(p) / 1024.0, EMAIL_KB, p)


class StoreManagerPersonaCase(unittest.TestCase):
    """The sixth persona: a door, against its own recent form."""

    @classmethod
    def setUpClass(cls):
        cls.site = dbfixture.site_dir()
        cls.comp = dbfixture.companion_dir()
        cls.obj = dbfixture.site_objects()[-1]
        cls.date = cls.obj["date"]
        cls.da = dbfixture.da()

    def test_the_entry_page_exists_on_both_trees(self):
        for root in (self.site, self.comp):
            p = os.path.join(root, "store-manager", "%s.html" % self.date)
            self.assertTrue(os.path.exists(p), p)

    def test_the_entry_page_lists_every_door_grouped_by_brand(self):
        txt = _read(os.path.join(self.site, "store-manager",
                                 "%s.html" % self.date))
        for b in self.obj["stores"].values():
            self.assertIn(b["name"], txt, b["entity_id"])
        for brand in ("Lumière", "Atelier Noir", "Botanica"):
            self.assertIn(brand, txt, brand)

    def test_the_persona_nav_carries_store_manager_everywhere(self):
        checked = 0
        for r, _d, fs in os.walk(self.site):
            for f in sorted(fs):
                if not f.endswith(".html"):
                    continue
                txt = _read(os.path.join(r, f))
                m = re.search(r'<nav class="personas">.*?</nav>', txt, re.S)
                if not m:
                    continue
                checked += 1
                self.assertIn("Store Manager", m.group(0),
                              os.path.relpath(os.path.join(r, f), self.site))
        self.assertGreater(checked, 300)

    def test_every_posted_door_landing_opens_with_its_own_blocks(self):
        checked = 0
        for eid, b in sorted(self.obj["stores"].items()):
            if not b["posted"]:
                continue
            checked += 1
            self.assertIn("headlines", b, eid)
            txt = _read(os.path.join(self.site, "store", eid,
                                     "%s.html" % self.date))
            self.assertIn("Needs attention", txt, eid)
            self.assertIn("Worth celebrating", txt, eid)
        self.assertGreater(checked, 20)

    def test_door_blocks_obey_the_three_and_no_double_rules(self):
        for eid, b in sorted(self.obj["stores"].items()):
            h = b.get("headlines")
            if not h:
                continue
            self.assertLessEqual(len(h["attention"]), 3, eid)
            self.assertLessEqual(len(h["celebration"]), 3, eid)
            att = set(i["subject"] for i in h["attention"])
            cel = set(i["subject"] for i in h["celebration"])
            self.assertFalse(att & cel, "%s: %s in both" % (eid, att & cel))

    def test_every_door_item_figure_equals_the_object(self):
        checked = 0
        for eid, b in sorted(self.obj["stores"].items()):
            h = b.get("headlines")
            if not h:
                continue
            for it in h["attention"] + h["celebration"]:
                checked += 1
                self.assertEqual(it["key"], eid)
                if it["subject"] == "sales":
                    self.assertAlmostEqual(
                        it["actual"], self.da.net_sales_of(eid, dbfixture.ANCHOR),
                        places=2, msg=eid)
                if it["subject"] == "upt":
                    self.assertAlmostEqual(
                        it["actual"],
                        self.da.basket(dbfixture.ANCHOR, entity_id=eid)["upt"],
                        places=9, msg=eid)
                if it["subject"] == "conversion":
                    self.assertAlmostEqual(
                        it["actual"],
                        self.da.conversion(dbfixture.ANCHOR,
                                           entity_id=eid)["conversion"],
                        places=9, msg=eid)
        self.assertGreater(checked, 20)

    def test_the_baseline_rule_reproduced_independently(self):
        """Re-derive the four same-weekday days and the mean by hand-SQL."""
        import datetime as _dt
        conn = dbfixture.conn()
        for eid in ("LB-015", "LB-002"):
            days = self.da.baseline_days(dbfixture.ANCHOR, eid)
            want = []
            for k in (1, 2, 3, 4):
                d = dbfixture.ANCHOR - _dt.timedelta(days=7 * k)
                row = conn.execute(
                    "SELECT net_sales FROM sales_day WHERE date=? AND entity_id=?",
                    (d.isoformat(), eid)).fetchone()
                if row:
                    want.append(d)
            self.assertEqual(days, want, eid)
            hand = sum(conn.execute(
                "SELECT net_sales FROM sales_day WHERE date=? AND entity_id=?",
                (d.isoformat(), eid)).fetchone()[0] for d in days) / len(days)
            base = self.da.trailing_baseline(dbfixture.ANCHOR, eid)
            self.assertAlmostEqual(base["net_sales"], round(hand, 2), places=2,
                                   msg=eid)
            # every baseline day is the same weekday as the anchor
            for d in days:
                self.assertEqual(d.weekday(), dbfixture.ANCHOR.weekday(), eid)

    def test_items_are_ranked_by_dollar_impact_against_the_baseline(self):
        for eid, b in sorted(self.obj["stores"].items()):
            h = b.get("headlines")
            if not h:
                continue
            for block in ("attention", "celebration"):
                vals = [i["impact"] for i in h[block]]
                self.assertEqual(vals, sorted(vals, reverse=True), eid)

    def test_every_item_states_the_performance_frame_alongside(self):
        for eid, b in sorted(self.obj["stores"].items()):
            h = b.get("headlines")
            if not h:
                continue
            for it in h["attention"] + h["celebration"]:
                self.assertTrue(it["frames"], "%s %s" % (eid, it["subject"]))
                self.assertTrue(
                    "LY" in it["frames"] or "plan" in it["frames"]
                    or "baseline" in it["frames"] or "shape only" in it["frames"],
                    "%s %s: %s" % (eid, it["subject"], it["frames"]))

    def test_the_baseline_and_ranking_rules_are_printed_on_the_page(self):
        txt = _read(os.path.join(self.site, "store", "LB-015",
                                 "%s.html" % self.date))
        self.assertIn("same-weekday days it posted", txt)
        self.assertIn("coaching frame leads", txt)
        self.assertIn("scored on none", txt)

    def test_the_two_planted_stories_surface_on_their_doors(self):
        conv = self.obj["stores"][seed.CONV_STORE]["headlines"]
        subjects = [i["subject"] for i in conv["attention"]]
        self.assertIn("conversion", subjects)
        attach = self.obj["stores"][seed.ATTACH_STORE]["headlines"]
        subjects = [i["subject"] for i in attach["celebration"]]
        self.assertIn("upt", subjects)

    def test_door_landings_stay_off_the_companion(self):
        self.assertFalse(os.path.isdir(os.path.join(self.comp, "store")))
        entry = _read(os.path.join(self.comp, "store-manager",
                                   "%s.html" % self.date))
        self.assertIn(dbfixture.COMPANION_BASE, entry)
        # every door link on the companion entry crosses to the complete site
        for h in HREF_RE.findall(entry):
            if "/store/" in h:
                self.assertTrue(h.startswith(dbfixture.COMPANION_BASE), h)


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
