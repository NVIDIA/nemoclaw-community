# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

import yaml

EXAMPLE_DIR = Path(__file__).parents[2]
SCRIPTS_DIR = EXAMPLE_DIR / "scripts"
HERMES_DIR = EXAMPLE_DIR / "agents" / "hermes"
sys.path.insert(0, str(SCRIPTS_DIR))

from lib import web_search_policy as WEB_POLICY  # noqa: E402


def load_script(name: str):
    script = SCRIPTS_DIR / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"recipe_{name}", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


TAVILY_PREFLIGHT = load_script("tavily_search_preflight")


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class WebSearchPolicyTest(TestCase):
    def test_unconfigured_template_grants_no_tavily_egress(self) -> None:
        template = (EXAMPLE_DIR / "policy.yaml").read_text(encoding="utf-8")
        rendered = WEB_POLICY.render_policy(template, enabled=False)
        policy = yaml.safe_load(rendered)

        self.assertNotIn("tavily_web_search", policy["network_policies"])
        self.assertNotIn("api.tavily.com", rendered)
        self.assertNotIn(WEB_POLICY.POLICY_MARKER, rendered)

    def test_configured_policy_allows_only_search_from_hermes_python(self) -> None:
        template = (EXAMPLE_DIR / "policy.yaml").read_text(encoding="utf-8")
        rendered = WEB_POLICY.render_policy(template, enabled=True)
        block = yaml.safe_load(rendered)["network_policies"]["tavily_web_search"]
        endpoint = block["endpoints"][0]

        self.assertEqual("api.tavily.com", endpoint["host"])
        self.assertIs(endpoint["request_body_credential_rewrite"], True)
        self.assertEqual(
            [{"allow": {"method": "POST", "path": "/search"}}],
            endpoint["rules"],
        )
        self.assertEqual([{"path": "/opt/hermes/.venv/bin/python"}], block["binaries"])
        self.assertNotIn("/extract", rendered)
        self.assertNotIn("curl", WEB_POLICY.TAVILY_POLICY)

    def test_provider_profile_matches_the_same_narrow_boundary(self) -> None:
        profile = yaml.safe_load(
            (EXAMPLE_DIR / "providers" / "tavily-search.yaml").read_text(
                encoding="utf-8"
            )
        )

        self.assertEqual("nemoclaw-tavily-search", profile["id"])
        self.assertEqual(["TAVILY_API_KEY"], profile["credentials"][0]["env_vars"])
        self.assertEqual(
            [{"allow": {"method": "POST", "path": "/search"}}],
            profile["endpoints"][0]["rules"],
        )
        self.assertIs(profile["endpoints"][0]["request_body_credential_rewrite"], True)
        self.assertEqual(["/opt/hermes/.venv/bin/python"], profile["binaries"])

    def test_staging_command_supports_the_same_input_and_output_path(self) -> None:
        template = (EXAMPLE_DIR / "policy.yaml").read_text(encoding="utf-8")
        with tempfile.TemporaryDirectory() as temp_dir:
            staged = Path(temp_dir) / "policy.yaml"
            staged.write_text(template, encoding="utf-8")
            with patch.dict(
                os.environ, {"TAVILY_API_KEY": "test-tavily-key"}, clear=True
            ):
                exit_code = WEB_POLICY.main(
                    ["--template", str(staged), "--output", str(staged)]
                )

            self.assertEqual(0, exit_code)
            rendered = staged.read_text(encoding="utf-8")
            self.assertIn("api.tavily.com", rendered)
            self.assertNotIn(WEB_POLICY.POLICY_MARKER, rendered)


class TavilyPreflightTest(TestCase):
    def test_bounded_request_uses_fixed_endpoint_without_exposing_key(self) -> None:
        secret = "example-tavily-key-not-valid"
        observed = {}

        def urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["method"] = request.get_method()
            observed["body"] = json.loads(request.data)
            observed["authorization"] = request.get_header("Authorization")
            observed["timeout"] = timeout
            return Response(b'{"results":[{"title":"NemoClaw"}]}')

        TAVILY_PREFLIGHT.run_preflight(secret, 7, urlopen=urlopen)

        self.assertEqual(TAVILY_PREFLIGHT.TAVILY_SEARCH_URL, observed["url"])
        self.assertEqual("POST", observed["method"])
        self.assertEqual(1, observed["body"]["max_results"])
        self.assertIs(observed["body"]["include_raw_content"], False)
        self.assertEqual(f"Bearer {secret}", observed["authorization"])
        self.assertEqual(7, observed["timeout"])

    def test_invalid_credentials_fail_before_http(self) -> None:
        for key in (
            "",
            " example-tavily-key-not-valid ",
            "openshell:resolve:env:TAVILY_API_KEY",
        ):
            with (
                self.subTest(key=key),
                patch.object(TAVILY_PREFLIGHT.urllib.request, "urlopen") as urlopen,
                self.assertRaises(TAVILY_PREFLIGHT.TavilyPreflightError),
            ):
                TAVILY_PREFLIGHT.run_preflight(key)
            urlopen.assert_not_called()

    def test_rejected_credential_error_and_cli_output_are_redacted(self) -> None:
        secret = "example-rejected-tavily-key-not-valid"
        error = urllib.error.HTTPError(
            TAVILY_PREFLIGHT.TAVILY_SEARCH_URL,
            401,
            "body mentions " + secret,
            {},
            io.BytesIO(("server echoed " + secret).encode()),
        )
        with self.assertRaisesRegex(
            TAVILY_PREFLIGHT.TavilyPreflightError, "rejected.*HTTP 401"
        ) as context:
            TAVILY_PREFLIGHT.run_preflight(
                secret, urlopen=lambda *_args, **_kwargs: (_ for _ in ()).throw(error)
            )
        self.assertNotIn(secret, str(context.exception))

        stderr = io.StringIO()
        with (
            patch.dict(
                os.environ, {"NEMOCLAW_TAVILY_PREFLIGHT_KEY": secret}, clear=True
            ),
            patch.object(
                TAVILY_PREFLIGHT,
                "run_preflight",
                side_effect=TAVILY_PREFLIGHT.TavilyPreflightError(
                    "Tavily rejected the configured API key (HTTP 401)"
                ),
            ),
            patch("sys.stderr", stderr),
        ):
            self.assertEqual(1, TAVILY_PREFLIGHT.main([]))
        self.assertNotIn(secret, stderr.getvalue())


class HermesWebSearchConfigurationTest(TestCase):
    def run_generator(self, provider: str) -> tuple[dict, str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            home = Path(temp_dir)
            (home / ".hermes").mkdir()
            env = os.environ.copy()
            env.update(
                {
                    "HOME": str(home),
                    "NEMOCLAW_MODEL": "test/model",
                    "NEMOCLAW_INFERENCE_BASE_URL": "https://inference.local/v1",
                    "NEMOCLAW_MESSAGING_CHANNELS_B64": base64.b64encode(
                        json.dumps(["slack"]).encode()
                    ).decode(),
                    "NEMOCLAW_WEB_SEARCH_PROVIDER": provider,
                }
            )
            result = subprocess.run(
                [
                    "node",
                    "--experimental-strip-types",
                    str(HERMES_DIR / "generate-config.ts"),
                ],
                check=False,
                capture_output=True,
                env=env,
                text=True,
            )
            self.assertEqual(0, result.returncode, result.stderr)
            config = yaml.safe_load(
                (home / ".hermes" / "config.yaml").read_text(encoding="utf-8")
            )
            env_text = (home / ".hermes" / ".env").read_text(encoding="utf-8")
            return config, env_text

    def test_enabled_config_selects_tavily_and_writes_only_placeholder(self) -> None:
        config, env_text = self.run_generator("tavily")

        self.assertEqual({"backend": "tavily"}, config["web"])
        self.assertIn("search", config["platform_toolsets"]["slack"])
        self.assertNotIn("web", config["platform_toolsets"]["slack"])
        self.assertIn("search", config["platform_toolsets"]["api_server"])
        self.assertNotIn("web", config["platform_toolsets"]["api_server"])
        self.assertIn("TAVILY_API_KEY=openshell:resolve:env:TAVILY_API_KEY\n", env_text)

    def test_disabled_config_does_not_advertise_web_or_write_placeholder(self) -> None:
        config, env_text = self.run_generator("")

        self.assertNotIn("web", config)
        self.assertNotIn("search", config["platform_toolsets"]["slack"])
        self.assertNotIn("web", config["platform_toolsets"]["slack"])
        self.assertNotIn("api_server", config["platform_toolsets"])
        self.assertNotIn("TAVILY_API_KEY", env_text)


class WebSearchLifecycleContractTest(TestCase):
    def test_provider_policy_runtime_and_teardown_are_conditional(self) -> None:
        providers = (EXAMPLE_DIR / "scripts" / "02-providers.sh").read_text(
            encoding="utf-8"
        )
        sandbox = (EXAMPLE_DIR / "scripts" / "03-sandbox.sh").read_text(
            encoding="utf-8"
        )
        teardown = (EXAMPLE_DIR / "scripts" / "tear-down.sh").read_text(
            encoding="utf-8"
        )
        start = (HERMES_DIR / "start.sh").read_text(encoding="utf-8")

        self.assertIn('if [[ -n "${TAVILY_API_KEY:-}" ]]', providers)
        self.assertIn("tavily_search_preflight.py", providers)
        self.assertIn("nemoclaw-tavily-search", providers)
        self.assertIn("web_search_policy.py", sandbox)
        self.assertIn("$SANDBOX_NAME-tavily-search", sandbox)
        self.assertIn("NEMOCLAW_WEB_SEARCH_PROVIDER", sandbox)
        self.assertIn("$SANDBOX_NAME-tavily-search", teardown)
        self.assertIn("GITHUB_TOKEN TAVILY_API_KEY", start)

    def test_skill_forbids_every_direct_fetch_fallback(self) -> None:
        skill = (HERMES_DIR / "skills" / "public-web-search" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        soul = (HERMES_DIR / "SOUL.md").read_text(encoding="utf-8")

        self.assertIn("Use `web_search` only", skill)
        for blocked in ("web_extract", "browser", "web_fetch", "curl"):
            self.assertIn(blocked, skill)
        self.assertIn("Public web search is disabled", skill)
        self.assertIn("public-web-search", soul)
