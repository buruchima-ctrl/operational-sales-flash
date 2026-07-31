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

Python 3 standard library and SQLite. No dependencies, no network, no install.

> **Status: foundation complete.** Schema, deterministic seed, metric catalog
> and tests are in place and green. Compute, the persona site and the morning
> email digest are the next phase; this README grows with them.

---

## Quick start

```bash
python3 seed.py                       # builds ops.db and asserts every storyline
python3 -m unittest discover -s tests -t .
```

`seed.py` refuses to produce a database that the acceptance material is missing
from: it plants 21 storylines and asserts each one manifests, alongside the
reconciliation rules, before it reports success.

---

## What is built

```
seed.py ──▶ ops.db ──▶ flash/  (catalog · omni · customer · merch)
              ▲
         schema.sql
```

| Piece | What it holds |
|-------|---------------|
| `flash/calendar.py` | NRF 4-5-4 fiscal calendar with day-aligned last-year dates and a holiday override map. Ported **byte-identical** from the executive flash — it is proven, and fork-drift is the failure to refuse. |
| `flash/catalog.py` | The one home for every core formula: comps, plan at three grains, windows (WTD / LW / MTD / QTD / YTD), traffic and conversion, discounts and returns, store-status funnel, rankings, the hourly series, and the KPI decomposition tree. |
| `flash/omni.py` | The five omni families — BOPIS, Real-Time Delivery, Order Online From In Store, Buy Online Return In Store, Click & Reserve — each on both a recognized and an all-inclusive basis. |
| `flash/customer.py` | New-to-file, total buyers, repeat rate, and the New Customer block. |
| `flash/merch.py` | Category rollups, category basket metrics, and top/bottom SKU movers. |
| `seed.py` | The deterministic generator and every storyline assertion. |

## The rules the code enforces

The numbers are only worth reading because a handful of rules are enforced
rather than promised:

- **Comparisons are calendar-true.** Every comp joins to a materialized
  day-aligned last-year date on the same fiscal week and weekday, with a
  holiday override where the holiday moved.
- **Missing is never zero.** A door that has not posted is absent from the
  totals and named in the completeness line. A door with no traffic shows
  conversion as *unavailable*, never as 0%.
- **Omni attributes, never adds.** An omni order is a slice of money already
  in the headline — a pickup lives inside e-commerce demand, its upsell inside
  the store's own sales. Turning the omni layer on cannot move the headline,
  and the code computes that identity instead of claiming it.
- **Every level sums to its parent, to the cent.** Region → district → store →
  category → SKU, and hour by hour within a day. The seed *allocates* each
  posted day down to its parts rather than drawing them independently, so the
  identity is structural; the tests re-derive it anyway.
- **Currency is explicit.** Facts are stored in each door's local currency.
  Cross-market rollups convert once, at one seeded fixed rate, disclosed
  wherever a converted figure appears. Adding two currencies together raises.
- **Plan is measured at its own grain.** One brand plans daily, one weekly,
  one not at all. A weekly plan is never spread across days to fake a daily
  attainment, and a brand without a plan shows "no plan" — never 100%.
- **One formula, one home.** AST and AUS are the field's names for AOV and AUR
  and are emitted from the same computation, not recalculated. The KPI tree
  hands its driver values to the site's what-if calculator as data, so no
  formula is ever written twice.
- **Regeneration is byte-identical.** No wall clock, no random module — all
  variation is a stable hash of (entity, date, tag). Two builds produce the
  same database, bit for bit.

## Determinism

The demo is anchored to a fixed date rather than to today, so it reads the same
in a year as it does now. Seeding the whole model — roughly 2.5 fiscal years of
daily facts, plus SKU, hourly, omni and customer grain across a 14-week detail
window — takes about three seconds, assertions included.

---

Built with [Claude Code](https://claude.com/claude-code).
