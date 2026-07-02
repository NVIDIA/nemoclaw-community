# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for DeepAgentsAdapter's non-subprocess logic."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from hep.adapters.base import HarnessAdapter
from hep.adapters.deepagents import _PLUGIN_DIR, DeepAgentsAdapter


def _adapter(tmp_path: Path) -> DeepAgentsAdapter:
    return DeepAgentsAdapter(evals_dir=tmp_path)


def test_deepagents_adapter_satisfies_protocol(tmp_path: Path) -> None:
    assert isinstance(_adapter(tmp_path), HarnessAdapter)


def test_validate_config_accepts_valid_python(tmp_path: Path) -> None:
    # A minimal but well-formed profile shape: passes ast.parse always, and
    # passes the trial-registration pre-check too (register() exists and
    # doesn't raise) when the optional deepagents extra is installed.
    assert _adapter(tmp_path).validate_config("def register() -> None:\n    pass\n") is True


def test_validate_config_rejects_invalid_python(tmp_path: Path) -> None:
    assert _adapter(tmp_path).validate_config("def f(:\n") is False


def test_read_write_config_round_trip(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    config_file = tmp_path / "profile.py"
    adapter.write_config(config_file, "system_prompt_suffix = 'be careful'\n")
    assert adapter.read_config(config_file) == "system_prompt_suffix = 'be careful'\n"


def test_describe_config_surface_mentions_key_levers(tmp_path: Path) -> None:
    surface = _adapter(tmp_path).describe_config_surface()
    assert "system_prompt_suffix" in surface
    assert "extra_middleware" in surface


def test_extract_task_source_reads_function_body(tmp_path: Path) -> None:
    evals_dir = tmp_path
    test_file = evals_dir / "tests" / "evals" / "test_example.py"
    test_file.parent.mkdir(parents=True)
    test_file.write_text(
        "def test_something():\n"
        "    '''Docstring.'''\n"
        "    assert True\n"
    )
    adapter = DeepAgentsAdapter(evals_dir=evals_dir)

    source = adapter.extract_task_source("tests/evals/test_example.py::test_something[model:x]")

    assert source is not None
    assert "def test_something():" in source


def test_extract_task_source_returns_none_for_missing_file(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    assert adapter.extract_task_source("tests/evals/does_not_exist.py::test_x") is None


def test_collect_context_returns_empty_without_sdk_root(tmp_path: Path) -> None:
    adapter = _adapter(tmp_path)
    config_file = tmp_path / "profile.py"
    config_file.write_text("# no sdk here\n")
    assert adapter.collect_context(config_file, "some failure") == ""


def _build_checkout(tmp_path: Path) -> Path:
    """Lay out a synthetic checkout matching the real one's shape, including .venv bloat."""
    checkout = tmp_path / "checkout"
    sdk_pkg = checkout / "libs" / "deepagents" / "deepagents"
    sdk_pkg.mkdir(parents=True)
    (sdk_pkg / "__init__.py").write_text("")
    (sdk_pkg / "profiles" / "harness").mkdir(parents=True)
    (sdk_pkg / "profiles" / "harness" / "harness_profiles.py").write_text("HARNESS_PROFILES_MARKER = 1\n")

    sdk_venv_bloat = checkout / "libs" / "deepagents" / ".venv" / "lib" / "site-packages" / "anyio" / "_core"
    sdk_venv_bloat.mkdir(parents=True)
    (sdk_venv_bloat / "_fileio.py").write_text("# vendored dependency, not real SDK source\n")

    evals_tests = checkout / "libs" / "evals" / "tests"
    (evals_tests / "evals").mkdir(parents=True)
    (evals_tests / "evals" / "test_x.py").write_text("def test_x(): pass\n")
    (evals_tests / "unit_tests").mkdir(parents=True)
    (evals_tests / "unit_tests" / "test_y.py").write_text("def test_y(): pass\n")

    evals_venv_bloat = checkout / "libs" / "evals" / ".venv" / "lib" / "site-packages" / "requests"
    evals_venv_bloat.mkdir(parents=True)
    (evals_venv_bloat / "__init__.py").write_text("# vendored dependency, not real evals source\n")

    return checkout


def test_sdk_and_evals_roots_narrows_to_source_dirs(tmp_path: Path) -> None:
    checkout = _build_checkout(tmp_path)
    adapter = DeepAgentsAdapter(evals_dir=checkout / "libs" / "evals")

    sdk_root, evals_root = adapter.sdk_and_evals_roots()

    assert sdk_root == checkout / "libs" / "deepagents" / "deepagents"
    assert evals_root == checkout / "libs" / "evals" / "tests"


def test_sdk_and_evals_roots_excludes_venv_bloat(tmp_path: Path) -> None:
    checkout = _build_checkout(tmp_path)
    adapter = DeepAgentsAdapter(evals_dir=checkout / "libs" / "evals")

    sdk_root, evals_root = adapter.sdk_and_evals_roots()

    sdk_bloat = checkout / "libs" / "deepagents" / ".venv" / "lib" / "site-packages" / "anyio"
    evals_bloat = checkout / "libs" / "evals" / ".venv" / "lib" / "site-packages" / "requests"
    assert not sdk_bloat.is_relative_to(sdk_root)
    assert not evals_bloat.is_relative_to(evals_root)


def test_collect_context_returns_sdk_source_when_present(tmp_path: Path) -> None:
    checkout = _build_checkout(tmp_path)
    adapter = DeepAgentsAdapter(evals_dir=checkout / "libs" / "evals")
    config_file = tmp_path / "profile.py"
    config_file.write_text("# profile\n")

    context = adapter.collect_context(config_file, "some failure")

    assert context != ""
    assert "HARNESS_PROFILES_MARKER" in context


def test_run_pytest_wires_up_profile_plugin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """`_run_pytest` must set HEP_PROFILE_FILE, prepend PYTHONPATH, and pass -p."""
    captured: dict[str, Any] = {}

    class _FakeCompleted:
        returncode = 0

    def _fake_run(cmd, *, cwd, env, check):  # noqa: ANN001, ARG001
        captured["cmd"] = cmd
        captured["env"] = env
        return _FakeCompleted()

    monkeypatch.setattr("hep.adapters.deepagents.subprocess.run", _fake_run)

    adapter = _adapter(tmp_path)
    config_file = tmp_path / "profile.py"
    config_file.write_text("# profile\n")
    adapter._run_pytest(
        test_target="tests/evals", model="fake-model", config_file=config_file, report_file=tmp_path / "r.json"
    )

    assert "-p" in captured["cmd"]
    assert captured["cmd"][captured["cmd"].index("-p") + 1] == "hep_profile_plugin"
    assert captured["env"]["HEP_PROFILE_FILE"] == str(config_file)
    assert str(_PLUGIN_DIR) in captured["env"]["PYTHONPATH"].split(os.pathsep)
