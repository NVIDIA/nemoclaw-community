# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: schema migration."""

import json, os, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
from migrate import MIGRATIONS, SCHEMA_VERSION, SchemaFromTheFuture, current_version, migrate, open_store  # noqa: E402

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

    def test_a_real_v1_store_upgrades_to_the_current_version(self):
        """Exercised against v1's own schema artifact, not a doctored current one.

        The shortcut — take the current schema and remove what v2 added — keeps
        every other column the real v1 had, so a genuine v1 database can still
        fail to open while the test passes. `schema-v1.sql` is the file that
        shipped, kept verbatim for this.
        """
        artifact = HERE / "schema-v1.sql"
        self.assertTrue(artifact.exists(), "the v1 schema artifact is missing")
        path = Path(tempfile.mkdtemp()) / "v1.db"
        with sqlite3.connect(path) as c:
            c.executescript(artifact.read_text(encoding="utf-8"))
            self.assertEqual(current_version(c), 1)
            columns = {row[1] for row in c.execute("PRAGMA table_info(items)")}
            self.assertNotIn("body_cleared_at", columns,
                             "the artifact is not really v1")

        with sqlite3.connect(path) as c:
            self.assertEqual(migrate(c), [2])
            self.assertEqual(current_version(c), SCHEMA_VERSION)
            columns = {row[1] for row in c.execute("PRAGMA table_info(items)")}
            self.assertIn("body_cleared_at", columns)

    def test_the_upgrade_keeps_the_rows_that_were_already_there(self):
        """An upgrade that loses a message is worse than one that refuses."""
        artifact = HERE / "schema-v1.sql"
        path = Path(tempfile.mkdtemp()) / "v1.db"
        with sqlite3.connect(path) as c:
            c.executescript(artifact.read_text(encoding="utf-8"))
            c.execute("INSERT INTO items(source_id, source, scope, event_at,"
                      " body, state) VALUES"
                      " ('m1','email','inbox','2026-08-01T00:00:00Z','kept','pending')")
        with sqlite3.connect(path) as c:
            migrate(c)
            row = c.execute("SELECT body, body_cleared_at FROM items"
                            " WHERE source_id='m1'").fetchone()
        self.assertEqual(row[0], "kept")
        self.assertIsNone(row[1], "an upgraded row was marked as cleared")

    def test_the_v1_artifact_is_never_quietly_edited(self):
        """It is frozen: a schema change goes in schema.sql and a migration."""
        artifact = (HERE / "schema-v1.sql").read_text(encoding="utf-8")
        self.assertIn("'schema_version', '1'", artifact)
        self.assertNotIn("body_cleared_at", artifact)

    def test_the_shipped_schema_opens_a_store_that_the_shipped_schema_made(self):
        """The artifact under test is the one the recipe installs."""
        p = self.fresh()
        with sqlite3.connect(p) as c:
            columns = {r[1] for r in c.execute("PRAGMA table_info(items)")}
        # Columns belonging to phases that have not shipped must not be here:
        # one of them arrived by a bad merge and broke opening a real store.
        self.assertNotIn("deleted_at", columns)
        with sqlite3.connect(p) as c:
            self.assertEqual(migrate(c), [])

    def test_a_versionless_store_migrates_up_from_zero(self):
        p = self.fresh()
        with sqlite3.connect(p) as c:
            c.execute("DELETE FROM meta WHERE key='schema_version'")
        with sqlite3.connect(p) as c:
            self.assertEqual(current_version(c), 0)
            self.assertEqual(migrate(c), list(range(1, SCHEMA_VERSION + 1)))
            self.assertEqual(current_version(c), SCHEMA_VERSION)


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

    def _fake_a_future_store(self):
        """A v99 store that dropped a table we ship and added one we do not."""
        with sqlite3.connect(self.db) as c:
            c.execute("UPDATE meta SET value='99' WHERE key='schema_version'")
            c.execute("DROP TABLE events")
            c.execute("CREATE TABLE v99_notes (id TEXT)")

    def _tables(self):
        with sqlite3.connect(self.db) as c:
            return sorted(r[0] for r in c.execute(
                "SELECT name FROM sqlite_master"
                " WHERE type='table' AND name NOT LIKE 'sqlite_%'"))

    def test_the_schema_is_not_touched_before_the_refusal(self):
        """"Refused before any write" has to include the baseline DDL.

        `CREATE TABLE IF NOT EXISTS` is idempotent against our own schema and
        not against a later version's. Running it first silently recreated a
        table that version had dropped, and the store was left carrying a
        table from a schema the refusing code does not understand. Asserting
        only that no rows were written missed it, because the damage is DDL.
        """
        import migrate                        # noqa: E402
        self._fake_a_future_store()
        before = self._tables()
        self.assertNotIn("events", before)     # the future version dropped it
        with self.assertRaises(migrate.SchemaFromTheFuture):
            self._db.ensure_store()
        self.assertEqual(self._tables(), before)

    def test_the_version_is_not_rewritten_by_the_refusal(self):
        self._fake_a_future_store()
        with self.assertRaises(Exception):
            self._db.ensure_store()
        with sqlite3.connect(self.db) as c:
            version = c.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
        self.assertEqual(int(version), 99)

    def test_a_store_with_no_meta_table_is_not_mistaken_for_the_future(self):
        """The pre-check runs before the baseline exists, so it must tolerate that."""
        import migrate                        # noqa: E402
        with sqlite3.connect(self.db) as c:
            c.execute("DROP TABLE meta")
        with sqlite3.connect(self.db) as c:
            migrate.refuse_if_from_the_future(c)      # must not raise
        self.assertTrue(self._db.ensure_store().is_file())

    def test_a_versionless_v1_store_is_migrated_not_stamped_current(self):
        """The baseline DDL must not vote on the version of a store it finds.

        `schema.sql` carries `INSERT OR IGNORE ... ('schema_version', '2')`.
        Run over a real v1 store whose version row is missing — a restored
        backup, a hand-built table, any reason — it stamps 2 over a database
        with none of the v2 columns, and `migrate` then sees its own version
        and does nothing. The store ends up claiming a shape it does not have,
        which surfaces as a missing column in whichever job touches it first.
        """
        import migrate                        # noqa: E402
        v1 = (HERE / "schema-v1.sql").read_text(encoding="utf-8")
        with sqlite3.connect(self.db) as c:
            c.executescript("DROP TABLE IF EXISTS items;"
                            "DROP TABLE IF EXISTS obligations;"
                            "DROP TABLE IF EXISTS events;"
                            "DROP TABLE IF EXISTS cursors;"
                            "DROP TABLE IF EXISTS meta;")
            c.executescript(v1)
            c.execute("DELETE FROM meta WHERE key='schema_version'")

        self._db.ensure_store()

        with sqlite3.connect(self.db) as c:
            version = c.execute(
                "SELECT value FROM meta WHERE key='schema_version'").fetchone()[0]
            columns = {r[1] for r in c.execute("PRAGMA table_info(items)")}
        self.assertEqual(int(version), migrate.SCHEMA_VERSION)
        self.assertIn("body_cleared_at", columns,
                      "store reports the current version without the column "
                      "that version added")

    def test_a_versionless_store_keeps_the_rows_it_already_held(self):
        """The repair must not be a rebuild: an unversioned store has data."""
        v1 = (HERE / "schema-v1.sql").read_text(encoding="utf-8")
        with sqlite3.connect(self.db) as c:
            c.executescript("DROP TABLE IF EXISTS items;"
                            "DROP TABLE IF EXISTS obligations;"
                            "DROP TABLE IF EXISTS events;"
                            "DROP TABLE IF EXISTS cursors;"
                            "DROP TABLE IF EXISTS meta;")
            c.executescript(v1)
            c.execute("DELETE FROM meta WHERE key='schema_version'")
            c.execute("INSERT INTO items(source_id, source, scope, event_at,"
                      " sender, subject, body, state)"
                      " VALUES ('m1','email','inbox','2026-01-01T00:00:00.000Z',"
                      "         'Dana','s','b','pending')")

        self._db.ensure_store()

        with sqlite3.connect(self.db) as c:
            row = c.execute("SELECT sender, body, body_cleared_at FROM items"
                            " WHERE source_id='m1'").fetchone()
        self.assertEqual(row[0], "Dana")
        self.assertEqual(row[1], "b")
        self.assertIsNone(row[2])

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
