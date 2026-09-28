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

import contextlib
import importlib.util
import io
import marshal
import os
import shutil
import subprocess
import sys
import tempfile
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
    """An external check rejects candidates that changed the unpromotable.

    The wrapper checks this too, but it cannot enforce it: Harbor resolves the
    entry point inside the agent directory, so the file carrying the check is
    the file a candidate may rewrite. These tests drive
    `scorer/verify_candidates.py`, which is never copied into a candidate, and
    the decisive case is a candidate that deletes the wrapper's own guard.
    """

    def setUp(self) -> None:
        sys.path.insert(0, str(EXAMPLE / "scorer"))
        import verify_candidates

        self.verify = verify_candidates
        self.experiment = EXAMPLE / "harness" / "experiment"
        self.agents = self.experiment / "eval-and-optimize" / "agents"

    def tearDown(self) -> None:
        shutil.rmtree(self.experiment, ignore_errors=True)

    def _candidate(self, name: str = "agent-1") -> Path:
        path = self.agents / name
        path.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(path, ignore_errors=True)
        shutil.copytree(AGENT_SOURCE, path,
                        ignore=shutil.ignore_patterns("__pycache__", "artifacts", "traces"))
        return path

    def test_an_untouched_candidate_passes(self) -> None:
        self.assertEqual(self.verify.violations(self._candidate()), [])

    def test_a_candidate_that_deletes_the_guard_is_rejected(self) -> None:
        # The case the in-wrapper check cannot catch: removing the check is
        # part of the edit, so nothing inside the candidate is left to object.
        candidate = self._candidate()
        wrapper = candidate / "harbor_wrapper.py"
        source = wrapper.read_text()
        start = source.index("def _assert_promotable_change_surface()")
        end = source.index("_assert_promotable_change_surface()\n", start) + len(
            "_assert_promotable_change_surface()\n")
        wrapper.write_text(source[:start] + source[end:])
        self.assertNotIn("def _assert_promotable_change_surface", wrapper.read_text())
        self.assertIn("harbor_wrapper.py differs from the original",
                      self.verify.violations(candidate))

    def test_a_changed_pyproject_is_rejected(self) -> None:
        # Not the wrapper, but it decides what the trial installs.
        candidate = self._candidate()
        pyproject = candidate / "pyproject.toml"
        pyproject.write_text(pyproject.read_text() + '\n# candidate edit\n')
        self.assertIn("pyproject.toml differs from the original",
                      self.verify.violations(candidate))

    def test_an_unexpected_module_is_rejected(self) -> None:
        # A new module is one shadowed import away from running host-side.
        candidate = self._candidate()
        (candidate / "helper.py").write_text("print('hello')\n")
        self.assertTrue(any("helper.py is not in the original" in v
                            for v in self.verify.violations(candidate)))

    def test_a_deleted_file_is_rejected(self) -> None:
        candidate = self._candidate()
        (candidate / "pyproject.toml").unlink()
        self.assertTrue(any("pyproject.toml was deleted" in v
                            for v in self.verify.violations(candidate)))

    def test_a_symlink_is_rejected(self) -> None:
        candidate = self._candidate()
        (candidate / "escape.py").symlink_to("/etc/hosts")
        self.assertTrue(any("escape.py is a symlink" in v
                            for v in self.verify.violations(candidate)))

    def test_a_new_skill_is_allowed(self) -> None:
        candidate = self._candidate()
        skill = candidate / "workspace" / "skills" / "new-policy"
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text("---\nname: new-policy\ndescription: d\n---\n")
        self.assertEqual(self.verify.violations(candidate), [])

    def test_runtime_output_is_not_a_violation(self) -> None:
        # The agent and the optimizer both write inside the candidate.
        candidate = self._candidate()
        (candidate / "artifacts").mkdir(exist_ok=True)
        (candidate / "artifacts" / "out.FCStd").write_bytes(b"\x00")
        self.assertEqual(self.verify.violations(candidate), [])

    def test_an_ignored_root_replaced_by_a_symlink_is_rejected(self) -> None:
        # The bypass: skipping on directory name before testing for a symlink
        # let a candidate point artifacts/ or traces/ anywhere on the host and
        # have the whole subtree ignored.
        for name in ("artifacts", "traces", "__pycache__", ".fabric"):
            with self.subTest(root=name):
                candidate = self._candidate()
                target = candidate / name
                shutil.rmtree(target, ignore_errors=True)
                target.unlink(missing_ok=True)
                target.symlink_to("/etc")
                self.assertIn(f"{name} is a symlink; candidates may not link outside the tree",
                              self.verify.violations(candidate))

    def test_descendants_of_a_real_ignored_root_are_out_of_scope(self) -> None:
        # Pins the boundary rather than asserting a rejection. Once the root
        # itself is known to be a real directory, its contents are runtime
        # output: nothing under it is imported, executed or promoted, so a
        # symlink there cannot reach host code the way a symlinked root could.
        # __pycache__ is deliberately not such a root; see CachedBytecode.
        candidate = self._candidate()
        (candidate / "traces").mkdir(exist_ok=True)
        (candidate / "traces" / "escape").symlink_to("/etc")
        self.assertEqual(self.verify.violations(candidate), [])

    def test_real_ignored_directories_stay_ignored(self) -> None:
        candidate = self._candidate()
        for name in ("artifacts", "traces", ".fabric"):
            d = candidate / name
            d.mkdir(exist_ok=True)
            (d / "generated.bin").write_bytes(b"\x00")
        self.assertEqual(self.verify.violations(candidate), [])

    def test_the_optimizer_architecture_doc_is_not_a_violation(self) -> None:
        # The optimizer writes architecture.md into every candidate after the
        # change is final. Rejecting it would fail every trial, baseline
        # included, so this is the regression that keeps the loop runnable.
        candidate = self._candidate()
        (candidate / "architecture.md").write_text("# Agent\n\nflowchart\n")
        self.assertEqual(self.verify.violations(candidate), [])

    def test_a_model_or_sampling_change_is_rejected(self) -> None:
        candidate = self._candidate()
        config = candidate / "agent.yaml"
        config.write_text(config.read_text().replace(
            "    provider: nvidia", "    provider: nvidia\n    temperature: 0.2"))
        self.assertIn("agent.yaml changed a pinned block",
                      self.verify.violations(candidate))

    def test_a_system_prompt_change_is_allowed(self) -> None:
        candidate = self._candidate()
        config = candidate / "agent.yaml"
        config.write_text(config.read_text().replace(
            "You are a CAD Agent", "You are a careful CAD Agent"))
        self.assertEqual(self.verify.violations(candidate), [])

    def test_a_subagent_is_allowed(self) -> None:
        candidate = self._candidate()
        config = candidate / "agent.yaml"
        config.write_text(config.read_text().replace(
            "      deepagents: {}",
            "      deepagents:\n        subagents: [{name: checker}]"))
        self.assertEqual(self.verify.violations(candidate), [])

    def test_main_exits_nonzero_when_any_candidate_is_rejected(self) -> None:
        self._candidate("agent-1")
        bad = self._candidate("agent-2")
        (bad / "harbor_wrapper.py").write_text("# replaced wholesale\n")
        argv = sys.argv
        sys.argv = ["verify_candidates", str(self.experiment)]
        sink = io.StringIO()
        try:
            # main() reports to stdout and stderr; swallow it so the rejection
            # it is meant to produce does not read as a test-run failure.
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                self.assertEqual(self.verify.main(), 1)
        finally:
            sys.argv = argv
        self.assertIn("REJECTED agent-2", sink.getvalue())

    def test_the_verifier_is_not_inside_the_candidate_source(self) -> None:
        self.assertFalse((AGENT_SOURCE / "verify_candidates.py").exists())
        self.assertTrue((EXAMPLE / "scorer" / "verify_candidates.py").is_file())

    def test_ethos_scope_matches_what_is_enforced(self) -> None:
        ethos = (EXAMPLE / "agent" / "ETHOS.md").read_text()
        self.assertIn("Evaluation harness, including `harbor_wrapper.py`: no", ethos)
        self.assertIn("Model selection and sampling parameters: no", ethos)
        self.assertNotIn("with-approval", ethos)


class CachedBytecode(unittest.TestCase):
    """A planted .pyc must neither pass the verifier nor run under the contract.

    Python imports `__pycache__/<module>.<tag>.pyc` in place of source when the
    header matches the source's mtime and size, so a candidate can keep a
    byte-identical `harbor_wrapper.py` and still run different code. The run
    contract is PYTHONPYCACHEPREFIX, which moves bytecode lookup out of the
    tree; PYTHONDONTWRITEBYTECODE is not enough, because it stops writes only.
    """

    MARKER = "PLANTED-BYTECODE-RAN"

    def setUp(self) -> None:
        sys.path.insert(0, str(EXAMPLE / "scorer"))
        import verify_candidates

        self.verify = verify_candidates
        self.experiment = EXAMPLE / "harness" / "experiment"
        self.candidate = self.experiment / "eval-and-optimize" / "agents" / "agent-1"
        shutil.rmtree(self.experiment, ignore_errors=True)
        shutil.copytree(AGENT_SOURCE, self.candidate,
                        ignore=shutil.ignore_patterns("__pycache__", "artifacts", "traces"))
        self._plant()

    def tearDown(self) -> None:
        shutil.rmtree(self.experiment, ignore_errors=True)

    def _plant(self) -> None:
        """Write a timestamp-valid .pyc for the untouched wrapper source."""
        source = self.candidate / "harbor_wrapper.py"
        stat = source.stat()
        code = compile(f"print({self.MARKER!r})\n", str(source), "exec")
        header = (importlib.util.MAGIC_NUMBER + (0).to_bytes(4, "little")
                  + (int(stat.st_mtime) & 0xFFFFFFFF).to_bytes(4, "little")
                  + (stat.st_size & 0xFFFFFFFF).to_bytes(4, "little"))
        cache = self.candidate / "__pycache__"
        cache.mkdir()
        (cache / f"harbor_wrapper.{sys.implementation.cache_tag}.pyc").write_bytes(
            header + marshal.dumps(code))

    def _import_like_harbor(self, **env: str) -> subprocess.CompletedProcess[str]:
        """Import the candidate's wrapper the way harbor_native does.

        A synthetic package whose __path__ is the agent directory, then an
        ordinary import of `<package>.harbor_wrapper` through the path finder.
        """
        snippet = (
            "import importlib, importlib.machinery, sys, types\n"
            "pkg = types.ModuleType('agent_under_test')\n"
            "pkg.__spec__ = importlib.machinery.ModuleSpec('agent_under_test', None, is_package=True)\n"
            f"pkg.__path__ = [{str(self.candidate)!r}]\n"
            "sys.modules['agent_under_test'] = pkg\n"
            "importlib.import_module('agent_under_test.harbor_wrapper')\n"
        )
        clean = {k: v for k, v in os.environ.items() if not k.startswith("PYTHON")}
        return subprocess.run([sys.executable, "-c", snippet], capture_output=True,
                              text=True, env={**clean, **env}, timeout=120)

    def test_the_source_is_untouched(self) -> None:
        # The attack only matters because the byte comparison cannot see it.
        self.assertEqual((self.candidate / "harbor_wrapper.py").read_bytes(),
                         (AGENT_SOURCE / "harbor_wrapper.py").read_bytes())

    def test_planted_bytecode_runs_without_the_contract(self) -> None:
        # The threat is real: this is what a run without a prefix executes.
        # PYTHONDONTWRITEBYTECODE, the obvious fix, does not change it.
        for env in ({}, {"PYTHONDONTWRITEBYTECODE": "1"}):
            with self.subTest(env=env):
                self.assertIn(self.MARKER, self._import_like_harbor(**env).stdout)

    def test_planted_bytecode_cannot_run_under_the_contract(self) -> None:
        with tempfile.TemporaryDirectory() as prefix:
            done = self._import_like_harbor(PYTHONPYCACHEPREFIX=prefix)
        self.assertNotIn(self.MARKER, done.stdout)
        # The pristine source ran instead, found the planted directory, and
        # refused the candidate before any trial.
        self.assertIn("__pycache__ is cached bytecode", done.stderr)

    def test_the_external_verifier_rejects_it(self) -> None:
        self.assertIn("__pycache__ is cached bytecode, which Python imports in place of source",
                      self.verify.violations(self.candidate))

    def test_nested_bytecode_is_rejected_too(self) -> None:
        # Skills are the open surface, but bytecode is not a skill.
        nested = self.candidate / "workspace" / "skills" / "policy" / "__pycache__"
        nested.mkdir(parents=True)
        self.assertTrue(any(v.startswith("workspace/skills/policy/__pycache__ is cached bytecode")
                            for v in self.verify.violations(self.candidate)))


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
