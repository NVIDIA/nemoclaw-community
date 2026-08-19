# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: concurrency, crash recovery, reinstall survival, and the
promise that no source system is ever written to."""

import os, re, shutil, sqlite3, sys, tempfile, threading, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")

# Mirrors USER_OWNED_EXCLUDE in the distribution installer: these names are
# never copied and never replaced when a distribution is installed or updated.
USER_OWNED = {"workspace", "memories", "sessions", "logs", "state.db", ".env"}
DIST_OWNED = {"SOUL.md", "schema.md", "skills", "scripts"}


class TestConcurrency(unittest.TestCase):

    def setUp(self):
        os.environ["HERMES_HOME"] = self.tmp = tempfile.mkdtemp()
        for m in ("_db", "ranking", "apply_decisions"):
            sys.modules.pop(m, None)
        import _db, apply_decisions  # noqa: E402
        self._db, self.mod = _db, apply_decisions
        _db.ensure_store()
        with sqlite3.connect(_db.ledger_path()) as c:
            for n in range(1, 41):
                c.execute("INSERT INTO items(source_id, source, scope, event_at)"
                          " VALUES (?,'email','inbox','2026-08-18T00:00:00Z')", (f"m{n}",))

    def envelope(self, ids):
        return {"version": 1, "decisions": [
            {"source_id": i, "decision": "CREATE", "rank": n, "intent_gated": True,
             "title": f"row {i}"} for n, i in enumerate(ids, start=1)]}

    def test_two_writers_serialize_rather_than_interleave(self):
        errors: list[Exception] = []

        def write(ids):
            try:
                self.mod.apply(self.envelope(ids))
            except Exception as exc:      # noqa: BLE001
                errors.append(exc)

        a = threading.Thread(target=write, args=([f"m{n}" for n in range(1, 21)],))
        b = threading.Thread(target=write, args=([f"m{n}" for n in range(21, 41)],))
        a.start(); b.start(); a.join(); b.join()

        self.assertEqual(errors, [], "a writer failed under contention")
        with sqlite3.connect(self._db.ledger_path()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM obligations").fetchone()[0], 40)
            # Every row got exactly one creation event: no double-apply.
            self.assertEqual(
                c.execute("SELECT count(*) FROM events WHERE event_type='created'")
                 .fetchone()[0], 40)

    def test_the_same_envelope_applied_twice_does_not_duplicate(self):
        env = self.envelope(["m1", "m2"])
        self.mod.apply(env); self.mod.apply(env)
        with sqlite3.connect(self._db.ledger_path()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM obligations").fetchone()[0], 2)


class TestCrashRecovery(unittest.TestCase):

    def setUp(self):
        os.environ["HERMES_HOME"] = self.tmp = tempfile.mkdtemp()
        for m in ("_db", "ranking", "apply_decisions"):
            sys.modules.pop(m, None)
        import _db, apply_decisions  # noqa: E402
        self._db, self.mod = _db, apply_decisions
        _db.ensure_store()
        with sqlite3.connect(_db.ledger_path()) as c:
            c.execute("INSERT INTO items(source_id, source, scope, event_at)"
                      " VALUES ('m1','email','inbox','2026-08-18T00:00:00Z')")

    def test_a_failure_midway_leaves_neither_rows_nor_an_advanced_cursor(self):
        # The cursor must never outrun the rows it claims to cover: on the next
        # run the source would be re-read from a point whose messages were
        # never stored, and they would be lost silently.
        with self.assertRaises(sqlite3.IntegrityError):
            self.mod.apply({"version": 1, "decisions": [
                {"source_id": "m1", "decision": "CREATE", "rank": 1,
                 "intent_gated": True, "title": "ok"},
                {"source_id": "does-not-exist", "decision": "CREATE", "rank": 2,
                 "intent_gated": True, "title": "orphan"}],
                "cursor": {"source": "email", "scope": "inbox", "value": "must-not-land"}})
        with sqlite3.connect(self._db.ledger_path()) as c:
            self.assertEqual(c.execute("SELECT count(*) FROM obligations").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT count(*) FROM cursors").fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT count(*) FROM events").fetchone()[0], 0)

    def test_the_store_is_usable_after_an_aborted_write(self):
        try:
            self.mod.apply({"version": 1, "decisions": [
                {"source_id": "nope", "decision": "CREATE", "rank": 1,
                 "intent_gated": True, "title": "x"}]})
        except sqlite3.IntegrityError:
            pass
        self.mod.apply({"version": 1, "decisions": [
            {"source_id": "m1", "decision": "CREATE", "rank": 1,
             "intent_gated": True, "title": "recovered"}]})
        with sqlite3.connect(self._db.ledger_path()) as c:
            self.assertEqual(c.execute("SELECT title FROM obligations").fetchone()[0],
                             "recovered")


class TestReinstallSurvival(unittest.TestCase):
    """A distribution install replaces what it owns and must not touch the rest."""

    def install(self, home: Path):
        for name in DIST_OWNED:
            dest = home / name
            if dest.is_dir():
                shutil.rmtree(dest)        # the installer replaces owned dirs wholesale
            (home / name).mkdir(exist_ok=True) if name in {"skills", "scripts"} \
                else (home / name).write_text("shipped\n", encoding="utf-8")

    def test_user_state_survives_an_install_that_replaces_owned_paths(self):
        home = Path(tempfile.mkdtemp())
        ledger = home / "workspace" / "ledger"
        ledger.mkdir(parents=True)
        with sqlite3.connect(ledger / "state.db") as c:
            c.executescript(SCHEMA)
            c.execute("INSERT INTO items(source_id, source, scope, event_at)"
                      " VALUES ('keep-me','email','inbox','2026-08-18T00:00:00Z')")
        (home / "skills").mkdir(); (home / "skills" / "old.md").write_text("old\n")

        self.install(home)
        self.install(home)      # update runs the same path; twice must be safe

        with sqlite3.connect(ledger / "state.db") as c:
            self.assertEqual(c.execute("SELECT count(*) FROM items").fetchone()[0], 1)
        self.assertFalse((home / "skills" / "old.md").exists(),
                         "distribution-owned content is expected to be replaced")

    def test_no_user_owned_name_is_also_distribution_owned(self):
        # A name in both sets would be silently destroyed on every update.
        self.assertEqual(USER_OWNED & DIST_OWNED, set())


class TestNoSourceMutation(unittest.TestCase):
    """The source systems are inputs. Nothing here writes back to them."""

    WRITE_VERBS = re.compile(r'method\s*=\s*["\'](POST|PUT|PATCH|DELETE)', re.I)
    WRITE_CALLS = re.compile(r'\b(graph_post|graph_patch|graph_delete|chat\.postMessage'
                             r'|conversations\.mark|reactions\.add|files\.upload)\b')

    def test_no_module_issues_a_write_to_a_source_system(self):
        offenders = []
        for path in sorted(HERE.glob("*.py")):
            text = path.read_text(encoding="utf-8")
            if self.WRITE_VERBS.search(text) or self.WRITE_CALLS.search(text):
                offenders.append(path.name)
        self.assertEqual(offenders, [],
                         "a source system must never be mutated by this recipe")

    def test_the_schema_has_no_column_that_mirrors_source_state(self):
        # Storing something like a remote read flag invites writing it back.
        schema = SCHEMA.lower()
        for forbidden in ("is_read_remote", "source_flag", "remote_status"):
            self.assertNotIn(forbidden, schema)


if __name__ == "__main__":
    unittest.main(verbosity=2)
