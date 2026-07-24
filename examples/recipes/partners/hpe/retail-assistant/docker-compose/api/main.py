# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
NemoClaw Retail API
-------------------
A thin SQL-proxy API with JWT authentication and PostgreSQL-level RBAC.

RBAC is enforced by switching the PostgreSQL role per request:
  - store_manager / country_manager  → nemoclaw_manager      (full read/write)
  - data_analyst                     → nemoclaw_data_analyst (read-only on all tables)

The database itself rejects any write from a data_analyst — the application
never needs to parse or validate SQL.
"""

import os
import bcrypt as _bcrypt
import psycopg2
import psycopg2.extras
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv()

# =============================================================
# Config
# =============================================================

DB_HOST     = os.getenv("PSQL_HOST", "retail_database")
DB_PORT     = int(os.getenv("PSQL_PORT", "5432"))
DB_NAME     = os.getenv("PSQL_DB", "retail")
DB_USER     = os.getenv("PSQL_USER", "admin")
DB_PASSWORD = os.getenv("PSQL_PASSWORD", "admin")

JWT_SECRET    = os.getenv("JWT_SECRET", "change-me-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRE_MINUTES = 60

# Map application roles → PostgreSQL roles
PG_ROLE_MAP = {
    "country_manager":  "nemoclaw_country_manager",
    "store_manager":    "nemoclaw_manager",
    "data_analyst":  "nemoclaw_data_analyst",
}

# =============================================================
# App + security
# =============================================================

app = FastAPI(title="NemoClaw Retail API", version="1.0.0")

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


# =============================================================
# Database helpers
# =============================================================

def get_connection():
    return psycopg2.connect(
        host=DB_HOST, port=DB_PORT,
        dbname=DB_NAME, user=DB_USER, password=DB_PASSWORD,
    )


def execute_as_role(sql: str, params: list, pg_role: str, store_id: int | None = None) -> list[dict]:
    """
    Run `sql` inside a transaction where the active PG role is `pg_role`.
    SET LOCAL ROLE is scoped to the transaction — it resets automatically on commit/rollback.
    store_id is written to app.current_store_id for Row Level Security policies on
    InventoryTransfers and ReorderRequests (0 = country_manager / no-store context).
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            # Switch role for this transaction only
            cur.execute(f"SET LOCAL ROLE {pg_role};")
            # Set store context for RLS policies (0 never matches a real store_id)
            cur.execute("SET LOCAL app.current_store_id TO %s", (str(store_id if store_id is not None else 0),))
            try:
                if params:
                    cur.execute(sql, params)
                else:
                    cur.execute(sql)
            except IndexError:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="SQL contains %s placeholders but params list is empty or mismatched.",
                )
            except psycopg2.errors.InsufficientPrivilege:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Your role does not have permission to perform this operation.",
                )
            except psycopg2.Error as e:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=str(e).split("\n")[0],
                )
            if cur.description:
                rows = cur.fetchall()
                return [dict(r) for r in rows]
            conn.commit()
            return [{"affected_rows": cur.rowcount}]


# =============================================================
# Auth helpers
# =============================================================

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    employee_id: int
    role: str
    store_id: int | None


class CurrentEmployee(BaseModel):
    employee_id: int
    email: str
    role: str
    store_id: int | None
    country: str | None
    pg_role: str


def create_token(data: dict) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + timedelta(minutes=JWT_EXPIRE_MINUTES)
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def get_current_employee(token: str = Depends(oauth2_scheme)) -> CurrentEmployee:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        employee_id: int = payload.get("employee_id")
        if employee_id is None:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    return CurrentEmployee(
        employee_id=payload["employee_id"],
        email=payload["email"],
        role=payload["role"],
        store_id=payload.get("store_id"),
        country=payload.get("country"),
        pg_role=PG_ROLE_MAP[payload["role"]],
    )


# =============================================================
# Endpoints
# =============================================================

# --- Auth ---

@app.post("/auth/login", response_model=TokenResponse, tags=["Auth"])
def login(form: OAuth2PasswordRequestForm = Depends()):
    """
    Authenticate with email + password. Returns a JWT.
    For the demo, password is validated as bcrypt hash stored in Employees.
    If no hash is stored, any non-empty password is accepted (demo mode).
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT employee_id, email, role, store_id, country, password_hash "
                "FROM Employees WHERE email = %s AND is_active = TRUE",
                (form.username,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored_hash = row.get("password_hash")
    if not stored_hash:
        # No hash stored — reject (all employees must have a password)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not _bcrypt.checkpw(form.password.encode(), stored_hash.encode()):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = create_token({
        "employee_id": row["employee_id"],
        "email":       row["email"],
        "role":        row["role"],
        "store_id":    row["store_id"],
        "country":     row["country"],
    })
    return TokenResponse(
        access_token=token,
        employee_id=row["employee_id"],
        role=row["role"],
        store_id=row["store_id"],
    )


class TelegramLoginRequest(BaseModel):
    telegram_id: str


@app.post("/auth/login-telegram", response_model=TokenResponse, tags=["Auth"])
def login_telegram(body: TelegramLoginRequest):
    """
    Authenticate via Telegram user ID. Returns a JWT.
    Looks up the telegram_id in the TelegramAuth table, joins to Employees,
    and issues the same JWT as the password-based login.
    No password required — Telegram has already verified the user's identity.
    """
    with get_connection() as conn:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                "SELECT e.employee_id, e.email, e.role, e.store_id, e.country "
                "FROM TelegramAuth ta "
                "JOIN Employees e ON ta.employee_id = e.employee_id "
                "WHERE ta.telegram_id = %s AND e.is_active = TRUE",
                (body.telegram_id,),
            )
            row = cur.fetchone()

    if not row:
        raise HTTPException(status_code=401, detail="Telegram ID not authorised")

    token = create_token({
        "employee_id": row["employee_id"],
        "email":       row["email"],
        "role":        row["role"],
        "store_id":    row["store_id"],
        "country":     row["country"],
    })
    return TokenResponse(
        access_token=token,
        employee_id=row["employee_id"],
        role=row["role"],
        store_id=row["store_id"],
    )


@app.get("/auth/me", tags=["Auth"])
def me(employee: CurrentEmployee = Depends(get_current_employee)):
    return employee


# --- Flexible query endpoint (the core agent tool) ---

class QueryRequest(BaseModel):
    sql: str
    params: list[Any] = []


@app.post("/query", tags=["Query"])
def query(
    body: QueryRequest,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    """
    Execute any SQL statement under the caller's PostgreSQL role.
    RBAC is enforced by the database:
      - data_analysts get a 403 on any write operation (fully read-only PG role).
      - managers can read and write all tables.
    """
    rows = execute_as_role(body.sql, body.params, employee.pg_role, employee.store_id)
    return {
        "role":  employee.role,
        "pg_role": employee.pg_role,
        "rows":  rows,
        "count": len(rows),
    }


# --- Convenience read endpoints (thin wrappers the agent can also call) ---

@app.get("/inventory", tags=["Inventory"])
def get_inventory(
    store_id: int | None = None,
    product_id: int | None = None,
    low_stock_only: bool = False,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    if low_stock_only:
        sql    = "SELECT * FROM LowStockAlerts WHERE 1=1"
        params = []
        if store_id:
            sql += " AND store_id = %s"; params.append(store_id)
    else:
        sql    = "SELECT * FROM InventoryAvailable WHERE 1=1"
        params = []
        if store_id:
            sql += " AND store_id = %s"; params.append(store_id)
        if product_id:
            sql += " AND product_id = %s"; params.append(product_id)

    return execute_as_role(sql, params, employee.pg_role, employee.store_id)


@app.get("/products", tags=["Products"])
def get_products(
    category: str | None = None,
    brand: str | None = None,
    season: str | None = None,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    sql    = "SELECT * FROM Products WHERE is_active = TRUE"
    params = []
    if category: sql += " AND category = %s"; params.append(category)
    if brand:    sql += " AND brand = %s";    params.append(brand)
    if season:   sql += " AND season = %s";   params.append(season)
    return execute_as_role(sql, params, employee.pg_role, employee.store_id)


@app.get("/customers", tags=["CRM"])
def get_customers(
    customer_id: int | None = None,
    email: str | None = None,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    if customer_id:
        sql    = "SELECT * FROM Customer360 WHERE customer_id = %s"
        params = [customer_id]
    elif email:
        sql    = "SELECT * FROM Customer360 WHERE email = %s"
        params = [email]
    else:
        sql    = "SELECT * FROM Customer360 ORDER BY lifetime_value DESC LIMIT 50"
        params = []
    return execute_as_role(sql, params, employee.pg_role, employee.store_id)


@app.get("/promotions", tags=["Promotions"])
def get_promotions(
    active_only: bool = True,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    if active_only:
        sql = "SELECT * FROM ActivePromotions ORDER BY end_date"
    else:
        sql = "SELECT * FROM Promotions ORDER BY start_date DESC"
    return execute_as_role(sql, [], employee.pg_role, employee.store_id)


@app.get("/sales-performance", tags=["Analytics"])
def sales_performance(
    store_id: int | None = None,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    sql    = "SELECT * FROM SalesPerformanceByStore WHERE 1=1"
    params = []
    if store_id:
        sql += " AND store_id = %s"; params.append(store_id)
    sql += " ORDER BY sales_month DESC"
    return execute_as_role(sql, params, employee.pg_role, employee.store_id)


class TransferBody(BaseModel):
    product_id: int
    to_store_id: int
    quantity: int
    size: str | None = None
    color: str | None = None
    notes: str | None = None
    from_store_id: int | None = None  # ignored for store_managers; used by country_manager


@app.post("/inventory/transfer", tags=["Inventory"])
def create_transfer(
    body: TransferBody,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    """
    Only managers may create inventory transfers.
    store_managers: from_store_id is always their own store (body field ignored).
    country_managers: must supply from_store_id.
    """
    if employee.role == "data_analyst":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data Analysts cannot create inventory transfers.",
        )

    if employee.role == "store_manager":
        if not employee.store_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Store manager has no store assigned.",
            )
        from_store_id = employee.store_id
    else:
        if not body.from_store_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="from_store_id is required for this role.",
            )
        from_store_id = body.from_store_id

    if from_store_id == body.to_store_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="from_store_id and to_store_id must be different.",
        )

    sql = """
        INSERT INTO InventoryTransfers
            (from_store_id, to_store_id, product_id, size, color, quantity, requested_by, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING transfer_id, from_store_id, to_store_id, product_id, quantity, status, requested_at
    """
    params = [
        from_store_id,
        body.to_store_id,
        body.product_id,
        body.size,
        body.color,
        body.quantity,
        employee.employee_id,
        body.notes,
    ]
    return execute_as_role(sql, params, employee.pg_role, employee.store_id)


class ReorderBody(BaseModel):
    product_id: int
    requested_quantity: int
    size: str | None = None
    color: str | None = None
    triggered_by: str = "manual"
    store_id: int | None = None  # ignored for store_managers; used by country_manager


@app.post("/reorder", tags=["Inventory"])
def create_reorder(
    body: ReorderBody,
    employee: CurrentEmployee = Depends(get_current_employee),
):
    """
    Only managers may create reorder requests.
    store_managers are always scoped to their own store (store_id field is ignored).
    country_managers may specify any store_id.
    """
    if employee.role == "data_analyst":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Data Analysts cannot create reorder requests.",
        )

    # Determine store_id — store_managers cannot override this
    if employee.role == "store_manager":
        if not employee.store_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Store manager has no store assigned.",
            )
        if body.store_id and body.store_id != employee.store_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Store managers can only create reorder requests for their own store (store_id={employee.store_id}).",
            )
        store_id = employee.store_id
    else:
        # country_manager / other manager roles
        if not body.store_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="store_id is required for this role.",
            )
        store_id = body.store_id

    sql = """
        INSERT INTO ReorderRequests
            (store_id, product_id, size, color, requested_quantity, triggered_by, requested_by)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        RETURNING reorder_id, store_id, product_id, requested_quantity, status, requested_at
    """
    params = [
        store_id,
        body.product_id,
        body.size,
        body.color,
        body.requested_quantity,
        body.triggered_by,
        employee.employee_id,
    ]
    return execute_as_role(sql, params, employee.pg_role, employee.store_id)
