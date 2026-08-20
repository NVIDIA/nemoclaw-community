# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Acceptance: what the cron pre-steps hand the agent, and when they decline to
wake it at all."""

import json, os, re, sqlite3, subprocess, sys, tempfile, unittest
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
    another copy of all five jobs.
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
        yield from sorted((self.RECIPE / "scripts").glob("*.sh"))
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
            found[name.strip('"')] = (schedule, skill)
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
