#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Contract: HPA helper reports 8 GPUs; 0/0 polls are not treated as 8."""

from __future__ import annotations

import importlib.util
import asyncio
import inspect
import json
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "e2e-openclaw-ollama-load-test.py"
spec = importlib.util.spec_from_file_location("e2e_openclaw_ollama_load_test", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
reached = mod.hpa_replicas_reached_target

assert reached(0, 0, 8) is False, "failed HPA poll must not look like 8 GPUs"
assert reached(1, 1, 8) is False
assert reached(7, 7, 8) is False
assert reached(7, 8, 8) is True, "desired 8 is at the demo target"
assert reached(8, 7, 8) is True
assert reached(8, 8, 8) is True
assert reached(2, 3, 8) is False
assert mod.hpa_effective_replicas(0, 0) == 0
assert mod.hpa_stop_new_chats_at(8) == 8
assert mod.hpa_should_stop_new_chats(0, 0, 8) is False
assert mod.hpa_should_stop_new_chats(6, 6, 8) is False
assert mod.hpa_should_stop_new_chats(7, 7, 8) is False
assert mod.hpa_should_stop_new_chats(7, 8, 8) is True
assert mod.hpa_should_stop_new_chats(8, 8, 8) is True
assert mod.hpa_replicas_back_to_one(0, 0) is False
assert mod.hpa_replicas_back_to_one(1, 1) is True
assert mod.hpa_replicas_back_to_one(2, 1) is False

hold = mod.should_stop_after_hold
stop_now, since = hold(False, 60, None, 10.0)
assert stop_now is False
assert since is None
stop_now, since = hold(True, 60, None, 10.0)
assert stop_now is False
assert since == 10.0
stop_now, _since = hold(True, 60, 10.0, 69.9)
assert stop_now is False
stop_now, _since = hold(True, 60, 10.0, 70.0)
assert stop_now is True
stop_now, _since = hold(True, 0, None, 10.0)
assert stop_now is True

import subprocess
import sys

missing_host = subprocess.run(
    [sys.executable, str(SCRIPT), "--users", "1", "--output", "/tmp/e2e-openclaw-host-required"],
    check=False,
    capture_output=True,
    text=True,
)
assert missing_host.returncode == 2, missing_host.stderr
assert "in-sandbox load helpers" in missing_host.stderr
assert "KILL_OPENCLAW_EXEC" in mod.KILL_SANDBOX_HELPERS
assert "[e]2e-openclaw-load" in mod.KILL_SANDBOX_HELPERS
assert 'or "nemoclaw-start" in cmd' in mod.KILL_SANDBOX_HELPERS
assert "INTERRUPT_OPENCLAW_INFLIGHT" not in SCRIPT.read_text()
assert "interrupt_openclaw_inflight" not in SCRIPT.read_text()
assert "[o]penclaw gateway run" not in SCRIPT.read_text()
source = inspect.getsource(mod.stop_sandbox_chats)
assert "kill_sandbox_load_helpers" in source
assert "interrupt_openclaw_inflight" not in source
start_source = inspect.getsource(mod.run_test)
assert "kill_sandbox_load_helpers" in start_source
assert "interrupt_openclaw_inflight" not in start_source
assert "prune_stale_openclaw_sessions" not in start_source
assert "publish_ramp_to_sandboxes" not in start_source
assert "e2e_latency_load_ramp" not in SCRIPT.read_text()
assert "clear_ramp_from_sandboxes" not in SCRIPT.read_text()
assert "Each user sends chats to that user's sandbox." not in start_source
# Start must not restart the gateway (that races the max_tokens pin).
start_only = start_source.split("print(\"=\" * 70)", 1)[0]
assert "setup-openclaw-ollama-e2e-sandboxes.sh" not in start_only
try:
    asyncio.run(mod.simulate_user())
except RuntimeError as exc:
    assert "does not copy load helpers" in str(exc)
else:
    raise AssertionError("simulate_user must not copy e2e-openclaw-load into sandboxes")
chart = Path(__file__).resolve().parent.parent
helper = (chart / "files" / "openclaw-e2e-ws-prompt.py").read_text()
assert 'os.environ.get("E2E_DRAIN_SEC")' in helper
assert 'os.environ.get("E2E_PROMPT_TIMEOUT_SEC")' in helper
assert 'os.environ.get("E2E_DRAIN_SEC", "0")' not in helper
assert 'os.environ.get("E2E_DRAIN_SEC", "8")' not in helper
assert "return 2, 0" in helper
assert 'event_payload.get("state") == "final"' in helper
assert "if answer and send_id and send_id not in pending:" not in helper
assert "E2E_CHATS_PER_USER" not in helper
assert "CHATS" not in helper.split("MAX_TOKENS")[0]
assert '"maxTokens": _max_tokens()' not in helper
assert 'send_params["maxTokens"]' not in helper
assert "pause = 0.0" in helper
assert "def _max_tokens()" in helper
assert "Do not use tools." in helper
assert 'f"{session_base}:w{wid}"' in helper
assert ":t{turn}" not in helper
assert '"sessions.delete"' in helper
assert "_read_latency_ramp" not in helper
assert "E2E_LATENCY_RAMP" not in helper
assert "def _replica_count()" in helper
assert "_replica_count() >= 6" in helper
assert "def _latency_metric()" in helper
assert "_latency_metric() and _replica_count() >= 6" in helper
assert "pin_short_max_tokens_for_demo" not in SCRIPT.read_text()
assert "hpa_common_set_dcgm_peak_window 15" in SCRIPT.read_text()
pin_src = (chart / "files" / "pin-openclaw-ollama-model.py").read_text()
assert '"write"' in pin_src
assert '"read"' in pin_src
assert '"edit"' in pin_src
assert '"agents" / "main" / "sessions"' in pin_src
assert "import shutil" in pin_src
assert 'maint["maxEntries"] = 100000' in pin_src
assert 'maint["mode"] = "warn"' in pin_src
assert 'tools["profile"] = "minimal"' in pin_src
agent_common = (chart / "scripts" / "agent-common.sh").read_text()
assert "PIN_RESET_SESSIONS" not in agent_common
assert "agent_common_repin_openclaw_max_tokens" not in agent_common
assert '"write"' in agent_common
assert 'maint["maxEntries"] = 100000' in agent_common
assert "openclaw) raw=2048" in agent_common
assert 'openclaw) echo "onprem-openclaw"' in agent_common
uninstall = (chart / "scripts" / "uninstall-e2e.sh").read_text()
assert "onprem-openclaw" in uninstall
assert "onprem-ollama" not in uninstall
hermes_setup = (chart / "scripts" / "setup-hermes-vllm-e2e-sandboxes.sh").read_text()
assert "prepare_hermes_sandbox_home" in hermes_setup
assert 'os.chmod("/sandbox", 0o755)' in hermes_setup
assert 'os.chown("/sandbox/.nemoclaw", 0, 0)' in hermes_setup or 'os.chown(home, 0, 0)' in hermes_setup
assert 'os.chmod(home, 0o755)' in hermes_setup
assert "503 gateway_draining" in hermes_setup
assert 'os.chmod("/sandbox/.hermes", 0o700)' in hermes_setup
assert "start exited early (attempt" in hermes_setup
assert "agent_common_pin_hermes_model" not in hermes_setup
hermes_load = (chart / "scripts" / "e2e-hermes-load-test.py").read_text()
assert '"-m"' in hermes_load
assert "inference_model()" in hermes_load
assert 'raw="${E2E_LATENCY_TOKEN_START:-2048}"' in agent_common
assert 'raw="${E2E_HERMES_LATENCY_TOKEN_START:-2048}"' in agent_common
assert 'raw="${E2E_DEEPAGENTS_LATENCY_TOKEN_START:-1024}"' in agent_common
assert "*latency*)" in agent_common
assert "INFLIGHT=1" in agent_common.split("agent_common_export_demo_workload")[1].split("agent_common_export_client_inflight")[0]
assert 'INFLIGHT="${E2E_HERMES_LATENCY_INFLIGHT:-1}"' in agent_common
assert 'INFLIGHT="${E2E_DEEPAGENTS_LATENCY_INFLIGHT:-1}"' in agent_common
assert "agent_common_export_demo_workload deepagents" in (chart / "scripts" / "client_deepagents.sh").read_text()
assert "Leftover MAX_TOKENS from GPU util must not change the latency demo." in agent_common
assert "agent_common_export_demo_workload hermes" in (chart / "scripts" / "client_hermes.sh").read_text()
discovery = (chart / "files" / "e2e-http-discovery.py").read_text()
assert 'E2E_PUBLISH_BIND' in discovery
assert 'return "127.0.0.1"' in discovery
assert 'ThreadingHTTPServer(("0.0.0.0"' not in discovery
shortcut = (chart / "files" / "e2e-openclaw-ui-shortcut.py").read_text()
assert 'E2E_PUBLISH_BIND' in shortcut
assert 'sock.bind(("0.0.0.0"' not in shortcut
forward = (chart / "scripts" / "remote-http-clients.sh").read_text()
hermes_ui_proxy = (chart / "files" / "e2e-hermes-ui-host-proxy.py").read_text()
assert "rewrite_host_header" in hermes_ui_proxy
assert 'sock.bind(("0.0.0.0"' not in hermes_ui_proxy
assert "remote_http_start_hermes_ui_proxy" in forward
assert "remote_http_start_hermes_api_proxy" in forward
assert "remote_http_prepare_hermes_home" in forward
assert "os.chown(home, 0, 0)" in forward
assert "E2E_HERMES_API_KEY_FILE" in forward
assert "inner_api=$((28642 + i))" in forward
assert "remote_http_stop_ports_for_count" in forward
assert "seq 18789 18799" not in forward
assert "seq 8642 8652" not in forward
assert 'remote_http_start_forward "${name}" 18789 "${inner}"' in forward.split("remote_http_publish_hermes")[1]
assert "Laptop HTTP does not set a Bearer token." in forward
hermes_api_proxy = (chart / "files" / "e2e-hermes-api-auth-proxy.py").read_text()
assert "E2E_HERMES_API_KEY_FILE" in hermes_api_proxy
assert "inject_authorization" in hermes_api_proxy
assert "sys.argv[4]" not in hermes_api_proxy
ha_spec = importlib.util.spec_from_file_location(
    "e2e_hermes_api_auth_proxy", chart / "files" / "e2e-hermes-api-auth-proxy.py"
)
assert ha_spec and ha_spec.loader
ha = importlib.util.module_from_spec(ha_spec)
ha_spec.loader.exec_module(ha)
injected = ha.inject_authorization(
    b"POST /v1/chat/completions HTTP/1.1\r\nHost: 10.184.164.109:8642\r\n\r\n",
    "SECRET",
)
assert b"Authorization: Bearer SECRET" in injected
assert b"Host: 10.184.164.109:8642" in injected
hp_spec = importlib.util.spec_from_file_location(
    "e2e_hermes_ui_host_proxy", chart / "files" / "e2e-hermes-ui-host-proxy.py"
)
assert hp_spec and hp_spec.loader
hp = importlib.util.module_from_spec(hp_spec)
hp_spec.loader.exec_module(hp)
rewritten = hp.rewrite_host_header(
    b"GET / HTTP/1.1\r\nHost: 10.184.164.109:18789\r\nAccept: text/html",
    b"127.0.0.1:18789",
)
assert b"Host: 127.0.0.1:18789" in rewritten
assert b"10.184.164.109" not in rewritten
assert "E2E_PUBLISH_BIND:-127.0.0.1" in forward
assert 'E2E_PUBLISH_BIND:-0.0.0.0' in forward
assert "E2E_OPENCLAW_GATEWAY_TOKEN_FILE" in forward
assert '"token": sys.argv[7]' not in forward
assert "Location: /#token=" not in shortcut
assert "sys.argv[4]" not in shortcut
assert "settimeout(None)" in shortcut
assert "up.join(timeout=120)" not in shortcut
disc_spec = importlib.util.spec_from_file_location(
    "e2e_http_discovery", chart / "files" / "e2e-http-discovery.py"
)
assert disc_spec and disc_spec.loader
disc = importlib.util.module_from_spec(disc_spec)
disc_spec.loader.exec_module(disc)
redacted = disc.redact_secrets(
    {
        "users": [
            {
                "user_id": 0,
                "token": "SECRET",
                "api_key": "SECRET",
                "dashboard_url": "http://127.0.0.1:18789/u/0#token=SECRET",
            }
        ]
    }
)
redacted_text = json.dumps(redacted)
assert "SECRET" not in redacted_text
assert "token" not in redacted_text
sc_spec = importlib.util.spec_from_file_location(
    "e2e_openclaw_ui_shortcut", chart / "files" / "e2e-openclaw-ui-shortcut.py"
)
assert sc_spec and sc_spec.loader
sc = importlib.util.module_from_spec(sc_spec)
sc_spec.loader.exec_module(sc)
injected = sc.inject_connect_token(
    b'{"type":"req","method":"connect","params":{"auth":{"token":""}}}',
    "SECRET",
)
assert b"SECRET" in injected
assert sc._is_websocket_upgrade(
    b"GET / HTTP/1.1\r\nHost: x\r\nUpgrade: websocket\r\n\r\n"
)
assert not sc._is_websocket_upgrade(
    b"GET /assets/app.js HTTP/1.1\r\nHost: x\r\n\r\n"
)
dash = (chart / "scripts" / "openclaw-dashboard-url.sh").read_text()
assert "#token=" not in dash
client = (chart / "scripts" / "client.sh").read_text()
assert "trap '_client_finish' EXIT" in client
assert 'exit "${load_rc}"' in client
hermes = (chart / "scripts" / "client_hermes.sh").read_text()
assert 'headers["Authorization"] = f"Bearer {token}"' in hermes
assert "export E2E_OUTPUT_DIR" in hermes
deep = (chart / "scripts" / "client_deepagents.sh").read_text()
assert "agent_common_print_laptop_client_usage" not in deep
assert "Deep Agents has no laptop HTTP" in deep
assert 'E2E_CLIENT_HOST:-' in deep
common = (chart / "scripts" / "agent-common.sh").read_text()
assert "client_deepagents.sh)" in common
assert 'script="$(basename "${0}")"' in common
assert "hermes vllm nvidia/NVIDIA-Nemotron-3-Nano-4B-FP8" in common
assert "deepagents nim nvidia/nemotron-3-nano" in common
readme = (chart / "README.md").read_text()
assert "`secrets.env` is gitignored." in readme
assert "Keep [step 5](#5-connect-the-openshell-cli) in another terminal:" in readme
publish_hermes = (chart / "scripts" / "publish-hermes-remote-http.sh").read_text()
assert "remote_http_publish_hermes" in publish_hermes
assert "Does not print API keys." in publish_hermes
assert "publish-hermes-remote-http.sh" in readme
assert "The laptop does not set a Hermes API key." in readme
assert "broken pipe" in readme
assert "not a failed OpenShell tunnel" in readme
forward_sh = (chart / "scripts" / "openshell-port-forward.sh").read_text()
assert "kubectl may print broken pipe" in forward_sh
assert "Git has `secrets.env.example` only." in readme
assert "kubectl get secret ngc-registry -n nemoclaw-gpu" in readme
assert "If that Secret exists, skip `apply-local-secrets.sh`." in readme
assert "## Simple HPA-only test (optional)" in readme
assert "[Simple HPA-only test (optional)](#simple-hpa-only-test-optional)" in readme
assert "Simple HPA only test" not in readme
assert "DCGM_NAMESPACE=gpu-operator-resources MAX_REPLICAS=8" in readme
assert "It is a one-shot through the in-sandbox" in readme
assert "#token=" in readme and "with no `#token=`" in readme
assert "hermes nim nvidia/nemotron-3-nano" not in common
assert 'E2E_CLIENT_HOST' in common
dgx = (chart / "scripts" / "hpa-load-test-dgx-8xh100.sh").read_text()
assert "ingress.auth.password" in dgx
assert "--force-conflicts" in dgx
adapter = (chart / "monitoring" / "prometheus-adapter-gpu-values.yaml").read_text()
assert "[90s]" in adapter
assert "client.sh shortens this to 15s" in adapter
assert "stabilizationWindowSeconds=120" not in (chart / "scripts" / "hpa-common.sh").read_text()
hpa_common = (chart / "scripts" / "hpa-common.sh").read_text()
assert "hpa_common_resolve_allow_insecure_http" in hpa_common
assert "Unset inherits the live chart" in hpa_common
assert "ALLOW_INSECURE_HTTP=1 ./scripts/agentscaling_gpuutil.sh" not in readme
assert "ALLOW_INSECURE_HTTP=1 ./scripts/agentscaling_latency.sh" not in readme
assert "ALLOW_INSECURE_HTTP=1 ./scripts/agentscaling_hermes_gpuutil.sh" not in readme
assert "ALLOW_INSECURE_HTTP=1 ./scripts/agentscaling_deepagents_gpuutil.sh" not in readme
assert "ALLOW_INSECURE_HTTP=1 \\\n  ./scripts/install-hpa.sh" not in readme
assert "ALLOW_INSECURE_HTTP=1" not in readme
assert "TLS required by default" not in readme
assert "### TLS values" not in readme
assert "This recipe does not use Envoy TLS." in readme
assert "OpenShell client mTLS is step 5." in readme
gw = (chart / "templates" / "gateway.yaml").read_text()
assert "protocol: HTTPS" not in gw
assert "ingress.tls is empty and ingress.allowInsecureHttp is false" not in gw
assert "TLS is required when ENABLE_ENVOY_LB=1" not in (
    chart / "scripts" / "install-hpa.sh"
).read_text()
assert 'export ALLOW_INSECURE_HTTP="${ALLOW_INSECURE_HTTP:-0}"' not in (chart / "scripts" / "agentscaling-common.sh").read_text()
assert 'export ALLOW_INSECURE_HTTP="${ALLOW_INSECURE_HTTP:-0}"' not in (chart / "scripts" / "agentscaling-hermes-common.sh").read_text()
assert 'export ALLOW_INSECURE_HTTP="${ALLOW_INSECURE_HTTP:-0}"' not in (chart / "scripts" / "agentscaling-deepagents-common.sh").read_text()
hold_disp = hpa_common.split("def hold_display_current")[1].split("def gpu_display_current")[0]
assert "if pods:" in hold_disp
assert "age > 45" not in hold_disp
assert "int(replicas) > 1" not in hold_disp
assert "int(replicas) <= 1" in hold_disp
assert 'hold_display_current("gpu_utilization_percent"' in hpa_common
assert 'hold_display_current("nemoclaw_llm_latency_avg_milliseconds"' in hpa_common
assert "fmt_ms(latency_display_current" in hpa_common
fmt_ms = hpa_common.split("def fmt_ms")[1].split("def fmt_rate")[0]
assert 'return "?"' not in fmt_ms
assert 'return "0"' in fmt_ms
assert "0.0 if value is None else value" in hpa_common
gateway = (chart / "templates" / "gateway.yaml").read_text()
assert "maxRequestsPerConnection: 1" in gateway
assert "hpa_common_set_dcgm_peak_window" in hpa_common
assert "sys.exit(2)" in hpa_common
assert "hpa_common_set_dcgm_peak_window 90" in client
assert "hpa_common_set_dcgm_peak_window 15" in client
assert "Restarting OpenClaw so max_tokens=" not in client
assert "hold_hpa_until_client" not in client
assert "hold_hpa_until_client" not in hermes
assert "hold_hpa_until_client" not in deep
assert "pause_hpa_scale_down" not in hermes
assert "pause_hpa_scale_down" not in deep
assert "kubectl cp" not in hermes_load
assert "e2e-sandbox-saturate" not in hermes_load
assert "e2e-openclaw-load" not in hermes_load
assert "does not copy a load helper into the sandbox" in hermes_load
deep_load = (chart / "scripts" / "e2e-deepagents-load-test.py").read_text()
assert "kubectl cp" not in deep_load
assert "e2e-sandbox-saturate" not in deep_load
assert "e2e-openclaw-load" not in deep_load
assert "does not copy a load helper into the sandbox" in deep_load
assert hermes_load.count("stop_sandbox_chats(") >= 3
assert "[h]ermes.real -m .* -z" in hermes_load
assert "[h]ermes -z'" not in hermes_load
assert deep_load.count("stop_sandbox_chats(") >= 3
assert "`INFLIGHT=1`, `MAX_TOKENS=2048`" in readme
assert "OpenClaw latency defaults: `INFLIGHT=1`, `MAX_TOKENS=2048`" in readme
assert "mean of **completed** samples in the last **30s**" in readme
assert "no new completed sample for 15s" in readme
assert "OpenClaw, Hermes, and Deep Agents share this metric" in readme
assert "That 0 lets HPA scale down. It does not mean chat latency was 0 ms." in readme
assert "Hermes latency is `INFLIGHT=1`, `MAX_TOKENS=2048` in the code" in readme
assert "Do not add those flags." in readme
assert "INFLIGHT=1 MAX_TOKENS=2048" in hermes
assert "INFLIGHT=2 MAX_TOKENS=1024" in hermes
assert "INFLIGHT=2 MAX_TOKENS=1024" in readme
assert "INFLIGHT=4 MAX_TOKENS=2048" in readme
assert "INFLIGHT=4 MAX_TOKENS=2048" in client
assert "openclaw) INFLIGHT=4 ;;" in agent_common
assert 'export E2E_USERS="${E2E_USERS:-10}"' in hermes
assert 'parser.add_argument("--users", type=int, required=True)' in hermes_load
assert 'parser.add_argument("--users", type=int, required=True)' in SCRIPT.read_text()
assert 'parser.add_argument("--users", type=int, required=True)' in deep_load
assert 'default=int(os.environ.get("E2E_USERS"' not in hermes_load
assert 'default=int(os.environ.get("E2E_USERS"' not in SCRIPT.read_text()
assert 'default=int(os.environ.get("E2E_USERS"' not in deep_load
assert 'export E2E_USERS="${E2E_USERS:-10}"' in (chart / "scripts" / "agentscaling-hermes-common.sh").read_text()
assert 'export E2E_USERS="${E2E_USERS:-10}"' in publish_hermes
assert 'export E2E_USERS="${E2E_USERS:-5}"' in client
assert "10 end users send requests to 10 Hermes agents" in readme
assert "5 end users send requests to 5 OpenClaw agents" in readme
assert "10 end users send requests to 10 Deep Agents" in readme
assert 'export E2E_USERS="${E2E_USERS:-10}"' in (chart / "scripts" / "agentscaling-deepagents-common.sh").read_text()
assert 'export E2E_USERS="${E2E_USERS:-10}"' in deep
assert "`E2E_USERS=10`" in readme
assert "`8642+i`" in readme
assert "`18789+i`" in readme
assert "Last ports are `8642+N-1`" in readme
assert ":8642 … :8646" not in readme
assert "INFLIGHT=1 MAX_TOKENS=1024" in readme
assert "INFLIGHT=1 MAX_TOKENS=1024" in deep
assert "INFLIGHT=1 MAX_TOKENS=1024" not in hermes
assert "INFLIGHT=3 MAX_TOKENS=64" not in readme
assert "Default is `INFLIGHT=1 MAX_TOKENS=1024` for GPU util and for latency" in readme
assert "INFLIGHT=1 MAX_TOKENS=1024 E2E_USERS=10 ./scripts/client_deepagents.sh" not in readme
assert "INFLIGHT=1 MAX_TOKENS=2048 E2E_USERS=5 ./scripts/client_deepagents.sh" not in readme
assert "E2E_USERS=5 ./scripts/client_deepagents.sh" not in readme
for line in readme.splitlines():
    stripped = line.lstrip()
    if stripped.startswith("#") or not stripped.startswith(
        ("INFLIGHT=", "MAX_TOKENS=", "E2E_USERS=", "E2E_CLIENT_HOST=")
    ):
        continue
    if "client_deepagents.sh" not in stripped:
        continue
    assert "INFLIGHT=" not in stripped, stripped
    assert "MAX_TOKENS=" not in stripped, stripped
assert "deepagents) INFLIGHT=1 ;;" in agent_common
assert "Set those flags on the client." in readme
assert "[user {uid} sandbox {uid}]" in hermes
assert "thread.join(timeout=2)" not in hermes
assert "already-sent chats finished" in hermes
assert "already-sent chats finished" in hermes_load
assert "already-sent chats finished" in deep_load
assert "Do not drain in-flight" not in client
assert 'E2E_DRAIN_SEC:-${E2E_PROMPT_TIMEOUT_SEC' in client
assert "INFLIGHT=${INFLIGHT} MAX_TOKENS=${MAX_TOKENS}" in agent_common
assert "Restarting idle OpenClaw" not in client
assert "MAX_REPLICAS_HOLD_SEC:-0" in client
assert "E2E_CHAT_PAUSE_SEC:-0" in client
assert "agent_common_export_demo_workload" in client
assert '--scale-down-wait-loops "${SCALE_DOWN_WAIT_LOOPS}"' in client
assert "--scale-down-wait-loops 0" not in client
assert "Successful chats = chats that got a reply" in SCRIPT.read_text()
assert "resume_hpa_scale_down_for_demo" in SCRIPT.read_text()
assert "wait_sec=float(timeout_sec) + 5.0" not in SCRIPT.read_text()
assert "join_deadline = time.monotonic() + max(0.0, drain)" in helper
assert "max(timeout, drain)" not in helper
assert 'stabilizationWindowSeconds","value":0' in hpa_common.replace(" ", "")
assert "--chats" not in client
assert "E2E_CHATS_PER_USER" not in client
assert "E2E_CHATS_PER_USER" not in common
assert "E2E_USER_STAGGER_SEC:-0" in client
assert "*latency*" in client
assert '"maxReplicas":1' not in client.split("_client_finish")[1].split("trap ")[0]
finish = client.split("_client_finish")[1].split("trap ")[0]
assert "setup-openclaw-ollama-e2e-sandboxes.sh\" stop" not in finish
assert "SKIP_WAIT_INFERENCE_LOCAL=1" not in finish
assert "uninstall-e2e.sh" in client
assert "SKIP_WAIT_INFERENCE_LOCAL" in (chart / "scripts" / "setup-openclaw-ollama-e2e-sandboxes.sh").read_text()
for name, text in (
    ("client.sh", client),
    ("client_hermes.sh", hermes),
    ("client_deepagents.sh", deep),
):
    assert "e2e-sandboxes.sh" not in text, name
    assert "Restarting idle" not in text, name
    assert "uninstall-e2e.sh" in text, name
assert 'os.environ.get("INFLIGHT")' in hermes
assert "inflight=inflight" in hermes
assert "MAX_REPLICAS_HOLD_SEC:-0" in hermes
print("OK: HPA helper reports the 8 GPU target without treating a failed poll as 8")
print("OK: OpenClaw client requires --host and does not start in-sandbox helpers")
print("OK: client stop kills leftover helpers and leaves agents running")
print("OK: WS helper counts a reply as ok and a sent chat with no reply as err")
assert "e2e_timeline" in (chart / "scripts" / "e2e-openclaw-ollama-load-test.py").read_text()
assert "client-timeline.jsonl" in (chart / "scripts" / "e2e-openclaw-ollama-load-test.py").read_text()
assert "e2e-hpa-timeline.py" in (chart / "scripts" / "agent-common.sh").read_text()
print("OK: inner forwards bind 127.0.0.1; remote publish binds 0.0.0.0 unless E2E_PUBLISH_BIND is set")
print("OK: published HTTP and argv do not include gateway tokens or API keys")
print("OK: client cleanup, Hermes Bearer, pairings, and Helm restore match review fixes")
