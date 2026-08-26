# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""What the memory-writing job is handed, and what it is not.

The selector decides who the model is even asked about. Everything it drops is
dropped silently — no page is written, nothing says why — so the filtering is
the part worth pinning. These go through the real functions against a real
store rather than asserting on a dictionary the collector never produces.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import select_memory  # noqa: E402

SCHEMA = (HERE / "schema.sql").read_text(encoding="utf-8")


def iso(days_ago: int) -> str:
    moment = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


class SelectorCase(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        (Path(self.home) / "distribution.yaml").write_text("id: test\n",
                                                           encoding="utf-8")
        self.workspace = Path(self.home) / "workspace"
        (self.workspace / "ledger").mkdir(parents=True)
        self.db = self.workspace / "ledger" / "state.db"
        with sqlite3.connect(self.db) as conn:
            conn.executescript(SCHEMA)
        os.environ["HERMES_HOME"] = self.home

    def tearDown(self):
        os.environ.pop("MEMORY_WINDOW_DAYS", None)
        shutil.rmtree(self.home, ignore_errors=True)

    def add(self, sender, *, days_ago=0, source="email", subject="s",
            body="b", scope="inbox"):
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO items(source_id, source, scope, event_at, sender,"
                " subject, body, addressing, state)"
                " VALUES (?,?,?,?,?,?,?, 'direct', 'pending')",
                (f"{sender}:{days_ago}:{body}", source, scope, iso(days_ago),
                 sender, subject, body))

    def report(self):
        """The selector's real output, parsed the way the scheduler sees it."""
        with sqlite3.connect(self.db) as conn:
            found = select_memory.evidence(
                conn, iso(select_memory.WINDOW_DAYS))
        return found

    def page(self, slug, updated=None, decay=None, kind="people",
             last_interaction=None):
        folder = self.workspace / "memory" / kind
        folder.mkdir(parents=True, exist_ok=True)
        head = ["---"]
        if updated:
            head.append(f"updated: {updated}")
        if decay:
            head.append(f"decay: {decay}")
        if last_interaction:
            head.append(f"last_interaction: {last_interaction}")
        head += ["---", "", "# page"]
        (folder / f"{slug}.md").write_text("\n".join(head), encoding="utf-8")

    def correction(self, actor="user", event_type="priority_override"):
        """One row the user wrote, through the only path that writes them."""
        with sqlite3.connect(self.db) as conn:
            conn.execute(
                "INSERT INTO obligations(id, source_id, title, status,"
                " priority, global_rank) VALUES"
                " ('o1','m1','the cutover','open','high',1)")
            conn.execute(
                "INSERT INTO events(obligation_id, event_type, actor,"
                " after_json) VALUES (?,?,?,?)",
                ("o1", event_type, actor, json.dumps({"priority": "high"})))

    def run_selector(self):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            select_memory.main()
        out = buffer.getvalue()
        lines = [line for line in out.splitlines() if line.strip()]
        return out, lines[-1]


class TestWhoIsWorthAsking(SelectorCase):
    def test_one_message_is_an_event_not_a_relationship(self):
        self.add("Dana Okoro")
        self.assertEqual(self.report()["people"], [])

    def test_two_messages_qualify(self):
        self.add("Dana Okoro", days_ago=1)
        self.add("Dana Okoro", days_ago=2, body="b2")
        self.assertEqual([p["sender"] for p in self.report()["people"]],
                         ["Dana Okoro"])

    def test_machinery_never_qualifies_however_loud(self):
        """A page for a build server teaches the ranking nothing."""
        for sender in ("no-reply@example.com", "GitLab", "jenkins",
                       "Build Notifications", "do-not-reply@x.example",
                       "jira", "some-bot"):
            for n in range(5):
                self.add(sender, days_ago=n, body=f"b{n}")
        self.assertEqual(self.report()["people"], [])

    def test_a_person_whose_name_merely_contains_a_stop_word_still_counts(self):
        """`Robotics` contains `bot`; the rule matches words, not substrings."""
        self.add("Ada Robotics", days_ago=1)
        self.add("Ada Robotics", days_ago=2, body="b2")
        self.assertEqual([p["sender"] for p in self.report()["people"]],
                         ["Ada Robotics"])

    def test_existing_pages_are_recognised_on_disk(self):
        self.add("Dana Okoro", days_ago=1)
        self.add("Dana Okoro", days_ago=2, body="b2")
        self.page("dana_okoro")
        self.assertTrue(self.report()["people"][0]["has_page"])

    def test_somebody_with_no_page_is_offered_before_somebody_with_one(self):
        """A missing page is worth more than a page a few bullets behind."""
        for n in range(9):
            self.add("Chatty Colleague", days_ago=n, body=f"b{n}")
        self.page("chatty_colleague")
        self.add("Quiet Colleague", days_ago=1)
        self.add("Quiet Colleague", days_ago=2, body="b2")
        order = [p["sender"] for p in self.report()["people"]]
        self.assertEqual(order[0], "Quiet Colleague")

    def test_the_batch_is_bounded(self):
        """A turn asked to write forty pages writes forty bad ones."""
        for i in range(select_memory.MAX_PEOPLE + 6):
            for n in range(2):
                self.add(f"Person {i:02d}", days_ago=n, body=f"b{i}{n}")
        self.assertEqual(len(self.report()["people"]),
                         select_memory.MAX_PEOPLE)

    def test_interactions_are_bounded_per_person(self):
        for n in range(select_memory.MAX_INTERACTIONS + 5):
            self.add("Dana Okoro", days_ago=n, body=f"b{n}")
        found = self.report()
        self.assertLessEqual(len(found["interactions"]["Dana Okoro"]),
                             select_memory.MAX_INTERACTIONS)


class TestIdentityIsStable(SelectorCase):
    """A page name is a durable identity, so two people must never share one."""

    # Two distinct Han-script personal names, written as escapes so a reviewer
    # can check what is being asserted without having to recognise the glyphs.
    # Any script without Latin letters would do; these reduced to the empty
    # string under the old rule, which is the failure being pinned.
    HAN_NAME_A = "\u674e\u660e"      # LI3 MING2
    HAN_NAME_B = "\u674e\u5f3a"      # LI3 QIANG2

    def test_a_non_latin_name_keeps_a_page(self):
        """It reduced to the empty string, so everyone whose name has no
        Latin letters shared one nameless page."""
        self.assertTrue(select_memory.slug(self.HAN_NAME_A))
        self.assertNotEqual(select_memory.slug(self.HAN_NAME_A),
                            select_memory.slug(self.HAN_NAME_B))

    def test_accented_letters_are_not_dropped(self):
        """A name with diacritics became `nal_z`, losing the letters it did
        not recognise — a different person's page, silently."""
        name = "\u00dcnal \u00d6z"          # U-umlaut nal, O-umlaut z
        made = select_memory.slug(name)
        self.assertIn("\u00fc", made)
        self.assertIn("\u00f6", made)

    def test_names_that_differ_only_in_punctuation_do_not_collide(self):
        """`A-B` and `A B` both became `a_b`, so the second overwrote the
        first's page."""
        self.assertNotEqual(select_memory.slug("A-B"),
                            select_memory.slug("A B"))

    def test_a_name_of_only_punctuation_still_gets_an_identity(self):
        self.assertTrue(select_memory.slug("!!!"))
        self.assertNotEqual(select_memory.slug("!!!"),
                            select_memory.slug("???"))

    def test_the_ordinary_case_stays_readable(self):
        """Collision-safety must not make every page a hash."""
        self.assertEqual(select_memory.slug("Dana Okoro"), "dana_okoro")

    def test_the_same_name_typed_differently_is_the_same_person(self):
        self.assertEqual(select_memory.slug("Dana Okoro"),
                         select_memory.slug("dana okoro"))

    def test_an_empty_name_yields_no_identity(self):
        self.assertEqual(select_memory.slug("   "), "")


class TestACleanInstallIsInitialised(SelectorCase):
    """The first run must not have to guess the structure it validates against."""

    def test_the_memory_is_created_before_the_model_sees_it(self):
        self.assertFalse((self.workspace / "memory").exists())
        self.run_selector()
        root = self.workspace / "memory"
        self.assertTrue((root / "index.md").is_file())
        self.assertTrue((root / "log.md").is_file())
        self.assertTrue((root / "people").is_dir())
        self.assertTrue((root / "attention").is_dir())

    def test_the_attention_pages_arrive_valid_rather_than_missing(self):
        """The correct initial state of the page the ranking gates on is not
        "absent" but "nothing chosen yet, and here is what would count"."""
        self.run_selector()
        page = (self.workspace / "memory" / "attention"
                / "current_priorities.md").read_text(encoding="utf-8")
        self.assertIn("type: current_priorities", page)
        self.assertIn("decay: daily", page)
        self.assertIn("has not yet observed a chosen priority", page)

    def test_the_seeded_pages_are_the_shipped_files(self):
        """Assembled in code, a page is a second copy of the schema that
        drifts the first time either changes."""
        self.run_selector()
        for source in select_memory.seed_root().rglob("*.md"):
            copied = (self.workspace / "memory"
                      / source.relative_to(select_memory.seed_root()))
            text = copied.read_text(encoding="utf-8")
            if source.name == "log.md":
                # The log is appended to as soon as it is seeded, which is the
                # point of it; the packaged text is its opening.
                self.assertTrue(text.startswith(
                    source.read_text(encoding="utf-8")))
            else:
                self.assertEqual(text, source.read_text(encoding="utf-8"),
                                 str(source.name))

    def test_the_seeded_priorities_page_is_stale_on_arrival(self):
        """So the first pass is told to look, not told everything is current."""
        self.run_selector()
        found = {a["page"]: a["state"]
                 for a in select_memory.stale_attention()}
        self.assertEqual(found.get("current_priorities"), "stale")

    def test_the_report_names_what_it_seeded(self):
        out, _ = self.run_selector()
        self.assertIn("index.md", out)
        self.assertIn("current_priorities.md", out)
        out, _ = self.run_selector()
        self.assertIn('"seeded": []', out)

    def test_the_bootstrap_is_recorded_in_the_log(self):
        """Six producers append to this file and none removes; the repair job
        reads it to explain itself later."""
        self.run_selector()
        log = (self.workspace / "memory" / "log.md").read_text(
            encoding="utf-8")
        self.assertIn("bootstrap", log)

    def test_it_does_not_overwrite_a_page_that_exists(self):
        """Non-destructive: somebody's own memory is not a thing to replace
        with the packaged copy on every tick."""
        root = self.workspace / "memory"
        (root / "attention").mkdir(parents=True)
        (root / "index.md").write_text("---\ntype: index\n---\nmine\n",
                                       encoding="utf-8")
        (root / "attention" / "current_priorities.md").write_text(
            "---\ntype: current_priorities\ndecay: daily\n---\nships next week\n",
            encoding="utf-8")
        self.run_selector()
        self.assertIn("mine", (root / "index.md").read_text(encoding="utf-8"))
        self.assertIn("ships next week",
                      (root / "attention" / "current_priorities.md").read_text(
                          encoding="utf-8"))


class TestAQuietDayCostsNothing(SelectorCase):
    """The wake gate is what makes an idle tick free, and it was never firing."""

    def current_attention(self):
        today = datetime.now(timezone.utc).date().isoformat()
        self.page("current_priorities", updated=today, decay="daily",
                  kind="attention")
        self.page("active_threads", updated=today, decay="weekly",
                  kind="attention")

    def test_an_unchanged_correspondent_does_not_wake_the_agent(self):
        """Two messages from last week and a page written since is not work.
        Treating it as work kept the agent awake every half hour for the
        length of the window."""
        self.current_attention()
        self.add("Dana Okoro", days_ago=6)
        self.add("Dana Okoro", days_ago=7, body="b2")
        today = datetime.now(timezone.utc).date().isoformat()
        self.page("dana_okoro", last_interaction=today)
        _, last = self.run_selector()
        self.assertEqual(json.loads(last), {"wakeAgent": False})

    def test_a_message_after_the_page_is_work(self):
        self.current_attention()
        today = datetime.now(timezone.utc).date().isoformat()
        old_day = (datetime.now(timezone.utc).date()
                   - timedelta(days=5)).isoformat()
        self.page("dana_okoro", last_interaction=old_day)
        self.add("Dana Okoro", days_ago=0)
        self.add("Dana Okoro", days_ago=1, body="b2")
        out, _ = self.run_selector()
        self.assertNotIn("wakeAgent", out)
        self.assertIn("Dana Okoro", out)

    def test_a_page_with_no_recorded_date_is_still_offered(self):
        """Unknown means look, not skip."""
        self.current_attention()
        self.page("dana_okoro")
        self.add("Dana Okoro", days_ago=6)
        self.add("Dana Okoro", days_ago=7, body="b2")
        out, _ = self.run_selector()
        self.assertNotIn("wakeAgent", out)

    def test_a_user_correction_is_work_on_its_own(self):
        """It is the only evidence of choosing, so it must never be slept
        through."""
        self.current_attention()
        self.correction()
        out, _ = self.run_selector()
        self.assertNotIn("wakeAgent", out)


class TestOnlyTheUserSaysWhatTheyChose(SelectorCase):
    """`current_priorities.md` gates the top tier, so its evidence is narrow."""

    def test_corrections_are_surfaced_separately_from_obligations(self):
        self.correction()
        found = json.loads(self.run_selector()[0])
        self.assertTrue(found["user_corrections"])
        self.assertIn("user_corrections", found)
        self.assertIn("open_obligations", found)

    def test_an_agent_event_is_not_a_correction(self):
        """Only `correct.py` writes `actor='user'`; a rerank is the assistant
        talking to itself."""
        self.correction(actor="agent")
        found = json.loads(self.run_selector()[0])
        self.assertEqual(found["user_corrections"], [])

    def test_the_correction_names_what_it_was_about(self):
        self.correction()
        entry = json.loads(self.run_selector()[0])["user_corrections"][0]
        self.assertEqual(entry["action"], "priority_override")
        self.assertEqual(entry["title"], "the cutover")
        self.assertEqual(entry["to"], "high")


class TestTheScopeIsStatedWhereItIsChecked(unittest.TestCase):
    """The schema declares more page types than anything writes.

    That is fine and is now said out loud, in the schema's writer table and in
    the skill. What is not fine is the two drifting apart, or a page type
    gaining a writer without the table noticing — which is how the schema came
    to promise that ingest checked `event_triggers` against every incoming
    message when no shipped job has ever read that page.
    """

    RECIPE = HERE.parents[1]

    def schema(self):
        return (self.RECIPE / "profile" / "schema.md").read_text(
            encoding="utf-8")

    def skill(self):
        return (self.RECIPE / "profile" / "skills" / "memory-writing"
                / "SKILL.md").read_text(encoding="utf-8")

    def test_the_schema_names_a_writer_for_every_page_type_it_declares(self):
        schema = self.schema()
        declared = re.findall(r"^### \w+ \(`([a-z_]+)/`\)", schema, re.M)
        self.assertTrue(declared, "no page types found in the schema")
        table = schema.split("## What writes these pages", 1)[1].split(
            "## Page types", 1)[0]
        for page_type in declared:
            self.assertIn(f"`{page_type}/", table,
                          f"{page_type}/ is declared but the writer table "
                          "does not say what writes it")

    def test_the_unwritten_types_are_named_as_unwritten(self):
        """A reader must not have to infer an absence from silence."""
        table = self.schema().split("## What writes these pages", 1)[1].split(
            "## Page types", 1)[0]
        for page_type in ("projects", "patterns", "concepts", "goals"):
            row = [line for line in table.splitlines()
                   if f"`{page_type}/`" in line]
            self.assertTrue(row, page_type)
            self.assertIn("nothing yet", row[0], page_type)

    def test_the_skill_says_it_does_not_write_the_unwritten_types(self):
        """Mentioning the word somewhere is not saying it is out of scope.

        The first version of this asserted the word appeared anywhere in the
        file, which it does — in the rationale, in an example. Deleting the
        scope statement left it green.
        """
        skill = self.skill()
        refusals = skill.split("## What NOT to write", 1)
        self.assertEqual(len(refusals), 2, "no refusal section in the skill")
        refusals = refusals[1]
        for page_type in ("projects", "patterns", "concepts"):
            self.assertIn(f"`{page_type}/", refusals,
                          f"the skill does not refuse {page_type}/ where a "
                          "reader looks for what it will not write")

    def test_the_schema_no_longer_promises_ingest_reads_event_triggers(self):
        """A behavioural claim about a page nothing reads."""
        schema = self.schema()
        self.assertNotIn(
            "Ingest\n  checks active triggers", schema)
        self.assertNotIn("checks active triggers against every incoming",
                         schema.replace("\n  ", " ").replace("\n", " ")
                         .split("An earlier")[0])


class TestTheWindow(SelectorCase):
    def test_the_default_window_is_the_one_the_docs_state(self):
        self.assertEqual(select_memory.WINDOW_DAYS, 30)

    def test_a_window_that_selects_nobody_is_refused(self):
        for bad in ("0", "-1", "abc", str(select_memory.MAX_WINDOW_DAYS + 1)):
            os.environ["MEMORY_WINDOW_DAYS"] = bad
            with self.assertRaises(SystemExit):
                select_memory.bounded_days(
                    "MEMORY_WINDOW_DAYS", select_memory.WINDOW_DAYS)

    def test_an_unset_window_falls_back_to_the_default(self):
        os.environ.pop("MEMORY_WINDOW_DAYS", None)
        self.assertEqual(
            select_memory.bounded_days("MEMORY_WINDOW_DAYS", 30), 30)

    def test_somebody_outside_the_window_is_not_offered(self):
        self.add("Old Friend", days_ago=90)
        self.add("Old Friend", days_ago=95, body="b2")
        self.assertEqual(self.report()["people"], [])


class TestTheAttentionPagesAreChecked(SelectorCase):
    """`current_priorities.md` is what the ranking gates its top tier on, so
    its absence has to be reported as loudly as its staleness."""

    def test_a_missing_priorities_page_is_reported(self):
        states = {a["page"]: a["state"] for a in select_memory.stale_attention()}
        self.assertEqual(states.get("current_priorities"), "missing")

    def test_a_fresh_page_is_not_reported(self):
        today = datetime.now(timezone.utc).date().isoformat()
        self.page("current_priorities", updated=today, decay="daily",
                  kind="attention")
        self.page("active_threads", updated=today, decay="weekly",
                  kind="attention")
        self.assertEqual(select_memory.stale_attention(), [])

    def test_a_page_past_its_decay_window_is_reported(self):
        old = (datetime.now(timezone.utc).date() - timedelta(days=9)).isoformat()
        today = datetime.now(timezone.utc).date().isoformat()
        self.page("current_priorities", updated=old, decay="daily",
                  kind="attention")
        self.page("active_threads", updated=today, decay="weekly",
                  kind="attention")
        found = {a["page"]: a["state"] for a in select_memory.stale_attention()}
        self.assertEqual(found.get("current_priorities"), "stale")

    def test_decay_governs_the_window_rather_than_a_fixed_number_of_days(self):
        """Eight days is stale for `daily` and current for `monthly`."""
        eight = (datetime.now(timezone.utc).date()
                 - timedelta(days=8)).isoformat()
        today = datetime.now(timezone.utc).date().isoformat()
        self.page("active_threads", updated=today, decay="weekly",
                  kind="attention")
        self.page("current_priorities", updated=eight, decay="monthly",
                  kind="attention")
        self.assertEqual(select_memory.stale_attention(), [])

    def test_an_impossible_date_is_a_finding_not_a_crash(self):
        """`2026-99-99` has the shape and is not a date. Raising aborted the
        whole pass — including the report that would have named the page. This
        job runs before the repair job, so the crash also delayed the fix."""
        self.page("current_priorities", updated="2026-99-99", decay="daily",
                  kind="attention")
        self.page("active_threads", updated=datetime.now(timezone.utc)
                  .date().isoformat(), decay="weekly", kind="attention")
        found = {a["page"]: a["state"] for a in select_memory.stale_attention()}
        self.assertEqual(found.get("current_priorities"), "unreadable date")

    def test_the_selector_still_finishes_with_an_impossible_date(self):
        self.page("current_priorities", updated="2026-13-40", decay="daily",
                  kind="attention")
        out, _ = self.run_selector()
        self.assertIn("unreadable date", out)

    def test_a_page_with_no_updated_field_cannot_be_trusted_as_current(self):
        self.page("current_priorities", decay="daily", kind="attention")
        self.page("active_threads", updated=datetime.now(timezone.utc)
                  .date().isoformat(), decay="weekly", kind="attention")
        found = {a["page"]: a["state"] for a in select_memory.stale_attention()}
        self.assertEqual(found.get("current_priorities"), "no updated field")


class TestTheGate(SelectorCase):
    """A quiet day must cost no tokens, and a missing priorities page must
    not be a quiet day."""

    def test_nothing_to_write_gates_the_agent_off(self):
        today = datetime.now(timezone.utc).date().isoformat()
        self.page("current_priorities", updated=today, decay="daily",
                  kind="attention")
        self.page("active_threads", updated=today, decay="weekly",
                  kind="attention")
        _, last = self.run_selector()
        self.assertEqual(json.loads(last), {"wakeAgent": False})

    def test_a_missing_priorities_page_is_work_even_with_no_new_people(self):
        out, last = self.run_selector()
        self.assertNotIn("wakeAgent", out)
        self.assertEqual(last.strip(), "}")

    def test_somebody_new_is_work(self):
        today = datetime.now(timezone.utc).date().isoformat()
        self.page("current_priorities", updated=today, decay="daily",
                  kind="attention")
        self.page("active_threads", updated=today, decay="weekly",
                  kind="attention")
        self.add("Dana Okoro", days_ago=1)
        self.add("Dana Okoro", days_ago=2, body="b2")
        out, _ = self.run_selector()
        self.assertNotIn("wakeAgent", out)
        self.assertIn("Dana Okoro", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
