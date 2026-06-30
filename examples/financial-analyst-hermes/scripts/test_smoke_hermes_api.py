#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import unittest

MODULE_PATH = Path(__file__).with_name("smoke-hermes-api.py")
SPEC = importlib.util.spec_from_file_location("smoke_hermes_api", MODULE_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)
validate_assistant_message = MODULE.validate_assistant_message


class SmokeHermesApiTest(unittest.TestCase):
    def test_accepts_a_real_answer(self) -> None:
        answer = "Free cash flow yield compares free cash flow with market value."
        self.assertEqual(validate_assistant_message(answer), answer)

    def test_rejects_empty_and_upstream_error_messages(self) -> None:
        for message in (
            "",
            "(No assistant message returned.)",
            "API call failed after 3 retries: internal error: DEGRADED function cannot be invoked",
        ):
            with self.subTest(message=message):
                with self.assertRaises(RuntimeError):
                    validate_assistant_message(message)


if __name__ == "__main__":
    unittest.main()
