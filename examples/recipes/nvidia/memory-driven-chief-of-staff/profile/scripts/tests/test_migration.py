# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: schema migration."""

import json, os, sqlite3, subprocess, sys, tempfile, unittest
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

    def test_an_older_store_gains_the_position_column(self):
        """v1 wrote the batch position straight into global_rank."""
        p = self.fresh()
        with sqlite3.connect(p) as c:
            c.executescript(
                "DROP INDEX IF EXISTS idx_obl_rank_unique;"
                "ALTER TABLE obligations DROP COLUMN batch_rank;")
            c.execute("UPDATE meta SET value='1' WHERE key='schema_version'")
            c.execute("INSERT INTO items(source_id, source, scope, event_at)"
                      " VALUES ('keep','email','inbox','2026-08-18T00:00:00Z')")
            c.execute("INSERT INTO obligations(id, source_id, title, priority, global_rank)"
                      " VALUES ('o1','keep','t','high',1)")
        with sqlite3.connect(p) as c:
            # Every step above v1 runs, in order, and lands on the current
            # version. Spelling the list out here would make each new
            # migration look like a regression in an unrelated test.
            self.assertEqual(migrate(c), list(range(2, SCHEMA_VERSION + 1)))
            self.assertEqual(current_version(c), SCHEMA_VERSION)
            cols = {r[1] for r in c.execute("PRAGMA table_info(obligations)")}
            self.assertIn("batch_rank", cols)
            # The old position is preserved as the batch position, and the
            # global one is cleared for the next write to re-derive.
            self.assertEqual(
                c.execute("SELECT batch_rank, global_rank FROM obligations").fetchone(),
                (1, None))
            self.assertEqual(c.execute("SELECT count(*) FROM items").fetchone()[0], 1)


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


class TestVersionGuardOnTheRealPath(unittest.TestCase):
    """A store from the future is refused before anything writes to it.

    Checking the version inside a migration helper is not protection if the
    executables never call that helper. These tests go through the paths a
    reader actually runs: the store opener every script begins with, and the
    writer's command line.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HERMES_HOME"] = self.tmp
        for m in ("_db", "migrate", "ranking", "apply_decisions"):
            sys.modules.pop(m, None)
        import _db                            # noqa: E402
        self._db = _db
        _db.ensure_store()
        self.db = _db.ledger_path()

    def _set_version(self, value):
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(value),))

    def test_ensure_store_refuses_a_newer_schema(self):
        import migrate                        # noqa: E402
        self._set_version(99)
        with self.assertRaises(migrate.SchemaFromTheFuture):
            self._db.ensure_store()

    def test_the_writer_exits_nonzero_and_writes_nothing(self):
        """The refusal reaches the command line, and no row is created."""
        self._set_version(99)
        env = json.dumps({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "CREATE", "rank": 1, "title": "t"}]})
        proc = subprocess.run(
            [sys.executable, str(HERE / "apply_decisions.py")],
            input=env, capture_output=True, text=True,
            env={**os.environ, "HERMES_HOME": self.tmp})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("99", proc.stderr)
        with sqlite3.connect(self.db) as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM obligations").fetchone()[0], 0)

    def test_an_older_store_is_migrated_rather_than_refused(self):
        """The guard is one-sided: behind is upgraded, ahead is refused."""
        import migrate                        # noqa: E402
        self._set_version(1)
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE obligations SET global_rank=NULL")
        self._db.ensure_store()
        with sqlite3.connect(self.db) as c:
            version = c.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        self.assertEqual(int(version), migrate.SCHEMA_VERSION)
