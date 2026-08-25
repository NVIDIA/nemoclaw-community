# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Normalization against recorded-shape payloads. No credentials, no network."""

import sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from normalize import graph_message_to_item, slack_message_to_item  # noqa: E402

ME = "avery@example.com"


def graph(**over):
    msg = {
        "id": "AAMkAGI2", "receivedDateTime": "2026-08-18T09:00:00Z",
        "subject": "Q3 capacity", "from": {"emailAddress": {"name": "Dana Okoro",
                                                            "address": "dana@example.com"}},
        "toRecipients": [{"emailAddress": {"address": ME}}],
        "ccRecipients": [], "body": {"contentType": "text", "content": "Numbers by Thu?"},
        "parentFolderId": "inbox", "conversationId": "CONV1",
        "webLink": "https://outlook.example.com/m/AAMkAGI2", "isRead": False,
    }
    msg.update(over)
    return msg


class TestGraph(unittest.TestCase):

    def test_maps_every_column(self):
        it = graph_message_to_item(graph(), ME)
        self.assertEqual(it["source_id"], "AAMkAGI2")
        self.assertEqual(it["scope"], "inbox")
        self.assertEqual(it["thread_ref"], "CONV1")
        self.assertEqual(it["event_at"], "2026-08-18T09:00:00Z")
        self.assertEqual(it["sender"], "Dana Okoro")
        self.assertEqual(it["body"], "Numbers by Thu?")
        self.assertEqual(it["unread"], 1)

    def test_to_recipient_is_direct_cc_only_is_broadcast(self):
        self.assertEqual(graph_message_to_item(graph(), ME)["addressing"], "direct")
        cc_only = graph(toRecipients=[{"emailAddress": {"address": "someone@example.com"}}],
                        ccRecipients=[{"emailAddress": {"address": ME}}])
        self.assertEqual(graph_message_to_item(cc_only, ME)["addressing"], "broadcast")

    def test_distribution_list_delivery_names_nobody_and_counts_as_broadcast(self):
        dl = graph(toRecipients=[{"emailAddress": {"address": "team@example.com"}}])
        self.assertEqual(graph_message_to_item(dl, ME)["addressing"], "broadcast")

    def test_read_mail_reports_unread_zero(self):
        self.assertEqual(graph_message_to_item(graph(isRead=True), ME)["unread"], 0)

    def test_sender_falls_back_to_the_address_when_no_display_name(self):
        anon = graph(**{"from": {"emailAddress": {"address": "noreply@example.com"}}})
        self.assertEqual(graph_message_to_item(anon, ME)["sender"], "noreply@example.com")


class TestSlack(unittest.TestCase):

    def test_source_id_is_channel_qualified_because_ts_is_not_unique(self):
        a = slack_message_to_item({"ts": "1787059200.000100", "user": "U1", "text": "hi"},
                                  {"id": "C111", "type": "channel"}, "UME")
        b = slack_message_to_item({"ts": "1787059200.000100", "user": "U1", "text": "hi"},
                                  {"id": "C222", "type": "channel"}, "UME")
        self.assertNotEqual(a["source_id"], b["source_id"])
        self.assertEqual(a["source_id"], "C111:1787059200.000100")

    def test_epoch_becomes_iso_so_both_sources_sort_together(self):
        it = slack_message_to_item({"ts": "1787059200.000100", "user": "U1", "text": ""},
                                   {"id": "C1", "type": "channel"}, "UME")
        self.assertEqual(it["event_at"], "2026-08-18T13:20:00Z")

    def test_dm_is_direct_mention_is_mentioned_channel_is_broadcast(self):
        dm = slack_message_to_item({"ts": "1.0", "user": "U1", "text": "ping"},
                                   {"id": "D1", "type": "im"}, "UME")
        self.assertEqual(dm["addressing"], "direct")
        at = slack_message_to_item({"ts": "1.0", "user": "U1", "text": "<@UME> can you look"},
                                   {"id": "C1", "type": "channel"}, "UME")
        self.assertEqual(at["addressing"], "mentioned")
        bc = slack_message_to_item({"ts": "1.0", "user": "U1", "text": "shipping today"},
                                   {"id": "C1", "type": "channel"}, "UME")
        self.assertEqual(bc["addressing"], "broadcast")

    def test_a_mention_of_someone_else_is_not_a_mention_of_you(self):
        it = slack_message_to_item({"ts": "1.0", "user": "U1", "text": "<@UOTHER> please review"},
                                   {"id": "C1", "type": "channel"}, "UME")
        self.assertEqual(it["addressing"], "broadcast")

    def test_thread_parent_and_reply_share_a_thread_ref(self):
        parent = slack_message_to_item({"ts": "100.1", "user": "U1", "text": "q"},
                                       {"id": "C1", "type": "channel"}, "UME")
        reply = slack_message_to_item({"ts": "100.9", "user": "U2", "text": "a",
                                       "thread_ts": "100.1"},
                                      {"id": "C1", "type": "channel"}, "UME")
        self.assertEqual(parent["thread_ref"], reply["thread_ref"])

    def test_read_state_is_absent_for_slack(self):
        it = slack_message_to_item({"ts": "1.0", "user": "U1", "text": ""},
                                   {"id": "C1", "type": "im"}, "UME")
        self.assertIsNone(it["unread"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
