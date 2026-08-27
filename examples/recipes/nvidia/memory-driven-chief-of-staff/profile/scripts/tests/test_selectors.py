# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: what the cron pre-steps hand the agent, and when they decline to
wake it at all."""

import json, os, re, shutil, sqlite3, subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")


class SelectorCase(unittest.TestCase):

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.db = Path(self.home) / "workspace" / "ledger" / "state.db"
        self.db.parent.mkdir(parents=True)
        with sqlite3.connect(self.db) as c:
            c.executescript(SCHEMA)

    def run_selector(self, script, **env):
        proc = subprocess.run(
            [sys.executable, str(HERE / script)], capture_output=True, text=True,
            env={"PATH": os.environ["PATH"], "HERMES_HOME": self.home, **env})
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    @staticmethod
    def wake_gate_present(stdout: str) -> bool:
        """Decide the way the scheduler decides.

        Hermes reads the *last non-empty stdout line* and nothing else
        (`cron/scheduler.py`, `_parse_wake_gate`): if that line parses as a
        JSON object with `wakeAgent` false, the agent is skipped; anything
        else — non-JSON, a missing key, a gate printed earlier with output
        after it — wakes it. Asserting only that the gate appears somewhere
        would stay green while every idle tick woke the model, which is the
        one thing this gate exists to prevent.
        """
        lines = [line for line in stdout.splitlines() if line.strip()]
        if not lines:
            return False
        try:
            gate = json.loads(lines[-1].strip())
        except ValueError:
            return False
        return isinstance(gate, dict) and gate.get("wakeAgent", True) is False

    def payload(self, stdout: str) -> dict:
        # The gate, when present, is a separate JSON object after the payload.
        head = stdout.split('{"wakeAgent"')[0]
        return json.loads(head)

    def add_item(self, sid, state="pending", event_at="2026-08-18T00:00:00Z"):
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO items(source_id, source, scope, event_at, state,"
                      " sender, subject, body, addressing, unread)"
                      " VALUES (?,'email','inbox',?,?,'Dana','subject','body','direct',1)",
                      (sid, event_at, state))

    def add_obligation(self, sid, reviewed_at=None, status="open", snoozed_until=None):
        self.add_item(sid, state="judged")
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO obligations(id, source_id, title, priority, status,"
                      " reviewed_at, snoozed_until) VALUES (?,?,?,'high',?,?,?)",
                      (sid[:12], sid, f"title {sid}", status, reviewed_at, snoozed_until))


class TestIntake(SelectorCase):

    def test_an_empty_store_declines_to_wake_the_agent(self):
        # The whole point of the gate: a quiet half-hour must cost no tokens.
        out = self.run_selector("select_intake.py")
        self.assertTrue(self.wake_gate_present(out))
        self.assertEqual(self.payload(out)["slice"], [])

    def test_pending_items_wake_the_agent(self):
        self.add_item("m1")
        out = self.run_selector("select_intake.py")
        self.assertFalse(self.wake_gate_present(out))
        self.assertEqual(len(self.payload(out)["slice"]), 1)

    def test_judged_and_skipped_items_are_not_offered_again(self):
        self.add_item("judged", state="judged")
        self.add_item("skipped", state="skipped")
        out = self.run_selector("select_intake.py")
        self.assertTrue(self.wake_gate_present(out))

    def test_the_slice_is_bounded_and_oldest_first(self):
        for n in range(10):
            self.add_item(f"m{n}", event_at=f"2026-08-{10 + n:02d}T00:00:00Z")
        out = self.run_selector("select_intake.py", INTAKE_SLICE="3")
        rows = self.payload(out)["slice"]
        self.assertEqual(len(rows), 3)
        self.assertEqual([r["source_id"] for r in rows], ["m0", "m1", "m2"])

    def test_absent_collectors_are_reported_rather_than_failing(self):
        out = self.run_selector("select_intake.py")
        collected = self.payload(out)["collected"]
        self.assertEqual(set(collected), {"ingest_graph.py", "ingest_slack.py"})


class TestReview(SelectorCase):

    def test_no_open_obligations_declines_to_wake_the_agent(self):
        out = self.run_selector("select_review.py")
        self.assertTrue(self.wake_gate_present(out))

    def test_never_reviewed_rows_come_before_stale_ones(self):
        self.add_obligation("old", reviewed_at="2026-01-01T00:00:00Z")
        self.add_obligation("fresh", reviewed_at="2026-08-18T00:00:00Z")
        self.add_obligation("never")
        rows = self.payload(self.run_selector("select_review.py"))["batch"]
        self.assertEqual(rows[0]["source_id"], "never")
        self.assertEqual(rows[1]["source_id"], "old")

    def test_a_snoozed_row_is_left_alone_until_its_time(self):
        self.add_obligation("sleeping", snoozed_until="2099-01-01T00:00:00Z")
        out = self.run_selector("select_review.py")
        self.assertTrue(self.wake_gate_present(out))

    def test_an_expired_snooze_returns_to_the_batch(self):
        self.add_obligation("woken", snoozed_until="2020-01-01T00:00:00Z")
        rows = self.payload(self.run_selector("select_review.py"))["batch"]
        self.assertEqual([r["source_id"] for r in rows], ["woken"])

    def test_closed_rows_are_not_re_reviewed(self):
        self.add_obligation("done", status="done")
        self.add_obligation("ignored", status="ignored")
        out = self.run_selector("select_review.py")
        self.assertTrue(self.wake_gate_present(out))

    def test_the_batch_is_bounded(self):
        for n in range(10):
            self.add_obligation(f"o{n}")
        rows = self.payload(self.run_selector("select_review.py", REVIEW_BATCH="4"))["batch"]
        self.assertEqual(len(rows), 4)


class TestSchedulerIntegrationContract(unittest.TestCase):
    """The two promises the scheduler side of this phase rests on.

    Both are claims about files outside this test: the shipped manifest and the
    registration script. Neither was covered, and one of them was already
    false — the script looked jobs up with `cron list --json`, a flag the CLI
    does not have, so the lookup always came back empty and every run created
    another copy of all seven jobs.
    """

    RECIPE = HERE.parents[1]

    def test_the_manifest_does_not_claim_the_cron_directory(self):
        """Owning `cron` would let an update replace the live job store."""
        manifest = (self.RECIPE / "profile" / "distribution.yaml").read_text(
            encoding="utf-8")
        owned = []
        collecting = False
        for line in manifest.splitlines():
            if line.startswith("distribution_owned:"):
                collecting = True
                continue
            if collecting:
                if line.startswith("  - "):
                    owned.append(line[4:].strip())
                elif line.strip() and not line.startswith(" "):
                    break
        self.assertTrue(owned, "the manifest declares nothing as owned")
        self.assertNotIn("cron", owned)
        self.assertNotIn("workspace", owned)

    def test_the_registration_script_looks_a_job_up_before_creating_it(self):
        script = (self.RECIPE / "scripts" / "register-jobs.sh").read_text(
            encoding="utf-8")
        self.assertIn("job_id_for", script)
        # `cron list` takes no `--json`. Passing it made argparse print usage,
        # the lookup came back empty behind `2>/dev/null`, and the script
        # created another copy of every job on each run. Match the invocation,
        # not the word: the comment above the lookup explains the flag.
        for line in script.splitlines():
            if line.strip().startswith("#"):
                continue
            with self.subTest(line=line.strip()[:60]):
                self.assertNotIn("cron list --json", line)

    def test_the_registration_script_only_writes_through_the_cron_cli(self):
        """The lookup may read the store; the writes must go through Hermes."""
        script = (self.RECIPE / "scripts" / "register-jobs.sh").read_text(
            encoding="utf-8")
        for verb in ("cron create", "cron edit"):
            with self.subTest(verb=verb):
                self.assertIn(f'hermes -p "$PROFILE" {verb}', script)
        # The store is read, never written: no redirect and no python -c that
        # opens it for writing.
        for line in script.splitlines():
            if "jobs.json" not in line or line.strip().startswith("#"):
                continue
            with self.subTest(line=line.strip()[:60]):
                self.assertNotIn(">", line)
                self.assertNotIn("rm ", line)


class TestScriptsNameRealHermesCommands(unittest.TestCase):
    """Every `hermes` command the shipped text names must exist.

    Pointing a reader at a command that is not there is the failure this recipe
    has now made three times: an error message said `restore` when the
    subcommand is `unignore`; a teardown line said `hermes profile remove` when
    it is `delete`; and the installer's remediation said `hermes model <name>`,
    which the CLI rejects because `model` takes no positional argument. The
    first two were caught by reading the CLI, the third by an independent
    review — none by a test, because the scan covered only two command groups
    and only the shell scripts.

    So it covers four groups now, and the README as well as the scripts. The
    surfaces below were read from `hermes <group> --help` on Hermes 0.20.0;
    update them deliberately if the CLI changes.
    """

    RECIPE = HERE.parents[1]

    KNOWN = {
        "cron": {"list", "create", "add", "edit", "pause", "resume", "run",
                 "remove", "rm", "delete", "status", "runs", "history",
                 "notepad", "tick"},
        "profile": {"list", "use", "create", "delete", "describe", "show",
                    "alias", "rename", "export", "import", "install",
                    "update", "info"},
        "gateway": {"run", "start", "stop", "restart", "status", "install",
                    "uninstall", "list", "setup", "migrate-legacy", "enroll"},
        "config": {"show", "edit", "get", "set", "unset", "path", "env-path",
                   "check", "migrate"},
    }
    # `hermes model` takes flags only. Naming anything after it is the bug the
    # installer shipped with.
    NO_POSITIONAL = {"model"}

    GROUPED = re.compile(r"hermes\b[^\n|`]*?\b(cron|profile|gateway|config)\s+([a-z-]+)")
    # `model` must be the subcommand itself: only flags and their values may
    # sit between `hermes` and it. Without that, `config set model <name>` —
    # which is correct — matched as `model <name>`, which is not.
    BARE = re.compile(
        r"hermes(?:\s+-{1,2}[A-Za-z-]+(?:\s+\S+)?)*\s+(model)\s+([^\s|`]+)")

    def sources(self):
        # Skip dotfiles. A macOS archive carries an AppleDouble sidecar beside
        # each file — `._install.sh` ends in `.sh`, is binary, and made this
        # scan raise UnicodeDecodeError the first time the recipe was unpacked
        # on Linux. `load_fixtures` learned the same lesson for `.md` pages.
        yield from sorted(f for f in (self.RECIPE / "scripts").glob("*.sh")
                          if not f.name.startswith("."))
        yield self.RECIPE / "README.md"

    def test_every_named_subcommand_is_real(self):
        for path in self.sources():
            text = path.read_text(encoding="utf-8")
            for group, sub in self.GROUPED.findall(text):
                with self.subTest(source=path.name, command=f"{group} {sub}"):
                    self.assertIn(sub, self.KNOWN[group],
                                  f"{path.name} names `hermes {group} {sub}`, "
                                  f"which is not a {group} subcommand")

    def test_no_argument_is_passed_to_a_flags_only_command(self):
        for path in self.sources():
            text = path.read_text(encoding="utf-8")
            for command, argument in self.BARE.findall(text):
                with self.subTest(source=path.name, command=command):
                    self.fail(f"{path.name} passes `{argument}` to "
                              f"`hermes {command}`, which takes flags only")

    def test_the_scan_would_catch_all_three_historical_mistakes(self):
        """The check has to be able to fail the way it failed before."""
        self.assertEqual(self.GROUPED.findall("hermes -p x profile remove y"),
                         [("profile", "remove")])
        self.assertNotIn("remove", self.KNOWN["profile"])
        self.assertEqual(self.BARE.findall("hermes -p x model gpt-4"),
                         [("model", "gpt-4")])
        # The correct spelling must not trip it.
        self.assertEqual(
            self.BARE.findall("hermes -p x config set model gpt-4"), [])
        self.assertEqual(self.GROUPED.findall("hermes gateway strt"),
                         [("gateway", "strt")])
        self.assertNotIn("strt", self.KNOWN["gateway"])


class TestTheDocumentedScheduleMatchesTheScript(unittest.TestCase):
    """The README's job table is a copy of the script's arguments.

    A copy drifts. This one is worth pinning because a reader plans around the
    cadence — "every 30 minutes" is what tells them an idle tick has to be
    free — and nothing else would notice if the script changed underneath it.
    """

    RECIPE = HERE.parents[1]
    EXPECTED = {
        "intake": ("*/30 * * * *", "inbound-judging"),
        "review": ("0 */6 * * *", "obligation-review"),
        "memory writing": ("0 1 * * *", "memory-writing"),
        # No skill: retention needs no judgment, clears bodies past the
        # window, and gates the agent off. Naming one would advertise a
        # capability the job never reaches.
        "retention": ("0 2 * * *", None),
        "memory repair": ("0 3 * * *", "memory-repair"),
        "memory consolidation": ("0 4 * * *", "memory-consolidation"),
        "preference update": ("30 4 * * *", "preference-update"),
    }

    def registered(self):
        script = (self.RECIPE / "scripts" / "register-jobs.sh").read_text(
            encoding="utf-8")
        found = {}
        for name, schedule, skill in re.findall(
                r'register\s+("?[a-z ]+"?)\s+"([^"]+)"\s+(\S+)', script):
            # `register` takes an empty skill argument (`""`) for a job that
            # never wakes the agent; read that as no skill rather than as a
            # skill named `""`, which would then be looked for on disk.
            found[name.strip('"')] = (schedule,
                                      skill.strip('"') or None)
        return found

    def test_the_script_registers_exactly_the_documented_jobs(self):
        self.assertEqual(set(self.registered()), set(self.EXPECTED))

    def test_each_job_carries_the_documented_schedule_and_skill(self):
        for name, expected in self.EXPECTED.items():
            with self.subTest(job=name):
                self.assertEqual(self.registered()[name], expected)

    def test_the_readme_table_agrees_with_the_script(self):
        readme = (self.RECIPE / "README.md").read_text(encoding="utf-8")
        prose = {
            "intake": "every 30 minutes",
            "review": "every 6 hours",
            "memory repair": "daily 03:00",
            "memory consolidation": "daily 04:00",
            "preference update": "daily 04:30",
        }
        for name, cadence in prose.items():
            with self.subTest(job=name):
                self.assertRegex(
                    readme, rf"\|\s*{re.escape(name)}\s*\|\s*{re.escape(cadence)}\s*\|",
                    f"the README table no longer lists {name} as {cadence}")

    def test_every_skill_the_schedule_names_is_shipped(self):
        for _, skill in self.EXPECTED.values():
            if skill is None:
                continue
            with self.subTest(skill=skill):
                self.assertTrue((self.RECIPE / "profile" / "skills" / skill
                                 / "SKILL.md").is_file())


class TestTheRebootStoryIsWhatTheReadmeSays(unittest.TestCase):
    """What survives a restart, and what the README promises about it.

    This is the first question anyone asks the morning after installing, and
    it has three different answers — the jobs persist, the firing does not
    unless a service was installed, and a backlog collapses rather than
    replaying. The parts this recipe controls are asserted here; the parts
    Hermes controls are quoted from its source with a pointer, because a test
    that reimplemented them would only be testing itself.
    """

    RECIPE = HERE.parents[1]

    def readme(self):
        return (self.RECIPE / "README.md").read_text(encoding="utf-8")

    def test_the_job_store_is_not_something_an_update_can_replace(self):
        """The claim "a profile update leaves it alone" rests on this."""
        manifest = (self.RECIPE / "profile" / "distribution.yaml").read_text(
            encoding="utf-8")
        owned, collecting = [], False
        for line in manifest.splitlines():
            if line.startswith("distribution_owned:"):
                collecting = True
                continue
            if collecting:
                if line.startswith("  - "):
                    owned.append(line[4:].strip())
                elif line.strip() and not line.startswith(" "):
                    break
        self.assertNotIn("cron", owned)

    def test_the_readme_separates_surviving_from_resuming(self):
        """Conflating the two is what makes a reader think it is fixed."""
        readme = self.readme()
        self.assertIn("gateway install", readme)
        self.assertIn("gateway run", readme)
        # The distinction has to be stated, not implied.
        self.assertIn("Only if the gateway was installed", readme)

    def test_the_readme_states_the_backlog_is_collapsed(self):
        readme = self.readme()
        self.assertIn("One of them", readme)
        self.assertRegex(readme, r"does not wake to ninety-six")

    def test_the_backlog_claim_matches_the_schedule_it_cites(self):
        """Ninety-six is two days of the documented intake cadence."""
        script = (self.RECIPE / "scripts" / "register-jobs.sh").read_text(
            encoding="utf-8")
        self.assertIn('register intake "*/30 * * * *"', script)
        per_day = 24 * 60 // 30
        self.assertEqual(per_day * 2, 96)


class CollectorCase(unittest.TestCase):
    """Fixture shared by the collector-behaviour classes below."""

    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.recipe = Path(tempfile.mkdtemp())
        shutil.copytree(HERE, self.recipe / "scripts")
        self.db = Path(self.home) / "workspace" / "ledger" / "state.db"
        self.db.parent.mkdir(parents=True)
        with sqlite3.connect(self.db) as c:
            c.executescript(SCHEMA)

    def _collector(self, body):
        (self.recipe / "scripts" / "ingest_graph.py").write_text(
            "import sys\n" + body + "\n", encoding="utf-8")

    def _add_pending(self, sid):
        with sqlite3.connect(self.db) as c:
            c.execute("INSERT INTO items(source_id, source, scope, event_at, state)"
                      " VALUES (?,'email','inbox','2026-08-18T00:00:00Z','pending')",
                      (sid,))

    def _run(self):
        proc = subprocess.run(
            [sys.executable, str(self.recipe / "scripts" / "select_intake.py")],
            capture_output=True, text=True,
            env={**os.environ, "HERMES_HOME": self.home})
        body = proc.stdout.split('{"wakeAgent"')[0]
        return json.loads(body), proc.stdout

    def _graph(self, payload):
        return payload["collected"]["ingest_graph.py"]


class TestACollectorFailureIsVisible(CollectorCase):
    """A connector that stops working must not be silent.

    This is the worst failure this design can have, and it was the shipped
    behaviour: a collector whose credential expired wrote to stderr and exited
    non-zero while printing nothing, `json.loads("" or "{}")` turned that into
    an empty success, and the idle gate then skipped the agent entirely. Every
    half hour, forever, with nothing anywhere saying so. Slack's rotating user
    tokens make an expired credential an ordinary event rather than an
    exceptional one, so this path is the one that matters most.
    """

    def test_a_nonzero_exit_with_no_output_is_recorded_as_a_failure(self):
        self._collector('print("", end=""); print("token expired", file=sys.stderr); sys.exit(1)')
        payload, _ = self._run()
        entry = self._graph(payload)
        self.assertTrue(entry["failed"])
        self.assertEqual(entry["exit_code"], 1)
        self.assertEqual(entry["error_class"], "nonzero_exit")
        # The collector's own text belongs in neither the prompt nor the local
        # log; only the sanitized failure metadata is retained.
        self.assertNotIn("token expired", json.dumps(payload))

    def test_a_nonzero_exit_with_valid_json_is_still_a_failure(self):
        """Readable output does not mean the run succeeded."""
        self._collector('print(\'{"seen": 3}\'); sys.exit(2)')
        payload, _ = self._run()
        self.assertTrue(self._graph(payload)["failed"])
        self.assertEqual(self._graph(payload)["exit_code"], 2)

    def test_unreadable_output_from_a_clean_exit_is_a_failure(self):
        self._collector('print("not json"); sys.exit(0)')
        payload, _ = self._run()
        self.assertTrue(self._graph(payload)["failed"])
        self.assertEqual(self._graph(payload)["error_class"], "unreadable_output")

    def test_a_failure_with_no_pending_rows_still_wakes_the_agent(self):
        """The gate makes an idle tick free; it must not make a broken one quiet."""
        self._collector('print("", end=""); print("boom", file=sys.stderr); sys.exit(1)')
        payload, stdout = self._run()
        self.assertEqual(payload["slice"], [])
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.assertNotEqual(lines[-1].strip(), '{"wakeAgent": false}')

    def test_a_healthy_collector_with_no_rows_still_gates(self):
        """The fix must not cost the saving the gate exists for."""
        self._collector('print(\'{"seen": 0}\'); sys.exit(0)')
        _, stdout = self._run()
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.assertEqual(lines[-1].strip(), '{"wakeAgent": false}')

    def test_a_failure_does_not_stop_pending_rows_being_offered(self):
        self._collector('print("", end=""); print("boom", file=sys.stderr); sys.exit(1)')
        self._add_pending("m1")
        payload, _ = self._run()
        self.assertEqual(len(payload["slice"]), 1)
        self.assertTrue(self._graph(payload)["failed"])


class TestTheInstallerRefusesTheWrongPlatform(unittest.TestCase):
    """Documentation that says "Linux only" and code that installs anywhere.

    The README states the scheduled path does not work on macOS, and the
    scripts installed and registered seven jobs there regardless — producing
    exactly the model-without-skill calls the same document warns about. A
    warning nothing enforces is not a warning.
    """

    RECIPE = HERE.parents[1]
    SCRIPTS = ("install.sh", "register-jobs.sh")

    def _with_uname(self, kernel):
        """Run each script with `uname` reporting a chosen kernel."""
        fake = Path(tempfile.mkdtemp())
        (fake / "uname").write_text(f"#!/bin/sh\necho {kernel}\n", encoding="utf-8")
        (fake / "uname").chmod(0o755)
        return fake

    def _run(self, script, kernel):
        fake = self._with_uname(kernel)
        return subprocess.run(
            ["bash", str(self.RECIPE / "scripts" / script)],
            capture_output=True, text=True, cwd=str(self.RECIPE),
            env={**os.environ, "PATH": f"{fake}:{os.environ['PATH']}",
                 "PROFILE_NAME": "does-not-exist-under-test"})

    def test_darwin_is_refused_by_both_scripts(self):
        for script in self.SCRIPTS:
            with self.subTest(script=script):
                proc = self._run(script, "Darwin")
                self.assertEqual(proc.returncode, 1)
                self.assertIn("only works on Linux", proc.stderr)
                self.assertIn("Darwin", proc.stderr)

    def test_the_refusal_names_the_path_that_does_work(self):
        proc = self._run("install.sh", "Darwin")
        self.assertIn("walkthrough.py", proc.stderr)

    def test_linux_is_accepted_and_reaches_the_next_check(self):
        """The guard must gate on the platform and nothing else."""
        for script in self.SCRIPTS:
            with self.subTest(script=script):
                proc = self._run(script, "Linux")
                combined = proc.stdout + proc.stderr
                self.assertNotIn("only works on Linux", combined)

    def test_the_guard_runs_before_anything_is_installed(self):
        """Position matters: a guard after the first mutation is not a guard."""
        for script in self.SCRIPTS:
            with self.subTest(script=script):
                text = (self.RECIPE / "scripts" / script).read_text(encoding="utf-8")
                guard_at = text.index("require_linux\n")
                for verb in ("hermes profile install", "cron create", "cp \""):
                    if verb in text:
                        self.assertLess(guard_at, text.index(verb),
                                        f"{script} runs `{verb}` before the guard")


class TestTheSliceBoundCannotBeDefeated(unittest.TestCase):
    """The bound is the product, so an override must not be able to remove it.

    SQLite reads a negative `LIMIT` as no limit, so `INTAKE_SLICE=-1` handed
    the model every pending row in the store — silently, and past the cap this
    recipe is built on. Zero fails the other way: the job wakes, says it has
    work, and offers none. Malformed text raised during import, before any
    message could name the variable.
    """


    # Both selectors read their bound through the same helper, so every case
    # below runs against both — `REVIEW_BATCH` was named in the finding too.
    SELECTORS = (("select_intake.py", "INTAKE_SLICE"),
                 ("select_review.py", "REVIEW_BATCH"))
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.db = Path(self.home) / "workspace" / "ledger" / "state.db"
        self.db.parent.mkdir(parents=True)
        with sqlite3.connect(self.db) as c:
            c.executescript(SCHEMA)
            for n in range(60):
                c.execute(
                    "INSERT INTO items(source_id, source, scope, event_at, state)"
                    " VALUES (?,'email','inbox','2026-08-18T00:00:00Z','pending')",
                    (f"m{n}",))
            for n in range(60):
                c.execute(
                    "INSERT INTO obligations(id, source_id, title, priority, status)"
                    " VALUES (?,?,?,'high','open')", (f"o{n}", f"m{n}", f"t{n}"))

    def _run(self, script, **env):
        return subprocess.run(
            [sys.executable, str(HERE / script)], capture_output=True, text=True,
            env={**os.environ, "HERMES_HOME": self.home, **env})

    def _slice_size(self, proc, key):
        return len(json.loads(proc.stdout.split('{"wakeAgent"')[0])[key])

    def test_the_default_bound_holds(self):
        self.assertEqual(self._slice_size(self._run("select_intake.py"), "slice"), 25)
        self.assertEqual(
            self._slice_size(self._run("select_review.py"), "batch"), 15)

    def test_a_negative_override_is_refused_rather_than_unbounded(self):
        for script, var in self.SELECTORS:
            with self.subTest(script=script):
                proc = self._run(script, **{var: "-1"})
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(var, proc.stderr)
                self.assertNotIn('"slice"', proc.stdout)

    def test_zero_is_refused(self):
        for script, var in self.SELECTORS:
            with self.subTest(script=script):
                proc = self._run(script, **{var: "0"})
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn("between 1 and", proc.stderr)

    def test_malformed_text_names_the_variable_instead_of_raising(self):
        for script, var in self.SELECTORS:
            with self.subTest(script=script):
                proc = self._run(script, **{var: "abc"})
                self.assertNotEqual(proc.returncode, 0)
                self.assertIn(var, proc.stderr)
                self.assertNotIn("Traceback", proc.stderr)

    def test_an_override_above_the_ceiling_is_refused(self):
        for script, var in self.SELECTORS:
            with self.subTest(script=script):
                proc = self._run(script, **{var: "9999"})
                self.assertNotEqual(proc.returncode, 0)

    def test_a_valid_override_still_works(self):
        """The guard must not remove the knob, only bound it."""
        proc = self._run("select_intake.py", INTAKE_SLICE="40")
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self._slice_size(proc, "slice"), 40)


class TestTheInstallerCarriesSettingsNotSecrets(unittest.TestCase):
    """The installer used to copy `~/.hermes/config.yaml` into the new profile.

    That file's own `model:` block is documented to hold an inline `api_key`,
    and a generated config really does put one there, so the copy duplicated a
    credential into a second file while the README told the reader no
    credentials were involved. It bought nothing either, though not for the
    reason first given here: a profile with no key of its own does not
    authenticate through the config it inherits — it sends the placeholder
    `no-key-required` — so the fix is to require a key on the target profile
    rather than to copy one.

    These assertions pin the shape that depends on — named settings through the
    CLI, no file copy, every transfer failing closed and read back, and both
    runnability checks landing before anything is scheduled.
    """

    INSTALL = HERE.parents[1] / "scripts" / "install.sh"
    CARRIED = ("model.default", "model.provider", "model.base_url")

    def setUp(self):
        self.text = self.INSTALL.read_text(encoding="utf-8")
        # Comments explain the old behavior, so they would match every pattern
        # below and hide a regression in the code they describe.
        self.code = "\n".join(line for line in self.text.splitlines()
                               if not line.lstrip().startswith("#"))
        # The remediation text tells the reader to run `config set
        # model.api_key`, which is an instruction rather than a transfer. A
        # test that cannot tell printing from doing fails on its own advice.
        self.commands = "\n".join(
            line for line in self.code.splitlines()
            if not line.lstrip().startswith("echo "))

    def test_no_config_file_is_copied_into_the_profile(self):
        self.assertIsNone(
            re.search(r"\bcp\b[^\n]*config\.yaml", self.code),
            "installer copies config.yaml again; that carries an inline "
            "api_key into the new profile")

    def test_each_model_setting_is_transferred_through_the_cli(self):
        for key in self.CARRIED:
            self.assertIn(key, self.code, f"{key} is no longer carried over")
        self.assertIn("config set", self.code,
                      "settings must move through `hermes config set`")

    def test_nothing_named_like_a_credential_is_transferred(self):
        for secret in ("api_key", "sudo_password", "auth.json", ".env"):
            self.assertIsNone(
                re.search(rf"config set[^\n]*{re.escape(secret)}",
                          self.commands),
                f"installer transfers {secret} into the new profile")

    def test_the_runnability_check_runs_before_any_job_is_registered(self):
        check = self.code.find("config get model.default")
        register = self.code.find("register-jobs.sh")
        self.assertNotEqual(check, -1, "no model-resolution check remains")
        self.assertNotEqual(register, -1, "installer no longer registers jobs")
        self.assertLess(check, register,
                        "the check must precede registration, or the exit "
                        "leaves seven jobs scheduled against a dead profile")

    def test_an_unresolvable_model_exits_non_zero(self):
        """The check has to end the run, not merely print a complaint."""
        after = self.code[self.code.find("config get model.default"):]
        window = after[:after.find("register-jobs.sh")]
        self.assertIn("exit 1", window,
                      "an unresolvable model must abort, not warn and continue")

    def test_a_missing_credential_aborts_before_registration(self):
        """A model name alone does not make a profile runnable.

        The credential is not inherited. A profile carrying only the three
        settings sends the literal placeholder `no-key-required`, so every
        scheduled job fails to authenticate — silently, in the logs, four times
        an hour. The check belongs where a person is watching.
        """
        check = self.code.find("config get model.api_key")
        register = self.code.find("register-jobs.sh")
        self.assertNotEqual(check, -1, "no credential check")
        self.assertLess(check, register,
                        "the credential check must precede registration")
        window = self.code[check:register]
        self.assertIn("exit 1", window,
                      "a missing credential must abort, not warn and continue")

    def test_the_no_credential_case_has_a_deliberate_opt_out(self):
        """Endpoints that need no key are real; they just have to say so."""
        self.assertIn("ALLOW_NO_API_KEY", self.code,
                      "no way to install against a keyless endpoint")

    def test_the_credential_is_never_printed(self):
        """Reading a key is fine; echoing it into a terminal is not."""
        for line in self.code.splitlines():
            if "echo" in line and "$credential" in line:
                self.fail(f"installer echoes the credential: {line.strip()}")


class TestTheReadmeDescribesTheInstallerItShips(unittest.TestCase):
    """The README documented a copy and an override that no longer exist.

    `SOURCE_PROFILE_CONFIG` was removed with the file copy, and a reader
    following the old paragraph would set a variable nothing reads.
    """

    RECIPE = HERE.parents[1]

    def setUp(self):
        self.readme = (self.RECIPE / "README.md").read_text(encoding="utf-8")
        self.install = (self.RECIPE / "scripts" / "install.sh").read_text(
            encoding="utf-8")

    def test_the_readme_names_no_environment_variable_the_script_ignores(self):
        for name in re.findall(r"`([A-Z][A-Z0-9_]{3,})`", self.readme):
            if name in ("HERMES_HOME", "PROFILE_NAME", "INTAKE_SLICE",
                        "REVIEW_BATCH"):
                continue
            if name.startswith("NEMOCLAW") or name.startswith("SOURCE_"):
                self.assertIn(name, self.install,
                              f"README documents {name}; install.sh never "
                              "reads it")

    def test_the_readme_does_not_promise_a_config_copy(self):
        self.assertNotIn("copy of `~/.hermes/config.yaml`", self.readme,
                         "README still describes the removed file copy")


class TestCollectorDiagnosticsStayOutOfThePrompt(CollectorCase):
    """A failing collector's own output is untrusted text, and stdout is a prompt.

    Making the failure visible was right; carrying the collector's stderr into
    the payload to do it was not. That stdout becomes the scheduled agent's
    prompt, and a collector is a subprocess talking to a mail or chat API — its
    stderr is a traceback that can hold a bearer token, a signed URL, or a
    stranger's message body. Truncating to two hundred characters bounds the
    length and not the content; the first two hundred characters of a traceback
    are where the request line is.

    The payload and local log carry only a stable error class and an exit code.
    The collector's own text is dropped from both streams.
    """

    SECRET = "Bearer xoxp-9999-SECRET-TOKEN-VALUE"
    URL = "https://graph.example.com/v1/me?sig=AAAABBBBCCCC"

    def _run_full(self):
        return subprocess.run(
            [sys.executable, str(self.recipe / "scripts" / "select_intake.py")],
            capture_output=True, text=True,
            env={**os.environ, "HERMES_HOME": self.home})

    def _failing_collector_leaking(self):
        self._collector(
            f'sys.stderr.write("Traceback: auth failed\\n'
            f'  headers={{\'Authorization\': \'{self.SECRET}\'}}\\n'
            f'  url={self.URL}\\n")\nsys.exit(1)')

    def test_secret_shaped_stderr_never_reaches_stdout(self):
        self._failing_collector_leaking()
        proc = self._run_full()
        for leaked in (self.SECRET, "xoxp-", "SECRET-TOKEN-VALUE", self.URL,
                       "sig=AAAABBBBCCCC"):
            self.assertNotIn(leaked, proc.stdout,
                             f"{leaked!r} reached the agent prompt")

    def test_no_raw_stderr_field_survives_in_the_payload(self):
        """The field itself is the hazard, whatever a given run puts in it."""
        self._failing_collector_leaking()
        proc = self._run_full()
        self.assertNotIn('"stderr"', proc.stdout,
                         "the payload still carries a raw stderr field")

    def test_the_secret_is_absent_from_stderr_as_well(self):
        """Moving it out of the prompt only moved the problem.

        The scheduler captures this process's stderr into the job log, so text
        that was transient in a subprocess becomes a file that outlives the
        token in it. Neither stream may carry it.
        """
        self._failing_collector_leaking()
        proc = self._run_full()
        for leaked in (self.SECRET, "xoxp-", "SECRET-TOKEN-VALUE", self.URL,
                       "sig=AAAABBBBCCCC"):
            self.assertNotIn(leaked, proc.stderr,
                             f"{leaked!r} was written to the job log")

    def test_stderr_still_says_which_collector_failed_and_how(self):
        """Dropping the text must not mean dropping the signal."""
        self._collector('sys.stderr.write("boom\\n")\nsys.exit(3)')
        proc = self._run_full()
        self.assertIn("ingest_graph.py", proc.stderr)
        self.assertIn("3", proc.stderr)
        self.assertIn("nonzero_exit", proc.stderr)
        self.assertNotIn("boom", proc.stderr,
                         "the collector's own text is still being quoted")

    def test_the_payload_says_what_class_of_failure_it_was(self):
        """The agent still needs enough to act on, just nothing quotable."""
        self._collector('sys.stderr.write("boom\\n")\nsys.exit(3)')
        payload, _ = self._run()
        graph = self._graph(payload)
        self.assertTrue(graph["failed"])
        self.assertEqual(graph["exit_code"], 3)
        self.assertEqual(graph["error_class"], "nonzero_exit")

    def test_unreadable_output_is_classed_without_quoting_the_output(self):
        self._collector('print("{not json")\nsys.exit(0)')
        payload, stdout = self._run()
        graph = self._graph(payload)
        self.assertEqual(graph["error_class"], "unreadable_output")
        self.assertNotIn("not json", stdout,
                         "the unparsable text was quoted back into the prompt")


class TestAFailedTransferStopsTheInstall(unittest.TestCase):
    """`set -e` does not abort on the left operand of `&&`.

    The carry loop was written `config set … && echo …`, on the assumption that
    `set -euo pipefail` would end the run if the set failed. It does not:
    `false && echo` is a no-op, not an abort. So a profile could take
    `model.default`, silently drop `model.provider` and `model.base_url`, pass
    the model check — which only asks about `model.default` — pass the
    credential check, and get all seven jobs registered against whatever route
    it had left.

    Exit status alone is also not proof the value landed, so each carried
    setting is read back off the target profile and compared.

    These tests stub `hermes` on PATH and assert on what the installer does,
    not on what the script says. The earlier installer tests all read the file
    and matched patterns in it, which is why none of them could see this.
    """

    RECIPE = HERE.parents[1]

    def setUp(self):
        self.bin = Path(tempfile.mkdtemp())
        self.state = Path(tempfile.mkdtemp())
        self.profile_home = Path(tempfile.mkdtemp())
        self.log = self.state / "calls.log"
        (self.bin / "uname").write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
        (self.bin / "uname").chmod(0o755)
        (self.bin / "hermes").write_text(HERMES_STUB, encoding="utf-8")
        (self.bin / "hermes").chmod(0o755)
        for key, value in (("model.default", "some/model"),
                           ("model.provider", "custom"),
                           ("model.base_url", "https://example.invalid/v1")):
            (self.state / f"source.{key}").write_text(value, encoding="utf-8")

    def _install(self, **env):
        return subprocess.run(
            ["bash", str(self.RECIPE / "scripts" / "install.sh")],
            capture_output=True, text=True, cwd=str(self.RECIPE),
            env={**os.environ,
                 "PATH": f"{self.bin}:{os.environ['PATH']}",
                 "PROFILE_NAME": "under-test",
                 "STUB_STATE": str(self.state),
                 "STUB_PROFILE_HOME": str(self.profile_home),
                 "STUB_LOG": str(self.log),
                 **env})

    def _registered(self):
        """Did anything reach the scheduler?"""
        if not self.log.exists():
            return False
        return "cron" in self.log.read_text(encoding="utf-8")

    # These pass `ALLOW_NO_API_KEY` so the credential gate cannot be what stops
    # the run. Without it the first draft of `schedules_nothing` passed against
    # the broken installer, because a later check happened to abort first.
    def test_a_failing_transfer_aborts_instead_of_being_skipped(self):
        proc = self._install(STUB_FAIL_SET="model.provider", ALLOW_NO_API_KEY="1")
        self.assertNotEqual(proc.returncode, 0,
                            "installer exited 0 after a transfer failed")
        self.assertIn("model.provider", proc.stderr)

    def test_a_failing_transfer_schedules_nothing(self):
        self._install(STUB_FAIL_SET="model.provider", ALLOW_NO_API_KEY="1")
        self.assertFalse(self._registered(),
                         "jobs were registered on a half-configured profile")

    def test_a_setting_that_does_not_stick_is_caught_by_read_back(self):
        """A `config set` can exit 0 and still not be there afterwards."""
        proc = self._install(STUB_ACCEPT_WITHOUT_WRITING="model.base_url",
                             ALLOW_NO_API_KEY="1")
        self.assertNotEqual(proc.returncode, 0,
                            "a silently dropped setting installed cleanly")
        self.assertIn("did not keep", proc.stderr)
        self.assertFalse(self._registered())

    def test_a_clean_transfer_reaches_registration(self):
        """The guard must not block the path it exists to protect."""
        proc = self._install(ALLOW_NO_API_KEY="1")
        self.assertEqual(proc.returncode, 0, proc.stderr[-400:])
        self.assertTrue(self._registered(),
                        "a fully configured profile never reached the scheduler")


HERMES_STUB = r"""#!/bin/sh
# A stand-in for the parts of `hermes` the installer touches. Records every
# invocation so a test can ask whether the scheduler was ever reached.
printf '%s\n' "$*" >> "$STUB_LOG"
prof=""
if [ "$1" = "-p" ]; then prof="$2"; shift 2; fi
case "$1 $2" in
  "profile install") exit 0 ;;
  "profile show") echo "Path: $STUB_PROFILE_HOME"; exit 0 ;;
  "config get")
      if [ -n "$prof" ]; then f="$STUB_STATE/target.$3"; else f="$STUB_STATE/source.$3"; fi
      if [ -f "$f" ]; then cat "$f"; exit 0; fi
      echo "Config key not set: $3"; exit 1 ;;
  "config set")
      [ "$3" = "$STUB_FAIL_SET" ] && exit 1
      [ "$3" = "$STUB_ACCEPT_WITHOUT_WRITING" ] && exit 0
      printf '%s' "$4" > "$STUB_STATE/target.$3"; exit 0 ;;
esac
exit 0
"""


class TestAnUnconfiguredConnectorDoesNotCostATick(CollectorCase):
    """Shipping a collector must not make every idle tick wake the model.

    Adding `ingest_slack.py` did exactly that for one commit: the selector runs
    whatever collectors are present, an unconfigured one exited non-zero, that
    counted as a failure, and the failure suppressed the idle gate. Every user
    who had not connected Slack would have woken the model every half hour,
    forever, to be told there was nothing to do — the scheduled expense with
    none of the assistant.

    A collector that has never been configured now reports that state and exits
    zero. One that *was* configured and lost its credential still fails loudly.
    """

    def test_a_collector_reporting_unconfigured_still_gates(self):
        self._collector('print(\'{"unconfigured": true}\')')
        _, stdout = self._run()
        lines = [line for line in stdout.splitlines() if line.strip()]
        self.assertEqual(lines[-1].strip(), '{"wakeAgent": false}',
                         "an unconfigured connector suppressed the idle gate")

    def test_the_shipped_slack_collector_gates_when_unconfigured(self):
        """Not a stand-in: the real file, with no token in the environment."""
        env = {k: v for k, v in os.environ.items() if k != "SLACK_USER_TOKEN"}
        proc = subprocess.run(
            [sys.executable, str(self.recipe / "scripts" / "select_intake.py")],
            capture_output=True, text=True, env={**env, "HERMES_HOME": self.home})
        lines = [line for line in proc.stdout.splitlines() if line.strip()]
        self.assertEqual(lines[-1].strip(), '{"wakeAgent": false}',
                         "the shipped Slack collector woke the agent on an "
                         "empty store with no credential configured")


class TestTheSlackSetupKnowsWhichMachineItIsOn(unittest.TestCase):
    """`install.sh` and `setup-slack.sh` run in different places.

    A NemoClaw sandbox has `hermes` and no `openshell`; the host has
    `openshell` and no `hermes`. Both scripts sit in the same directory, so
    running the second where the first belongs is the obvious mistake — and
    the obvious fallback, writing the token into the profile's `.env`, would
    silently abandon the gateway-held credential the user chose. Verified on a
    real sandbox: `command -v openshell` is empty there and `command -v hermes`
    is empty on the host.
    """

    SCRIPT = HERE.parents[1] / "scripts" / "setup-slack.sh"

    def _run(self, env):
        fake = Path(tempfile.mkdtemp())
        (fake / "uname").write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
        (fake / "uname").chmod(0o755)
        # System paths for `bash` and `uname`'s neighbours, but deliberately
        # not `~/.local/bin`, which is where a real host keeps `openshell`.
        return subprocess.run(
            ["bash", str(self.SCRIPT)], capture_output=True, text=True,
            env={"PATH": f"{fake}:/bin:/usr/bin",
                 "HOME": os.environ.get("HOME", "/tmp"), **env})

    def test_inside_a_sandbox_it_says_to_run_it_on_the_host(self):
        proc = self._run({"OPENSHELL_SANDBOX": "hermes"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("host", proc.stderr.lower())

    def test_no_dotenv_fallback_is_offered_anywhere(self):
        """There is no supported path that puts a Slack token in the profile.

        An earlier draft fell back to writing one into `.env` when `openshell`
        was absent. That silently abandoned gateway custody — and with rotation
        required, a token written there would expire in twelve hours with
        nothing to renew it. Refusing is the honest answer in both places.
        """
        for env in ({"OPENSHELL_SANDBOX": "hermes"}, {}):
            proc = self._run(env)
            self.assertNotEqual(proc.returncode, 0)
            self.assertNotIn("SLACK_USER_TOKEN=xox", proc.stderr,
                             "a .env fallback is still being offered")

    def test_off_a_sandbox_it_says_the_gateway_is_required(self):
        proc = self._run({})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("gateway", proc.stderr.lower())

    def test_the_two_scripts_do_not_claim_to_need_the_same_cli(self):
        install = (HERE.parents[1] / "scripts" / "install.sh").read_text()
        setup = self.SCRIPT.read_text()
        self.assertIn("command -v hermes", install)
        self.assertIn("command -v openshell", setup)
        self.assertNotIn("command -v openshell", install,
                         "install.sh now needs a CLI the sandbox does not have")


class TestTheEncryptionPrerequisiteIsEstablishedNotMentioned(unittest.TestCase):
    """Decision 5 on #122 gates real message bodies on encryption at rest.

    A prerequisite that only appears in prose is the finding class this review
    has raised repeatedly, so the setup flow refuses to attach a provider until
    the operator has answered — and it says what it could and could not check,
    rather than implying it verified something it cannot see.
    """

    RECIPE = HERE.parents[1]
    SCRIPT = RECIPE / "scripts" / "setup-slack.sh"

    def test_the_prerequisite_has_its_own_page(self):
        page = self.RECIPE / "docs" / "encrypted-storage.md"
        self.assertTrue(page.exists())
        text = page.read_text(encoding="utf-8")
        self.assertIn("not encryption", text)

    # What the registered profile is supposed to look like. The tests below
    # bend one field at a time, because the finding was that a profile could
    # be wrong in a way independent substring checks could not see.
    GOOD_PROFILE = {
        "id": "memory-driven-cos-slack-user",
        "endpoints": [{"host": "slack.com", "port": 443, "protocol": "rest",
                       "access": "read-only", "enforcement": "enforce"}],
        "credentials": [{"env_vars": ["SLACK_USER_TOKEN"]}],
        "binaries": ["/usr/bin/python3"],
    }

    def fake_openshell(self, folder, *, reusable=True, policy=None):
        """An `openshell` on PATH that reports a provider worth reusing.

        The reuse path is the one that skipped the gate, and it cannot be
        reached without a gateway answering. Stubbing the command is what lets
        the script actually run to that branch.
        """
        stub = folder / "openshell"
        rows = "mdcos-slack  memory-driven-cos-slack-user  1" if reusable else ""
        profile = json.dumps(dict(self.GOOD_PROFILE, **(policy or {})))
        stub.write_text(f"""#!/usr/bin/env bash
case "$1 $2" in
  "sandbox provider") cat <<'LIST'
NAME  TYPE  CREDENTIAL_KEYS
{rows}
LIST
  ;;
  "provider get") printf 'Type: memory-driven-cos-slack-user\\nCredential keys: SLACK_USER_TOKEN\\n' ;;
  "provider refresh") printf 'STRATEGY oauth2_refresh_token STATUS refreshed\\n' ;;
  "provider profile") cat <<'JSON'
{profile}
JSON
  ;;
  *) exit 0 ;;
esac
""", encoding="utf-8")
        stub.chmod(0o755)

        # The script refuses to run outside Linux, which is a different gate
        # and not what these tests are about. Answering `uname` keeps them
        # runnable on a contributor's machine; the Linux refusal has its own
        # test elsewhere.
        uname = folder / "uname"
        uname.write_text("#!/usr/bin/env bash\necho Linux\n", encoding="utf-8")
        uname.chmod(0o755)
        return folder

    def run_setup(self, folder, env):
        base = {"PATH": f"{folder}:{os.environ['PATH']}",
                "HOME": str(folder), "OPENSHELL_SANDBOX": ""}
        base.update(env)
        return subprocess.run(
            ["bash", str(self.SCRIPT)], capture_output=True, text=True,
            stdin=subprocess.DEVNULL, cwd=str(self.RECIPE), env=base)

    def test_the_gate_runs_even_when_a_usable_provider_is_already_attached(self):
        """The reproduced defect: reuse exited 0 without ever checking.

        The previous test for this compared the position of two strings in the
        source. The early exit sits between them, so it stayed green for as
        long as the bypass shipped. This runs the script.
        """
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder)
            proc = self.run_setup(folder, {})
        self.assertNotEqual(proc.returncode, 0,
                            "setup succeeded without checking storage")
        self.assertNotIn("Nothing to do", proc.stdout,
                         "reported a finished setup with the prerequisite "
                         "unchecked")
        self.assertIn("SANDBOX_STORAGE_PATH", proc.stdout + proc.stderr)

    def test_the_gate_runs_before_anything_is_inspected(self):
        """Ordering asserted by what the run produced, not by source offsets."""
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder, reusable=False)
            proc = self.run_setup(folder, {})
        out = proc.stdout + proc.stderr
        self.assertIn("SANDBOX_STORAGE_PATH", out)
        self.assertNotIn("none attached that exposes", out,
                         "looked for a credential before checking the "
                         "prerequisite")

    def test_a_named_path_that_does_not_exist_stops_the_run(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder)
            proc = self.run_setup(
                folder, {"SANDBOX_STORAGE_PATH": str(folder / "nope")})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not exist", proc.stdout + proc.stderr)

    def refuses_policy(self, policy, expected):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder, policy=policy)
            proc = self.run_setup(folder, {
                "SANDBOX_STORAGE_PATH": str(folder),
                "STORE_ENCRYPTION_ACKNOWLEDGED": "1"})
        out = proc.stdout + proc.stderr
        self.assertNotIn("Nothing to do", out,
                         f"reused a provider whose profile is {expected}")
        return out

    def test_a_read_write_slack_endpoint_is_not_reused(self):
        """The recipe never writes to Slack; the boundary is what enforces it."""
        out = self.refuses_policy(
            {"endpoints": [{"host": "slack.com", "port": 443,
                            "protocol": "rest", "access": "read-write",
                            "enforcement": "enforce"}]},
            "read-write")
        self.assertIn("read-only", out)

    def test_an_unenforced_endpoint_is_not_reused(self):
        """`observe` watches a write go through and records it."""
        out = self.refuses_policy(
            {"endpoints": [{"host": "slack.com", "port": 443,
                            "protocol": "rest", "access": "read-only",
                            "enforcement": "observe"}]},
            "unenforced")
        self.assertIn("enforce", out)

    def test_a_second_host_is_not_reused(self):
        """The defect the substring checks allowed: a read-only entry for one
        host and something else for another, both matching the old greps."""
        out = self.refuses_policy(
            {"endpoints": [
                {"host": "slack.com", "port": 443, "protocol": "rest",
                 "access": "read-only", "enforcement": "enforce"},
                {"host": "files.slack.example", "port": 443,
                 "protocol": "rest", "access": "read-write",
                 "enforcement": "enforce"}]},
            "wider than slack.com")
        self.assertIn("files.slack.example", out)

    def test_a_profile_that_does_not_declare_the_credential_is_not_reused(self):
        out = self.refuses_policy(
            {"credentials": [{"env_vars": ["SLACK_BOT_TOKEN"]}]},
            "bound to a different credential")
        self.assertIn("SLACK_USER_TOKEN", out)

    def test_a_profile_with_no_binary_allow_list_is_not_reused(self):
        """Without one, any process in the sandbox can spend the credential."""
        out = self.refuses_policy({"binaries": []}, "unbounded by binary")
        self.assertIn("binary", out)

    VALIDATOR = RECIPE / "scripts" / "validate-provider-profile.sh"

    def validate(self, policy):
        """Run the shipped validator against a profile with one field bent.

        Invoked directly rather than through `setup-slack.sh`, because step 5
        of that script exchanges an authorization code against Slack — a run
        that reaches the profile check has already talked to a live service.
        This is the same file both paths source.
        """
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder, policy=policy)
            proc = subprocess.run(
                ["bash", str(self.VALIDATOR), "memory-driven-cos-slack-user"],
                capture_output=True, text=True,
                env={"PATH": f"{folder}:{os.environ['PATH']}",
                     "HOME": str(folder),
                     "USABLE_KEY": "SLACK_USER_TOKEN",
                     "WANT_HOST": "slack.com"})
        return proc.returncode, proc.stdout + proc.stderr

    def test_the_expected_profile_passes(self):
        """Strictness that rejects the shipped profile is not strictness."""
        code, out = self.validate(None)
        self.assertEqual(code, 0, out)

    def test_a_read_write_endpoint_is_refused(self):
        """Two independent greps passed this: the read-only match came from a
        different endpoint than the slack.com one."""
        code, out = self.validate(
            {"endpoints": [{"host": "slack.com", "port": 443,
                            "protocol": "rest", "access": "read-write",
                            "enforcement": "enforce"}]})
        self.assertNotEqual(code, 0)
        self.assertIn("read-only", out)

    def test_an_unenforced_endpoint_is_refused(self):
        """`observe` watches a write go through and records it."""
        code, out = self.validate(
            {"endpoints": [{"host": "slack.com", "port": 443,
                            "protocol": "rest", "access": "read-only",
                            "enforcement": "observe"}]})
        self.assertNotEqual(code, 0)
        self.assertIn("enforce", out)

    def test_a_second_endpoint_is_refused(self):
        code, out = self.validate(
            {"endpoints": [
                {"host": "slack.com", "port": 443, "protocol": "rest",
                 "access": "read-only", "enforcement": "enforce"},
                {"host": "files.slack.example", "port": 443,
                 "protocol": "rest", "access": "read-write",
                 "enforcement": "enforce"}]})
        self.assertNotEqual(code, 0)
        self.assertIn("files.slack.example", out)

    def test_a_missing_slack_endpoint_is_refused(self):
        code, out = self.validate(
            {"endpoints": [{"host": "example.invalid", "port": 443,
                            "protocol": "rest", "access": "read-only",
                            "enforcement": "enforce"}]})
        self.assertNotEqual(code, 0)
        self.assertIn("slack.com", out)

    def test_a_different_credential_is_refused(self):
        code, out = self.validate(
            {"credentials": [{"env_vars": ["SLACK_BOT_TOKEN"]}]})
        self.assertNotEqual(code, 0)
        self.assertIn("SLACK_USER_TOKEN", out)

    def test_a_missing_binary_allow_list_is_refused(self):
        """Without one, any process in the sandbox can spend the credential."""
        code, out = self.validate({"binaries": []})
        self.assertNotEqual(code, 0)
        self.assertIn("binary", out)

    def test_both_paths_run_it(self):
        """Reuse validated and the fresh path grepped. Asserted on the source
        because the fresh path cannot be reached without exchanging a real
        authorization code — the validator's behaviour is covered above."""
        script = self.SCRIPT.read_text(encoding="utf-8")
        self.assertEqual(script.count("validate_profile "), 2,
                         "both the reuse and the fresh path must validate")
        self.assertNotIn('grep -q "host: slack.com"', script)
        self.assertNotIn('grep -q "access: read-only"', script)

    def test_an_acknowledged_unencrypted_path_lets_the_run_continue(self):
        """The gate is a question, not a wall — but it has to be asked."""
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder)
            proc = self.run_setup(folder, {
                "SANDBOX_STORAGE_PATH": str(folder),
                "STORE_ENCRYPTION_ACKNOWLEDGED": "1"})
        self.assertIn("Nothing to do", proc.stdout,
                      "the acknowledged path should reach the reuse branch")

    def test_an_unconfirmed_prerequisite_aborts(self):
        """Run it rather than search the source for `exit 1`.

        The previous form looked between two strings in `setup-slack.sh`. The
        gate has since moved into a file both setup flows source, so the
        search window emptied and the test passed on nothing — the same shape
        of failure that let the reuse-path bypass ship.
        """
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self.fake_openshell(folder)
            proc = self.run_setup(folder, {
                "SANDBOX_STORAGE_PATH": str(folder)})
        self.assertNotEqual(proc.returncode, 0,
                            "an unconfirmed prerequisite must abort, not warn")
        self.assertNotIn("Nothing to do", proc.stdout)

    def test_the_docs_point_at_the_page(self):
        for name in ("README.md", "docs/set-up-slack.md"):
            self.assertIn("encrypted-storage.md",
                          (self.RECIPE / name).read_text(encoding="utf-8"),
                          f"{name} never mentions the prerequisite")


class TestTheEncryptionGateChecksAPathItWasGiven(unittest.TestCase):
    """The four tests above read the script; none of them runs it.

    That gap was demonstrated rather than assumed: reverting the storage path
    from `SANDBOX_STORAGE_PATH` back to `$HOME` — the defect this review
    found, where the check can approve a volume the sandbox does not use —
    left every one of them passing. A gate that cannot be seen to fail is not
    a gate, so this one runs the script.
    """

    SCRIPT = HERE.parents[1] / "scripts" / "setup-slack.sh"

    def _run(self, env=None):
        fake = Path(tempfile.mkdtemp())
        (fake / "uname").write_text("#!/bin/sh\necho Linux\n", encoding="utf-8")
        # An openshell that reports an empty provider list, so the run reaches
        # the storage gate instead of stopping at the CLI check.
        (fake / "openshell").write_text(
            "#!/bin/sh\n"
            'case "$1 $2" in\n'
            '  "sandbox provider") echo NAME; exit 0 ;;\n'
            "esac\nexit 0\n", encoding="utf-8")
        for name in ("uname", "openshell"):
            (fake / name).chmod(0o755)
        return subprocess.run(
            ["bash", str(self.SCRIPT)], capture_output=True, text=True,
            stdin=subprocess.DEVNULL,
            env={"PATH": f"{fake}:/bin:/usr/bin",
                 "HOME": os.environ.get("HOME", "/tmp"), **(env or {})})

    def test_it_refuses_to_guess_where_the_storage_lives(self):
        proc = self._run()
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("SANDBOX_STORAGE_PATH", proc.stdout + proc.stderr,
                      "the script inferred a storage location instead of "
                      "requiring one to be named")

    def test_a_path_that_does_not_exist_is_refused(self):
        proc = self._run({"SANDBOX_STORAGE_PATH": "/no/such/place"})
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("does not exist", proc.stderr)

    def test_an_unencrypted_path_is_not_waved_through(self):
        """`/tmp` is not on a crypt device in any environment this runs in."""
        proc = self._run({"SANDBOX_STORAGE_PATH": "/tmp"})
        self.assertNotEqual(proc.returncode, 0,
                            "an unencrypted path was accepted without the "
                            "operator confirming anything")
        self.assertIn("encrypted", (proc.stdout + proc.stderr).lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)
