---
name: retail-api
description: "Araz Retail API — query stores, inventory, sales, customers, promotions, and orders. CLI: node ~/.openclaw/skills/retail-api/scripts/retail-api.js <command> --telegram-id TID. Authenticate with --telegram-id (the user's Telegram ID from message metadata from.id). Do NOT use --email or --password. Read commands: me, products [--category X] [--brand X] [--season X], inventory [--store N] [--product N] [--low-stock], customers [--id N] [--customer-email X], promotions [--all], sales [--store N], query \"SQL\". Write commands: transfer --product ID_OR_NAME --to-store N --quantity N [--size S] [--color C] [--from-store N], reorder --product ID_OR_NAME --quantity N [--store N] [--size S] [--color C]. QUERY SYNTAX: query \"SELECT ... LIMIT 50\" --telegram-id TID. The SQL is a positional argument — do NOT use -q flag (it does not exist). Table names are all lowercase: stores, products, inventory, orders, orderitems, customers, promotions, inventorytransfers, reorderrequests. Products PK is id, name column is product_name. Orders PK is id. OrderItems has product_id for direct JOINs. Customers has full_name (generated). Stores column is name not store_name. Inventory has no quantity_available column — use InventoryAvailable view. CRITICAL VIEW RULE: When querying a view directly (LowStockAlerts, InventoryAvailable, Customer360, etc.), use flat column names WITHOUT table alias prefixes. Views: InventoryAvailable, LowStockAlerts, Customer360, SalesPerformanceByStore, TopProductsByRevenue, ActivePromotions. NOT for: web_fetch, browser, writing Python scripts, or urllib."
metadata: { "openclaw": { "emoji": "🛒", "requires": { "bins": ["node"] } } }
---

# Araz Retail API Skill

Query and manage the Araz retail chain: stores, inventory, sales, customers, promotions, and orders.

## How to Use

All commands use: `node ~/.openclaw/skills/retail-api/scripts/retail-api.js <command> [options] --telegram-id TID`

**Every command MUST include `--telegram-id` with the user's Telegram ID from message metadata `from.id`.**

Rules:
- Use only this CLI in `exec`.
- **Exactly one `exec` call per user request. No exceptions.**
- **Never retry.** If the command fails, report the error to the user and stop.
- Do not use `-q` flag — it does not exist. The `query` command takes SQL as a positional argument.
- Do not use `--email` or `--password` — use `--telegram-id` instead.
- Do not use curl/browser/web_fetch or write helper scripts.
- Never fabricate data; use only data returned by the CLI in the current request.
- Ignore `/proc/self/oom_score_adj: Permission denied`; it is a harmless sandbox warning.
- Authorized Telegram IDs are in SOUL.md. Look up by `from.id`.

## Read Commands

### Current user info

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js me --telegram-id 8667894990
```

### Products

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js products --telegram-id TID
node ~/.openclaw/skills/retail-api/scripts/retail-api.js products --telegram-id TID --category Footwear
node ~/.openclaw/skills/retail-api/scripts/retail-api.js products --telegram-id TID --brand "Eco Threads" --season SS2026
```

### Inventory

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js inventory --telegram-id TID --store 3
node ~/.openclaw/skills/retail-api/scripts/retail-api.js inventory --telegram-id TID --store 3 --low-stock
node ~/.openclaw/skills/retail-api/scripts/retail-api.js inventory --telegram-id TID --store 3 --product 7
```

### Customers

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js customers --telegram-id TID
node ~/.openclaw/skills/retail-api/scripts/retail-api.js customers --telegram-id TID --id 42
node ~/.openclaw/skills/retail-api/scripts/retail-api.js customers --telegram-id TID --customer-email john@example.com
```

### Promotions

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js promotions --telegram-id TID
node ~/.openclaw/skills/retail-api/scripts/retail-api.js promotions --telegram-id TID --all
```

### Sales performance

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js sales --telegram-id TID
node ~/.openclaw/skills/retail-api/scripts/retail-api.js sales --telegram-id TID --store 3
```

### Custom SQL query (for complex questions)

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js query "SELECT store_id, name, city FROM Stores WHERE is_active = true" --telegram-id TID
node ~/.openclaw/skills/retail-api/scripts/retail-api.js query "SELECT c.full_name, SUM(o.total_amount) as total FROM Orders o JOIN Customers c ON o.customer_id = c.customer_id WHERE o.order_date >= '2026-02-01' GROUP BY c.customer_id, c.full_name ORDER BY total DESC LIMIT 5" --telegram-id TID
```

Example: top products by revenue for a store:
```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js query "SELECT p.product_name, p.category, p.brand, SUM(oi.quantity) AS units_sold, SUM(oi.total_item_price) AS revenue FROM orderitems oi JOIN products p ON oi.product_id = p.id JOIN orders o ON oi.order_id = o.id WHERE o.store_id = 2 GROUP BY p.id, p.product_name, p.category, p.brand ORDER BY revenue DESC LIMIT 10" --telegram-id TID
```

## Write Commands

### Inventory transfer (inter-store)

⚠ **Inventory is tracked per size/color variant.** Always include `--size` and `--color` when transferring. If the user doesn't specify size/color, **ask them** — do NOT make multiple lookup calls.

`--product` accepts a **product_id** (number) or a **product name** (string). The CLI resolves names automatically.

```bash
# store_manager (from_store_id is auto-set to their own store; --to-store can be any store):
node ~/.openclaw/skills/retail-api/scripts/retail-api.js transfer --product "Running Shoe EcoWear" --to-store 2 --quantity 15 --size 41 --color Mint --telegram-id TID
# country_manager (must specify from_store):
node ~/.openclaw/skills/retail-api/scripts/retail-api.js transfer --product 7 --from-store 4 --to-store 2 --quantity 15 --size L --color White --telegram-id TID
```

**Always use the `transfer` CLI command for transfers — NEVER use raw SQL INSERT into inventorytransfers.**

### Reorder request (supplier replenishment)

```bash
# store_manager (store_id auto-set):
node ~/.openclaw/skills/retail-api/scripts/retail-api.js reorder --product "Running Shoe ClimaTex" --quantity 30 --size M --color Black --telegram-id TID
# country_manager (must specify store):
node ~/.openclaw/skills/retail-api/scripts/retail-api.js reorder --product 12 --quantity 30 --store 3 --telegram-id TID
```

**Prefer the `reorder` CLI command over raw SQL INSERT** — it handles `triggered_by`, `status`, and `requested_at` automatically.

## SQL Tips for the `query` Command

- **Always use JOINs** in a single query — never split into multiple exec calls.
- **Always filter and sort in SQL** — use `ORDER BY` + `LIMIT`, don't fetch all rows.
- **Use `SELECT DISTINCT`** on product-level fields when listing products for a store (Inventory has one row per size/color variant).
- **Use `ILIKE`** for fuzzy name matching: `WHERE p.product_name ILIKE '%jacket%'`.
- **Prefer views** for common questions: `InventoryAvailable` for stock, `LowStockAlerts` for low-stock items, `Customer360` for customer profiles.
- **Always add `LIMIT 50`** unless the user explicitly asks for all rows.
- **Use the exact column names** from the schema above. Do not guess.

### CRITICAL: Views use flat column names — NO table aliases

Views already expose pre-named columns (`store_name`, `product_name`, `brand`, `size`, etc.).
When querying a view directly, use column names **without any prefix**.

**WRONG** — causes `missing FROM-clause entry for table "p"` (HTTP 400):
```sql
SELECT p.name, s.name, i.size FROM LowStockAlerts
```

**CORRECT** — use the view's own column names:
```sql
SELECT product_name, store_name, size FROM LowStockAlerts
```

Table alias prefixes (`s.`, `p.`, `i.`, `rr.`) are ONLY for queries that JOIN base tables:
```sql
SELECT s.name AS store_name, p.name AS product_name
FROM inventory i JOIN stores s ON i.store_id = s.store_id JOIN products p ON i.product_id = p.product_id
```

**Simple rule: FROM has only a view? → No prefixes. FROM has JOINed tables? → Use aliases.**

## Minimal examples

Active promotions:

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js promotions --telegram-id TID
```

Inventory for a store:

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js inventory --store 3 --telegram-id TID
```

Complex reporting query:

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js query "SELECT s.name, SUM(o.total_amount) AS revenue FROM Orders o JOIN Stores s ON o.store_id = s.store_id WHERE o.status = 'completed' GROUP BY s.name ORDER BY revenue DESC" --telegram-id TID
```

Transfer stock (⚠ always include --size and --color):

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js transfer --product "Running Shoe EcoWear" --to-store 2 --quantity 10 --size 41 --color Mint --telegram-id TID
```

Reorder stock:

```bash
node ~/.openclaw/skills/retail-api/scripts/retail-api.js reorder --product "Wool Coat NeoFit" --quantity 30 --telegram-id TID
```

## RBAC Rules

**See SOUL.md for the full pre-flight authorization check.** Before any write operation, you MUST apply the rules defined there. Do not call the CLI until the check passes.

Summary:
- `country_manager` → full read + write across all stores
- `store_manager` → read all stores; write own store only; approve own store's reorders only; CANNOT approve transfers
- `data_analyst` → read-only (HTTP 403 on any write)

Reorder approval SQL (store_manager, own store only):
```sql
UPDATE reorderrequests SET status='approved' WHERE reorder_id=N AND store_id=MYSTORE
```

## Database Schema

Use ONLY the column names listed below. Do not guess or invent columns.

### Tables

**Stores** (PK: store_id)
store_id INT, name VARCHAR, city VARCHAR, country VARCHAR, region VARCHAR, address TEXT, phone VARCHAR, is_active BOOL, opened_at DATE, manager_id INT → Employees(employee_id)

**Employees** (PK: employee_id, UNIQUE: email)
employee_id INT, store_id INT → Stores(store_id), first_name VARCHAR, last_name VARCHAR, email VARCHAR, role VARCHAR, country VARCHAR, is_active BOOL, hired_at DATE

**Customers** (PK: customer_id, UNIQUE: email)
customer_id INT, first_name VARCHAR, last_name VARCHAR, full_name VARCHAR (generated: first_name || ' ' || last_name), email VARCHAR, phone VARCHAR, preferred_store_id INT → Stores(store_id), date_of_birth DATE, gender VARCHAR, registration_date TIMESTAMP

**Products** (PK: id)
id INT, product_name VARCHAR, description TEXT, category VARCHAR, subcategory VARCHAR, brand VARCHAR, gender_target VARCHAR, sustainability_score NUMERIC, season VARCHAR, price NUMERIC, is_active BOOL

**Inventory** (PK: inventory_id, UNIQUE: store_id+product_id+size+color)
inventory_id INT, store_id INT → Stores(store_id), product_id INT → Products(id), size VARCHAR, color VARCHAR, quantity_on_hand INT, quantity_reserved INT, reorder_level INT, reorder_quantity INT, last_restocked_at TIMESTAMP

Note: there is NO `quantity_available` column in Inventory. Use the `InventoryAvailable` view or compute `quantity_on_hand - quantity_reserved`.

**Orders** (PK: id)
id INT, customer_id INT → Customers(customer_id), store_id INT → Stores(store_id), employee_id INT → Employees(employee_id), order_channel VARCHAR, status VARCHAR, subtotal NUMERIC, discount_amount NUMERIC, total_amount NUMERIC, order_date TIMESTAMP

**OrderItems** (PK: order_item_id)
order_item_id INT, order_id INT → Orders(id), inventory_id INT → Inventory(inventory_id), product_id INT → Products(id), promotion_id INT → Promotions(promotion_id), quantity INT, unit_price NUMERIC, discount_amount NUMERIC, total_item_price NUMERIC

**Promotions** (PK: promotion_id)
promotion_id INT, name VARCHAR, description TEXT, discount_type VARCHAR, discount_value NUMERIC, buy_x_quantity INT, get_y_quantity INT, min_purchase_amount NUMERIC, applicable_to VARCHAR, applicable_value VARCHAR, store_id INT → Stores(store_id), start_date DATE, end_date DATE, is_active BOOL, created_by INT → Employees(employee_id)

**InventoryTransfers** (PK: transfer_id)
transfer_id INT, from_store_id INT → Stores(store_id), to_store_id INT → Stores(store_id), product_id INT → Products(id), size VARCHAR, color VARCHAR, quantity INT, requested_by INT → Employees(employee_id), approved_by INT → Employees(employee_id), status VARCHAR, notes TEXT, requested_at TIMESTAMP, completed_at TIMESTAMP

**ReorderRequests** (PK: reorder_id)
reorder_id INT, store_id INT → Stores(store_id), product_id INT → Products(id), size VARCHAR, color VARCHAR, requested_quantity INT, triggered_by VARCHAR(20) NOT NULL — CHECK: must be `'manual'` or `'automatic'` (no other values accepted — NOT a Telegram ID or integer), requested_by INT → Employees(employee_id), status VARCHAR NOT NULL DEFAULT 'pending' — CHECK: one of `'pending'`, `'approved'`, `'ordered'`, `'received'`, `'cancelled'`, supplier_reference VARCHAR, expected_delivery DATE, requested_at TIMESTAMP, received_at TIMESTAMP

### Views (pre-computed, prefer these for common queries)

**InventoryAvailable** — stock levels with computed availability
All Inventory columns plus: store_name, city, country, product_name, category, brand, season, quantity_available (= on_hand - reserved), needs_reorder BOOL, selling_price

**LowStockAlerts** — items at or below reorder threshold
store_id, store_name, product_id, product_name, category, brand, size, color, quantity_on_hand, quantity_reserved, quantity_available, reorder_level, suggested_reorder_qty, needs_reorder

**SalesPerformanceByStore** — monthly revenue per store
country, region, store_id, store_name, sales_month, total_orders, unique_customers, revenue, total_discounts, avg_order_value

**TopProductsByRevenue** — top-selling products
country, product_id, product_name, category, brand, season, units_sold, revenue

**Customer360** — customer profile with purchase summary
customer_id, full_name, email, phone, gender, date_of_birth, registration_date, preferred_store, total_orders, lifetime_value, last_order_date, avg_order_value

**ActivePromotions** — currently active promotions (filtered by date + is_active)
promotion_id, name, description, discount_type, discount_value, buy_x_quantity, get_y_quantity, min_purchase_amount, applicable_to, applicable_value, applicable_store (VARCHAR — store NAME, e.g., `'NemoClaw Barcelona'`, `'All Stores'`; NOT a store_id), start_date, end_date
⚠ `applicable_store` is a **store name string**, not an integer. To get promotions for a store: `WHERE applicable_store = 'NemoClaw Barcelona' OR applicable_store = 'All Stores'`

### Tips to avoid common mistakes

- Stores has `name`, NOT `store_name`. Use `s.name` with alias: `s.name AS store_name`.
- Inventory has NO `quantity_available`. Use the `InventoryAvailable` view or `quantity_on_hand - quantity_reserved`.
- **NEVER prefix columns with table aliases when querying a view.** Views are flat — `SELECT product_name FROM LowStockAlerts`, NOT `SELECT p.product_name FROM LowStockAlerts`.
- Orders date column is `order_date`, NOT `purchase_date`, `date`, or `order_time`.
- ReorderRequests `triggered_by` must be exactly `'manual'` or `'automatic'`. It is NOT a Telegram ID, user ID, or integer.
- **Use `transfer` / `reorder` CLI commands** for write operations — do NOT use raw SQL INSERT.
- **ActivePromotions view: `applicable_store` is a store NAME string** (e.g., `'NemoClaw Barcelona'`, `'All Stores'`), NOT a store_id integer.
