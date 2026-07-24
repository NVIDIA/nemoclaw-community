-- =============================================================
-- NemoClaw Retail Agent — Database Initialization
-- PostgreSQL 14+
-- =============================================================


-- =============================================================
-- TABLES
-- =============================================================

-- 1. Stores
--    Physical locations. is_active lets the agent skip closed stores.
CREATE TABLE Stores (
    store_id    SERIAL       PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    city        VARCHAR(100) NOT NULL,
    country     VARCHAR(100) NOT NULL,
    region      VARCHAR(100),               -- e.g. "North", "Mediterranean"
    address     TEXT,
    phone       VARCHAR(20),
    is_active   BOOLEAN      NOT NULL DEFAULT TRUE,
    opened_at   DATE
);


-- 2. Employees
--    manager_id on Stores creates a circular dependency; resolved with ALTER TABLE below.
CREATE TABLE Employees (
    employee_id   SERIAL       PRIMARY KEY,
    store_id      INT          REFERENCES Stores(store_id),
    first_name    VARCHAR(50)  NOT NULL,
    last_name     VARCHAR(50)  NOT NULL,
    email         VARCHAR(100) NOT NULL UNIQUE,
    role          VARCHAR(30)  NOT NULL
                      CHECK (role IN ('country_manager', 'store_manager', 'data_analyst')),
    country       VARCHAR(100),
    is_active     BOOLEAN      NOT NULL DEFAULT TRUE,
    hired_at      DATE,
    password_hash VARCHAR(255)             -- bcrypt hash of firstname (lowercase) + nemoclaw1234
);

-- Back-fill: each store has one manager
ALTER TABLE Stores ADD COLUMN manager_id INT REFERENCES Employees(employee_id);


-- 3. Customers / CRM
CREATE TABLE Customers (
    customer_id        SERIAL       PRIMARY KEY,
    first_name         VARCHAR(50),
    last_name          VARCHAR(50),
    full_name          VARCHAR(101) GENERATED ALWAYS AS (first_name || ' ' || last_name) STORED,
    email              VARCHAR(100) UNIQUE,
    phone              VARCHAR(20),
    preferred_store_id INT          REFERENCES Stores(store_id),
    date_of_birth      DATE,
    gender             VARCHAR(10)  CHECK (gender IN ('male', 'female', 'other', 'unspecified')),
    registration_date  TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- 4. Products — master catalog
CREATE TABLE Products (
    id                   SERIAL        PRIMARY KEY,
    product_name         VARCHAR(200)  NOT NULL,
    description          TEXT,
    category             VARCHAR(100),                -- e.g. "Footwear", "Apparel", "Accessories"
    subcategory          VARCHAR(100),                -- e.g. "Running", "Casual", "Formal"
    brand                VARCHAR(100),
    gender_target        VARCHAR(20)   CHECK (gender_target IN ('men', 'women', 'unisex', 'kids')),
    sustainability_score NUMERIC(3,2)  CHECK (sustainability_score >= 0 AND sustainability_score <= 10),
    season               VARCHAR(20),                 -- e.g. "SS2026", "AW2025"
    price                NUMERIC(10,2) NOT NULL,
    is_active            BOOLEAN       NOT NULL DEFAULT TRUE
);


-- 5. Inventory — one row per product × size × color × store
CREATE TABLE Inventory (
    inventory_id      SERIAL    PRIMARY KEY,
    store_id          INT       NOT NULL REFERENCES Stores(store_id),
    product_id        INT       NOT NULL REFERENCES Products(id),
    size              VARCHAR(20),                    -- e.g. "S", "M", "L", "42", "One Size"
    color             VARCHAR(50),                    -- e.g. "Navy Blue", "Off White"
    quantity_on_hand  INT       NOT NULL DEFAULT 0,
    quantity_reserved INT       NOT NULL DEFAULT 0,   -- held by pending / online orders
    reorder_level     INT       NOT NULL DEFAULT 5,   -- alert threshold
    reorder_quantity  INT       NOT NULL DEFAULT 20,  -- suggested PO quantity
    last_restocked_at TIMESTAMP,
    UNIQUE (store_id, product_id, size, color),
    CONSTRAINT chk_qty_non_negative      CHECK (quantity_on_hand  >= 0),
    CONSTRAINT chk_reserved_non_negative CHECK (quantity_reserved >= 0)
);


-- 6. Inventory Transfers — inter-store stock movements
CREATE TABLE InventoryTransfers (
    transfer_id    SERIAL      PRIMARY KEY,
    from_store_id  INT         NOT NULL REFERENCES Stores(store_id),
    to_store_id    INT         NOT NULL REFERENCES Stores(store_id),
    product_id     INT         NOT NULL REFERENCES Products(id),
    size           VARCHAR(20),
    color          VARCHAR(50),
    quantity       INT         NOT NULL CHECK (quantity > 0),
    requested_by   INT         NOT NULL REFERENCES Employees(employee_id),
    approved_by    INT         REFERENCES Employees(employee_id),
    status         VARCHAR(20) NOT NULL DEFAULT 'pending'
                       CHECK (status IN ('pending', 'approved', 'in_transit', 'completed', 'cancelled')),
    notes          TEXT,
    requested_at   TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at   TIMESTAMP,
    CONSTRAINT chk_different_stores CHECK (from_store_id <> to_store_id)
);


-- 7. Reorder Requests — supplier replenishment (manual or automatic)
CREATE TABLE ReorderRequests (
    reorder_id         SERIAL      PRIMARY KEY,
    store_id           INT         NOT NULL REFERENCES Stores(store_id),
    product_id         INT         NOT NULL REFERENCES Products(id),
    size               VARCHAR(20),
    color              VARCHAR(50),
    requested_quantity INT         NOT NULL CHECK (requested_quantity > 0),
    triggered_by       VARCHAR(20) NOT NULL CHECK (triggered_by IN ('automatic', 'manual')),
    requested_by       INT         REFERENCES Employees(employee_id), -- NULL when automatic
    status             VARCHAR(20) NOT NULL DEFAULT 'pending'
                           CHECK (status IN ('pending', 'approved', 'ordered', 'received', 'cancelled')),
    supplier_reference VARCHAR(100),
    expected_delivery  DATE,
    requested_at       TIMESTAMP   NOT NULL DEFAULT CURRENT_TIMESTAMP,
    received_at        TIMESTAMP
);


-- 8. Promotions — discount campaigns with targeting rules
--    applicable_to + applicable_value define the scope:
--      'all'      → entire catalog             (applicable_value: NULL)
--      'category' → product category           (applicable_value: "Footwear")
--      'brand'    → brand name                 (applicable_value: "Nike")
--      'season'   → season code                (applicable_value: "SS2026")
--      'product'  → specific product           (applicable_value: "<product_id>")
CREATE TABLE Promotions (
    promotion_id        SERIAL        PRIMARY KEY,
    name                VARCHAR(200)  NOT NULL,
    description         TEXT,
    discount_type       VARCHAR(30)   NOT NULL
                            CHECK (discount_type IN ('percentage', 'fixed_amount', 'buy_x_get_y', 'bundle')),
    discount_value      NUMERIC(10,2),              -- % (0–100) or currency amount
    buy_x_quantity      INT,                        -- for buy_x_get_y
    get_y_quantity      INT,                        -- for buy_x_get_y
    min_purchase_amount NUMERIC(10,2),              -- minimum basket value to qualify
    applicable_to       VARCHAR(30)   NOT NULL
                            CHECK (applicable_to IN ('all', 'category', 'brand', 'season', 'product')),
    applicable_value    VARCHAR(100),               -- e.g. "Footwear", "Nike", "SS2026", "<product_id>"
    store_id            INT           REFERENCES Stores(store_id),  -- NULL = chain-wide
    start_date          DATE          NOT NULL,
    end_date            DATE          NOT NULL,
    is_active           BOOLEAN       NOT NULL DEFAULT TRUE,
    created_by          INT           REFERENCES Employees(employee_id),
    CONSTRAINT chk_dates CHECK (end_date >= start_date)
);


-- 9. Orders — one per sales transaction
--    Promotions are applied at line-item level (see OrderItems) to support
--    multiple simultaneous promotions (e.g. footwear 10% off + t-shirts 2×3).
CREATE TABLE Orders (
    id              SERIAL        PRIMARY KEY,
    customer_id     INT           REFERENCES Customers(customer_id), -- NULL = anonymous sale
    store_id        INT           NOT NULL REFERENCES Stores(store_id),
    employee_id     INT           REFERENCES Employees(employee_id), -- Data Analyst
    order_channel   VARCHAR(30)   NOT NULL DEFAULT 'in_store'
                        CHECK (order_channel IN ('in_store', 'online', 'phone', 'app')),
    status          VARCHAR(30)   NOT NULL DEFAULT 'completed'
                        CHECK (status IN ('pending', 'completed', 'cancelled', 'refunded')),
    subtotal        NUMERIC(10,2) NOT NULL,
    discount_amount NUMERIC(10,2) NOT NULL DEFAULT 0, -- sum of all line discounts (denormalized)
    total_amount    NUMERIC(10,2) NOT NULL,
    order_date      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- 10. Order Items — one row per product line within an order
--     Each line carries its own promotion_id (NULL = full price).
CREATE TABLE OrderItems (
    order_item_id    SERIAL        PRIMARY KEY,
    order_id         INT           NOT NULL REFERENCES Orders(id) ON DELETE CASCADE,
    inventory_id     INT           NOT NULL REFERENCES Inventory(inventory_id), -- store + product + size + color
    product_id       INT           REFERENCES Products(id),                     -- denormalized from inventory for easy JOINs
    promotion_id     INT           REFERENCES Promotions(promotion_id),         -- NULL = no promo on this line
    quantity         INT           NOT NULL CHECK (quantity > 0),
    unit_price       NUMERIC(10,2) NOT NULL,  -- snapshot of price at sale time
    discount_amount  NUMERIC(10,2) NOT NULL DEFAULT 0,
    total_item_price NUMERIC(10,2) NOT NULL   -- (unit_price - discount_amount) * quantity
);


-- 11. Telegram Auth — maps Telegram user IDs to employees
--     Used by the /auth/login-telegram endpoint to authenticate
--     Telegram bot users without a password.
CREATE TABLE TelegramAuth (
    telegram_id  VARCHAR(30)  PRIMARY KEY,
    employee_id  INT          NOT NULL REFERENCES Employees(employee_id),
    created_at   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
);


-- =============================================================
-- VIEWS
-- =============================================================

-- Stock availability with computed available qty and reorder flag
CREATE VIEW InventoryAvailable AS
SELECT
    i.inventory_id,
    s.store_id,
    s.name                                      AS store_name,
    s.city,
    s.country,
    p.id                                        AS product_id,
    p.product_name,
    p.category,
    p.brand,
    p.season,
    i.size,
    i.color,
    i.quantity_on_hand,
    i.quantity_reserved,
    (i.quantity_on_hand - i.quantity_reserved)  AS quantity_available,
    i.reorder_level,
    CASE
        WHEN (i.quantity_on_hand - i.quantity_reserved) <= i.reorder_level
        THEN TRUE ELSE FALSE
    END                                         AS needs_reorder,
    p.price                                     AS selling_price
FROM Inventory i
JOIN Stores   s ON s.store_id  = i.store_id
JOIN Products p ON p.id = i.product_id;


-- Store Manager: items at or below reorder threshold
CREATE VIEW LowStockAlerts AS
SELECT
    s.store_id,
    s.name                              AS store_name,
    p.id                                AS product_id,
    p.product_name,
    p.category,
    p.brand,
    i.size,
    i.color,
    i.quantity_on_hand,
    i.quantity_reserved,
    (i.quantity_on_hand - i.quantity_reserved) AS quantity_available,
    i.reorder_level,
    i.reorder_quantity                  AS suggested_reorder_qty,
    TRUE                                AS needs_reorder
FROM Inventory i
JOIN Stores   s ON s.store_id  = i.store_id
JOIN Products p ON p.id = i.product_id
WHERE (i.quantity_on_hand - i.quantity_reserved) <= i.reorder_level
  AND s.is_active = TRUE
  AND p.is_active = TRUE;


-- Country Manager: monthly revenue per store
CREATE VIEW SalesPerformanceByStore AS
SELECT
    s.country,
    s.region,
    s.store_id,
    s.name                               AS store_name,
    DATE_TRUNC('month', o.order_date) AS sales_month,
    COUNT(DISTINCT o.id)                 AS total_orders,
    COUNT(DISTINCT o.customer_id)        AS unique_customers,
    SUM(o.total_amount)                  AS revenue,
    SUM(o.discount_amount)               AS total_discounts,
    ROUND(AVG(o.total_amount), 2)        AS avg_order_value
FROM Orders o
JOIN Stores s ON s.store_id = o.store_id
WHERE o.status = 'completed'
GROUP BY s.country, s.region, s.store_id, s.name, DATE_TRUNC('month', o.order_date);


-- Country Manager: top-selling products by units and revenue
CREATE VIEW TopProductsByRevenue AS
SELECT
    s.country,
    p.id                                AS product_id,
    p.product_name,
    p.category,
    p.brand,
    p.season,
    SUM(oi.quantity)                    AS units_sold,
    SUM(oi.total_item_price)            AS revenue
FROM OrderItems oi
JOIN Orders    o  ON o.id            = oi.order_id
JOIN Inventory iv ON iv.inventory_id = oi.inventory_id
JOIN Products  p  ON p.id           = iv.product_id
JOIN Stores    s  ON s.store_id      = o.store_id
WHERE o.status = 'completed'
GROUP BY s.country, p.id, p.product_name, p.category, p.brand, p.season;


-- Data Analyst: full customer profile with purchase summary
CREATE VIEW Customer360 AS
SELECT
    c.customer_id,
    c.full_name,
    c.email,
    c.phone,
    c.gender,
    c.date_of_birth,
    c.registration_date,
    st.name                             AS preferred_store,
    COUNT(DISTINCT o.id)                AS total_orders,
    COALESCE(SUM(o.total_amount), 0)    AS lifetime_value,
    MAX(o.order_date)                   AS last_order_date,
    ROUND(AVG(o.total_amount), 2)       AS avg_order_value
FROM Customers c
LEFT JOIN Stores  st ON st.store_id  = c.preferred_store_id
LEFT JOIN Orders   o ON  o.customer_id = c.customer_id AND o.status = 'completed'
GROUP BY c.customer_id, c.full_name, c.first_name, c.last_name, c.email, c.phone,
         c.gender, c.date_of_birth, c.registration_date, st.name;


-- Agent eligibility check: promotions active today
CREATE VIEW ActivePromotions AS
SELECT
    pr.promotion_id,
    pr.name,
    pr.description,
    pr.discount_type,
    pr.discount_value,
    pr.buy_x_quantity,
    pr.get_y_quantity,
    pr.min_purchase_amount,
    pr.applicable_to,
    pr.applicable_value,
    COALESCE(s.name, 'All Stores')      AS applicable_store,
    pr.start_date,
    pr.end_date
FROM Promotions pr
LEFT JOIN Stores s ON s.store_id = pr.store_id
WHERE pr.is_active = TRUE
  AND CURRENT_DATE BETWEEN pr.start_date AND pr.end_date;


-- =============================================================
-- INDEXES
-- =============================================================

-- Inventory lookups (most frequent agent query pattern)
CREATE INDEX idx_inventory_store        ON Inventory(store_id);
CREATE INDEX idx_inventory_product      ON Inventory(product_id);
CREATE INDEX idx_inventory_size_color   ON Inventory(size, color);

-- Product catalog filtering
CREATE INDEX idx_product_category_brand ON Products(category, brand);
CREATE INDEX idx_product_season         ON Products(season);
CREATE INDEX idx_product_is_active      ON Products(is_active);

-- Sales analytics
CREATE INDEX idx_orders_store_date      ON Orders(store_id, order_date);
CREATE INDEX idx_orders_customer        ON Orders(customer_id);
CREATE INDEX idx_orders_employee        ON Orders(employee_id);
CREATE INDEX idx_order_items_order      ON OrderItems(order_id);
CREATE INDEX idx_order_items_inventory  ON OrderItems(inventory_id);
CREATE INDEX idx_order_items_product    ON OrderItems(product_id);
CREATE INDEX idx_order_items_promotion  ON OrderItems(promotion_id);

-- Promotions eligibility (partial index: only active rows)
CREATE INDEX idx_promotions_dates       ON Promotions(start_date, end_date) WHERE is_active = TRUE;
CREATE INDEX idx_promotions_scope       ON Promotions(applicable_to, applicable_value);

-- CRM
CREATE INDEX idx_customers_email        ON Customers(email);
CREATE INDEX idx_customers_store        ON Customers(preferred_store_id);


-- =============================================================
-- POSTGRESQL ROLES  (RBAC enforcement at database level)
-- =============================================================
-- Two roles are created and granted to the API superuser at runtime.
-- The API switches role per request via SET LOCAL ROLE inside a transaction,
-- so PostgreSQL enforces the permissions — no application-level SQL parsing needed.

-- Role: nemoclaw_country_manager
--   Full read + write on all tables (including approving transfers).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nemoclaw_country_manager') THEN
    CREATE ROLE nemoclaw_country_manager;
  END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nemoclaw_country_manager;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nemoclaw_country_manager;

-- Role: nemoclaw_manager
--   Read + write on all tables EXCEPT cannot UPDATE InventoryTransfers
--   (transfer approval is country_manager only).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nemoclaw_manager') THEN
    CREATE ROLE nemoclaw_manager;
  END IF;
END $$;

GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO nemoclaw_manager;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nemoclaw_manager;
-- Row Level Security (see policies below) limits UPDATE/INSERT to the manager's own store.

-- Role: nemoclaw_data_analyst
--   Read-only on all tables and views.
--   No write access to any table — analysts query data, they do not mutate it.
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'nemoclaw_data_analyst') THEN
    CREATE ROLE nemoclaw_data_analyst;
  END IF;
END $$;

GRANT SELECT ON ALL TABLES IN SCHEMA public TO nemoclaw_data_analyst;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO nemoclaw_data_analyst;
-- No INSERT/UPDATE/DELETE granted to any table (default deny)


-- =============================================================
-- ROW LEVEL SECURITY  (per-store enforcement for store_managers)
-- =============================================================
-- The API sets app.current_store_id per transaction (SET LOCAL).
-- nemoclaw_manager may INSERT/UPDATE only rows belonging to their store.
-- nemoclaw_country_manager is unrestricted (USING true).
-- nemoclaw_data_analyst has SELECT-only policies (no write grants anyway).

-- InventoryTransfers
ALTER TABLE InventoryTransfers ENABLE ROW LEVEL SECURITY;

CREATE POLICY cm_all_transfers ON InventoryTransfers
  TO nemoclaw_country_manager USING (true) WITH CHECK (true);

CREATE POLICY mgr_select_transfers ON InventoryTransfers
  FOR SELECT TO nemoclaw_manager USING (true);

CREATE POLICY mgr_insert_transfers ON InventoryTransfers
  FOR INSERT TO nemoclaw_manager
  WITH CHECK (from_store_id = NULLIF(current_setting('app.current_store_id', true), '')::int);
-- No UPDATE policy for nemoclaw_manager on InventoryTransfers:
-- RLS default-deny means store_managers cannot approve transfers. Only country_manager can.

CREATE POLICY analyst_select_transfers ON InventoryTransfers
  FOR SELECT TO nemoclaw_data_analyst USING (true);

-- ReorderRequests
ALTER TABLE ReorderRequests ENABLE ROW LEVEL SECURITY;

CREATE POLICY cm_all_reorders ON ReorderRequests
  TO nemoclaw_country_manager USING (true) WITH CHECK (true);

CREATE POLICY mgr_select_reorders ON ReorderRequests
  FOR SELECT TO nemoclaw_manager USING (true);

CREATE POLICY mgr_insert_reorders ON ReorderRequests
  FOR INSERT TO nemoclaw_manager
  WITH CHECK (store_id = NULLIF(current_setting('app.current_store_id', true), '')::int);

CREATE POLICY mgr_update_reorders ON ReorderRequests
  FOR UPDATE TO nemoclaw_manager
  USING (store_id = NULLIF(current_setting('app.current_store_id', true), '')::int)
  WITH CHECK (store_id = NULLIF(current_setting('app.current_store_id', true), '')::int);

CREATE POLICY analyst_select_reorders ON ReorderRequests
  FOR SELECT TO nemoclaw_data_analyst USING (true);
