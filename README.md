# Lumière Ops Flash

The **operational** daily sales flash for Lumière Beauty Group — a fictional
three-brand prestige beauty house trading 29 doors across two country markets
plus e-commerce.

This is the second product built on the same data spine as the executive
[Daily Sales Flash](https://github.com/buruchima-ctrl/daily-sales-flash). The
executive flash answers *how was yesterday, and why*, in twenty seconds. This
one answers the questions it deliberately refuses to carry: which SKUs drove
the miss, how omni is executing, whether the customer file is growing, what
each door's hourly shape says about staffing.

Python 3 standard library and SQLite. No dependencies, no network, no install,
no build step.

---

## Run it

```bash
python3 seed.py              # build ops.db and assert every planted storyline
python3 run_flash.py --all   # compute 60 days, render the site and the digests
python3 app.py               # serve it at http://127.0.0.1:8765/
```

Or check the whole thing in one command:

```bash
python3 run_flash.py --check # seed + storyline assertions + 188 tests + determinism
```

The demo clock is fixed: **today is 2026-07-24** and the latest complete day is
**2026-07-23**. Nothing anywhere calls `now()`, so this reads the same in a
year as it does today, and two builds produce byte-identical output.

### Where to start

| | |
|---|---|
| `/` | the archive — a fiscal-week grid over 60 days, plus the storyline index |
| `/corporate/2026-07-23.html` | Corporate landing: timeframe grid, donuts, brand rank, trends |
| `/field/2026-07-23.html` | Field Leadership: districts and doors, coaching-first |
| `/day/2026-07-23.html` | the day flash: headline, exceptions, focus, every panel |
| `/email/2026-07-23.html` | the morning digest as it lands on a phone |
| `/store/LB-015/tree/2026-07-23.html` | the KPI tree and the what-if calculator |
| `/extracts/2026-07-23-doors.csv` | door × brand × the full KPI set |
| `/today` | generated live from the database, not read from the archive |

---

## What it is

```
seed.py ──▶ ops.db ──▶ compute.py ──▶ render/site/
              ▲         (one object      ├─ day/ · corporate/ · brand/ · region/
         schema.sql      per day)        │  affiliate/ · field/ · district/ · store/
                                         │  category/ · sku/ · omni/ · customer/
                                         │  merch/ · rank/ · extracts/
                                         └─ email/   (the morning digest)
app.py serves it, and can generate today on demand
```

| Piece | What it holds |
|-------|---------------|
| `flash/calendar.py` | NRF 4-5-4 fiscal calendar with day-aligned last-year dates and a holiday override map. Ported **byte-identical** from the executive flash — it is proven, and fork-drift is the failure to refuse. |
| `flash/catalog.py` | The one home for every core formula: comps, plan at three grains, windows (LW / WTD / MTD / QTD / YTD), traffic and conversion, discounts and returns, the store-status funnel, rankings, hourly series, the KPI decomposition tree. |
| `flash/omni.py` | The five omni families — BOPIS, Real-Time Delivery, Order Online From In Store, Buy Online Return In Store, Click & Reserve — each on both a recognized and an all-inclusive basis. |
| `flash/customer.py` | New-to-file, total buyers, repeat rate, the New Customer block. |
| `flash/merch.py` | Category rollups, category basket metrics, top and bottom SKU movers. |
| `flash/compute.py` | The per-day object every surface reads, plus the per-day invariants. |
| `flash/focus.py` | The focus panel and the five exception families. |
| `flash/render_site.py` | Every page. `flash/render_email.py` is the digest. |

---

## The rules the code enforces

The numbers are only worth reading because a handful of rules are enforced
rather than promised. Each is checked on every generated day, and the tests
re-derive several of them a second way.

- **Comparisons are calendar-true.** Every comp joins to a materialized
  day-aligned last-year date on the same fiscal week and weekday, with a
  holiday override where the holiday moved. The adjusted figure leads and the
  raw one is still stated — including the same-calendar-date comparison the old
  spreadsheet would have printed.
- **Missing is never zero.** A door that has not posted is absent from the
  totals and named in the completeness line. A door with no traffic shows
  conversion as *unavailable*, and is listed separately on rank tables rather
  than sorted last as zero.
- **Omni attributes, never adds.** An omni order is a slice of money already in
  the headline — a pickup lives inside e-commerce demand, its upsell inside the
  store's own sales. The day flash prints the headline with the omni layer on
  and with it off, side by side. They are the same number by construction.
- **Every level sums to its parent, to the cent.** Region → district → door →
  category → SKU, and hour by hour within a day. The seed *allocates* each
  posted day down to its parts rather than drawing them independently, so the
  identity is structural. Displayed parts are reconciled too: a column a reader
  can add up always adds up.
- **Currency is explicit.** Facts are held in each door's local currency.
  Cross-market rollups convert once, at one seeded fixed rate, disclosed
  wherever a converted figure appears. Adding two currencies together raises.
- **Plan is measured at its own grain.** One brand plans daily, one weekly, one
  not at all. A weekly plan is never spread across days to fake a daily
  attainment, and a brand without a plan shows "no plan" — never 100%.
- **One formula, one home.** AST and AUS are the field's names for AOV and AUR
  and are emitted from the same computation. The site, the digest and the CSV
  extract read one object, so they cannot disagree.
- **A sent flash is immutable.** A correction is a new version with a reason
  string; version 1 survives byte for byte at its own URL.
- **Regeneration is byte-identical.** No wall clock, no random module — every
  variation is a stable hash of (entity, date, tag). Two builds produce the same
  database and the same `render/` tree, bit for bit.

### The what-if calculator

The KPI tree pages carry the site's **only** JavaScript. It holds no formula:
it is handed the catalog's own driver values as a JSON block, evaluates the
catalog's own identity (`sales = traffic × conversion × AST`), and verifies on
load that it reproduces the catalog's figure before it will let you touch a
slider. "Solve: what conversion matches LY?" is that same identity rearranged
for one variable — the question the original dashboard brief asked.

---

## Archive tiering

All **60 days** carry a flash page, a morning digest and their restatement
history. The last **14 days** additionally carry the full drill-down: persona
landings, districts, doors, hourly views, KPI trees, category and SKU pages,
omni panels, rank tables and the door extract.

All 60 days sit in the database at the same depth — only static page generation
is tiered. A summary day's links open the most recent full-depth day and the
page says so, rather than leading anywhere dead. Every storyline below is fully
clickable inside the full-depth window.

---

## The seeded storylines — where each one surfaces

Twenty-one planted storylines, every one asserted at seed time before the
database is allowed to exist. Paths are relative to the site root.

| # | Storyline | Rule | What was planted | Where to see it |
|---|-----------|------|------------------|-----------------|
| 1 | BOPIS upsell champion | `PRD §7.1` | Coral Bay Galleria attaches an upsell to roughly half its pickups, against a fleet rate near one in six. | `omni/BOPIS/2026-07-23.html` — upsell leaderboard, trailing 14 days |
| 2 | BOPIS execution gap — Southwest | `BR-10` | Southwest's pickup rate has run roughly 15 points below the fleet for two weeks; recognized and all-inclusive diverge visibly. | `omni/BOPIS/2026-07-23.html` — pickup execution by region |
| 3 | BORIS save story — Copper Row | `BR-14` | High return volume turned into measurable saved sales, with the shipping-label constant disclosed beside it. | `omni/BORIS/2026-07-23.html` — save leaderboard |
| 4 | Fragrance category slide | `BR-11` | Fragrance has comped negative for 14 consecutive days, driven by three identifiable SKUs. | `category/fragrance/2026-07-23.html` — the SKU table, bottom rows |
| 5 | SKU breakout — a new Skincare line | `PRD §5 #29` | A SKU launched fewer than 90 days ago sits in the top movers on most days of the window. | `sku/LUM-SKN-030.html` — the daily series |
| 6 | New-to-file dip — e-commerce | `BR-12` | New-buyer share fell more than five points below its own trailing baseline this week. | `customer/2026-07-23.html` — the CRM flag and the channel table |
| 7 | Omni invariance demo day | `BR-9` | A heavy-BOPIS day, printing the headline with omni on and with it off. | `day/2026-07-18.html` — the green omni-invariance band |
| 8 | Click & Reserve conversion win | `BR-10` | C&R conversion steps up sharply after a planted date and holds. | `omni/CR/2026-07-23.html` — completion rate on the created cohort |
| 9 | Traffic up, conversion down | `BR-15` | Riverbend Square has taken more traffic and converted less of it for two weeks. | `store/LB-015/2026-07-23.html` — the KPI row and the windows table |
| 10 | Lost midday peak | `BR-17` | Desert Bloom Galleria's midday hours collapsed against its own trailing hourly curve. | `store/LB-018/hourly/2026-07-21.html` — Δ share against its own baseline |
| 11 | Brand divergence inside one region | `BR-18` | In the West, Lumière comps positive while Atelier Noir comps negative on the same day. | `region/west/2026-07-23.html` — the brand rollup |
| 12 | Canada beats plan, smaller in USD | `BR-16` | The Canadian affiliate beats plan in CAD and contributes less in USD at the seeded fixed rate. | `affiliate/CA/2026-07-23.html` — the currency band and the KPI row |
| 13 | Three plan grains on one page | `BR-19` | The same trading day read three ways, none of them fabricated. | `day/2026-07-23.html` — "Plan, at each brand's own grain" |
| 14 | The tree explains the conversion story | `BR-20` | A positive traffic contribution overwhelmed by a negative conversion contribution, composing exactly to the gap. | `store/LB-015/tree/2026-07-23.html` — contributions and the calculator |
| 15 | Restatement — version 2 | `BR-7` | 2026-07-20 re-issued on the settled basis with a reason string. | `day/2026-07-20-history.html` — both versions and the reason |
| 16 | Holiday shift — July 4 | `BR-1` | Week-aligned, holiday-aligned and same-calendar-date comps all differ. | `day/2026-07-04.html` — the gold banner and the disclosures |
| 17 | Late posters, one escalating | `BR-3` | Santa Rosa Plaza missed two days running; Granite Hill Commons missed one. | `day/2026-07-23.html` — the red completeness banner |
| 18 | Remodel closure and a new door | `BR-2` | One door dark for remodel and out of comp on both sides; one too young to comp. | `day/2026-07-23.html` — disclosures, the two BR-2 lines |
| 19 | E-commerce maturation | `BR-4` | Demand read soft on the send morning and the shipped series settled positive. | `day/2026-07-20-history.html` — version 1 against version 2 |
| 20 | Soft Southeast region | `BR-6` | Two Southeast doors soft for two weeks; the focus panel names them and reconciles to the cent. | `day/2026-07-23.html` — the focus panel |
| 21 | A door with no traffic posted | `BR-15` | Bluegrass Commons posted sales but no traffic on two days. | `rank/conversion/2026-07-23.html` — the "not ranked" table |

This table is generated from the same list the site's archive index prints, so
the two cannot drift apart.

---

## Determinism and scale

Seeding the model — roughly 2.5 fiscal years of daily facts, plus SKU, hourly,
omni and customer grain across a 14-week detail window — takes about three
seconds including 45 storyline assertions. Computing 60 days and rendering
2,045 files takes about eight. Both are byte-identical on a rebuild.

```
python3 seed.py                                ~3s    45 assertions
python3 run_flash.py --all                     ~8s    2,045 files, 22 MB
python3 -m unittest discover -s tests -t .    ~12s    188 tests
```

---

Built with [Claude Code](https://claude.com/claude-code).
