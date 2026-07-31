# -*- coding: utf-8 -*-
"""Metric catalog — the ONE home for every formula (BR-5).

Forked from the executive flash's catalog and extended with the operational
metric set (PRD §5 #16–42). Metrics #16–24 and #35 live in `flash.omni`,
#25/#26/#34 in `flash.customer`, #27–#29 in `flash.merch`; every one of those
modules is a thin extension of THIS class's `DataAccess`, so there is still
exactly one home per formula. Renderers consume the objects these functions
produce and never re-derive a number — including the KPI tree's what-if
calculator, which is handed `kpi_tree()['payload']` as data (BR-20).

Two conventions this fork adds to the executive original:

1. **Currency (BR-16).** Facts are stored in each entity's local currency.
   Every rollup in this module returns REPORTING currency (default USD),
   converted once at the seeded fixed rate. `*_local` variants exist where a
   native-currency figure is wanted; nothing silently mixes the two.
2. **Scope keys.** Metric functions take `**scope` from a closed set
   (region / channel / entity_id / entity_ids / brand_id / district_id /
   affiliate_id / status). An unknown key raises rather than silently widening
   a rollup to the whole fleet.

Terminology (BRD §4.9): operator surfaces label AOV as **AST** (average sale
per transaction) and AUR as **AUS** (average unit sale). They are display
names for the identical formulas — `basket()` emits both from one computation.
"""

from __future__ import annotations

import datetime as dt
from typing import Dict, List, Optional

from flash.calendar import NRFCalendar, PERIODS_PER_YEAR

D = dt.date
COMP_PERIODS = 13          # BR-2: 13 full fiscal periods before comp entry
US_REGIONS = ("Northeast", "Southeast", "Midwest", "Southwest", "West")
REGIONS = US_REGIONS + ("Canada",)

# BR-4: an e-commerce day is "matured" (settled figures trustworthy) only after
# the fulfillment file has had this many days to close.
ECOM_SETTLE_LAG_DAYS = 3

WINDOWS = ("WTD", "MTD", "QTD", "YTD", "LW")     # #4–6 plus #41

SCOPE_KEYS = frozenset((
    "region", "channel", "entity_id", "entity_ids",
    "brand_id", "district_id", "affiliate_id", "status",
))

# Store trading hours (seed constant, restated here for the hourly metrics).
OPEN_HOUR, CLOSE_HOUR = 10, 20

# BR-14: BORIS shipping-label saving, a named constant, disclosed in the panel.
LABEL_SAVING_USD = 7.46

# Exception thresholds (PRD §10). One home, consumed by focus/exception code.
THRESHOLDS = {
    "omni_family_vs_ly": 0.15,        # ±15% vs LY
    "category_vs_fleet_pts": 0.03,    # category comp < fleet comp − 3pts
    "ntf_below_baseline_pts": 0.05,   # new-to-file < baseline − 5pts WTD
    "conversion_below_baseline_bp": 150,
    # UPT is a ratio of counts, not a percentage of visits, so a basis-point
    # threshold would be meaningless. It takes the omni family's shape instead:
    # a percentage move against the door's own trailing baseline, in either
    # direction — below it is a coaching signal, above it is an attach-rate
    # winner worth naming.
    "upt_vs_baseline_pct": 0.05,
    "fav_unfav_band": 0.05,           # ±5% fav / within / unfav key
}


class CatalogError(ValueError):
    pass


def reconcile_display(rows, key, total):
    """Make the DISPLAYED parts sum to the displayed whole.

    Eleven hours or five categories each rounded to cents can miss their own
    total by a penny — and after a currency conversion they usually do. The
    underlying allocation is exact; this pushes the display residual onto the
    largest row so a reader never sees a column that does not add up. BR-11 is
    about what the reader can check, not only what the database knows."""
    if not rows:
        return
    cents = [int(round(r[key] * 100)) for r in rows]
    residual = int(round(total * 100)) - sum(cents)
    if residual:
        biggest = max(range(len(rows)), key=lambda i: (cents[i], -i))
        cents[biggest] += residual
    for r, c in zip(rows, cents):
        r[key] = round(c / 100.0, 2)


class DataAccess(object):
    """Query surface over `ops.db` + the NRF calendar."""

    def __init__(self, conn, cal: Optional[NRFCalendar] = None,
                 ecom_basis: str = "demand", reporting_currency: str = "USD"):
        if ecom_basis not in ("demand", "settled"):
            raise CatalogError(
                "ecom_basis %r is not 'demand' or 'settled'. BR-4: the day-of "
                "flash reads demand (labeled); the settled view reads shipped. "
                "Mixing them silently is the rule this argument exists to stop."
                % (ecom_basis,))
        self.conn = conn
        self.cal = cal or NRFCalendar()
        self.ecom_basis = ecom_basis
        self.reporting_currency = reporting_currency
        self._entities = None
        self._brands = None
        self._districts = None
        self._products = None
        self._fx = None
        self._sales = None
        self._plan = None
        self._ly = None
        self._calrow = None
        self._traffic = None
        self._comp_set_cache = {}
        self._comp_elig_cache = {}
        # Read-through memos. Semantics are unchanged — every one of these is a
        # pure function of (day, scope) over an immutable database. They exist
        # because a 60-day archive walks YTD windows for every day, and the
        # same scope aggregate is otherwise recomputed thousands of times.
        self._entity_by_id = None
        self._scope_cache = {}
        self._agg_cache = {}

    @staticmethod
    def _skey(scope):
        """A hashable, order-independent key for a scope dict."""
        return tuple(sorted(
            (k, tuple(v) if isinstance(v, (list, tuple, set)) else v)
            for k, v in scope.items()))

    # =====================================================================
    # Dimensions
    # =====================================================================

    ENTITY_COLS = ("entity_id", "store_number", "name", "channel", "region",
                   "open_date", "close_date", "remodel_start", "remodel_end",
                   "rentable_sf", "target_sales_psf", "annual_volume",
                   "brand_id", "district_id", "affiliate_id", "currency",
                   "state_province", "city", "store_status")

    def entities(self) -> List[dict]:
        if self._entities is None:
            rows = self.conn.execute(
                "SELECT %s FROM stores ORDER BY entity_id"
                % ",".join(self.ENTITY_COLS)).fetchall()
            self._entities = [dict(zip(self.ENTITY_COLS, r)) for r in rows]
        return self._entities

    def entity(self, entity_id) -> dict:
        if self._entity_by_id is None:
            self._entity_by_id = {e["entity_id"]: e for e in self.entities()}
        return self._entity_by_id[entity_id]

    def brands(self) -> List[dict]:
        if self._brands is None:
            cols = ("brand_id", "name", "positioning", "categories", "plan_grain")
            rows = self.conn.execute(
                "SELECT %s FROM brand ORDER BY brand_id" % ",".join(cols))
            self._brands = [dict(zip(cols, r)) for r in rows]
            for b in self._brands:
                b["categories"] = tuple(b["categories"].split("|"))
        return self._brands

    def brand(self, brand_id) -> dict:
        for b in self.brands():
            if b["brand_id"] == brand_id:
                return b
        raise KeyError(brand_id)

    def districts(self) -> List[dict]:
        if self._districts is None:
            cols = ("district_id", "name", "region", "affiliate_id")
            self._districts = [dict(zip(cols, r)) for r in self.conn.execute(
                "SELECT %s FROM district ORDER BY district_id" % ",".join(cols))]
        return self._districts

    def products(self) -> List[dict]:
        if self._products is None:
            cols = ("sku_id", "name", "brand_id", "category", "launch_date",
                    "unit_price")
            self._products = [dict(zip(cols, r)) for r in self.conn.execute(
                "SELECT %s FROM product ORDER BY sku_id" % ",".join(cols))]
        return self._products

    def categories(self) -> List[str]:
        return sorted(set(p["category"] for p in self.products()))

    # =====================================================================
    # Currency (BR-16)
    # =====================================================================

    def fx(self) -> Dict[str, float]:
        """currency -> units of that currency per 1 USD. Fixed, seeded."""
        if self._fx is None:
            self._fx = dict(self.conn.execute(
                "SELECT currency, units_per_usd FROM fx_rate"))
        return self._fx

    def fx_disclosure(self, currency: str) -> str:
        row = self.conn.execute(
            "SELECT basis FROM fx_rate WHERE currency=?", (currency,)).fetchone()
        return row[0] if row else ""

    def convert(self, value: Optional[float], from_ccy: str,
                to_ccy: Optional[str] = None) -> Optional[float]:
        """Convert at the seeded fixed rate. Disclosed wherever it is used."""
        if value is None:
            return None
        to_ccy = to_ccy or self.reporting_currency
        rates = self.fx()
        for c in (from_ccy, to_ccy):
            if c not in rates:
                raise CatalogError(
                    "no seeded FX rate for %r (have %s). BR-16 forbids silently "
                    "mixing currencies; add the rate to fx_rate rather than "
                    "assuming parity." % (c, sorted(rates)))
        if from_ccy == to_ccy:
            return value
        return value / rates[from_ccy] * rates[to_ccy]

    # =====================================================================
    # Scope
    # =====================================================================

    def _check_scope(self, scope):
        bad = set(scope) - SCOPE_KEYS
        if bad:
            raise CatalogError(
                "unknown scope key(s) %s — the scope dimensions are %s. A "
                "mistyped scope key would silently widen a rollup to the whole "
                "fleet, which is the failure this check exists to stop."
                % (sorted(bad), sorted(SCOPE_KEYS)))

    def _scope_entities(self, **scope) -> List[dict]:
        self._check_scope(scope)
        key = self._skey(scope)
        hit = self._scope_cache.get(key)
        if hit is not None:
            return hit
        out = self._scope_entities_uncached(**scope)
        self._scope_cache[key] = out
        return out

    def _scope_entities_uncached(self, **scope) -> List[dict]:
        eids = scope.get("entity_ids")
        eids = set(eids) if eids else None
        out = []
        for e in self.entities():
            if scope.get("entity_id") and e["entity_id"] != scope["entity_id"]:
                continue
            if eids is not None and e["entity_id"] not in eids:
                continue
            if scope.get("region") and e["region"] != scope["region"]:
                continue
            if scope.get("channel") and e["channel"] != scope["channel"]:
                continue
            if scope.get("brand_id") and e["brand_id"] != scope["brand_id"]:
                continue
            if scope.get("district_id") and e["district_id"] != scope["district_id"]:
                continue
            if scope.get("affiliate_id") and e["affiliate_id"] != scope["affiliate_id"]:
                continue
            if scope.get("status") and e["store_status"] != scope["status"]:
                continue
            out.append(e)
        return out

    def scope_ids(self, **scope) -> List[str]:
        return [e["entity_id"] for e in self._scope_entities(**scope)]

    @staticmethod
    def _narrow(scope, **over):
        """Narrow a caller's scope with a metric's own fixed dimension (e.g.
        `channel='STORE'` for a store-only KPI) without a duplicate-kwarg
        crash. The metric's own dimension wins — it is part of the definition."""
        out = dict(scope)
        out.update(over)
        return out

    # =====================================================================
    # Open / remodel / comp eligibility (BR-2)
    # =====================================================================

    def _in_remodel(self, e, day: D) -> bool:
        if not e["remodel_start"]:
            return False
        rs = D.fromisoformat(e["remodel_start"])
        re_ = D.fromisoformat(e["remodel_end"]) if e["remodel_end"] else None
        return day >= rs and (re_ is None or day <= re_)

    def is_open_on(self, e, day: D) -> bool:
        if D.fromisoformat(e["open_date"]) > day:
            return False
        if e["close_date"] and day > D.fromisoformat(e["close_date"]):
            return False
        return not self._in_remodel(e, day)

    def in_portfolio(self, e, day: D) -> bool:
        """Portfolio (#36/#40) counts a door the company holds on the day —
        including one dark for remodel, which Trading excludes."""
        if D.fromisoformat(e["open_date"]) > day:
            return False
        if e["close_date"] and day > D.fromisoformat(e["close_date"]):
            return False
        return True

    def _step_period(self, fy, pno, delta):
        idx = (fy * PERIODS_PER_YEAR + (pno - 1)) + delta
        return idx // PERIODS_PER_YEAR, idx % PERIODS_PER_YEAR + 1

    def comp_eligible(self, entity_id, day: D) -> bool:
        """True if the entity is in the comp set on `day` (BR-2)."""
        key = (entity_id, day)
        if key in self._comp_elig_cache:
            return self._comp_elig_cache[key]
        out = self._comp_eligible_uncached(entity_id, day)
        self._comp_elig_cache[key] = out
        return out

    def _comp_eligible_uncached(self, entity_id, day: D) -> bool:
        e = self.entity(entity_id)
        if e["channel"] == "ECOM":
            return True
        if self._in_remodel(e, day):
            return False
        per = self.cal.period_for_date(day)
        tfy, tpno = self._step_period(per.fiscal_year, per.period_no, -COMP_PERIODS)
        threshold = self.cal.period(tfy, tpno).start
        return D.fromisoformat(e["open_date"]) <= threshold

    # =====================================================================
    # Raw fact access
    # =====================================================================

    SALES_COLS = ("net_sales", "transactions", "units", "demand_sales",
                  "shipped_sales", "returns_recorded", "gross_sales",
                  "discount_sales", "return_sales", "posted_at")

    def _sales_index(self):
        if self._sales is None:
            self._sales = {}
            sql = ("SELECT date, entity_id, %s FROM sales_day"
                   % ",".join(self.SALES_COLS))
            for row in self.conn.execute(sql):
                self._sales[(row[0], row[1])] = dict(
                    zip(self.SALES_COLS, row[2:]))
        return self._sales

    def sales_row(self, entity_id, day: D) -> Optional[dict]:
        return self._sales_index().get((day.isoformat(), entity_id))

    def _traffic_index(self):
        if self._traffic is None:
            self._traffic = {}
            for d, e, t in self.conn.execute(
                    "SELECT date, entity_id, traffic FROM traffic_day"):
                self._traffic[(d, e)] = t
        return self._traffic

    def traffic_of(self, entity_id, day: D) -> Optional[int]:
        """Store traffic, or None when the day never posted traffic.

        BR-15: None means UNAVAILABLE. It must never be coerced to 0, because
        0 traffic with >0 transactions is an infinite conversion rate and
        0 traffic with 0 transactions is a fabricated 0%."""
        return self._traffic_index().get((day.isoformat(), entity_id))

    def cal_row(self, day: D) -> dict:
        if self._calrow is None:
            cols = ("date", "fiscal_year", "period", "week", "day_of_week",
                    "holiday_code", "ly_aligned_date", "restated", "quarter",
                    "week_start", "week_end")
            self._calrow = {}
            for r in self.conn.execute("SELECT %s FROM calendar" % ",".join(cols)):
                self._calrow[r[0]] = dict(zip(cols, r))
        row = self._calrow.get(day.isoformat())
        if row is None:
            raise CatalogError(
                "no calendar row for %s — the seed materializes %s..%s; extend "
                "CAL_END in seed.py if a later date is needed"
                % (day, min(self._calrow), max(self._calrow)))
        return row

    def ly_date(self, day: D) -> D:
        """Materialized day-aligned LY counterpart (BR-1) — a join, not a
        computation."""
        return D.fromisoformat(self.cal_row(day)["ly_aligned_date"])

    def restated(self, day: D) -> bool:
        return bool(self.cal_row(day)["restated"])

    # -- money in local vs reporting currency ------------------------------

    def net_sales_local_of(self, entity_id, day: D) -> Optional[float]:
        """The entity's net sales in ITS OWN currency, or None if unposted."""
        row = self.sales_row(entity_id, day)
        if row is None:
            return None
        if (self.entity(entity_id)["channel"] == "ECOM"
                and self.ecom_basis == "settled"
                and row["shipped_sales"] is not None):
            return row["shipped_sales"]
        return row["net_sales"]

    def net_sales_of(self, entity_id, day: D) -> Optional[float]:
        """Net sales in REPORTING currency (BR-16). Every rollup uses this, so
        a CAD door can never be added to a USD door unconverted."""
        v = self.net_sales_local_of(entity_id, day)
        if v is None:
            return None
        return self.convert(v, self.entity(entity_id)["currency"])

    def _money_of(self, entity_id, day: D, col: str) -> Optional[float]:
        row = self.sales_row(entity_id, day)
        if row is None or row[col] is None:
            return None
        return self.convert(row[col], self.entity(entity_id)["currency"])

    def currencies_in_scope(self, **scope) -> List[str]:
        return sorted(set(e["currency"] for e in self._scope_entities(**scope)))

    def currency_note(self, **scope) -> Optional[str]:
        """The BR-16 disclosure string for a scope, or None if single-currency
        and already in the reporting currency."""
        ccys = self.currencies_in_scope(**scope)
        foreign = [c for c in ccys if c != self.reporting_currency]
        if not foreign:
            return None
        parts = ["%s converted at %s" % (c, self.fx_disclosure(c)) for c in foreign]
        return "Reported in %s. %s." % (self.reporting_currency, "; ".join(parts))

    # =====================================================================
    # Headline metrics (#1, #2, #7)
    # =====================================================================

    def net_sales(self, day: D, **scope) -> float:
        """#1 Net Sales (day) = Σ net_sales over REPORTED entities in scope,
        in reporting currency. ECOM contributes demand, labeled (BR-4)."""
        key = ("net", day, self._skey(scope))
        hit = self._agg_cache.get(key)
        if hit is not None:
            return hit
        out = self._net_sales_uncached(day, **scope)
        self._agg_cache[key] = out
        return out

    def _net_sales_uncached(self, day: D, **scope) -> float:
        total = 0.0
        for eid in self.scope_ids(**scope):
            v = self.net_sales_of(eid, day)
            if v is not None:
                total += v
        return round(total, 2)

    def net_sales_local(self, day: D, **scope) -> float:
        """Native-currency total. Only meaningful for a single-currency scope;
        raises otherwise rather than silently mixing (BR-16)."""
        ccys = self.currencies_in_scope(**scope)
        if len(ccys) > 1:
            raise CatalogError(
                "net_sales_local was asked for a scope spanning %s. Local "
                "currency totals only exist inside one currency; use "
                "net_sales() for the converted rollup (BR-16)." % (ccys,))
        total = 0.0
        for eid in self.scope_ids(**scope):
            v = self.net_sales_local_of(eid, day)
            if v is not None:
                total += v
        return round(total, 2)

    def comp_set(self, day: D, ly_override: Optional[D] = None, **scope) -> List[str]:
        """Comp entities on `day`: eligible, open both TY and LY sides, and
        reported on both sides (missing => excluded, disclosed, never zeroed)."""
        key = (day, ly_override, tuple(sorted(
            (k, tuple(v) if isinstance(v, (list, tuple, set)) else v)
            for k, v in scope.items())))
        if key in self._comp_set_cache:
            return self._comp_set_cache[key]
        ly = ly_override or self.ly_date(day)
        out = []
        for e in self._scope_entities(**scope):
            eid = e["entity_id"]
            if not self.comp_eligible(eid, day):
                continue
            if self._in_remodel(e, ly):
                continue
            if self.net_sales_of(eid, day) is None:
                continue
            if self.net_sales_of(eid, ly) is None:
                continue
            out.append(eid)
        out.sort()
        self._comp_set_cache[key] = out
        return out

    def comp_pair(self, day: D, ly_override: Optional[D] = None,
                  **scope) -> Dict[str, object]:
        """The two sides behind #2, so callers never re-sum them themselves."""
        key = ("comppair", day, ly_override, self._skey(scope))
        hit = self._agg_cache.get(key)
        if hit is not None:
            return hit
        out = self._comp_pair_uncached(day, ly_override, **scope)
        self._agg_cache[key] = out
        return out

    def _comp_pair_uncached(self, day: D, ly_override=None,
                            **scope) -> Dict[str, object]:
        ly_day = ly_override or self.ly_date(day)
        members = self.comp_set(day, ly_override, **scope)
        ty_raw = sum(self.net_sales_of(m, day) for m in members)
        ly_raw = sum(self.net_sales_of(m, ly_day) for m in members)
        # `*_raw` are the unrounded sums. Comp % and the per-entity
        # contributions are both computed from THESE, so Σ contributions
        # equals comp % exactly (BR-6) instead of to within a cent of rounding
        # error. Rounding is a display concern and happens on the way out.
        return {"ty": round(ty_raw, 2), "ly": round(ly_raw, 2),
                "gap": round(ty_raw - ly_raw, 2),
                "gap_raw": ty_raw - ly_raw,
                "ty_raw": ty_raw, "ly_raw": ly_raw,
                "members": members, "ly_date": ly_day.isoformat(),
                "restated": self.restated(day)}

    def comp_pct(self, day: D, ly_override: Optional[D] = None,
                 **scope) -> Optional[float]:
        """#2 Comp Sales % (day) = (Σ comp TY ÷ Σ comp LY-aligned) − 1."""
        pair = self.comp_pair(day, ly_override, **scope)
        if not pair["ly_raw"]:
            return None
        return pair["ty_raw"] / pair["ly_raw"] - 1.0

    def comp_transactions(self, day: D, ly_override: Optional[D] = None,
                          **scope) -> Dict[str, object]:
        """#7 Transactions (day, vs LY) — same comp basis as #2."""
        ly_day = ly_override or self.ly_date(day)
        members = self.comp_set(day, ly_override, **scope)
        ty = sum(self.sales_row(m, day)["transactions"] for m in members)
        lyv = sum(self.sales_row(m, ly_day)["transactions"] for m in members)
        return {"ty": ty, "ly": lyv, "pct": (ty / lyv - 1.0) if lyv else None}

    def contribution_to_comp_gap(self, day: D, ly_override: Optional[D] = None,
                                 **scope) -> List[dict]:
        """#15 Contribution to Comp Gap, per entity, within scope.

        entity contribution = (TY − LY-aligned) ÷ total LY-aligned. By
        construction Σ contributions = scope comp% (BR-6). Most adverse first."""
        ly = ly_override or self.ly_date(day)
        pair = self.comp_pair(day, ly_override, **scope)
        members = pair["members"]
        ly_total = pair["ly_raw"]
        out = []
        for m in members:
            e = self.entity(m)
            ty = self.net_sales_of(m, day)
            lyv = self.net_sales_of(m, ly)
            out.append({
                "entity_id": m, "name": e["name"], "region": e["region"],
                "channel": e["channel"], "brand_id": e["brand_id"],
                "district_id": e["district_id"], "affiliate_id": e["affiliate_id"],
                "ty": ty, "ly": lyv, "delta": ty - lyv,
                "contribution": ((ty - lyv) / ly_total) if ly_total else 0.0,
            })
        out.sort(key=lambda c: (c["contribution"], c["entity_id"]))
        return out

    # =====================================================================
    # Basket: #8 AOV/AST, #9 UPT, #10 AUR/AUS
    # =====================================================================

    def _sum_col(self, col, day, ids):
        total = 0
        for eid in ids:
            row = self.sales_row(eid, day)
            if row and row[col] is not None:
                total += row[col]
        return total

    def basket(self, day: D, **scope) -> Dict[str, object]:
        """#8/#9/#10 over reported entities in scope.

        `ast` and `aus` are the FIELD names for `aov` and `aur` (BRD §4.9) —
        the same computation emitted twice under two labels, never computed a
        second time. That is the whole point of naming them here."""
        key = ("basket", day, self._skey(scope))
        hit = self._agg_cache.get(key)
        if hit is not None:
            return hit
        out = self._basket_uncached(day, **scope)
        self._agg_cache[key] = out
        return out

    def _basket_uncached(self, day: D, **scope) -> Dict[str, object]:
        ids = self.scope_ids(**scope)
        net = self.net_sales(day, **scope)
        txns = self._sum_col("transactions", day, ids)
        units = self._sum_col("units", day, ids)
        aov = (net / txns) if txns else None
        aur = (net / units) if units else None
        return {
            "net_sales": net, "transactions": txns, "units": units,
            "aov": aov, "upt": (units / txns) if txns else None, "aur": aur,
            "ast": aov, "aus": aur,
            "alias_note": "AST is AOV and AUS is AUR — one formula, two labels "
                          "(BRD §4.9 field terminology).",
        }

    def comp_basket(self, day: D, ly_override: Optional[D] = None,
                    **scope) -> Dict[str, object]:
        """#8/#9/#10 against the day-aligned LY, on the COMP basis.

        The headline row showed AST, AUS and UPT with no comparison, which
        makes a lever look like a fact. Comparing them needs the comp entity
        set — the same one the sales comp uses — because a basket average over
        a different set of doors is a different average, not a movement."""
        ly_day = ly_override or self.ly_date(day)
        members = self.comp_set(day, ly_override, **scope)
        ty_net = ly_net = 0.0
        ty_txn = ly_txn = ty_un = ly_un = 0
        for m in members:
            ty_net += self.net_sales_of(m, day)
            ly_net += self.net_sales_of(m, ly_day)
            a_ = self.sales_row(m, day)
            b_ = self.sales_row(m, ly_day)
            ty_txn += a_["transactions"]
            ly_txn += b_["transactions"]
            ty_un += a_["units"]
            ly_un += b_["units"]

        def ratio(num, den):
            return (num / float(den)) if den else None

        def pct(a_, b_):
            return (a_ / b_ - 1.0) if (a_ is not None and b_) else None

        ty_ast, ly_ast = ratio(ty_net, ty_txn), ratio(ly_net, ly_txn)
        ty_aus, ly_aus = ratio(ty_net, ty_un), ratio(ly_net, ly_un)
        ty_upt, ly_upt = ratio(ty_un, ty_txn), ratio(ly_un, ly_txn)
        return {
            "members": len(members), "ly_date": ly_day.isoformat(),
            "ty_transactions": ty_txn, "ly_transactions": ly_txn,
            "ty_units": ty_un, "ly_units": ly_un,
            "ast": ty_ast, "ly_ast": ly_ast, "ast_pct": pct(ty_ast, ly_ast),
            "aus": ty_aus, "ly_aus": ly_aus, "aus_pct": pct(ty_aus, ly_aus),
            "upt": ty_upt, "ly_upt": ly_upt, "upt_pct": pct(ty_upt, ly_upt),
            "units_pct": pct(float(ty_un), float(ly_un)),
            "basis": "comp entity set, day-aligned LY",
        }

    def basket_window(self, day: D, window: str, **scope) -> Dict[str, object]:
        """AST / AUS / UPT over a fiscal window, aggregated as Σ ÷ Σ.

        Never an average of daily ratios: a mean of UPTs weights a quiet
        Tuesday the same as a Saturday and answers a question nobody asked."""
        ty_net = ly_net = 0.0
        ty_txn = ly_txn = ty_un = ly_un = 0
        for d in self.window_dates(day, window):
            ids = self.scope_ids(**scope)
            ty_net += self.net_sales(d, **scope)
            ty_txn += self._sum_col("transactions", d, ids)
            ty_un += self._sum_col("units", d, ids)
            ld = self.ly_date(d)
            ly_net += self.net_sales(ld, **scope)
            ly_txn += self._sum_col("transactions", ld, ids)
            ly_un += self._sum_col("units", ld, ids)

        def ratio(num, den):
            return (num / float(den)) if den else None

        ty_upt, ly_upt = ratio(ty_un, ty_txn), ratio(ly_un, ly_txn)
        return {
            "window": window, "end": day.isoformat(),
            "transactions": ty_txn, "units": ty_un,
            "ast": ratio(ty_net, ty_txn), "aus": ratio(ty_net, ty_un),
            "upt": ty_upt,
            "ly_transactions": ly_txn, "ly_units": ly_un,
            "ly_ast": ratio(ly_net, ly_txn), "ly_aus": ratio(ly_net, ly_un),
            "ly_upt": ly_upt,
            "upt_pct_vs_ly": ((ty_upt / ly_upt - 1.0)
                              if (ty_upt is not None and ly_upt) else None),
        }

    # =====================================================================
    # Plan at each brand's native grain (#3, D12, BR-19)
    # =====================================================================

    def plan_grain_of(self, entity_id) -> str:
        """'DAY' | 'WEEK' | 'NONE'. ECOM plans at DAY grain (see seed.gen_plan
        for why the whole channel rather than a brand slice)."""
        e = self.entity(entity_id)
        if e["channel"] == "ECOM":
            return "DAY"
        return self.brand(e["brand_id"])["plan_grain"]

    def _plan_index(self):
        if self._plan is None:
            self._plan = {"DAY": {}, "WEEK": {}}
            for eid, grain, ps, plan in self.conn.execute(
                    "SELECT entity_id, grain, period_start, plan_sales FROM plan_day"):
                self._plan[grain].setdefault(ps, {})[eid] = plan
        return self._plan

    def plan_of(self, entity_id, day: D) -> Optional[float]:
        """DAY-grain plan for a date, reporting currency. None if the entity
        does not plan at day grain — never 0, never fabricated (BR-19)."""
        if self.plan_grain_of(entity_id) != "DAY":
            return None
        v = self._plan_index()["DAY"].get(day.isoformat(), {}).get(entity_id)
        if v is None:
            return None
        return self.convert(v, self.entity(entity_id)["currency"])

    def week_plan_of(self, entity_id, day: D) -> Optional[float]:
        if self.plan_grain_of(entity_id) != "WEEK":
            return None
        ws = self.cal_row(day)["week_start"]
        v = self._plan_index()["WEEK"].get(ws, {}).get(entity_id)
        if v is None:
            return None
        return self.convert(v, self.entity(entity_id)["currency"])

    def plan_pair(self, day: D, **scope) -> Dict[str, float]:
        """Reported actual and its matching DAY-grain plan — the two sides
        behind #3. Only DAY-grain entities take part; the others are reported
        by plan_status()."""
        key = ("planpair", day, self._skey(scope))
        hit = self._agg_cache.get(key)
        if hit is not None:
            return hit
        out = self._plan_pair_uncached(day, **scope)
        self._agg_cache[key] = out
        return out

    def _plan_pair_uncached(self, day: D, **scope) -> Dict[str, float]:
        actual = plan = 0.0
        for eid in self.scope_ids(**scope):
            if self.plan_grain_of(eid) != "DAY":
                continue
            v = self.net_sales_of(eid, day)
            if v is None:
                continue
            actual += v
            plan += self.plan_of(eid, day) or 0.0
        return {"actual": round(actual, 2), "plan": round(plan, 2)}

    def plan_attainment(self, day: D, **scope) -> Optional[float]:
        """#3 Plan Attainment % (day) at DAY grain = reported actual ÷ plan.
        A missing store is not a plan miss — it is disclosed in completeness."""
        pair = self.plan_pair(day, **scope)
        if pair["plan"] == 0:
            return None
        return pair["actual"] / pair["plan"]

    def plan_status(self, day: D, **scope) -> Dict[str, object]:
        """BR-19 in one object: attainment at every grain present in the scope,
        each labeled, plus what share of the scope's actuals is planned at all.

        A week-planned brand shows WTD actual against the FULL week plan and
        says so — the weekly number is never spread across days, because the
        plan does not exist at day grain and inventing one is the lie BR-19
        exists to prevent. A no-plan brand shows actual only."""
        ws = D.fromisoformat(self.cal_row(day)["week_start"])
        week_days = [ws + dt.timedelta(days=i) for i in range((day - ws).days + 1)]
        day_a = day_p = wk_a = wk_p = wk_day_a = np_a = 0.0
        n = {"DAY": 0, "WEEK": 0, "NONE": 0}
        for eid in self.scope_ids(**scope):
            grain = self.plan_grain_of(eid)
            v = self.net_sales_of(eid, day)
            if v is None:
                continue
            n[grain] += 1
            if grain == "DAY":
                day_a += v
                day_p += self.plan_of(eid, day) or 0.0
            elif grain == "WEEK":
                wk_day_a += v
                wk_p += self.week_plan_of(eid, day) or 0.0
                for d in week_days:
                    dv = self.net_sales_of(eid, d)
                    if dv is not None:
                        wk_a += dv
            else:
                np_a += v
        total_actual = round(day_a + wk_day_a + np_a, 2)
        grains = [g for g in ("DAY", "WEEK", "NONE") if n[g]]
        return {
            "day_grain": {
                "entities": n["DAY"], "actual": round(day_a, 2),
                "plan": round(day_p, 2),
                "attainment": (day_a / day_p) if day_p else None,
                "label": "vs day plan",
            },
            "week_grain": {
                "entities": n["WEEK"], "wtd_actual": round(wk_a, 2),
                "week_plan": round(wk_p, 2),
                "attainment": (wk_a / wk_p) if wk_p else None,
                "elapsed_days": len(week_days), "week_days": 7,
                "week_start": ws.isoformat(),
                "label": "WTD vs full week plan (%d of 7 days elapsed)"
                         % len(week_days),
            },
            "no_plan": {
                "entities": n["NONE"], "actual": round(np_a, 2),
                "attainment": None, "label": "no plan",
            },
            "grain_mix": grains,
            "actual_total": total_actual,
            "planned_share_of_actual": (
                round((day_a + wk_day_a) / total_actual, 4)
                if total_actual else None),
            "disclosure": self._plan_disclosure(grains),
        }

    @staticmethod
    def _plan_disclosure(grains) -> str:
        parts = {"DAY": "day-planned brands measured against the day plan",
                 "WEEK": "week-planned brands measured week-to-date against "
                         "the weekly plan (not spread to days)",
                 "NONE": "brands without a plan show actuals only"}
        return "Plan grain mix: " + "; ".join(parts[g] for g in grains) + "."

    # =====================================================================
    # Windows: #4/#5/#6 (WTD/MTD/YTD) + #41 (LW/QTD)
    # =====================================================================

    def window_range(self, day: D, window: str):
        if window not in WINDOWS:
            raise CatalogError(
                "window %r is not one of %s — those are the fiscal windows the "
                "ops flash reports (rolling and custom ranges are out of scope)."
                % (window, WINDOWS))
        row = self.cal_row(day)
        fy = row["fiscal_year"]
        if window == "WTD":
            return D.fromisoformat(row["week_start"]), day
        if window == "LW":
            ws = D.fromisoformat(row["week_start"])
            prev = ws - dt.timedelta(days=7)
            return prev, prev + dt.timedelta(days=6)
        if window == "MTD":
            return self.cal.period_for_date(day).start, day
        if window == "QTD":
            q = row["quarter"]
            return (self.cal.fy_start_date(fy)
                    + dt.timedelta(days=(q - 1) * 13 * 7), day)
        return self.cal.fy_start_date(fy), day

    def window_start(self, day: D, window: str) -> D:
        return self.window_range(day, window)[0]

    def window_dates(self, day: D, window: str) -> List[D]:
        start, end = self.window_range(day, window)
        return [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]

    def window_metrics(self, day: D, window: str, **scope) -> Dict[str, object]:
        """#4 net sales, #5 comp %, #6 plan attainment over a fiscal window.

        Built day by day from each day's own aligned LY date and each day's own
        comp set: summing a window total and shifting it would silently mix
        weekdays across the year boundary."""
        net = plan = actual = comp_ty = comp_ly = 0.0
        txns = units = 0
        days = self.window_dates(day, window)
        for d in days:
            net += self.net_sales(d, **scope)
            pp = self.plan_pair(d, **scope)
            actual += pp["actual"]
            plan += pp["plan"]
            cp = self.comp_pair(d, **scope)
            comp_ty += cp["ty"]
            comp_ly += cp["ly"]
            ids = self.scope_ids(**scope)
            txns += self._sum_col("transactions", d, ids)
            units += self._sum_col("units", d, ids)
        return {
            "window": window, "start": days[0].isoformat(),
            "end": days[-1].isoformat(), "days": len(days),
            "net_sales": round(net, 2), "transactions": txns, "units": units,
            "comp_ty": round(comp_ty, 2), "comp_ly": round(comp_ly, 2),
            "comp_gap": round(comp_ty - comp_ly, 2),
            "comp_pct": (comp_ty / comp_ly - 1.0) if comp_ly else None,
            "plan": round(plan, 2),
            "plan_attainment": (actual / plan) if plan else None,
            "plan_grain_note": "day-grain plan only; see plan_status() for the "
                               "week-planned and no-plan brands (BR-19)",
        }

    # =====================================================================
    # Traffic & conversion (#30, #31 — BR-15)
    # =====================================================================

    def _traffic_scope_ids(self, **scope) -> List[str]:
        return [e["entity_id"] for e in self._scope_entities(**scope)
                if e["channel"] == "STORE"]

    def traffic(self, day: D, **scope) -> Dict[str, object]:
        """#30 Traffic (day, vs LY). Stores only — FSS-labeled. Doors with no
        traffic posted are NAMED, not zero-filled (BR-15)."""
        ly = self.ly_date(day)
        ids = self._traffic_scope_ids(**scope)
        have, missing, comparable = [], [], []
        for eid in ids:
            if self.sales_row(eid, day) is None:
                continue
            t = self.traffic_of(eid, day)
            if t is None:
                missing.append(eid)
                continue
            have.append(eid)
            if self.traffic_of(eid, ly) is not None:
                comparable.append(eid)
        ty = sum(self.traffic_of(e, day) for e in have) if have else None
        ty_c = sum(self.traffic_of(e, day) for e in comparable) or None
        ly_c = sum(self.traffic_of(e, ly) for e in comparable) or None
        return {
            "traffic": ty, "stores_with_traffic": len(have),
            "stores_missing_traffic": sorted(missing),
            "missing_names": [self.entity(m)["name"] for m in sorted(missing)],
            "comparable_stores": len(comparable),
            "ty_comparable": ty_c, "ly_comparable": ly_c,
            "pct_vs_ly": (ty_c / ly_c - 1.0) if (ty_c and ly_c) else None,
            "ly_date": ly.isoformat(),
            "basis": "FSS (stores) only — e-commerce has no door traffic.",
        }

    def conversion(self, day: D, **scope) -> Dict[str, object]:
        """#31 Conversion = transactions ÷ traffic, as a % of visits, with the
        LY move in basis points (deck convention).

        Where traffic is missing the answer is `None` = UNAVAILABLE. It is
        never 0%: the flash says "no traffic posted" and names the door."""
        key = ("conv", day, self._skey(scope))
        hit = self._agg_cache.get(key)
        if hit is not None:
            return hit
        out = self._conversion_uncached(day, **scope)
        self._agg_cache[key] = out
        return out

    def _conversion_uncached(self, day: D, **scope) -> Dict[str, object]:
        ly = self.ly_date(day)
        ids = self._traffic_scope_ids(**scope)
        ty_t = ty_x = 0
        ly_t = ly_x = 0
        have, missing, comparable = [], [], []
        for eid in ids:
            row = self.sales_row(eid, day)
            if row is None:
                continue
            t = self.traffic_of(eid, day)
            if t is None:
                missing.append(eid)
                continue
            have.append(eid)
            ty_t += t
            ty_x += row["transactions"]
            ly_row = self.sales_row(eid, ly)
            lt = self.traffic_of(eid, ly)
            if ly_row is not None and lt:
                comparable.append(eid)
                ly_t += lt
                ly_x += ly_row["transactions"]
        ty_conv = (ty_x / ty_t) if ty_t else None
        ly_conv = (ly_x / ly_t) if ly_t else None
        return {
            "conversion": ty_conv,
            "available": ty_conv is not None,
            "transactions": ty_x, "traffic": ty_t,
            "ly_conversion": ly_conv,
            "bps_vs_ly": (round((ty_conv - ly_conv) * 10000.0, 1)
                          if (ty_conv is not None and ly_conv is not None) else None),
            "stores_with_traffic": len(have),
            "stores_missing_traffic": sorted(missing),
            "missing_names": [self.entity(m)["name"] for m in sorted(missing)],
            "comparable_stores": len(comparable),
            "ly_date": ly.isoformat(),
            "unavailable_note": (
                "conversion unavailable — no traffic posted (BR-15: missing "
                "traffic is never shown as 0%)" if ty_conv is None else None),
        }

    def conversion_window(self, day: D, window: str, **scope) -> Dict[str, object]:
        """Conversion over a fiscal window, aggregated (Σ transactions ÷ Σ
        traffic), never an average of daily rates."""
        ty_t = ty_x = ly_t = ly_x = 0
        for d in self.window_dates(day, window):
            c = self.conversion(d, **scope)
            ty_t += c["traffic"]
            ty_x += c["transactions"]
            ld = self.ly_date(d)
            lc = self.conversion(ld, **scope)
            ly_t += lc["traffic"]
            ly_x += lc["transactions"]
        ty = (ty_x / ty_t) if ty_t else None
        lyv = (ly_x / ly_t) if ly_t else None
        return {"window": window, "conversion": ty, "ly_conversion": lyv,
                "traffic": ty_t, "transactions": ty_x,
                "ly_traffic": ly_t, "ly_transactions": ly_x,
                "bps_vs_ly": (round((ty - lyv) * 10000.0, 1)
                              if (ty is not None and lyv is not None) else None)}

    # =====================================================================
    # Gross / discounts / returns (#32, #33, #42)
    # =====================================================================

    def gross_pack(self, day: D, **scope) -> Dict[str, object]:
        """One pass over gross, discounts and returns, in reporting currency.

        The identity net = gross − discounts − returns is seeded to hold to the
        cent per row and is re-asserted here for the scope, so a rollup can
        never present three numbers that do not add up."""
        key = ("gross", day, self._skey(scope))
        hit = self._agg_cache.get(key)
        if hit is not None:
            return hit
        out = self._gross_pack_uncached(day, **scope)
        self._agg_cache[key] = out
        return out

    def _gross_pack_uncached(self, day: D, **scope) -> Dict[str, object]:
        gross = disc = ret = net = 0.0
        for eid in self.scope_ids(**scope):
            row = self.sales_row(eid, day)
            if row is None:
                continue
            ccy = self.entity(eid)["currency"]
            gross += self.convert(row["gross_sales"], ccy)
            disc += self.convert(row["discount_sales"], ccy)
            ret += self.convert(row["return_sales"], ccy)
            net += self.convert(row["net_sales"], ccy)
        return {"gross": round(gross, 2), "discounts": round(disc, 2),
                "returns": round(ret, 2), "net": round(net, 2),
                "identity_gap": round(gross - disc - ret - net, 2)}

    def discounts(self, day: D, **scope) -> Dict[str, object]:
        """#32 Discounts $ and % of gross, with the LY-aligned comparison."""
        ly = self.ly_date(day)
        ty = self.gross_pack(day, **scope)
        lyp = self.gross_pack(ly, **scope)
        return {
            "discounts": ty["discounts"], "gross": ty["gross"],
            "pct_of_gross": (ty["discounts"] / ty["gross"]) if ty["gross"] else None,
            "ly_discounts": lyp["discounts"], "ly_gross": lyp["gross"],
            "ly_pct_of_gross": (lyp["discounts"] / lyp["gross"]) if lyp["gross"] else None,
            "pct_vs_ly": (ty["discounts"] / lyp["discounts"] - 1.0)
                         if lyp["discounts"] else None,
            "ly_date": ly.isoformat(),
        }

    def store_returns(self, day: D, **scope) -> Dict[str, object]:
        """#33 Returns $ and % to LY. Store-side returns of store purchases —
        distinct from ECOM settled returns (#12) and from BORIS (#22)."""
        ly = self.ly_date(day)
        sub = self._narrow(scope, channel="STORE")
        ty = self.gross_pack(day, **sub)
        lyp = self.gross_pack(ly, **sub)
        return {
            "returns": ty["returns"], "gross": ty["gross"],
            "pct_of_gross": (ty["returns"] / ty["gross"]) if ty["gross"] else None,
            "ly_returns": lyp["returns"],
            "pct_vs_ly": (ty["returns"] / lyp["returns"] - 1.0)
                         if lyp["returns"] else None,
            "ly_date": ly.isoformat(),
            "basis": "store-side returns of store purchases (FSS)",
        }

    def demand_pct_of_gross(self, day: D, **scope) -> Optional[float]:
        """#42 Demand % of gross = ECOM demand ÷ gross sales in scope."""
        g = self.gross_pack(day, **scope)
        demand = 0.0
        for eid in self.scope_ids(**self._narrow(scope, channel="ECOM")):
            row = self.sales_row(eid, day)
            if row and row["demand_sales"] is not None:
                demand += self.convert(row["demand_sales"],
                                       self.entity(eid)["currency"])
        return (demand / g["gross"]) if g["gross"] else None

    # =====================================================================
    # Store status: #36 portfolio/trading, #40 the funnel
    # =====================================================================

    def store_status(self, day: D, **scope) -> Dict[str, object]:
        """#36/#40 Portfolio → Trading → Comp-Trading, with the two rates the
        relaunch doc's Ops Landing puts above every table."""
        stores = [e for e in self._scope_entities(**scope)
                  if e["channel"] == "STORE"]
        portfolio = [e for e in stores if self.in_portfolio(e, day)]
        trading = [e for e in portfolio if self.is_open_on(e, day)]
        comp = set(self.comp_set(day, **self._narrow(scope, channel="STORE")))
        comp_trading = [e for e in trading if e["entity_id"] in comp]
        new = [e for e in trading if e["entity_id"] not in comp
               and not self.comp_eligible(e["entity_id"], day)]
        closed = [e for e in portfolio if not self.is_open_on(e, day)]
        return {
            "portfolio": len(portfolio), "trading": len(trading),
            "comp_trading": len(comp_trading), "new": len(new),
            "closed": len(closed),
            "pct_trading": (len(trading) / len(portfolio)) if portfolio else None,
            "pct_comp_of_trading": (len(comp_trading) / len(trading))
                                   if trading else None,
            "portfolio_ids": sorted(e["entity_id"] for e in portfolio),
            "trading_ids": sorted(e["entity_id"] for e in trading),
            "comp_trading_ids": sorted(e["entity_id"] for e in comp_trading),
            "closed_ids": sorted(e["entity_id"] for e in closed),
        }

    TIERS = ("COMP_TRADING", "ALL_TRADING", "TOTAL")

    def tier_metrics(self, day: D, tier: str, **scope) -> Dict[str, object]:
        """The relaunch doc's three-tier table column: TY, % to LY, plan, % to
        plan for one tier. TOTAL includes ECOM; the trading tiers are doors."""
        if tier not in self.TIERS:
            raise CatalogError("tier %r is not one of %s" % (tier, self.TIERS))
        if tier == "TOTAL":
            ids = self.scope_ids(**scope)
        elif tier == "ALL_TRADING":
            ids = [e["entity_id"] for e in self._scope_entities(**scope)
                   if e["channel"] == "STORE" and self.is_open_on(e, day)]
        else:
            ids = self.store_status(day, **scope)["comp_trading_ids"]
        sub = dict(scope)
        sub.pop("entity_ids", None)
        sub["entity_ids"] = ids
        net = self.net_sales(day, **sub)
        pair = self.comp_pair(day, **sub)
        pp = self.plan_pair(day, **sub)
        return {
            "tier": tier, "entities": len(ids), "net_sales": net,
            "comp_ty": pair["ty"], "comp_ly": pair["ly"],
            "comp_pct": self.comp_pct(day, **sub),
            "plan": pp["plan"],
            "plan_attainment": (pp["actual"] / pp["plan"]) if pp["plan"] else None,
        }

    @staticmethod
    def fav_band(value: Optional[float]) -> Optional[str]:
        """±5% fav / within / unfav key (relaunch doc's triangle legend)."""
        if value is None:
            return None
        b = THRESHOLDS["fav_unfav_band"]
        if value > b:
            return "fav"
        if value < -b:
            return "unfav"
        return "within"

    # =====================================================================
    # Rank & leaderboards (#37)
    # =====================================================================

    RANK_KPIS = ("net_sales", "comp_pct", "conversion", "plan_attainment",
                 "traffic", "transactions", "ast", "upt")

    def rank_stores(self, day: D, kpi: str = "net_sales", n: int = 10,
                    **scope) -> Dict[str, List[dict]]:
        """#37 Top/Bottom-N stores by a selectable KPI, persona-scoped.

        Entities the KPI cannot be computed for (no traffic, no plan, not comp)
        are returned in `unavailable` rather than sorted to the bottom as zero."""
        if kpi not in self.RANK_KPIS:
            raise CatalogError(
                "rank KPI %r is not one of %s — ranking on an undefined KPI "
                "would silently order stores by None." % (kpi, self.RANK_KPIS))
        rows, unavailable = [], []
        for e in self._scope_entities(**scope):
            eid = e["entity_id"]
            if e["channel"] != "STORE" or self.sales_row(eid, day) is None:
                continue
            v = self._kpi_value(eid, day, kpi)
            rec = {"entity_id": eid, "name": e["name"], "region": e["region"],
                   "brand_id": e["brand_id"], "district_id": e["district_id"],
                   "affiliate_id": e["affiliate_id"], "kpi": kpi, "value": v}
            (rows if v is not None else unavailable).append(rec)
        rows.sort(key=lambda r: (-r["value"], r["entity_id"]))
        unavailable.sort(key=lambda r: r["entity_id"])
        return {"kpi": kpi, "top": rows[:n], "bottom": list(reversed(rows[-n:])),
                "unavailable": unavailable, "ranked": len(rows)}

    def upt_movers(self, day: D, n: int = 10, **scope) -> Dict[str, object]:
        """Doors ranked by how far UPT has MOVED against the aligned LY day,
        not by how high it sits.

        A level table rewards doors whose assortment naturally carries a big
        basket. A movement table names the doors that changed, which is the one
        a field leader can act on — and the only one on which an attach-rate
        story can win."""
        rows, unavailable = [], []
        for e in self._scope_entities(**scope):
            eid = e["entity_id"]
            if e["channel"] != "STORE" or self.sales_row(eid, day) is None:
                continue
            cb = self.comp_basket(day, entity_id=eid)
            rec = {"entity_id": eid, "name": e["name"], "region": e["region"],
                   "brand_id": e["brand_id"], "district_id": e["district_id"],
                   "affiliate_id": e["affiliate_id"],
                   "upt": cb["upt"], "ly_upt": cb["ly_upt"],
                   "upt_pct": cb["upt_pct"], "ast_pct": cb["ast_pct"],
                   "aus_pct": cb["aus_pct"],
                   "transactions": cb["ty_transactions"],
                   "units": cb["ty_units"]}
            (rows if cb["upt_pct"] is not None else unavailable).append(rec)
        rows.sort(key=lambda r: (-r["upt_pct"], r["entity_id"]))
        unavailable.sort(key=lambda r: r["entity_id"])
        return {"top": rows[:n], "bottom": list(reversed(rows[-n:])),
                "unavailable": unavailable, "ranked": len(rows),
                "basis": "comp basis, day-aligned LY; a door outside the comp "
                         "set has no like-for-like basket to move against"}

    def _kpi_value(self, eid, day, kpi):
        if kpi == "net_sales":
            return self.net_sales_of(eid, day)
        if kpi == "comp_pct":
            return self.comp_pct(day, entity_id=eid)
        if kpi == "conversion":
            return self.conversion(day, entity_id=eid)["conversion"]
        if kpi == "plan_attainment":
            return self.plan_attainment(day, entity_id=eid)
        if kpi == "traffic":
            t = self.traffic_of(eid, day)
            return float(t) if t is not None else None
        if kpi == "transactions":
            row = self.sales_row(eid, day)
            return float(row["transactions"]) if row else None
        if kpi == "upt":
            return self.basket(day, entity_id=eid)["upt"]
        return self.basket(day, entity_id=eid)["ast"]

    # =====================================================================
    # Hourly (#38 — BR-17)
    # =====================================================================

    def hourly_series(self, entity_id, day: D) -> Dict[str, object]:
        """#38 Hour-by-hour net sales, traffic and transactions for one door.

        Σ hourly reconciles to the day's posted total by construction (the
        seed ALLOCATES the day across hours) and the reconciliation gap is
        emitted so a surface can state it rather than assume it (BR-17)."""
        rows = self.conn.execute(
            "SELECT hour, traffic, net_sales, transactions FROM traffic_hour "
            "WHERE date=? AND entity_id=? ORDER BY hour",
            (day.isoformat(), entity_id)).fetchall()
        ccy = self.entity(entity_id)["currency"]
        hours = [{"hour": h, "traffic": t,
                  "net_sales": self.convert(n, ccy),
                  "net_sales_local": n, "transactions": x}
                 for h, t, n, x in rows]
        day_row = self.sales_row(entity_id, day)
        day_net = self.net_sales_of(entity_id, day)
        if day_net is not None:
            reconcile_display(hours, "net_sales", day_net)
        sum_net = round(sum(h["net_sales"] for h in hours), 2)
        sum_txn = sum(h["transactions"] for h in hours)
        return {
            "entity_id": entity_id, "date": day.isoformat(), "hours": hours,
            "open_hour": OPEN_HOUR, "close_hour": CLOSE_HOUR,
            "hourly_net_total": sum_net,
            "day_net_total": day_net,
            "reconciliation_gap": (round(sum_net - day_net, 2)
                                   if day_net is not None else None),
            "hourly_transactions": sum_txn,
            "day_transactions": day_row["transactions"] if day_row else None,
            "peak_hour": max(hours, key=lambda h: (h["net_sales"], h["hour"]))["hour"]
                         if hours else None,
            "governance": "Hourly is intraday and unaudited. The posted daily "
                          "figure remains the system of record (BR-17).",
        }

    def hourly_profile(self, entity_id, day: D, weeks: int = 4) -> Dict[str, object]:
        """The door's own trailing same-weekday hourly shape — the baseline a
        lost midday peak is visible against (storyline 10)."""
        share_acc = dict((h, 0.0) for h in range(OPEN_HOUR, CLOSE_HOUR + 1))
        n = 0
        for i in range(1, weeks + 1):
            d = day - dt.timedelta(days=7 * i)
            s = self.hourly_series(entity_id, d)
            total = s["hourly_net_total"]
            if not s["hours"] or not total:
                continue
            n += 1
            for h in s["hours"]:
                share_acc[h["hour"]] += h["net_sales"] / total
        if not n:
            return {"weeks": 0, "baseline_share": None}
        base = dict((h, share_acc[h] / n) for h in share_acc)
        cur = self.hourly_series(entity_id, day)
        total = cur["hourly_net_total"] or 0.0
        actual = dict((h["hour"], (h["net_sales"] / total) if total else 0.0)
                      for h in cur["hours"])
        return {
            "weeks": n, "baseline_share": base, "actual_share": actual,
            "delta_share": dict((h, round(actual.get(h, 0.0) - base[h], 5))
                                for h in base),
        }

    # =====================================================================
    # KPI tree (#39 — BR-20)
    # =====================================================================

    def kpi_tree(self, entity_id, day: D) -> Dict[str, object]:
        """#39 Sales = Traffic × Conversion × AST, AST = AUS × UPT.

        Driver contributions use SEQUENTIAL (waterfall) attribution in the
        fixed order traffic → conversion → AST:

            traffic     = (T1 − T0) · C0 · A0
            conversion  =  T1 · (C1 − C0) · A0
            AST         =  T1 ·  C1 · (A1 − A0)

        Those three telescope to T1C1A1 − T0C0A0 exactly, so the residual
        interaction term is zero by construction — it is still computed and
        emitted so a reader can see that it is zero rather than take it on
        trust (BR-20). AST is split the same way into AUS and UPT.

        `payload` is what the site's what-if calculator receives: the catalog's
        own driver values. The calculator multiplies them; it does not contain
        a second copy of any formula."""
        ly = self.ly_date(day)
        e = self.entity(entity_id)
        cur = self._tree_point(entity_id, day)
        prior = self._tree_point(entity_id, ly)
        if cur is None or prior is None:
            return {"entity_id": entity_id, "date": day.isoformat(),
                    "available": False,
                    "reason": ("no traffic or no posted sales on %s or its "
                               "LY-aligned day %s — the tree needs both sides "
                               "(BR-15: no fabricated traffic)"
                               % (day.isoformat(), ly.isoformat()))}
        t1, c1, a1, u1, p1, s1 = cur
        t0, c0, a0, u0, p0, s0 = prior
        traffic_c = (t1 - t0) * c0 * a0
        conv_c = t1 * (c1 - c0) * a0
        ast_c = t1 * c1 * (a1 - a0)
        aus_c = t1 * c1 * (u1 - u0) * p0
        upt_c = t1 * c1 * u1 * (p1 - p0)
        gap = s1 - s0
        residual = gap - (traffic_c + conv_c + ast_c)
        return {
            "entity_id": entity_id, "date": day.isoformat(),
            "ly_date": ly.isoformat(), "available": True,
            "actual": round(s1, 2), "ly": round(s0, 2), "gap": round(gap, 2),
            "drivers": [
                {"driver": "traffic", "ty": t1, "ly": t0,
                 "contribution": round(traffic_c, 2)},
                {"driver": "conversion", "ty": c1, "ly": c0,
                 "contribution": round(conv_c, 2)},
                {"driver": "ast", "ty": a1, "ly": a0,
                 "contribution": round(ast_c, 2)},
            ],
            "ast_split": [
                {"driver": "aus", "ty": u1, "ly": u0,
                 "contribution": round(aus_c, 2)},
                {"driver": "upt", "ty": p1, "ly": p0,
                 "contribution": round(upt_c, 2)},
            ],
            "residual_interaction": round(residual, 2),
            "method": "sequential (waterfall) attribution, fixed driver order "
                      "traffic -> conversion -> AST; AST split AUS -> UPT",
            # The payload carries UNROUNDED money. Rounding it to cents here
            # would make traffic x conversion x AST disagree with net_sales by
            # a fraction, and a reader converting a USD figure back to the
            # door's own currency would land a cent away from the store page.
            # Display rounding happens once, in the renderer (BR-16).
            "payload": {"traffic": t1, "conversion": c1, "aus": u1, "upt": p1,
                        "ast": a1, "net_sales": s1,
                        "ly_traffic": t0, "ly_conversion": c0, "ly_aus": u0,
                        "ly_upt": p0, "ly_ast": a0, "ly_net_sales": s0,
                        "currency": self.reporting_currency,
                        "local_currency": e["currency"],
                        "net_sales_local": self.net_sales_local_of(entity_id, day),
                        "ly_net_sales_local": self.net_sales_local_of(entity_id, ly),
                        "fx_units_per_usd": self.fx().get(e["currency"]),
                        "fx_disclosure": self.fx_disclosure(e["currency"]),
                        "converted": e["currency"] != self.reporting_currency},
        }

    def _tree_point(self, entity_id, day: D):
        row = self.sales_row(entity_id, day)
        traffic = self.traffic_of(entity_id, day)
        if row is None or not traffic or not row["transactions"] or not row["units"]:
            return None
        net = self.net_sales_of(entity_id, day)
        conv = row["transactions"] / float(traffic)
        ast = net / float(row["transactions"])
        aus = net / float(row["units"])
        upt = row["units"] / float(row["transactions"])
        return (float(traffic), conv, ast, aus, upt, net)

    # =====================================================================
    # E-commerce demand vs settled (#11, #12 — BR-4)
    # =====================================================================

    def ecom_ids(self, **scope) -> List[str]:
        return self.scope_ids(**self._narrow(scope, channel="ECOM"))

    def ecom_matured(self, day: D, as_of: D) -> bool:
        return (as_of - day).days >= ECOM_SETTLE_LAG_DAYS

    def ecom_day(self, day: D, as_of: D, **scope) -> Optional[Dict[str, object]]:
        """#11 E-comm Demand vs Shipped for a day, with its maturation state."""
        ids = [e for e in self.ecom_ids(**scope) if self.sales_row(e, day)]
        if not ids:
            return None
        ly_day = self.ly_date(day)

        def acc(d, col):
            total, seen = 0.0, False
            for eid in ids:
                row = self.sales_row(eid, d)
                if row and row[col] is not None:
                    total += self.convert(row[col], self.entity(eid)["currency"])
                    seen = True
            return round(total, 2) if seen else None

        out = {
            "date": day.isoformat(), "entities": ids,
            "demand": acc(day, "demand_sales"),
            "shipped": acc(day, "shipped_sales"),
            "returns": acc(day, "returns_recorded"),
            "matured": self.ecom_matured(day, as_of),
            "settle_lag_days": ECOM_SETTLE_LAG_DAYS,
            "ly_date": ly_day.isoformat(),
            "ly_demand": acc(ly_day, "demand_sales"),
            "ly_shipped": acc(ly_day, "shipped_sales"),
        }
        out["demand_comp_pct"] = (out["demand"] / out["ly_demand"] - 1.0
                                  if out["ly_demand"] else None)
        out["shipped_comp_pct"] = (out["shipped"] / out["ly_shipped"] - 1.0
                                   if out["ly_shipped"] else None)
        return out

    def ecom_settled_return_rate(self, as_of: D, lookback_days: int = 28,
                                 **scope) -> Optional[float]:
        """#12 returns ÷ shipped over a MATURED window only (the BR-4 trap)."""
        last = as_of - dt.timedelta(days=ECOM_SETTLE_LAG_DAYS)
        shipped = returns = 0.0
        for eid in self.ecom_ids(**scope):
            ccy = self.entity(eid)["currency"]
            for i in range(lookback_days):
                row = self.sales_row(eid, last - dt.timedelta(days=i))
                if row is None or row["shipped_sales"] is None:
                    continue
                shipped += self.convert(row["shipped_sales"], ccy)
                returns += self.convert(row["returns_recorded"], ccy)
        return (returns / shipped) if shipped else None

    # =====================================================================
    # Gap-to-go (#14) and completeness (#13 — BR-3)
    # =====================================================================

    def gap_to_go(self, day: D, **scope) -> Dict[str, object]:
        """#14 Plan remaining in the fiscal period ÷ selling days remaining.
        Day-grain plan only; the disclosure names the covered brands."""
        per = self.cal.period_for_date(day)
        plan_total = 0.0
        d = per.start
        while d <= per.end:
            for eid in self.scope_ids(**scope):
                p = self.plan_of(eid, d)
                if p:
                    plan_total += p
            d += dt.timedelta(days=1)
        actual = self.window_metrics(day, "MTD", **scope)["net_sales"]
        remaining_days = (per.end - day).days
        remaining_plan = round(plan_total - actual, 2)
        return {
            "period_label": per.label, "period_end": per.end.isoformat(),
            "period_plan": round(plan_total, 2), "actual_to_date": actual,
            "remaining_plan": remaining_plan, "remaining_days": remaining_days,
            "required_run_rate": (remaining_plan / remaining_days)
                                 if remaining_days > 0 else None,
            "basis": "day-grain plan only (BR-19)",
        }

    def completeness(self, day: D, **scope) -> Dict[str, object]:
        """#13 Completeness: reported stores ÷ expected; missing entities named,
        plus posted dollars against the trailing same-weekday average."""
        expected = [e for e in self._scope_entities(**scope)
                    if e["channel"] == "STORE" and self.is_open_on(e, day)]
        missing = [e["entity_id"] for e in expected
                   if self.sales_row(e["entity_id"], day) is None]
        sub = self._narrow(scope, channel="STORE")
        posted = self.net_sales(day, **sub)
        baseline = self.trailing_same_weekday_avg(day, 4, **sub)
        return {
            "expected": len(expected), "reported": len(expected) - len(missing),
            "missing": sorted(missing),
            "missing_names": [self.entity(m)["name"] for m in sorted(missing)],
            "pct": ((len(expected) - len(missing)) / len(expected))
                   if expected else 1.0,
            "posted_sales": posted, "baseline_sales": baseline,
            "posted_pct": (posted / baseline) if baseline else None,
        }

    def trailing_same_weekday_avg(self, day: D, weeks: int = 4,
                                  **scope) -> Optional[float]:
        vals = []
        for i in range(1, weeks + 1):
            d = day - dt.timedelta(days=7 * i)
            try:
                self.cal_row(d)
            except CatalogError:
                continue
            vals.append(self.net_sales(d, **scope))
        if not vals:
            return None
        return round(sum(vals) / len(vals), 2)

    def late_posters(self, day: D, lookback_days: int = 1, **scope) -> List[dict]:
        """BR-3 late-poster escalation: stores unposted on `day`, flagged as
        escalating when they were unposted the preceding day too."""
        out = []
        for eid in self.completeness(day, **scope)["missing"]:
            streak, probe = 1, day - dt.timedelta(days=1)
            while streak <= lookback_days + 3:
                e = self.entity(eid)
                if not self.is_open_on(e, probe):
                    break
                if self.sales_row(eid, probe) is not None:
                    break
                streak += 1
                probe -= dt.timedelta(days=1)
            e = self.entity(eid)
            out.append({"entity_id": eid, "name": e["name"], "region": e["region"],
                        "brand_id": e["brand_id"], "district_id": e["district_id"],
                        "consecutive_days": streak, "escalate": streak >= 2,
                        "since": (day - dt.timedelta(days=streak - 1)).isoformat()})
        out.sort(key=lambda r: (-r["consecutive_days"], r["entity_id"]))
        return out
