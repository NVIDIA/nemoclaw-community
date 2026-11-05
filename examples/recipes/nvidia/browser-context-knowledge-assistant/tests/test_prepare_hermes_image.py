# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Regression checks for the supported managed inference-route layouts."""

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('prepare_image', ROOT / 'scripts/prepare-hermes-image.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ImagePreparationTests(unittest.TestCase):
    def fixture(self, guarded):
        route = module.VISION_ROUTE_BEFORE
        if guarded:
            route = '  if (settings.model !== null)\n' + '\n'.join('  ' + line for line in route.splitlines())
        return '\n'.join((module.MANAGED_POLICY_BEFORE, module.ROUTING_KEYS_BEFORE, route))

    def test_both_supported_layouts_are_idempotent(self):
        for guarded in (False, True):
            with self.subTest(guarded=guarded):
                original = self.fixture(guarded)
                prepared = module.update_managed_policy(original)
                self.assertIn('supports_vision = true;', prepared)
                self.assertEqual(module.update_managed_policy(prepared), prepared)
                self.assertEqual(prepared.count('supports_vision = true;'), 1)
                if guarded:
                    self.assertIn('if (settings.model !== null)\n    applyHermesManagedRoute', prepared)

    def test_changed_or_ambiguous_contract_is_rejected(self):
        original = self.fixture(False)
        for text in (original.replace('model: settings.model', 'model: otherModel'),
                     original + '\n' + module.VISION_ROUTE_BEFORE):
            with self.subTest(text=text):
                with self.assertRaises(SystemExit):
                    module.update_managed_policy(text)


if __name__ == '__main__':
    unittest.main()
