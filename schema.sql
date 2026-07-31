-- Lumière Ops Flash — SQLite schema (PRD §3). Stdlib sqlite3 only.
-- Forked from the executive flash schema and extended with the operational
-- dimensions: brand, affiliate, district, product/SKU grain, traffic (daily +
-- hourly), customer identity, omni orders, and store-side return events.
--
-- Grain discipline (BR-5 applied to dimensions): brand and category are NEVER
-- stored on a fact row. They are derived by joining the fact's entity/SKU to
-- its dimension row, so there is exactly one home for "what brand is this".

PRAGMA foreign_keys = ON;

DROP TABLE IF EXISTS flash_archive;
DROP TABLE IF EXISTS return_event;
DROP TABLE IF EXISTS omni_order;
DROP TABLE IF EXISTS customer;
DROP TABLE IF EXISTS traffic_hour;
DROP TABLE IF EXISTS traffic_day;
DROP TABLE IF EXISTS sales_line;
DROP TABLE IF EXISTS plan_day;
DROP TABLE IF EXISTS sales_day;
DROP TABLE IF EXISTS product;
DROP TABLE IF EXISTS calendar;
DROP TABLE IF EXISTS stores;
DROP TABLE IF EXISTS district;
DROP TABLE IF EXISTS affiliate;
DROP TABLE IF EXISTS fx_rate;
DROP TABLE IF EXISTS brand;

-- =========================================================================
-- Org dimensions (D7/D8 — the persona spine)
-- =========================================================================

-- Three brands under the Lumière Beauty Group house. `plan_grain` carries
-- D12's authentic mix: one brand plans daily, one weekly, one not at all.
CREATE TABLE brand (
    brand_id    TEXT PRIMARY KEY,          -- 'LUM' | 'ATN' | 'BOT'
    name        TEXT NOT NULL,
    positioning TEXT NOT NULL,
    categories  TEXT NOT NULL,             -- pipe-separated category list
    plan_grain  TEXT NOT NULL              -- 'DAY' | 'WEEK' | 'NONE' (BR-19)
);

-- Country markets. Facts are stored in the affiliate's local currency (BR-16).
CREATE TABLE affiliate (
    affiliate_id TEXT PRIMARY KEY,         -- 'US' | 'CA'
    name         TEXT NOT NULL,
    currency     TEXT NOT NULL             -- 'USD' | 'CAD'
);

-- One seeded fixed rate. Units: `units_per_usd` of `currency` buy one USD.
-- Fixed, disclosed wherever a converted figure appears (BR-16). No floating FX.
CREATE TABLE fx_rate (
    currency      TEXT PRIMARY KEY,
    units_per_usd REAL NOT NULL,
    basis         TEXT NOT NULL            -- disclosure string
);

-- The level between region and store (11 total: 2 per US region + 1 for CA).
CREATE TABLE district (
    district_id  TEXT PRIMARY KEY,         -- 'NE-1' ...
    name         TEXT NOT NULL,
    region       TEXT NOT NULL,
    affiliate_id TEXT NOT NULL,
    FOREIGN KEY (affiliate_id) REFERENCES affiliate(affiliate_id)
);

-- Entities: 29 Lumière Beauty Group stores (25 vendored US + 4 seeded CA) plus
-- two virtual e-commerce channels (US and CA). `entity_id` = lease_id for
-- stores, 'ECOM-US' / 'ECOM-CA' for e-comm.
CREATE TABLE stores (
    entity_id        TEXT PRIMARY KEY,
    store_number     INTEGER,              -- NULL for ECOM
    name             TEXT NOT NULL,
    channel          TEXT NOT NULL,        -- 'STORE' | 'ECOM'
    region           TEXT NOT NULL,        -- 5 US regions, 'Canada', or 'ECOM'
    open_date        TEXT NOT NULL,        -- ISO; drives comp eligibility (BR-2)
    close_date       TEXT,                 -- ISO or NULL
    remodel_start    TEXT,                 -- ISO or NULL (comp-excluded window)
    remodel_end      TEXT,                 -- ISO or NULL (NULL = still down)
    rentable_sf      INTEGER,
    target_sales_psf REAL,
    annual_volume    REAL NOT NULL,        -- synthesized base-year anchor (local ccy)
    -- operational extensions --------------------------------------------
    -- brand_id is NULL for ECOM only: e-commerce is multi-brand and carries
    -- brand through the SKU on each sales_line (PRD §3), never on the entity.
    brand_id         TEXT,
    district_id      TEXT,                 -- NULL for ECOM
    affiliate_id     TEXT NOT NULL,
    currency         TEXT NOT NULL,        -- local currency of the facts
    state_province   TEXT,
    city             TEXT,
    store_status     TEXT NOT NULL,        -- roster status: Open/Closing/Opening Soon
    FOREIGN KEY (brand_id) REFERENCES brand(brand_id),
    FOREIGN KEY (district_id) REFERENCES district(district_id),
    FOREIGN KEY (affiliate_id) REFERENCES affiliate(affiliate_id)
);
CREATE INDEX idx_stores_brand ON stores(brand_id);
CREATE INDEX idx_stores_district ON stores(district_id);

-- One row per calendar date. ly_aligned_date is MATERIALIZED at seed time so
-- every downstream comp is a join, not a computation (BR-5 applied to dates).
CREATE TABLE calendar (
    date            TEXT PRIMARY KEY,      -- ISO YYYY-MM-DD
    fiscal_year     INTEGER NOT NULL,
    period          INTEGER NOT NULL,      -- 1..12
    week            INTEGER NOT NULL,      -- 1..52/53 (fiscal week)
    day_of_week     INTEGER NOT NULL,      -- 1=Sun .. 7=Sat
    holiday_code    TEXT,                  -- NULL if no holiday
    ly_aligned_date TEXT NOT NULL,         -- same fiscal week + DOW, prior FY
    restated        INTEGER NOT NULL DEFAULT 0,  -- 53-week NRF shift in effect
    quarter         INTEGER NOT NULL,      -- 1..4 (for QTD, metric #41)
    week_start      TEXT NOT NULL,         -- ISO date of the fiscal week's Sunday
    week_end        TEXT NOT NULL          -- ISO date of the fiscal week's Saturday
);
CREATE INDEX idx_calendar_fy ON calendar(fiscal_year, period, week);

-- =========================================================================
-- Merchandise dimension
-- =========================================================================

-- ~120 deterministic SKUs. Each brand carries only its own categories, so
-- category rollups partition cleanly by brand (BR-11).
CREATE TABLE product (
    sku_id      TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    brand_id    TEXT NOT NULL,
    category    TEXT NOT NULL,             -- one of the 5 merch categories
    launch_date TEXT NOT NULL,             -- ISO; drives "new SKU" (#29 / storyline 5)
    unit_price  REAL NOT NULL,             -- USD list; category-banded (AUR emerges)
    FOREIGN KEY (brand_id) REFERENCES brand(brand_id)
);
CREATE INDEX idx_product_brand_cat ON product(brand_id, category);

-- =========================================================================
-- Fact tables
-- =========================================================================

-- Date × entity actuals. A MISSING (unposted) store has NO row (BR-3: missing,
-- never zero). posted_at is materialized from the data, never now() (NFR-2).
-- Money is in the entity's LOCAL currency (BR-16).
CREATE TABLE sales_day (
    date             TEXT NOT NULL,
    entity_id        TEXT NOT NULL,
    net_sales        REAL NOT NULL,        -- for ECOM: = demand_sales (BR-4)
    transactions     INTEGER NOT NULL,
    units            INTEGER NOT NULL,
    demand_sales     REAL,                 -- ECOM only
    shipped_sales    REAL,                 -- ECOM only (settled)
    returns_recorded REAL,                 -- ECOM only (settled)
    gross_sales      REAL NOT NULL,        -- deck KPI; net = gross − disc − ret
    discount_sales   REAL NOT NULL,        -- metric #32
    return_sales     REAL NOT NULL,        -- metric #33
    posted_at        TEXT NOT NULL,
    PRIMARY KEY (date, entity_id),
    FOREIGN KEY (entity_id) REFERENCES stores(entity_id),
    FOREIGN KEY (date) REFERENCES calendar(date)
);
CREATE INDEX idx_sales_entity ON sales_day(entity_id, date);

-- Date × entity × SKU. Brand and category are DERIVED via product, never
-- stored here (BR-5). Σ sales_line = sales_day per entity/day, asserted (BR-11).
-- Seeded across the detail window only (see seed.py DETAIL_DAYS) — the window
-- that carries every SKU-grain surface plus its LY-aligned counterpart.
CREATE TABLE sales_line (
    date      TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    sku_id    TEXT NOT NULL,
    net_sales REAL NOT NULL,               -- local currency
    units     INTEGER NOT NULL,
    PRIMARY KEY (date, entity_id, sku_id),
    FOREIGN KEY (entity_id) REFERENCES stores(entity_id),
    FOREIGN KEY (sku_id) REFERENCES product(sku_id),
    FOREIGN KEY (date) REFERENCES calendar(date)
);
CREATE INDEX idx_line_sku ON sales_line(sku_id, date);
CREATE INDEX idx_line_entity ON sales_line(entity_id, date);

-- Plan at each brand's NATIVE grain (D12/BR-19). A DAY-grain row has
-- period_start = period_end = the date. A WEEK-grain row spans the fiscal
-- week. A no-plan brand has NO rows — views say "no plan", never 100%.
CREATE TABLE plan_day (
    entity_id    TEXT NOT NULL,
    grain        TEXT NOT NULL,            -- 'DAY' | 'WEEK'
    period_start TEXT NOT NULL,            -- ISO
    period_end   TEXT NOT NULL,            -- ISO
    fiscal_year  INTEGER NOT NULL,
    fiscal_week  INTEGER NOT NULL,
    plan_sales   REAL NOT NULL,            -- local currency
    PRIMARY KEY (entity_id, grain, period_start),
    FOREIGN KEY (entity_id) REFERENCES stores(entity_id)
);
CREATE INDEX idx_plan_span ON plan_day(period_start, period_end);

-- Store traffic, daily. Stores only (FSS-labeled); ECOM has no traffic.
-- A missing-traffic day has NO row => conversion is UNAVAILABLE, never 0% (BR-15).
CREATE TABLE traffic_day (
    date      TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    traffic   INTEGER NOT NULL,
    PRIMARY KEY (date, entity_id),
    FOREIGN KEY (entity_id) REFERENCES stores(entity_id),
    FOREIGN KEY (date) REFERENCES calendar(date)
);

-- Hourly grain for the Store Hourly view (D9). Hours are 10..20 local
-- (11 trading hours). Σ hourly = the day's posted total, asserted (BR-17);
-- hourly surfaces are labeled unaudited/intraday.
CREATE TABLE traffic_hour (
    date         TEXT NOT NULL,
    entity_id    TEXT NOT NULL,
    hour         INTEGER NOT NULL,         -- 10..20
    traffic      INTEGER NOT NULL,
    net_sales    REAL NOT NULL,
    transactions INTEGER NOT NULL,
    PRIMARY KEY (date, entity_id, hour),
    FOREIGN KEY (entity_id) REFERENCES stores(entity_id),
    FOREIGN KEY (date) REFERENCES calendar(date)
);

-- Customer identity, minimal by design (D3): enough for new-to-file, total
-- buyers and repeat rate — no LTV, no segmentation. New-to-file is derived
-- SOLELY from first_purchase_date (BR-12).
CREATE TABLE customer (
    customer_id         TEXT PRIMARY KEY,
    first_purchase_date TEXT NOT NULL,
    home_entity_id      TEXT NOT NULL,     -- store or ECOM channel
    affiliate_id        TEXT NOT NULL,
    -- The value of the acquiring basket, in the home entity's local currency.
    -- ALLOCATED out of that entity/day's posted net sales, never added to it,
    -- so the New Customer block (#34) attributes rather than invents (BR-9).
    first_basket        REAL NOT NULL,
    first_units         INTEGER NOT NULL,
    FOREIGN KEY (home_entity_id) REFERENCES stores(entity_id),
    FOREIGN KEY (affiliate_id) REFERENCES affiliate(affiliate_id)
);
CREATE INDEX idx_customer_first ON customer(first_purchase_date, home_entity_id);

-- Omni orders at order grain (omni BRD #1–35, #51–58). `sales` ATTRIBUTES
-- money that already sits in sales_day — it is never added to a total (BR-9).
-- `attributed_to` names where that money lives so the rule is auditable.
CREATE TABLE omni_order (
    order_id       TEXT PRIMARY KEY,
    order_type     TEXT NOT NULL,          -- 'BOPIS' | 'RTD' | 'OOFIS' | 'CR'
    store_id       TEXT NOT NULL,          -- fulfilling / originating store
    customer_id    TEXT NOT NULL,
    created_date   TEXT NOT NULL,
    fulfilled_date TEXT,                   -- pickup / delivery / conversion date
    status         TEXT NOT NULL,          -- completed|in_progress|partial|cancelled
    sales          REAL NOT NULL,          -- local currency; attributed, not additive
    items          INTEGER NOT NULL,
    upsell_sales   REAL NOT NULL DEFAULT 0,-- store-side attach on pickup
    upsell_items   INTEGER NOT NULL DEFAULT 0,
    attributed_to  TEXT NOT NULL,          -- 'ECOM-US'|'ECOM-CA'|store entity_id
    FOREIGN KEY (store_id) REFERENCES stores(entity_id),
    FOREIGN KEY (customer_id) REFERENCES customer(customer_id)
);
CREATE INDEX idx_omni_day ON omni_order(fulfilled_date, order_type);
CREATE INDEX idx_omni_created ON omni_order(created_date, order_type);
CREATE INDEX idx_omni_store ON omni_order(store_id, fulfilled_date);

-- BORIS: store-side returns of online orders (#36–44, ex-#40). Distinct from
-- sales_day.returns_recorded (aggregate ECOM settled returns) and from
-- sales_day.return_sales (store-side returns of store purchases).
CREATE TABLE return_event (
    return_id    TEXT PRIMARY KEY,
    return_date  TEXT NOT NULL,
    store_id     TEXT NOT NULL,
    customer_id  TEXT NOT NULL,
    amount       REAL NOT NULL,            -- local currency
    items        INTEGER NOT NULL,
    saved_sales  REAL NOT NULL DEFAULT 0,  -- same store/day/customer re-purchase
    saved        INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (store_id) REFERENCES stores(entity_id),
    FOREIGN KEY (customer_id) REFERENCES customer(customer_id)
);
CREATE INDEX idx_return_day ON return_event(return_date, store_id);

-- One row per generated flash version. Immutable once written (BR-7);
-- restatements append version+1 with a reason string.
CREATE TABLE flash_archive (
    date          TEXT NOT NULL,
    version       INTEGER NOT NULL,
    computed_json TEXT NOT NULL,
    reason        TEXT,                    -- restatement reason (version>1)
    created_at    TEXT NOT NULL,           -- from data, never now()
    PRIMARY KEY (date, version)
);
