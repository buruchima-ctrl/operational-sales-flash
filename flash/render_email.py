# -*- coding: utf-8 -*-
"""The morning digest — one self-contained HTML file per day (PRD §6, BR-13).

The site is the operational product; this is the pull that builds the habit.
So the digest is deliberately the summary layer only: the headline row, the
day's exceptions, and a deep link into the site for each one. Everything else
is a click away rather than a scroll away.

Constraints, and why each one is here:

  * **Inline CSS only.** Not "mostly inline with a <style> block for the hard
    parts" — Gmail's web client strips <style> from forwarded mail, and a flash
    that survives the first send but breaks on the forward to the regional
    director is worse than one that never worked. Every declaration is a style
    attribute.
  * **Table layout.** Outlook's Word rendering engine has no flexbox and no
    grid. Tables are not nostalgia; they are the only box model that renders
    the same in Outlook, Gmail and Apple Mail.
  * **Relative links.** The digest lives inside the site tree at
    `email/<date>.html`, so every deep link is `../day/…`, `../store/…` and so
    on. Those resolve identically from `file://`, from `app.py`, and from
    whatever slug the site is eventually published under — which is what BR-13
    needs, because a deep link that only works on one host is not a deep link.
  * **No external assets, no JS, no http(s) references at all.** Remote images
    are the tracking-pixel pattern corporate mail scanners strip, which would
    leave holes in the layout, and a digest must render with images off.
  * **Dark-mode safe.** Every cell declares its own background AND foreground,
    so a client that flips the page background cannot leave dark text on dark.
  * **375px, one column.** Nothing here can produce a horizontal scrollbar on
    a phone.

The renderer reads `obj["display"]` strings (BR-5). It never formats a number
itself, so the digest cannot round differently from the site or the extract.
"""

from __future__ import annotations

from html import escape as esc

# The site's tokens, restated as literals because an email cannot link a
# stylesheet. Same hues, same meanings — gold input, blue presentation, green
# calculated — so the digest and the site read as one product.
INK = "#18242F"
INK_2 = "#3D4C59"
INK_SOFT = "#6B7885"
FAINT = "#98A2AC"
PAPER = "#F6F4EF"
PANEL = "#FFFFFF"
PANEL_2 = "#FBFAF7"
RULE = "#D8D2C7"
HAIR = "#EAE6DD"
GOLD = "#8A6416"
BLUE = "#2C5F8A"
CALC = "#2A7355"
BAD = "#A33A2A"
GOOD = "#2A7355"

DISPLAY = ("'Avenir Next',Avenir,'Segoe UI',system-ui,'Helvetica Neue',"
           "Helvetica,Arial,sans-serif")
BODY = ("Charter,'Iowan Old Style','Palatino Linotype',Georgia,"
        "'Times New Roman',serif")
DATA = ("ui-monospace,'SF Mono',Menlo,Consolas,'DejaVu Sans Mono',"
        "'Courier New',monospace")

WRAP = ("margin:0;padding:0;width:100%%;background:%s;color:%s;"
        "-webkit-text-size-adjust:100%%;" % (PAPER, INK))
CARD = ("width:100%%;max-width:600px;background:%s;border:1px solid %s;"
        "border-collapse:collapse;" % (PANEL, RULE))
CELL = ("padding:18px 22px;font-family:%s;font-size:15.5px;line-height:1.6;"
        "color:%s;" % (BODY, INK))
EYEBROW = ("font-family:%s;font-size:11px;letter-spacing:0.13em;"
           "text-transform:uppercase;color:%s;font-weight:600;"
           % (DISPLAY, INK_SOFT))
NUM = ("font-family:%s;font-variant-numeric:tabular-nums lining-nums;color:%s;"
       % (DATA, INK))

UP = "../"          # the digest sits one level down, at email/<date>.html


def subject_line(obj) -> str:
    return obj["subject"]


def render(obj) -> str:
    d = obj["display"]
    out = []
    a = out.append

    a('<!doctype html>')
    a('<html lang="en"><head>')
    a('<meta charset="utf-8">')
    a('<meta name="viewport" content="width=device-width,initial-scale=1">')
    a('<meta name="color-scheme" content="light dark">')
    a('<meta name="supported-color-schemes" content="light dark">')
    a('<title>%s</title>' % esc(obj["subject"]))
    a("<!-- Subject: %s -->" % esc(obj["subject"]))
    a("<!-- Every token in the subject is a display string the body also "
      "prints (BR-5), so the subject cannot disagree with the digest it "
      "announces. Links are relative so they resolve wherever the site is "
      "hosted (BR-13). -->")
    a('</head>')
    a('<body style="%s">' % WRAP)
    a('<div style="display:none;max-height:0;overflow:hidden;opacity:0;">%s</div>'
      % esc(_preheader(obj)))
    a('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
      'border="0" style="background:%s;"><tr><td align="center" '
      'style="padding:12px;">' % PAPER)
    a('<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
      'style="%s">' % CARD)

    _masthead(a, obj, d)
    _headline(a, obj, d)
    _banners(a, obj, d)
    _narrative(a, obj)
    _headlines(a, obj, d)
    _exceptions(a, obj, d)
    _kpis(a, obj, d)
    _plan(a, obj, d)
    _windows(a, obj, d)
    _panels(a, obj, d)
    _focus(a, obj, d)
    _links(a, obj, d)
    _disclosures(a, obj)
    _method(a, obj)

    a('</table>')
    a('</td></tr></table>')
    a('</body></html>')
    return "\n".join(out) + "\n"


# -- sections ---------------------------------------------------------------

def _preheader(obj) -> str:
    d = obj["display"]
    n = len([e for e in obj["exceptions"]
             if e["severity"] in ("escalation", "adverse")])
    return "%s · comp %s · plan %s · %d exception%s · %s" % (
        d["net_sales"], d["comp_pct"], d["plan_attainment"], n,
        "" if n == 1 else "s", d["completeness"])


def _masthead(a, obj, d):
    a('<tr><td style="%spadding-bottom:14px;border-bottom:2px solid %s;">'
      % (CELL, INK))
    a('<div style="%s">%s <span style="color:%s;">·</span> %s</div>'
      % (EYEBROW, esc(obj["company"]), FAINT, esc(obj["product"])))
    a('<div style="font-family:%s;font-size:25px;font-weight:600;color:%s;'
      'padding-top:8px;line-height:1.12;letter-spacing:-0.015em;">%s</div>'
      % (DISPLAY, INK, esc(d["date_long"])))
    a('<div style="font-family:%s;font-size:11.5px;color:%s;padding-top:7px;'
      'line-height:1.5;">%s &nbsp;·&nbsp; fiscal %s &nbsp;·&nbsp; %s '
      '&nbsp;·&nbsp; for the morning of %s%s</div>'
      % (DATA, INK_SOFT, esc(d["week_label"]), esc(d["period_label"]),
         esc(d["quarter_label"]), esc(d["as_of"]),
         " &nbsp;·&nbsp; VERSION %d (restatement)" % obj["version"]
         if obj["version"] > 1 else ""))
    a('</td></tr>')


def _headline(a, obj, d):
    comp_colour = GOOD if (obj["headline"]["comp_pct"] or 0) >= 0 else BAD
    plan_colour = GOOD if (obj["headline"]["plan_attainment"] or 0) >= 1 else BAD
    tiles = [("Net sales", d["net_sales"], INK, d["net_sales_exact"]),
             ("Comp %s" % obj["comp"]["basis"], d["comp_pct"], comp_colour,
              "vs %s" % d["comp_ly_date"]),
             ("Plan (day grain)", d["plan_attainment"], plan_colour, d["plan_gap"])]
    a('<tr><td style="padding:0;">')
    a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
      'border="0"><tr>')
    for label, value, colour, sub in tiles:
        # 10px horizontal padding, not the card's 20px: three tiles side by
        # side cannot be narrower than their widest unbreakable token, and at
        # 20px a side the row exceeded a 375px phone. Email has no media
        # queries to stack it.
        a('<td width="33%%" align="left" valign="top" style="padding:18px 10px '
          '16px;border-bottom:1px solid %s;background:%s;">' % (RULE, PANEL_2))
        a('<div style="font-family:%s;font-size:10px;letter-spacing:0.11em;'
          'text-transform:uppercase;color:%s;font-weight:600;">%s</div>'
          % (DISPLAY, INK_SOFT, esc(label)))
        a('<div style="%sfont-size:25px;font-weight:600;color:%s;'
          'padding-top:5px;line-height:1.1;letter-spacing:-0.02em;">%s</div>'
          % (NUM, colour, esc(value)))
        a('<div style="font-family:%s;font-size:10.5px;color:%s;'
          'padding-top:4px;line-height:1.35;">%s</div>'
          % (DATA, INK_SOFT, esc(sub)))
        a('</td>')
    a('</tr></table></td></tr>')


def _banners(a, obj, d):
    c = obj["comp"]
    base = obj.get("companion_base")
    if base:
        _banner(a, BLUE, "#E9F0F7",
                "Summary companion — drill-down lives on the complete site",
                "This digest and the pages it links to are the summary tier. "
                "Door, district, hourly, KPI-tree and SKU links below open the "
                "complete site at %s. Both render from the same computed "
                "object, so the figures are identical (BR-13)." % base)
    if c["override_in_effect"]:
        _banner(a, GOLD, "#FBF4E4", "Holiday alignment in effect",
                "Leading comp %s is measured against %s — the same holiday last "
                "year. The raw week-aligned comparison (%s) reads %s. The "
                "adjusted figure leads; both are stated."
                % (d["comp_pct"], d["holiday_aligned_ly_date"],
                   d["week_aligned_ly_date"], d["week_aligned_pct"]))
    cm = obj["completeness"]
    if cm["missing"]:
        _banner(a, BAD, "#FBEDEA", "Incomplete — %s" % d["completeness"],
                "%s had not posted at generation time. Missing doors are "
                "excluded from totals and comp, never counted as zero. Posted "
                "sales are %s of the trailing-4 same-weekday average."
                % (", ".join(cm["missing_names"]), d["posted_pct"]))
    if cm["traffic_missing"]:
        _banner(a, BAD, "#FBEDEA", "Traffic not posted",
                "%s posted sales but no door traffic, so their conversion is "
                "unavailable rather than 0%%."
                % ", ".join(cm["traffic_missing_names"]))
    if obj["version"] > 1 and obj["reason"]:
        _banner(a, BLUE, "#EAF1F7", "Restatement — version %d" % obj["version"],
                obj["reason"])


def _banner(a, colour, bg, title, body):
    a('<tr><td style="padding:0 22px 12px;">')
    a('<table role="presentation" width="100%%" cellpadding="0" cellspacing="0" '
      'border="0" style="background:%s;border-left:3px solid %s;'
      'border-top:1px solid %s;border-right:1px solid %s;'
      'border-bottom:1px solid %s;"><tr>'
      '<td style="padding:12px 14px;">' % (bg, colour, HAIR, HAIR, HAIR))
    a('<div style="font-family:%s;font-size:10px;letter-spacing:0.11em;'
      'text-transform:uppercase;color:%s;font-weight:700;'
      'padding-bottom:4px;">%s</div>' % (DISPLAY, colour, esc(title)))
    a('<div style="font-family:%s;font-size:13px;line-height:1.55;color:%s;">'
      '%s</div>' % (BODY, INK_2, esc(body)))
    a('</td></tr></table></td></tr>')


def _narrative(a, obj):
    a('<tr><td style="%spadding-top:16px;padding-bottom:14px;">' % CELL)
    a('<div style="font-size:16px;line-height:1.65;color:%s;">%s</div>'
      % (INK, esc(obj["narrative"])))
    a('</td></tr>')


def _headlines(a, obj, d):
    """The corporate-scoped blocks, ahead of everything else. A digest that
    makes an operator scroll to find what needs doing has been written for the
    sender, not the reader."""
    h = obj["headlines"]
    for key, title, colour in (("attention", "Needs attention", BAD),
                               ("celebration", "Worth celebrating", CALC)):
        _section(a, title)
        a('<tr><td style="padding:0 22px 10px;">')
        if not h[key]:
            a('<div style="font-family:%s;font-size:13px;color:%s;">Nothing '
              'cleared a threshold today.</div>' % (BODY, INK_SOFT))
        for i, it in enumerate(h[key], 1):
            label = esc(it["headline"])
            if it["href"] and obj.get("deep_links"):
                label = ('<a href="%s%s" style="color:%s;'
                         'text-decoration:underline;">%s</a>'
                         % (UP, esc(it["href"]), BLUE, label))
            a('<div style="padding:9px 0 9px 10px;border-left:3px solid %s;'
              'border-bottom:1px solid %s;margin-bottom:6px;">' % (colour, HAIR))
            a('<div style="font-family:%s;font-size:14px;font-weight:600;'
              'line-height:1.4;color:%s;">%s</div>' % (DISPLAY, INK, label))
            a('<div style="font-family:%s;font-size:11.5px;color:%s;'
              'padding-top:3px;line-height:1.5;">%s</div>'
              % (DATA, INK_2, esc(it["move"])))
            a('<div style="font-family:%s;font-size:11px;color:%s;'
              'padding-top:2px;line-height:1.5;"><span style="color:%s;">why</span> '
              '%s</div>' % (DATA, INK_SOFT, CALC, esc(it["driver"] or "—")))
            a('</div>')
        a('<div style="font-family:%s;font-size:10.5px;color:%s;'
          'padding-top:2px;line-height:1.5;">%s</div>'
          % (DATA, FAINT, esc(h["ranking_rule"] if key == "attention"
                              else h["celebration_rule"])))
        a('</td></tr>')


def _exceptions(a, obj, d):
    _section(a, "Today's exceptions")
    items = d["exceptions"]
    a('<tr><td style="padding:0 22px 10px;">')
    if not items:
        a('<div style="font-family:%s;font-size:13px;color:%s;">Nothing cleared '
          'a threshold today.</div>' % (BODY, INK_SOFT))
    for e in items:
        colour = BAD if e["severity"] in ("escalation", "adverse") else GOOD
        title = esc(e["title"])
        if e["href"] and obj.get("deep_links"):
            title = ('<a href="%s%s" style="color:%s;text-decoration:underline;">'
                     '%s</a>' % (UP, esc(e["href"]), BLUE, title))
        a('<div style="padding:7px 0;border-bottom:1px solid %s;">' % RULE)
        a('<div style="font-family:%s;font-size:14px;line-height:1.4;color:%s;">'
          '<span style="color:%s;font-weight:700;">%s</span> %s'
          '<span style="font-family:%s;font-size:10px;color:%s;"> %s</span></div>'
          % (BODY, INK, colour, esc(e["mark"]), title, DATA, GOLD,
             esc(e["rule"] or "")))
        a('<div style="font-family:%s;font-size:12px;line-height:1.45;color:%s;'
          'padding-top:2px;">%s</div>' % (BODY, INK_SOFT, esc(e["detail"])))
        a('</div>')
    if items and obj.get("companion_base") and obj.get("deep_links"):
        a('<div style="font-family:%s;font-size:11px;color:%s;padding-top:8px;">'
          'Exception headlines link to the door and KPI-tree pages behind them. '
          'Those live on the complete site, so these links leave this '
          'companion.</div>' % (DATA, INK_SOFT))
    a('</td></tr>')


def _kpis(a, obj, d):
    """The ◆ digest metrics — the deck's KPI row, phone-shaped."""
    _section(a, "KPI row")
    rows = [
        ("Transactions", d["transactions"], d["txn_comp"]),
        ("AST — avg sale per transaction", d["ast"], d["ast_vs_ly"]),
        ("AUS — avg unit sale", d["aus"], d["aus_vs_ly"]),
        ("UPT — units per transaction", d["upt"], d["upt_vs_ly"]),
        ("Traffic", d["traffic"], d["traffic_pct"]),
        ("Conversion", d["conversion"], d["conversion_move"]),
        ("New customers", d["new_customers"], d["new_customer_pct"] + " of sales"),
        ("Returns", d["returns"], d["returns_vs_ly"]),
        ("Discounts", d["discounts"], d["discounts_pct_of_gross"] + " of gross"),
        ("OMNI penetration", d["omni_penetration"], d["omni_penetration_bps"]),
        ("Portfolio / trading", "%s / %s" % (d["portfolio"], d["trading"]),
         d["pct_comp_of_trading"] + " comp"),
    ]
    _table(a, ["", "Day", "vs LY"], rows, aligns=["left", "right", "right"])


def _plan(a, obj, d):
    ps = obj["plan_status"]
    _section(a, "Plan — each brand at its own grain")
    rows = [
        ("Day-planned (%d)" % ps["day_grain"]["entities"],
         d["plan_day_attainment"], "vs day plan"),
        ("Week-planned (%d)" % ps["week_grain"]["entities"],
         d["plan_week_attainment"], "WTD vs week plan"),
        ("No plan (%d)" % ps["no_plan"]["entities"],
         d["plan_no_plan_actual"], "actuals only"),
    ]
    _table(a, ["Grain", "Attainment", "Basis"], rows,
           aligns=["left", "right", "right"])
    a('<tr><td style="padding:0 22px 14px;">')
    a('<div style="font-family:%s;font-size:11px;color:%s;">%s of the day\'s '
      'sales sit inside a plan of any grain. A weekly plan is never spread '
      'across days (BR-19).</div>' % (DATA, INK_SOFT, esc(d["plan_coverage"])))
    a('</td></tr>')


def _windows(a, obj, d):
    _section(a, "Windows")
    rows = [(d["windows"][k]["label"], d["windows"][k]["net_sales"],
             d["windows"][k]["comp_pct"], d["windows"][k]["plan_attainment"])
            for k in ("LW", "WTD", "MTD", "QTD", "YTD")]
    _table(a, ["", "Net sales", "Comp", "Plan"], rows,
           aligns=["left", "right", "right", "right"])


def _panels(a, obj, d):
    _section(a, "Omni, customer, merchandise")
    rows = [("OMNI penetration", d["omni"]["penetration"],
             d["omni"]["penetration_bps"]),
            ("BOPIS recognized", d["omni"]["families"][0]["sales"],
             d["omni"]["families"][0]["vs_ly"]),
            ("BOPIS upsell", d["omni"]["upsell_sales"],
             d["omni"]["upsell_attach"] + " attach"),
            ("New to file", d["customer"]["pct_new_to_file"],
             d["customer"]["ntf_bps_vs_ly"]),
            ("Repeat rate", d["customer"]["repeat_rate"], "")]
    _table(a, ["", "Value", "vs LY"], rows,
           aligns=["left", "right", "right"])
    if d["merch"]["available"]:
        rows = [(c["category"], c["net_sales"], c["comp_pct"], c["mix_pct"])
                for c in d["merch"]["categories"]]
        _table(a, ["Category", "Net sales", "Comp", "Mix"], rows,
               aligns=["left", "right", "right", "right"])


def _focus(a, obj, d):
    f = d["focus"]
    _section(a, "Focus — what moved the comp")
    a('<tr><td style="padding:0 22px 8px;">')
    a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
      'border="0">')
    for e in f["entries"]:
        colour = BAD if e["adverse"] else GOOD
        a('<tr><td style="padding:7px 0;border-bottom:1px solid %s;">' % RULE)
        a('<div style="font-family:%s;font-size:14px;line-height:1.45;color:%s;">'
          '<span style="color:%s;font-weight:600;">%s</span> %s</div>'
          % (BODY, INK, colour, "▼" if e["adverse"] else "▲", esc(e["line"])))
        for r in e["receipts"]:
            a('<div style="font-family:%s;font-size:12px;color:%s;'
              'padding-left:14px;padding-top:2px;">%s</div>'
              % (DATA, INK_SOFT, esc(r)))
        a('</td></tr>')
    a('<tr><td style="padding:7px 0;border-bottom:1px solid %s;">' % RULE)
    a('<div style="font-family:%s;font-size:13px;color:%s;">%s %s</div>'
      % (BODY, INK_SOFT, esc(f["remainder_label"]), esc(f["remainder"])))
    a('</td></tr>')
    a('<tr><td style="padding:8px 0 0;">')
    a('<div style="font-family:%s;font-size:11px;color:%s;">Named contributions '
      '+ all other = %s, the headline comp gap, to the cent (BR-6).</div>'
      % (DATA, CALC, esc(f["headline_gap"])))
    a('</td></tr></table></td></tr>')


DEEP_LINKS = (
    ("Corporate landing", "corporate/%s.html"),
    ("Field Leadership — districts and doors", "field/%s.html"),
    ("Merchandise panel", "merch/%s.html"),
    ("Customer panel", "customer/%s.html"),
    ("Top and bottom doors", "rank/net_sales/%s.html"),
    ("Door extract (CSV)", "extracts/%s-doors.csv"),
)


def _links(a, obj, d):
    _section(a, "Open the site")
    a('<tr><td style="padding:0 22px 14px;">')
    target = obj.get("deep_links_date") or obj["date"]
    a('<div style="font-family:%s;font-size:13px;padding:4px 0;">'
      '<a href="%sday/%s.html" style="color:%s;text-decoration:underline;">'
      'The full day flash →</a></div>'
      % (BODY, UP, esc(obj["date"]), BLUE))
    for label, path in DEEP_LINKS:
        a('<div style="font-family:%s;font-size:13px;padding:4px 0;">'
          '<a href="%s%s" style="color:%s;text-decoration:underline;">%s →</a>'
          '</div>' % (BODY, UP, esc(path % target), BLUE, esc(label)))
    if not obj.get("deep_links"):
        a('<div style="font-family:%s;font-size:11px;color:%s;padding-top:6px;">'
          'The full drill-down is pre-rendered for the last 14 days; these '
          'links open %s, the most recent full-depth day.</div>'
          % (DATA, INK_SOFT, esc(target)))
    a('<div style="font-family:%s;font-size:11px;color:%s;padding-top:6px;">'
      '%s</div>' % (DATA, INK_SOFT, esc(_link_policy(obj))))
    a('</td></tr>')


def _link_policy(obj) -> str:
    """What is true of THIS digest's links — not what is true of the product.

    The complete site's digest is entirely relative, and said so. The
    companion's digest is not: its exception links reach door and KPI-tree
    pages that the companion does not carry, and those are rewritten to
    absolute URLs on the complete site. Repeating the all-relative sentence
    there printed a claim the file itself contradicts, which is the same
    failure as a number that does not reconcile — the page asserting a
    property it does not have."""
    base = obj.get("companion_base")
    if not base:
        return ("Every link is relative, so it resolves from a local file, "
                "from the demo server and from wherever this site is hosted. "
                "The numbers behind them are the same computed object this "
                "digest printed (BR-13).")
    return ("Links to this digest's own day flash and panels are relative and "
            "resolve inside this companion. Links into door, district, "
            "hourly, KPI-tree and SKU pages are absolute and open the complete "
            "site at %s — this companion does not carry them. The numbers "
            "behind every one of them are the same computed object this "
            "digest printed (BR-13)." % base)


def _disclosures(a, obj):
    _section(a, "Disclosures")
    a('<tr><td style="padding:0 22px 12px;">')
    for item in obj["disclosures"]:
        a('<div style="font-family:%s;font-size:12px;line-height:1.5;color:%s;'
          'padding-bottom:6px;"><span style="font-family:%s;color:%s;">%s</span> '
          '%s</div>' % (BODY, INK, DATA, GOLD, esc(item["rule"]), esc(item["text"])))
    a('</td></tr>')


def _method(a, obj):
    _section(a, "Formula key")
    a('<tr><td style="padding:0 22px 22px;">')
    for m in obj["method"]:
        a('<div style="font-family:%s;font-size:11px;line-height:1.5;color:%s;'
          'padding-bottom:4px;"><strong style="color:%s;">%s</strong> — %s</div>'
          % (DATA, INK_SOFT, INK, esc(m["metric"]), esc(m["formula"])))
    a('<div style="font-family:%s;font-size:11px;color:%s;padding-top:8px;'
      'border-top:1px solid %s;margin-top:8px;">Generated from seeded data for '
      'the morning of %s. No live systems were queried. Demo build.</div>'
      % (DATA, INK_SOFT, RULE, esc(obj["display"]["as_of"])))
    a('</td></tr>')


# -- primitives -------------------------------------------------------------

def _section(a, title):
    """A section head with a short ink rule above it — the same device the site
    uses, so the two surfaces are recognisably one product."""
    a('<tr><td style="padding:20px 22px 8px;">')
    a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
      'border="0"><tr><td style="height:2px;width:30px;background:'
      + INK + ';font-size:0;line-height:0;">&nbsp;</td></tr></table>')
    a('<div style="%spadding-top:10px;">%s</div>' % (EYEBROW, esc(title)))
    a('</td></tr>')


def _table(a, headers, rows, aligns):
    a('<tr><td style="padding:0 22px 14px;">')
    a('<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
      'border="0" style="border-collapse:collapse;">')
    a('<tr>')
    for h, al in zip(headers, aligns):
        a('<th align="%s" style="font-family:%s;font-size:9.5px;'
          'letter-spacing:0.09em;text-transform:uppercase;color:%s;'
          'font-weight:700;padding:0 0 6px;border-bottom:1.5px solid %s;">'
          '%s</th>' % (al, DISPLAY, INK_SOFT, INK_2, esc(h)))
    a('</tr>')
    for row in rows:
        a('<tr>')
        for i, (cell, al) in enumerate(zip(row, aligns)):
            font = BODY if i == 0 else DATA
            size = "13px" if i == 0 else "12px"
            colour = INK if i == 0 else INK_2
            if i > 0 and isinstance(cell, str) and cell.startswith("−"):
                colour = BAD
            a('<td align="%s" style="font-family:%s;font-size:%s;color:%s;'
              'font-variant-numeric:tabular-nums lining-nums;padding:7px 0;'
              'border-bottom:1px solid %s;">%s</td>'
              % (al, font, size, colour, HAIR, esc(str(cell))))
        a('</tr>')
    a('</table></td></tr>')
