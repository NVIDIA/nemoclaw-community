#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# ─── Database seed script ──────────────────────────────────────
# Runs inside a postgres:17.3 container connected to retail_database.
# Loads CSV data in FK-safe order with an idempotency guard.
set -e

PSQL="psql -h retail_database -U $PSQL_USER -d $PSQL_DB"

echo "Waiting for Postgres schema (Employees table)..."
until $PSQL -c "SELECT 1 FROM Employees LIMIT 1" >/dev/null 2>&1; do
  sleep 3
done
echo "Schema ready."

# Idempotency: skip if already seeded
COUNT=$($PSQL -t -c "SELECT COUNT(*) FROM Employees" 2>/dev/null | tr -d ' \n')
if [ "${COUNT:-0}" -gt "0" ]; then
  echo "Database already seeded (${COUNT} employees). Skipping."
  exit 0
fi

echo "=== Seeding database ==="

# 1. Stores (without manager_id — Employees don't exist yet)
echo "  [1/11] Stores..."
$PSQL -c "\copy Stores (store_id, name, city, country, region, address, phone, is_active, opened_at) FROM '/data/csv/Stores.csv' CSV HEADER NULL ''"

# 2. Employees
echo "  [2/11] Employees..."
$PSQL -c "\copy Employees (employee_id, store_id, first_name, last_name, email, role, country, is_active, hired_at, password_hash) FROM '/data/csv/Employees.csv' CSV HEADER NULL ''"

# 3. Back-fill Stores.manager_id
# Madrid(1)→Raffaele(1), Barcelona(2)→Paula(3), Valencia(3)→Claudia(4), Sevilla(4)→Iñigo(2), Bilbao(5)→Sergio Pérez(6)
echo "  [3/11] Stores.manager_id backfill..."
$PSQL -c "UPDATE Stores s SET manager_id = src.manager_id FROM (VALUES (1,1),(2,3),(3,4),(4,2),(5,6)) AS src(store_id, manager_id) WHERE s.store_id = src.store_id;"

# 4. Customers
echo "  [4/11] Customers..."
$PSQL -c "\copy Customers (customer_id, first_name, last_name, email, phone, preferred_store_id, date_of_birth, gender, registration_date) FROM '/data/csv/Customers.csv' CSV HEADER NULL ''"

# 5. Products
echo "  [5/11] Products..."
$PSQL -c "\copy Products (id, product_name, description, category, subcategory, brand, gender_target, sustainability_score, season, price, is_active) FROM '/data/csv/Products.csv' CSV HEADER NULL ''"

# 6. Inventory
echo "  [6/11] Inventory..."
$PSQL -c "\copy Inventory (inventory_id, store_id, product_id, size, color, quantity_on_hand, quantity_reserved, reorder_level, reorder_quantity, last_restocked_at) FROM '/data/csv/Inventory.csv' CSV HEADER NULL ''"

# 7. Promotions
echo "  [7/11] Promotions..."
$PSQL -c "\copy Promotions (promotion_id, name, description, discount_type, discount_value, buy_x_quantity, get_y_quantity, min_purchase_amount, applicable_to, applicable_value, store_id, start_date, end_date, is_active, created_by) FROM '/data/csv/Promotions.csv' CSV HEADER NULL ''"

# 8. Orders
echo "  [8/11] Orders..."
$PSQL -c "\copy Orders (id, customer_id, store_id, employee_id, order_channel, status, subtotal, discount_amount, total_amount, order_date) FROM '/data/csv/Orders.csv' CSV HEADER NULL ''"

# 9. OrderItems
echo "  [9/11] OrderItems..."
$PSQL -c "\copy OrderItems (order_item_id, order_id, inventory_id, promotion_id, quantity, unit_price, discount_amount, total_item_price) FROM '/data/csv/OrderItems.csv' CSV HEADER NULL ''"

# 9b. Backfill OrderItems.product_id from Inventory
echo "  [9b] Backfilling OrderItems.product_id..."
$PSQL -c "UPDATE OrderItems oi SET product_id = i.product_id FROM Inventory i WHERE i.inventory_id = oi.inventory_id;"

# 10. ReorderRequests
echo "  [10/11] ReorderRequests..."
$PSQL -c "\copy ReorderRequests (reorder_id, store_id, product_id, size, color, requested_quantity, triggered_by, requested_by, status, supplier_reference, expected_delivery, requested_at, received_at) FROM '/data/csv/ReorderRequests.csv' CSV HEADER NULL ''"

# 11. InventoryTransfers
echo "  [11/12] InventoryTransfers..."
$PSQL -c "\copy InventoryTransfers (transfer_id, from_store_id, to_store_id, product_id, size, color, quantity, requested_by, approved_by, status, notes, requested_at, completed_at) FROM '/data/csv/InventoryTransfers.csv' CSV HEADER NULL ''"

# 12. TelegramAuth — map Telegram user IDs to employees
echo "  [12/12] TelegramAuth..."
$PSQL -c "\copy TelegramAuth (telegram_id, employee_id) FROM '/data/csv/TelegramAuth.csv' CSV HEADER"

# 13. Reset all SERIAL sequences after CSV seed (CSV loads explicit IDs
#     but does not advance the sequences, causing PK collisions on INSERT)
echo "  [13/13] Resetting SERIAL sequences..."
$PSQL <<'SQL'
SELECT setval('stores_store_id_seq',              (SELECT MAX(store_id)      FROM Stores));
SELECT setval('employees_employee_id_seq',        (SELECT MAX(employee_id)   FROM Employees));
SELECT setval('customers_customer_id_seq',        (SELECT MAX(customer_id)   FROM Customers));
SELECT setval('products_id_seq',                  (SELECT MAX(id)            FROM Products));
SELECT setval('inventory_inventory_id_seq',       (SELECT MAX(inventory_id)  FROM Inventory));
SELECT setval('inventorytransfers_transfer_id_seq',(SELECT MAX(transfer_id)  FROM InventoryTransfers));
SELECT setval('reorderrequests_reorder_id_seq',   (SELECT MAX(reorder_id)    FROM ReorderRequests));
SELECT setval('promotions_promotion_id_seq',      (SELECT MAX(promotion_id)  FROM Promotions));
SELECT setval('orders_id_seq',                    (SELECT MAX(id)            FROM Orders));
SELECT setval('orderitems_order_item_id_seq',     (SELECT MAX(order_item_id) FROM OrderItems));
SQL

echo ""
echo "=== Verifying row counts ==="
$PSQL <<'SQL'
  SELECT 'Stores'              AS "table", COUNT(*) AS rows FROM Stores
  UNION ALL SELECT 'Employees',            COUNT(*) FROM Employees
  UNION ALL SELECT 'Customers',            COUNT(*) FROM Customers
  UNION ALL SELECT 'Products',             COUNT(*) FROM Products
  UNION ALL SELECT 'Inventory',            COUNT(*) FROM Inventory
  UNION ALL SELECT 'Promotions',           COUNT(*) FROM Promotions
  UNION ALL SELECT 'Orders',               COUNT(*) FROM Orders
  UNION ALL SELECT 'OrderItems',           COUNT(*) FROM OrderItems
  UNION ALL SELECT 'ReorderRequests',      COUNT(*) FROM ReorderRequests
  UNION ALL SELECT 'InventoryTransfers',   COUNT(*) FROM InventoryTransfers
  UNION ALL SELECT 'TelegramAuth',          COUNT(*) FROM TelegramAuth
  ORDER BY "table";
SQL

echo ""
echo "=== Seed complete ==="
