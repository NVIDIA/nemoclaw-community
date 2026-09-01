# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import io
import json
import os
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).parents[1]
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import configuration as CONFIGURATION  # noqa: E402


def load_script(name: str):
    script = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"recipe_{name}", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


CONFIGURE = load_script("configure")
PREFLIGHT = load_script("preflight")

SLACK_ENV = {
    "COMPATIBLE_API_KEY": "test-inference-secret",
    "SLACK_BOT_TOKEN": "xoxb-test-bot-secret",
    "SLACK_APP_TOKEN": "xapp-test-app-secret",
}
OUTLOOK_ENV = {
    "COMPATIBLE_API_KEY": "test-inference-secret",
    "OUTLOOK_TENANT_ID": "test-tenant",
    "OUTLOOK_CLIENT_ID": "test-client",
    "OUTLOOK_TARGET_MAILBOX": "agent@example.test",
    "OUTLOOK_REPLY_TO": "owner@example.test",
}


class ConfigurationDocumentTest(TestCase):
    def test_updates_preserve_comments_order_and_unselected_values(self) -> None:
        original = "# operator note\nUNKNOWN=value\nSLACK_BOT_TOKEN=old\n"
        document = CONFIGURATION.parse_env_text(original)

        rendered = CONFIGURATION.render_updates(
            document,
            {
                "SLACK_BOT_TOKEN": "xoxb-new value",
                "SLACK_APP_TOKEN": "xapp-new",
            },
        )

        self.assertIn("# operator note\nUNKNOWN=value", rendered)
        self.assertIn("SLACK_BOT_TOKEN='xoxb-new value'", rendered)
        self.assertIn("SLACK_APP_TOKEN=xapp-new", rendered)
        self.assertEqual(
            "value", CONFIGURATION.parse_env_text(rendered).values["UNKNOWN"]
        )

    def test_duplicate_assignment_fails_instead_of_guessing(self) -> None:
        with self.assertRaisesRegex(CONFIGURATION.ConfigurationError, "duplicate"):
            CONFIGURATION.parse_env_text("SLACK_BOT_TOKEN=one\nSLACK_BOT_TOKEN=two\n")

    def test_invalid_unquoted_space_fails(self) -> None:
        with self.assertRaisesRegex(CONFIGURATION.ConfigurationError, "shell quoting"):
            CONFIGURATION.parse_env_text("NEMOCLAW_MODEL=two values\n")

    def test_inline_comments_and_hash_values_are_parsed_without_execution(self) -> None:
        document = CONFIGURATION.parse_env_text(
            "FIRST=value # operator note\n"
            "SECOND=value#suffix\n"
            "THIRD='value # quoted'\n"
            "FOURTH=#leading-hash\n"
        )

        self.assertEqual("value", document.values["FIRST"])
        self.assertEqual("value#suffix", document.values["SECOND"])
        self.assertEqual("value # quoted", document.values["THIRD"])
        self.assertEqual("#leading-hash", document.values["FOURTH"])

    def test_update_keeps_assignment_style_and_inline_comment(self) -> None:
        original = "  export SANDBOX_NAME=old-name  # operator note\n"
        document = CONFIGURATION.parse_env_text(original)

        unchanged = CONFIGURATION.render_updates(document, {"SANDBOX_NAME": "old-name"})
        changed = CONFIGURATION.render_updates(document, {"SANDBOX_NAME": "new-name"})

        self.assertEqual(original, unchanged)
        self.assertEqual(
            "  export SANDBOX_NAME=new-name  # operator note\n",
            changed,
        )

    def test_executable_shell_syntax_is_rejected_without_running_it(self) -> None:
        for text in (
            "VALUE=$(id)\n",
            "VALUE=`id`\n",
            "VALUE=${HOME}\n",
            "VALUE=valid;id\n",
            "id\n",
        ):
            with (
                self.subTest(text=text),
                self.assertRaisesRegex(
                    CONFIGURATION.ConfigurationError,
                    r"unsupported|not a supported",
                ),
            ):
                CONFIGURATION.parse_env_text(text)

        quoted = CONFIGURATION.parse_env_text("VALUE='${literal};value'\n")
        self.assertEqual("${literal};value", quoted.values["VALUE"])

    def test_atomic_write_uses_owner_only_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env"
            CONFIGURATION.write_env(path, "SLACK_BOT_TOKEN=xoxb-test\n")

            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(
                path.read_text(encoding="utf-8"), "SLACK_BOT_TOKEN=xoxb-test\n"
            )

    def test_defaults_resolve_without_overwriting_file_values(self) -> None:
        document = CONFIGURATION.parse_env_text("SANDBOX_NAME=custom-sandbox\n")
        values = CONFIGURATION.resolved_values(
            document,
            {"SANDBOX_NAME": "process-sandbox"},
        )

        self.assertEqual("custom-sandbox", values["SANDBOX_NAME"])
        self.assertEqual(CONFIGURATION.DEFAULT_MODEL, values["NEMOCLAW_MODEL"])
        self.assertEqual(
            "https://127.0.0.1:17670", values["OPENSHELL_GATEWAY_ENDPOINT"]
        )

    def test_atif_relay_endpoint_matches_lifecycle_origin_contract(self) -> None:
        self.assertEqual(
            ("https://host.openshell.internal:8443", "host.openshell.internal", 8443),
            CONFIGURATION.parse_atif_relay_endpoint(
                "https://host.openshell.internal:08443/"
            ),
        )


class GuidedConfigurationTest(TestCase):
    def test_non_interactive_slack_profile_preserves_existing_file(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env"
            path.write_text(
                "# keep this comment\n"
                "CUSTOM_SETTING=keep-me\n"
                "SANDBOX_NAME=existing\n"
                "NEMOCLAW_INFERENCE_PREFLIGHT=0\n",
                encoding="utf-8",
            )
            path.chmod(0o600)
            output = io.StringIO()
            with (
                patch.dict(os.environ, SLACK_ENV, clear=True),
                patch("sys.stdout", output),
            ):
                exit_code = CONFIGURE.main(
                    [
                        "--non-interactive",
                        "--profile",
                        "slack",
                        "--env-file",
                        str(path),
                    ]
                )

            self.assertEqual(0, exit_code)
            result = CONFIGURATION.read_env(path)
            self.assertEqual("keep-me", result.values["CUSTOM_SETTING"])
            self.assertEqual("existing", result.values["SANDBOX_NAME"])
            self.assertEqual("0", result.values["NEMOCLAW_INFERENCE_PREFLIGHT"])
            self.assertEqual(
                SLACK_ENV["SLACK_BOT_TOKEN"], result.values["SLACK_BOT_TOKEN"]
            )
            self.assertNotIn(SLACK_ENV["SLACK_BOT_TOKEN"], output.getvalue())
            self.assertNotIn(SLACK_ENV["SLACK_APP_TOKEN"], output.getvalue())
            self.assertNotIn(SLACK_ENV["COMPATIBLE_API_KEY"], output.getvalue())
            self.assertEqual(0o600, stat.S_IMODE(path.stat().st_mode))

    def test_non_interactive_profiles_generate_required_values(self) -> None:
        for profile, environment, required in (
            ("slack", SLACK_ENV, CONFIGURATION.SLACK_REQUIRED),
            ("outlook", OUTLOOK_ENV, CONFIGURATION.OUTLOOK_REQUIRED),
            (
                "both",
                {**SLACK_ENV, **OUTLOOK_ENV},
                CONFIGURATION.SLACK_REQUIRED + CONFIGURATION.OUTLOOK_REQUIRED,
            ),
        ):
            with (
                self.subTest(profile=profile),
                tempfile.TemporaryDirectory() as temp_dir,
            ):
                path = Path(temp_dir) / ".env"
                with (
                    patch.dict(os.environ, environment, clear=True),
                    patch("sys.stdout", io.StringIO()),
                ):
                    exit_code = CONFIGURE.main(
                        [
                            "--non-interactive",
                            "--profile",
                            profile,
                            "--env-file",
                            str(path),
                        ]
                    )
                values = CONFIGURATION.read_env(path).values
                self.assertEqual(0, exit_code)
                self.assertTrue(all(values.get(key) for key in required))
                self.assertEqual(
                    "NVIDIA/OpenShell", values["GITHUB_READONLY_REPOS"]
                )
                self.assertEqual([], CONFIGURATION.profile_errors(values))
                if profile == "slack":
                    self.assertNotIn("OUTLOOK_LOGIN_CACHE", values)
                if profile == "outlook":
                    self.assertNotIn("NEMOCLAW_SLACK_RICH_BLOCKS", values)

    def test_missing_non_interactive_value_fails_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / ".env"
            stderr = io.StringIO()
            with (
                patch.dict(
                    os.environ,
                    {
                        "COMPATIBLE_API_KEY": "test-inference-secret",
                        "SLACK_BOT_TOKEN": "xoxb-test-bot-secret",
                    },
                    clear=True,
                ),
                patch("sys.stderr", stderr),
            ):
                exit_code = CONFIGURE.main(
                    [
                        "--non-interactive",
                        "--profile",
                        "slack",
                        "--env-file",
                        str(path),
                    ]
                )

            self.assertEqual(2, exit_code)
            self.assertFalse(path.exists())
            self.assertIn("SLACK_APP_TOKEN", stderr.getvalue())
            self.assertNotIn("xoxb-test-bot-secret", stderr.getvalue())

    def test_interactive_and_non_interactive_paths_are_equivalent(self) -> None:
        environment = {**SLACK_ENV, **OUTLOOK_ENV}
        document = CONFIGURATION.EnvDocument(lines=(), values={}, line_indexes={})
        input_answers = iter([""] * 8)
        secret_answers = iter([""] * 3)
        _, interactive = CONFIGURE.collect_interactive_updates(
            document,
            environment,
            profile="both",
            replacements={},
            input_fn=lambda _prompt: next(input_answers),
            secret_fn=lambda _prompt: next(secret_answers),
        )
        non_interactive = CONFIGURE.collect_non_interactive_updates(
            document,
            environment,
            profile="both",
            replacements={},
            replace=False,
        )

        self.assertEqual(non_interactive, interactive)
        self.assertEqual(
            "https://127.0.0.1:17670",
            interactive["OPENSHELL_GATEWAY_ENDPOINT"],
        )

    def test_gateway_change_proposes_the_matching_endpoint(self) -> None:
        document = CONFIGURATION.parse_env_text("OPENSHELL_GATEWAY=openshell\n")
        input_answers = iter(["", "snap-docker", "", ""])
        secret_answers = iter([""] * 3)

        _, updates = CONFIGURE.collect_interactive_updates(
            document,
            SLACK_ENV,
            profile="slack",
            replacements={},
            input_fn=lambda _prompt: next(input_answers),
            secret_fn=lambda _prompt: next(secret_answers),
        )

        self.assertEqual("snap-docker", updates["OPENSHELL_GATEWAY"])
        self.assertEqual(
            "http://127.0.0.1:17670",
            updates["OPENSHELL_GATEWAY_ENDPOINT"],
        )

    def test_replace_discards_unselected_advanced_values_only_when_requested(
        self,
    ) -> None:
        document = CONFIGURATION.parse_env_text("ADVANCED_SETTING=old\n")
        updates = CONFIGURE.collect_non_interactive_updates(
            document,
            SLACK_ENV,
            profile="slack",
            replacements={},
            replace=True,
        )
        rendered = CONFIGURATION.render_updates(document, updates, replace=True)

        self.assertNotIn("ADVANCED_SETTING", rendered)
        self.assertIn("SLACK_BOT_TOKEN", rendered)

    def test_configurator_preserves_plural_github_repository_scope(self) -> None:
        document = CONFIGURATION.parse_env_text(
            "GITHUB_READONLY_REPOS=example/skills,example/blueprint\n"
        )
        updates = CONFIGURE.collect_non_interactive_updates(
            document,
            SLACK_ENV,
            profile="slack",
            replacements={},
            replace=False,
        )

        self.assertEqual(
            "example/skills,example/blueprint",
            updates["GITHUB_READONLY_REPOS"],
        )
        self.assertNotIn("GITHUB_READONLY_REPO", updates)

    def test_configurator_preserves_legacy_github_repository_scope(self) -> None:
        document = CONFIGURATION.parse_env_text(
            "GITHUB_READONLY_REPO=example/legacy\n"
        )
        updates = CONFIGURE.collect_non_interactive_updates(
            document,
            SLACK_ENV,
            profile="slack",
            replacements={},
            replace=False,
        )

        self.assertEqual("example/legacy", updates["GITHUB_READONLY_REPO"])
        self.assertNotIn("GITHUB_READONLY_REPOS", updates)


def successful_runner(
    command: tuple[str, ...] | list[str], _timeout: float
) -> subprocess.CompletedProcess[str]:
    args = list(command)
    stdout = ""
    if args == ["openshell", "--version"]:
        stdout = "openshell 0.0.85\n"
    elif args == [
        "openshell",
        "settings",
        "get",
        "--global",
        "--gateway",
        "openshell",
    ]:
        stdout = "providers_v2_enabled = true\n"
    return subprocess.CompletedProcess(args, 0, stdout, "")


class ConsolidatedPreflightTest(TestCase):
    def test_openshell_version_comes_from_dependency_contract(self) -> None:
        self.assertEqual(
            PREFLIGHT.resolve_expected_openshell_version(),
            PREFLIGHT.EXPECTED_OPENSHELL_VERSION,
        )

    def make_env(self, directory: str, values: dict[str, str] | None = None) -> Path:
        path = Path(directory) / ".env"
        ca_bundle = Path(directory) / "ca-certificates.crt"
        ca_bundle.write_text("test CA bundle\n", encoding="utf-8")
        settings = {
            **SLACK_ENV,
            "NEMOCLAW_HOST_CA_BUNDLE": str(ca_bundle),
            **(values or {}),
        }
        path.write_text(
            "\n".join(f"{key}={value}" for key, value in settings.items()) + "\n",
            encoding="utf-8",
        )
        path.chmod(0o600)
        return path

    def test_local_preflight_is_read_only_and_skips_external_services(self) -> None:
        commands: list[tuple[str, ...]] = []

        def runner(command, timeout):
            commands.append(tuple(command))
            return successful_runner(command, timeout)

        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(temp_dir)
            with (
                patch.object(PREFLIGHT.shutil, "which", return_value="/test/tool"),
                patch.object(
                    PREFLIGHT.inference_preflight, "run_preflight"
                ) as inference,
                patch.object(
                    PREFLIGHT.slack_socket_preflight, "run_preflight"
                ) as slack,
            ):
                result, exit_code = PREFLIGHT.run_preflight(
                    path,
                    environment={},
                    command_runner=runner,
                    port_available=lambda _port: True,
                    endpoint_reachable=lambda _endpoint, _timeout: True,
                )

        self.assertEqual(0, exit_code)
        self.assertTrue(result["ok"])
        inference.assert_not_called()
        slack.assert_not_called()
        self.assertEqual(
            {
                ("docker", "info"),
                ("docker", "compose", "version"),
                ("openshell", "--version"),
                ("openshell", "gateway", "info", "--gateway", "openshell"),
                (
                    "openshell",
                    "settings",
                    "get",
                    "--global",
                    "--gateway",
                    "openshell",
                ),
            },
            set(commands),
        )
        self.assertEqual(
            "python3 scripts/preflight.py --external", result["next_command"]
        )

    def test_external_preflight_reuses_specialized_validators(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(temp_dir)
            with (
                patch.object(PREFLIGHT.shutil, "which", return_value="/test/tool"),
                patch.object(
                    PREFLIGHT.inference_preflight, "run_preflight"
                ) as inference,
                patch.object(
                    PREFLIGHT.slack_socket_preflight, "run_preflight"
                ) as slack,
            ):
                result, exit_code = PREFLIGHT.run_preflight(
                    path,
                    environment={},
                    external=True,
                    command_runner=successful_runner,
                    port_available=lambda _port: True,
                    endpoint_reachable=lambda _endpoint, _timeout: True,
                )

        self.assertEqual(0, exit_code)
        inference.assert_called_once()
        slack.assert_called_once_with(SLACK_ENV["SLACK_APP_TOKEN"], 10.0)
        self.assertEqual("bash scripts/bring-up.sh", result["next_command"])
        serialized = json.dumps(result)
        self.assertNotIn(SLACK_ENV["SLACK_BOT_TOKEN"], serialized)
        self.assertNotIn(SLACK_ENV["SLACK_APP_TOKEN"], serialized)
        self.assertNotIn(SLACK_ENV["COMPATIBLE_API_KEY"], serialized)

    def test_tavily_external_preflight_is_optional_and_redacted(self) -> None:
        secret = "example-tavily-key-not-valid"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(temp_dir, {"TAVILY_API_KEY": secret})
            with (
                patch.object(PREFLIGHT.shutil, "which", return_value="/test/tool"),
                patch.object(PREFLIGHT.inference_preflight, "run_preflight"),
                patch.object(PREFLIGHT.slack_socket_preflight, "run_preflight"),
                patch.object(
                    PREFLIGHT.tavily_search_preflight, "run_preflight"
                ) as tavily,
            ):
                result, exit_code = PREFLIGHT.run_preflight(
                    path,
                    environment={},
                    external=True,
                    command_runner=successful_runner,
                    port_available=lambda _port: True,
                    endpoint_reachable=lambda _endpoint, _timeout: True,
                )

        self.assertEqual(0, exit_code)
        tavily.assert_called_once_with(secret, 10.0)
        serialized = json.dumps(result)
        self.assertNotIn(secret, serialized)
        self.assertIn('"Tavily API key": "configured"', serialized)
        tavily_check = next(
            item for item in result["checks"] if item["name"] == "Tavily Search"
        )
        self.assertEqual("PASS", tavily_check["status"])

    def test_failed_external_check_recommends_the_external_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(temp_dir)
            with (
                patch.object(PREFLIGHT.shutil, "which", return_value="/test/tool"),
                patch.object(
                    PREFLIGHT.inference_preflight,
                    "run_preflight",
                    side_effect=PREFLIGHT.inference_preflight.PreflightError(
                        "provider-availability", "test failure", 6
                    ),
                ),
                patch.object(PREFLIGHT.slack_socket_preflight, "run_preflight"),
            ):
                result, exit_code = PREFLIGHT.run_preflight(
                    path,
                    environment={},
                    external=True,
                    command_runner=successful_runner,
                    port_available=lambda _port: True,
                    endpoint_reachable=lambda _endpoint, _timeout: True,
                )

        self.assertEqual(1, exit_code)
        self.assertEqual(
            "python3 scripts/preflight.py --external", result["next_command"]
        )

    def test_non_finite_timeout_is_rejected_before_checks(self) -> None:
        stderr = io.StringIO()
        with patch("sys.stderr", stderr):
            exit_code = PREFLIGHT.main(["--timeout", "nan"])

        self.assertEqual(2, exit_code)
        self.assertIn("at most 60 seconds", stderr.getvalue())

    def test_invalid_configuration_reports_actionable_names_without_secrets(
        self,
    ) -> None:
        secret = "xoxb-private-test-value"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(
                temp_dir,
                {
                    "SLACK_BOT_TOKEN": secret,
                    "SLACK_APP_TOKEN": "wrong-token-type",
                    "NEMOCLAW_SLACK_RICH_BLOCKS": "yes",
                    "OUTLOOK_TENANT_ID": "partial",
                    "GITHUB_READONLY_REPO": "invalid",
                },
            )
            values = CONFIGURATION.resolved_values(CONFIGURATION.read_env(path), {})
            checks = PREFLIGHT.configuration_checks(path, values)

        failures = "\n".join(
            f"{item.name}: {item.detail}" for item in checks if item.status == "FAIL"
        )
        self.assertIn("partial Outlook configuration", failures)
        self.assertIn("Slack token formats", failures)
        self.assertIn("Slack rich blocks", failures)
        self.assertIn("GitHub read-only repository", failures)
        self.assertNotIn(secret, failures)

    def test_plural_github_repository_scope_is_reported_without_token(self) -> None:
        secret = "test-github-secret-value"
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(
                temp_dir,
                {
                    "GITHUB_READONLY_REPOS": "example/skills,example/blueprint",
                    "GITHUB_TOKEN": secret,
                },
            )
            values = CONFIGURATION.resolved_values(CONFIGURATION.read_env(path), {})
            checks = PREFLIGHT.configuration_checks(path, values)

        github = next(
            item for item in checks if item.name == "GitHub read-only repositories"
        )
        self.assertEqual("PASS", github.status)
        self.assertIn("2 configured", github.detail)
        self.assertNotIn(secret, github.detail)

    def test_missing_tools_and_gateway_are_reported_before_bring_up(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(temp_dir)
            with patch.object(PREFLIGHT.shutil, "which", return_value=None):
                result, exit_code = PREFLIGHT.run_preflight(
                    path,
                    environment={},
                    command_runner=successful_runner,
                    port_available=lambda _port: True,
                    endpoint_reachable=lambda _endpoint, _timeout: False,
                )

        self.assertEqual(1, exit_code)
        self.assertFalse(result["ok"])
        self.assertEqual("python3 scripts/preflight.py", result["next_command"])
        failed_names = {
            item["name"] for item in result["checks"] if item["status"] == "FAIL"
        }
        self.assertIn("docker command", failed_names)
        self.assertIn("openshell command", failed_names)

    def test_occupied_recipe_port_is_disclosed_as_warning(self) -> None:
        values = CONFIGURATION.resolved_values(
            CONFIGURATION.parse_env_text(
                "COMPATIBLE_API_KEY=test\n"
                "SLACK_BOT_TOKEN=xoxb-test\n"
                "SLACK_APP_TOKEN=xapp-test\n"
            ),
            {},
        )
        checks = PREFLIGHT.local_port_checks(
            values,
            port_available=lambda port: port != 6006,
        )

        phoenix = next(item for item in checks if item.name == "Phoenix UI port")
        self.assertEqual("WARN", phoenix.status)
        self.assertIn("already in use", phoenix.detail)

    def test_custom_host_service_ports_are_checked(self) -> None:
        values = CONFIGURATION.resolved_values(
            CONFIGURATION.parse_env_text(
                "SOURCE_ETL_API_PORT=3200\n"
                "SOURCE_ETL_POSTGRES_PORT=5544\n"
                "ATIF_EXPORT_MODE=relay\n"
                "ATIF_RELAY_ENDPOINT=https://host.openshell.internal:19443\n"
            ),
            {},
        )
        observed: list[int] = []

        PREFLIGHT.local_port_checks(
            values,
            port_available=lambda port: observed.append(port) or True,
        )

        self.assertIn(3200, observed)
        self.assertIn(5544, observed)
        self.assertIn(19443, observed)

    def test_invalid_atif_relay_origins_fail_before_port_check(self) -> None:
        invalid_endpoints = {
            "path": "https://host.openshell.internal:18443/unexpected",
            "query": "https://host.openshell.internal:18443?mode=test",
            "fragment": "https://host.openshell.internal:18443#relay",
            "user information": "https://operator:private@host.example:18443",
            "missing explicit port": "https://host.openshell.internal",
            "invalid hostname": "https://-invalid.example:18443",
            "port below range": "https://host.openshell.internal:0",
            "port above range": "https://host.openshell.internal:65536",
        }

        for case, endpoint in invalid_endpoints.items():
            with self.subTest(case=case):
                values = CONFIGURATION.resolved_values(
                    CONFIGURATION.parse_env_text(
                        f"ATIF_EXPORT_MODE=relay\nATIF_RELAY_ENDPOINT={endpoint}\n"
                    ),
                    {},
                )
                observed: list[int] = []

                checks = PREFLIGHT.local_port_checks(
                    values,
                    port_available=lambda port: observed.append(port) or True,
                )

                failure = next(
                    item for item in checks if item.name == "ATIF relay endpoint"
                )
                self.assertEqual("FAIL", failure.status)
                self.assertNotIn(endpoint, failure.detail)
                self.assertNotIn(18443, observed)
                self.assertNotIn(65536, observed)

    def test_missing_configuration_points_to_configurator(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / ".env"
            with patch.object(PREFLIGHT.shutil, "which", return_value=None):
                result, exit_code = PREFLIGHT.run_preflight(
                    missing,
                    environment=SLACK_ENV,
                    command_runner=successful_runner,
                    port_available=lambda _port: True,
                    endpoint_reachable=lambda _endpoint, _timeout: False,
                )

        self.assertEqual(1, exit_code)
        self.assertEqual("python3 scripts/configure.py", result["next_command"])

    def test_world_readable_configuration_fails_with_exact_fix(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.make_env(temp_dir)
            path.chmod(0o644)
            values = CONFIGURATION.resolved_values(CONFIGURATION.read_env(path), {})
            check = PREFLIGHT.configuration_checks(path, values)[0]

        self.assertEqual("FAIL", check.status)
        self.assertIn("chmod 600", check.remediation)


if __name__ == "__main__":
    import unittest

    unittest.main()
