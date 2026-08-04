# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import importlib.util
import io
import os
import socket
import subprocess
import sys
import tempfile
import urllib.error
from pathlib import Path
from unittest import TestCase
from unittest.mock import MagicMock, patch

SCRIPT = Path(__file__).parents[1] / "inference_preflight.py"
PROVIDERS_SCRIPT = SCRIPT.parent / "02-providers.sh"
SPEC = importlib.util.spec_from_file_location("inference_preflight", SCRIPT)
assert SPEC and SPEC.loader
PREFLIGHT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PREFLIGHT
SPEC.loader.exec_module(PREFLIGHT)


def http_error(status: int, body: bytes = b"") -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        url="https://example.test/v1/chat/completions",
        code=status,
        msg="test error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


class InferencePreflightTest(TestCase):
    def test_valid_configuration_uses_bounded_completion(self) -> None:
        response = MagicMock()
        response.status = 200
        response.read.return_value = (
            b'{"choices":[{"message":{"content":"OK"}}]}'
        )
        response.__enter__.return_value = response
        with patch.object(PREFLIGHT.urllib.request, "urlopen", return_value=response) as open_:
            PREFLIGHT.run_preflight(
                "https://example.test/v1", "nvidia/test-model", "secret", 4
            )

        request = open_.call_args.args[0]
        self.assertEqual(
            request.full_url, "https://example.test/v1/chat/completions"
        )
        self.assertEqual(open_.call_args.kwargs["timeout"], 4)
        self.assertNotIn("secret", request.full_url)

    def test_completion_url_preserves_query_parameters(self) -> None:
        self.assertEqual(
            PREFLIGHT.completion_url(
                "https://example.test/v1?api-version=2026-07-01"
            ),
            "https://example.test/v1/chat/completions?api-version=2026-07-01",
        )

    def test_remote_http_endpoint_is_rejected_before_network_call(self) -> None:
        with patch.object(PREFLIGHT.urllib.request, "urlopen") as open_:
            with self.assertRaisesRegex(
                PREFLIGHT.PreflightError, "remote inference endpoints must use HTTPS"
            ) as raised:
                PREFLIGHT.run_preflight(
                    "http://example.test/v1", "nvidia/test-model", "secret", 4
                )
        self.assertEqual(raised.exception.category, "endpoint")
        open_.assert_not_called()

    def test_loopback_http_endpoint_is_allowed(self) -> None:
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"choices":[{"message":{"content":"OK"}}]}'
        response.__enter__.return_value = response
        with patch.object(
            PREFLIGHT.urllib.request, "urlopen", return_value=response
        ) as open_:
            PREFLIGHT.run_preflight(
                "http://127.0.0.1:18080/v1", "nvidia/test-model", "secret", 4
            )

        self.assertEqual(
            open_.call_args.args[0].full_url,
            "http://127.0.0.1:18080/v1/chat/completions",
        )

    def test_missing_credential_is_configuration_failure(self) -> None:
        with self.assertRaisesRegex(PREFLIGHT.PreflightError, "credential is missing") as raised:
            PREFLIGHT.run_preflight(
                "https://example.test/v1", "nvidia/test-model", "", 4
            )
        self.assertEqual(raised.exception.category, "configuration")

    def test_invalid_credential_is_authentication_failure(self) -> None:
        with patch.object(
            PREFLIGHT.urllib.request, "urlopen", side_effect=http_error(401)
        ):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/test-model", "secret", 4
                )
        self.assertEqual(raised.exception.category, "authentication")
        self.assertNotIn("secret", str(raised.exception))

    def test_unavailable_model_is_model_access_failure(self) -> None:
        body = b'{"error":{"message":"Model does not exist"}}'
        with patch.object(
            PREFLIGHT.urllib.request, "urlopen", side_effect=http_error(404, body)
        ):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/missing", "secret", 4
                )
        self.assertEqual(raised.exception.category, "model-access")

    def test_missing_completion_route_is_endpoint_failure(self) -> None:
        with patch.object(
            PREFLIGHT.urllib.request,
            "urlopen",
            side_effect=http_error(404, b"page not found"),
        ):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/test-model", "secret", 4
                )
        self.assertEqual(raised.exception.category, "endpoint")

    def test_unreachable_endpoint_is_endpoint_failure(self) -> None:
        with patch.object(
            PREFLIGHT.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError(ConnectionRefusedError()),
        ):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/test-model", "secret", 4
                )
        self.assertEqual(raised.exception.category, "endpoint")

    def test_timeout_is_distinct_from_endpoint_failure(self) -> None:
        with patch.object(
            PREFLIGHT.urllib.request,
            "urlopen",
            side_effect=urllib.error.URLError(socket.timeout()),
        ):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/test-model", "secret", 4
                )
        self.assertEqual(raised.exception.category, "timeout")

    def test_provider_outage_is_availability_failure(self) -> None:
        with patch.object(
            PREFLIGHT.urllib.request, "urlopen", side_effect=http_error(503)
        ):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/test-model", "secret", 4
        )
        self.assertEqual(raised.exception.category, "provider-availability")

    def test_non_json_success_is_provider_response_failure(self) -> None:
        response = MagicMock()
        response.status = 200
        response.read.return_value = b"<html>proxy login</html>"
        response.__enter__.return_value = response
        with patch.object(PREFLIGHT.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/test-model", "secret", 4
                )
        self.assertEqual(raised.exception.category, "provider-response")

    def test_success_without_choice_is_provider_response_failure(self) -> None:
        response = MagicMock()
        response.status = 200
        response.read.return_value = b'{"choices":[]}'
        response.__enter__.return_value = response
        with patch.object(PREFLIGHT.urllib.request, "urlopen", return_value=response):
            with self.assertRaises(PREFLIGHT.PreflightError) as raised:
                PREFLIGHT.run_preflight(
                    "https://example.test/v1", "nvidia/test-model", "secret", 4
                )
        self.assertEqual(raised.exception.category, "provider-response")

    def test_display_endpoint_removes_credentials_and_query(self) -> None:
        self.assertEqual(
            PREFLIGHT.display_endpoint(
                "https://user:secret@example.test:8443/v1?api_key=secret"
            ),
            "https://example.test:8443/v1",
        )


class ProviderPhasePreflightTest(TestCase):
    def run_provider_phase(self, preflight: str) -> subprocess.CompletedProcess[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_openshell = Path(temp_dir) / "openshell"
            fake_python = Path(temp_dir) / "python3"
            fake_openshell.write_text(
                """#!/usr/bin/env bash
if [[ "$1 $2" == "settings get" ]]; then
  echo "providers_v2_enabled = true"
  exit 0
fi
if [[ "$1 $2" == "provider get" ]]; then
  exit 1
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_python.write_text(
                "#!/usr/bin/env bash\nexit 0\n",
                encoding="utf-8",
            )
            fake_openshell.chmod(0o755)
            fake_python.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{temp_dir}:{os.environ['PATH']}",
                "SLACK_BOT_TOKEN": "test-bot-token",
                "SLACK_APP_TOKEN": "xapp-test-app-token",
                "NEMOCLAW_INFERENCE_PREFLIGHT": preflight,
                "ATIF_EXPORT_MODE": "local",
            }
            environment.pop("OPENAI_API_KEY", None)
            environment.pop("COMPATIBLE_API_KEY", None)
            return subprocess.run(
                ["bash", str(PROVIDERS_SCRIPT)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

    def test_missing_credential_stops_provider_phase_by_default(self) -> None:
        result = self.run_provider_phase("1")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("credential", result.stderr)
        self.assertIn("intentional offline setup", result.stderr)

    def test_explicit_bypass_allows_intentional_offline_setup(self) -> None:
        result = self.run_provider_phase("0")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("preflight bypassed", result.stderr)

    def test_preflight_preserves_proxy_and_ca_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fake_openshell = Path(temp_dir) / "openshell"
            network_log = Path(temp_dir) / "network-env.log"
            fake_python = Path(temp_dir) / "python3"
            fake_openshell.write_text(
                """#!/usr/bin/env bash
if [[ "$1 $2" == "settings get" ]]; then
  echo "providers_v2_enabled = true"
  exit 0
fi
if [[ "$1 $2" == "provider get" ]]; then
  exit 1
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_python.write_text(
                f"""#!/usr/bin/env bash
if [[ "$1" == *"inference_preflight.py" ]]; then
  printf '%s\\n' "${{HTTPS_PROXY:-}}|${{NO_PROXY:-}}|${{SSL_CERT_FILE:-}}|${{SSL_CERT_DIR:-}}" > "{network_log!s}"
fi
exit 0
""",
                encoding="utf-8",
            )
            fake_openshell.chmod(0o755)
            fake_python.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{temp_dir}:{os.environ['PATH']}",
                "COMPATIBLE_API_KEY": "test-inference-key",
                "NEMOCLAW_INFERENCE_PREFLIGHT": "1",
                "NEMOCLAW_ENDPOINT_URL": "https://example.test/v1",
                "SLACK_BOT_TOKEN": "test-bot-token",
                "SLACK_APP_TOKEN": "test-app-token",
                "ATIF_EXPORT_MODE": "local",
                "HTTPS_PROXY": "http://proxy.example.test:8080",
                "NO_PROXY": "127.0.0.1,localhost",
                "SSL_CERT_FILE": "/etc/example/ca.pem",
                "SSL_CERT_DIR": "/etc/example/certs",
            }
            environment.pop("OPENAI_API_KEY", None)
            result = subprocess.run(
                ["bash", str(PROVIDERS_SCRIPT)],
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(
                network_log.read_text(encoding="utf-8").strip(),
                "http://proxy.example.test:8080|127.0.0.1,localhost|"
                "/etc/example/ca.pem|/etc/example/certs",
            )
