# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Tests for the path that makes a candidate's own changes measurable.

The optimizer copies `agent_source/` into `agents/agent-N/` per candidate and
the wrapper builds the agent from the copy's own `agent.yaml`. These tests pin
the three properties that has to hold: the config comes from the copy, the
example root is still found from inside the copy, and the guardrail metric does
not.
"""

from __future__ import annotations

import shutil
import sys
import unittest
from pathlib import Path

EXAMPLE = Path(__file__).resolve().parent.parent
AGENT_SOURCE = EXAMPLE / "harness" / "agent_source"
sys.path.insert(0, str(AGENT_SOURCE))

import harbor_wrapper  # noqa: E402


class CandidateLocalInvocation(unittest.TestCase):
    """The agent is built from the candidate's config, not a shared one."""

    def test_agent_config_is_the_one_beside_the_wrapper(self) -> None:
        self.assertEqual(harbor_wrapper.AGENT_CONFIG.parent, harbor_wrapper.AGENT_DIR)
        self.assertEqual(harbor_wrapper.AGENT_CONFIG.name, "agent.yaml")
        self.assertTrue(harbor_wrapper.AGENT_CONFIG.is_file())

    def test_agent_name_is_read_from_that_config(self) -> None:
        declared = [
            line.split(":", 1)[1].strip()
            for line in harbor_wrapper.AGENT_CONFIG.read_text().splitlines()
            if line.startswith("name:")
        ]
        self.assertEqual(harbor_wrapper.AGENT_NAME, declared[0])

    def test_no_fixed_deployment_remains(self) -> None:
        # A fixed deployment name would mean candidate edits never execute.
        source = (AGENT_SOURCE / "harbor_wrapper.py").read_text()
        self.assertNotIn("CAD_AGENT_DEPLOYMENT", source)
        self.assertNotIn("chat/completions", source)


class ExampleRootDiscovery(unittest.TestCase):
    """A candidate copy sits deeper in the tree; the scorer must still resolve."""

    def _root_from(self, wrapper_path: Path) -> Path:
        for candidate in wrapper_path.resolve().parents:
            if (candidate / "scorer" / "score.py").is_file():
                return candidate
        raise AssertionError(f"no example root above {wrapper_path}")

    def test_root_found_from_the_checkout(self) -> None:
        self.assertEqual(self._root_from(AGENT_SOURCE / "harbor_wrapper.py"), EXAMPLE)

    def test_root_found_from_a_copied_candidate_directory(self) -> None:
        # The layout the Experimentalist creates: experiment/eval-and-optimize/
        # agents/agent-N/. A fixed parents[N] offset lands inside the run output
        # here, where scorer/ and meshes/ do not exist, and every measurement is
        # silently discarded.
        candidate = (EXAMPLE / "harness" / "experiment" / "eval-and-optimize"
                     / "agents" / "agent-0")
        candidate.mkdir(parents=True, exist_ok=True)
        copied = candidate / "harbor_wrapper.py"
        try:
            shutil.copyfile(AGENT_SOURCE / "harbor_wrapper.py", copied)
            self.assertEqual(self._root_from(copied), EXAMPLE)
        finally:
            shutil.rmtree(EXAMPLE / "harness" / "experiment", ignore_errors=True)


class GuardrailIsOutsideTheCandidate(unittest.TestCase):
    """A candidate must not be able to rewrite the metric that selects it."""

    def test_metric_module_loads_from_the_example_root(self) -> None:
        loaded = Path(harbor_wrapper.TRIAL_METRIC.__file__).resolve()
        self.assertEqual(loaded, (EXAMPLE / "scorer" / "trial_metric.py").resolve())

    def test_metric_module_is_not_inside_agent_source(self) -> None:
        loaded = Path(harbor_wrapper.TRIAL_METRIC.__file__).resolve()
        self.assertNotIn(AGENT_SOURCE.resolve(), loaded.parents)

    def test_agent_source_ships_no_copy_of_the_metric(self) -> None:
        # If one were copied in, the loader would still prefer the example root,
        # but its presence would invite a candidate to edit the wrong file.
        self.assertFalse((AGENT_SOURCE / "trial_metric.py").exists())

    def test_wrapper_does_not_compute_the_guardrail_itself(self) -> None:
        source = (AGENT_SOURCE / "harbor_wrapper.py").read_text()
        self.assertNotIn("def _iou_span", source)
        self.assertIn("TRIAL_METRIC.iou_span", source)


class OnlyPromotableSurfacesAreMeasurable(unittest.TestCase):
    """A candidate that changes something unpromotable cannot produce a score.

    The change surface is the system prompt, subagents and
    `workspace/skills/`. The harness and the rest of `agent.yaml` are pinned:
    an edit there can still move the reward, and then the run has measured
    something there is no way to ship.
    """

    def _candidate(self, name: str = "agent-1") -> Path:
        path = (EXAMPLE / "harness" / "experiment" / "eval-and-optimize"
                / "agents" / name)
        path.mkdir(parents=True, exist_ok=True)
        for source in ("harbor_wrapper.py", "agent.yaml"):
            shutil.copyfile(AGENT_SOURCE / source, path / source)
        return path

    def tearDown(self) -> None:
        shutil.rmtree(EXAMPLE / "harness" / "experiment", ignore_errors=True)

    def _wrapper_differs(self, candidate: Path) -> bool:
        original = (AGENT_SOURCE / "harbor_wrapper.py").read_bytes()
        return (candidate / "harbor_wrapper.py").read_bytes() != original

    def _config_differs(self, candidate: Path) -> bool:
        pinned = harbor_wrapper._pinned_config
        return pinned(candidate / "agent.yaml") != pinned(AGENT_SOURCE / "agent.yaml")

    def test_the_checkout_itself_passes(self) -> None:
        harbor_wrapper._assert_promotable_change_surface()

    def test_an_untouched_candidate_copy_passes(self) -> None:
        candidate = self._candidate()
        self.assertFalse(self._wrapper_differs(candidate))
        self.assertFalse(self._config_differs(candidate))

    def test_a_harness_edit_is_rejected(self) -> None:
        candidate = self._candidate()
        wrapper = candidate / "harbor_wrapper.py"
        wrapper.write_bytes(wrapper.read_bytes() + b"\n# candidate edit\n")
        self.assertTrue(self._wrapper_differs(candidate))

    def test_a_model_or_sampling_change_is_rejected(self) -> None:
        candidate = self._candidate()
        config = candidate / "agent.yaml"
        config.write_text(config.read_text().replace(
            "    provider: nvidia", "    provider: nvidia\n    temperature: 0.2"))
        self.assertTrue(self._config_differs(candidate))

    def test_a_system_prompt_change_is_allowed(self) -> None:
        candidate = self._candidate()
        config = candidate / "agent.yaml"
        config.write_text(config.read_text().replace(
            "You are a CAD Agent", "You are a careful CAD Agent"))
        self.assertFalse(self._config_differs(candidate))

    def test_a_subagent_is_allowed(self) -> None:
        candidate = self._candidate()
        config = candidate / "agent.yaml"
        config.write_text(config.read_text().replace(
            "      deepagents: {}",
            "      deepagents:\n        subagents: [{name: checker}]"))
        self.assertFalse(self._config_differs(candidate))

    def test_ethos_scope_matches_what_is_enforced(self) -> None:
        ethos = (EXAMPLE / "agent" / "ETHOS.md").read_text()
        self.assertIn("Evaluation harness, including `harbor_wrapper.py`: no", ethos)
        self.assertIn("Model selection and sampling parameters: no", ethos)
        self.assertNotIn("with-approval", ethos)


class CandidateWorkspaceSkill(unittest.TestCase):
    """A skill dropped into the candidate's workspace is part of its config."""

    def test_agent_source_ships_a_workspace_for_skills(self) -> None:
        self.assertTrue((AGENT_SOURCE / "workspace" / "skills").is_dir())

    def test_config_points_the_backend_root_at_that_workspace(self) -> None:
        config = harbor_wrapper.AGENT_CONFIG.read_text()
        self.assertIn("workspace: ./workspace", config)

    def test_config_tells_the_agent_where_skills_live(self) -> None:
        # Without the pointer the skill is on disk but never read: skills.paths
        # does not reach the deployed system prompt.
        self.assertIn("/skills/", harbor_wrapper.AGENT_CONFIG.read_text())


if __name__ == "__main__":
    unittest.main()
