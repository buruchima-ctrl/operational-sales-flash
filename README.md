# Lumière Ops Flash

**Live demo:** https://buruchima-ctrl.github.io/operational-sales-flash/
**Summary companion:** https://vast-marsh-4bgd.here.now/ — the summary tier on here.now; drill-down links open the complete site

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
python3 seed.py                  # build ops.db and assert every planted storyline
python3 run_flash.py --all       # compute 60 days, render both site targets
python3 app.py                   # serve it at http://127.0.0.1:8765/
python3 run_flash.py --companion # rebuild the summary companion only
```

Or check the whole thing in one command:

```bash
python3 run_flash.py --check # seed + storyline assertions + 252 tests + determinism
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
| `flash/style.py` | The stylesheet — one file, one home, no external asset. |

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
- **A conversion move carries its drivers** (BR-22). Traffic and transactions
  travel with every basis-point figure, so a symptom is never mistaken for a
  diagnosis.
- **A page never claims a property it does not have.** The complete site's
  digest says its links are relative, because they are. The companion's says
  which of its links leave, because some do. The tests pair each claim with a
  predicate that reads the file.
- **A sent flash is immutable.** A correction is a new version with a reason
  string; version 1 survives byte for byte at its own URL.
- **Regeneration is byte-identical.** No wall clock, no random module — every
  variation is a stable hash of (entity, date, tag). Two builds produce the same
  database and the same `render/` tree, bit for bit.

### Every persona opens on what it can act on

Each of the five persona landings — and the day flash, and the morning digest —
opens with two blocks: **Needs attention** and **Worth celebrating**, at most
three items each. An item names the entity, states the move, gives its driver,
and links to the page behind it.

The blocks are *scoped*, not filtered. Filtering a fleet list gave a Canada
page a headline reading "Makeup comps −6.2%" over a move reading +16.9%,
because the title came from the fleet and the figure came from Canada. Building
the exceptions in the persona's own scope makes that impossible — the title and
the figure are the same computation (BR-18).

**Ranking rule**, one for every item type and stated on the page:

> Items are ranked by the **absolute dollar impact** of the move they name,
> measured against the day-aligned LY, in the reporting currency, restricted to
> that view's own scope.

One rule for doors, categories, omni families and customer signals, so a Region
page and the Corporate page order the same pair the same way and neither has to
explain itself. A door that has not posted is scored on the money its own
trailing four same-weekday averages say is unaccounted for — the honest size of
"we do not know", rather than zero. A returns family inverts the sign, because
less merchandise coming back is a gain.

Scope answers *whose numbers these are*; a second filter answers *whose problem
it is*. Field Leadership sees doors and door-level omni execution only — a
district manager cannot re-buy Fragrance or fix e-commerce acquisition, so
neither belongs at the top of the one block they read. Corporate, Brand, Region
and Affiliate see every kind. The narrowing is stated on the page.

**A celebration is a threshold-clearing favourable move, never editorial.** It
comes from the same machinery, the same thresholds and the same catalog calls
as an exception; the only difference is the sign. Sources: favourable omni and
UPT exceptions, doors clearing the +5% band on comp, and doors beating a
day-grain plan by more than that band. An entity never appears in both blocks
on the same view, and the blocks are always both shown — a block that
disappears when it is empty teaches a reader to stop looking for it.

### A conversion move never travels without its drivers

**BR-22.** "Conversion −264 bp" cannot tell a district manager whether fewer
people came in or the same people bought less often — a demand problem and an
execution problem with the same symptom. So wherever a conversion movement is
stated outside a full KPI tile grid, it carries the drivers that produced it:

```
conversion −245 bp (traffic +9.9%, txns −5.7%)
```

Exception lines, coaching narratives, headline items, persona and omni panels,
window tables, slice tables, rank tables and the digest all carry it. Inside a
KPI tile grid the annotation is omitted, because traffic and transactions are
already their own tiles beside conversion.

It is emitted by one catalog function from one comparable set — the doors that
posted both sales and traffic on the day *and* on its aligned LY counterpart —
so the arithmetic is checkable: `(1 + txns%) ÷ (1 + traffic%)` equals the
conversion ratio, and the check is returned rather than assumed. Where traffic
is missing the annotation says *unavailable — no traffic posted*, naming the
door, rather than quietly dropping the comparison (BR-15).

### Exception thresholds

Every threshold lives once, in `catalog.THRESHOLDS`, so a renderer, a test and
an assertion cannot disagree about what "beyond threshold" means.

| Exception | Threshold | Measured against |
|---|---|---|
| Omni family movement | ±15% | the recognized basis vs the day-aligned LY |
| Category comp | 3 pts below the fleet | the same comp entity set as the headline |
| New-to-file share | 5 pts below baseline, WTD | the channel's own trailing 4-week WTD |
| Conversion | 150 bp below baseline, WTD | the door's own trailing 4-week WTD |
| **UPT** | **±5%, WTD** | **the door's own trailing 4-week WTD** |
| Favourable / unfavourable key | ±5% | the ±5% triangle on every ops table, and the band a headline celebration or attention item must clear |

UPT takes a percentage rather than a basis-point threshold because it is a
ratio of counts, not a percentage of visits — basis points would be a category
error. It is the only exception that fires in both directions: below baseline
is a coaching signal, above it is an attach-rate winner the field should be
copying rather than ignoring.

### UPT is a lever, not a by-product

A door grows two ways: by pulling more people through the door, or by selling
them more once they are inside. Conversion covers the first. Units per
transaction covers the second, and it gets the same treatment — a comparison
against last year wherever it appears (persona rows, store pages, windows,
slices, the digest, the door extract), a place in the selectable rank KPIs, its
own exception, and a planted storyline.

The rank page for UPT carries two tables on purpose. The first ranks the
**level**, and a door with a naturally big assortment will always sit near the
top of it and tell you nothing. The second ranks the **move** against the
day-aligned LY on the comp basis, which is the one a field leader can act on.

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

## Two render targets

| | files | what it carries |
|---|---:|---|
| `render/site/` | 2,059 | everything — 60 day flashes, digests, persona landings, districts, doors, hourly views, KPI trees, category and SKU pages, omni panels, rank tables, extracts |
| `render/companion/` | 601 | the summary tier only — day flashes, digests, the five persona landings, omni / customer / merchandise / category / rank panels, extracts, index |

The companion exists for a host that caps at a thousand files. It renders from
the **same archived objects** the complete site renders from, so there is no
second computation — only a smaller selection of pages. The extract CSVs are
byte-identical between the two trees, and any figure present on both is the
same figure.

Nothing in it dangles. After writing, every relative link is resolved against
what actually exists in the companion, and anything that does not is rewritten
to an absolute URL on the complete site. That is the **only** external link in
the entire product, and every page carrying one says so.

## The seeded storylines — where each one surfaces

Twenty-two planted storylines, every one asserted at seed time before the
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
| 22 | Attach-rate winner — the basket lever | `BR-20` | The mirror image of #9. Harborlight Galleria grew sales with traffic flat and conversion steady, by selling more units per transaction. | `store/LB-002/tree/2026-07-23.html` — the AST split; `rank/upt/2026-07-23.html` — the movers table |
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
seconds including 49 storyline assertions. Computing 60 days and rendering both
targets takes about ten. Every artefact is byte-identical on a rebuild.

```
python3 seed.py                                ~3s    49 assertions
python3 run_flash.py --all                    ~10s    2,660 files, 35 MB
python3 run_flash.py --companion               ~1s      601 files, 12 MB
python3 -m unittest discover -s tests -t .     ~13s    252 tests
```

---

Built with [Claude Code](https://claude.com/claude-code).
