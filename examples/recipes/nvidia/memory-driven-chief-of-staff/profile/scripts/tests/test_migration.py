# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: schema migration."""

import sqlite3, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from migrate import SCHEMA_VERSION, SchemaFromTheFuture, current_version, migrate, open_store  # noqa: E402

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")


class TestMigration(unittest.TestCase):

    def fresh(self):
        p = Path(tempfile.mkdtemp()) / "state.db"
        c = sqlite3.connect(p); c.executescript(SCHEMA); c.commit(); c.close()
        return p

    def test_a_fresh_store_reports_the_current_version(self):
        with sqlite3.connect(self.fresh()) as c:
            self.assertEqual(current_version(c), SCHEMA_VERSION)

    def test_migrating_an_up_to_date_store_does_nothing(self):
        # Every job calls this on startup, so a no-op has to be genuinely free.
        with sqlite3.connect(self.fresh()) as c:
            self.assertEqual(migrate(c), [])

    def test_migration_is_idempotent(self):
        p = self.fresh()
        with sqlite3.connect(p) as c:
            migrate(c); migrate(c)
            self.assertEqual(current_version(c), SCHEMA_VERSION)

    def test_a_store_from_the_future_is_refused_rather_than_opened(self):
        p = self.fresh()
        with sqlite3.connect(p) as c:
            c.execute("UPDATE meta SET value=? WHERE key='schema_version'",
                      (str(SCHEMA_VERSION + 5),))
        with self.assertRaises(SchemaFromTheFuture):
            open_store(p)

    def test_a_versionless_store_migrates_up_from_zero(self):
        p = self.fresh()
        with sqlite3.connect(p) as c:
            c.execute("DELETE FROM meta WHERE key='schema_version'")
        with sqlite3.connect(p) as c:
            self.assertEqual(current_version(c), 0)
            self.assertEqual(migrate(c), list(range(1, SCHEMA_VERSION + 1)))
            self.assertEqual(current_version(c), SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main(verbosity=2)
