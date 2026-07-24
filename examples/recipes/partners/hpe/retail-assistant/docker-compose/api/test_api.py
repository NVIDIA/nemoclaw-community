# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
NemoClaw Retail API — Integration Tests
Runs against the live stack (retail_database + retail_api containers must be up).

Run:
    python3 -m pytest api/test_api.py -v
    # or from inside the api/ folder:
    python3 -m pytest test_api.py -v

Install test deps (once):
    pip install pytest httpx
"""

import pytest
import httpx

BASE = "http://localhost:8000"

# ---------------------------------------------------------------------------
# Credentials (firstname lowercase + nemoclaw1234)
# ---------------------------------------------------------------------------
COUNTRY_MANAGER  = {"username": "amalia.cid@araz.es",         "password": "amalianemoclaw1234"}
STORE_MANAGER    = {"username": "inigo.varas@araz.es",         "password": "inigonemoclaw1234"}
DATA_ANALYST     = {"username": "maria.castro@araz.es",        "password": "marianemoclaw1234"}
WRONG_CREDS      = {"username": "nobody@araz.es",              "password": "wrong"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def login(creds: dict) -> str:
    """Return a Bearer token for the given credentials."""
    r = httpx.post(f"{BASE}/auth/login", data=creds)
    assert r.status_code == 200, f"Login failed: {r.text}"
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# 1. Authentication
# ---------------------------------------------------------------------------

class TestAuth:
    def test_login_country_manager_succeeds(self):
        r = httpx.post(f"{BASE}/auth/login", data=COUNTRY_MANAGER)
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "country_manager"
        assert body["store_id"] is None
        assert "access_token" in body

    def test_login_store_manager_succeeds(self):
        r = httpx.post(f"{BASE}/auth/login", data=STORE_MANAGER)
        assert r.status_code == 200
        body = r.json()
        assert body["role"] == "store_manager"
        assert body["store_id"] == 1          # Iñigo manages Madrid (store 1)

    def test_login_data_analyst_succeeds(self):
        r = httpx.post(f"{BASE}/auth/login", data=DATA_ANALYST)
        assert r.status_code == 200
        assert r.json()["role"] == "data_analyst"

    def test_login_wrong_credentials_rejected(self):
        r = httpx.post(f"{BASE}/auth/login", data=WRONG_CREDS)
        assert r.status_code == 401

    def test_login_wrong_password_rejected(self):
        r = httpx.post(f"{BASE}/auth/login", data={
            "username": COUNTRY_MANAGER["username"],
            "password": "notthepassword",
        })
        assert r.status_code == 401

    def test_me_returns_correct_role(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/auth/me", headers=auth(token))
        assert r.status_code == 200
        assert r.json()["role"] == "country_manager"
        assert r.json()["pg_role"] == "nemoclaw_manager"

    def test_me_data_analyst_pg_role(self):
        token = login(DATA_ANALYST)
        r = httpx.get(f"{BASE}/auth/me", headers=auth(token))
        assert r.status_code == 200
        assert r.json()["pg_role"] == "nemoclaw_data_analyst"

    def test_unauthenticated_request_rejected(self):
        r = httpx.get(f"{BASE}/inventory")
        assert r.status_code == 401

    def test_invalid_token_rejected(self):
        r = httpx.get(f"{BASE}/inventory", headers={"Authorization": "Bearer fake.jwt.token"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# 2. Inventory
# ---------------------------------------------------------------------------

class TestInventory:
    def test_country_manager_sees_all_stores(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/inventory", headers=auth(token))
        assert r.status_code == 200
        store_ids = {row["store_id"] for row in r.json()}
        assert len(store_ids) > 1            # must span multiple stores

    def test_store_manager_scoped_to_own_store(self):
        token = login(STORE_MANAGER)
        r = httpx.get(f"{BASE}/inventory", headers=auth(token))
        assert r.status_code == 200
        store_ids = {row["store_id"] for row in r.json()}
        assert store_ids == {1}              # Iñigo's store (Madrid = 1)

    def test_inventory_filter_by_store(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/inventory?store_id=2", headers=auth(token))
        assert r.status_code == 200
        assert all(row["store_id"] == 2 for row in r.json())

    def test_inventory_filter_by_product(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/inventory?product_id=1", headers=auth(token))
        assert r.status_code == 200
        assert all(row["product_id"] == 1 for row in r.json())

    def test_low_stock_alerts_returns_only_low_items(self):
        token = login(STORE_MANAGER)
        r = httpx.get(f"{BASE}/inventory?low_stock_only=true", headers=auth(token))
        assert r.status_code == 200
        rows = r.json()
        # Every row must have quantity_available <= reorder_level
        for row in rows:
            assert row["quantity_available"] <= row["reorder_level"]

    def test_demo_scenario_b_basic_tee_low_in_barcelona(self):
        """Scenario B: Basic Tee (product 5) critically low in Barcelona (store 2)."""
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/inventory?store_id=2&product_id=5&low_stock_only=true",
                      headers=auth(token))
        assert r.status_code == 200
        assert len(r.json()) > 0, "Expected low-stock rows for Basic Tee in Barcelona"

    def test_demo_scenario_a_overstock_wool_coat_madrid(self):
        """Scenario A: Wool Coat (product 15) has high stock in Madrid (store 1)."""
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/inventory?store_id=1&product_id=15", headers=auth(token))
        assert r.status_code == 200
        rows = r.json()
        assert any(row["quantity_on_hand"] >= 50 for row in rows), \
            "Expected over-stocked Wool Coat rows in Madrid"


# ---------------------------------------------------------------------------
# 3. Products
# ---------------------------------------------------------------------------

class TestProducts:
    def test_all_products_returned(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/products", headers=auth(token))
        assert r.status_code == 200
        assert len(r.json()) == 200

    def test_filter_by_category(self):
        token = login(DATA_ANALYST)
        r = httpx.get(f"{BASE}/products?category=Footwear", headers=auth(token))
        assert r.status_code == 200
        assert all(row["category"] == "Footwear" for row in r.json())

    def test_filter_by_brand(self):
        token = login(DATA_ANALYST)
        r = httpx.get(f"{BASE}/products?brand=EcoWear", headers=auth(token))
        assert r.status_code == 200
        assert all(row["brand"] == "EcoWear" for row in r.json())

    def test_filter_by_season(self):
        token = login(DATA_ANALYST)
        r = httpx.get(f"{BASE}/products?season=SS2026", headers=auth(token))
        assert r.status_code == 200
        assert all(row["season"] == "SS2026" for row in r.json())


# ---------------------------------------------------------------------------
# 4. Customers
# ---------------------------------------------------------------------------

class TestCustomers:
    def test_top_customers_by_lifetime_value(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/customers", headers=auth(token))
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) > 0
        # Should be sorted descending by lifetime_value
        values = [row["lifetime_value"] for row in rows]
        assert values == sorted(values, reverse=True)

    def test_lookup_by_customer_id(self):
        token = login(STORE_MANAGER)
        r = httpx.get(f"{BASE}/customers?customer_id=1", headers=auth(token))
        assert r.status_code == 200
        rows = r.json()
        assert len(rows) == 1
        assert rows[0]["customer_id"] == 1

    def test_lookup_by_email(self):
        # First get any customer's email via id
        token = login(COUNTRY_MANAGER)
        r1 = httpx.get(f"{BASE}/customers?customer_id=1", headers=auth(token))
        email = r1.json()[0]["email"]

        r2 = httpx.get(f"{BASE}/customers?email={email}", headers=auth(token))
        assert r2.status_code == 200
        assert r2.json()[0]["email"] == email


# ---------------------------------------------------------------------------
# 5. Promotions
# ---------------------------------------------------------------------------

class TestPromotions:
    def test_active_promotions_are_within_date_range(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/promotions?active_only=true", headers=auth(token))
        assert r.status_code == 200
        # All returned promos should be currently active (checked by the DB view)
        assert isinstance(r.json(), list)

    def test_all_promotions_includes_inactive(self):
        token = login(COUNTRY_MANAGER)
        active_r = httpx.get(f"{BASE}/promotions?active_only=true",  headers=auth(token))
        all_r    = httpx.get(f"{BASE}/promotions?active_only=false", headers=auth(token))
        assert all_r.status_code == 200
        assert len(all_r.json()) >= len(active_r.json())

    def test_demo_promotions_exist(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/promotions?active_only=false", headers=auth(token))
        names = {p["name"] for p in r.json()}
        assert "Summer Sale SS2025"    in names
        assert "AW2025 Coat Clearance" in names
        assert "Eco Reward — Organic Tee 10% Off" in names


# ---------------------------------------------------------------------------
# 6. Sales Performance
# ---------------------------------------------------------------------------

class TestSalesPerformance:
    def test_country_manager_sees_all_stores(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/sales-performance", headers=auth(token))
        assert r.status_code == 200
        store_ids = {row["store_id"] for row in r.json()}
        assert len(store_ids) > 1

    def test_store_manager_scoped_to_own_store(self):
        token = login(STORE_MANAGER)
        r = httpx.get(f"{BASE}/sales-performance", headers=auth(token))
        assert r.status_code == 200
        store_ids = {row["store_id"] for row in r.json()}
        assert store_ids == {1}

    def test_revenue_is_positive(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.get(f"{BASE}/sales-performance", headers=auth(token))
        assert all(float(row["revenue"]) > 0 for row in r.json())


# ---------------------------------------------------------------------------
# 7. Flexible /query endpoint
# ---------------------------------------------------------------------------

class TestQuery:
    def test_manager_can_run_select(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.post(f"{BASE}/query",
                       headers=auth(token),
                       json={"sql": "SELECT COUNT(*) AS total FROM Products"})
        assert r.status_code == 200
        assert r.json()["rows"][0]["total"] == 200

    def test_data_analyst_can_run_select(self):
        token = login(DATA_ANALYST)
        r = httpx.post(f"{BASE}/query",
                       headers=auth(token),
                       json={"sql": "SELECT store_id, SUM(quantity_on_hand) AS total "
                                    "FROM Inventory GROUP BY store_id ORDER BY store_id"})
        assert r.status_code == 200
        assert len(r.json()["rows"]) == 5     # 5 stores

    def test_parameterised_query(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.post(f"{BASE}/query",
                       headers=auth(token),
                       json={"sql": "SELECT * FROM Stores WHERE store_id = %s",
                             "params": [1]})
        assert r.status_code == 200
        assert r.json()["rows"][0]["city"] == "Madrid"

    def test_manager_can_insert_transfer(self):
        token = login(STORE_MANAGER)
        r = httpx.post(f"{BASE}/query",
                       headers=auth(token),
                       json={
                           "sql": (
                               "INSERT INTO InventoryTransfers "
                               "(from_store_id, to_store_id, product_id, size, color, "
                               " quantity, requested_by, status) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING transfer_id"
                           ),
                           "params": [1, 2, 5, "M", "White", 5, 2, "pending"],
                       })
        assert r.status_code == 200
        assert "transfer_id" in r.json()["rows"][0]

    def test_data_analyst_blocked_from_insert(self):
        """Core RBAC test: data_analyst PG role must be read-only."""
        token = login(DATA_ANALYST)
        r = httpx.post(f"{BASE}/query",
                       headers=auth(token),
                       json={
                           "sql": (
                               "INSERT INTO InventoryTransfers "
                               "(from_store_id, to_store_id, product_id, size, color, "
                               " quantity, requested_by, status) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"
                           ),
                           "params": [1, 2, 5, "M", "White", 5, 7, "pending"],
                       })
        assert r.status_code == 403

    def test_data_analyst_blocked_from_reorder_insert(self):
        """data_analyst cannot write to ReorderRequests either."""
        token = login(DATA_ANALYST)
        r = httpx.post(f"{BASE}/query",
                       headers=auth(token),
                       json={
                           "sql": (
                               "INSERT INTO ReorderRequests "
                               "(store_id, product_id, size, color, requested_quantity, "
                               " triggered_by, status) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s)"
                           ),
                           "params": [1, 5, "M", "White", 20, "manual", "pending"],
                       })
        assert r.status_code == 403

    def test_data_analyst_blocked_from_updating_inventory(self):
        """data_analyst cannot update Inventory quantities."""
        token = login(DATA_ANALYST)
        r = httpx.post(f"{BASE}/query",
                       headers=auth(token),
                       json={
                           "sql": "UPDATE Inventory SET quantity_on_hand = 999 WHERE inventory_id = 1",
                           "params": [],
                       })
        assert r.status_code == 403


# ---------------------------------------------------------------------------
# 8. /inventory/transfer and /reorder dedicated endpoints
# ---------------------------------------------------------------------------

class TestProtectedEndpoints:
    def test_data_analyst_blocked_from_transfer_endpoint(self):
        token = login(DATA_ANALYST)
        r = httpx.post(f"{BASE}/inventory/transfer",
                       headers=auth(token),
                       json={"sql": "SELECT 1", "params": []})
        assert r.status_code == 403
        assert "Data Analysts" in r.json()["detail"]

    def test_data_analyst_blocked_from_reorder_endpoint(self):
        token = login(DATA_ANALYST)
        r = httpx.post(f"{BASE}/reorder",
                       headers=auth(token),
                       json={"sql": "SELECT 1", "params": []})
        assert r.status_code == 403
        assert "Data Analysts" in r.json()["detail"]

    def test_store_manager_can_use_transfer_endpoint(self):
        token = login(STORE_MANAGER)
        r = httpx.post(f"{BASE}/inventory/transfer",
                       headers=auth(token),
                       json={
                           "sql": (
                               "INSERT INTO InventoryTransfers "
                               "(from_store_id, to_store_id, product_id, size, color, "
                               " quantity, requested_by, status) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING transfer_id"
                           ),
                           "params": [1, 3, 5, "L", "Black", 3, 2, "pending"],
                       })
        assert r.status_code == 200

    def test_country_manager_can_use_reorder_endpoint(self):
        token = login(COUNTRY_MANAGER)
        r = httpx.post(f"{BASE}/reorder",
                       headers=auth(token),
                       json={
                           "sql": (
                               "INSERT INTO ReorderRequests "
                               "(store_id, product_id, size, color, requested_quantity, "
                               " triggered_by, requested_by, status) "
                               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING reorder_id"
                           ),
                           "params": [2, 20, "One Size", "Navy", 25, "manual", 1, "pending"],
                       })
        assert r.status_code == 200
