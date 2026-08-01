# -*- coding: utf-8 -*-
"""The site — the operational flash's destination surface (PRD §6).

The executive flash is delivered and not visited. This one inverts that on
purpose: operators live in the detail, so the site is the product and the
morning email is the pull that builds the habit.

Everything here reads a computed object and prints it. Renderers may FORMAT
(through `fmt`, the one formatting home) and they may never COMPUTE: no
division, no summation, no comparison of two figures to decide a third. If a
page needs a number that is not on the object, the fix is in `compute.py`.

Link strategy: **relative hrefs only**, everywhere, computed from each page's
own depth. The same files then resolve identically from `file://`, from
`app.py`, and from any host directory the tree is copied into — which is what
BR-13 needs, because the email's deep links have to land on the site wherever
it happens to live.

The only JavaScript on the site is the KPI tree's what-if calculator. It is
handed `kpi_tree()['payload']` — the catalog's own driver values — as a JSON
block and multiplies them. It contains no formula of its own (BR-20), and it
verifies on load that its arithmetic reproduces the catalog's figure before it
will let the reader touch a slider.

No external assets of any kind: no webfonts, no CDN, no images. Every page
declares utf-8.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import posixpath
import re
from html import escape as esc
from html import unescape
from typing import Dict, List, Optional

from flash import fmt
from flash.catalog import reconcile_display
from flash.focus import _slug
from flash.style import CSS

D = dt.date

WEEKDAY_HEADS = ("Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat")

PERSONA_SCOPE = {
    "corporate": ("Corporate", "Brand · Region · Affiliate · top doors"),
    "brand": ("Brand", "Region · Affiliate · Field Leadership · Doors"),
    "region": ("Region", "Brand · Affiliate · Field Leadership · Districts · Doors"),
    "affiliate": ("Affiliate", "Brands · Field Leadership · Districts · Doors"),
    "field": ("Field Leadership", "Districts · Doors"),
}

RANK_LABELS = {
    "net_sales": "Net sales", "comp_pct": "Comp %", "conversion": "Conversion",
    "plan_attainment": "Plan attainment", "traffic": "Traffic",
    "transactions": "Transactions", "ast": "AST", "upt": "UPT",
}

OMNI_TITLES = {
    "BOPIS": "Buy Online, Pick up In Store", "RTD": "Real-Time Delivery",
    "OOFIS": "Order Online From In Store", "CR": "Click & Reserve",
    "BORIS": "Buy Online, Return In Store",
}

# A page earns a sub-menu at this many sections. Below it the menu would be
# longer than the scroll it saves: a SKU page, a district table, a rank table
# and an hourly view are one screen of content with two headings, and a
# navigation bar over two headings is furniture, not navigation.
MIN_SECTIONS_FOR_MENU = 4

H2_RE = re.compile(r'<h2([^>]*)>(.*?)</h2>', re.S)
TAGS_RE = re.compile(r"<[^>]+>")
NAV_RE = re.compile(r'\s*data-nav="([^"]*)"')
MENU_LABEL_MAX = 26


def _nav_label(text: str) -> str:
    """A menu label short enough to scan, from a heading written to be read.

    Headings carry a subject and a subtitle — "Focus — what moved the comp".
    The menu wants the subject. Cut at the em dash, then at the first comma;
    a heading with neither and no explicit `data-nav` keeps its full text, and
    the few that are still too long carry one."""
    for sep in (" \u2014 ", ", "):
        if sep in text:
            head = text.split(sep)[0].strip()
            if len(head) >= 4:
                return head
    return text


def _sectionise(body: str, min_sections: int = MIN_SECTIONS_FOR_MENU):
    """Give every section a stable id and, on a long enough page, a sticky
    sub-menu above them.

    Ids are slugs of the heading text, deduplicated by suffix in document
    order, so they are deterministic across regenerations and stable as long
    as the heading is — which is what makes a link into a section safe to
    share. Returns (body, menu_html); menu_html is empty on a short page, and
    a short page gets no back-to-menu links either, because there is nowhere
    to go back to."""
    titles = [TAGS_RE.sub("", m.group(2)).strip() for m in H2_RE.finditer(body)]
    del titles[len(titles):]
    has_menu = len(titles) >= min_sections
    seen, items = {}, []

    def repl(m):
        attrs, inner = m.group(1) or "", m.group(2)
        override = NAV_RE.search(attrs)
        attrs = NAV_RE.sub("", attrs)
        text = unescape(TAGS_RE.sub("", inner).strip())
        sid = _slug(text) or "section"
        seen[sid] = seen.get(sid, 0) + 1
        if seen[sid] > 1:
            sid = "%s-%d" % (sid, seen[sid])
        items.append((sid, override.group(1) if override else _nav_label(text)))
        top = ('<a class="totop" href="#menu">\u2191 menu</a>' if has_menu else "")
        return '<h2 id="%s"%s>%s%s</h2>' % (sid, attrs, inner, top)

    body = H2_RE.sub(repl, body)
    if not has_menu:
        return body, ""
    links = "".join('<a href="#%s">%s</a>' % (esc(sid), esc(text))
                    for sid, text in items)
    menu = ('<nav class="submenu" id="menu" aria-label="Sections on this page">'
            '<span class="sml">On this page</span>%s</nav>' % links)
    return body, menu


def _page(title: str, body: str, depth: int = 0, wrap_class: str = "",
          script: str = "") -> str:
    """Every page declares utf-8 and links its stylesheet relatively.

    `depth` is how many directories down the page sits, which is the whole of
    the link strategy: relative hrefs only, so the site works identically from
    `file://`, from `app.py`, and from a copied folder on any host."""
    up = "../" * depth
    body, menu = _sectionise(body)
    if menu:
        # One placement rule for every page type and both render targets: the
        # menu sits directly under the masthead, so it is in the same place
        # whether the reader arrived at a day flash, a persona landing or a
        # store manager page.
        if "</header>" in body:
            body = body.replace("</header>", "</header>\n" + menu, 1)
        else:
            body = menu + body
    o = ['<!doctype html>', '<html lang="en">', '<head>',
         '<meta charset="utf-8">',
         '<meta name="viewport" content="width=device-width,initial-scale=1">',
         '<title>%s</title>' % esc(title),
         '<link rel="stylesheet" href="%sassets/site.css">' % up,
         '</head>', '<body>',
         '<div class="wrap%s">' % ((" " + wrap_class) if wrap_class else ""),
         body, '</div>']
    if script:
        o.append(script)
    o += ['</body>', '</html>']
    return "\n".join(o) + "\n"


def _up(depth: int) -> str:
    return "../" * depth


def _href(depth: int, path: str) -> str:
    """A site-root-relative path, rewritten for a page `depth` levels down."""
    return _up(depth) + path


def _header(eyebrow: str, title: str, meta: str) -> str:
    return ('<header class="top"><div class="eyebrow">%s</div>'
            '<h1>%s</h1><div class="meta">%s</div></header>'
            % (esc(eyebrow), esc(title), meta))


def _crumbs(depth: int, items) -> str:
    """items: list of (label, path-or-None). The last is the current page."""
    parts = []
    for label, path in items:
        if path:
            parts.append('<a href="%s">%s</a>' % (esc(_href(depth, path)), esc(label)))
        else:
            parts.append(esc(label))
    return '<div class="crumbs">%s</div>' % '<span class="sep">›</span>'.join(parts)


def _persona_nav(depth: int, date_iso: str, current: str = "") -> str:
    links = [("Corporate", "corporate/%s.html" % date_iso, "corporate"),
             ("Brands", "brand/LUM/%s.html" % date_iso, "brand"),
             ("Regions", "region/northeast/%s.html" % date_iso, "region"),
             ("Affiliates", "affiliate/US/%s.html" % date_iso, "affiliate"),
             ("Field Leadership", "field/%s.html" % date_iso, "field"),
             ("Store Manager", "store-manager/%s.html" % date_iso, "store"),
             ("Day flash", "day/%s.html" % date_iso, "day"),
             ("Archive", "index.html", "index")]
    out = ['<nav class="personas">']
    for label, path, key in links:
        out.append('<a class="%s" href="%s">%s</a>'
                   % ("on" if key == current else "", esc(_href(depth, path)),
                      esc(label)))
    out.append('</nav>')
    return "".join(out)


def _footer(extra: str = "") -> str:
    return ('<footer>%sEvery figure on this site is computed once in the metric '
            'catalog and rendered to the site, the morning digest and the door '
            'extract from one object (BR-5 / BR-13). Generated from seeded '
            'data; no live systems were queried. Demo build.</footer>'
            % (extra + " " if extra else ""))


def _legend() -> str:
    return ('<div class="legend">Colour tokens: <i class="gold">gold</i> = an '
            'input the business asserted · <i class="blue">blue</i> = a figure '
            'presented as given · <i class="calc">green</i> = calculated here. '
            'Dotted underline = hover for the formula.</div>')


def _currency_band(obj, local_ccy: str, local_total=None,
                   converted_total=None, what: str = "This door") -> str:
    """The BR-16 disclosure, with the NUMERIC rate, wherever a converted figure
    appears.

    "converted at the seeded fixed plan rate" is not a disclosure — a reader
    cannot check it. The rate itself is the disclosure, so it is printed as a
    number on every page that shows a converted figure, next to the native
    figure the reader can compare it against."""
    fx = obj.get("fx") or {}
    reporting = fx.get("reporting_currency", obj.get("reporting_currency", "USD"))
    if local_ccy == reporting:
        return ""
    rate = (fx.get("rates") or {}).get(local_ccy)
    disclosure = (fx.get("disclosures") or {}).get(local_ccy, "")
    native = ("Native total %s %s. " % (fmt.money_exact(local_total), local_ccy)
              if local_total is not None else "")
    shown = ("Shown above as %s %s. " % (fmt.money_exact(converted_total), reporting)
             if converted_total is not None else "")
    return _band(
        "gold", "Currency — %s converted at %s %s per %s"
        % (local_ccy, fmt.ratio(rate), local_ccy, reporting),
        "%s trades in %s. %s%sThe rate is %s %s per 1 %s — %s. It is fixed and "
        "seeded, it is the only rate used anywhere on this site, and it is "
        "stated here because a converted figure without its rate cannot be "
        "checked (BR-16)."
        % (esc(what), esc(local_ccy), esc(native), esc(shown),
           esc(fmt.ratio(rate)), esc(local_ccy), esc(reporting),
           esc(disclosure)))


COMPANION_TIERS = ("day", "email", "corporate", "brand", "region", "affiliate",
                   "field", "omni", "customer", "merch", "category", "rank",
                   "extracts")


def _companion_band(obj_or_base) -> str:
    """The one sanctioned external link on the whole product, disclosed.

    The companion carries the summary tier only, because its host caps at a
    thousand files. Rather than hide the doors, districts and SKUs that do not
    fit, every page that links into them says where they went and links out. A
    link that silently 404s and a link that quietly leaves the site are both
    worse than a link that tells you it is leaving."""
    base = (obj_or_base if isinstance(obj_or_base, str)
            else (obj_or_base or {}).get("companion_base"))
    if not base:
        return ""
    return _band(
        "note", "Summary companion — full drill-down lives on the complete site",
        'This companion carries the daily flash, the morning digests, the five '
        'persona landings and the omni, customer, merchandise, category and '
        'rank panels. Door, district, hourly, KPI-tree and SKU pages live on '
        'the complete site at <a href="%s">%s</a>, and every link to one of '
        'them below goes there. The figures are identical: both sites render '
        'from the same computed object (BR-13).' % (esc(base), esc(base)))


def _fav_key() -> str:
    return ('<div class="keyrow"><i><span class="tri up">▲</span> favourable '
            '(better than +5%)</i><i><span class="tri mid">◆</span> within '
            '±5%</i><i><span class="tri dn">▼</span> unfavourable (worse than '
            '−5%)</i></div>')

def _band(kind: str, title: str, body_html: str) -> str:
    cls = {"gold": ("band", "g"), "alert": ("band alert", "r"),
           "note": ("band note", "b"), "calc": ("band calcband", "c")}[kind]
    return ('<div class="%s"><span class="t %s">%s</span>%s</div>'
            % (cls[0], cls[1], esc(title), body_html))


def _tile(label: str, value: str, cls: str = "", sub: str = "",
          formula: Optional[str] = None, small: bool = False) -> str:
    lab = ('<span class="eyebrow hint" title="%s">%s</span>' % (esc(formula), esc(label))
           if formula else '<span class="eyebrow">%s</span>' % esc(label))
    return ('<div class="tile%s">%s<div class="v %s">%s</div>'
            '<div class="s">%s</div></div>'
            % (" sm" if small else "", lab, cls, esc(value), esc(sub)))


def _table(headers, rows, titles=None, cls="", group_header=None) -> str:
    """`titles` gives hover formulas for the header cells. Cells may be plain
    strings (escaped) or ('raw', html) tuples for links."""
    o = ['<div class="scroll"><table%s>' % (' class="%s"' % cls if cls else "")]
    if group_header:
        o.append("<tr>")
        for label, span in group_header:
            o.append('<th class="grp" colspan="%d">%s</th>' % (span, esc(label)))
        o.append("</tr>")
    o.append("<tr>")
    for i, h in enumerate(headers):
        t = (titles[i] if titles and i < len(titles) else None)
        o.append('<th%s>%s</th>' % (' title="%s"' % esc(t) if t else "", esc(h)))
    o.append("</tr>")
    for row in rows:
        tr_cls = ""
        cells = []
        for c in row:
            if isinstance(c, tuple) and c and c[0] == "raw":
                cells.append('<td>%s</td>' % c[1])
                continue
            if isinstance(c, tuple) and c and c[0] == "total":
                tr_cls = ' class="tot"'
                c = c[1]
            s = "" if c is None else str(c)
            cls_ = "bad" if s.startswith(fmt.MINUS) else ""
            cells.append('<td class="%s">%s</td>' % (cls_, esc(s)))
        o.append("<tr%s>%s</tr>" % (tr_cls, "".join(cells)))
    o.append("</table></div>")
    return "".join(o)


def _link(depth: int, path: str, label: str) -> tuple:
    return ("raw", '<a href="%s">%s</a>' % (esc(_href(depth, path)), esc(label)))


def _num_class(v, positive_is_good: bool = True, pivot: float = 0.0) -> str:
    if v is None:
        return ""
    return "good" if (v >= pivot) == positive_is_good else "bad"


def _tri(v, band: float = 0.05) -> str:
    """The relaunch doc's ±5% fav / within / unfav triangle."""
    if v is None:
        return '<span class="tri mid">–</span>'
    if v > band:
        return '<span class="tri up">▲</span>'
    if v < -band:
        return '<span class="tri dn">▼</span>'
    return '<span class="tri mid">◆</span>'


def _kpi_row(d: Dict[str, object], obj) -> str:
    """The deck's KPI headline row — the same ten tiles on every persona page,
    plus OMNI penetration and the door counts (PRD §6)."""
    h = obj["headline"]
    tiles = [
        _tile("Net sales", d["net_sales"], "", d["net_sales_exact"],
              "Σ net sales over reported entities, converted once to USD"),
        _tile("Comp %s" % obj["comp"]["basis"], d["comp_pct"],
              _num_class(h["comp_pct"]), "vs %s" % d["comp_ly_date"],
              "(Σ comp TY ÷ Σ comp LY-aligned) − 1"),
        _tile("Plan attainment", d["plan_attainment"],
              _num_class(h["plan_attainment"], pivot=1.0), d["plan_gap"],
              "reported actual ÷ plan, day grain (BR-19)"),
        _tile("Transactions", d["transactions"], "", d["txn_comp"] + " vs LY"),
        _tile("AST", d["ast"], _num_class(h["ast_pct_vs_ly"]),
              d["ast_vs_ly"] + " vs LY · = AOV", "net sales ÷ transactions"),
        _tile("AUS", d["aus"], _num_class(h["aus_pct_vs_ly"]),
              d["aus_vs_ly"] + " vs LY · = AUR", "net sales ÷ units"),
        _tile("UPT", d["upt"], _num_class(h["upt_pct_vs_ly"]),
              d["upt_vs_ly"] + " vs LY · LY " + d["ly_upt"],
              "units ÷ transactions, on the comp entity set — the basket "
              "lever a door can actually move"),
        _tile("Traffic", d["traffic"], _num_class(h["traffic_pct_vs_ly"]),
              d["traffic_pct"] + " vs LY", "store door counts; FSS only"),
        _tile("Conversion", d["conversion"],
              _num_class(h["conversion_bps_vs_ly"]),
              d["conversion_bps"] + " vs LY",
              "transactions ÷ traffic; unavailable where no traffic posted"),
        _tile("New customers", d["new_customers"], "",
              "%s of sales · AST %s" % (d["new_customer_pct"], d["new_customer_ast"]),
              "customers whose first purchase is this day"),
        _tile("Returns", d["returns"], "",
              "%s of gross · %s vs LY" % (d["returns_pct_of_gross"], d["returns_vs_ly"])),
        _tile("Discounts", d["discounts"], "",
              "%s of gross · %s vs LY" % (d["discounts_pct_of_gross"], d["discounts_vs_ly"])),
        _tile("OMNI penetration", d["omni_penetration"], "calc",
              d["omni_penetration_bps"] + " vs LY",
              "omni-attributed sales ÷ net sales (a share, never an addition)"),
        _tile("Portfolio / trading", "%s / %s" % (d["portfolio"], d["trading"]),
              "", "%s trading · %s comp of trading"
              % (d["pct_trading"], d["pct_comp_of_trading"])),
    ]
    return '<div class="tiles">%s</div><!--/tiles-->' % "".join(tiles)


def _headline_blocks(depth: int, h, linked: bool = True) -> str:
    """The two blocks every persona opens with.

    Attention first, and always both — a day with nothing to celebrate says so
    rather than dropping the block, because a block that disappears when it is
    empty teaches a reader to stop looking for it."""
    o = ['<div class="heads">']
    for key, cls, title in (("attention", "att", "Needs attention"),
                            ("celebration", "cel", "Worth celebrating")):
        o.append('<section><h2 class="%s">%s</h2><ol class="head %s">'
                 % (cls, esc(title), cls))
        items = h[key]
        if not items:
            o.append('<li class="empty">Nothing cleared a threshold in this '
                     'view today.</li>')
        for i, it in enumerate(items, 1):
            label = esc(it["headline"])
            if it["href"] and linked:
                label = '<a href="%s">%s</a>' % (esc(_href(depth, it["href"])),
                                                 label)
            o.append('<li><span class="imp">%s</span>'
                     '<span class="n">%d</span>'
                     '<div class="h">%s</div>'
                     '<div class="m">%s</div>'
                     '<div class="why"><b>why</b> %s</div></li>'
                     % (esc(fmt.money_compact(it["impact"])), i, label,
                        esc(it["move"]), esc(it["driver"] or "—")))
        o.append('</ol></section>')
    o.append('</div>')
    o.append('<p class="headrule">%s %s %s</p>'
             % (esc(h.get("scope_rule") or ""), esc(h["ranking_rule"]),
                esc(h["celebration_rule"])))
    return "".join(o)


def _channel_section(cb) -> str:
    """Stores against e-commerce — two channels and a total, never three.

    Omni rides as a penetration column inside each channel rather than as a row
    of its own, because a BOPIS order is money already sitting in e-commerce
    demand and its upsell is money already sitting in the store's takings.
    Adding an omni row would double-count the headline in the one table most
    likely to be read as a partition of it (BR-9)."""
    rows = []
    for r in cb["rows"]:
        fss = r["traffic_applies"]
        att = r.get("attributed")
        label = r["label"] + (" (attributed by SKU)" if att else "")
        posted = ("%d storefront%s" % (r["open_entities"],
                                       "" if r["open_entities"] == 1 else "s")
                  if att else "%d/%d" % (r["reported_entities"],
                                         r["open_entities"]))
        rows.append((
            label, posted,
            fmt.money_compact(r["net_sales"]), fmt.pct_plain(r["mix_pct"]),
            ("raw", "%s %s" % (_tri(r["comp_pct"]), esc(fmt.pct(r["comp_pct"])))),
            "no entity plan" if att else fmt.pct_plain(r["plan_attainment"]),
            "not attributable" if att else (
                "/".join(r["plan_grain_mix"]) or "no plan"),
            fmt.count(r["traffic"]) if fss else "FSS only",
            (fmt.pct_plain(r["conversion"], 2) if fss and r["conversion"]
             else "FSS only"),
            r["conversion_move"] if fss else "FSS only",
            "not attributable" if att
            else fmt.pct_plain(r["omni_penetration"], 2)))
    rows.append((("total", "Total"), "",
                 fmt.money_compact(cb["total"]), "100.0%", "", "", "", "", "",
                 "", ""))
    out = [_table(["Channel", "Posted", "Net sales", "Mix", "% to LY",
                   "% to plan", "Plan grain", "Traffic", "Conversion",
                   "vs LY + drivers", "OMNI penetration"], rows,
                  cls="channel",
                  titles=[None, None, None, "share of this view's net sales",
                          None, "at each brand's native grain (BR-19)", None,
                          "free-standing stores only", None, None,
                          "omni-attributed sales inside this channel"])]
    parts = " + ".join("%s %s" % (r["label"], fmt.money_exact(r["net_sales"]))
                       for r in cb["rows"]) or "nothing"
    if cb.get("attributed_channel"):
        # The one scope where the channel total is NOT the page headline, so
        # it says which figure is which instead of asserting an equality it
        # does not have. The stores row alone is the headline above; the
        # attributed row is trade the headline never counted.
        stores = next((r for r in cb["rows"] if not r.get("attributed")), None)
        out.append(_recon(
            "%s = %s, the total of this cut, to the cent. The %s above is the "
            "headline on this page: e-commerce carries no brand entity, so a "
            "brand's online trade sits outside a stores-only headline and is "
            "attributed here through the SKU (BR-11 applied to the channel "
            "cut, with the grain stated rather than assumed)."
            % (parts, fmt.money_exact(cb["total"]),
               fmt.money_exact(stores["net_sales"]) if stores else "figure")))
    else:
        out.append(_recon("%s = %s, this view's headline, to the cent (BR-11 "
                          "applied to the channel cut)."
                          % (parts, fmt.money_exact(cb["total"]))))
    if cb.get("attribution_note"):
        out.append('<p class="key">%s</p>' % esc(cb["attribution_note"]))
    out.append('<p class="key">%s</p>' % esc(cb["omni_note"]))
    out.append('<p class="key">%s</p>' % esc(cb["traffic_note"]))
    if cb["scope_note"]:
        out.insert(0, _band("note", "One channel at this scope",
                            esc(cb["scope_note"])))
    return "".join(out)


def _exception_list(depth: int, d, limit: Optional[int] = None,
                    linked: bool = True) -> str:
    items = d["exceptions"][:limit] if limit else d["exceptions"]
    if not items:
        return ('<p class="key">No exception cleared its threshold today. The '
                'thresholds are stated in the formula key below.</p>')
    o = ['<ul class="exc">']
    for e in items:
        cls = {"escalation": "bad", "adverse": "bad",
               "favourable": "good"}.get(e["severity"], "soft")
        title = esc(e["title"])
        if e["href"] and linked:
            title = '<a href="%s">%s</a>' % (esc(_href(depth, e["href"])), title)
        o.append('<li><div class="h"><span class="%s">%s</span> %s'
                 '<span class="r">%s</span></div><div class="d">%s</div></li>'
                 % (cls, e["mark"], title, esc(e["rule"] or ""), esc(e["detail"])))
    o.append('</ul>')
    return "".join(o)


def _recon(text: str) -> str:
    return '<div class="recon">%s</div>' % esc(text)


def _plan_grain_block(obj, d) -> str:
    """BR-19 made legible: the same trading day read three ways, on one page,
    without a reader having to guess which brand is which."""
    ps = obj["plan_status"]
    rows = [
        ("Day-planned brands (%d entities)" % ps["day_grain"]["entities"],
         fmt.money_compact(ps["day_grain"]["actual"]),
         fmt.money_compact(ps["day_grain"]["plan"]),
         d["plan_day_attainment"], "vs the day plan"),
        ("Week-planned brand (%d entities)" % ps["week_grain"]["entities"],
         fmt.money_compact(ps["week_grain"]["wtd_actual"]),
         fmt.money_compact(ps["week_grain"]["week_plan"]),
         d["plan_week_attainment"], ps["week_grain"]["label"]),
        ("No-plan brand (%d entities)" % ps["no_plan"]["entities"],
         d["plan_no_plan_actual"], fmt.DASH, "no plan",
         "actuals only — never a fabricated 100%"),
    ]
    return (_table(["Plan grain", "Actual", "Plan", "Attainment", "Basis"], rows)
            + _recon("%s of the day's sales sit inside a plan of any grain. "
                     "A weekly plan is never spread across days (BR-19)."
                     % d["plan_coverage"]))

# =========================================================================
# Static SVG — no library, no script, no external asset (D13)
# =========================================================================

# A sequence, not a rainbow: the three token hues lead, then a muted neutral,
# then tints of the same three. Adjacent segments never share a value, so the
# separator stroke is doing contrast work rather than carrying it alone.
PALETTE = ("#2C5F8A", "#8A6416", "#2A7355", "#6B7885", "#A33A2A",
           "#6E93B4", "#BFA469", "#6FA98D", "#A8B2BB", "#C99184")
INK_SVG = "#18242F"
SOFT_SVG = "#6B7885"
HAIR_SVG = "#EAE6DD"
PANEL_SVG = "#FFFFFF"


def _fmt_n(v: float) -> str:
    """Fixed-precision coordinate formatting, so two renders of the same data
    produce byte-identical path strings (NFR-2)."""
    return ("%.2f" % v).rstrip("0").rstrip(".") or "0"


def _arc_path(cx, cy, r_out, r_in, a0, a1) -> str:
    import math
    large = 1 if (a1 - a0) > 180.0 else 0
    def pt(r, a):
        rad = math.radians(a - 90.0)
        return (cx + r * math.cos(rad), cy + r * math.sin(rad))
    x0, y0 = pt(r_out, a0)
    x1, y1 = pt(r_out, a1)
    x2, y2 = pt(r_in, a1)
    x3, y3 = pt(r_in, a0)
    return ("M%s %s A%s %s 0 %d 1 %s %s L%s %s A%s %s 0 %d 0 %s %s Z"
            % (_fmt_n(x0), _fmt_n(y0), _fmt_n(r_out), _fmt_n(r_out), large,
               _fmt_n(x1), _fmt_n(y1), _fmt_n(x2), _fmt_n(y2), _fmt_n(r_in),
               _fmt_n(r_in), large, _fmt_n(x3), _fmt_n(y3)))


DONUT_FONT = ("ui-monospace,'SF Mono',Menlo,Consolas,monospace")


def _donut(rings, centre_top: str = "", centre_sub: str = "",
           size: int = 210) -> str:
    """A double-layer donut: `rings` is a list of ring definitions, outermost
    first, each a list of (label, value).

    Two deliberate choices. Segments are separated by a hairline in the panel
    colour rather than by hoping adjacent hues differ enough — a two-percent
    slice next to a forty-percent one has to be visible as its own thing. And
    the inner ring is thinner than the outer, so the eye reads the outer as the
    primary cut instead of treating the two as equals."""
    cx = cy = size / 2.0
    o = ['<svg class="viz" viewBox="0 0 %d %d" width="%d" height="%d" '
         'role="img" aria-label="%s">' % (size, size, size, size,
                                          esc(centre_top or "donut"))]
    bands = (30.0, 20.0, 15.0)
    gap = 6.0
    r_out = size / 2.0 - 7.0
    for depth_i, ring in enumerate(rings):
        band = bands[min(depth_i, len(bands) - 1)]
        total = sum(max(0.0, v) for _l, v in ring) or 1.0
        ang = 0.0
        for i, (label, value) in enumerate(ring):
            frac = max(0.0, value) / total
            sweep = frac * 360.0
            if sweep <= 0.0:
                continue
            o.append('<path d="%s" fill="%s" stroke="%s" stroke-width="1"'
                     ' stroke-linejoin="round"><title>%s — %s</title></path>'
                     % (_arc_path(cx, cy, r_out, r_out - band, ang, ang + sweep),
                        PALETTE[i % len(PALETTE)], PANEL_SVG,
                        esc(label), esc(fmt.pct_plain(frac))))
            ang += sweep
        r_out -= (band + gap)
    inner = max(8.0, r_out)
    o.append('<circle cx="%s" cy="%s" r="%s" fill="%s"/>'
             % (_fmt_n(cx), _fmt_n(cy), _fmt_n(inner), PANEL_SVG))
    if centre_top:
        o.append('<text x="%s" y="%s" text-anchor="middle" font-family="%s" '
                 'font-size="16" font-weight="600" fill="%s" '
                 'letter-spacing="-0.3">%s</text>'
                 % (_fmt_n(cx), _fmt_n(cy + 2), DONUT_FONT, INK_SVG,
                    esc(centre_top)))
    if centre_sub:
        o.append('<text x="%s" y="%s" text-anchor="middle" font-family="%s" '
                 'font-size="8.5" fill="%s" letter-spacing="1.1">%s</text>'
                 % (_fmt_n(cx), _fmt_n(cy + 17), DONUT_FONT, SOFT_SVG,
                    esc(centre_sub.upper())))
    o.append('</svg>')
    return "".join(o)


def _donut_keys(ring) -> str:
    total = sum(max(0.0, v) for _l, v in ring) or 1.0
    parts = []
    for i, (label, value) in enumerate(ring):
        parts.append('<i><span class="sw" style="background:%s"></span>%s %s</i>'
                     % (PALETTE[i % len(PALETTE)], esc(label),
                        esc(fmt.pct_plain(max(0.0, value) / total))))
    return '<div class="legendkeys">%s</div>' % "".join(parts)


def _trend(series, labels=None, w: int = 348, h: int = 116,
           colour: str = "#2C5F8A", second=None, second_colour: str = "#8A6416",
           title: str = "") -> str:
    """A trend line, optionally with a second independently-scaled series (the
    deck's traffic-vs-conversion chart).

    Each series keeps its own axis because they are different units; sharing
    one would be a lie of shape. The first series gets a soft area fill so the
    eye reads it as the subject and the second as the comparison, and both get
    an endpoint dot because the last value is the one anyone actually looks
    for."""
    if not series:
        return ""
    pad_x, pad_t, pad_b = 10.0, 12.0, 14.0

    def geometry(vals):
        lo, hi = min(vals), max(vals)
        span = (hi - lo) or (abs(hi) or 1.0)
        step = (w - 2 * pad_x) / float(max(1, len(vals) - 1))
        pts = []
        for i, v in enumerate(vals):
            x = pad_x + i * step
            y = h - pad_b - ((v - lo) / span) * (h - pad_t - pad_b)
            pts.append((x, y))
        return pts

    o = ['<svg class="viz" viewBox="0 0 %d %d" width="%d" height="%d" '
         'role="img" aria-label="%s">' % (w, h, w, h, esc(title or "trend"))]
    # three faint gridlines, so a slope can be read as a magnitude
    for frac in (0.25, 0.5, 0.75):
        y = pad_t + (h - pad_t - pad_b) * frac
        o.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" '
                 'stroke-width="1"/>' % (_fmt_n(pad_x), _fmt_n(y),
                                         _fmt_n(w - pad_x), _fmt_n(y), HAIR_SVG))
    o.append('<line x1="%s" y1="%s" x2="%s" y2="%s" stroke="%s" '
             'stroke-width="1"/>' % (_fmt_n(pad_x), _fmt_n(h - pad_b),
                                     _fmt_n(w - pad_x), _fmt_n(h - pad_b),
                                     "#D8D2C7"))
    main = geometry(series)
    area = ("M%s %s " % (_fmt_n(main[0][0]), _fmt_n(h - pad_b))
            + " ".join("L%s %s" % (_fmt_n(x), _fmt_n(y)) for x, y in main)
            + " L%s %s Z" % (_fmt_n(main[-1][0]), _fmt_n(h - pad_b)))
    o.append('<path d="%s" fill="%s" opacity="0.10"/>' % (area, colour))
    o.append('<polyline fill="none" stroke="%s" stroke-width="2" '
             'stroke-linecap="round" stroke-linejoin="round" points="%s"/>'
             % (colour, " ".join("%s,%s" % (_fmt_n(x), _fmt_n(y))
                                 for x, y in main)))
    o.append('<circle cx="%s" cy="%s" r="3" fill="%s" stroke="%s" '
             'stroke-width="1.5"/>' % (_fmt_n(main[-1][0]), _fmt_n(main[-1][1]),
                                       PANEL_SVG, colour))
    if second:
        sec = geometry(second)
        o.append('<polyline fill="none" stroke="%s" stroke-width="1.6" '
                 'stroke-dasharray="4 3" stroke-linecap="round" points="%s"/>'
                 % (second_colour, " ".join("%s,%s" % (_fmt_n(x), _fmt_n(y))
                                            for x, y in sec)))
        o.append('<circle cx="%s" cy="%s" r="3" fill="%s" stroke="%s" '
                 'stroke-width="1.5"/>' % (_fmt_n(sec[-1][0]), _fmt_n(sec[-1][1]),
                                           PANEL_SVG, second_colour))
    o.append('</svg>')
    return "".join(o)


def _hour_bars(hours, overlay: str = "traffic") -> str:
    """Hour-by-hour net sales with a selectable overlay. Static: both variants
    are pre-rendered and the page links between them, because the site's only
    JavaScript is the what-if calculator (PRD §6)."""
    if not hours:
        return '<p class="key">No hourly detail for this door and day.</p>'
    max_net = max(h["net_sales"] for h in hours) or 1.0
    key = "traffic" if overlay == "traffic" else "transactions"
    max_ov = max(h[key] for h in hours) or 1
    o = ['<div class="hours">']
    for h in hours:
        hn = h["net_sales"] / max_net * 100.0
        ov = (h[key] / float(max_ov)) * 100.0
        o.append('<div class="h" title="%s — %s · %s %s">'
                 '<div class="b2" style="height:%s%%"></div>'
                 '<div class="b" style="height:%s%%"></div>'
                 '<div class="t">%02d</div></div>'
                 % (esc("%02d:00" % h["hour"]), esc(fmt.money_compact(h["net_sales"])),
                    esc(fmt.count(h[key])), esc(key),
                    _fmt_n(ov * 0.45), _fmt_n(hn * 0.55), h["hour"]))
    o.append('</div>')
    o.append('<div class="legendkeys"><i><span class="sw" '
             'style="background:#2C5F8A"></span>net sales</i>'
             '<i><span class="sw" style="background:#8A6416"></span>%s</i></div>'
             % esc(key))
    return "".join(o)

# =========================================================================
# The daily ops flash page (every archived day)
# =========================================================================

def render_day(obj, nav: Optional[Dict[str, object]] = None) -> str:
    """One archived flash on the web. `nav` carries only links — never data,
    so a navigation bug can never change a number."""
    nav = nav or {}
    d = obj["display"]
    date_iso = obj["date"]
    depth = 1
    o = []
    a = o.append

    a(_persona_nav(depth, deep_date(obj), "day"))
    a(_companion_band(obj))
    a(_header(
        "%s · %s" % (obj["company"], obj["product"]),
        d["date_long"],
        "%s · fiscal %s · %s · week %d · generated for the morning of %s%s"
        % (esc(d["week_label"]), esc(d["period_label"]), esc(d["quarter_label"]),
           obj["calendar"]["week"], esc(d["as_of"]),
           " · VERSION %d (restatement)" % obj["version"] if obj["version"] > 1 else "")))

    a(_day_versions_bar(obj, nav, depth))
    a(_kpi_row(d, obj))
    a(_day_banners(obj, d, nav, depth))
    a('<p class="narr">%s</p>' % esc(obj["narrative"]))

    a(_headline_blocks(depth, obj["headlines"],
                       linked=obj.get("deep_links", False)))

    a("<h2>Exceptions — the day's calls to action</h2>")
    a(_exception_list(depth, d, linked=obj.get("deep_links", False)))

    a("<h2>Focus — what moved the comp</h2>")
    a(_day_focus(obj, d))

    a('<h2 data-nav="Store status">Store status and the three-tier view</h2>')
    a(_day_status(obj, d))

    a("<h2>Plan, at each brand's own grain</h2>")
    a(_plan_grain_block(obj, d))

    a("<h2>Windows</h2>")
    a(_day_windows(d))

    a('<h2 data-nav="Slices">By brand, affiliate, region and channel</h2>')
    a(_day_slices(obj, d, depth))

    a('<h2 data-nav="Channels">Stores and e-commerce</h2>')
    a(_channel_section(obj["channel_block"]))

    a("<h2>Omni — attribution, never addition</h2>")
    a(_day_omni(obj, d, depth))

    a("<h2>Customer file</h2>")
    a(_day_customer(obj, d, depth))

    a("<h2>Merchandise</h2>")
    a(_day_merch(obj, d, depth))

    a("<h2>E-commerce — demand vs settled</h2>")
    a(_day_ecom(obj, d))

    if obj["recap"]:
        a("<h2>Monday trade recap — the week that closed</h2>")
        a(_day_recap(d))

    a("<h2>Drill down</h2>")
    a(_day_deep_links(obj, depth))

    a("<h2>Disclosures</h2>")
    a(_day_disclosures(obj))
    a("<h2>Formula key</h2>")
    a(_day_method(obj))
    a(_legend())
    a(_pager(nav, depth))
    a(_footer())
    return _page("Ops Flash — %s" % d["date_long"], "\n".join(o), depth=depth)


def _day_versions_bar(obj, nav, depth) -> str:
    bits = []
    for v in nav.get("versions", []):
        label = "version %d%s" % (v["version"],
                                  " (as sent)" if v["version"] == 1 else " (restated)")
        if v["href"] == nav.get("stem_href"):
            bits.append('<b>%s</b>' % esc(label))
        else:
            bits.append('<a href="%s">%s</a>' % (esc(v["href"]), esc(label)))
    if nav.get("history"):
        bits.append('<a href="%s">version history</a>' % esc(nav["history"]))
    if nav.get("settled"):
        bits.append('<a href="%s">settled view</a>' % esc(nav["settled"]))
    if nav.get("email"):
        bits.append('<a href="%s">morning digest</a>' % esc(nav["email"]))
    if nav.get("extract"):
        bits.append('<a href="%s">door extract (CSV)</a>' % esc(nav["extract"]))
    if not bits:
        return ""
    return '<div class="key">%s</div>' % " · ".join(bits)


def _day_banners(obj, d, nav, depth) -> str:
    o = []
    c = obj["comp"]
    if nav.get("live_note"):
        o.append(_band("note", "Generated on demand", esc(nav["live_note"])))
    if c["override_in_effect"]:
        o.append(_band("gold", "Holiday alignment in effect",
                       "Leading comp %s is measured against %s — the same "
                       "holiday last year. The raw week-aligned comparison (%s) "
                       "reads %s, and the same-calendar-date comparison reads "
                       "%s. The adjusted figure leads; all three are stated."
                       % (esc(d["comp_pct"]), esc(d["holiday_aligned_ly_date"]),
                          esc(d["week_aligned_ly_date"]), esc(d["week_aligned_pct"]),
                          esc(d["calendar_date_pct"] or fmt.NA))))
    cm = obj["completeness"]
    if cm["missing"]:
        o.append(_band("alert", "Incomplete — %s" % esc(d["completeness"]),
                       "%s had not posted at generation time. Missing doors are "
                       "excluded from totals and comp, never counted as zero. "
                       "Posted sales are %s of the trailing-4 same-weekday "
                       "average." % (esc(", ".join(cm["missing_names"])),
                                     esc(d["posted_pct"]))))
    if cm["traffic_missing"]:
        o.append(_band("alert", "Traffic not posted",
                       "%s posted sales but no door traffic. Conversion for "
                       "those doors is UNAVAILABLE and they are excluded from "
                       "the fleet conversion on both sides — never shown as 0%%."
                       % esc(", ".join(cm["traffic_missing_names"]))))
    if obj["version"] > 1 and obj["reason"]:
        o.append(_band("note", "Restatement — version %d" % obj["version"],
                       esc(obj["reason"])))
    inv = obj["omni"]["invariance"]
    o.append(_band("calc", "Omni invariance (BR-9)",
                   "Headline net sales with the omni layer on: <b>%s</b>. With "
                   "it off: <b>%s</b>. The same number, because omni panels "
                   "attribute %s of these sales rather than add to them."
                   % (esc(d["omni"]["invariance_on"]),
                      esc(d["omni"]["invariance_off"]),
                      esc(d["omni"]["attributed_share"]))))
    return "".join(o)


def _day_focus(obj, d) -> str:
    f = d["focus"]
    o = ['<ul class="focus">']
    for e in f["entries"]:
        mark = "▼" if e["adverse"] else "▲"
        cls = "bad" if e["adverse"] else "good"
        o.append('<li><span class="mk %s">%s</span>%s' % (cls, mark, esc(e["line"])))
        for r in e["receipts"]:
            o.append('<span class="rc">%s</span>' % esc(r))
        o.append('</li>')
    o.append('<li><span class="mk soft">·</span>%s %s</li>'
             % (esc(f["remainder_label"]), esc(f["remainder"])))
    o.append('</ul>')
    o.append(_recon("Named contributions + all other = %s, the headline comp "
                    "gap, to the cent (BR-6)." % f["headline_gap"]))
    o.append(_table(["Region", "LY", "TY", "Δ", "%"],
                    [(r["label"], r["ly"], r["ty"], r["delta"], r["pct"])
                     for r in f["trailing_regions"]]))
    return "".join(o)


def _day_status(obj, d) -> str:
    s = obj["status"]
    funnel = ('<div class="funnel">'
              '<div class="f"><div class="l">Portfolio</div><div class="n">%d</div></div>'
              '<div class="arrow">→</div>'
              '<div class="f"><div class="l">Trading</div><div class="n">%d</div></div>'
              '<div class="arrow">→</div>'
              '<div class="f"><div class="l">Comp trading</div><div class="n">%d</div></div>'
              '<div class="f"><div class="l">%% trading</div><div class="n">%s</div></div>'
              '<div class="f"><div class="l">%% comp of trading</div><div class="n">%s</div></div>'
              '</div>' % (s["portfolio"], s["trading"], s["comp_trading"],
                          esc(d["pct_trading"]), esc(d["pct_comp_of_trading"])))
    rows = []
    for key in ("COMP_TRADING", "ALL_TRADING", "TOTAL"):
        t = d["tiers"][key]
        raw = obj["tiers"][key]
        rows.append((t["tier"], t["entities"], t["net_sales"],
                     ("raw", "%s %s" % (_tri(raw["comp_pct"]), esc(t["comp_pct"]))),
                     t["plan"],
                     ("raw", "%s %s" % (_tri((raw["plan_attainment"] or 1.0) - 1.0),
                                        esc(t["plan_attainment"])))))
    return (funnel + _fav_key()
            + _table(["Tier", "Entities", "Net sales", "% to LY", "Plan",
                      "% to plan"], rows, cls="tier")
            + _recon("Closed doors: %s. Comp trading excludes remodels and "
                     "doors with fewer than 13 full periods of trading (BR-2)."
                     % (", ".join(s["closed_ids"]) or "none")))


def _day_windows(d) -> str:
    rows = []
    for k in ("LW", "WTD", "MTD", "QTD", "YTD"):
        w = d["windows"][k]
        rows.append((w["label"], w["range"], w["net_sales"], w["comp_pct"],
                     w["plan_attainment"], w["conversion"],
                     w["conversion_move"], w["upt"], w["upt_vs_ly"],
                     w["pct_new_to_file"]))
    return _table(["Window", "Range", "Net sales", "Comp", "Plan", "Conversion",
                   "vs LY", "UPT", "vs LY", "New-to-file"], rows,
                  titles=[None, None, "Σ net sales over the window's days",
                          "each day against its own aligned LY date",
                          "day-grain plan only", "Σ transactions ÷ Σ traffic",
                          "basis points", "Σ units ÷ Σ transactions, never an "
                          "average of daily ratios", "the basket lever",
                          "new buyers ÷ total buyers"])


def _day_slices(obj, d, depth) -> str:
    o = []
    for dim, heading, linker in (
            ("brand", "Brand", lambda r: ("brand/%s/%s.html" % (r["key"], obj["date"])
                                          if r["key"] != "ECOM" else None)),
            ("affiliate", "Affiliate", lambda r: "affiliate/%s/%s.html"
             % (r["key"], obj["date"])),
            ("region", "Region", lambda r: (
                None if r["key"] == "ECOM"
                else "region/%s/%s.html" % (_slug(r["key"]), obj["date"]))),
            ("channel", "Channel", lambda r: None),
            ("district", "District", lambda r: "district/%s/%s.html"
             % (r["key"], obj["date"]))):
        rows = []
        for r in d["slices"][dim]:
            href = linker(r) if obj.get("deep_links") else None
            first = _link(depth, href, r["label"]) if href else r["label"]
            rows.append((first, r["coverage"], r["net_sales"], r["comp_pct"],
                         r["plan_attainment"], r["plan_grain_mix"],
                         r["conversion"], r["conversion_move"],
                         r["upt"], r["upt_vs_ly"]))
        o.append("<h3>%s</h3>" % esc(heading))
        o.append(_table([heading, "Posted", "Net sales", "Comp", "Plan",
                         "Plan grain", "Conversion", "vs LY + drivers", "UPT",
                         "vs LY"], rows))
    o.append(_recon("Brand + e-commerce, affiliate, region and district each "
                    "sum to the same %s headline (BR-11)." % d["net_sales"]))
    return "".join(o)


def _day_omni(obj, d, depth) -> str:
    o = []
    rows = []
    for f in d["omni"]["families"]:
        label = f["label"]
        if obj.get("deep_links"):
            label = _link(depth, "omni/%s/%s.html" % (f["key"], obj["date"]),
                          f["label"])
        rows.append((label, f["orders"], f["sales"], f["aov"], f["vs_ly"],
                     f["all_orders"], f["all_sales"], f["completion"]))
    o.append(_table(["Family", "Recognized orders", "Recognized sales", "AOV",
                     "vs LY", "All-inclusive orders", "All-inclusive sales",
                     "Completion"], rows,
                    titles=[None, "picked up / delivered / converted / returned",
                            None, None, "recognized basis vs the aligned LY day",
                            "every order created on the day, any status", None,
                            "share of the day's created cohort that completed"]))
    o.append('<p class="key">Recognized and all-inclusive are different series '
             'over different populations. They are never added and never charted '
             'as one (BR-10).</p>')
    o.append('<div class="tiles">%s%s%s</div><!--/tiles-->' % (
        _tile("OMNI penetration", d["omni"]["penetration"], "calc",
              d["omni"]["penetration_bps"] + " vs LY", small=True),
        _tile("Omni-attributed sales", d["omni"]["attributed"], "",
              "a slice of net sales, not an addition", small=True),
        _tile("BOPIS upsell", d["omni"]["upsell_sales"], "",
              "%s attach on %s picked-up orders"
              % (d["omni"]["upsell_attach"], d["omni"]["upsell_orders"]), small=True)))
    return "".join(o)


def _day_customer(obj, d, depth) -> str:
    c = d["customer"]
    tiles = '<div class="tiles">%s%s%s%s%s</div><!--/tiles-->' % (
        _tile("Total buyers", c["total_buyers"], "", "one transaction, one buyer",
              small=True),
        _tile("New to file", c["new_buyers"], "",
              "%s of buyers · %s vs LY" % (c["pct_new_to_file"], c["ntf_bps_vs_ly"]),
              small=True),
        _tile("Repeat rate", c["repeat_rate"], "", "%s repeat buyers"
              % c["repeat_buyers"], small=True),
        _tile("New-customer sales", c["new_sales"], "",
              "%s of net · AST %s (%s of fleet)"
              % (c["new_pct_of_sales"], c["new_ast"], c["new_ast_index"]), small=True),
        _tile("Customer file", c["file_size"], "", "identities acquired to date",
              small=True))
    link = ""
    if obj.get("deep_links"):
        link = ('<p class="key"><a href="%s">Full customer panel →</a></p>'
                % esc(_href(depth, "customer/%s.html" % obj["date"])))
    return tiles + link


def _day_merch(obj, d, depth) -> str:
    m = d["merch"]
    if not m["available"]:
        return _band("note", "SKU grain unavailable", esc(m["reason"]))
    rows = []
    for r in m["categories"]:
        label = r["category"]
        if obj.get("deep_links"):
            label = _link(depth, "category/%s/%s.html" % (_slug(r["category"]),
                                                          obj["date"]), r["category"])
        rows.append((label, r["net_sales"], r["mix_pct"], r["comp_pct"],
                     r["plan"], r["plan_attainment"], r["plan_coverage"],
                     r["units"], r["aur"]))
    o = [_table(["Category", "Net sales", "Mix", "Comp", "Plan (derived)",
                 "% to plan", "Plan coverage", "Units", "AUR"], rows,
                titles=[None, None, "share of the day's net sales",
                        "same comp entity set as the headline",
                        "entity plan split by the LY category mix — an "
                        "allocation, not a plan", None,
                        "share of the category's sales that sit inside a plan",
                        None, None])]
    o.append(_recon(m["reconciliation"] + " (BR-11)"))
    o.append("<h3>Top movers vs the aligned LY day</h3>")
    o.append(_mover_table(obj, m["top"], depth))
    o.append("<h3>Bottom movers</h3>")
    o.append(_mover_table(obj, m["bottom"], depth))
    if obj.get("deep_links"):
        o.append('<p class="key"><a href="%s">Full merchandise panel →</a></p>'
                 % esc(_href(depth, "merch/%s.html" % obj["date"])))
    return "".join(o)


def _mover_table(obj, movers, depth) -> str:
    rows = []
    for r in movers:
        label = r["name"]
        if obj.get("deep_links"):
            label = _link(depth, "sku/%s.html" % r["sku_id"], r["name"])
        rows.append((label, r["category"], r["ty"], r["ly"], r["delta"],
                     r["pct"], r["share"],
                     "new" if r["new"] else r["days_since_launch"]))
    return _table(["SKU", "Category", "TY", "LY", "Δ", "% vs LY",
                   "Contribution", "Days since launch"], rows,
                  titles=[None, None, None, None, None, None,
                          "SKU delta ÷ the group's LY total — these sum to the "
                          "group's own comp %", None])


def _day_ecom(obj, d) -> str:
    if "ecom" not in d:
        return '<p class="key">No e-commerce row for this day.</p>'
    e = d["ecom"]
    rows = [("Demand (ordered)", e["demand"], e["demand_comp"]),
            ("Shipped (settled)", e["shipped"], e["shipped_comp"]),
            ("Returns recorded", e["returns"], ""),
            ("Settled return rate (matured window)", e["return_rate"], ""),
            ("Demand % of gross", d["demand_pct_of_gross"], "")]
    return (_table(["", "Amount", "vs LY"], rows)
            + '<p class="key">Headline uses %s. This day is %s (settles after '
              '%d days); the archive shows both series without rewriting this '
              'flash (BR-4).</p>'
              % (esc(e["basis"]), esc(e["matured"]),
                 obj["ecom"].get("settle_lag_days", 3)))


def _day_recap(d) -> str:
    r = d["recap"]
    return (_table(["Closed week", "Net sales", "Comp", "Plan"],
                   [("Week %s" % r["range"], r["net_sales"], r["comp_pct"],
                     r["plan_attainment"])])
            + '<p class="key">%s has %s of plan left across %s selling days — '
              '%s a day to make it.</p>'
              % (esc(r["period_label"]), esc(r["remaining_plan"]),
                 esc(r["remaining_days"]), esc(r["run_rate"])))


def _day_deep_links(obj, depth) -> str:
    date_iso = deep_date(obj)
    note = ""
    if not obj.get("deep_links"):
        note = _band("note", "Drill-down tier",
                     "The full drill-down is pre-rendered for the last 14 "
                     "days. This day's own figures are complete above and its "
                     "detail is in the database at the same depth; the links "
                     "below open the most recent full-depth day (%s) rather "
                     "than 404." % esc(date_iso))
    cards = []
    for label, path, blurb in (
            ("Corporate landing", "corporate/%s.html" % date_iso,
             "Timeframe grid, channel and omni donuts, brand rank, trend lines"),
            ("Field Leadership", "field/%s.html" % date_iso,
             "Districts and doors, coaching-first"),
            ("Merchandise", "merch/%s.html" % date_iso,
             "Category grid and the full mover tables"),
            ("Customer", "customer/%s.html" % date_iso,
             "New-to-file, repeat rate, omni capture"),
            ("Rank — net sales", "rank/net_sales/%s.html" % date_iso,
             "Top and bottom doors by any KPI"),
            ("Door extract (CSV)", "extracts/%s-doors.csv" % date_iso,
             "Door × brand × the full KPI set, byte-stable")):
        cards.append('<div class="card"><div class="n">Drill</div>'
                     '<div class="h"><a href="%s">%s</a></div>%s</div>'
                     % (esc(_href(depth, path)), esc(label), esc(blurb)))
    return note + '<div class="cards">%s</div>' % "".join(cards)


def _day_disclosures(obj) -> str:
    return "".join('<p class="disc"><b>%s</b> %s</p>' % (esc(i["rule"]), esc(i["text"]))
                   for i in obj["disclosures"])


def _day_method(obj) -> str:
    return "".join('<p class="key"><b>%s</b> — %s</p>'
                   % (esc(m["metric"]), esc(m["formula"])) for m in obj["method"])


def _pager(nav, depth) -> str:
    prev = ('<a href="%s">← %s</a>' % (esc(nav["prev_href"]), esc(nav["prev_label"]))
            if nav.get("prev_href") else "<span></span>")
    nxt = ('<a href="%s">%s →</a>' % (esc(nav["next_href"]), esc(nav["next_label"]))
           if nav.get("next_href") else "<span></span>")
    return '<div class="pager">%s%s</div>' % (prev, nxt)

# =========================================================================
# Persona landings — the owner's scoping matrix, one page each (BR-18)
# =========================================================================

def _persona_kpi_row(p) -> str:
    d = p["display"]
    h = p["headline"]
    tiles = [
        _tile("Net sales", d["net_sales"], "", d["net_sales_exact"]),
        _tile("Comp", d["comp_pct"], _num_class(h["comp_pct"]),
              "%s comp doors" % d["comp_trading"]),
        _tile("Plan attainment", d["plan_attainment"],
              _num_class(h["plan_attainment"], pivot=1.0), d["plan_gap"]),
        _tile("Transactions", d["transactions"], "", d["txn_comp"] + " vs LY"),
        _tile("AST", d["ast"], _num_class(h["ast_pct_vs_ly"]),
              d["ast_vs_ly"] + " vs LY · = AOV"),
        _tile("AUS", d["aus"], _num_class(h["aus_pct_vs_ly"]),
              d["aus_vs_ly"] + " vs LY · = AUR"),
        _tile("UPT", d["upt"], _num_class(h["upt_pct_vs_ly"]),
              d["upt_vs_ly"] + " vs LY"),
        _tile("Traffic", d["traffic"], _num_class(h["traffic_pct_vs_ly"]),
              d["traffic_pct"] + " vs LY"),
        _tile("Conversion", d["conversion"], _num_class(h["conversion_bps_vs_ly"]),
              d["conversion_bps"] + " vs LY"),
        _tile("New customers", d["new_customers"], "",
              "%s of sales" % d["new_customer_pct"]),
        _tile("Returns", d["returns"], "", "%s of gross" % d["returns_pct_of_gross"]),
        _tile("Discounts", d["discounts"], "",
              "%s of gross" % d["discounts_pct_of_gross"]),
        _tile("OMNI penetration", d["omni_penetration"], "calc",
              d["omni_penetration_bps"] + " vs LY"),
        _tile("Portfolio / trading", "%s / %s" % (d["portfolio"], d["trading"]),
              "", "%s comp of trading" % d["pct_comp_of_trading"]),
    ]
    return '<div class="tiles">%s</div><!--/tiles-->' % "".join(tiles)


ROLLUP_HEADINGS = {"brand": "Brand", "region": "Region", "affiliate": "Affiliate",
                   "district": "District (Field Leadership)", "doors": "Doors"}


def _rollup_table(p_key: str, dim: str, rows, date_iso: str, depth: int) -> str:
    if not rows:
        return ""
    out = ["<h3>%s</h3>" % esc(ROLLUP_HEADINGS[dim])]
    table_rows = []
    for r in rows:
        href = None
        if dim == "brand" and r["key"] != "ECOM":
            href = "brand/%s/%s.html" % (r["key"], date_iso)
        elif dim == "region":
            # ECOM is a channel bucket, not a geography: it has no landing page.
            href = (None if r["key"] == "ECOM"
                    else "region/%s/%s.html" % (_slug(r["key"]), date_iso))
        elif dim == "affiliate":
            href = "affiliate/%s/%s.html" % (r["key"], date_iso)
        elif dim == "district":
            href = "district/%s/%s.html" % (r["key"], date_iso)
        elif dim == "doors":
            href = "store/%s/%s.html" % (r["key"], date_iso)
        first = _link(depth, href, r["label"]) if href else r["label"]
        table_rows.append((
            first, "%d/%d" % (r["reported_entities"], r["open_entities"]),
            fmt.money_compact(r["net_sales"]),
            ("raw", "%s %s" % (_tri(r["comp_pct"]), esc(fmt.pct(r["comp_pct"])))),
            fmt.pct_plain(r["plan_attainment"]),
            "/".join(r["plan_grain_mix"]) or "no plan",
            fmt.pct_plain(r["conversion"], 2),
            r["conversion_move"],
            fmt.ratio(r["upt"]),
            fmt.pct(r["upt_pct_vs_ly"]),
        ))
    out.append(_table([ROLLUP_HEADINGS[dim], "Posted", "Net sales", "% to LY",
                       "% to plan", "Plan grain", "Conversion", "vs LY + drivers",
                       "UPT", "vs LY"], table_rows))
    return "".join(out)


def _bps_str(v) -> str:
    if v is None:
        return fmt.NA
    sign = "+" if v >= 0 else fmt.MINUS
    return "%s%d bp" % (sign, abs(int(round(v))))


def render_persona(obj, persona_key: str, nav: Dict[str, object]) -> str:
    """One persona landing. `persona_key` is 'kind/key' — e.g. 'region/West'."""
    p = obj["personas"][persona_key]
    depth = nav["depth"]
    date_iso = obj["date"]
    d = obj["display"]
    o = []
    a = o.append

    a(_persona_nav(depth, date_iso, p["kind"]))
    a(_companion_band(obj))
    a(_crumbs(depth, nav["crumbs"]))
    a(_header("%s view · %s" % (p["persona_label"], obj["product"]),
              "%s — %s" % (p["label"], d["date_long"]),
              "Opens on: %s · %s · fiscal %s · week %d"
              % (esc(p["scope_note"]), esc(d["week_label"]),
                 esc(d["period_label"]), obj["calendar"]["week"])))

    if p["currency_note"]:
        a(_band("gold", "Currency", esc(p["currency_note"])))
    a(_persona_kpi_row(p))
    a(_headline_blocks(depth, p["headlines"], linked=True))

    if p["kind"] == "corporate":
        a(_corp_visuals(obj, depth))
        trends = render_corp_trends(obj, nav.get("trend_series"), depth)
        if trends:
            a("<h2>Trends — the last %d days</h2>" % len(nav["trend_series"]))
            a(trends)

    a("<h2>Exceptions in this view</h2>")
    a(_exception_list(depth, {"exceptions": [
        {"kind": e["kind"], "severity": e["severity"], "title": e["title"],
         "detail": e["detail"], "href": e["href"], "rule": e["rule"],
         "mark": {"escalation": "!", "adverse": "▼", "watch": "•",
                  "favourable": "▲"}.get(e["severity"], "•")}
        for e in p["exceptions"]]}))

    a('<h2 data-nav="Scoped tables">%s</h2>' % esc(p["scope_note"]))
    a(_fav_key())
    for dim in p["rollups"]:
        a(_rollup_table(persona_key, dim, p["rollups"][dim], date_iso, depth))

    if p["kind"] == "corporate":
        a("<h2>Top doors — expand for the full rank</h2>")
        a(_corp_rank(obj, depth))

    a('<h2 data-nav="Channels">Stores and e-commerce</h2>')
    a(_channel_section(p["channel_block"]))

    a("<h2>Plan, at each brand's own grain</h2>")
    a(_persona_plan(p))

    a(_recon("Every figure on this page is the same computed object the day "
             "flash, the morning digest and the door extract read. Only the "
             "scope differs (BR-18)."))
    a('<p class="key"><a href="%s">Full day flash for %s →</a> · '
      '<a href="%s">door extract (CSV)</a></p>'
      % (esc(_href(depth, "day/%s.html" % date_iso)), esc(d["date_short"]),
         esc(_href(depth, "extracts/%s-doors.csv" % date_iso))))
    a(_legend())
    a(_footer())
    return _page("%s — %s · %s" % (p["persona_label"], p["label"], d["date_short"]),
                 "\n".join(o), depth=depth)


def _persona_plan(p) -> str:
    ps = p["plan_status"]
    rows = [
        ("Day-planned (%d entities)" % ps["day_grain"]["entities"],
         fmt.money_compact(ps["day_grain"]["actual"]),
         fmt.money_compact(ps["day_grain"]["plan"]),
         fmt.pct_plain(ps["day_grain"]["attainment"]), "vs the day plan"),
        ("Week-planned (%d entities)" % ps["week_grain"]["entities"],
         fmt.money_compact(ps["week_grain"]["wtd_actual"]),
         fmt.money_compact(ps["week_grain"]["week_plan"]),
         fmt.pct_plain(ps["week_grain"]["attainment"]),
         ps["week_grain"]["label"]),
        ("No plan (%d entities)" % ps["no_plan"]["entities"],
         fmt.money_compact(ps["no_plan"]["actual"]), fmt.DASH, "no plan",
         "actuals only — never a fabricated 100%"),
    ]
    return (_table(["Plan grain", "Actual", "Plan", "Attainment", "Basis"], rows)
            + _recon(ps["disclosure"]))


# -- Corporate landing extras (D13) ---------------------------------------

def _corp_visuals(obj, depth: int) -> str:
    d = obj["display"]
    o = ["<h2>Timeframe grid</h2>"]
    rows = []
    for k in ("WTD", "LW", "MTD", "QTD", "YTD"):
        w = d["windows"][k]
        rows.append((w["label"], w["range"], w["net_sales"], w["comp_pct"],
                     w["plan_attainment"], w["transactions"], w["conversion"],
                     w["conversion_move"], w["pct_new_to_file"]))
    rows.insert(0, ("Today", d["date_short"], d["net_sales"], d["comp_pct"],
                    d["plan_attainment"], d["transactions"], d["conversion"],
                    d["conversion_move"], fmt.pct_plain(
                        obj["customer"]["day"]["ty"]["pct_new_to_file"])))
    o.append(_table(["Timeframe", "Range", "Net sales", "Comp", "Plan",
                     "Transactions", "Conversion", "vs LY + drivers",
                     "New-to-file"], rows))

    channel = [(s["label"], s["net_sales"]) for s in obj["slices"]["channel"]]
    brands = [(s["label"], s["net_sales"]) for s in obj["slices"]["brand"]]
    omni_parts = obj["omni"]["penetration"]["parts"]
    omni_ring = [(k, v) for k, v in sorted(omni_parts.items()) if v > 0]
    rest = max(0.0, obj["headline"]["net_sales"] - sum(v for _k, v in omni_ring))
    regions = [(s["label"], s["net_sales"]) for s in obj["slices"]["region"]
               if s["net_sales"] > 0]
    affil = [(s["label"], s["net_sales"]) for s in obj["slices"]["affiliate"]]

    o.append("<h2>Where the day came from</h2>")
    o.append('<div class="vizrow">')
    o.append('<figure>%s%s<figcaption>Outer ring: channel. Inner ring: brand '
             '(e-commerce carries brand on the SKU, so it is its own '
             'segment).</figcaption></figure>'
             % (_donut([channel, brands], d["net_sales"], "net sales"),
                _donut_keys(channel)))
    o.append('<figure>%s%s<figcaption>Outer ring: omni-attributed sales by '
             'family against everything else. These sales are already inside '
             'the headline (BR-9).</figcaption></figure>'
             % (_donut([omni_ring + [("Non-omni", rest)]],
                       d["omni_penetration"], "omni"),
                _donut_keys(omni_ring + [("Non-omni", rest)])))
    o.append('<figure>%s%s<figcaption>Outer ring: region. Inner ring: '
             'affiliate, converted once at the seeded fixed rate '
             '(BR-16).</figcaption></figure>'
             % (_donut([regions, affil], d["comp_pct"], "comp"),
                _donut_keys(regions)))
    o.append('</div>')
    return "".join(o)


def _corp_rank(obj, depth: int) -> str:
    r = obj["ranks"]["net_sales"]
    date_iso = obj["date"]
    def rows_for(items):
        return [(_link(depth, "store/%s/%s.html" % (x["entity_id"], date_iso),
                       x["name"]),
                 x["brand_id"] or "—", x["region"],
                 fmt.money_compact(x["value"])) for x in items]
    top5 = _table(["Door", "Brand", "Region", "Net sales"], rows_for(r["top"][:5]))
    more = _table(["Door", "Brand", "Region", "Net sales"], rows_for(r["top"][5:]))
    bottom = _table(["Door", "Brand", "Region", "Net sales"], rows_for(r["bottom"]))
    return (top5 + '<details class="rank"><summary>Expand — the rest of the top '
            'ten, and the bottom ten</summary>%s%s</details>'
            '<p class="key"><a href="%s">All rank tables, by any KPI →</a></p>'
            % (more, bottom,
               esc(_href(depth, "rank/net_sales/%s.html" % date_iso))))


def render_corp_trends(obj, series, depth: int) -> str:
    """Trend lines for the corporate landing: net sales, and traffic against
    conversion on independent axes."""
    if not series:
        return ""
    sales = [s["net_sales"] for s in series]
    traffic = [s["traffic"] for s in series if s["traffic"] is not None]
    conv = [s["conversion"] for s in series if s["conversion"] is not None]
    o = ['<div class="vizrow">']
    o.append('<figure>%s<figcaption>Net sales, last %d days.</figcaption></figure>'
             % (_trend(sales, title="net sales"), len(sales)))
    if traffic and conv:
        o.append('<figure>%s<div class="legendkeys">'
                 '<i><span class="sw" style="background:#2C5F8A"></span>traffic</i>'
                 '<i><span class="sw" style="background:#8A6416"></span>conversion</i>'
                 '</div><figcaption>Traffic and conversion on independent axes — '
                 'they are different units and sharing one would be a lie of '
                 'shape.</figcaption></figure>'
                 % _trend(traffic, second=conv, title="traffic vs conversion"))
    o.append('</div>')
    return "".join(o)

# =========================================================================
# Drill pages — district, door, hourly, tree, category, SKU
# =========================================================================

def render_store_entry(obj, nav) -> str:
    """The Store Manager entry page: pick your door.

    The other five personas each have one landing because there is one
    Corporate and six Regions. There are twenty-nine doors, so the sixth
    persona's landing is a door picker — no auth, an entry page like the rest
    (PRD §6). Doors are grouped by brand and then region, because a store
    manager knows their brand before they know their district code."""
    depth = nav["depth"]
    date_iso = obj["date"]
    d = obj["display"]
    o = [_persona_nav(depth, date_iso, "store"), _companion_band(obj),
         _crumbs(depth, nav["crumbs"]),
         _header("Store Manager view · %s" % obj["product"],
                 "Pick your door — %s" % d["date_long"],
                 "Opens on: your own door · hourly · KPI tree · omni · "
                 "customer · %s" % esc(d["week_label"]))]
    o.append(_band("note", "One page per door per day",
                   "Each door's landing opens on what that door can act on "
                   "today — its conversion, its basket, its omni execution, "
                   "its trading shape and its category movement, each against "
                   "the door's own recent form — and then carries the full "
                   "Store Manager page beneath it."))

    stores = [b for b in obj["stores"].values()]
    by_brand = {}
    for b in stores:
        by_brand.setdefault(b["brand_id"] or "ECOM", []).append(b)

    ranked = {r["entity_id"]: i + 1
              for i, r in enumerate(obj["ranks"]["net_sales"]["top"])}
    for brand_id in sorted(by_brand):
        brand_name = next((b["brand_name"] for b in by_brand[brand_id]
                           if b["brand_name"]), brand_id)
        o.append("<h2>%s</h2>" % esc(brand_name or brand_id))
        rows = []
        for b in sorted(by_brand[brand_id],
                        key=lambda x: (x["region"], x["entity_id"])):
            eid = b["entity_id"]
            first = _link(depth, "store/%s/%s.html" % (eid, date_iso), b["name"])
            if not b["posted"]:
                rows.append((first, b["region"], b["district_id"] or "—",
                             "not posted", "", "", "", ""))
                continue
            hd = b["headline"]
            hl = b.get("headlines") or {"attention": [], "celebration": []}
            top = (hl["attention"][0]["headline"] if hl["attention"]
                   else (hl["celebration"][0]["headline"]
                         if hl["celebration"] else "nothing over threshold"))
            rows.append((
                first, b["region"], b["district_id"] or "—",
                fmt.money_compact(hd["net_sales"]),
                ("raw", "%s %s" % (_tri(hd["comp_pct"]),
                                   esc(fmt.pct(hd["comp_pct"])))),
                (fmt.pct_plain(hd["conversion"], 2)
                 if hd["conversion_available"] else "unavailable"),
                fmt.ratio(hd["upt"]),
                ("raw", esc(top))))
        o.append(_table(["Door", "Region", "District", "Net sales", "% to LY",
                         "Conversion", "UPT", "Top of its own list"], rows))
    o.append(_recon("Every figure here is the same computed object each door's "
                    "own landing reads, and the same one the day flash and the "
                    "extract read. Only the scope differs (BR-18)."))
    o.append(_legend())
    o.append(_footer())
    return _page("Store Manager — pick your door, %s" % d["date_short"],
                 "\n".join(o), depth=depth)


def render_district(obj, district_id: str, nav) -> str:
    depth = nav["depth"]
    date_iso = obj["date"]
    d = obj["display"]
    row = next(r for r in obj["slices"]["district"] if r["key"] == district_id)
    doors = [s for reg in obj["drill"]["regions"] for dd in reg["districts"]
             if dd["key"] == district_id for s in dd["stores"]]
    o = [_persona_nav(depth, date_iso, "field"), _crumbs(depth, nav["crumbs"]),
         _header("District · %s" % row["region"],
                 "%s — %s" % (row["label"], d["date_long"]),
                 "%d doors · %d posted · %s"
                 % (row["open_entities"], row["reported_entities"],
                    esc(d["week_label"])))]
    for ccy in row.get("currencies", []):
        o.append(_currency_band(obj, ccy, what="Every door in %s" % row["label"]))
    o.append('<div class="tiles">%s%s%s%s%s</div><!--/tiles-->' % (
        _tile("Net sales", fmt.money_compact(row["net_sales"]), "",
              fmt.money_exact(row["net_sales"])),
        _tile("Comp", fmt.pct(row["comp_pct"]), _num_class(row["comp_pct"]),
              "%d comp doors" % row["comp_members"]),
        _tile("Plan attainment", fmt.pct_plain(row["plan_attainment"]),
              _num_class(row["plan_attainment"], pivot=1.0),
              "grain: %s" % ("/".join(row["plan_grain_mix"]) or "no plan")),
        _tile("Conversion", fmt.pct_plain(row["conversion"], 2), "",
              _bps_str(row["conversion_bps_vs_ly"]) + " vs LY"),
        _tile("Traffic", fmt.count(row["traffic"]), "", "FSS only")))
    o.append("<h2>Doors</h2>")
    o.append(_fav_key())
    rows = []
    for s in doors:
        rows.append((_link(depth, "store/%s/%s.html" % (s["key"], date_iso),
                           s["label"]),
                     "%d/%d" % (s["reported_entities"], s["open_entities"]),
                     fmt.money_compact(s["net_sales"]),
                     ("raw", "%s %s" % (_tri(s["comp_pct"]),
                                        esc(fmt.pct(s["comp_pct"])))),
                     fmt.pct_plain(s["plan_attainment"]),
                     "/".join(s["plan_grain_mix"]) or "no plan",
                     fmt.pct_plain(s["conversion"], 2),
                     s["conversion_move"],
                     fmt.ratio(s["upt"]), fmt.pct(s["upt_pct_vs_ly"])))
    o.append(_table(["Door", "Posted", "Net sales", "% to LY", "% to plan",
                     "Plan grain", "Conversion", "vs LY + drivers", "UPT", "vs LY"], rows))
    o.append(_recon("Doors sum to %s, this district's total (BR-11)."
                    % fmt.money_exact(row["net_sales"])))
    o.append(_legend())
    o.append(_footer())
    return _page("District %s — %s" % (row["label"], d["date_short"]),
                 "\n".join(o), depth=depth)


def render_store(obj, entity_id: str, nav) -> str:
    """The unified Store Manager page (PRD §6): performance, omni, customer,
    merchandise, hourly and the KPI tree, on one page per door per day."""
    depth = nav["depth"]
    date_iso = obj["date"]
    b = obj["stores"][entity_id]
    d = obj["display"]
    o = [_persona_nav(depth, date_iso, "field"), _crumbs(depth, nav["crumbs"])]
    o.append(_header(
        "Store Manager view · %s%s" % (b["brand_name"] or "E-commerce",
                                       " · %s" % b["region"]),
        "%s — %s" % (b["name"], d["date_long"]),
        "#%s · %s, %s · district %s · %s · plan grain %s%s"
        % (b["store_number"], esc(b["city"] or ""), esc(b["state_province"] or ""),
           esc(b["district_id"] or "—"), esc(b["affiliate_id"]),
           esc(b["plan_grain"].lower()),
           "" if b["comp_eligible"] else " · NON-COMP")))

    if not b["posted"]:
        o.append(_band("alert", "Not posted", esc(b["missing_note"])))
        o.append(_footer())
        return _page("%s — %s" % (b["name"], d["date_short"]), "\n".join(o),
                     depth=depth)

    h = b["headline"]
    hd = _store_display(b)
    o.append('<div class="tiles">%s</div><!--/tiles-->' % "".join([
        _tile("Net sales", hd["net_sales"], "", hd["net_sales_local"]),
        _tile("Comp", hd["comp_pct"], _num_class(h["comp_pct"]),
              "contribution %s" % hd["contribution"]),
        _tile("Plan attainment", hd["plan_attainment"],
              _num_class(h["plan_attainment"], pivot=1.0),
              "grain: %s" % b["plan_grain"].lower()),
        _tile("Transactions", hd["transactions"], "", hd["txn_comp"] + " vs LY"),
        _tile("AST", hd["ast"], _num_class(h["ast_pct_vs_ly"]),
              hd["ast_vs_ly"] + " vs LY · = AOV"),
        _tile("AUS", hd["aus"], _num_class(h["aus_pct_vs_ly"]),
              hd["aus_vs_ly"] + " vs LY · = AUR"),
        _tile("UPT", hd["upt"], _num_class(h["upt_pct_vs_ly"]),
              hd["upt_vs_ly"] + " vs LY · LY " + hd["ly_upt"]),
        _tile("Traffic", hd["traffic"], _num_class(h["traffic_pct_vs_ly"]),
              hd["traffic_pct"] + " vs LY"),
        _tile("Conversion", hd["conversion"], _num_class(h["conversion_bps_vs_ly"]),
              hd["conversion_bps"] + " vs LY"),
        _tile("New customers", hd["new_customers"], "",
              "%s of sales" % hd["new_customer_pct"]),
        _tile("Returns", hd["returns"], "", "%s of gross" % hd["returns_pct"]),
        _tile("Discounts", hd["discounts"], "", "%s of gross" % hd["discounts_pct"]),
        _tile("OMNI penetration", hd["omni_penetration"], "calc",
              hd["omni_penetration_bps"] + " vs LY"),
    ]))

    o.append(_currency_band(obj, b["currency"], b["net_sales_local"],
                            h["net_sales"], what=b["name"]))

    if b.get("headlines"):
        o.append(_headline_blocks(depth, b["headlines"], linked=True))

    o.append("<h2>Hours — the day's shape</h2>")
    o.append(_hour_bars(b["hourly"]["hours"], "traffic"))
    o.append('<p class="key">%s <a href="%s">Full hourly view →</a></p>'
             % (esc(b["hourly"]["governance"]),
                esc(_href(depth, "store/%s/hourly/%s.html" % (entity_id, date_iso)))))

    o.append("<h2>Why — the KPI tree</h2>")
    o.append(_tree_nodes(b["tree"]))
    o.append('<p class="key"><a href="%s">Open the tree with the what-if '
             'calculator →</a></p>'
             % esc(_href(depth, "store/%s/tree/%s.html" % (entity_id, date_iso))))

    o.append("<h2>Windows</h2>")
    wrows = []
    for k in ("WTD", "MTD", "QTD"):
        w = b["windows"][k]
        wrows.append((w["label"], "%s – %s" % (fmt.day_short(w["start"]),
                                               fmt.day_short(w["end"])),
                      fmt.money_compact(w["net_sales"]), fmt.pct(w["comp_pct"]),
                      fmt.pct_plain(w["plan_attainment"]),
                      fmt.pct_plain(w["conversion"], 2),
                      w["conversion_move"],
                      fmt.ratio(w["upt"]), fmt.pct(w["upt_pct_vs_ly"])))
    o.append(_table(["Window", "Range", "Net sales", "Comp", "Plan",
                     "Conversion", "vs LY + drivers", "UPT", "vs LY"], wrows))

    o.append("<h2>Merchandise at this door</h2>")
    o.append(_store_categories(obj, b, depth))

    o.append('<h2 data-nav="Channels">Stores and e-commerce</h2>')
    o.append(_channel_section(b["channel_block"]))

    o.append("<h2>Omni execution</h2>")
    o.append(_store_omni(b))

    o.append("<h2>Customer</h2>")
    o.append(_store_customer(b))

    o.append(_recon("This door's net sales roll into district %s, region %s and "
                    "the %s fleet headline without restatement (BR-11)."
                    % (b["district_id"], b["region"], d["net_sales"])))
    o.append(_legend())
    o.append(_footer())
    return _page("%s — %s" % (b["name"], d["date_short"]), "\n".join(o),
                 depth=depth)


def _store_display(b) -> Dict[str, str]:
    h = b["headline"]
    c = b.get("contribution") or {}
    return {
        "net_sales": fmt.money_compact(h["net_sales"]),
        "net_sales_local": "%s %s" % (fmt.money_exact(b["net_sales_local"]),
                                      b["currency"]),
        "comp_pct": fmt.pct(h["comp_pct"]),
        "contribution": fmt.pct(c.get("contribution")),
        "plan_attainment": fmt.pct_plain(h["plan_attainment"]),
        "transactions": fmt.count(h["transactions"]),
        "txn_comp": fmt.pct(h["comp_transactions"]["pct"]),
        "ast": fmt.money_plain(h["ast"]), "aus": fmt.money_plain(h["aus"]),
        "upt": fmt.ratio(h["upt"]),
        "ast_vs_ly": fmt.pct(h["ast_pct_vs_ly"]),
        "aus_vs_ly": fmt.pct(h["aus_pct_vs_ly"]),
        "upt_vs_ly": fmt.pct(h["upt_pct_vs_ly"]),
        "ly_upt": fmt.ratio(h["ly_upt"]),
        "traffic": fmt.count(h["traffic"]),
        "traffic_pct": fmt.pct(h["traffic_pct_vs_ly"]),
        "conversion": (fmt.pct_plain(h["conversion"], 2)
                       if h["conversion_available"] else "unavailable"),
        "conversion_bps": _bps_str(h["conversion_bps_vs_ly"]),
        "new_customers": fmt.count(h["new_customers"]),
        "new_customer_pct": fmt.pct_plain(h["new_customer_pct"]),
        "returns": fmt.money_compact(h["returns"]),
        "returns_pct": fmt.pct_plain(h["returns_pct_of_gross"]),
        "discounts": fmt.money_compact(h["discounts"]),
        "discounts_pct": fmt.pct_plain(h["discounts_pct_of_gross"]),
        "omni_penetration": fmt.pct_plain(h["omni_penetration"], 2),
        "omni_penetration_bps": _bps_str(h["omni_penetration_bps_vs_ly"]),
    }


def _store_categories(obj, b, depth) -> str:
    c = b["categories"]
    if not c.get("available"):
        return _band("note", "SKU grain unavailable", esc(c.get("reason", "")))
    rows = [(_link(depth, "category/%s/%s.html" % (_slug(r["category"]), obj["date"]),
                   r["category"]),
             fmt.money_compact(r["net_sales"]), fmt.pct_plain(r["mix_pct"]),
             fmt.pct(r["comp_pct"]), fmt.count(r["units"]),
             fmt.money_plain(r["aur"])) for r in c["categories"]]
    out = [_table(["Category", "Net sales", "Mix", "Comp", "Units", "AUR"], rows)]
    out.append(_recon("Categories sum to %s, this door's posted net sales."
                      % fmt.money_exact(c["reconciliation"]["entity_day_total"])))
    m = b["movers"]
    if m.get("available") and m["top"]:
        out.append("<h3>SKU movers at this door</h3>")
        rows = [(_link(depth, "sku/%s.html" % r["sku_id"], r["name"]),
                 r["category"], fmt.money_compact(r["ty"]),
                 fmt.money_compact(r["ly"]), fmt.money_signed(r["delta"]),
                 fmt.pct(r["pct_vs_ly"]))
                for r in (m["top"][:5] + m["bottom"][:5])]
        out.append(_table(["SKU", "Category", "TY", "LY", "Δ", "% vs LY"], rows))
    return "".join(out)


def _store_omni(b) -> str:
    rows = []
    for fam in ("BOPIS", "RTD", "OOFIS", "CR"):
        f = b["omni"]["families"][fam]
        rows.append((OMNI_TITLES[fam], fmt.count(f["recognized"]["orders"]),
                     fmt.money_compact(f["recognized"]["sales"]),
                     fmt.money_plain(f["recognized"]["aov"]),
                     fmt.pct(f["recognized_pct_vs_ly"]),
                     fmt.count(f["all_inclusive"]["orders"]),
                     fmt.pct_plain(f["completion_rate"])))
    bo = b["omni"]["boris"]["recognized"]
    rows.append((OMNI_TITLES["BORIS"], fmt.count(bo["orders"]),
                 fmt.money_compact(bo["returned_sales"]), fmt.DASH,
                 fmt.pct(b["omni"]["boris"]["pct_vs_ly"]), fmt.DASH,
                 fmt.pct_plain(bo["save_rate"])))
    up = b["omni"]["upsell"]
    return (_table(["Family", "Recognized orders", "Recognized sales", "AOV",
                    "vs LY", "All-inclusive orders", "Completion / save rate"],
                   rows)
            + '<p class="key">Pickup upsell: %s on %s of %s picked-up orders '
              '(%s attach). Upsell sits inside this door\'s own net sales; '
              'the BOPIS order sits inside e-commerce demand (BR-9).</p>'
              % (esc(fmt.money_compact(up["upsell_sales"])),
                 esc(fmt.count(up["upsell_orders"])),
                 esc(fmt.count(up["picked_up_orders"])),
                 esc(fmt.pct_plain(up["attach_pct"]))))


def _store_customer(b) -> str:
    c = b["customer"]
    ty = c["day"]["ty"]
    nb = c["new_block"]
    return '<div class="tiles">%s%s%s%s</div><!--/tiles-->' % (
        _tile("Buyers", fmt.count(ty["total_buyers"]), "",
              "one transaction, one buyer", small=True),
        _tile("New to file", fmt.count(ty["new_buyers"]), "",
              "%s of buyers" % fmt.pct_plain(ty["pct_new_to_file"]), small=True),
        _tile("New-customer sales", fmt.money_compact(nb["net_sales"]), "",
              "%s of net · AST %s" % (fmt.pct_plain(nb["pct_of_net_sales"]),
                                      fmt.money_plain(nb["ast"])), small=True),
        _tile("WTD new-to-file", fmt.pct_plain(c["wtd"]["pct_new_to_file"]), "",
              "%s new buyers" % fmt.count(c["wtd"]["new_buyers"]), small=True))


def tree_contributions(t):
    """Driver contributions at CENT precision, reconciled so the displayed
    column sums to the displayed gap.

    The underlying waterfall telescopes exactly — that is proved on the object
    and re-proved in the tests. What broke here was the display: compact money
    rounds anything under $1,000 to whole dollars, so +$404.85, −$665.31 and
    −$11.45 printed as +$405, −$665 and −$11 and summed to −$271 against a
    gap of −$272. A column a reader adds up has to add up, so contributions
    are shown to the cent and any residual from the object's own per-part
    rounding lands on the largest part — the same rule the category and hourly
    tables use."""
    rows = [{"driver": x["driver"], "ty": x["ty"], "ly": x["ly"],
             "contribution": x["contribution"]} for x in t["drivers"]]
    reconcile_display(rows, "contribution", t["gap"])
    ast = next(r for r in rows if r["driver"] == "ast")
    split = [{"driver": x["driver"], "ty": x["ty"], "ly": x["ly"],
              "contribution": x["contribution"]} for x in t["ast_split"]]
    reconcile_display(split, "contribution", ast["contribution"])
    return rows, split


def _tree_nodes(t) -> str:
    if not t.get("available"):
        return _band("note", "Tree unavailable", esc(t.get("reason", "")))
    rows, split = tree_contributions(t)
    dr = {x["driver"]: x for x in rows}
    sp = {x["driver"]: x for x in split}

    def node(label, value, ly_value, contrib):
        return ('<div class="node"><div class="l">%s</div>'
                '<div class="v">%s</div>'
                '<div class="c soft">LY %s</div>'
                '<div class="c %s">%s to the gap</div></div>'
                % (esc(label), esc(value), esc(ly_value),
                   "good" if contrib >= 0 else "bad",
                   esc(fmt.money_signed_exact(contrib))))

    o = ['<div class="tree">']
    o.append(node("Traffic", fmt.count(dr["traffic"]["ty"]),
                  fmt.count(dr["traffic"]["ly"]), dr["traffic"]["contribution"]))
    o.append(u'<div class="node op">×</div>')
    o.append(node("Conversion", fmt.pct_plain(dr["conversion"]["ty"], 2),
                  fmt.pct_plain(dr["conversion"]["ly"], 2),
                  dr["conversion"]["contribution"]))
    o.append(u'<div class="node op">×</div>')
    o.append(node("AST", fmt.money_plain(dr["ast"]["ty"]),
                  fmt.money_plain(dr["ast"]["ly"]), dr["ast"]["contribution"]))
    o.append('<div class="node op">=</div>')
    o.append('<div class="node"><div class="l">Net sales</div><div class="v">%s</div>'
             '<div class="c soft">LY %s</div><div class="c %s">gap %s</div></div>'
             % (esc(fmt.money_exact(t["actual"])), esc(fmt.money_exact(t["ly"])),
                "good" if t["gap"] >= 0 else "bad",
                esc(fmt.money_signed_exact(t["gap"]))))
    o.append('</div>')

    o.append('<div class="tree">')
    o.append(u'<div class="node op">↳</div>')
    o.append(node("AUS", fmt.money_plain(sp["aus"]["ty"]),
                  fmt.money_plain(sp["aus"]["ly"]), sp["aus"]["contribution"]))
    o.append(u'<div class="node op">×</div>')
    o.append(node("UPT", fmt.ratio(sp["upt"]["ty"]), fmt.ratio(sp["upt"]["ly"]),
                  sp["upt"]["contribution"]))
    o.append('</div>')
    o.append(_recon(u"Traffic %s, conversion %s and AST %s sum to %s — the "
                    u"sales gap, to the cent. Residual interaction %s. %s"
                    % (fmt.money_signed_exact(dr["traffic"]["contribution"]),
                       fmt.money_signed_exact(dr["conversion"]["contribution"]),
                       fmt.money_signed_exact(dr["ast"]["contribution"]),
                       fmt.money_signed_exact(t["gap"]),
                       fmt.money_exact(t["residual_interaction"]), t["method"])))
    return "".join(o)


def render_hourly(obj, entity_id: str, nav) -> str:
    """The Store Hourly view (D9). Both overlays are pre-rendered — the site's
    only JavaScript is the what-if calculator, so 'selectable' here means the
    reader opens the other overlay, not that a script redraws it."""
    depth = nav["depth"]
    b = obj["stores"][entity_id]
    d = obj["display"]
    hs = b["hourly"]
    o = [_persona_nav(depth, obj["date"], "field"), _crumbs(depth, nav["crumbs"]),
         _header("Store Hourly · %s" % b["region"],
                 "%s — %s" % (b["name"], d["date_long"]),
                 "Hours %02d:00–%02d:00 local · unaudited intraday view"
                 % (hs["open_hour"], hs["close_hour"]))]
    o.append(_currency_band(obj, b["currency"], b["net_sales_local"],
                            b["headline"]["net_sales"], what=b["name"]))
    o.append(_band("gold", "Intraday and unaudited (BR-17)",
                   "%s Hourly buckets are an allocation of the posted day, so "
                   "they sum to it exactly: hourly total %s against the posted "
                   "%s, reconciliation gap %s."
                   % (esc(hs["governance"]),
                      esc(fmt.money_exact(hs["hourly_net_total"])),
                      esc(fmt.money_exact(hs["day_net_total"])),
                      esc(fmt.money_exact(hs["reconciliation_gap"])))))
    o.append("<h2>Net sales by hour, with traffic overlay</h2>")
    o.append(_hour_bars(hs["hours"], "traffic"))
    o.append('<details class="rank"><summary>Switch overlay to transactions'
             '</summary>%s</details>' % _hour_bars(hs["hours"], "transactions"))

    o.append("<h2>Hour by hour</h2>")
    prof = b["hourly_profile"]
    rows = []
    for h in hs["hours"]:
        share = (h["net_sales"] / hs["hourly_net_total"]
                 if hs["hourly_net_total"] else None)
        base = (prof.get("baseline_share") or {}).get(h["hour"])
        delta = (prof.get("delta_share") or {}).get(h["hour"])
        rows.append(("%02d:00" % h["hour"], fmt.money_compact(h["net_sales"]),
                     fmt.count(h["traffic"]), fmt.count(h["transactions"]),
                     fmt.pct_plain(share), fmt.pct_plain(base),
                     fmt.pct(delta) if delta is not None else fmt.NA))
    rows.append((("total", "Day total"), fmt.money_compact(hs["hourly_net_total"]),
                 fmt.count(sum(h["traffic"] for h in hs["hours"])),
                 fmt.count(hs["hourly_transactions"]), "100.0%", "100.0%", ""))
    o.append(_table(["Hour", "Net sales", "Traffic", "Transactions",
                     "Share of day", "Own %d-week baseline" % prof.get("weeks", 0),
                     "Δ share"], rows,
                    titles=[None, None, None, None, None,
                            "this door's own trailing same-weekday hourly curve",
                            "today's shape against that curve"]))
    o.append(_recon("Σ hourly = the posted day, to the cent, for net sales and "
                    "transactions (BR-17). The peak hour today was %02d:00."
                    % (hs["peak_hour"] or 0)))
    o.append('<p class="key"><a href="%s">← Store Manager page</a> · '
             '<a href="%s">KPI tree</a></p>'
             % (esc(_href(depth, "store/%s/%s.html" % (entity_id, obj["date"]))),
                esc(_href(depth, "store/%s/tree/%s.html" % (entity_id, obj["date"])))))
    o.append(_legend())
    o.append(_footer())
    return _page("Hourly — %s, %s" % (b["name"], d["date_short"]),
                 "\n".join(o), depth=depth)


# -- the what-if calculator: the site's only JavaScript (BR-20) ------------

WHATIF_JS = """<script>
/* The what-if calculator.
   It contains NO formula of its own. The identity below is the catalog's,
   emitted into the page as data in `model`, and every input value is a number
   the catalog computed. The only arithmetic here is that identity, evaluated,
   plus one rearrangement of it to solve for conversion — the question the
   original dashboard doc asked ("what does conversion have to be to hit target
   on negative traffic?").
   On load it checks its own arithmetic against the catalog's answer and
   refuses to pretend if they disagree. */
(function () {
  var el = document.getElementById("tree-payload");
  if (!el) { return; }
  var P = JSON.parse(el.textContent);

  function sales(traffic, conversion, ast) { return traffic * conversion * ast; }
  function conversionFor(target, traffic, ast) { return target / (traffic * ast); }

  function money(v) {
    var s = Math.abs(v) >= 1000000 ? "$" + (Math.abs(v) / 1000000).toFixed(2) + "M"
          : Math.abs(v) >= 1000 ? "$" + (Math.abs(v) / 1000).toFixed(1) + "K"
          : "$" + Math.round(Math.abs(v));
    return (v < 0 ? "\\u2212" : "") + s;
  }
  function signed(v) { return (v >= 0 ? "+" : "") + money(v); }
  function pc(v) { return (v * 100).toFixed(2) + "%"; }

  var check = sales(P.traffic, P.conversion, P.ast);
  var agrees = Math.abs(check - P.net_sales) < 0.01;
  document.getElementById("wi-check").textContent = agrees
    ? "Self-check: traffic x conversion x AST reproduces the catalog's "
      + P.display.net_sales + " exactly. " + P.model
    : "SELF-CHECK FAILED: this page computes " + check
      + " where the catalog says " + P.net_sales + ". Do not trust the sliders.";
  if (!agrees) { return; }

  var ids = ["traffic", "conversion", "ast"];
  var inputs = {};
  ids.forEach(function (k) { inputs[k] = document.getElementById("wi-" + k); });

  function scenario() {
    var t = P.traffic * (1 + inputs.traffic.value / 100);
    var c = P.conversion * (1 + inputs.conversion.value / 100);
    var a = P.ast * (1 + inputs.ast.value / 100);
    return { t: t, c: c, a: a, s: sales(t, c, a) };
  }

  function paint() {
    var s = scenario();
    ids.forEach(function (k) {
      document.getElementById("wi-" + k + "-out").textContent =
        (inputs[k].value >= 0 ? "+" : "") + inputs[k].value + "%";
    });
    document.getElementById("wi-traffic-val").textContent = Math.round(s.t);
    document.getElementById("wi-conversion-val").textContent = pc(s.c);
    document.getElementById("wi-ast-val").textContent = money(s.a);
    document.getElementById("wi-sales").textContent = money(s.s);
    document.getElementById("wi-vs-actual").textContent =
      signed(s.s - P.net_sales) + " vs today";
    document.getElementById("wi-vs-ly").textContent =
      signed(s.s - P.ly_net_sales) + " vs LY (" + P.display.ly_net_sales + ")";
  }

  document.getElementById("wi-solve").addEventListener("click", function () {
    var t = P.traffic * (1 + inputs.traffic.value / 100);
    var a = P.ast * (1 + inputs.ast.value / 100);
    var needed = conversionFor(P.ly_net_sales, t, a);
    var pct = Math.round((needed / P.conversion - 1) * 1000) / 10;
    inputs.conversion.value = Math.max(-50, Math.min(50, pct));
    paint();
    document.getElementById("wi-solved").textContent =
      "To match LY (" + P.display.ly_net_sales + ") on that traffic and AST, "
      + "conversion has to reach " + pc(needed) + " — today it is "
      + P.display.conversion + ".";
  });

  ids.forEach(function (k) { inputs[k].addEventListener("input", paint); });
  document.getElementById("wi-reset").addEventListener("click", function () {
    ids.forEach(function (k) { inputs[k].value = 0; });
    document.getElementById("wi-solved").textContent = "";
    paint();
  });
  paint();
})();
</script>"""


def render_tree(obj, entity_id: str, nav) -> str:
    depth = nav["depth"]
    b = obj["stores"][entity_id]
    d = obj["display"]
    t = b["tree"]
    o = [_persona_nav(depth, obj["date"], "field"), _crumbs(depth, nav["crumbs"]),
         _header("KPI tree · %s" % b["region"],
                 "%s — %s" % (b["name"], d["date_long"]),
                 "Sales = Traffic × Conversion × AST · AST = AUS × UPT")]
    o.append(_currency_band(obj, b["currency"], b.get("net_sales_local"),
                            b["headline"]["net_sales"] if b["posted"] else None,
                            what=b["name"]))
    o.append(_tree_nodes(t))
    if not t.get("available"):
        o.append(_footer())
        return _page("KPI tree — %s" % b["name"], "\n".join(o), depth=depth)

    o.append("<h2>Driver contributions</h2>")
    contribs, split = tree_contributions(t)
    rows = [(x["driver"].upper(), fmt.money_signed_exact(x["contribution"]))
            for x in contribs]
    rows.append((("total", "Sum = the sales gap"),
                 fmt.money_signed_exact(t["gap"])))
    rows.append(("Residual interaction", fmt.money_exact(t["residual_interaction"])))
    o.append(_table(["Driver", "Contribution to the gap"], rows,
                    titles=["sequential attribution, fixed order traffic → "
                            "conversion → AST", None]))
    o.append(_table(["AST splits into", "Contribution to the gap"],
                    [(x["driver"].upper(), fmt.money_signed_exact(x["contribution"]))
                     for x in split]
                    + [(("total", "Sum = the AST contribution"),
                        fmt.money_signed_exact(
                            next(c["contribution"] for c in contribs
                                 if c["driver"] == "ast")))]))
    o.append(_recon("Sequential attribution telescopes exactly, so the residual "
                    "is zero by construction — it is computed and shown rather "
                    "than assumed (BR-20). Both columns above are shown to the "
                    "cent so that they sum to their own totals as printed."))

    payload = dict(t["payload"])
    payload["model"] = "sales = traffic x conversion x AST"
    payload["display"] = {
        "net_sales": fmt.money_compact(t["payload"]["net_sales"]),
        "ly_net_sales": fmt.money_compact(t["payload"]["ly_net_sales"]),
        "conversion": fmt.pct_plain(t["payload"]["conversion"], 2),
        "traffic": fmt.count(t["payload"]["traffic"]),
        "ast": fmt.money_plain(t["payload"]["ast"]),
    }
    if payload.get("converted"):
        # A reader who converts the USD figure back must land on the door's own
        # posted figure, not a cent away from it. So the native figure is
        # printed rather than left to be derived, and the rate is stated with
        # it (BR-16).
        o.append("<h2>This door's own currency</h2>")
        o.append(_table(
            ["", "%s (native)" % payload["local_currency"],
             "%s (converted at %s)" % (payload["currency"],
                                       fmt.ratio(payload["fx_units_per_usd"]))],
            [("Net sales", fmt.money_exact(payload["net_sales_local"]),
              fmt.money_exact(payload["net_sales"])),
             ("LY net sales", fmt.money_exact(payload["ly_net_sales_local"]),
              fmt.money_exact(payload["ly_net_sales"]))]))
        o.append(_recon(
            "The native figure is the door's posted total; the converted one is "
            "that figure divided once by %s. The calculator below works in %s "
            "and carries unrounded values, so converting its answer back at the "
            "same rate returns the native figure exactly (BR-16)."
            % (fmt.ratio(payload["fx_units_per_usd"]), payload["currency"])))
    o.append("<h2>What if — the calculator</h2>")
    o.append(_whatif_box(payload))
    o.append('<p class="key"><a href="%s">← Store Manager page</a> · '
             '<a href="%s">hourly view</a></p>'
             % (esc(_href(depth, "store/%s/%s.html" % (entity_id, obj["date"]))),
                esc(_href(depth, "store/%s/hourly/%s.html" % (entity_id, obj["date"])))))
    o.append(_legend())
    o.append(_footer())
    return _page("KPI tree — %s, %s" % (b["name"], d["date_short"]),
                 "\n".join(o), depth=depth, script=WHATIF_JS)


def _whatif_box(payload) -> str:
    data = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    sliders = []
    for key, label in (("traffic", "Traffic"), ("conversion", "Conversion"),
                       ("ast", "AST")):
        sliders.append(
            '<label for="wi-%s">%s <output id="wi-%s-out">+0%%</output> → '
            '<span id="wi-%s-val" class="calc"></span></label>'
            '<input type="range" id="wi-%s" min="-50" max="50" step="1" value="0">'
            % (key, esc(label), key, key, key))
    return (
        '<script id="tree-payload" type="application/json">%s</script>'
        '<div class="calcbox">'
        '<div class="chk" id="wi-check">Checking the calculator against the '
        'catalog…</div>%s'
        '<div class="out" id="wi-sales">—</div>'
        '<div class="chk"><span id="wi-vs-actual"></span> · '
        '<span id="wi-vs-ly"></span></div>'
        '<p style="margin:10px 0 0"><button type="button" id="wi-solve">'
        'Solve: what conversion matches LY?</button> '
        '<button type="button" id="wi-reset">Reset</button></p>'
        '<div class="chk" id="wi-solved"></div>'
        '<div class="chk">This calculator holds no formula. It is handed the '
        'catalog\'s own driver values and evaluates the catalog\'s own identity; '
        'it verifies that it reproduces the catalog\'s figure before it will let '
        'you touch a slider (BR-20).</div>'
        '</div>' % (data, "".join(sliders)))


def render_category(obj, category: str, nav) -> str:
    depth = nav["depth"]
    d = obj["display"]
    m = obj["merch"]
    row = next(r for r in m["categories"]["categories"] if r["category"] == category)
    movers = None
    o = [_persona_nav(depth, obj["date"], "day"), _companion_band(obj), _crumbs(depth, nav["crumbs"]),
         _header("Category · %s" % (row["brand_id"] or ""),
                 "%s — %s" % (category, d["date_long"]),
                 "Derived from sales lines; brand and category are never stored "
                 "on a fact row")]
    o.append('<div class="tiles">%s%s%s%s%s</div><!--/tiles-->' % (
        _tile("Net sales", fmt.money_compact(row["net_sales"]), "",
              fmt.money_exact(row["net_sales"])),
        _tile("Comp", fmt.pct(row["comp_pct"]), _num_class(row["comp_pct"]),
              "same comp entity set as the headline"),
        _tile("Mix", fmt.pct_plain(row["mix_pct"]), "", "share of the day"),
        _tile("Plan (derived)", fmt.money_compact(row["plan"]), "",
              "%s attainment · %s coverage"
              % (fmt.pct_plain(row["plan_attainment"]),
                 fmt.pct_plain(row["plan_coverage"]))),
        _tile("AUR", fmt.money_plain(row["aur"]), "",
              "%s units" % fmt.count(row["units"]))))
    run = obj["merch"]["slide_runs"].get(category)
    if run and run["consecutive_negative_days"] >= 3:
        o.append(_band("alert", "Negative %d days running"
                       % run["consecutive_negative_days"],
                       "%s has comped negative on every one of the last %d "
                       "trading days. A slide, not a bad Tuesday."
                       % (esc(category), run["consecutive_negative_days"])))
    exc = [e for e in m["exceptions"] if e["category"] == category]
    if exc:
        o.append(_band("alert", "Category exception",
                       esc(exc[0]["message"] + ".")))
    o.append("<h2>SKUs in this category, by contribution</h2>")
    o.append(_category_skus(obj, category, depth))
    o.append(_recon("These SKUs sum into %s, this category's net sales, which "
                    "sums with the other categories into the %s headline "
                    "(BR-11)." % (fmt.money_exact(row["net_sales"]), d["net_sales"])))
    o.append(_legend())
    o.append(_footer())
    return _page("%s — %s" % (category, d["date_short"]), "\n".join(o), depth=depth)


def _category_skus(obj, category, depth) -> str:
    rows = []
    for r in obj["merch"]["category_skus"].get(category, []):
        rows.append((_link(depth, "sku/%s.html" % r["sku_id"], r["name"]),
                     fmt.money_compact(r["ty"]), fmt.money_compact(r["ly"]),
                     fmt.money_signed(r["delta"]), fmt.pct(r["pct_vs_ly"]),
                     fmt.pct(r["contribution"]), fmt.count(r["ty_units"]),
                     "new" if r["days_since_launch"] < 90
                     else str(r["days_since_launch"])))
    return _table(["SKU", "TY", "LY", "Δ", "% vs LY", "Contribution", "Units",
                   "Days since launch"], rows)


def render_sku(sku, series, nav) -> str:
    """One page per SKU, covering the full-depth window as a daily series."""
    depth = nav["depth"]
    o = [_crumbs(depth, nav["crumbs"]),
         _header("SKU · %s · %s" % (sku["brand_name"], sku["category"]),
                 sku["name"],
                 "%s · list %s · launched %s (%d days ago)"
                 % (esc(sku["sku_id"]), esc(fmt.money_plain(sku["unit_price"])),
                    esc(fmt.day_short_year(sku["launch_date"])),
                    sku["days_since_launch"]))]
    if sku["days_since_launch"] < 90:
        o.append(_band("gold", "New SKU",
                       "Launched fewer than 90 days ago, so it has no "
                       "like-for-like LY history for part of this window. Where "
                       "the LY figure is absent the comparison is shown as "
                       "unavailable, never as growth from zero."))
    o.append('<div class="tiles">%s%s%s%s</div><!--/tiles-->' % (
        _tile("Window net sales", fmt.money_compact(sku["total_ty"]), "",
              "%d days" % len(series)),
        _tile("Window LY", fmt.money_compact(sku["total_ly"]), "",
              "aligned days"),
        _tile("Δ vs LY", fmt.money_signed(sku["total_delta"]),
              _num_class(sku["total_delta"]), fmt.pct(sku["total_pct"])),
        _tile("Units", fmt.count(sku["total_units"]), "",
              "AUR %s" % fmt.money_plain(sku["aur"]))))
    o.append("<h2>Daily series</h2>")
    rows = []
    for s in series:
        rows.append((_link(depth, "category/%s/%s.html"
                           % (_slug(sku["category"]), s["date"]),
                           fmt.day_short(s["date"])),
                     fmt.money_compact(s["ty"]), fmt.money_compact(s["ly"]),
                     fmt.money_signed(s["delta"]), fmt.pct(s["pct"]),
                     fmt.count(s["units"])))
    o.append(_table(["Day", "TY", "LY", "Δ", "% vs LY", "Units"], rows))
    o.append(_recon("Every row is this SKU's slice of that day's posted door "
                    "sales — an allocation, never an independent figure (BR-11)."))
    o.append(_legend())
    o.append(_footer())
    return _page("%s — %s" % (sku["name"], sku["sku_id"]), "\n".join(o),
                 depth=depth)

# =========================================================================
# Panel pages — omni family, customer, merchandise, rank
# =========================================================================

def render_omni(obj, family: str, nav) -> str:
    depth = nav["depth"]
    d = obj["display"]
    o = [_persona_nav(depth, obj["date"], "day"), _companion_band(obj), _crumbs(depth, nav["crumbs"]),
         _header("Omni panel", "%s — %s" % (OMNI_TITLES[family], d["date_long"]),
                 "Recognized and all-inclusive bases, stated separately (BR-10)")]
    f = obj["omni"]["families"][family]
    o.append(_band("calc", "Attribution, never addition (BR-9)",
                   esc(obj["omni"]["attribution_notes"].get(
                       family, f.get("attribution", "")))))

    if family == "BORIS":
        r, ly = f["recognized"], f["ly_recognized"]
        o.append('<div class="tiles">%s%s%s%s%s</div><!--/tiles-->' % (
            _tile("Returns", fmt.count(r["orders"]), "",
                  "%s of merchandise" % fmt.money_compact(r["returned_sales"])),
            _tile("vs LY", fmt.pct(f["pct_vs_ly"]),
                  _num_class(f["pct_vs_ly"], positive_is_good=False),
                  "returned basis"),
            _tile("Saves", fmt.count(r["saved_orders"]), "calc",
                  "%s save rate" % fmt.pct_plain(r["save_rate"])),
            _tile("Saved sales", fmt.money_compact(r["saved_sales"]), "calc",
                  "%s of returned value"
                  % fmt.pct_plain(r["saved_pct_of_returned"])),
            _tile("Label savings", fmt.money_compact(r["label_savings"]), "gold",
                  "US$%.2f per return" % f["label_saving_constant_usd"])))
        o.append('<p class="key">%s</p>' % esc(f["label_saving_note"]))
        o.append("<h2>Save leaderboard — trailing 14 days</h2>")
        rows = [(_link(depth, "store/%s/%s.html" % (r_["entity_id"], obj["date"]),
                       r_["name"]),
                 r_["region"], fmt.count(r_["returns"]), fmt.count(r_["saves"]),
                 fmt.pct_plain(r_["save_rate"]),
                 fmt.money_compact(r_["returned_sales"]),
                 fmt.money_compact(r_["saved_sales"]))
                for r_ in obj["omni"]["boris_leaderboard"]]
        o.append(_table(["Door", "Region", "Returns", "Saves", "Save rate",
                         "Returned", "Saved"], rows))
    else:
        rec, ai = f["recognized"], f["all_inclusive"]
        o.append('<div class="tiles">%s%s%s%s%s%s</div><!--/tiles-->' % (
            _tile("Recognized orders", fmt.count(rec["orders"]), "",
                  f["recognized_basis"]),
            _tile("Recognized sales", fmt.money_compact(rec["sales"]), "",
                  "AOV %s" % fmt.money_plain(rec["aov"])),
            _tile("vs LY", fmt.pct(f["recognized_pct_vs_ly"]),
                  _num_class(f["recognized_pct_vs_ly"]),
                  "recognized basis, aligned day"),
            _tile("All-inclusive orders", fmt.count(ai["orders"]), "",
                  f["all_inclusive_basis"]),
            _tile("All-inclusive sales", fmt.money_compact(ai["sales"]), "",
                  "AOV %s" % fmt.money_plain(ai["aov"])),
            _tile("Completion", fmt.pct_plain(f["completion_rate"]), "calc",
                  f["completion_basis"])))
        o.append(_band("note", "Two series, never one", esc(f["basis_warning"])))

        o.append('<h2 data-nav="Status mix">Status of the day\'s created cohort</h2>')
        mix = f["status_mix"]
        o.append(_table(["Status", "Orders"],
                        [(k, fmt.count(v)) for k, v in sorted(mix.items())]))

        lift = f["lifts"]
        o.append('<h2 data-nav="Lift and share">Lift and share (recognized basis)</h2>')
        o.append(_table(
            ["", "Value"],
            [("AOV", fmt.money_plain(lift["aov"])),
             ("AOV lift vs store AOV", fmt.pct(lift["aov_lift_vs_fss"])),
             ("AOV lift vs online AOV", fmt.pct(lift["aov_lift_vs_online"])),
             ("% of store sales", fmt.pct_plain(lift["pct_of_fss_sales"])),
             ("% of online sales", fmt.pct_plain(lift["pct_of_online_sales"]))]))

        cap = obj["customer"]["omni_capture"].get(family)
        if cap:
            o.append("<h2>New-buyer capture</h2>")
            o.append(_table(["", "Value"],
                            [("Buyers on the recognized basis",
                              fmt.count(cap["total_buyers"])),
                             ("New to file", fmt.count(cap["new_buyers"])),
                             ("% new to file", fmt.pct_plain(cap["pct_new_to_file"]))]))
            o.append('<p class="key">%s</p>' % esc(cap["basis"]))

        if family == "BOPIS":
            o.append("<h2>Pickup execution by region — trailing 14 days</h2>")
            pe = obj["omni"]["pickup_execution"]
            rows = [(r_["region"], fmt.count(r_["created"]),
                     fmt.count(r_["picked_up"]), fmt.pct_plain(r_["pickup_rate"]))
                    for r_ in pe["regions"]]
            rows.append((("total", "Fleet"), "", "",
                         fmt.pct_plain(pe["fleet_pickup_rate"])))
            o.append(_table(["Region", "Created", "Picked up", "Pickup rate"], rows))
            o.append("<h2>Upsell leaderboard — trailing 14 days</h2>")
            rows = [(_link(depth, "store/%s/%s.html" % (r_["entity_id"], obj["date"]),
                           r_["name"]),
                     r_["region"], fmt.count(r_["picked_up"]),
                     fmt.count(r_["attached"]), fmt.pct_plain(r_["attach_pct"]),
                     fmt.money_compact(r_["upsell_sales"]))
                    for r_ in obj["omni"]["upsell_leaderboard"]]
            o.append(_table(["Door", "Region", "Picked up", "Attached",
                             "Attach rate", "Upsell sales"], rows))

    o.append("<h2>OMNI penetration</h2>")
    pen = obj["omni"]["penetration"]
    o.append(_table(["Family", "Attributed sales"],
                    [(k, fmt.money_compact(v))
                     for k, v in sorted(pen["parts"].items())]
                    + [(("total", "Total attributed"),
                        fmt.money_compact(pen["omni_attributed_sales"]))]))
    o.append(_recon("%s of the day's %s net sales. %s"
                    % (d["omni"]["penetration"], d["net_sales"], pen["basis"])))
    o.append('<p class="key">%s</p>' % " · ".join(
        '<a href="%s">%s</a>' % (esc(_href(depth, "omni/%s/%s.html"
                                           % (k, obj["date"]))), esc(OMNI_TITLES[k]))
        for k in obj["omni"]["family_order"] if k != family))
    o.append(_legend())
    o.append(_footer())
    return _page("%s — %s" % (OMNI_TITLES[family], d["date_short"]),
                 "\n".join(o), depth=depth)


def render_customer(obj, nav) -> str:
    depth = nav["depth"]
    d = obj["display"]
    c = obj["customer"]
    o = [_persona_nav(depth, obj["date"], "day"), _companion_band(obj), _crumbs(depth, nav["crumbs"]),
         _header("Customer panel", "Customer file — %s" % d["date_long"],
                 "New-to-file derives only from each customer's first purchase "
                 "date (BR-12)")]
    o.append('<div class="tiles">%s%s%s%s%s%s</div><!--/tiles-->' % (
        _tile("Total buyers", d["customer"]["total_buyers"], "",
              "one transaction, one buyer"),
        _tile("New to file", d["customer"]["new_buyers"], "",
              "%s of buyers" % d["customer"]["pct_new_to_file"]),
        _tile("vs LY", d["customer"]["ntf_bps_vs_ly"], "",
              "new-to-file share, basis points"),
        _tile("Repeat rate", d["customer"]["repeat_rate"], "",
              "%s repeat buyers" % d["customer"]["repeat_buyers"]),
        _tile("New-customer sales", d["customer"]["new_sales"], "",
              "%s of net · AST %s" % (d["customer"]["new_pct_of_sales"],
                                      d["customer"]["new_ast"])),
        _tile("File size", d["customer"]["file_size"], "",
              "identities acquired to date")))
    exc = c["ntf_exception"]
    if exc and exc["fires"]:
        o.append(_band("alert", "CRM flag — new-to-file below baseline",
                       esc(exc["message"] + ".")))

    o.append("<h2>Windows</h2>")
    rows = []
    for k in ("LW", "WTD", "MTD", "QTD", "YTD"):
        w = c["windows"][k]
        rows.append((w["window"], fmt.count(w["total_buyers"]),
                     fmt.count(w["new_buyers"]),
                     fmt.pct_plain(w["pct_new_to_file"]),
                     fmt.pct_plain(w["repeat_rate"])))
    o.append(_table(["Window", "Buyers", "New", "% new to file", "Repeat rate"],
                    rows))

    o.append("<h2>By channel</h2>")
    rows = []
    for ch in c["channels"]:
        b = ch["buyers"]
        nb = ch["new_block"]
        rows.append((ch["label"], fmt.count(b["total_buyers"]),
                     fmt.count(b["new_buyers"]),
                     fmt.pct_plain(b["pct_new_to_file"]),
                     fmt.money_compact(nb["net_sales"]),
                     fmt.money_plain(nb["ast"]),
                     "fires" if (ch["ntf_exception"] or {}).get("fires") else "—"))
    o.append(_table(["Channel", "Buyers", "New", "% new to file",
                     "New-customer sales", "New AST", "CRM flag"], rows))

    o.append('<h2 data-nav="New-buyer capture">New-buyer capture by omni family</h2>')
    rows = [(OMNI_TITLES[k], fmt.count(v["total_buyers"]),
             fmt.count(v["new_buyers"]), fmt.pct_plain(v["pct_new_to_file"]))
            for k, v in sorted(c["omni_capture"].items())]
    o.append(_table(["Family", "Buyers", "New", "% new to file"], rows))
    o.append(_recon("The same first-purchase-date rule produces every figure on "
                    "this page and the new-buyer lines inside the omni panels. "
                    "There is no second definition (BR-12)."))
    o.append("<h2>New Customer block</h2>")
    nb = c["new_block"]
    o.append('<p class="key">%s</p>' % esc(nb["attribution"]))
    o.append(_table(["", "Value"],
                    [("New customers", fmt.count(nb["new_customers"])),
                     ("Net sales", fmt.money_exact(nb["net_sales"])),
                     ("% of net sales", fmt.pct_plain(nb["pct_of_net_sales"])),
                     ("AST", fmt.money_plain(nb["ast"])),
                     ("AST index vs fleet",
                      fmt.pct_plain(nb["ast_index_vs_fleet"]))]))
    o.append(_legend())
    o.append(_footer())
    return _page("Customer — %s" % d["date_short"], "\n".join(o), depth=depth)


def render_merch(obj, nav) -> str:
    depth = nav["depth"]
    d = obj["display"]
    m = obj["merch"]
    o = [_persona_nav(depth, obj["date"], "day"), _companion_band(obj), _crumbs(depth, nav["crumbs"]),
         _header("Merchandise panel", "Merchandise — %s" % d["date_long"],
                 "Category and brand are derived from the SKU, never stored on "
                 "a fact row")]
    if not m["available"]:
        o.append(_band("note", "SKU grain unavailable",
                       esc(m["categories"].get("reason", ""))))
        o.append(_footer())
        return _page("Merchandise — %s" % d["date_short"], "\n".join(o), depth=depth)

    for e in m["exceptions"]:
        o.append(_band("alert", "Category exception", esc(e["message"] + ".")))

    o.append("<h2>Category grid</h2>")
    rows = []
    for r in d["merch"]["categories"]:
        rows.append((_link(depth, "category/%s/%s.html"
                           % (_slug(r["category"]), obj["date"]), r["category"]),
                     r["brand_id"], r["net_sales"], r["mix_pct"], r["comp_pct"],
                     r["plan"], r["plan_attainment"], r["plan_coverage"],
                     r["units"], r["aur"]))
    rows.append((("total", "Total"), "", d["merch"]["total"], "100.0%",
                 d["comp_pct"], "", "", "", "", ""))
    o.append(_table(["Category", "Brand", "Net sales", "Mix", "Comp",
                     "Plan (derived)", "% to plan", "Plan coverage", "Units",
                     "AUR"], rows))
    o.append(_recon(d["merch"]["reconciliation"] + " (BR-11)"))
    o.append('<p class="key">%s</p>'
             % esc(m["categories"]["plan_basis"]))

    o.append("<h2>Category basket — AUR, AUS and UPT</h2>")
    bk = m["basket"]
    if bk.get("available"):
        rows = [(r["category"], fmt.money_plain(r["aur"]), fmt.money_plain(r["aus"]),
                 fmt.ratio(r["upt"]), fmt.money_plain(r["ast"]),
                 fmt.count(r["units"])) for r in bk["categories"]]
        o.append(_table(["Category", "AUR", "AUS", "UPT", "AST", "Units"], rows))
        o.append('<p class="key">%s</p>' % esc(bk["upt_basis"]))

    o.append("<h2>Top 10 movers</h2>")
    o.append(_mover_table(obj, d["merch"]["top"], depth))
    o.append("<h2>Bottom 10 movers</h2>")
    o.append(_mover_table(obj, d["merch"]["bottom"], depth))
    o.append(_recon("Contributions across every SKU sum to the group's own "
                    "comp %s — the same decomposition discipline the focus "
                    "panel uses on doors (BR-6)." % d["comp_pct"]))
    o.append(_legend())
    o.append(_footer())
    return _page("Merchandise — %s" % d["date_short"], "\n".join(o), depth=depth)


def render_rank(obj, kpi: str, nav) -> str:
    depth = nav["depth"]
    d = obj["display"]
    r = obj["ranks"][kpi]
    o = [_persona_nav(depth, obj["date"], "day"), _companion_band(obj), _crumbs(depth, nav["crumbs"]),
         _header("Rank", "%s — %s" % (RANK_LABELS[kpi], d["date_long"]),
                 "%d doors ranked; doors where this KPI cannot be computed are "
                 "listed separately, never sorted to the bottom as zero"
                 % r["ranked"])]
    o.append('<nav class="personas">%s</nav>' % "".join(
        '<a class="%s" href="%s">%s</a>'
        % ("on" if k == kpi else "",
           esc(_href(depth, "rank/%s/%s.html" % (k, obj["date"]))),
           esc(RANK_LABELS[k])) for k in sorted(obj["ranks"])))

    def fmt_val(v):
        if kpi in ("net_sales", "ast"):
            return fmt.money_compact(v)
        if kpi in ("comp_pct",):
            return fmt.pct(v)
        if kpi in ("plan_attainment", "conversion"):
            return fmt.pct_plain(v, 2)
        if kpi == "upt":
            return fmt.ratio(v)
        return fmt.count(v)

    def rows_for(items):
        return [(_link(depth, "store/%s/%s.html" % (x["entity_id"], obj["date"]),
                       x["name"]),
                 x["brand_id"] or "—", x["region"], x["district_id"] or "—",
                 x["affiliate_id"], fmt_val(x["value"])) for x in items]

    o.append("<h2>Top 10</h2>")
    o.append(_table(["Door", "Brand", "Region", "District", "Affiliate",
                     RANK_LABELS[kpi]], rows_for(r["top"])))
    o.append("<h2>Bottom 10</h2>")
    o.append(_table(["Door", "Brand", "Region", "District", "Affiliate",
                     RANK_LABELS[kpi]], rows_for(r["bottom"])))
    if kpi == "upt" and obj.get("upt_movers"):
        o.append("<h2>Biggest UPT movers vs LY — the basket lever</h2>")
        o.append('<p class="key">The table above ranks the LEVEL. This one '
                 'ranks the MOVE, which is the one a field leader can act on: '
                 'a door with a naturally big assortment will always sit high '
                 'on level and tell you nothing.</p>')
        mv = obj["upt_movers"]

        def mrows(items):
            return [(_link(depth, "store/%s/%s.html" % (x["entity_id"],
                                                        obj["date"]), x["name"]),
                     x["region"], fmt.ratio(x["upt"]), fmt.ratio(x["ly_upt"]),
                     fmt.pct(x["upt_pct"]), fmt.pct(x["ast_pct"]),
                     fmt.pct(x["aus_pct"])) for x in items]

        head = ["Door", "Region", "UPT", "LY UPT", "UPT vs LY", "AST vs LY",
                "AUS vs LY"]
        o.append(_table(head, mrows(mv["top"])))
        o.append("<h3>Doors losing basket</h3>")
        o.append(_table(head, mrows(mv["bottom"])))
        o.append(_recon("Comp basis, day-aligned LY. A door outside the comp "
                        "set has no like-for-like basket to move against and "
                        "is listed as unavailable rather than ranked."))
    if r["unavailable"]:
        o.append("<h2>Not ranked — the KPI is unavailable for these doors</h2>")
        o.append(_table(["Door", "Brand", "Region", "District", "Affiliate",
                         "Reason"],
                        [(x["name"], x["brand_id"] or "—", x["region"],
                          x["district_id"] or "—", x["affiliate_id"],
                          "no traffic posted" if kpi == "conversion"
                          else "not computable for this door")
                         for x in r["unavailable"]]))
        o.append(_recon("A missing measurement is not a bad measurement. These "
                        "doors are named rather than ranked last (BR-15)."))
    o.append(_legend())
    o.append(_footer())
    return _page("Rank %s — %s" % (RANK_LABELS[kpi], d["date_short"]),
                 "\n".join(o), depth=depth)

# =========================================================================
# Version history (BR-7) and the archive index
# =========================================================================

def render_history(versions: List[dict]) -> str:
    depth = 1
    first = versions[0]["obj"]
    d = first["display"]
    o = [_crumbs(depth, [("Archive", "index.html"),
                         (d["date_short"], "day/%s.html" % first["date"]),
                         ("Version history", None)]),
         _header("Restatement history · BR-7",
                 "%s — %d versions" % (d["date_long"], len(versions)),
                 "A flash is immutable once sent. A correction is a new "
                 "version, never an edit.")]
    rows = []
    for v in versions:
        ob = v["obj"]
        rows.append((("raw", '<a href="%s">version %d</a>'
                      % (esc(day_href(ob["date"], ob["version"])), ob["version"])),
                     v["created_at"], ob["basis"],
                     ob["display"]["net_sales"], ob["display"]["comp_pct"],
                     ob["display"]["plan_attainment"]))
    o.append(_table(["Version", "Written", "E-comm basis", "Net sales", "Comp",
                     "Plan"], rows))
    for v in versions:
        if v["reason"]:
            o.append(_band("note", "Why version %d exists" % v["obj"]["version"],
                           esc(v["reason"])))
    v1, vn = versions[0]["obj"], versions[-1]["obj"]
    o.append("<h2>What changed</h2>")
    o.append(_table(["Figure", "Version 1 (as sent)",
                     "Version %d (restated)" % vn["version"]],
                    [("Net sales", v1["display"]["net_sales"],
                      vn["display"]["net_sales"]),
                     ("Comp", v1["display"]["comp_pct"], vn["display"]["comp_pct"]),
                     ("Plan attainment", v1["display"]["plan_attainment"],
                      vn["display"]["plan_attainment"]),
                     ("E-commerce basis", v1["ecom"].get("basis_in_headline"),
                      vn["ecom"].get("basis_in_headline"))]))
    o.append(_recon("Version 1 is preserved byte for byte at its own URL. "
                    "Nothing on this page rewrites it (BR-7)."))
    o.append(_footer())
    return _page("Version history — %s" % d["date_long"], "\n".join(o), depth=depth)


def day_href(date_iso: str, version: int = 1) -> str:
    return ("%s.html" % date_iso if version == 1
            else "%s-v%d.html" % (date_iso, version))


def render_index(days: List[dict], storylines=None, today: Optional[str] = None,
                 full_depth_dates=None, anchor: Optional[str] = None,
                 companion_base: Optional[str] = None) -> str:
    full_depth_dates = set(full_depth_dates or [])
    anchor = anchor or (days[-1]["date"] if days else "")
    o = [_persona_nav(0, anchor, "index"), _companion_band(companion_base)]
    o.append(_header(
        "Lumière Beauty Group · Operational Sales Flash",
        "The archive",
        "%d generated days ending %s · demo clock fixed at %s · full drill-down "
        "for the last %d days"
        % (len(days), esc(anchor), esc(today or ""), len(full_depth_dates))))
    if companion_base:
        o.append(_band(
            "gold", "This is the summary companion",
            'Every day\'s flash, digest and panel is here. The door, district, '
            'hourly, KPI-tree and SKU pages are on the complete site at '
            '<a href="%s">%s</a>. Both render from the same computed object, '
            'so any figure you can find in both places is the same figure '
            '(BR-13).' % (esc(companion_base), esc(companion_base))))
    o.append(_band("note", "How this archive is tiered",
                   "Every one of the %d days has its own flash page and its "
                   "restatement history. The last %d days additionally carry "
                   "the full drill-down — persona landings, districts, doors, "
                   "hourly, KPI trees, category and SKU pages, omni panels, "
                   "rank tables and the door extract. All %d days are in the "
                   "database at the same depth; only the static pages are "
                   "tiered."
                   % (len(days), len(full_depth_dates), len(days))))
    o.append("<h2>Start here</h2>")
    cards = []
    for label, path, note in (
            ("Corporate landing", "corporate/%s.html" % anchor,
             "Timeframe grid, channel and omni donuts, brand rank, trend lines"),
            ("Field Leadership", "field/%s.html" % anchor,
             "Districts and doors — the coaching view"),
            ("The day flash", "day/%s.html" % anchor,
             "Headline, exceptions, focus, every panel"),
            ("Morning digest", "email/%s.html" % anchor,
             "The phone-first email, with deep links back into this site"),
            ("Merchandise", "merch/%s.html" % anchor,
             "Category grid and the mover tables"),
            ("Door extract", "extracts/%s-doors.csv" % anchor,
             "Door × brand × the full KPI set, byte-stable CSV")):
        cards.append('<div class="card"><div class="n">Entry point</div>'
                     '<div class="h"><a href="%s">%s</a></div>%s</div>'
                     % (esc(path), esc(label), esc(note)))
    o.append('<div class="cards">%s</div>' % "".join(cards))

    o.append("<h2>Fiscal weeks</h2>")
    o.append(_calendar_grid(days, full_depth_dates))

    if storylines:
        o.append("<h2>The seeded storylines — where each one surfaces</h2>")
        rows = []
        for s in storylines:
            rows.append((("raw", '<a href="%s">%s</a>'
                          % (esc(s["href"]), esc("%d. %s" % (s["n"], s["title"])))),
                         s["rule"], s["where"]))
        o.append(_table(["Storyline", "Rule", "Where to see it"], rows))
        o.append('<p class="key">This table is generated from the same list the '
                 'README prints, so the two cannot drift apart.</p>')
    o.append(_legend())
    o.append(_footer())
    return _page("Lumière Ops Flash — archive", "\n".join(o), depth=0)


def _calendar_grid(days: List[dict], full_depth_dates) -> str:
    by_date = {e["date"]: e for e in days}
    dates = sorted(by_date)
    if not dates:
        return ""
    start = D.fromisoformat(dates[0])
    end = D.fromisoformat(dates[-1])
    start -= dt.timedelta(days=(start.weekday() + 1) % 7)      # back to Sunday
    o = ['<div class="scroll"><table class="cal"><tr><th class="wk">Week</th>']
    for h in WEEKDAY_HEADS:
        o.append("<th>%s</th>" % h)
    o.append("</tr>")
    cur = start
    while cur <= end:
        entries = [by_date.get((cur + dt.timedelta(days=i)).isoformat())
                   for i in range(7)]
        label = _week_range(cur)
        o.append('<tr><td class="wk">%s</td>' % esc(label))
        for i in range(7):
            o.append("<td>%s</td>" % _cell(entries[i],
                                           (cur + dt.timedelta(days=i)),
                                           full_depth_dates))
        o.append("</tr>")
        cur += dt.timedelta(days=7)
    o.append("</table></div>")
    return "".join(o)


def _week_range(sunday: D) -> str:
    return "%s – %s" % (fmt.day_short(sunday),
                        fmt.day_short(sunday + dt.timedelta(days=6)))


def _cell(entry, day: D, full_depth_dates) -> str:
    if not entry:
        return '<span class="cell empty"></span>'
    obj = entry["versions"][0]["obj"]
    d = obj["display"]
    flags = []
    if len(entry["versions"]) > 1:
        flags.append('<span class="flag b">restated</span>')
    if obj["comp"]["override_in_effect"]:
        flags.append('<span class="flag">holiday</span>')
    if obj["completeness"]["missing"]:
        flags.append('<span class="flag r">incomplete</span>')
    if entry["date"] in full_depth_dates:
        flags.append('<span class="flag c">drill</span>')
    cls = "good" if (obj["headline"]["comp_pct"] or 0) >= 0 else "bad"
    return ('<a class="cell" href="day/%s"><span class="dnum">%d</span>'
            '<span class="amt">%s</span><span class="cmp %s">%s</span>%s</a>'
            % (esc(day_href(entry["date"])), day.day, esc(d["net_sales"]),
               cls, esc(d["comp_pct"]), "".join(flags)))

# =========================================================================
# The writer
# =========================================================================

def tag_depth(obj, full_dates, anchor: str) -> None:
    """Mark which drill pages exist for this object's day.

    The archive is tiered, so a summary day has no drill pages of its own. Its
    links point at the most recent full-depth day instead of 404-ing, and the
    page says so. A dead link is a worse answer than a redirected one."""
    is_full = obj["date"] in set(full_dates)
    obj["deep_links"] = is_full
    obj["deep_links_date"] = obj["date"] if is_full else anchor


def deep_date(obj) -> str:
    return obj.get("deep_links_date") or obj["date"]


def write(path: str, text: str) -> str:
    """One place that touches the filesystem, so the byte-level rules (utf-8,
    LF newlines) are stated once and cannot drift between page types."""
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    return path


def _csv_cell(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        s = "%.6f" % v
        s = s.rstrip("0").rstrip(".")
        return s or "0"
    s = str(v)
    if any(ch in s for ch in ',"\n'):
        return '"%s"' % s.replace('"', '""')
    return s


def render_extract_csv(obj) -> str:
    """BR-21: door × brand × the full KPI set. Byte-stable — rows are sorted by
    door and every float is written with one fixed precision, so two runs of
    the same day produce the same bytes."""
    ex = obj["extract"]
    lines = [",".join(ex["columns"])]
    for row in ex["rows"]:
        lines.append(",".join(_csv_cell(row[c]) for c in ex["columns"]))
    return "\n".join(lines) + "\n"


def build_site(out_dir: str, days: List[dict], storylines=None,
               today: Optional[str] = None, anchor: Optional[str] = None,
               sku_index=None) -> List[str]:
    """Render the whole site. Returns the written paths, sorted.

    `days` is the archive read back out of SQLite — the site renders what was
    sent (BR-7), not a fresh recompute. Days whose object carries
    `depth == 'full'` also get the drill-down tree."""
    written = [write(os.path.join(out_dir, "assets", "site.css"), CSS)]
    days = sorted(days, key=lambda e: e["date"])
    full_dates = [e["date"] for e in days
                  if e["versions"][0]["obj"].get("depth") == "full"]
    anchor = anchor or (days[-1]["date"] if days else "")
    trend_series = _trend_series(days)

    for i, entry in enumerate(days):
        date_iso = entry["date"]
        versions = entry["versions"]
        is_full = versions[0]["obj"].get("depth") == "full"
        vlinks = [{"version": v["obj"]["version"],
                   "href": day_href(date_iso, v["obj"]["version"])}
                  for v in versions]
        history = ("%s-history.html" % date_iso) if len(versions) > 1 else None
        prev_e = days[i - 1] if i > 0 else None
        next_e = days[i + 1] if i + 1 < len(days) else None

        for v in versions:
            obj = v["obj"]
            tag_depth(obj, full_dates, anchor)
            nav = {
                "stem_href": day_href(date_iso, obj["version"]),
                "versions": vlinks, "history": history,
                "email": "../email/%s.html" % date_iso,
                "extract": ("../extracts/%s-doors.csv" % date_iso) if is_full else None,
                "settled": entry.get("settled_href"),
                "deep": is_full,
                "prev_href": day_href(prev_e["date"]) if prev_e else None,
                "prev_label": (prev_e["versions"][0]["obj"]["display"]["date_short"]
                               if prev_e else None),
                "next_href": day_href(next_e["date"]) if next_e else None,
                "next_label": (next_e["versions"][0]["obj"]["display"]["date_short"]
                               if next_e else None),
            }
            written.append(write(
                os.path.join(out_dir, "day", day_href(date_iso, obj["version"])),
                render_day(obj, nav)))
        if history:
            written.append(write(os.path.join(out_dir, "day", history),
                                 render_history(versions)))
        if is_full:
            written += _build_deep(out_dir, versions[0]["obj"], trend_series)

    if sku_index:
        written += _build_skus(out_dir, sku_index)

    written.append(write(os.path.join(out_dir, "index.html"),
                         render_index(days, storylines=storylines, today=today,
                                      full_depth_dates=full_dates,
                                      anchor=anchor)))
    return sorted(written)


# =========================================================================
# The companion — the summary tier, for a host that caps at 1,000 files
# =========================================================================

def build_companion(out_dir: str, days: List[dict], base_url: str,
                    storylines=None, today: Optional[str] = None,
                    anchor: Optional[str] = None) -> List[str]:
    """Render the summary tier only, then point every link it cannot satisfy
    at the complete site.

    Two rules make this safe. First, it renders from the SAME archived objects
    the full site renders from, so a figure here is the same figure there
    (BR-13, BR-18, BR-21) — there is no second computation, only a smaller
    selection of pages. Second, nothing is left dangling: after writing, every
    relative link is resolved against what actually exists in this tree, and
    anything that does not is rewritten to an absolute URL on the complete
    site. A page that carries such a link says so."""
    written = [write(os.path.join(out_dir, "assets", "site.css"), CSS)]
    days = sorted(days, key=lambda e: e["date"])
    full_dates = [e["date"] for e in days
                  if e["versions"][0]["obj"].get("depth") == "full"]
    anchor = anchor or (days[-1]["date"] if days else "")
    trend_series = _trend_series(days)

    for i, entry in enumerate(days):
        date_iso = entry["date"]
        versions = entry["versions"]
        is_full = versions[0]["obj"].get("depth") == "full"
        vlinks = [{"version": v["obj"]["version"],
                   "href": day_href(date_iso, v["obj"]["version"])}
                  for v in versions]
        history = ("%s-history.html" % date_iso) if len(versions) > 1 else None
        prev_e = days[i - 1] if i > 0 else None
        next_e = days[i + 1] if i + 1 < len(days) else None

        for v in versions:
            obj = v["obj"]
            tag_depth(obj, full_dates, anchor)
            obj["companion"] = True
            obj["companion_base"] = base_url
            nav = {
                "stem_href": day_href(date_iso, obj["version"]),
                "versions": vlinks, "history": history,
                "email": "../email/%s.html" % date_iso,
                "extract": ("../extracts/%s-doors.csv" % date_iso) if is_full else None,
                "deep": is_full,
                "prev_href": day_href(prev_e["date"]) if prev_e else None,
                "prev_label": (prev_e["versions"][0]["obj"]["display"]["date_short"]
                               if prev_e else None),
                "next_href": day_href(next_e["date"]) if next_e else None,
                "next_label": (next_e["versions"][0]["obj"]["display"]["date_short"]
                               if next_e else None),
            }
            written.append(write(
                os.path.join(out_dir, "day", day_href(date_iso, obj["version"])),
                render_day(obj, nav)))
            written.append(write(
                os.path.join(out_dir, "email", "%s.html" % (
                    date_iso if obj["version"] == 1
                    else "%s-v%d" % (date_iso, obj["version"]))),
                _render_digest(obj)))
        if history:
            written.append(write(os.path.join(out_dir, "day", history),
                                 render_history(versions)))
        if is_full:
            written += _build_companion_panels(out_dir, versions[0]["obj"],
                                               trend_series)

    written.append(write(os.path.join(out_dir, "index.html"),
                         render_index(days, storylines=storylines, today=today,
                                      full_depth_dates=full_dates, anchor=anchor,
                                      companion_base=base_url)))
    externalized = _externalize(out_dir, base_url)
    return sorted(written), externalized


def _render_digest(obj):
    from flash import render_email
    return render_email.render(obj)


def _build_companion_panels(out_dir: str, obj, trend_series) -> List[str]:
    """Persona landings and the four panel families — no doors, no districts,
    no SKU pages. Those are the file-count tail, and they are exactly what the
    complete site is for."""
    date_iso = obj["date"]
    short = obj["display"]["date_short"]
    written = []
    for key, p in sorted(obj["personas"].items()):
        kind, pkey = key.split("/", 1)
        depth = 1 if kind in ("corporate", "field") else 2
        path = ("%s/%s.html" % (kind, date_iso) if depth == 1
                else "%s/%s/%s.html" % (kind, _persona_dir(kind, pkey), date_iso))
        nav = {"depth": depth,
               "crumbs": _crumb_base(date_iso, short) + [(p["label"], None)],
               "trend_series": trend_series}
        written.append(write(os.path.join(out_dir, path),
                             render_persona(obj, key, nav)))
    written.append(write(
        os.path.join(out_dir, "store-manager", "%s.html" % date_iso),
        render_store_entry(obj, {"depth": 1,
                                 "crumbs": _crumb_base(date_iso, short)
                                 + [("Store Manager", None)]})))
    for fam in obj["omni"]["family_order"]:
        nav = {"depth": 2, "crumbs": _crumb_base(date_iso, short)
               + [(OMNI_TITLES[fam], None)]}
        written.append(write(
            os.path.join(out_dir, "omni", fam, "%s.html" % date_iso),
            render_omni(obj, fam, nav)))
    nav = {"depth": 1, "crumbs": _crumb_base(date_iso, short) + [("Customer", None)]}
    written.append(write(os.path.join(out_dir, "customer", "%s.html" % date_iso),
                         render_customer(obj, nav)))
    nav = {"depth": 1, "crumbs": _crumb_base(date_iso, short) + [("Merchandise", None)]}
    written.append(write(os.path.join(out_dir, "merch", "%s.html" % date_iso),
                         render_merch(obj, nav)))
    if obj["merch"]["available"]:
        for c in obj["merch"]["categories"]["categories"]:
            nav = {"depth": 2, "crumbs": _crumb_base(date_iso, short)
                   + [("Merchandise", "merch/%s.html" % date_iso),
                      (c["category"], None)]}
            written.append(write(
                os.path.join(out_dir, "category", _slug(c["category"]),
                             "%s.html" % date_iso),
                render_category(obj, c["category"], nav)))
    for kpi in sorted(obj["ranks"]):
        nav = {"depth": 2, "crumbs": _crumb_base(date_iso, short)
               + [("Rank — %s" % RANK_LABELS[kpi], None)]}
        written.append(write(
            os.path.join(out_dir, "rank", kpi, "%s.html" % date_iso),
            render_rank(obj, kpi, nav)))
    written.append(write(
        os.path.join(out_dir, "extracts", "%s-doors.csv" % date_iso),
        render_extract_csv(obj)))
    return written


_HREF_RE = re.compile(r'((?:href|src)=")([^"]+)(")')


def _externalize(out_dir: str, base_url: str) -> int:
    """Rewrite every relative link the companion cannot satisfy into an
    absolute link on the complete site. Returns how many were rewritten.

    Deterministic: a sorted walk, a pure regex substitution, and a target set
    read off the tree that was just written."""
    base = base_url.rstrip("/") + "/"
    existing = set()
    for root, dirs, files in os.walk(out_dir):
        dirs.sort()
        for f in files:
            existing.add(os.path.relpath(os.path.join(root, f),
                                         out_dir).replace(os.sep, "/"))
    count = 0
    for root, dirs, files in sorted(os.walk(out_dir)):
        dirs.sort()
        for f in sorted(files):
            if not f.endswith(".html"):
                continue
            path = os.path.join(root, f)
            here = os.path.relpath(root, out_dir).replace(os.sep, "/")
            here = "" if here == "." else here
            with open(path, encoding="utf-8") as fh:
                text = fh.read()
            hits = [0]

            def fix(m):
                href = m.group(2)
                if href.startswith(("http://", "https://", "mailto:", "#",
                                    "data:")):
                    return m.group(0)
                bare = href.split("#")[0]
                target = posixpath.normpath(posixpath.join(here, bare))
                if target in existing:
                    return m.group(0)
                hits[0] += 1
                return m.group(1) + base + target + m.group(3)

            new = _HREF_RE.sub(fix, text)
            if hits[0]:
                count += hits[0]
                write(path, new)
    return count


def _trend_series(days) -> List[dict]:
    """The last 14 archived days as a compact series for the corporate trend
    lines. Read off the archived objects, never recomputed."""
    out = []
    for e in sorted(days, key=lambda x: x["date"])[-14:]:
        obj = e["versions"][0]["obj"]
        h = obj["headline"]
        out.append({"date": obj["date"], "net_sales": h["net_sales"],
                    "traffic": h["traffic"], "conversion": h["conversion"]})
    return out


def _crumb_base(date_iso, short):
    return [("Archive", "index.html"), (short, "day/%s.html" % date_iso)]


def _build_deep(out_dir: str, obj, trend_series) -> List[str]:
    """Every drill page for one full-depth day."""
    date_iso = obj["date"]
    short = obj["display"]["date_short"]
    obj["deep_links"] = True
    written = []

    # persona landings
    for key, p in sorted(obj["personas"].items()):
        kind, pkey = key.split("/", 1)
        depth = 1 if kind in ("corporate", "field") else 2
        path = ("%s/%s.html" % (kind, date_iso) if depth == 1
                else "%s/%s/%s.html" % (kind, _persona_dir(kind, pkey), date_iso))
        nav = {"depth": depth,
               "crumbs": _crumb_base(date_iso, short) + [(p["label"], None)],
               "trend_series": trend_series}
        written.append(write(os.path.join(out_dir, path),
                             render_persona(obj, key, nav)))

    # the Store Manager entry page — the sixth persona's door picker
    written.append(write(
        os.path.join(out_dir, "store-manager", "%s.html" % date_iso),
        render_store_entry(obj, {"depth": 1,
                                 "crumbs": _crumb_base(date_iso, short)
                                 + [("Store Manager", None)]})))

    # districts
    for row in obj["slices"]["district"]:
        nav = {"depth": 2, "crumbs": _crumb_base(date_iso, short)
               + [(row["region"], "region/%s/%s.html" % (_slug(row["region"]), date_iso)),
                  (row["label"], None)]}
        written.append(write(
            os.path.join(out_dir, "district", row["key"], "%s.html" % date_iso),
            render_district(obj, row["key"], nav)))

    # doors, hourly, trees
    for eid in sorted(obj["stores"]):
        b = obj["stores"][eid]
        base = _crumb_base(date_iso, short) + [
            (b["region"], "region/%s/%s.html" % (_slug(b["region"]), date_iso)),
            (b["district_id"] or "—",
             "district/%s/%s.html" % (b["district_id"], date_iso))]
        nav = {"depth": 2, "crumbs": base + [(b["name"], None)]}
        written.append(write(
            os.path.join(out_dir, "store", eid, "%s.html" % date_iso),
            render_store(obj, eid, nav)))
        if not b["posted"]:
            continue
        nav3 = {"depth": 3, "crumbs": base
                + [(b["name"], "store/%s/%s.html" % (eid, date_iso)),
                   ("Hourly", None)]}
        written.append(write(
            os.path.join(out_dir, "store", eid, "hourly", "%s.html" % date_iso),
            render_hourly(obj, eid, nav3)))
        nav3t = {"depth": 3, "crumbs": base
                 + [(b["name"], "store/%s/%s.html" % (eid, date_iso)),
                    ("KPI tree", None)]}
        written.append(write(
            os.path.join(out_dir, "store", eid, "tree", "%s.html" % date_iso),
            render_tree(obj, eid, nav3t)))

    # categories
    if obj["merch"]["available"]:
        for c in obj["merch"]["categories"]["categories"]:
            nav = {"depth": 2, "crumbs": _crumb_base(date_iso, short)
                   + [("Merchandise", "merch/%s.html" % date_iso),
                      (c["category"], None)]}
            written.append(write(
                os.path.join(out_dir, "category", _slug(c["category"]),
                             "%s.html" % date_iso),
                render_category(obj, c["category"], nav)))

    # omni panels
    for fam in obj["omni"]["family_order"]:
        nav = {"depth": 2, "crumbs": _crumb_base(date_iso, short)
               + [(OMNI_TITLES[fam], None)]}
        written.append(write(
            os.path.join(out_dir, "omni", fam, "%s.html" % date_iso),
            render_omni(obj, fam, nav)))

    # customer + merch panels
    nav = {"depth": 1, "crumbs": _crumb_base(date_iso, short) + [("Customer", None)]}
    written.append(write(os.path.join(out_dir, "customer", "%s.html" % date_iso),
                         render_customer(obj, nav)))
    nav = {"depth": 1, "crumbs": _crumb_base(date_iso, short) + [("Merchandise", None)]}
    written.append(write(os.path.join(out_dir, "merch", "%s.html" % date_iso),
                         render_merch(obj, nav)))

    # rank tables
    for kpi in sorted(obj["ranks"]):
        nav = {"depth": 2, "crumbs": _crumb_base(date_iso, short)
               + [("Rank — %s" % RANK_LABELS[kpi], None)]}
        written.append(write(
            os.path.join(out_dir, "rank", kpi, "%s.html" % date_iso),
            render_rank(obj, kpi, nav)))

    # extract
    written.append(write(
        os.path.join(out_dir, "extracts", "%s-doors.csv" % date_iso),
        render_extract_csv(obj)))
    return written


def _persona_dir(kind: str, key: str) -> str:
    return _slug(key) if kind == "region" else key


def _build_skus(out_dir: str, sku_index) -> List[str]:
    written = []
    for sku_id in sorted(sku_index):
        entry = sku_index[sku_id]
        nav = {"depth": 1,
               "crumbs": [("Archive", "index.html"),
                          ("Merchandise", "merch/%s.html" % entry["anchor"]),
                          (entry["sku"]["name"], None)]}
        written.append(write(os.path.join(out_dir, "sku", "%s.html" % sku_id),
                             render_sku(entry["sku"], entry["series"], nav)))
    return written


def build_sku_index(objs) -> Dict[str, object]:
    """Assemble the per-SKU daily series from the full-depth archive objects.

    Built from the archived objects rather than from a fresh query, so a SKU
    page cannot show a number the day pages never showed (BR-7)."""
    index: Dict[str, object] = {}
    anchor = objs[-1]["date"] if objs else ""
    for obj in objs:
        for cat, rows in sorted(obj["merch"].get("category_skus", {}).items()):
            for r in rows:
                e = index.setdefault(r["sku_id"], {
                    "sku": {"sku_id": r["sku_id"], "name": r["name"],
                            "category": r["category"], "brand_id": r["brand_id"],
                            "brand_name": r.get("brand_name", r["brand_id"]),
                            "launch_date": r["launch_date"],
                            "days_since_launch": r["days_since_launch"],
                            "unit_price": r.get("unit_price"),
                            "total_ty": 0.0, "total_ly": 0.0,
                            "total_units": 0},
                    "series": [], "anchor": anchor})
                e["sku"]["days_since_launch"] = max(
                    e["sku"]["days_since_launch"], r["days_since_launch"])
                e["sku"]["total_ty"] += r["ty"]
                e["sku"]["total_ly"] += r["ly"]
                e["sku"]["total_units"] += r["ty_units"]
                e["series"].append({
                    "date": obj["date"], "ty": r["ty"], "ly": r["ly"],
                    "delta": r["delta"], "pct": r["pct_vs_ly"],
                    "units": r["ty_units"]})
    for e in index.values():
        s = e["sku"]
        s["total_ty"] = round(s["total_ty"], 2)
        s["total_ly"] = round(s["total_ly"], 2)
        s["total_delta"] = round(s["total_ty"] - s["total_ly"], 2)
        s["total_pct"] = ((s["total_ty"] / s["total_ly"] - 1.0)
                          if s["total_ly"] else None)
        s["aur"] = (s["total_ty"] / s["total_units"]) if s["total_units"] else None
        e["series"].sort(key=lambda x: x["date"])
    return index
