# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


RECIPE_DIR = Path(__file__).resolve().parents[2]
MODULE_PATH = (
    RECIPE_DIR
    / "extras/source-etls/forums-etl/refresh_api_views.py"
)


class FakeSQL(str):
    def format(self, identifier: "FakeIdentifier") -> "FakeSQL":
        return FakeSQL(self.replace("{}", f'"{identifier.name}"'))


class FakeIdentifier:
    def __init__(self, name: str) -> None:
        self.name = name


class FakeCursor:
    def __init__(self, table_exists: bool) -> None:
        self.table_exists = table_exists
        self.statements: list[str] = []

    def __enter__(self) -> "FakeCursor":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, statement: object) -> None:
        self.statements.append(str(statement))

    def fetchone(self) -> tuple[str | None]:
        return ("forums_etl.forum_topics" if self.table_exists else None,)


class FakeConnection:
    def __init__(self, cursor: FakeCursor) -> None:
        self._cursor = cursor

    def __enter__(self) -> "FakeConnection":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def cursor(self) -> FakeCursor:
        return self._cursor


def load_module(cursor: FakeCursor):
    fake_psycopg = types.ModuleType("psycopg")
    fake_psycopg.sql = types.SimpleNamespace(SQL=FakeSQL, Identifier=FakeIdentifier)
    fake_psycopg.connect = lambda **_kwargs: FakeConnection(cursor)

    previous = sys.modules.get("psycopg")
    sys.modules["psycopg"] = fake_psycopg
    try:
        spec = importlib.util.spec_from_file_location("refresh_api_views", MODULE_PATH)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        if previous is None:
            sys.modules.pop("psycopg", None)
        else:
            sys.modules["psycopg"] = previous


def set_database_env(monkeypatch) -> None:
    for key, value in {
        "POSTGRES_HOST": "postgres",
        "POSTGRES_DB": "source_etls",
        "POSTGRES_USER": "source_etl_writer",
        "POSTGRES_PASSWORD": "test-only",
        "SOURCE_ETL_POSTGRES_READER_USER": "source_etl_reader",
    }.items():
        monkeypatch.setenv(key, value)


def test_empty_source_creates_typed_empty_view(monkeypatch) -> None:
    cursor = FakeCursor(table_exists=False)
    module = load_module(cursor)
    set_database_env(monkeypatch)

    module.main()

    rendered = "\n".join(cursor.statements)
    assert "CREATE VIEW api.forum_topics" in rendered
    assert 'GRANT SELECT ON api.forum_topics TO "source_etl_reader"' in rendered
    assert "NOTIFY pgrst, 'reload schema'" in rendered
    assert "SELECT api.refresh_views()" not in rendered


def test_populated_source_replaces_fallback_with_normal_view(monkeypatch) -> None:
    cursor = FakeCursor(table_exists=True)
    module = load_module(cursor)
    set_database_env(monkeypatch)

    module.main()

    assert cursor.statements[-2:] == [
        "DROP VIEW IF EXISTS api.forum_topics",
        "SELECT api.refresh_views()",
    ]
