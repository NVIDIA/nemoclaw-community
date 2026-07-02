# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""HarnessAdapter implementation for the LangChain deepagents SDK.

Wraps a deepagents `libs/evals` checkout: runs its pytest-based eval suite via
subprocess, and reads/writes `HarnessProfile` files (the deepagents SDK's
model-specific runtime-behavior config, tuned via `system_prompt_suffix` and
`extra_middleware`).
"""

from __future__ import annotations

import ast
import inspect
import json
import os
import re
import subprocess
import sys
import types
from pathlib import Path
from typing import Any

from hep.adapters import _deepagents_patch
from hep.adapters.base import HarnessAdapter

_PLUGIN_DIR = Path(__file__).resolve().parents[3] / "plugins"
"""Directory containing hep_profile_plugin.py, prepended to PYTHONPATH so `-p hep_profile_plugin` resolves."""

_TOOL_NAMES_RE = re.compile(r"\b(read_file|write_file|edit_file|ls|glob|grep|delete)\b")

_SDK_ALWAYS_FILES = ("profiles/harness/harness_profiles.py",)
_SDK_TOOL_FILES = ("middleware/filesystem.py",)
_SDK_SKILL_FILES = ("middleware/skills.py",)
_SDK_FILE_MAX_CHARS = 6000
_MAX_TEST_SOURCE_CHARS = 4000

_CONFIG_SURFACE = """\
A HarnessProfile is a Python file that configures model-specific runtime behavior via:
  - system_prompt_suffix: str  — appended to the base system prompt
  - extra_middleware: list[AgentMiddleware] | Callable  — intercept tool calls and model outputs

AgentMiddleware hooks you may implement (provide BOTH sync and async variants for each):
  - wrap_tool_call(request, handler) / awrap_tool_call(request, handler)
  - wrap_model_call(request, handler) / awrap_model_call(request, handler)
  - before_model(state, runtime) / abefore_model(state, runtime)

Fix strategy — choose the right lever for the observed failure:
  - system_prompt_suffix: guides the model's reasoning and decisions at inference time.
  - wrap_model_call middleware: intercepts and transforms model outputs (tool calls or
    final text) before they are executed — for failures prompt guidance cannot prevent.
  - wrap_tool_call middleware: intercepts tool results before the model sees them — for
    failures caused by missing or misleading information in tool output.
Both levers can be combined when neither alone is sufficient.\
"""


def _warn(msg: str) -> None:
    """Print a warning to stderr, prefixed for this adapter."""
    print(f"[hep:deepagents] warning: {msg}", file=sys.stderr, flush=True)


def _log(msg: str) -> None:
    """Print a progress message to stdout, prefixed for this adapter."""
    print(f"[hep:deepagents] {msg}", flush=True)


class DeepAgentsAdapter(HarnessAdapter):
    """HarnessAdapter for a deepagents SDK checkout's `libs/evals` package.

    Args:
        evals_dir: Path to the `libs/evals` directory of a deepagents source
            checkout. Its `tests/evals` suite is run via `uv run pytest`.
    """

    def __init__(self, evals_dir: Path) -> None:
        self._evals_dir = evals_dir.resolve()

    def read_config(self, config_file: Path) -> str:
        """Return the current contents of the HarnessProfile file being tuned."""
        return config_file.read_text(encoding="utf-8")

    def write_config(self, config_file: Path, content: str) -> None:
        """Write `content` to `config_file` after validating it as Python."""
        config_file.write_text(content, encoding="utf-8")

    def validate_config(self, content: str) -> bool:
        """Return True if `content` is syntactically valid and, when possible, trial-registers.

        `ast.parse` catches outright syntax errors with zero dependencies. If
        `deepagents` is importable in this venv (the optional `deepagents`
        extra), also trial-import and call `register()` in-process to catch
        construction-time errors (wrong middleware hook signature, undefined
        name, bad field) that `ast.parse` can't — before paying for a full
        eval-suite subprocess run. This is a fast, approximate filter: it
        validates against whatever `deepagents` version is installed in
        hep's own venv, not necessarily the exact version in the
        `--evals-dir` checkout under test. The real `run_eval_suite`/
        `run_single_test` subprocess flow against the actual checkout remains
        the authoritative verification.
        """
        try:
            ast.parse(content)
        except SyntaxError as exc:
            _warn(f"proposed fix has syntax error: {exc}")
            return False

        error = self._trial_register(content)
        if error is not None:
            _warn(f"proposed fix failed trial registration: {error}")
            return False
        return True

    def _trial_register(self, content: str) -> str | None:
        """Best-effort in-process trial import + register of a candidate profile.

        Restores the harness-profile registry to its exact pre-trial state
        afterward (success or failure) — without this, a second trial for the
        same key would additively merge onto the first (possibly-broken)
        candidate's leftovers instead of the true baseline.

        Returns:
            An error message if the trial raised, or None if it succeeded or
            `deepagents` isn't importable in this venv (skipped gracefully).
        """
        try:
            from deepagents.profiles.harness import harness_profiles as _hr
        except ImportError:
            return None

        _deepagents_patch.apply()

        touched_keys: set[str] = set()
        prior_values: dict[str, Any] = {}
        original_register_impl = _hr._register_harness_profile_impl

        def _tracking_register(key: str, profile: Any) -> None:
            if key not in touched_keys:
                touched_keys.add(key)
                prior_values[key] = _hr._HARNESS_PROFILES.get(key)
            original_register_impl(key, profile)

        _hr._register_harness_profile_impl = _tracking_register
        try:
            module = types.ModuleType("_hep_trial_profile")
            exec(compile(content, "<candidate-profile>", "exec"), module.__dict__)  # noqa: S102
            module.register()
        except Exception as exc:  # noqa: BLE001 - any candidate error is a validation failure
            return f"{type(exc).__name__}: {exc}"
        finally:
            _hr._register_harness_profile_impl = original_register_impl
            for key in touched_keys:
                prior = prior_values[key]
                if prior is None:
                    _hr.unregister_harness_profile(key)
                else:
                    _hr._HARNESS_PROFILES[key] = prior
        return None

    def run_eval_suite(
        self,
        model: str,
        config_file: Path,
        report_file: Path,
        categories: list[str] | None,
    ) -> dict[str, Any]:
        """Run the full `tests/evals` suite and return the parsed JSON report."""
        _log(f"running eval suite (model={model}, categories={categories or 'all'})")
        report_file.unlink(missing_ok=True)
        self._run_pytest(
            test_target="tests/evals",
            model=model,
            config_file=config_file,
            report_file=report_file,
            categories=categories,
        )
        if not report_file.is_file():
            _warn(f"no report written to {report_file}")
            return {}
        return json.loads(report_file.read_text(encoding="utf-8"))

    def run_single_test(
        self,
        node_id: str,
        model: str,
        config_file: Path,
        report_file: Path,
    ) -> tuple[bool, str]:
        """Re-run one pytest node ID; return (passed, failure_message_or_empty)."""
        _log(f"  re-running: {node_id}")
        report_file.unlink(missing_ok=True)
        # node_id already includes the model parametrization suffix e.g.
        # tests/evals/test_foo.py::test_bar[openai:nvidia/...] — pass it directly
        # as the positional target; --model must still be specified for the
        # conftest fixture.
        self._run_pytest(test_target=node_id, model=model, config_file=config_file, report_file=report_file)
        if not report_file.is_file():
            return False, "(no report written)"
        data = json.loads(report_file.read_text(encoding="utf-8"))
        passed = data.get("passed", 0) == 1
        failures = data.get("failures", [])
        failure_msg = failures[0].get("failure_message", "") if failures else ""
        return passed, failure_msg

    def extract_task_source(self, task_name: str) -> str | None:
        """Extract the source of the test function identified by its pytest node ID.

        Strips the parametrize suffix (e.g. `[model:...]`) and reads the function
        body from the test file using ast, giving the frontier model the full
        task description and success criteria rather than only the failure
        message.
        """
        base = re.sub(r"\[.*\]$", "", task_name)
        rel_path, sep, func_name = base.rpartition("::")
        if not sep:
            return None
        test_file = self._evals_dir / rel_path
        if not test_file.is_file():
            return None
        try:
            source = test_file.read_text(encoding="utf-8")
            tree = ast.parse(source)
        except (OSError, SyntaxError):
            return None
        lines = source.splitlines()
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == func_name:
                start = (
                    node.decorator_list[0].lineno - 1 if node.decorator_list else node.lineno - 1
                )
                end = node.end_lineno
                extracted = "\n".join(lines[start:end])
                if len(extracted) > _MAX_TEST_SOURCE_CHARS:
                    extracted = extracted[:_MAX_TEST_SOURCE_CHARS] + "\n... [test source truncated]"
                return extracted
        return None

    def collect_context(self, config_file: Path, failure_message: str) -> str:
        """Return relevant deepagents SDK source files as a string for the frontier model.

        Always includes the HarnessProfile definition. Conditionally includes
        middleware files that document tool behaviour (limits, truncation
        signals, etc.) based on what tools appear in the failure trajectory.
        The frontier model reads the real source instead of relying on
        hardcoded summaries.
        """
        sdk_root = self._sdk_root()
        if sdk_root is None:
            return ""

        rel_paths = list(_SDK_ALWAYS_FILES)
        tool_names = set(_TOOL_NAMES_RE.findall(failure_message))
        if tool_names:
            rel_paths.extend(_SDK_TOOL_FILES)
        if "skill" in failure_message.lower():
            rel_paths.extend(_SDK_SKILL_FILES)

        sections: list[str] = []
        for rel_path in rel_paths:
            path = sdk_root / rel_path
            if not path.is_file():
                continue
            content = path.read_text(encoding="utf-8")
            if len(content) > _SDK_FILE_MAX_CHARS:
                content = content[:_SDK_FILE_MAX_CHARS] + f"\n... [{rel_path} truncated]"
            sections.append(f"# {rel_path}\n{content}")

        # Include the installed AgentMiddleware types (hook signatures, type
        # aliases). Imported lazily to avoid a hard dependency at module load
        # time — langchain may not be on the path in every environment.
        try:
            import langchain.agents.middleware.types as _mw

            mw_src = inspect.getsource(_mw)
            if len(mw_src) > _SDK_FILE_MAX_CHARS:
                mw_src = mw_src[:_SDK_FILE_MAX_CHARS] + "\n... [truncated]"
            sections.append(f"# langchain.agents.middleware.types\n{mw_src}")
        except (ImportError, OSError):
            pass

        if not sections:
            return ""
        return (
            "SDK SOURCE FILES (use these to understand APIs and tool defaults):\n\n"
            + "\n\n---\n\n".join(sections)
        )

    def describe_config_surface(self) -> str:
        """Describe the HarnessProfile config surface for the optimizer's system prompt."""
        return _CONFIG_SURFACE

    def sdk_and_evals_roots(self) -> tuple[Path | None, Path]:
        """Return (sdk_root_or_None, evals_test_root) for read-only exposure to an agentic proposer.

        Both paths are narrowed to real source/test directories, not the
        whole project directories they live in — `<checkout>/libs/deepagents`
        and `<checkout>/libs/evals` each contain their own multi-thousand-file
        `.venv` (and, for the SDK side, egg-info/docs/scripts) alongside the
        actual source, which would otherwise flood an agentic proposer's
        grep/glob results with irrelevant vendored dependency code.

        Returns:
            A tuple of the importable `deepagents` package directory (None if
            it could not be located — same fallback behavior as
            `collect_context`, which silently omits SDK context in that case)
            and the evals project's `tests/` directory (covering both
            `tests/evals/`, what the eval suite itself runs, and
            `tests/unit_tests/`, which documents fixture/plugin behavior a
            proposer diagnosing a harness-profile failure may also need).
        """
        return self._sdk_root(), self._evals_dir / "tests"

    def _sdk_root(self) -> Path | None:
        """Return the importable `deepagents` package directory, derived from `--evals-dir`.

        `evals_dir` always points at `<checkout>/libs/evals`; the SDK package
        always lives at the sibling `<checkout>/libs/deepagents/deepagents`
        (the inner, importable package directory, not the outer project
        directory that also contains its `.venv`, `tests/`, `scripts/`, and
        docs). Deriving the root this way (rather than walking up from a
        config file's own location) works identically whether the config
        file being tuned lives inside the checkout or is a completely custom
        file living anywhere.
        """
        project_dir = self._evals_dir.parent / "deepagents"
        candidate = project_dir / "deepagents"
        if not (candidate / "__init__.py").is_file():
            _warn(
                f"expected an importable deepagents package at {candidate}, sibling to "
                f"--evals-dir ({self._evals_dir}) — SDK source context will not be collected. "
                "Confirm --evals-dir points at a deepagents checkout's libs/evals directory."
            )
            return None
        return candidate

    def _run_pytest(
        self,
        *,
        test_target: str,
        model: str,
        config_file: Path,
        report_file: Path,
        categories: list[str] | None = None,
    ) -> int:
        """Run pytest against the deepagents eval suite and return its exit code."""
        cmd: list[str] = [
            "uv",
            "run",
            "--group",
            "test",
            "pytest",
            test_target,
            "-v",
            "--tb=short",
            "--model",
            model,
            "--evals-report-file",
            str(report_file),
            "-p",
            "hep_profile_plugin",
        ]
        if categories:
            for cat in categories:
                cmd += ["--eval-category", cat]

        env = os.environ.copy()
        # This subprocess is a separate `uv` project (its own .venv under
        # self._evals_dir). Drop any inherited VIRTUAL_ENV so uv manages that
        # project's own venv instead of warning about a path mismatch against
        # hep's own .venv.
        env.pop("VIRTUAL_ENV", None)
        env.setdefault("LANGSMITH_TEST_SUITE", "deepagents-evals")
        env["HEP_PROFILE_FILE"] = str(config_file)
        existing_pythonpath = env.get("PYTHONPATH")
        env["PYTHONPATH"] = (
            f"{_PLUGIN_DIR}{os.pathsep}{existing_pythonpath}"
            if existing_pythonpath
            else str(_PLUGIN_DIR)
        )

        result = subprocess.run(cmd, cwd=self._evals_dir, env=env, check=False)
        return result.returncode
