#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""One person, however many places they write from.

The tests that matter here are the ones that would still matter with a fourth
and fifth connector, because that is what this module exists to survive.
"""

from __future__ import annotations

import io
import contextlib
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

import _db  # noqa: E402
import identity  # noqa: E402
import link_identity  # noqa: E402


SLACK = identity.Identity("slack", "U01DANA")
MAIL = identity.Identity("email", "dana@example.com")
# A key with colons in it, because Teams ids have them and an identity that
# round-trips through text must survive that.
TEAMS = identity.Identity("teams", "29:1a2b:3c")
GITHUB = identity.Identity("github", "dokoro")


class StoreCase(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        os.environ["HERMES_HOME"] = str(self.home)
        # Through `ensure_store`, not by writing the schema to a path spelled
        # out here. The store's location is the store's business, and a test
        # that guesses it tests a database nothing else opens.
        self.db = _db.ensure_store()
        with sqlite3.connect(self.db) as conn:
            conn.execute("INSERT OR IGNORE INTO sources(name)"
                         " VALUES ('teams'),('github')")

    def tearDown(self):
        shutil.rmtree(self.home, ignore_errors=True)

    def conn(self):
        conn = sqlite3.connect(self.db)
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def link(self, a, b, status="confirmed"):
        with contextlib.closing(self.conn()) as conn:
            identity.record(conn, a, b, status)
            conn.commit()

    def item(self, who, sender="Dana Okoro", handle=None, at="2026-08-20"):
        with contextlib.closing(self.conn()) as conn:
            conn.execute(
                "INSERT INTO items(source_id, source, scope, event_at, sender,"
                " sender_key, sender_handle, body, addressing, state) VALUES"
                " (?,?,?,?,?,?,?,?, 'direct','pending')",
                (f"{who}:{at}", who.source, "c", at + "T00:00:00Z", sender,
                 who.key, handle, "b"))
            conn.commit()


class TestAnIdentityIsASourceAndAKey(unittest.TestCase):
    def test_a_key_containing_colons_round_trips(self):
        """Teams ids look like `29:1a2b`. Splitting on the last colon, or on
        every colon, truncates every such account to something matching
        nobody — and does it silently."""
        self.assertEqual(identity.parse(str(TEAMS)), TEAMS)
        self.assertEqual(identity.parse("teams:29:1a2b:3c").key, "29:1a2b:3c")

    def test_text_without_a_source_is_refused(self):
        for bad in ("U01DANA", ":key", "Slack:U1", "sla ck:U1", "slack:"):
            with self.subTest(text=bad):
                with self.assertRaises(ValueError):
                    identity.parse(bad)

    def test_the_same_key_from_two_sources_is_two_people(self):
        """Nothing stops two systems minting the same string. Treating a bare
        key as an identity would merge their owners, silently."""
        self.assertNotEqual(identity.Identity("slack", "dana"),
                            identity.Identity("github", "dana"))


class TestAnswersCompose(StoreCase):
    """The property that makes this generalize past two connectors."""

    def test_confirming_two_pairs_joins_three_identities(self):
        self.link(SLACK, MAIL)
        self.link(MAIL, TEAMS)
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL, TEAMS])
        self.assertEqual(persons.group(SLACK), sorted([SLACK, MAIL, TEAMS]))
        self.assertEqual(persons.of(SLACK), persons.of(TEAMS),
                         "A~B and B~C did not make A~C")

    def test_a_fourth_identity_is_one_more_pair(self):
        """Not a new shape, and not a re-answer of what was already settled."""
        self.link(SLACK, MAIL)
        self.link(MAIL, TEAMS)
        self.link(TEAMS, GITHUB)
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL, TEAMS, GITHUB])
        self.assertEqual(len(persons.group(GITHUB)), 4)

    def test_the_representative_does_not_depend_on_link_order(self):
        """It decides the page name. One that changes between runs is a page
        lost, and link order is not stable — it is whatever the table
        returns."""
        forward = identity.Persons([(SLACK, MAIL), (MAIL, TEAMS)])
        backward = identity.Persons([(TEAMS, MAIL), (MAIL, SLACK)])
        self.assertEqual(forward.of(SLACK), backward.of(SLACK))
        self.assertEqual(forward.of(TEAMS), backward.of(TEAMS))

    def test_an_unlinked_identity_is_a_person_on_their_own(self):
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [GITHUB])
        self.assertEqual(persons.group(GITHUB), [GITHUB])

    def test_a_rejected_pair_stays_two_people(self):
        """The direction that matters most. A rejection read as an answer of
        any kind — or a store that groups on every row rather than on the
        confirmed ones — merges two people the user said were different, and
        the merge is the unrecoverable direction."""
        self.link(SLACK, MAIL, "rejected")
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL])
        self.assertNotEqual(persons.of(SLACK), persons.of(MAIL))
        self.assertEqual(persons.group(SLACK), [SLACK])

    def test_a_pair_is_stored_once_whichever_way_round_it_is_given(self):
        """Two rows for one question could disagree with each other."""
        self.link(MAIL, SLACK)
        self.link(SLACK, MAIL, "rejected")
        with contextlib.closing(self.conn()) as conn:
            rows = conn.execute("SELECT status FROM identity_links").fetchall()
        self.assertEqual(rows, [("rejected",)])


class TestOnlyTheUserJoinsIdentities(StoreCase):
    def test_a_shared_handle_is_proposed_and_not_applied(self):
        self.item(SLACK, handle="dana.okoro")
        self.item(MAIL, handle="dana.okoro")
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL])
            found = identity.candidates(
                [(SLACK, "Dana Okoro", "dana.okoro"),
                 (MAIL, "Dana Okoro", "dana.okoro")],
                identity.decisions(conn), persons)
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["reason"], "shared handle")
        self.assertNotEqual(persons.of(SLACK), persons.of(MAIL),
                            "a matching handle joined two identities on its own")

    def test_one_question_per_group_not_one_per_signal(self):
        """Name and handle both matching is one question, not two."""
        with contextlib.closing(self.conn()) as conn:
            found = identity.candidates(
                [(SLACK, "Dana Okoro", "dana"), (MAIL, "Dana Okoro", "dana")],
                {}, identity.Persons())
        self.assertEqual([f["identities"] for f in found],
                         [[str(MAIL), str(SLACK)]])

    def test_two_identities_in_one_source_are_not_proposed(self):
        """A source will not let two accounts share a handle, so a match
        within one is not a coincidence worth asking about."""
        other = identity.Identity("slack", "U02SAM")
        with contextlib.closing(self.conn()) as conn:
            found = identity.candidates(
                [(SLACK, "Dana Okoro", "dana"), (other, "Dana Okoro", "dana")],
                {}, identity.Persons())
        self.assertEqual(found, [])

    def test_an_answered_group_is_not_proposed_again(self):
        """A candidate re-asked nightly is how an idle job wakes the agent
        forever. Rejection has to be as durable as confirmation."""
        self.link(SLACK, MAIL, "rejected")
        with contextlib.closing(self.conn()) as conn:
            found = identity.candidates(
                [(SLACK, "Dana Okoro", "dana"), (MAIL, "Dana Okoro", "dana")],
                identity.decisions(conn), identity.resolve(conn, [SLACK, MAIL]))
        self.assertEqual(found, [])

    def test_a_group_already_joined_is_not_proposed(self):
        self.link(SLACK, MAIL)
        with contextlib.closing(self.conn()) as conn:
            found = identity.candidates(
                [(SLACK, "Dana Okoro", "dana"), (MAIL, "Dana Okoro", "dana")],
                identity.decisions(conn), identity.resolve(conn, [SLACK, MAIL]))
        self.assertEqual(found, [])

    def test_a_partly_answered_group_is_still_proposed(self):
        """Three identities, one pair answered: the other two are still open,
        and dropping the group would lose them."""
        with contextlib.closing(self.conn()) as conn:
            identity.record(conn, SLACK, MAIL, "rejected")
            conn.commit()
            found = identity.candidates(
                [(SLACK, "Dana Okoro", "dana"), (MAIL, "Dana Okoro", "dana"),
                 (TEAMS, "Dana Okoro", "dana")],
                identity.decisions(conn), identity.resolve(conn))
        self.assertEqual(len(found), 1)
        self.assertEqual(len(found[0]["identities"]), 3)


class TestAnswersThatNoLongerAgree(StoreCase):
    def test_transitivity_overruling_a_rejection_is_reported(self):
        self.link(SLACK, MAIL, "rejected")
        self.link(SLACK, TEAMS)
        self.link(TEAMS, MAIL)
        with contextlib.closing(self.conn()) as conn:
            conflicts = identity.contradictions(conn)
        self.assertEqual(len(conflicts), 1)
        self.assertIn(str(SLACK), conflicts[0]["rejected"])

    def test_the_confirmations_are_kept_rather_than_dropped(self):
        """Dropping them to honour the rejection would split a person whose
        other links the user did confirm — a second wrong answer, silently."""
        self.link(SLACK, MAIL, "rejected")
        self.link(SLACK, TEAMS)
        self.link(TEAMS, MAIL)
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL, TEAMS])
        self.assertEqual(len(persons.group(SLACK)), 3)

    def test_a_plain_rejection_is_not_a_conflict(self):
        self.link(SLACK, MAIL, "rejected")
        with contextlib.closing(self.conn()) as conn:
            self.assertEqual(identity.contradictions(conn), [])


class TestTheUserFacingCommand(StoreCase):
    def run_cli(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = link_identity.main(list(argv))
        return code, buffer.getvalue()

    def test_answering_about_three_records_every_pair(self):
        self.item(SLACK)
        self.item(MAIL)
        self.item(TEAMS)
        code, out = self.run_cli("same", str(SLACK), str(MAIL), str(TEAMS))
        self.assertEqual(code, 0)
        self.assertIn('"pairs": 3', out)
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL, TEAMS])
        self.assertEqual(len(persons.group(SLACK)), 3)

    def test_a_mistyped_source_is_refused_with_the_ones_that_exist(self):
        """The foreign key already refuses it and says `FOREIGN KEY
        constraint failed`, which tells the user nothing to act on."""
        code, _ = self.run_cli("same", "slak:U01DANA", str(MAIL))
        self.assertEqual(code, 2)
        with contextlib.closing(self.conn()) as conn:
            self.assertEqual(identity.decisions(conn), {})

    def test_an_identity_with_no_messages_yet_is_named_not_refused(self):
        self.item(SLACK)
        code, out = self.run_cli("same", str(SLACK), str(GITHUB))
        self.assertEqual(code, 0)
        self.assertIn(str(GITHUB), out)

    def test_a_group_cannot_be_answered_as_different(self):
        """The negative does not distribute.

        "These three are not one person" rules out the group and says nothing
        about which member is the odd one out — A and B may be the same
        colleague with C a stranger. Recording all three pairs as rejected
        buries the A~B link and stops it ever being proposed again, on the
        strength of an answer nobody gave.
        """
        self.item(SLACK)
        self.item(MAIL)
        self.item(TEAMS)
        code, _ = self.run_cli("different", str(SLACK), str(MAIL), str(TEAMS))
        self.assertEqual(code, 2)
        with contextlib.closing(self.conn()) as conn:
            self.assertEqual(identity.decisions(conn), {},
                             "a group rejection was recorded pairwise")

    def test_the_pair_the_user_did_deny_is_still_recorded(self):
        """Refusing the group must not refuse the answer they can give."""
        self.item(SLACK)
        self.item(MAIL)
        code, _ = self.run_cli("different", str(SLACK), str(MAIL))
        self.assertEqual(code, 0)
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL])
        self.assertNotEqual(persons.of(SLACK), persons.of(MAIL))

    def test_a_group_can_still_be_answered_as_the_same_person(self):
        """`same` distributes where `different` does not: one person is a
        claim about every pair, and each of them follows."""
        for who in (SLACK, MAIL, TEAMS):
            self.item(who)
        code, _ = self.run_cli("same", str(SLACK), str(MAIL), str(TEAMS))
        self.assertEqual(code, 0)
        with contextlib.closing(self.conn()) as conn:
            self.assertEqual(len(identity.decisions(conn)), 3)

    def test_naming_one_identity_is_refused(self):
        code, _ = self.run_cli("same", str(SLACK))
        self.assertEqual(code, 2)

    def test_an_answer_can_be_changed(self):
        """A stored answer that cannot be corrected is worse than none: the
        candidate never comes back to be asked again."""
        self.item(SLACK)
        self.item(MAIL)
        self.run_cli("same", str(SLACK), str(MAIL))
        self.run_cli("different", str(SLACK), str(MAIL))
        with contextlib.closing(self.conn()) as conn:
            persons = identity.resolve(conn, [SLACK, MAIL])
        self.assertNotEqual(persons.of(SLACK), persons.of(MAIL))


if __name__ == "__main__":
    unittest.main()
