# -*- coding: utf-8 -*-
"""Deterministic seed generator for the Lumière Ops Flash.

Builds `ops.db` from `schema.sql`: the three-brand Lumière Beauty Group house
(29 stores across two affiliates + two e-commerce channels), the NRF 4-5-4
calendar with materialized day-aligned LY dates, ~2.5 fiscal years of daily
facts, SKU-grain sales lines, traffic (daily + hourly), a ~90K customer file,
order-grain omni events, store-side return events, and plan at each brand's
native grain.

Every storyline the PRD (§7) names as acceptance material is planted here and
ASSERTED to manifest before the seed reports success. Assertion messages name
the storyline/rule, the rows involved, and the fix (the NFR-4 style).

Determinism (NFR-2): all randomness is a stable hash of (entity, date, tag) —
no `random` module, no `now()`, no wall-clock anywhere. Same source ->
byte-identical database.

Run:  python3 seed.py          # builds ./ops.db and prints the storyline index
"""

from __future__ import annotations

import bisect
import datetime as dt
import hashlib
import os
import sqlite3
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from flash.calendar import (          # noqa: E402
    NRFCalendar, dow_1sun, holiday_code, ly_holiday_aligned_date,
)
from vendor.roster import ROSTER      # noqa: E402

D = dt.date
HERE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(HERE, "ops.db")
SCHEMA_PATH = os.path.join(HERE, "schema.sql")

# --- demo anchors (fixed by the data, never now(); America/New_York) -------
TODAY = D(2026, 7, 24)             # "today"
LATEST_COMPLETE = D(2026, 7, 23)   # yesterday: the default flash date
SALES_START = D(2024, 2, 4)        # FY2024 start (2 full FYs + FY2026 YTD)
CAL_START = D(2023, 1, 29)         # FY2023 start, so FY2024's LY dates exist
SALES_END = LATEST_COMPLETE
CAL_END = NRFCalendar().period_for_date(LATEST_COMPLETE).end
TZ_SUFFIX = "-04:00"               # America/New_York in July; fixed, not derived

# The SKU / omni / customer / hourly grains are seeded over a DETAIL WINDOW
# rather than the full history: 14 fiscal weeks of TY plus each of those days'
# LY-aligned counterpart. That covers Day, LW, WTD, MTD and QTD at SKU grain
# with a comparable LY on every day, and holds full regeneration inside the
# 60s NFR (PRD §8 explicitly prefers a smaller seed to clever optimisation).
DETAIL_DAYS = 98                   # 14 fiscal weeks, inclusive of LATEST_COMPLETE

BASE_FY = 2024
STORE_GROWTH = 0.03                # YoY store trend
ECOM_GROWTH = 0.12                 # ECOM grows faster
ECOM_SHARE = 0.22                  # ECOM ~22% of its affiliate's revenue

# --- shape curves (normalized to mean 1.0 at load) ------------------------
_PERIOD_WEIGHTS = {                # beauty retailer; Q4 (P10/P11) heavy
    1: 1.05, 2: 0.92, 3: 0.95, 4: 1.10, 5: 1.00, 6: 1.02,
    7: 1.05, 8: 0.95, 9: 0.98, 10: 1.22, 11: 1.48, 12: 0.85,
}
_DOW_WEIGHTS = {                   # 1=Sun..7=Sat; Sat peak, Tue trough
    1: 1.05, 2: 0.85, 3: 0.80, 4: 0.88, 5: 0.95, 6: 1.20, 7: 1.45,
}
_HOLIDAY_MULT = {
    "NEW_YEARS_DAY": 0.60, "VALENTINES": 1.55, "EASTER": 0.70,
    "MOTHERS_DAY": 1.70, "MEMORIAL_DAY": 1.20, "JULY_4": 1.35,
    "LABOR_DAY": 1.20, "THANKSGIVING": 0.40, "BLACK_FRIDAY": 2.60,
    "CYBER_MONDAY": 1.90, "CHRISTMAS_EVE": 1.55, "CHRISTMAS_DAY": 0.10,
    "NEW_YEARS_EVE": 1.15,
}

# Store trading hours (PRD §10): 10:00–20:00 local => 11 hourly buckets.
OPEN_HOUR, CLOSE_HOUR = 10, 20
HOURS = tuple(range(OPEN_HOUR, CLOSE_HOUR + 1))
_HOUR_WEIGHTS = {10: 0.045, 11: 0.065, 12: 0.095, 13: 0.115, 14: 0.120,
                 15: 0.115, 16: 0.105, 17: 0.100, 18: 0.095, 19: 0.085,
                 20: 0.060}


def _normalized(weights):
    mean = sum(weights.values()) / len(weights)
    return {k: v / mean for k, v in weights.items()}


PERIOD_W = _normalized(_PERIOD_WEIGHTS)
DOW_W = _normalized(_DOW_WEIGHTS)

# =========================================================================
# Organisation dimensions (D7/D8)
# =========================================================================

CATEGORIES = ("Skincare", "Makeup", "Fragrance", "Haircare", "Tools & Accessories")

BRANDS = [
    dict(brand_id="LUM", name="Lumière",
         positioning="Prestige skincare and fragrance",
         categories=("Skincare", "Fragrance"), plan_grain="DAY"),
    dict(brand_id="ATN", name="Atelier Noir",
         positioning="Colour cosmetics",
         categories=("Makeup",), plan_grain="WEEK"),
    dict(brand_id="BOT", name="Botanica",
         positioning="Botanical haircare and styling tools",
         categories=("Haircare", "Tools & Accessories"), plan_grain="NONE"),
]
BRAND_BY_ID = {b["brand_id"]: b for b in BRANDS}
BRAND_OF_CATEGORY = {c: b["brand_id"] for b in BRANDS for c in b["categories"]}

AFFILIATES = [
    dict(affiliate_id="US", name="United States", currency="USD"),
    dict(affiliate_id="CA", name="Canada", currency="CAD"),
]
CURRENCY_OF_AFFILIATE = {a["affiliate_id"]: a["currency"] for a in AFFILIATES}

# One fixed rate, disclosed wherever a converted figure appears (BR-16).
FX_CAD_PER_USD = 1.35
FX_RATES = [
    dict(currency="USD", units_per_usd=1.0, basis="Reporting currency"),
    dict(currency="CAD", units_per_usd=FX_CAD_PER_USD,
         basis="Fixed plan rate CAD 1.35 per USD (seeded, not floating)"),
]

DISTRICTS = [
    dict(district_id="NE-1", name="Northeast 1", region="Northeast", affiliate_id="US"),
    dict(district_id="NE-2", name="Northeast 2", region="Northeast", affiliate_id="US"),
    dict(district_id="SE-1", name="Southeast 1", region="Southeast", affiliate_id="US"),
    dict(district_id="SE-2", name="Southeast 2", region="Southeast", affiliate_id="US"),
    dict(district_id="MW-1", name="Midwest 1", region="Midwest", affiliate_id="US"),
    dict(district_id="MW-2", name="Midwest 2", region="Midwest", affiliate_id="US"),
    dict(district_id="SW-1", name="Southwest 1", region="Southwest", affiliate_id="US"),
    dict(district_id="SW-2", name="Southwest 2", region="Southwest", affiliate_id="US"),
    dict(district_id="WE-1", name="West 1", region="West", affiliate_id="US"),
    dict(district_id="WE-2", name="West 2", region="West", affiliate_id="US"),
    dict(district_id="CA-1", name="Canada 1", region="Canada", affiliate_id="CA"),
]

# Brand partition of the fleet (PRD §10: Lumière 14, Atelier Noir 9, Botanica 6).
STORE_BRAND = {
    "LB-001": "LUM", "LB-002": "LUM", "LB-003": "ATN", "LB-004": "LUM",
    "LB-005": "ATN", "LB-006": "BOT", "LB-007": "LUM", "LB-008": "LUM",
    "LB-009": "ATN", "LB-010": "LUM", "LB-011": "BOT", "LB-012": "ATN",
    "LB-013": "LUM", "LB-014": "ATN", "LB-015": "LUM", "LB-016": "BOT",
    "LB-017": "ATN", "LB-018": "LUM", "LB-019": "ATN", "LB-020": "BOT",
    "LB-021": "LUM", "LB-022": "LUM", "LB-023": "BOT", "LB-024": "ATN",
    "LB-025": "LUM", "LB-026": "LUM", "LB-027": "ATN", "LB-028": "LUM",
    "LB-029": "BOT",
}

STORE_DISTRICT = {
    "LB-001": "NE-1", "LB-002": "NE-1", "LB-003": "NE-1",
    "LB-004": "NE-2", "LB-005": "NE-2", "LB-006": "NE-2",
    "LB-007": "SE-1", "LB-008": "SE-1", "LB-009": "SE-1",
    "LB-010": "SE-2", "LB-011": "SE-2", "LB-012": "SE-2",
    "LB-013": "MW-1", "LB-014": "MW-1", "LB-015": "MW-1",
    "LB-016": "MW-2", "LB-017": "MW-2",
    "LB-018": "SW-1", "LB-019": "SW-1",
    "LB-020": "SW-2", "LB-021": "SW-2",
    "LB-022": "WE-1", "LB-023": "WE-1",
    "LB-024": "WE-2", "LB-025": "WE-2",
    "LB-026": "CA-1", "LB-027": "CA-1", "LB-028": "CA-1", "LB-029": "CA-1",
}

# The four deterministic Canadian doors (D8). Money figures are CAD.
CA_STORES = [
    dict(entity_id="LB-026", store_number=126, name="Lumiere Bloor Court",
         city="Toronto", state_province="ON", rentable_sf=2700,
         target_sales_psf=1180.0, open_date=D(2019, 5, 1)),
    dict(entity_id="LB-027", store_number=127, name="Lumiere Queen West Pavilion",
         city="Toronto", state_province="ON", rentable_sf=2300,
         target_sales_psf=940.0, open_date=D(2021, 4, 1)),
    dict(entity_id="LB-028", store_number=128, name="Lumiere Pacific Centre Walk",
         city="Vancouver", state_province="BC", rentable_sf=2900,
         target_sales_psf=1120.0, open_date=D(2018, 9, 1)),
    dict(entity_id="LB-029", store_number=129, name="Lumiere Sainte-Catherine Row",
         city="Montreal", state_province="QC", rentable_sf=2500,
         target_sales_psf=860.0, open_date=D(2020, 3, 1)),
]

ECOM_ENTITIES = ("ECOM-US", "ECOM-CA")

# =========================================================================
# Planted storylines (README index; every one asserted in assert_storylines)
# =========================================================================

# -- inherited from the executive flash ----------------------------------
SOFT_REGION = "Southeast"
SOFT_STORES = ("LB-009", "LB-010")
SOFT_START = D(2026, 7, 10)
SOFT_MULT = 0.78
BRIGHT_STORE = "LB-022"
BRIGHT_START = D(2026, 7, 17)
BRIGHT_MULT = 1.18
REMODEL_STORE = "LB-013"
REMODEL_START = D(2026, 6, 15)
NEW_STORE = "LB-025"
LATE_BOTH = "LB-021"
LATE_ONE = "LB-005"
LATE_DAY = D(2026, 7, 23)
LATE_DAY_PREV = D(2026, 7, 22)
ECOM_MATURATION_DAY = D(2026, 7, 23)
ECOM_MATURATION_ENTITY = "ECOM-US"
RESTATE_DAY = D(2026, 7, 20)

# -- new, PRD §7 ----------------------------------------------------------
# 1 BOPIS upsell champion
UPSELL_STAR = "LB-008"
UPSELL_STAR_START = D(2026, 6, 1)
UPSELL_BASE_RATE = 0.18            # share of picked-up orders that attach
UPSELL_STAR_RATE = 0.46
# 2 BOPIS execution gap (recognized vs all-inclusive divergence)
PICKUP_GAP_REGION = "Southwest"
PICKUP_GAP_START = D(2026, 7, 10)
PICKUP_RATE_BASE = 0.88
PICKUP_RATE_GAP = 0.68
# 3 BORIS save story
BORIS_SAVE_STORE = "LB-014"
BORIS_SAVE_START = D(2026, 6, 15)
BORIS_SAVE_RATE_BASE = 0.22
BORIS_SAVE_RATE_STAR = 0.58
# 4 Category slide
SLIDE_CATEGORY = "Fragrance"
SLIDE_START = D(2026, 7, 10)
SLIDE_CATEGORY_MULT = 0.82
SLIDE_SKUS = ("LUM-FRG-003", "LUM-FRG-007", "LUM-FRG-012")
SLIDE_SKU_MULT = 0.42
# 5 SKU breakout
BREAKOUT_SKU = "LUM-SKN-030"
BREAKOUT_LAUNCH = D(2026, 5, 15)
BREAKOUT_MULT = 4.2
# 6 New-to-file dip
NTF_BASE_SHARE = 0.16
NTF_DIP_ENTITY = "ECOM-US"
NTF_DIP_START = D(2026, 7, 19)     # the fiscal week containing LATEST_COMPLETE
NTF_DIP_SHARE = 0.085
# 7 Omni invariance demo day
OMNI_HEAVY_DAY = D(2026, 7, 18)
OMNI_HEAVY_MULT = 3.4              # recognition lags creation, so the created
                                   # spike must be large for the picked-up
                                   # spike on the day to read as one
# 8 C&R conversion win
CR_STEP_DATE = D(2026, 6, 21)
CR_CONV_BASE = 0.44
CR_CONV_AFTER = 0.73
# 9 Traffic up / conversion down (and 14: the tree story)
CONV_STORE = "LB-015"
CONV_START = D(2026, 7, 10)
CONV_SALES_MULT = 0.93
CONV_RATE_MULT = 0.85              # conversion multiplier => traffic rises
# 10 Hourly shape story
HOURLY_STORE = "LB-018"
HOURLY_DAY = D(2026, 7, 21)
# 11 Brand divergence inside one region (West: LUM up, ATN down)
DIVERGE_REGION = "West"
DIVERGE_STORE = "LB-024"           # Atelier Noir
DIVERGE_START = D(2026, 7, 10)
DIVERGE_MULT = 0.84
# 12 Canada beats plan in CAD
CA_BEAT_STORES = ("LB-026", "LB-028")   # the day-planned CA doors
CA_BEAT_START = D(2026, 7, 5)
CA_BEAT_MULT = 1.13
# 13 Plan-grain story: structural (one brand per grain), asserted on the anchor
# 14 Tree story: derived from storyline 9's data, asserted on the anchor

# Missing-traffic incident (BR-15: conversion unavailable, never 0%).
TRAFFIC_MISSING = {("LB-011", D(2026, 7, 22)), ("LB-011", D(2026, 7, 23))}

# BORIS shipping-label saving constant (BR-14), USD.
LABEL_SAVING_USD = 7.46


def u(*parts) -> float:
    """Deterministic uniform in [0,1) from a stable hash (platform-independent)."""
    s = "|".join(str(p) for p in parts)
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:13], 16) / float(16 ** 13)


# =========================================================================
# SECTION: products
# =========================================================================
# ~120 SKUs across 5 categories, partitioned by brand. Names, prices and
# launch dates are all deterministic functions of the SKU index — no random.

_CAT_CODE = {"Skincare": "SKN", "Fragrance": "FRG", "Makeup": "MKP",
             "Haircare": "HAI", "Tools & Accessories": "TLS"}
_CAT_COUNT = {"Skincare": 34, "Fragrance": 20, "Makeup": 40,
              "Haircare": 16, "Tools & Accessories": 10}
_CAT_PRICE_BAND = {          # USD list price band (AUR emerges, is not stored)
    "Skincare": (38.0, 165.0),
    "Fragrance": (62.0, 210.0),
    "Makeup": (18.0, 58.0),
    "Haircare": (22.0, 72.0),
    "Tools & Accessories": (14.0, 120.0),
}
_CAT_LINES = {
    "Skincare": ("Rosewater", "Ceramide", "Nocturne", "Aurora", "Velvet",
                 "Coastal", "Lumen", "Amber", "Marine", "Silk", "Petal",
                 "Cedar", "Halo", "Dewpoint", "Ivory", "Solstice", "Meadow"),
    "Fragrance": ("Nocturne", "Blanc", "Tuberose", "Vetiver", "Bergamot",
                  "Santal", "Iris", "Fig Leaf", "Neroli", "Oud"),
    "Makeup": ("Noir", "Atelier", "Studio", "Matte", "Lustre", "Prisme",
               "Contour", "Kohl", "Satin", "Chroma", "Opal", "Graphite",
               "Rouge", "Bisque"),
    "Haircare": ("Botanica", "Willow", "Yarrow", "Birch", "Kelp", "Clover",
                 "Juniper", "Nettle"),
    "Tools & Accessories": ("Atelier", "Botanica", "Studio", "Field", "Everyday"),
}
_CAT_FORMS = {
    "Skincare": ("Serum", "Cream", "Essence", "Balm", "Mask", "Toner",
                 "Elixir", "Cleanser", "Oil", "Concentrate"),
    "Fragrance": ("Eau de Parfum", "Eau de Toilette", "Body Mist",
                  "Hair Mist", "Solid Perfume"),
    "Makeup": ("Lipstick", "Foundation", "Palette", "Mascara", "Liner",
               "Blush", "Gloss", "Powder"),
    "Haircare": ("Shampoo", "Conditioner", "Hair Oil", "Scalp Tonic",
                 "Masque", "Leave-In"),
    "Tools & Accessories": ("Brush Set", "Blending Sponge", "Wide-Tooth Comb",
                            "Detangling Brush", "Cosmetic Case"),
}
# A handful of deliberately recent launches so "new SKU" behaviour is exercised.
_EXTRA_RECENT_LAUNCHES = {
    "ATN-MKP-038": D(2026, 3, 2),
    "BOT-HAI-015": D(2026, 4, 20),
    "LUM-FRG-019": D(2026, 2, 9),
}


def build_products():
    """Return the deterministic product catalogue (list of dicts)."""
    out = []
    for cat in CATEGORIES:
        brand_id = BRAND_OF_CATEGORY[cat]
        code = _CAT_CODE[cat]
        lines, forms = _CAT_LINES[cat], _CAT_FORMS[cat]
        lo, hi = _CAT_PRICE_BAND[cat]
        for i in range(_CAT_COUNT[cat]):
            sku_id = "%s-%s-%03d" % (brand_id, code, i + 1)
            name = "%s %s" % (lines[i % len(lines)],
                              forms[(i // len(lines)) % len(forms)])
            price = float(int(round(lo + (hi - lo) * u(sku_id, "price"))))
            if sku_id == BREAKOUT_SKU:
                launch = BREAKOUT_LAUNCH
            elif sku_id in _EXTRA_RECENT_LAUNCHES:
                launch = _EXTRA_RECENT_LAUNCHES[sku_id]
            else:
                # spread across 2019-01-01 .. 2024-12-31 (all long-established)
                span = (D(2024, 12, 31) - D(2019, 1, 1)).days
                launch = D(2019, 1, 1) + dt.timedelta(
                    days=int(u(sku_id, "launch") * span))
            out.append(dict(sku_id=sku_id, name=name, brand_id=brand_id,
                            category=cat, launch_date=launch.isoformat(),
                            unit_price=price))
    return out

# =========================================================================
# SECTION: entities
# =========================================================================
def build_entities():
    """29 stores (25 vendored US + 4 seeded CA) + 2 e-commerce channels.

    `annual_volume` is the base-year anchor in the entity's LOCAL currency
    (BR-16: facts are local; conversion happens once, in the catalog)."""
    psfs = [r["target_sales_psf"] for r in ROSTER if r["target_sales_psf"]]
    median_psf = sorted(psfs)[len(psfs) // 2]

    entities = []
    us_store_total = 0.0
    ca_store_total = 0.0

    for r in ROSTER:
        psf = r["target_sales_psf"] or median_psf
        annual = psf * r["rentable_sf"]
        us_store_total += annual
        eid = r["lease_id"]
        entities.append(dict(
            entity_id=eid, store_number=r["store_number"], name=r["store_name"],
            channel="STORE", region=r["region"],
            open_date=r["commencement_date"].isoformat(), close_date=None,
            remodel_start=(REMODEL_START.isoformat()
                           if eid == REMODEL_STORE else None),
            remodel_end=None, rentable_sf=r["rentable_sf"],
            target_sales_psf=r["target_sales_psf"], annual_volume=round(annual, 2),
            brand_id=STORE_BRAND[eid], district_id=STORE_DISTRICT[eid],
            affiliate_id="US", currency="USD", state_province=r["state"],
            city=r["city"], store_status=r["store_status"],
        ))

    for s in CA_STORES:
        annual = s["target_sales_psf"] * s["rentable_sf"]      # CAD
        ca_store_total += annual
        entities.append(dict(
            entity_id=s["entity_id"], store_number=s["store_number"],
            name=s["name"], channel="STORE", region="Canada",
            open_date=s["open_date"].isoformat(), close_date=None,
            remodel_start=None, remodel_end=None,
            rentable_sf=s["rentable_sf"], target_sales_psf=s["target_sales_psf"],
            annual_volume=round(annual, 2),
            brand_id=STORE_BRAND[s["entity_id"]],
            district_id=STORE_DISTRICT[s["entity_id"]],
            affiliate_id="CA", currency="CAD",
            state_province=s["state_province"], city=s["city"],
            store_status="Open",
        ))

    # E-commerce, one channel per affiliate, each ~22% of its affiliate's
    # revenue. brand_id is NULL: ECOM is multi-brand and carries brand on the
    # SKU (PRD §3).
    for aff, store_total in (("US", us_store_total), ("CA", ca_store_total)):
        entities.append(dict(
            entity_id="ECOM-%s" % aff, store_number=None,
            name="E-commerce %s" % aff, channel="ECOM", region="ECOM",
            open_date=CAL_START.isoformat(), close_date=None,
            remodel_start=None, remodel_end=None, rentable_sf=None,
            target_sales_psf=None,
            annual_volume=round(store_total * (ECOM_SHARE / (1.0 - ECOM_SHARE)), 2),
            brand_id=None, district_id=None, affiliate_id=aff,
            currency=CURRENCY_OF_AFFILIATE[aff], state_province=None,
            city=None, store_status="Open",
        ))
    return entities


def open_date_of(e):
    return D.fromisoformat(e["open_date"])


def is_open_on(e, day):
    """Store is trading on `day` (open, not in a remodel/closure window)."""
    if open_date_of(e) > day:
        return False
    if e["remodel_start"]:
        rs = D.fromisoformat(e["remodel_start"])
        re_ = D.fromisoformat(e["remodel_end"]) if e["remodel_end"] else None
        if day >= rs and (re_ is None or day <= re_):
            return False
    return True


def is_missing(entity_id, day):
    """Planted late-poster incident: these entity/day rows never post (BR-3)."""
    if day == LATE_DAY and entity_id in (LATE_BOTH, LATE_ONE):
        return True
    if day == LATE_DAY_PREV and entity_id == LATE_BOTH:
        return True
    return False


def assortment_of(entity, products_by_brand, all_skus):
    """SKUs an entity can sell: its brand's range for a store, everything for
    ECOM (which is multi-brand and carries brand through the SKU)."""
    if entity["channel"] == "ECOM":
        return all_skus
    return products_by_brand[entity["brand_id"]]

# =========================================================================
# SECTION: daily model
# =========================================================================
def year_factor(channel, fiscal_year):
    yrs = fiscal_year - BASE_FY
    g = ECOM_GROWTH if channel == "ECOM" else STORE_GROWTH
    return (1.0 + g) ** yrs


def storyline_mult(entity_id, day):
    """Multiplicative storyline effects layered on the base sales model."""
    m = 1.0
    if entity_id in SOFT_STORES and SOFT_START <= day <= LATEST_COMPLETE:
        m *= SOFT_MULT
    if entity_id == BRIGHT_STORE and BRIGHT_START <= day <= LATEST_COMPLETE:
        m *= BRIGHT_MULT
    if entity_id == CONV_STORE and CONV_START <= day <= LATEST_COMPLETE:
        m *= CONV_SALES_MULT
    if entity_id == DIVERGE_STORE and DIVERGE_START <= day <= LATEST_COMPLETE:
        m *= DIVERGE_MULT
    if entity_id in CA_BEAT_STORES and CA_BEAT_START <= day <= LATEST_COMPLETE:
        m *= CA_BEAT_MULT
    return m


def daily_mean(entity, fiscal_year, period, dow, day):
    """The deterministic, noise-free, storyline-free expectation for a day.
    Plan is built from exactly this, so attainment reads as noise ± storyline."""
    base = (entity["annual_volume"]
            * year_factor(entity["channel"], fiscal_year) / 364.0)
    return base * PERIOD_W[period] * DOW_W[dow] * _HOLIDAY_MULT.get(
        holiday_code(day), 1.0)


def base_sales(entity, day, fiscal_year, period, dow):
    """Deterministic net sales for a trading entity/day (pre-missing check)."""
    noise = 0.90 + 0.20 * u(entity["entity_id"], day.isoformat(), "noise")
    return (daily_mean(entity, fiscal_year, period, dow, day) * noise
            * storyline_mult(entity["entity_id"], day))


def txn_units(entity, net):
    """Transactions and units. AOV/UPT are fixed per entity, so transactions
    track sales — which is what makes the KPI tree's driver algebra legible."""
    if entity["channel"] == "STORE":
        aov = 45.0 + 45.0 * u(entity["entity_id"], "aov")
    else:
        aov = 65.0 + 30.0 * u(entity["entity_id"], "aov")
    if entity["currency"] == "CAD":
        aov *= FX_CAD_PER_USD          # local-currency basket (BR-16)
    upt = 1.8 + 1.6 * u(entity["entity_id"], "upt")
    txns = max(1, int(round(net / aov)))
    units = max(txns, int(round(txns * upt)))
    return txns, units


def ecom_series(entity, day, net, cal):
    """demand / shipped(settled) / returns for an ECOM day (BR-4).

    The planted maturation day has demand −8% vs its LY but settles +5% — the
    burst-of-large-baskets case that looks soft day-of and settles positive."""
    demand = net
    if day == ECOM_MATURATION_DAY and entity["entity_id"] == ECOM_MATURATION_ENTITY:
        ly, _ = cal.ly_aligned_date(day)
        ly_net = base_sales(entity, ly, cal.fiscal_year_of(ly),
                            cal.period_for_date(ly).period_no, dow_1sun(ly))
        demand = round(ly_net * 0.92, 2)
        shipped = round(ly_net * 1.05, 2)
    else:
        shipped = round(demand * (0.985 + 0.03 * u(
            entity["entity_id"], day.isoformat(), "ship")), 2)
    returns = round(shipped * (0.06 + 0.03 * u(
        entity["entity_id"], day.isoformat(), "ret")), 2)
    return round(demand, 2), shipped, returns


def gross_discount_return(entity, day, net):
    """Deck KPIs #32/#33: gross, discounts, store-side returns.

    Seeded so that net = gross − discounts − returns EXACTLY, to the cent
    (asserted per row). Discounts run 8–16% of gross, store returns 4–7%."""
    eid = entity["entity_id"]
    if entity["channel"] == "ECOM":
        d = 0.06 + 0.06 * u(eid, day.isoformat(), "disc")
        r = 0.030 + 0.020 * u(eid, day.isoformat(), "retg")
    else:
        d = 0.08 + 0.08 * u(eid, day.isoformat(), "disc")
        r = 0.040 + 0.030 * u(eid, day.isoformat(), "retg")
        if eid == BORIS_SAVE_STORE and day >= BORIS_SAVE_START:
            r += 0.025                 # storyline 3: elevated return volume
    gross = round(net / (1.0 - d - r), 2)
    discount = round(gross * d, 2)
    ret = round(gross - discount - net, 2)
    return gross, discount, ret


def conversion_base(entity_id):
    """Per-store conversion trait, 15–25% (PRD §10 traffic model)."""
    return 0.15 + 0.10 * u(entity_id, "convbase")


def conversion_mult(entity_id, day):
    """Storyline 9: conversion slides while traffic rises (same transactions
    divided by a lower conversion rate produce MORE traffic, by construction)."""
    if entity_id == CONV_STORE and CONV_START <= day <= LATEST_COMPLETE:
        return CONV_RATE_MULT
    return 1.0


def traffic_of(entity, day, txns):
    """Traffic derived as transactions ÷ conversion (PRD §10). Deliberately
    low noise so conversion movement is a signal, not sampling wobble."""
    rate = conversion_base(entity["entity_id"]) * conversion_mult(
        entity["entity_id"], day)
    noise = 0.98 + 0.04 * u(entity["entity_id"], day.isoformat(), "tnoise")
    return max(1, int(round(txns / rate * noise)))


def hour_weights(entity_id, day, dow):
    """Per-store hourly curve: midday peak, Saturday shifted earlier, plus a
    small deterministic per-store tilt. Storyline 10 collapses one store's
    midday peak on one day and pushes the volume into the evening."""
    w = dict(_HOUR_WEIGHTS)
    tilt = -0.5 + u(entity_id, "hourtilt")          # −0.5 .. +0.5
    for h in HOURS:
        w[h] *= 1.0 + 0.10 * tilt * (h - 15) / 5.0
    if dow == 7:                                     # Saturday peaks earlier
        for h in HOURS:
            w[h] *= 1.0 + 0.12 * (15 - h) / 5.0
    if entity_id == HOURLY_STORE and day == HOURLY_DAY:
        for h in (12, 13, 14, 15):
            w[h] *= 0.55                             # the lost midday peak
        for h in (18, 19, 20):
            w[h] *= 1.65
    total = sum(w[h] for h in HOURS)
    return {h: w[h] / total for h in HOURS}


def ntf_share(entity_id, day):
    """New-to-file share of buyers. Storyline 6 dips one channel below the
    exception threshold for the current fiscal week."""
    base = NTF_BASE_SHARE + 0.03 * (u(entity_id, day.isoformat(), "ntf") - 0.5)
    if entity_id == NTF_DIP_ENTITY and NTF_DIP_START <= day <= LATEST_COMPLETE:
        return NTF_DIP_SHARE
    return base

# =========================================================================
# SECTION: generators
# =========================================================================
def allocate(total, weights):
    """Split an integer `total` across `weights` (list of (key, weight)) so the
    parts sum EXACTLY to `total`. Largest-remainder, ties broken by key, so the
    result is deterministic and reproducible byte for byte.

    This is the mechanism behind BR-11: SKU lines and hourly buckets are
    ALLOCATIONS of the posted day total, never independent draws that have to
    be reconciled afterwards."""
    if total <= 0 or not weights:
        return {}
    tw = sum(w for _, w in weights)
    if tw <= 0:
        return {}
    out, assigned, fracs = {}, 0, []
    for k, w in weights:
        exact = total * w / tw
        n = int(exact)
        out[k] = n
        assigned += n
        fracs.append((exact - n, k))
    fracs.sort(key=lambda t: (-t[0], t[1]))
    i = 0
    while assigned < total:
        out[fracs[i % len(fracs)][1]] += 1
        assigned += 1
        i += 1
    return out


def detail_dates(cal):
    """The SKU/omni/customer/hourly window: DETAIL_DAYS of TY plus each of
    those days' LY-aligned counterpart, so every detail metric has a
    calendar-true comparison inside the seeded range."""
    ty = [LATEST_COMPLETE - dt.timedelta(days=i) for i in range(DETAIL_DAYS)]
    days = set(ty)
    for d in ty:
        ly, _ = cal.ly_aligned_date(d)
        days.add(ly)
    return sorted(days)


# -- calendar --------------------------------------------------------------

def gen_calendar(cal):
    rows = []
    day = CAL_START
    while day <= CAL_END:
        fy, period, week, dow = cal.coordinates(day)
        ly, restated = cal.ly_aligned_date(day)
        wk_start = cal.fy_start_date(fy) + dt.timedelta(days=(week - 1) * 7)
        quarter = cal.period_for_date(day).quarter
        rows.append((day.isoformat(), fy, period, week, dow, holiday_code(day),
                     ly.isoformat(), 1 if restated else 0, quarter,
                     wk_start.isoformat(),
                     (wk_start + dt.timedelta(days=6)).isoformat()))
        day += dt.timedelta(days=1)
    return rows


# -- day-grain facts -------------------------------------------------------

def gen_day_facts(cal, entities):
    """sales_day + traffic_day for the full history.

    Returns (sales_rows, traffic_rows, sales_index) where sales_index is
    {(iso_date, entity_id): dict} — the in-memory view every later generator
    allocates against, so nothing downstream can invent money."""
    sales_rows, traffic_rows, index = [], [], {}
    day = SALES_START
    while day <= SALES_END:
        fy, period, week, dow = cal.coordinates(day)
        iso = day.isoformat()
        for e in entities:
            eid = e["entity_id"]
            if not is_open_on(e, day) or is_missing(eid, day):
                continue
            net = base_sales(e, day, fy, period, dow)
            demand = shipped = returns = None
            if e["channel"] == "ECOM":
                demand, shipped, returns = ecom_series(e, day, net, cal)
                net = demand
            net = round(net, 2)
            txns, units = txn_units(e, net)
            gross, disc, ret = gross_discount_return(e, day, net)
            posted = iso + "T06:30:00" + TZ_SUFFIX
            sales_rows.append((iso, eid, net, txns, units, demand, shipped,
                               returns, gross, disc, ret, posted))
            index[(iso, eid)] = dict(net_sales=net, transactions=txns,
                                     units=units, gross_sales=gross,
                                     discount_sales=disc, return_sales=ret)
            if e["channel"] == "STORE" and (eid, day) not in TRAFFIC_MISSING:
                traffic_rows.append((iso, eid, traffic_of(e, day, txns)))
        day += dt.timedelta(days=1)
    return sales_rows, traffic_rows, index


# -- plan at each brand's native grain (D12 / BR-19) -----------------------

def gen_plan(cal, entities):
    """Lumière plans by DAY, Atelier Noir by WEEK, Botanica not at all.

    Deviation from PRD §3, noted in the build report: the two ECOM channels
    plan at DAY grain for the WHOLE channel rather than for Lumière-brand
    demand only. Planning a fraction of a channel and then measuring the whole
    channel against it produces a meaningless attainment %; whole-channel keeps
    the number honest and still exercises all three grains."""
    rows = []
    for e in sorted(entities, key=lambda x: x["entity_id"]):
        grain = ("DAY" if e["channel"] == "ECOM"
                 else BRAND_BY_ID[e["brand_id"]]["plan_grain"])
        if grain == "NONE":
            continue
        day = SALES_START
        week_acc = {}
        while day <= CAL_END:
            fy, period, week, dow = cal.coordinates(day)
            if is_open_on(e, day):
                mean = round(daily_mean(e, fy, period, dow, day), 2)
                if grain == "DAY":
                    rows.append((e["entity_id"], "DAY", day.isoformat(),
                                 day.isoformat(), fy, week, mean))
                else:
                    wk_start = cal.fy_start_date(fy) + dt.timedelta(days=(week - 1) * 7)
                    key = (fy, week, wk_start)
                    week_acc[key] = week_acc.get(key, 0.0) + mean
            day += dt.timedelta(days=1)
        for (fy, week, wk_start), total in sorted(week_acc.items()):
            rows.append((e["entity_id"], "WEEK", wk_start.isoformat(),
                         (wk_start + dt.timedelta(days=6)).isoformat(),
                         fy, week, round(total, 2)))
    return rows


# -- hourly (BR-17: Σ hourly = the day's posted total) ---------------------

def gen_traffic_hour(cal, entities, sales_index, traffic_index, dates):
    rows = []
    stores = [e for e in entities if e["channel"] == "STORE"]
    for day in dates:
        iso = day.isoformat()
        dow = dow_1sun(day)
        for e in stores:
            eid = e["entity_id"]
            row = sales_index.get((iso, eid))
            if row is None:
                continue
            traffic = traffic_index.get((iso, eid))
            w = hour_weights(eid, day, dow)
            wl = [(h, w[h]) for h in HOURS]
            cents = allocate(int(round(row["net_sales"] * 100)), wl)
            txn = allocate(row["transactions"], wl)
            trf = allocate(traffic, wl) if traffic is not None else {}
            for h in HOURS:
                rows.append((iso, eid, h, trf.get(h, 0),
                             round(cents.get(h, 0) / 100.0, 2), txn.get(h, 0)))
    return rows


# -- SKU grain (BR-11: Σ sales_line = sales_day, by construction) ----------

def sku_day_mult(prod, day, cache):
    key = (prod["sku_id"], day)
    if key in cache:
        return cache[key]
    launch = D.fromisoformat(prod["launch_date"])
    if day < launch:
        m = 0.0
    else:
        m = 0.70 + 0.60 * u(prod["sku_id"], day.isoformat(), "m")
        age = (day - launch).days
        if age < 45:                                  # launch ramp
            m *= 0.35 + 0.65 * (age / 45.0)
        if prod["sku_id"] == BREAKOUT_SKU:
            m *= BREAKOUT_MULT                        # storyline 5
        if prod["category"] == SLIDE_CATEGORY and SLIDE_START <= day <= LATEST_COMPLETE:
            m *= SLIDE_CATEGORY_MULT                  # storyline 4
            if prod["sku_id"] in SLIDE_SKUS:
                m *= SLIDE_SKU_MULT
    cache[key] = m
    return m


def gen_sales_lines(entities, products, sales_index, dates):
    prod = {p["sku_id"]: p for p in products}
    by_brand = {}
    for p in products:
        by_brand.setdefault(p["brand_id"], []).append(p["sku_id"])
    for k in by_brand:
        by_brand[k].sort()
    all_skus = sorted(prod)

    base_w, assort = {}, {}
    for e in entities:
        skus = assortment_of(e, by_brand, all_skus)
        assort[e["entity_id"]] = skus
        for s in skus:
            base_w[(e["entity_id"], s)] = 0.40 + 1.60 * u(e["entity_id"], s, "w")

    mult_cache, rows = {}, []
    for day in dates:
        iso = day.isoformat()
        for e in entities:
            eid = e["entity_id"]
            row = sales_index.get((iso, eid))
            if row is None:
                continue
            fx = FX_CAD_PER_USD if e["currency"] == "CAD" else 1.0
            wl = []
            for s in assort[eid]:
                m = sku_day_mult(prod[s], day, mult_cache)
                if m > 0.0:
                    wl.append((s, base_w[(eid, s)] * m))
            if not wl:
                continue
            unit_alloc = allocate(row["units"], wl)
            vw = [(s, n * prod[s]["unit_price"] * fx)
                  for s, n in sorted(unit_alloc.items()) if n > 0]
            if not vw:
                continue
            cent_alloc = allocate(int(round(row["net_sales"] * 100)), vw)
            for s, n in vw:
                rows.append((iso, eid, s,
                             round(cent_alloc.get(s, 0) / 100.0, 2),
                             unit_alloc[s]))
    return rows


# -- customer file (BR-12: new-to-file derives ONLY from first_purchase_date)

LEGACY_CUSTOMERS = 10000
NEW_BUYER_BASKET_INDEX = 0.85      # acquiring baskets run below the fleet AST


def gen_customers(entities, sales_index, dates):
    """The customer file. Inside the detail window a day's new buyers are an
    ALLOCATION of that entity/day's posted transactions and net sales, so the
    New Customer block (#34) can never exceed the day it belongs to (BR-9),
    and new-to-file is a pure function of first_purchase_date (BR-12)."""
    rows = []
    ent_by_id = {e["entity_id"]: e for e in entities}

    # A legacy base so the file has depth before the detail window opens and
    # omni orders always have an existing customer to belong to. Legacy rows
    # carry no basket (their acquiring day is outside the seeded detail grain).
    window_start = dates[0]
    legacy_span = (window_start - dt.timedelta(days=1) - SALES_START).days
    homes = sorted(e["entity_id"] for e in entities)
    for i in range(LEGACY_CUSTOMERS):
        cid = "L%06d" % (i + 1)
        first = SALES_START + dt.timedelta(days=int(u(cid, "d") * legacy_span))
        home = homes[int(u(cid, "h") * len(homes))]
        e = ent_by_id[home]
        if not is_open_on(e, first):
            first = max(first, open_date_of(e))
        rows.append((cid, first.isoformat(), home, e["affiliate_id"], 0.0, 0))

    seq = 0
    for day in dates:
        iso = day.isoformat()
        for e in sorted(entities, key=lambda x: x["entity_id"]):
            eid = e["entity_id"]
            row = sales_index.get((iso, eid))
            if row is None:
                continue
            n_new = int(round(row["transactions"] * ntf_share(eid, day)))
            if n_new <= 0:
                continue
            share = (n_new / float(row["transactions"])) * NEW_BUYER_BASKET_INDEX
            cids = ["C%06d" % (seq + j + 1) for j in range(n_new)]
            seq += n_new
            wl = [(c, 0.5 + 1.0 * u(c, "basket")) for c in cids]
            cents = allocate(int(round(row["net_sales"] * share * 100)), wl)
            units = allocate(int(round(row["units"] * share)), wl)
            for c in cids:
                rows.append((c, iso, eid, e["affiliate_id"],
                             round(cents.get(c, 0) / 100.0, 2),
                             max(1, units.get(c, 0))))
    return rows


# -- omni orders (BR-9: attribution, never addition) -----------------------

# Volume shares (PRD §10 open questions), expressed against the sales that
# ALREADY exist in sales_day. Nothing here creates money: `attributed_to`
# names the entity whose posted net sales this order is a slice of.
OMNI_ECOM_SHARE = {"BOPIS": 0.08, "RTD": 0.03}
OMNI_STORE_SHARE = {"OOFIS": 0.02, "CR": 0.015}
OMNI_AOV_USD = {"BOPIS": 95.0, "RTD": 110.0, "OOFIS": 105.0, "CR": 88.0}
OMNI_PREFIX = {"BOPIS": "BP", "RTD": "RT", "OOFIS": "OF", "CR": "CR"}
RTD_DELIVERY_RATE = 0.94
OOFIS_COMPLETION_RATE = 0.90
CR_UPSELL_RATE = 0.15
NON_COMPLETED = ("in_progress", "partial", "cancelled")


class CustomerPool(object):
    """Deterministic customer picker: only customers that already exist on the
    order date are eligible, so omni buyer counts can never contradict the
    customer file (BR-12)."""

    def __init__(self, customer_rows):
        self.by_aff = {}
        for cid, first, _home, aff, _b, _un in customer_rows:
            self.by_aff.setdefault(aff, []).append((first, cid))
        self.dates = {}
        for aff in self.by_aff:
            self.by_aff[aff].sort()
            self.dates[aff] = [t[0] for t in self.by_aff[aff]]

    def pick(self, aff, day_iso, *salt):
        lst = self.by_aff[aff]
        n = bisect.bisect_right(self.dates[aff], day_iso) or len(lst)
        return lst[int(u(*salt) * n)][1]


def _completion_rate(order_type, store, day):
    if order_type == "BOPIS":
        if (store["region"] == PICKUP_GAP_REGION
                and PICKUP_GAP_START <= day <= LATEST_COMPLETE):
            return PICKUP_RATE_GAP           # storyline 2
        return PICKUP_RATE_BASE
    if order_type == "RTD":
        return RTD_DELIVERY_RATE
    if order_type == "OOFIS":
        return OOFIS_COMPLETION_RATE
    return CR_CONV_AFTER if day >= CR_STEP_DATE else CR_CONV_BASE   # storyline 8


def _nominal_rate(order_type, day):
    """The family's completion rate ignoring per-region storylines — used only
    to SIZE the all-inclusive order count so the recognized slice lands on its
    target share of existing sales."""
    if order_type == "BOPIS":
        return PICKUP_RATE_BASE
    if order_type == "RTD":
        return RTD_DELIVERY_RATE
    if order_type == "OOFIS":
        return OOFIS_COMPLETION_RATE
    return CR_CONV_AFTER if day >= CR_STEP_DATE else CR_CONV_BASE


def _upsell_rate(order_type, store, day):
    if order_type == "CR":
        return CR_UPSELL_RATE
    if order_type != "BOPIS":
        return 0.0
    if store["entity_id"] == UPSELL_STAR and day >= UPSELL_STAR_START:
        return UPSELL_STAR_RATE              # storyline 1
    return UPSELL_BASE_RATE


def gen_omni(entities, sales_index, dates, pool):
    stores_by_aff = {}
    for e in entities:
        if e["channel"] == "STORE":
            stores_by_aff.setdefault(e["affiliate_id"], []).append(e)
    for a in stores_by_aff:
        stores_by_aff[a].sort(key=lambda e: e["entity_id"])

    # Orders are generated on their CREATED date (the all-inclusive basis) and
    # recognized later on fulfilled_date. The generation set is therefore the
    # detail window widened backwards by the maximum fulfilment lag, so every
    # day inside the window has a COMPLETE recognized series rather than one
    # truncated at the window edge.
    gen_days = sorted(set(dates)
                      | set(d - dt.timedelta(days=k)
                            for d in dates for k in (1, 2))
                      | set())
    gen_days = [d for d in gen_days if d >= SALES_START]

    counters = {k: 0 for k in OMNI_PREFIX}
    rows = []
    for day in gen_days:
        iso = day.isoformat()
        for aff in ("CA", "US"):
            fx = FX_CAD_PER_USD if CURRENCY_OF_AFFILIATE[aff] == "CAD" else 1.0
            ecom_id = "ECOM-%s" % aff
            ecom_row = sales_index.get((iso, ecom_id))
            ecom_net = ecom_row["net_sales"] if ecom_row else 0.0
            open_stores = [e for e in stores_by_aff[aff]
                           if (iso, e["entity_id"]) in sales_index]
            if not open_stores:
                continue
            store_net = sum(sales_index[(iso, e["entity_id"])]["net_sales"]
                            for e in open_stores)
            weights = [(e["entity_id"],
                        sales_index[(iso, e["entity_id"])]["net_sales"])
                       for e in open_stores]
            by_id = {e["entity_id"]: e for e in open_stores}

            for otype in ("BOPIS", "CR", "OOFIS", "RTD"):
                if otype in OMNI_ECOM_SHARE:
                    target = ecom_net * OMNI_ECOM_SHARE[otype]
                    attributed = ecom_id
                else:
                    target = store_net * OMNI_STORE_SHARE[otype]
                    attributed = None            # the fulfilling store
                if otype == "BOPIS" and day == OMNI_HEAVY_DAY:
                    target *= OMNI_HEAVY_MULT    # storyline 7
                aov = OMNI_AOV_USD[otype] * fx
                # Size the ALL-INCLUSIVE order count so that the RECOGNIZED
                # slice lands on the family's target share of existing sales.
                n_total = int(round(target / aov / _nominal_rate(otype, day)))
                if n_total <= 0:
                    continue
                per_store = allocate(n_total, weights)
                for sid in sorted(per_store):
                    n_all = per_store[sid]
                    if n_all <= 0:
                        continue
                    store = by_id[sid]
                    rate = _completion_rate(otype, store, day)
                    up_rate = _upsell_rate(otype, store, day)
                    for i in range(n_all):
                        counters[otype] += 1
                        oid = "%s-%06d" % (OMNI_PREFIX[otype], counters[otype])
                        sales = round(aov * (0.55 + 0.90 * u(oid, "v")), 2)
                        items = 1 + int(3 * u(oid, "i"))
                        # Completion is decided PER ORDER, not by rounding a
                        # per-store count: with 2–3 orders a door, rounding
                        # 88% up to 100% would erase the very divergence the
                        # dual-basis rule exists to show (BR-10).
                        if u(oid, "cmp") < rate:
                            status = "completed"
                            lag = int(3 * u(oid, "lag"))
                            created = iso
                            fulfilled = (day + dt.timedelta(days=lag)).isoformat()
                            if u(oid, "up") < up_rate:
                                up_sales = round((16.0 + 44.0 * u(oid, "ups")) * fx, 2)
                                up_items = 1 + int(2 * u(oid, "upi"))
                            else:
                                up_sales, up_items = 0.0, 0
                        else:
                            status = NON_COMPLETED[int(3 * u(oid, "st"))]
                            created, fulfilled = iso, None
                            up_sales, up_items = 0.0, 0
                        rows.append((
                            oid, otype, sid,
                            pool.pick(aff, iso, oid, "cust"),
                            created, fulfilled, status, sales, items,
                            up_sales, up_items, attributed or sid))
    return rows


# -- BORIS return events (omni BRD #36–44, ex-#40) -------------------------

BORIS_SHARE_OF_ECOM_RETURNS = 0.30
BORIS_AVG_RETURN_USD = 75.0


def gen_return_events(entities, sales_index, ecom_returns, dates, pool):
    stores_by_aff = {}
    for e in entities:
        if e["channel"] == "STORE":
            stores_by_aff.setdefault(e["affiliate_id"], []).append(e)
    for a in stores_by_aff:
        stores_by_aff[a].sort(key=lambda e: e["entity_id"])

    counter, rows = 0, []
    for day in dates:
        iso = day.isoformat()
        for aff in ("CA", "US"):
            fx = FX_CAD_PER_USD if CURRENCY_OF_AFFILIATE[aff] == "CAD" else 1.0
            ret_total = ecom_returns.get((iso, "ECOM-%s" % aff), 0.0) \
                * BORIS_SHARE_OF_ECOM_RETURNS
            open_stores = [e for e in stores_by_aff[aff]
                           if (iso, e["entity_id"]) in sales_index]
            if not open_stores or ret_total <= 0:
                continue
            avg = BORIS_AVG_RETURN_USD * fx
            n_total = int(round(ret_total / avg))
            if n_total <= 0:
                continue
            weights = []
            for e in open_stores:
                w = sales_index[(iso, e["entity_id"])]["net_sales"]
                if e["entity_id"] == BORIS_SAVE_STORE and day >= BORIS_SAVE_START:
                    w *= 2.2                   # storyline 3: high return volume
                weights.append((e["entity_id"], w))
            per_store = allocate(n_total, weights)
            for sid in sorted(per_store):
                save_rate = (BORIS_SAVE_RATE_STAR
                             if sid == BORIS_SAVE_STORE and day >= BORIS_SAVE_START
                             else BORIS_SAVE_RATE_BASE)
                for _ in range(per_store[sid]):
                    counter += 1
                    rid = "BR-%06d" % counter
                    amount = round(avg * (0.50 + 1.00 * u(rid, "a")), 2)
                    items = 1 + int(2 * u(rid, "it"))
                    if u(rid, "sv") < save_rate:
                        saved, saved_sales = 1, round(
                            amount * (0.80 + 0.90 * u(rid, "ss")), 2)
                    else:
                        saved, saved_sales = 0, 0.0
                    rows.append((rid, iso, sid, pool.pick(aff, iso, rid, "cust"),
                                 amount, items, saved_sales, saved))
    return rows

# =========================================================================
# SECTION: build
# =========================================================================
def build(db_path=DB_PATH):
    """Build the whole database. Returns (conn, entities, products, stats)."""
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    with open(SCHEMA_PATH, "r", encoding="utf-8") as fh:
        conn.executescript(fh.read())
    cal = NRFCalendar()

    entities = build_entities()
    products = build_products()
    dates = detail_dates(cal)

    conn.executemany(
        "INSERT INTO brand VALUES (?,?,?,?,?)",
        [(b["brand_id"], b["name"], b["positioning"],
          "|".join(b["categories"]), b["plan_grain"]) for b in BRANDS])
    conn.executemany(
        "INSERT INTO affiliate VALUES (?,?,?)",
        [(a["affiliate_id"], a["name"], a["currency"]) for a in AFFILIATES])
    conn.executemany(
        "INSERT INTO fx_rate VALUES (?,?,?)",
        [(f["currency"], f["units_per_usd"], f["basis"]) for f in FX_RATES])
    conn.executemany(
        "INSERT INTO district VALUES (?,?,?,?)",
        [(d["district_id"], d["name"], d["region"], d["affiliate_id"])
         for d in DISTRICTS])
    conn.executemany(
        "INSERT INTO stores VALUES (:entity_id,:store_number,:name,:channel,"
        ":region,:open_date,:close_date,:remodel_start,:remodel_end,"
        ":rentable_sf,:target_sales_psf,:annual_volume,:brand_id,:district_id,"
        ":affiliate_id,:currency,:state_province,:city,:store_status)", entities)
    conn.executemany(
        "INSERT INTO product VALUES (:sku_id,:name,:brand_id,:category,"
        ":launch_date,:unit_price)", products)
    conn.executemany("INSERT INTO calendar VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                     gen_calendar(cal))

    sales_rows, traffic_rows, sales_index = gen_day_facts(cal, entities)
    conn.executemany(
        "INSERT INTO sales_day VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", sales_rows)
    conn.executemany("INSERT INTO traffic_day VALUES (?,?,?)", traffic_rows)
    conn.executemany("INSERT INTO plan_day VALUES (?,?,?,?,?,?,?)",
                     gen_plan(cal, entities))

    traffic_index = {(r[0], r[1]): r[2] for r in traffic_rows}
    conn.executemany(
        "INSERT INTO traffic_hour VALUES (?,?,?,?,?,?)",
        gen_traffic_hour(cal, entities, sales_index, traffic_index, dates))

    line_rows = gen_sales_lines(entities, products, sales_index, dates)
    conn.executemany("INSERT INTO sales_line VALUES (?,?,?,?,?)", line_rows)

    customer_rows = gen_customers(entities, sales_index, dates)
    conn.executemany("INSERT INTO customer VALUES (?,?,?,?,?,?)", customer_rows)
    pool = CustomerPool(customer_rows)

    conn.executemany(
        "INSERT INTO omni_order VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        gen_omni(entities, sales_index, dates, pool))

    ecom_returns = {(r[0], r[1]): (r[7] or 0.0) for r in sales_rows}
    conn.executemany(
        "INSERT INTO return_event VALUES (?,?,?,?,?,?,?,?)",
        gen_return_events(entities, sales_index, ecom_returns, dates, pool))

    conn.commit()
    stats = dict(detail_start=dates[0].isoformat(),
                 detail_end=dates[-1].isoformat(), detail_days=len(dates))
    return conn, entities, products, stats

# =========================================================================
# SECTION: storyline assertions
# =========================================================================
class Assertions(object):
    """Named, counted assertions in the NFR-4 style.

    Every failure message says WHICH storyline or rule broke, WHICH rows are
    involved, and WHAT to change to fix it. A green run prints the count so a
    reviewer can see the assertions ran rather than trusting that they exist.
    """

    def __init__(self):
        self.passed = []

    def require(self, tag, ok, detail, fix):
        if not ok:
            raise AssertionError(
                "%s did not hold.\n  what broke: %s\n  fix: %s" % (tag, detail, fix))
        self.passed.append(tag)

    def count(self):
        return len(self.passed)


def assert_all(conn, cal):
    """Every planted storyline and every reconciliation rule, checked against
    the database that was just written."""
    from flash import catalog, omni, customer, merch     # noqa: E402
    A = Assertions()
    cur = conn.cursor()

    def q(sql, args=()):
        return cur.execute(sql, args).fetchall()

    da = catalog.DataAccess(conn, cal)
    day = LATEST_COMPLETE
    detail = detail_dates(cal)
    ty_detail = [d for d in detail if d > LATEST_COMPLETE - dt.timedelta(days=DETAIL_DAYS)]

    # =====================================================================
    # Inherited storylines (ported from the executive flash seed)
    # =====================================================================

    raw_ly, _ = cal.ly_aligned_date(D(2026, 7, 4))
    hol_ly = ly_holiday_aligned_date(D(2026, 7, 4))
    A.require("STORYLINE I1 'holiday shift'",
              hol_ly is not None and raw_ly != hol_ly,
              "July 4 2026 week/day-aligned LY is %s and holiday-aligned LY is "
              "%s — they must differ for the dual-comp disclosure to have "
              "anything to disclose" % (raw_ly, hol_ly),
              "check flash/calendar.py holidays_for_calendar_year — it is "
              "ported verbatim and must not be edited")

    se_comp = da.comp_pct(day, region=SOFT_REGION)
    contribs = da.contribution_to_comp_gap(day, region=SOFT_REGION)
    A.require("STORYLINE I2 'soft Southeast'",
              se_comp is not None and se_comp < 0,
              "%s day comp on %s is %r (want < 0); comp members %s"
              % (SOFT_REGION, day, se_comp, da.comp_set(day, region=SOFT_REGION)),
              "lower SOFT_MULT or move SOFT_START earlier in seed.py")
    A.require("STORYLINE I2b 'soft Southeast top movers'",
              set(c["entity_id"] for c in contribs[:2]) == set(SOFT_STORES),
              "top-2 adverse movers are %s, expected %s"
              % ([c["entity_id"] for c in contribs[:2]], list(SOFT_STORES)),
              "lower SOFT_MULT so the planted doors dominate the gap")

    n = q("SELECT COUNT(*) FROM sales_day WHERE entity_id=? AND date>=?",
          (REMODEL_STORE, REMODEL_START.isoformat()))[0][0]
    A.require("STORYLINE I3 'remodel closure'",
              n == 0 and not da.comp_eligible(REMODEL_STORE, day),
              "%s has %d sales_day rows on/after %s and comp_eligible=%s "
              "(want 0 rows, not comp)"
              % (REMODEL_STORE, n, REMODEL_START, da.comp_eligible(REMODEL_STORE, day)),
              "check is_open_on()/REMODEL_START in seed.py")

    present = set(r[0] for r in q("SELECT entity_id FROM sales_day WHERE date=?",
                                  (LATE_DAY.isoformat(),)))
    prev = set(r[0] for r in q("SELECT entity_id FROM sales_day WHERE date=?",
                               (LATE_DAY_PREV.isoformat(),)))
    A.require("STORYLINE I4 'late posters'",
              LATE_BOTH not in present and LATE_ONE not in present
              and LATE_BOTH not in prev,
              "%s/%s present on %s = %s/%s; %s present on %s = %s"
              % (LATE_BOTH, LATE_ONE, LATE_DAY, LATE_BOTH in present,
                 LATE_ONE in present, LATE_BOTH, LATE_DAY_PREV, LATE_BOTH in prev),
              "check is_missing() in seed.py")
    lp = da.late_posters(LATE_DAY)
    A.require("STORYLINE I4b 'late-poster escalation'",
              any(r["entity_id"] == LATE_BOTH and r["escalate"] for r in lp),
              "%s is not flagged escalating on %s; late_posters returned %s"
              % (LATE_BOTH, LATE_DAY, [(r["entity_id"], r["consecutive_days"]) for r in lp]),
              "check LATE_DAY_PREV in seed.py is_missing()")

    r = q("SELECT demand_sales, shipped_sales FROM sales_day "
          "WHERE date=? AND entity_id=?",
          (ECOM_MATURATION_DAY.isoformat(), ECOM_MATURATION_ENTITY))[0]
    ly, _ = cal.ly_aligned_date(ECOM_MATURATION_DAY)
    ly_demand = q("SELECT demand_sales FROM sales_day WHERE date=? AND entity_id=?",
                  (ly.isoformat(), ECOM_MATURATION_ENTITY))[0][0]
    A.require("STORYLINE I5 'e-comm maturation'",
              r[0] < ly_demand < r[1],
              "demand %.0f, LY demand %.0f, shipped %.0f (want demand < LY < "
              "shipped so the day looks soft and settles positive)"
              % (r[0], ly_demand, r[1]),
              "adjust the 0.92/1.05 factors in ecom_series()")

    A.require("STORYLINE I6 'new store'",
              not da.comp_eligible(NEW_STORE, day)
              and da.sales_row(NEW_STORE, day) is not None,
              "%s comp_eligible=%s, posted=%s (want non-comp but present in "
              "the total)" % (NEW_STORE, da.comp_eligible(NEW_STORE, day),
                              da.sales_row(NEW_STORE, day) is not None),
              "check the roster commencement_date for the new door")

    att = da.plan_attainment(day, entity_id=BRIGHT_STORE)
    A.require("STORYLINE I7 'plan-beat bright spot'",
              att is not None and att > 1.05,
              "%s plan attainment on %s is %r (want > 1.05)"
              % (BRIGHT_STORE, day, att),
              "raise BRIGHT_MULT or move BRIGHT_START earlier")

    # =====================================================================
    # PRD §7 storylines 1–14
    # =====================================================================

    lb = omni.upsell_leaderboard(da, day, window_days=14)
    fleet_attach = (sum(r["attached"] for r in lb) / float(sum(r["picked_up"] for r in lb)))
    A.require("STORYLINE 1 'BOPIS upsell champion'",
              lb and lb[0]["entity_id"] == UPSELL_STAR
              and lb[0]["attach_pct"] >= fleet_attach * 1.4,
              "leaderboard leader is %s at %.1f%% attach against a fleet "
              "%.1f%% (want %s clear of the fleet by 1.4x)"
              % (lb[0]["entity_id"] if lb else None,
                 100 * lb[0]["attach_pct"] if lb else 0, 100 * fleet_attach, UPSELL_STAR),
              "raise UPSELL_STAR_RATE or lower UPSELL_BASE_RATE in seed.py")

    pe = omni.pickup_execution(da, day, window_days=14)
    worst = pe["regions"][0]
    A.require("STORYLINE 2 'BOPIS execution gap'",
              worst["region"] == PICKUP_GAP_REGION
              and worst["pickup_rate"] <= pe["fleet_pickup_rate"] - 0.10,
              "worst pickup region over 14 days is %s at %.1f%% against a "
              "fleet %.1f%% (want %s, at least 10 pts adverse)"
              % (worst["region"], 100 * worst["pickup_rate"],
                 100 * pe["fleet_pickup_rate"], PICKUP_GAP_REGION),
              "lower PICKUP_RATE_GAP in seed.py")
    pe_wk1 = omni.pickup_execution(da, day, window_days=7)
    pe_wk2 = omni.pickup_execution(da, day - dt.timedelta(days=7), window_days=7)
    A.require("STORYLINE 2b 'gap runs two weeks'",
              pe_wk1["regions"][0]["region"] == PICKUP_GAP_REGION
              and pe_wk2["regions"][0]["region"] == PICKUP_GAP_REGION,
              "worst region week 1 = %s, week 2 = %s (want %s both weeks)"
              % (pe_wk1["regions"][0]["region"], pe_wk2["regions"][0]["region"],
                 PICKUP_GAP_REGION),
              "move PICKUP_GAP_START at least 14 days before LATEST_COMPLETE")

    bl = omni.boris_leaderboard(da, day, window_days=14)
    fleet_save = (sum(r["saves"] for r in bl) / float(sum(r["returns"] for r in bl)))
    star = next((r for r in bl if r["entity_id"] == BORIS_SAVE_STORE), None)
    A.require("STORYLINE 3 'BORIS save story'",
              star is not None and bl[0]["entity_id"] == BORIS_SAVE_STORE
              and star["save_rate"] >= fleet_save * 1.6,
              "top saved-sales door is %s; %s save rate %.1f%% vs fleet %.1f%%"
              % (bl[0]["entity_id"] if bl else None, BORIS_SAVE_STORE,
                 100 * star["save_rate"] if star else 0, 100 * fleet_save),
              "raise BORIS_SAVE_RATE_STAR or the LB-014 return-volume weight")

    slide = merch.category_slide_run(da, day, SLIDE_CATEGORY)
    A.require("STORYLINE 4 'Fragrance category slide'",
              slide["consecutive_negative_days"] >= 10,
              "%s has comped negative for %d consecutive days ending %s "
              "(want >= 10)" % (SLIDE_CATEGORY, slide["consecutive_negative_days"], day),
              "lower SLIDE_CATEGORY_MULT or move SLIDE_START earlier")
    mv = merch.sku_movers_window(da, day, "WTD", n=6, category=SLIDE_CATEGORY)
    worst_skus = set(r["sku_id"] for r in mv["bottom"])
    A.require("STORYLINE 4b 'slide drills to 3 SKUs'",
              set(SLIDE_SKUS).issubset(worst_skus),
              "WTD bottom Fragrance movers are %s; the planted trio %s is not "
              "fully inside it" % (sorted(worst_skus), list(SLIDE_SKUS)),
              "lower SLIDE_SKU_MULT in seed.py")

    hits = 0
    for i in range(14):
        d = day - dt.timedelta(days=i)
        top = merch.sku_movers(da, d, n=10)["top"]
        if any(r["sku_id"] == BREAKOUT_SKU for r in top):
            hits += 1
    launch_age = (day - BREAKOUT_LAUNCH).days
    A.require("STORYLINE 5 'SKU breakout'",
              hits >= 8 and launch_age < 90,
              "%s (launched %s, %d days ago) is in the top-10 movers on %d of "
              "the last 14 days (want >= 8, and < 90 days old)"
              % (BREAKOUT_SKU, BREAKOUT_LAUNCH, launch_age, hits),
              "raise BREAKOUT_MULT or move BREAKOUT_LAUNCH later")

    ntf = customer.ntf_exception(da, day, "WTD", entity_id=NTF_DIP_ENTITY)
    A.require("STORYLINE 6 'new-to-file dip'",
              ntf is not None and ntf["fires"],
              "new-to-file WTD for %s is %.2f%% against a baseline %.2f%% "
              "(gap %.2f pts, threshold %.0f pts)"
              % (NTF_DIP_ENTITY, 100 * ntf["pct_new_to_file"], 100 * ntf["baseline"],
                 100 * ntf["gap_pts"], 100 * ntf["threshold_pts"]) if ntf else "no data",
              "lower NTF_DIP_SHARE or widen NTF_DIP_START in seed.py")

    inv = omni.assert_headline_invariant(da, OMNI_HEAVY_DAY)
    heavy = omni.family_day(da, "BOPIS", OMNI_HEAVY_DAY)["recognized"]["sales"]
    trail = [omni.family_day(da, "BOPIS", OMNI_HEAVY_DAY - dt.timedelta(days=7 * k)
                             )["recognized"]["sales"] for k in (1, 2, 3, 4)]
    trail_avg = sum(trail) / len(trail)
    A.require("STORYLINE 7 'omni invariance demo day'",
              inv["identical"] and not inv["attributed_exceeds_headline"]
              and heavy >= trail_avg * 1.6,
              "on %s BOPIS recognized is %.0f against a trailing same-weekday "
              "average of %.0f (want >= 1.6x) and headline omni-on/off = %s/%s"
              % (OMNI_HEAVY_DAY, heavy, trail_avg, inv["headline_omni_on"],
                 inv["headline_omni_off"]),
              "raise OMNI_HEAVY_MULT in seed.py")

    before = omni.family_day(da, "CR", CR_STEP_DATE - dt.timedelta(days=7))["completion_rate"]
    after = omni.family_day(da, "CR", CR_STEP_DATE + dt.timedelta(days=7))["completion_rate"]
    A.require("STORYLINE 8 'C&R conversion win'",
              before is not None and after is not None and after - before >= 0.15,
              "C&R conversion moved %.1f%% -> %.1f%% across %s (want >= 15 pts)"
              % (100 * (before or 0), 100 * (after or 0), CR_STEP_DATE),
              "widen the gap between CR_CONV_BASE and CR_CONV_AFTER")

    ty_t = ly_t = ty_x = ly_x = 0
    d = CONV_START
    while d <= day:
        t = da.traffic_of(CONV_STORE, d)
        row = da.sales_row(CONV_STORE, d)
        lyd = da.ly_date(d)
        lt = da.traffic_of(CONV_STORE, lyd)
        lrow = da.sales_row(CONV_STORE, lyd)
        if t and row and lt and lrow:
            ty_t += t
            ty_x += row["transactions"]
            ly_t += lt
            ly_x += lrow["transactions"]
        d += dt.timedelta(days=1)
    ty_conv, ly_conv = ty_x / float(ty_t), ly_x / float(ly_t)
    A.require("STORYLINE 9 'traffic up, conversion down'",
              ty_t > ly_t and ty_conv < ly_conv,
              "%s over %s..%s: traffic %d vs LY %d, conversion %.2f%% vs LY "
              "%.2f%% (want traffic up AND conversion down)"
              % (CONV_STORE, CONV_START, day, ty_t, ly_t, 100 * ty_conv, 100 * ly_conv),
              "lower CONV_RATE_MULT (drives traffic up) or CONV_SALES_MULT")

    prof = da.hourly_profile(HOURLY_STORE, HOURLY_DAY, weeks=4)
    midday_delta = sum(prof["delta_share"][h] for h in (12, 13, 14, 15))
    A.require("STORYLINE 10 'lost midday peak'",
              prof["weeks"] >= 3 and midday_delta <= -0.05,
              "%s on %s: midday (12–15h) share is %.1f pts below its own "
              "trailing %d-week curve (want at least 5 pts below)"
              % (HOURLY_STORE, HOURLY_DAY, 100 * midday_delta, prof["weeks"]),
              "deepen the midday multiplier in hour_weights()")

    lum_w = da.comp_pct(day, region=DIVERGE_REGION, brand_id="LUM")
    atn_w = da.comp_pct(day, region=DIVERGE_REGION, brand_id="ATN")
    A.require("STORYLINE 11 'brand divergence in one region'",
              lum_w is not None and atn_w is not None and lum_w > 0 > atn_w,
              "in %s on %s: Lumière comp %r, Atelier Noir comp %r (want one "
              "positive and one negative on the same day)"
              % (DIVERGE_REGION, day, lum_w, atn_w),
              "lower DIVERGE_MULT or raise BRIGHT_MULT in seed.py")

    ca = catalog.DataAccess(conn, cal, reporting_currency="CAD")
    ca_att = ca.plan_attainment(day, affiliate_id="CA")
    ca_cad = ca.net_sales(day, affiliate_id="CA")
    ca_usd = da.net_sales(day, affiliate_id="CA")
    A.require("STORYLINE 12 'Canada beats plan, smaller in USD'",
              ca_att is not None and ca_att > 1.0
              and abs(ca_usd - ca_cad / FX_CAD_PER_USD) < 0.01 and ca_usd < ca_cad,
              "CA day-grain plan attainment %r; CA net sales CAD %.2f -> USD "
              "%.2f at the seeded rate %.2f"
              % (ca_att, ca_cad, ca_usd, FX_CAD_PER_USD),
              "raise CA_BEAT_MULT or move CA_BEAT_START earlier")

    ps = da.plan_status(day)
    grains = set(ps["grain_mix"])
    bot_plan_rows = q("SELECT COUNT(*) FROM plan_day p JOIN stores s "
                      "USING(entity_id) WHERE s.brand_id='BOT'")[0][0]
    atn_day_rows = q("SELECT COUNT(*) FROM plan_day p JOIN stores s "
                     "USING(entity_id) WHERE s.brand_id='ATN' AND p.grain='DAY'")[0][0]
    A.require("STORYLINE 13 'three plan grains on one page'",
              grains == {"DAY", "WEEK", "NONE"} and bot_plan_rows == 0
              and atn_day_rows == 0,
              "grain mix on %s is %s; Botanica has %d plan rows (want 0); "
              "Atelier Noir has %d DAY rows (want 0)"
              % (day, sorted(grains), bot_plan_rows, atn_day_rows),
              "check gen_plan() and the brand plan_grain values")
    A.require("STORYLINE 13b 'no-plan brand shows no attainment'",
              ps["no_plan"]["attainment"] is None and ps["no_plan"]["entities"] > 0,
              "no-plan bucket on %s: %d entities, attainment %r (want entities "
              "> 0 and attainment None — never a fabricated 100%%)"
              % (day, ps["no_plan"]["entities"], ps["no_plan"]["attainment"]),
              "check plan_status() in flash/catalog.py")

    tree = da.kpi_tree(CONV_STORE, day)
    tc = dict((d_["driver"], d_["contribution"]) for d_ in tree["drivers"])
    A.require("STORYLINE 14 'the tree explains storyline 9'",
              tree["available"] and tc["conversion"] < 0
              and abs(tc["conversion"]) > abs(tc["traffic"]),
              "%s tree on %s: traffic %+.2f, conversion %+.2f, AST %+.2f, gap "
              "%+.2f (want a negative conversion contribution larger in "
              "magnitude than the traffic contribution)"
              % (CONV_STORE, day, tc["traffic"], tc["conversion"], tc["ast"],
                 tree["gap"]),
              "strengthen CONV_RATE_MULT so conversion dominates the gap")
    A.require("STORYLINE 14b 'tree composes exactly (BR-20)'",
              abs(tree["residual_interaction"]) < 0.01,
              "residual interaction is %.4f on %s/%s (want 0 to the cent — "
              "sequential attribution telescopes exactly)"
              % (tree["residual_interaction"], CONV_STORE, day),
              "check kpi_tree()'s sequential decomposition")

    # =====================================================================
    # Reconciliation rules
    # =====================================================================

    bad = q("SELECT COUNT(*) FROM sales_day WHERE "
            "ABS(net_sales-(gross_sales-discount_sales-return_sales))>0.005")[0][0]
    A.require("RULE deck-KPI identity (net = gross - discounts - returns)",
              bad == 0,
              "%d sales_day rows break the identity" % bad,
              "check gross_discount_return() rounding in seed.py")

    bad = q("""SELECT COUNT(*) FROM (
                 SELECT date, entity_id, ROUND(SUM(net_sales),2) s, SUM(units) u
                 FROM sales_line GROUP BY 1,2) x
               JOIN sales_day d ON d.date=x.date AND d.entity_id=x.entity_id
               WHERE ABS(x.s-d.net_sales)>0.005 OR x.u<>d.units""")[0][0]
    orphan = q("""SELECT COUNT(*) FROM (SELECT DISTINCT date, entity_id
                  FROM sales_line) x LEFT JOIN sales_day d
                  ON d.date=x.date AND d.entity_id=x.entity_id
                  WHERE d.date IS NULL""")[0][0]
    A.require("RULE BR-11 SKU lines sum to the day, every day, to the cent",
              bad == 0 and orphan == 0,
              "%d entity/day groups mismatch and %d line groups have no "
              "sales_day parent" % (bad, orphan),
              "check gen_sales_lines()'s allocate() usage — lines are an "
              "allocation of the posted day, never an independent draw")

    bad = q("""SELECT COUNT(*) FROM (
                 SELECT date, entity_id, ROUND(SUM(net_sales),2) s,
                        SUM(transactions) t FROM traffic_hour GROUP BY 1,2) x
               JOIN sales_day d ON d.date=x.date AND d.entity_id=x.entity_id
               WHERE ABS(x.s-d.net_sales)>0.005 OR x.t<>d.transactions""")[0][0]
    A.require("RULE BR-17 hourly sums to the posted day, every day",
              bad == 0,
              "%d entity/day hourly groups do not reconcile to sales_day" % bad,
              "check gen_traffic_hour()'s allocate() usage")

    hrs = q("SELECT MIN(hour), MAX(hour), COUNT(DISTINCT hour) FROM traffic_hour")[0]
    A.require("RULE hourly grain is the declared trading day",
              hrs == (OPEN_HOUR, CLOSE_HOUR, len(HOURS)),
              "hours run %s..%s across %s distinct values (want %s..%s, %s)"
              % (hrs[0], hrs[1], hrs[2], OPEN_HOUR, CLOSE_HOUR, len(HOURS)),
              "check HOURS in seed.py")

    breaks = []
    for d in ty_detail[::7] + [day]:
        for scope in ({}, {"region": "Southeast"}, {"region": "West"},
                      {"brand_id": "LUM"}, {"affiliate_id": "CA"}):
            cs = da.contribution_to_comp_gap(d, **scope)
            if not cs:
                continue
            total = sum(c["contribution"] for c in cs)
            cp = da.comp_pct(d, **scope)
            if cp is None or abs(total - cp) > 1e-9:
                breaks.append((d.isoformat(), scope, total, cp))
    A.require("RULE BR-6 contributions reconcile to the scope comp %",
              not breaks,
              "%d (day, scope) pairs break BR-6, first: %s"
              % (len(breaks), breaks[0] if breaks else None),
              "check contribution_to_comp_gap()'s denominator")

    breaks = []
    for d in ty_detail[::7] + [day]:
        inv = omni.assert_headline_invariant(da, d)
        if not inv["identical"] or inv["attributed_exceeds_headline"]:
            breaks.append((d.isoformat(), inv["omni_attributed"],
                           inv["headline_omni_off"]))
    A.require("RULE BR-9 omni attributes, never adds",
              not breaks,
              "%d days where omni attribution exceeds the headline it is "
              "supposed to partition, first: %s"
              % (len(breaks), breaks[0] if breaks else None),
              "lower the OMNI_ECOM_SHARE / OMNI_STORE_SHARE targets in seed.py")

    breaks = []
    for d in ty_detail[::7] + [day]:
        b = customer.buyers(da, d)
        txn = q("SELECT COALESCE(SUM(transactions),0) FROM sales_day WHERE date=?",
                (d.isoformat(),))[0][0]
        newc = q("SELECT COUNT(*) FROM customer c JOIN sales_day s "
                 "ON s.date=c.first_purchase_date AND s.entity_id=c.home_entity_id "
                 "WHERE c.first_purchase_date=?", (d.isoformat(),))[0][0]
        if b["total_buyers"] != txn or b["new_buyers"] != newc:
            breaks.append((d.isoformat(), b["total_buyers"], txn,
                           b["new_buyers"], newc))
    A.require("RULE BR-12 buyer counts are deterministic and consistent",
              not breaks,
              "%d days where the customer panel disagrees with the underlying "
              "rows, first: %s" % (len(breaks), breaks[0] if breaks else None),
              "check flash/customer.py buyers() and gen_customers()")

    over = q("""SELECT COUNT(*) FROM (
                  SELECT c.first_purchase_date d, c.home_entity_id e,
                         SUM(c.first_basket) b
                  FROM customer c WHERE c.first_basket>0 GROUP BY 1,2) x
                JOIN sales_day s ON s.date=x.d AND s.entity_id=x.e
                WHERE x.b > s.net_sales + 0.005""")[0][0]
    A.require("RULE BR-9 new-customer sales are a slice of the same day",
              over == 0,
              "%d entity/day groups where Σ first_basket exceeds the day's "
              "posted net sales" % over,
              "lower NEW_BUYER_BASKET_INDEX in seed.py")

    for eid, d in sorted(TRAFFIC_MISSING):
        c = da.conversion(d, entity_id=eid)
        A.require("RULE BR-15 missing traffic on %s %s" % (eid, d),
                  c["conversion"] is None and c["available"] is False
                  and eid in c["stores_missing_traffic"],
                  "conversion for %s on %s is %r (want None/unavailable, never "
                  "0%%)" % (eid, d, c["conversion"]),
                  "check traffic_of() returning None and conversion()'s guard")
    c_all = da.conversion(day)
    A.require("RULE BR-15 a missing door does not zero the rollup",
              c_all["conversion"] is not None
              and set(c_all["stores_missing_traffic"]) ==
              set(e for e, d in TRAFFIC_MISSING if d == day),
              "fleet conversion on %s is %r, missing doors %s"
              % (day, c_all["conversion"], c_all["stores_missing_traffic"]),
              "check conversion()'s exclusion of traffic-less doors")

    usd = q("""SELECT ROUND(SUM(d.net_sales),2) FROM sales_day d
               JOIN stores s USING(entity_id)
               WHERE d.date=? AND s.currency='USD'""", (day.isoformat(),))[0][0]
    cad = q("""SELECT ROUND(SUM(d.net_sales),2) FROM sales_day d
               JOIN stores s USING(entity_id)
               WHERE d.date=? AND s.currency='CAD'""", (day.isoformat(),))[0][0]
    A.require("RULE BR-16 currency conversion is explicit and correct",
              abs(da.net_sales(day) - (usd + cad / FX_CAD_PER_USD)) < 0.01,
              "catalog total %.2f vs hand-computed USD %.2f + CAD %.2f / %.2f "
              "= %.2f" % (da.net_sales(day), usd, cad, FX_CAD_PER_USD,
                          usd + cad / FX_CAD_PER_USD),
              "check net_sales_of()'s convert() call")
    A.require("RULE BR-16 mixed-currency local totals are refused",
              _raises(lambda: da.net_sales_local(day)),
              "net_sales_local() over the whole fleet did not raise; silently "
              "adding CAD to USD is the failure BR-16 exists to stop",
              "check net_sales_local()'s currency guard")

    grains = dict(q("SELECT b.brand_id, b.plan_grain FROM brand b"))
    breaks = []
    for eid, grain in q("SELECT DISTINCT p.entity_id, p.grain FROM plan_day p"):
        e = da.entity(eid)
        want = "DAY" if e["channel"] == "ECOM" else grains[e["brand_id"]]
        if grain != want:
            breaks.append((eid, grain, want))
    A.require("RULE BR-19 plan rows exist only at each brand's native grain",
              not breaks,
              "%d entities carry plan rows at the wrong grain: %s"
              % (len(breaks), breaks[:3]),
              "check gen_plan() in seed.py")

    breaks = []
    for d in ty_detail[::14] + [day]:
        rec = merch.reconcile_lines(da, d)
        if rec.get("available") and not rec["reconciled"]:
            breaks.append((d.isoformat(), rec["breaks"][:2]))
        cat = merch.category_day(da, d)
        if cat.get("available"):
            r = cat["reconciliation"]
            if abs(r["sum_of_categories"] - r["entity_day_total"]) > 0.01:
                breaks.append((d.isoformat(), r))
    A.require("RULE BR-11 categories sum to the entity total",
              not breaks,
              "%d days break the category rollup, first: %s"
              % (len(breaks), breaks[0] if breaks else None),
              "check flash/merch.py category_day()")

    n_bad = q("SELECT COUNT(*) FROM sales_day WHERE net_sales<=0 OR "
              "transactions<=0 OR units<transactions")[0][0]
    A.require("RULE fact sanity (positive sales, units >= transactions)",
              n_bad == 0,
              "%d sales_day rows are implausible" % n_bad,
              "check base_sales()/txn_units() in seed.py")

    n_orphan = q("SELECT COUNT(*) FROM omni_order o LEFT JOIN customer c "
                 "USING(customer_id) WHERE c.customer_id IS NULL")[0][0]
    n_orphan += q("SELECT COUNT(*) FROM return_event r LEFT JOIN customer c "
                  "USING(customer_id) WHERE c.customer_id IS NULL")[0][0]
    A.require("RULE every omni event belongs to a real customer",
              n_orphan == 0,
              "%d omni/return events reference a customer that does not exist"
              % n_orphan,
              "check CustomerPool.pick() in seed.py")

    n_early = q("SELECT COUNT(*) FROM omni_order o JOIN customer c "
                "USING(customer_id) WHERE c.first_purchase_date > o.created_date")[0][0]
    A.require("RULE no omni order predates its customer's first purchase",
              n_early == 0,
              "%d omni orders belong to a customer acquired later" % n_early,
              "check the bisect prefix in CustomerPool.pick()")

    return A


def _raises(fn):
    try:
        fn()
    except Exception:
        return True
    return False


TABLES = ("brand", "affiliate", "fx_rate", "district", "stores", "calendar",
          "product", "sales_day", "sales_line", "plan_day", "traffic_day",
          "traffic_hour", "customer", "omni_order", "return_event",
          "flash_archive")


def row_counts(conn):
    cur = conn.cursor()
    return [(t, cur.execute("SELECT COUNT(*) FROM %s" % t).fetchone()[0])
            for t in TABLES]


def main():
    t0 = time.time()
    conn, entities, products, stats = build()
    built = time.time() - t0
    cal = NRFCalendar()
    A = assert_all(conn, cal)
    total = time.time() - t0
    print("Built %s" % DB_PATH)
    print("  build %.1fs, assertions %.1fs, total %.1fs"
          % (built, total - built, total))
    print("  entities: %d (%d stores + %d e-commerce channels), %d SKUs"
          % (len(entities), len(entities) - len(ECOM_ENTITIES),
             len(ECOM_ENTITIES), len(products)))
    print("  detail window: %s .. %s (%d days)"
          % (stats["detail_start"], stats["detail_end"], stats["detail_days"]))
    for t, n in row_counts(conn):
        print("  %-14s %9d" % (t, n))
    print("  %d seed assertions passed (storylines + reconciliation rules)"
          % A.count())
    conn.close()


if __name__ == "__main__":
    main()
