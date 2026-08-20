# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: concurrency, crash recovery, reinstall survival, and the
promise that no source system is ever written to."""

import ast, os, re, shutil, sqlite3, sys, tempfile, threading, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")

PROFILE = HERE.parent
MANIFEST = PROFILE / "distribution.yaml"


def read_manifest(path: Path = MANIFEST) -> dict:
    """Parse the manifest without a YAML dependency.

    The recipe imports nothing outside the standard library, and this file is a
    flat mapping with one list and one folded block, so a general parser is not
    needed. It is deliberately strict: an unreadable manifest raises here rather
    than yielding an empty mapping that would make every assertion below vacuous.
    """
    data: dict = {}
    key = None
    mode = None                                # "list", "block", or None
    for raw in path.read_text(encoding="utf-8").splitlines():
        if raw.lstrip().startswith("#"):
            continue
        if not raw.strip():
            continue
        if raw.startswith((" ", "\t")):        # a continuation of the current key
            item = raw.strip()
            if mode == "list" and item.startswith("- "):
                data.setdefault(key, []).append(item[2:].strip().strip("'\""))
            elif mode == "block":
                data[key] = (data[key] + " " + item).strip()
            continue
        name, _, value = raw.split("#", 1)[0].partition(":")
        key = name.strip()
        value = value.strip().strip("'\"")
        if value in (">", ">-", "|", "|-"):
            data[key], mode = "", "block"
        elif value:
            data[key], mode = value, None
        else:
            data[key], mode = [], "list"
    return data


MANIFEST_DATA = read_manifest()

# What an install replaces, read from the shipped manifest rather than
# restated. A copy here would drift: it already had, omitting
# `distribution.yaml` itself while claiming to be the manifest's contents.
DIST_OWNED = set(MANIFEST_DATA["distribution_owned"])

# Paths the runtime treats as user-owned. This is a claim about Hermes, not
# about this repository, so the test cannot prove it — it pins the assumption
# the design rests on so that a change to it is a visible edit rather than a
# silent one. Measured against Hermes 0.19.0.
USER_OWNED = {"workspace", "memories", "sessions", "logs", "state.db", ".env"}


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

    def test_nothing_this_example_ships_lands_on_a_user_owned_path(self):
        # The check that matters is not that two literals differ, but that the
        # files actually in this contribution never occupy a user-owned name.
        # Hermes skips any shipped path whose top-level name is user-owned, so
        # a shipped `workspace` would never be installed at all — silently. The
        # destructive case runs the other way: a store under a
        # distribution-owned path is removed and replaced on every update.
        shipped = {p.name for p in (HERE.parent).iterdir()}
        self.assertEqual(shipped & USER_OWNED, set(),
                         "a shipped path collides with a user-owned name")
        self.assertEqual(USER_OWNED & DIST_OWNED, set())


class TestNoSourceMutation(unittest.TestCase):
    """The source systems are inputs. Nothing here writes back to them."""

    # Matches the shapes an HTTP write actually takes, not a list of names we
    # happened to think of. The previous version of this test scanned one
    # directory for seven hardcoded call names and passed vacuously.
    WRITE_PATTERNS = (
        re.compile(r'method\s*=\s*["\'](POST|PUT|PATCH|DELETE)', re.I),
        re.compile(r'\.(post|put|patch|delete)\s*\(', re.I),
        re.compile(r'\brequest\s*\(\s*["\'](POST|PUT|PATCH|DELETE)', re.I),
        re.compile(r'\b(graph_post|graph_patch|graph_delete|chat\.postMessage'
                   r'|conversations\.mark|reactions\.add|files\.upload)\b'),
        # `urlopen(url, data=...)` is a POST — the stdlib spelling of a write,
        # and one an earlier version of this scan did not see.
        re.compile(r'urlopen\s*\([^)]*\bdata\s*='),
        # Shelling out is the other way past a call-shape scan.
        re.compile(r'\b(subprocess|os)\.\w+\s*\([^)]*\b(curl|wget)\b'),
    )

    def test_no_module_issues_a_write_to_a_source_system(self):
        # Recursive, so a connector added in a subdirectory later is covered.
        offenders = []
        for path in sorted(HERE.rglob("*.py")):
            if path.name.startswith("test_"):
                continue          # tests may name a verb in order to forbid it
            text = path.read_text(encoding="utf-8")
            for pattern in self.WRITE_PATTERNS:
                if pattern.search(text):
                    offenders.append(f"{path.relative_to(HERE)}: {pattern.pattern[:34]}")
        self.assertEqual(offenders, [],
                         "a source system must never be mutated by this recipe")

    def test_the_scan_would_catch_a_real_write(self):
        # A guard that cannot fail is worse than no guard, so prove it fires.
        for sample in ('requests.post(url, json=body)',
                       'urllib.request.urlopen(url, data=body)',
                       'subprocess.run(["curl", "-X", "POST", url])',
                       'httpx.patch(url)',
                       'session.delete(url)',
                       'client.request("PATCH", url)',
                       'graph_patch(f"{GRAPH}/me/messages/{mid}", {"isRead": True})'):
            self.assertTrue(any(p.search(sample) for p in self.WRITE_PATTERNS),
                            f"the scan would not catch: {sample}")

    def test_read_state_is_stored_but_never_sent_back(self):
        # items.unread mirrors the source's read flag deliberately: an unread
        # message from a person is a judging signal. Mirroring it is fine;
        # writing it back is what the sibling recipe does and what this one
        # promises not to. Assert the invariant that actually matters — the
        # column exists, and nothing anywhere sends it anywhere.
        self.assertIn("unread", SCHEMA)
        for path in sorted(HERE.rglob("*.py")):
            if path.name.startswith("test_"):
                continue          # tests name the payload shape in order to forbid it
            text = path.read_text(encoding="utf-8")
            self.assertNotRegex(
                text, r"isRead[\"']?\s*:",
                f"{path.name} appears to build a payload carrying isRead")


class TestProfileHomeResolution(unittest.TestCase):
    """Both supported profile layouts resolve; a non-profile does not.

    Hermes serves the default profile from the runtime root itself and named
    profiles from `<root>/profiles/<name>`, so the two are indistinguishable by
    path name. An earlier version of this guard rejected any home whose last
    component was `.hermes`, which refused the default profile — every default
    installation, on the destructive path, with no test covering it.
    """

    def setUp(self):
        for m in ("_db",):
            sys.modules.pop(m, None)
        import _db                             # noqa: E402
        self._db = _db
        self.root = Path(tempfile.mkdtemp())

    def _profile(self, path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        (path / "SOUL.md").write_text("persona\n", encoding="utf-8")
        (path / "skills").mkdir(exist_ok=True)
        return path

    def _resolve(self, home: Path) -> Path:
        os.environ["HERMES_HOME"] = str(home)
        return self._db.ledger_path()

    def test_the_default_profile_is_the_runtime_root_itself(self):
        home = self._profile(self.root)
        (home / "profiles").mkdir()            # named profiles live alongside
        (home / "hermes-agent").mkdir()        # so does the runtime checkout
        self.assertEqual(self._resolve(home),
                         home / "workspace" / "ledger" / "state.db")

    def test_a_named_profile_resolves(self):
        home = self._profile(self.root / "profiles" / "work")
        self.assertEqual(self._resolve(home),
                         home / "workspace" / "ledger" / "state.db")

    def test_a_home_named_dot_hermes_is_not_rejected_for_its_name(self):
        """The name carries no information; only a marker does."""
        home = self._profile(self.root / ".hermes")
        self.assertEqual(self._resolve(home),
                         home / "workspace" / "ledger" / "state.db")

    def test_each_marker_alone_identifies_a_profile(self):
        for marker in self._db.PROFILE_MARKERS:
            with self.subTest(marker=marker):
                home = Path(tempfile.mkdtemp()) / "p"
                home.mkdir()
                (home / "unrelated.txt").write_text("x", encoding="utf-8")
                target = home / marker
                target.mkdir() if "." not in marker else target.write_text("x", encoding="utf-8")
                self.assertEqual(self._resolve(home).parent.parent.parent, home)

    def test_a_fresh_directory_is_accepted_so_a_first_run_can_create_the_store(self):
        home = self.root / "brand-new"
        home.mkdir()
        self.assertEqual(self._resolve(home),
                         home / "workspace" / "ledger" / "state.db")

    def test_a_home_that_does_not_exist_is_refused_rather_than_created(self):
        """A mistyped path is the ordinary way of naming the wrong directory.

        It was also the one case that got through: the profile check only ran
        on a directory that already existed, so a typo skipped it entirely and
        materialised a store under the misspelled name — the inverse of the
        rule, where a wrong directory that exists is caught and a wrong path
        that does not is obeyed.
        """
        home = self.root / ".hermes-typoo"
        with self.assertRaises(RuntimeError) as caught:
            self._resolve(home)
        self.assertIn("does not exist", str(caught.exception))
        self.assertFalse(home.exists(), "the refused path was created anyway")

    def test_a_missing_home_is_not_created_by_opening_the_store(self):
        """The refusal has to hold on the path that creates directories."""
        import _db                             # noqa: E402
        home = self.root / "absent"
        os.environ["HERMES_HOME"] = str(home)
        with self.assertRaises(RuntimeError):
            _db.ensure_store()
        self.assertFalse(home.exists())

    def test_a_dotfile_does_not_make_a_fresh_directory_look_occupied(self):
        """Opening a folder in a file browser should not change what it is."""
        home = self.root / "browsed"
        home.mkdir()
        (home / ".DS_Store").write_bytes(b"\x00\x01")
        self.assertEqual(self._resolve(home),
                         home / "workspace" / "ledger" / "state.db")

    def test_a_dotfile_does_not_make_a_non_profile_look_like_one(self):
        """Ignoring dotfiles must not weaken the check on real content."""
        home = self.root / "not-a-profile-either"
        home.mkdir()
        (home / ".DS_Store").write_bytes(b"\x00")
        (home / "Documents").mkdir()
        with self.assertRaises(RuntimeError):
            self._resolve(home)

    def test_a_directory_that_is_not_a_profile_is_refused(self):
        home = self.root / "not-a-profile"
        home.mkdir()
        (home / "Documents").mkdir()
        (home / "notes.txt").write_text("x", encoding="utf-8")
        with self.assertRaises(RuntimeError) as caught:
            self._resolve(home)
        self.assertIn("profile home", str(caught.exception))

    def test_an_unset_home_is_refused_rather_than_guessed(self):
        os.environ.pop("HERMES_HOME", None)
        with self.assertRaises(RuntimeError) as caught:
            self._db.ledger_path()
        self.assertIn("HERMES_HOME", str(caught.exception))

    def test_a_file_is_not_a_profile_home(self):
        home = self.root / "afile"
        home.write_text("x", encoding="utf-8")
        with self.assertRaises(RuntimeError):
            self._resolve(home)


class TestShippedProfileInstalls(unittest.TestCase):
    """A deterministic stand-in for `hermes profile install`.

    The manifest and the persona were both missing from an earlier revision and
    no test noticed, because every test drives the scripts directly and none of
    them installs anything. These assertions are about the artifact rather than
    the code: what the manifest declares, what the directory actually holds, and
    whether copying one onto a profile home produces something that runs.
    """

    REQUIRED_KEYS = ("name", "version", "description", "hermes_requires",
                     "author", "license", "distribution_owned")

    def test_the_manifest_declares_everything_hermes_reads(self):
        for key in self.REQUIRED_KEYS:
            with self.subTest(key=key):
                self.assertTrue(MANIFEST_DATA.get(key), f"manifest has no {key}")

    def test_every_declared_owned_path_is_actually_shipped(self):
        for name in DIST_OWNED:
            with self.subTest(path=name):
                self.assertTrue((PROFILE / name).exists(),
                                f"manifest declares {name} but the profile has no such path")

    def test_the_manifest_declares_itself(self):
        """It is replaced on update like anything else the distribution owns."""
        self.assertIn("distribution.yaml", DIST_OWNED)

    def test_nothing_shipped_at_the_profile_root_is_undeclared(self):
        """An undeclared file is not installed, so it may as well not exist."""
        shipped = {entry.name for entry in PROFILE.iterdir()
                   if not entry.name.startswith(".")}
        self.assertEqual(shipped - DIST_OWNED, set())

    def test_the_persona_and_schema_are_present_and_not_empty(self):
        for name in ("SOUL.md", "schema.md"):
            with self.subTest(file=name):
                self.assertGreater(len((PROFILE / name).read_text(encoding="utf-8").strip()),
                                   0, f"{name} is empty")

    def test_every_skill_has_a_skill_file_with_frontmatter(self):
        skills = sorted(p for p in (PROFILE / "skills").iterdir() if p.is_dir())
        self.assertTrue(skills, "the profile ships no skills")
        for skill in skills:
            with self.subTest(skill=skill.name):
                doc = skill / "SKILL.md"
                self.assertTrue(doc.is_file(), f"{skill.name} has no SKILL.md")
                self.assertTrue(doc.read_text(encoding="utf-8").startswith("---"),
                                f"{skill.name}/SKILL.md has no frontmatter")

    def test_installing_onto_a_profile_home_yields_a_working_store(self):
        """Copy what the manifest owns, then use the result the way a job would."""
        home = Path(tempfile.mkdtemp()) / "profile"
        home.mkdir()
        for name in DIST_OWNED:
            src = PROFILE / name
            if src.is_dir():
                shutil.copytree(src, home / name)
            else:
                shutil.copy2(src, home / name)

        os.environ["HERMES_HOME"] = str(home)
        for module in ("_db", "migrate", "ranking", "apply_decisions"):
            sys.modules.pop(module, None)
        sys.path.insert(0, str(home / "scripts"))
        try:
            import _db                          # noqa: E402
            self.assertTrue(_db.ensure_store().is_file())
        finally:
            sys.path.remove(str(home / "scripts"))
            for module in ("_db", "migrate", "ranking", "apply_decisions"):
                sys.modules.pop(module, None)

    def test_the_installed_profile_is_recognised_as_a_profile_home(self):
        """Which is what `ledger_path` requires before it will resolve."""
        home = Path(tempfile.mkdtemp()) / "profile"
        home.mkdir()
        shutil.copy2(MANIFEST, home / "distribution.yaml")
        sys.modules.pop("_db", None)
        import _db                              # noqa: E402
        os.environ["HERMES_HOME"] = str(home)
        self.assertEqual(_db.ledger_path().parent.parent.parent, home)


class TestTheSuiteRunsTheWayItIsDocumented(unittest.TestCase):
    """Every test class must sit above its file's `__main__` guard.

    A class defined after it is not yet defined when `unittest.main()` runs, so
    running the file directly — which is how the README documents it — silently
    skips the class. Discovery still finds it, so the two counts diverge and the
    file reports a smaller number that still says OK. This has now happened
    twice while addressing review feedback, each time hiding the very tests
    that were added.
    """

    def test_no_test_class_is_defined_after_the_main_guard(self):
        # Parsed rather than string-matched: this very file contains the guard
        # as a string literal, and searching for it found that literal first,
        # which made every class below look misplaced.
        for path in sorted(Path(__file__).parent.glob("test_*.py")):
            with self.subTest(file=path.name):
                tree = ast.parse(path.read_text(encoding="utf-8"))
                guards = [n.lineno for n in tree.body
                          if isinstance(n, ast.If)
                          and ast.dump(n.test).find("__main__") != -1]
                self.assertTrue(guards, f"{path.name} has no main guard")
                classes = [n.lineno for n in tree.body
                           if isinstance(n, ast.ClassDef)]
                late = [line for line in classes if line > min(guards)]
                self.assertEqual(late, [],
                                 f"{path.name} defines a class after its main guard "
                                 f"at line(s) {late}, so running the file directly "
                                 "skips it")


class TestAFailedWriteReportsItsOwnCause(unittest.TestCase):
    """The error a caller sees must be the one that stopped the write.

    `BEGIN IMMEDIATE` fails on a busy database, so no transaction opens. An
    unconditional rollback then fails too, with "cannot rollback - no
    transaction is active" — and that was what the caller saw, instead of
    "database is locked". The cleanup was reported as the fault.
    """

    def setUp(self):
        os.environ["HERMES_HOME"] = self.tmp = tempfile.mkdtemp()
        sys.modules.pop("_db", None)
        import _db                              # noqa: E402
        self._db = _db
        self.path = _db.ensure_store()

    def test_contention_surfaces_the_lock_error_not_the_rollback_error(self):
        holder = sqlite3.connect(self.path, isolation_level=None)
        holder.execute("BEGIN IMMEDIATE")       # hold the write lock
        try:
            with self.assertRaises(sqlite3.OperationalError) as caught:
                with self._db.write_txn() as conn:
                    conn.execute("SELECT 1")
            message = str(caught.exception)
            self.assertIn("locked", message)
            self.assertNotIn("cannot rollback", message)
        finally:
            holder.execute("ROLLBACK")
            holder.close()

    def test_a_failure_inside_the_transaction_still_rolls_back(self):
        """The guard must not stop a real rollback from happening."""
        with self.assertRaises(ValueError):
            with self._db.write_txn() as conn:
                conn.execute(
                    "INSERT INTO items(source_id, source, scope, event_at)"
                    " VALUES ('rolled-back','email','inbox','2026-08-18T00:00:00Z')")
                raise ValueError("boom")
        with sqlite3.connect(self.path) as c:
            self.assertEqual(
                c.execute("SELECT COUNT(*) FROM items").fetchone()[0], 0)


class TestSkillsNameFilesAbsolutely(unittest.TestCase):
    """Every path a skill hands to a shell must resolve from any directory.

    The agent's working directory is not the profile home, so a relative path
    resolves to nothing — and an unreadable file is indistinguishable from an
    empty one, which is why this failure is silent rather than loud. Ten paths
    were fixed for that reason once; one shipped skill was still invoking a
    script relatively when a reviewer found it, so the class is checked here
    rather than by reading.
    """

    SHELL_BLOCK = re.compile(r"```(?:bash|sh)\n(.*?)```", re.S)
    INVOCATION = re.compile(r"^\s*(?:python3|sqlite3|cat|\.)\s+(\S+)", re.M)

    def _skills(self):
        root = HERE.parent / "skills"
        self.assertTrue(root.is_dir(), "the profile ships no skills")
        return sorted(root.glob("*/SKILL.md"))

    def test_every_scripted_path_is_anchored(self):
        for doc in self._skills():
            text = doc.read_text(encoding="utf-8")
            for block in self.SHELL_BLOCK.findall(text):
                for target in self.INVOCATION.findall(block):
                    cleaned = target.strip('"\'')
                    if not cleaned.endswith((".py", ".db", ".json", ".md")):
                        continue
                    with self.subTest(skill=doc.parent.name, path=target):
                        self.assertTrue(
                            cleaned.startswith("$HERMES_HOME")
                            or cleaned.startswith("/"),
                            f"{doc.parent.name} runs {target} relative to the "
                            "working directory, which is not the profile home")

    def test_the_scan_would_catch_a_relative_invocation(self):
        """The check has to be able to fail, or it is telling us nothing."""
        block = 'python3 scripts/memory_check.py\n'
        found = self.INVOCATION.findall(block)
        self.assertEqual(found, ["scripts/memory_check.py"])
        self.assertFalse(found[0].startswith("$HERMES_HOME"))


class TestSkillsNameFilesThatWillExist(unittest.TestCase):
    """A `$HERMES_HOME` path is only anchored if something puts a file there.

    Anchoring the path was the fix for one silent failure; naming a path that
    nothing creates is the same failure with a longer prefix. Two skills read
    `$HERMES_HOME/workspace/memory/schema.md`, which the manifest installs at
    the profile root instead, so the job whose premise is "this memory has a
    contract" opened by reading a file that was never there.
    """

    HOME_PATH = re.compile(r"\$HERMES_HOME/([A-Za-z0-9_./-]+)")

    def _installed_roots(self):
        """Top-level names an install lays down, from the shipped manifest."""
        return set(MANIFEST_DATA["distribution_owned"])

    def test_every_referenced_path_is_installed_or_runtime_state(self):
        # `workspace/` is user-owned: the recipe's own code creates the store
        # and the memory there at run time, so those are legitimate.
        runtime = {"workspace"}
        for doc in sorted((HERE.parent / "skills").glob("*/SKILL.md")):
            text = doc.read_text(encoding="utf-8")
            for rel in self.HOME_PATH.findall(text):
                head = rel.split("/", 1)[0]
                with self.subTest(skill=doc.parent.name, path=rel):
                    self.assertIn(
                        head, self._installed_roots() | runtime,
                        f"{doc.parent.name} reads $HERMES_HOME/{rel}, and "
                        f"nothing installs or creates {head!r}")

    def test_a_shipped_file_is_referenced_where_it_lands(self):
        """`schema.md` installs at the profile root, so that is where it is read."""
        for doc in sorted((HERE.parent / "skills").glob("*/SKILL.md")):
            text = doc.read_text(encoding="utf-8")
            for rel in self.HOME_PATH.findall(text):
                if rel.endswith("schema.md"):
                    with self.subTest(skill=doc.parent.name):
                        self.assertEqual(rel, "schema.md")


if __name__ == "__main__":
    unittest.main(verbosity=2)
