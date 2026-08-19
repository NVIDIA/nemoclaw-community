# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml

EXAMPLE_DIR = Path(__file__).parents[2]
SCRIPTS_DIR = EXAMPLE_DIR / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import configuration as CONFIGURATION  # noqa: E402
from lib import github_repositories as REPOSITORIES  # noqa: E402


def load_github_helper():
    script = (
        EXAMPLE_DIR
        / "agents/hermes/skills/github-readonly-live/scripts/github_readonly.py"
    )
    spec = importlib.util.spec_from_file_location("github_readonly_live", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


GITHUB_HELPER = load_github_helper()


class RepositoryConfigurationTest(TestCase):
    def test_plural_setting_takes_precedence_and_preserves_order(self) -> None:
        repositories = CONFIGURATION.github_readonly_repositories(
            {
                "GITHUB_READONLY_REPOS": "example/skills, example/blueprint",
                "GITHUB_READONLY_REPO": "example/legacy",
            }
        )

        self.assertEqual(("example/skills", "example/blueprint"), repositories)

    def test_single_repository_setting_remains_supported(self) -> None:
        repositories = CONFIGURATION.github_readonly_repositories(
            {"GITHUB_READONLY_REPO": "example/legacy"}
        )

        self.assertEqual(("example/legacy",), repositories)

    def test_invalid_empty_duplicate_and_unsafe_items_fail_closed(self) -> None:
        for value in (
            "example/one,,example/two",
            "example/one,EXAMPLE/ONE",
            "example/one,example/two;post",
            "example/one,example/two\nexample/three",
            "example/..",
        ):
            with (
                self.subTest(value=value),
                self.assertRaises(CONFIGURATION.ConfigurationError),
            ):
                CONFIGURATION.github_readonly_repositories(
                    {"GITHUB_READONLY_REPOS": value}
                )


class RepositoryPolicyTest(TestCase):
    def test_policy_allows_two_repositories_and_no_write_methods(self) -> None:
        template = (EXAMPLE_DIR / "policy.yaml").read_text(encoding="utf-8")
        rendered = REPOSITORIES.render_policy(
            template, ("example/skills", "example/blueprint")
        )
        policy = yaml.safe_load(rendered)
        rules = policy["network_policies"]["github_repo_readonly"]["endpoints"][
            0
        ]["rules"]
        allowed = [rule["allow"] for rule in rules]
        paths = {rule["path"] for rule in allowed}

        self.assertIn("/repos/example/skills", paths)
        self.assertIn("/repos/example/skills/issues/**", paths)
        self.assertIn("/repos/example/blueprint", paths)
        self.assertIn("/repos/example/blueprint/contents/**", paths)
        self.assertFalse(any("example/unlisted" in path for path in paths))
        self.assertEqual({"GET"}, {rule["method"] for rule in allowed})
        self.assertNotIn(REPOSITORIES.POLICY_MARKER, rendered)

    def test_static_policy_is_fail_closed_until_staged(self) -> None:
        template = (EXAMPLE_DIR / "policy.yaml").read_text(encoding="utf-8")
        policy = yaml.safe_load(template)
        rules = policy["network_policies"]["github_repo_readonly"]["endpoints"][
            0
        ]["rules"]

        self.assertEqual([{"allow": {"method": "GET", "path": "/rate_limit"}}], rules)

    def test_staging_command_writes_resolved_repository_rules(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "policy.yaml"
            with patch.dict(
                os.environ,
                {"GITHUB_READONLY_REPOS": "example/skills,example/blueprint"},
                clear=True,
            ):
                exit_code = REPOSITORIES.main(
                    [
                        "stage-policy",
                        "--template",
                        str(EXAMPLE_DIR / "policy.yaml"),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, exit_code)
            rendered = output.read_text(encoding="utf-8")
            self.assertIn("/repos/example/skills/issues/**", rendered)
            self.assertIn("/repos/example/blueprint/pulls/**", rendered)

            with patch.dict(
                os.environ,
                {"GITHUB_READONLY_REPO": "example/legacy"},
                clear=True,
            ):
                exit_code = REPOSITORIES.main(
                    [
                        "stage-policy",
                        "--template",
                        str(EXAMPLE_DIR / "policy.yaml"),
                        "--output",
                        str(output),
                    ]
                )

            self.assertEqual(0, exit_code)
            legacy = output.read_text(encoding="utf-8")
            self.assertIn("/repos/example/legacy/issues/**", legacy)
            self.assertNotIn("/repos/example/skills", legacy)

    def test_plural_scope_is_propagated_to_build_and_runtime(self) -> None:
        sandbox_script = (EXAMPLE_DIR / "scripts/03-sandbox.sh").read_text(
            encoding="utf-8"
        )
        dockerfile = (EXAMPLE_DIR / "agents/hermes/Dockerfile").read_text(
            encoding="utf-8"
        )
        start_script = (EXAMPLE_DIR / "agents/hermes/start.sh").read_text(
            encoding="utf-8"
        )

        self.assertIn(
            '[GITHUB_READONLY_REPOS]="$GITHUB_READONLY_REPOS"', sandbox_script
        )
        self.assertIn(
            'GITHUB_READONLY_REPOS="$GITHUB_READONLY_REPOS"', sandbox_script
        )
        self.assertIn("ARG GITHUB_READONLY_REPOS=\n", dockerfile)
        self.assertIn("GITHUB_READONLY_REPOS=${GITHUB_READONLY_REPOS}", dockerfile)
        self.assertIn("export GITHUB_READONLY_REPOS=", start_script)


class RepositoryHelperTest(TestCase):
    def run_repo_command(self, repository: str, observed: list[str]) -> None:
        def fake_get_json(path, _params=None):
            observed.append(path)
            return {"full_name": repository}

        argv = ["github_readonly.py", "--repo", repository, "repo"]
        with (
            patch.object(GITHUB_HELPER, "get_json", side_effect=fake_get_json),
            patch.object(sys, "argv", argv),
            patch.object(sys, "stdout", io.StringIO()),
        ):
            self.assertEqual(0, GITHUB_HELPER.main())

    def test_two_allowed_repositories_can_be_read_in_one_lifecycle(self) -> None:
        observed: list[str] = []
        with patch.dict(
            os.environ,
            {"GITHUB_READONLY_REPOS": "example/skills,example/blueprint"},
            clear=True,
        ):
            self.run_repo_command("example/skills", observed)
            self.run_repo_command("example/blueprint", observed)

        self.assertEqual(
            ["/repos/example/skills", "/repos/example/blueprint"], observed
        )

    def test_unlisted_repository_is_rejected_before_http(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"GITHUB_READONLY_REPOS": "example/skills,example/blueprint"},
                clear=True,
            ),
            patch.object(GITHUB_HELPER, "get_json") as get_json,
            self.assertRaisesRegex(SystemExit, "not in the GitHub read-only allowlist"),
        ):
            GITHUB_HELPER.select_repository(
                "example/unlisted", GITHUB_HELPER.allowed_repositories()
            )

        get_json.assert_not_called()

    def test_multiple_repositories_require_an_explicit_selection(self) -> None:
        with self.assertRaisesRegex(SystemExit, "select one with --repo"):
            GITHUB_HELPER.select_repository(
                None, ("example/skills", "example/blueprint")
            )

    def test_single_legacy_repository_keeps_implicit_selection(self) -> None:
        with patch.dict(
            os.environ,
            {"GITHUB_READONLY_REPO": "example/legacy"},
            clear=True,
        ):
            repositories = GITHUB_HELPER.allowed_repositories()

        self.assertEqual(
            "example/legacy", GITHUB_HELPER.select_repository(None, repositories)
        )

    def test_write_like_command_is_rejected_before_http(self) -> None:
        argv = ["github_readonly.py", "--repo", "example/skills", "post", "issues"]
        with (
            patch.dict(
                os.environ,
                {"GITHUB_READONLY_REPOS": "example/skills"},
                clear=True,
            ),
            patch.object(GITHUB_HELPER, "get_json") as get_json,
            patch.object(sys, "argv", argv),
            patch.object(sys, "stderr", io.StringIO()),
            self.assertRaises(SystemExit) as exit_context,
        ):
            GITHUB_HELPER.main()

        self.assertEqual(2, exit_context.exception.code)
        get_json.assert_not_called()

    def test_http_helper_constructs_only_get_requests(self) -> None:
        class Response(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_args):
                self.close()

        observed_methods: list[str] = []

        def fake_urlopen(request, timeout):
            self.assertEqual(30, timeout)
            observed_methods.append(request.get_method())
            return Response(json.dumps({"ok": True}).encode("utf-8"))

        with (
            patch.object(GITHUB_HELPER.urllib.request, "urlopen", fake_urlopen),
            patch.object(GITHUB_HELPER, "auth_header", return_value=None),
        ):
            result = GITHUB_HELPER.get_json("/repos/example/skills")

        self.assertEqual({"ok": True}, result)
        self.assertEqual(["GET"], observed_methods)
