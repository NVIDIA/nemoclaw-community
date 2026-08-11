#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for build-workshop-policy.py: compose = live + exactly the additions."""

from __future__ import annotations

import copy
import importlib.util
import unittest
from pathlib import Path

SCRIPT = (Path(__file__).resolve().parents[1]
          / "skills/setup-workshop-nemoclaw-operator/scripts/build-workshop-policy.py")
spec = importlib.util.spec_from_file_location("bwp", SCRIPT)
bwp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bwp)

# Structurally faithful miniature of the recipe's stock policy.
STOCK = {
    "version": 1,
    "filesystem_policy": {
        "include_workdir": True,
        "read_only": ["/usr", "/etc"],
        "read_write": ["/sandbox", "/tmp"],
    },
    "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"},
    "network_policies": {
        "nvidia": {
            "name": "nvidia",
            "endpoints": [
                {"host": "integrate.api.nvidia.com", "port": 443, "protocol": "rest",
                 "enforcement": "enforce",
                 "rules": [{"allow": {"method": "POST", "path": "/v1/chat/completions"}}]},
                {"host": "inference-api.nvidia.com", "port": 443, "protocol": "rest",
                 "enforcement": "enforce",
                 "rules": [{"allow": {"method": "POST", "path": "/v1/chat/completions"}}]},
            ],
            "binaries": [{"path": "/usr/bin/python3"}],
        },
        "source_etl_api": {
            "name": "source_etl_api",
            "endpoints": [{"host": "host.openshell.internal", "port": 3100,
                           "protocol": "rest", "enforcement": "enforce",
                           "rules": [{"allow": {"method": "GET", "path": "/**"}}]}],
        },
    },
}


class ComposeTests(unittest.TestCase):
    def setUp(self):
        self.live = copy.deepcopy(STOCK)
        self.doc = bwp.compose(self.live)

    def test_input_untouched(self):
        self.assertEqual(self.live, STOCK)

    def test_all_workshop_blocks_added(self):
        added = set(self.doc["network_policies"]) - set(STOCK["network_policies"])
        self.assertEqual(added, set(bwp.WORKSHOP_BLOCKS))

    def test_ranking_rule_on_every_nvidia_endpoint(self):
        for ep in self.doc["network_policies"]["nvidia"]["endpoints"]:
            self.assertIn(bwp.RANKING_RULE, ep["rules"])

    def test_fs_grants_added(self):
        fs = self.doc["filesystem_policy"]
        self.assertIn(bwp.FS_READ_WRITE, fs["read_write"])
        self.assertIn(bwp.FS_READ_ONLY, fs["read_only"])

    def test_preexisting_blocks_untouched(self):
        self.assertEqual(self.doc["network_policies"]["source_etl_api"],
                         STOCK["network_policies"]["source_etl_api"])

    def test_self_verify_passes(self):
        self.assertEqual(bwp.verify(self.live, self.doc), [])

    def test_idempotent(self):
        again = bwp.compose(self.doc)
        self.assertEqual(again, self.doc)

    def test_verify_catches_removed_block(self):
        broken = copy.deepcopy(self.doc)
        del broken["network_policies"]["source_etl_api"]
        self.assertTrue(bwp.verify(self.live, broken))

    def test_verify_catches_mutated_block(self):
        broken = copy.deepcopy(self.doc)
        broken["network_policies"]["source_etl_api"]["endpoints"][0]["port"] = 9999
        self.assertTrue(bwp.verify(self.live, broken))

    def test_no_push_route_granted(self):
        gh = self.doc["network_policies"]["github_git_clone"]
        rules = [r["allow"]["path"] for ep in gh["endpoints"] for r in ep["rules"]]
        self.assertFalse(any("receive-pack" in p for p in rules))


if __name__ == "__main__":
    unittest.main()
