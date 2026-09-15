#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

node --check "$ROOT/extension/service-worker.js"
node --check "$ROOT/extension/auth-session.js"
node --check "$ROOT/extension/sidepanel.js"
bash -n "$ROOT/scripts/check-connection.sh"
bash -n "$ROOT/scripts/check-brev-host.sh"
bash -n "$ROOT/scripts/prepare-brev-gateway.sh"
bash -n "$ROOT/scripts/onboard.sh"
bash -n "$ROOT/scripts/configure-brev-nginx.sh"
grep -Fq 'io.containerd.snapshotter.v1' "$ROOT/scripts/onboard.sh"
grep -Fq 'openshell sandbox list' "$ROOT/scripts/onboard.sh"
grep -Fq 'Loopback development connection is ready' "$ROOT/scripts/check-connection.sh"
grep -Fq 'status.get("auth_required") is not False' "$ROOT/scripts/check-connection.sh"
grep -Fq 'X-Hermes-Session-Token' "$ROOT/scripts/check-connection.sh"
grep -Fq 'nemoclaw-managed-gateway.json' "$ROOT/scripts/onboard.sh"
grep -Fq 'NEMOCLAW_OPENSHELL_GATEWAY_CONTAINER_PATCH' "$ROOT/scripts/onboard.sh"
grep -Fq '/etc/nemoclaw/gateway-management.env' "$ROOT/scripts/onboard.sh"
grep -Fq 'unset NEMOCLAW_OPENSHELL_GATEWAY_STATE_DIR' "$ROOT/scripts/onboard.sh"
grep -Fq 'unset OPENSHELL_LOCAL_TLS_DIR' "$ROOT/scripts/onboard.sh"
grep -Fq 'HERMES_DOCKERFILE="$NEMOCLAW_SOURCE/agents/hermes/Dockerfile"' "$ROOT/scripts/onboard.sh"
grep -Fq -- '--from "$HERMES_DOCKERFILE"' "$ROOT/scripts/onboard.sh"
grep -Fq 'Omitting --from selects the stock managed' "$ROOT/scripts/onboard.sh"
grep -Fq 'Releasing %d existing Ask NemoClaw host forward(s) before recreation' "$ROOT/scripts/onboard.sh"
grep -Fq 'Removing existing example sandbox' "$ROOT/scripts/onboard.sh"
grep -Fq '"$NEMOHERMES_BIN" "$SANDBOX_NAME" destroy -y' "$ROOT/scripts/onboard.sh"
grep -Fq 'ONBOARD_ARGS+=(--fresh)' "$ROOT/scripts/onboard.sh"
grep -Fq 'scripts/build-extension-release.py' "$ROOT/README.md"
grep -Fq 'nemoclaw status' "$ROOT/README.md"
grep -Fq 'Kubernetes deployment exposes Hermes through an authenticated HTTPS ingress' \
  "$ROOT/README.md"
grep -Fq 'shutil.copytree(origin, destination, dirs_exist_ok=True)' \
  "$ROOT/scripts/prepare-hermes-image.py"
grep -Fq 'supports_vision = true' "$ROOT/scripts/prepare-hermes-image.py"
if "$ROOT/scripts/check-connection.sh" 'https://hermes.example.com/path' >/dev/null 2>&1; then
  printf 'connection checker accepted a URL path instead of an exact origin\n' >&2
  exit 1
fi
node "$ROOT/tests/test_sidepanel_parsing.js"
node "$ROOT/tests/test_auth_session.js"
node "$ROOT/tests/test_service_worker.js"
node "$ROOT/tests/test_authenticated_fetch.js"
"$PYTHON_BIN" "$ROOT/tests/test_dashboard_auth_helper.py" -v
"$PYTHON_BIN" "$ROOT/tests/test_dashboard_public_url_helper.py" -v
"$PYTHON_BIN" "$ROOT/tests/test_plugin_api.py" -v
"$PYTHON_BIN" "$ROOT/scripts/configure-extension.py" \
  --output "$ROOT/build/portable-verification-extension"
"$PYTHON_BIN" "$ROOT/scripts/configure-extension.py" \
  --hermes-origin https://hermes.example.com \
  --output "$ROOT/build/verification-extension"
"$PYTHON_BIN" "$ROOT/scripts/configure-extension.py" \
  --hermes-origin http://127.0.0.1:18789 \
  --output "$ROOT/build/loopback-verification-extension"
"$PYTHON_BIN" "$ROOT/scripts/configure-extension.py" \
  --hermes-origin https://nemoclaw.example.com \
  --service-path /ask-nemoclaw \
  --dashboard-path / \
  --output "$ROOT/build/brev-verification-extension"
"$PYTHON_BIN" "$ROOT/scripts/build-extension-release.py" --check
test -s "$ROOT/build/verification-extension/manifest.json"
test -s "$ROOT/build/verification-extension/config.js"
test -s "$ROOT/build/portable-verification-extension/manifest.json"
test -s "$ROOT/build/portable-verification-extension/auth-session.js"
"$PYTHON_BIN" -c 'import json,sys; assert json.load(open(sys.argv[1]))["host_permissions"] == []' \
  "$ROOT/build/portable-verification-extension/manifest.json"
"$PYTHON_BIN" -c 'import json,sys; assert "cookies" in json.load(open(sys.argv[1]))["permissions"]' \
  "$ROOT/build/portable-verification-extension/manifest.json"
grep -Fq 'hermesOrigin: ""' "$ROOT/build/portable-verification-extension/config.js"
test -s "$ROOT/build/loopback-verification-extension/manifest.json"
grep -Fq 'servicePath: "/ask-nemoclaw"' "$ROOT/build/brev-verification-extension/config.js"
grep -Fq 'dashboardPath: "/"' "$ROOT/build/brev-verification-extension/config.js"
grep -Fq 'listen 0.0.0.0:__PROXY_PORT__' "$ROOT/deploy/nginx/ask-nemoclaw-server.conf"
grep -Fq 'server_name __PUBLIC_HOST__' "$ROOT/deploy/nginx/ask-nemoclaw-server.conf"
grep -Fq 'proxy_set_header Host __PUBLIC_HOST__' "$ROOT/deploy/nginx/ask-nemoclaw-server.conf"
grep -Fq 'proxy_set_header Origin __PUBLIC_URL__' "$ROOT/deploy/nginx/ask-nemoclaw-server.conf"
grep -Fq 'NEMOCLAW_DASHBOARD_PORT' "$ROOT/scripts/configure-brev-nginx.sh"
grep -Fq 'NEMOCLAW_BREV_PROXY_PORT' "$ROOT/scripts/configure-brev-nginx.sh"
grep -Fq 'NEMOCLAW_PUBLIC_URL' "$ROOT/scripts/configure-brev-nginx.sh"
grep -Fq 'sudo -n nginx -t' "$ROOT/scripts/configure-brev-nginx.sh"
if grep -Eq 'sudo[[:space:]]+(ss|test|cp|install|nginx|rm|systemctl)' \
  "$ROOT/scripts/configure-brev-nginx.sh" "$ROOT/scripts/prepare-brev-gateway.sh"; then
  printf 'Brev helpers must use noninteractive sudo -n\n' >&2
  exit 1
fi
grep -Fq 'Operation is not implemented or not supported' "$ROOT/docs/brev.md"
grep -Fq 'Don’t copy individual OpenShell binaries' "$ROOT/docs/brev.md"
grep -Fq 'don’t run the launchable’s web' "$ROOT/README.md"
if grep -Eiq '\$[0-9]+([.][0-9]+)?(/hour|/hr)|compute price|storage pricing' "$ROOT/README.md"; then
  printf 'README must not include Brev pricing language\n' >&2
  exit 1
fi
grep -Fq '"mode": "nemoclaw-managed"' "$ROOT/deploy/brev/nemoclaw-managed-gateway.json"
if grep -Fq 'sudo install -o root -g root -m 0755' "$ROOT/README.md"; then
  printf 'README must not recommend replacing Brev-owned OpenShell binaries\n' >&2
  exit 1
fi
grep -Fq 'nvidia/nemotron-3-nano-omni-30b-a3b-reasoning' "$ROOT/README.md"
grep -Fq 'https://github.com/NVIDIA/NemoClaw/issues/8887' "$ROOT/README.md"
grep -Fq 'release/ask-nemoclaw-extension-0.10.11.zip' "$ROOT/README.md"
grep -Fq 'Connected to NemoClaw' "$ROOT/README.md"
grep -Fq 'one primary model for every' "$ROOT/docs/security.md"
grep -Fq 'A shorter `hermes plugins install` path may be useful later' "$ROOT/docs/development.md"
grep -Fq 'version: "0.9.4"' "$ROOT/hermes-plugin/plugin.yaml"
grep -Fq '"version": "0.9.4"' "$ROOT/hermes-plugin/dashboard/manifest.json"
test -s "$ROOT/assets/ask-nemoclaw-browser-context.png"
test -s "$ROOT/assets/ask-nemoclaw-architecture.png"
test -s "$ROOT/assets/ask-nemoclaw-architecture.svg"
grep -Fq 'sidepanel_browser_fixture.html' "$ROOT/tests/demo_screenshot_fixture.html"
if grep -Eiq 'confidential compute|SEV-SNP|KubeVirt|Google Docs.*branding' \
  "$ROOT/assets/ask-nemoclaw-architecture.svg"; then
  printf 'community architecture unexpectedly contains deployment-specific routing\n' >&2
  exit 1
fi

IMAGE_FIXTURE="$(mktemp -d)"
trap 'rm -rf -- "$IMAGE_FIXTURE"' EXIT
mkdir -p "$IMAGE_FIXTURE/.git" "$IMAGE_FIXTURE/agents/hermes/config"
printf '%s\n' '# managed Hermes image' '# Verify the immutable security package inventory in the completed image.' \
  > "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
printf '%s\n' \
  'const DASHBOARD_ROUTING_KEYS = [' \
  '  "_nemoclaw_upstream",' \
  '] as const;' \
  '' \
  'const MANAGED_POLICY_PATHS = [' \
  '  "updates.refresh_cua_driver",' \
  '  "plugins.enabled",' \
  '] as const;' \
  '' \
  'export const config = {' \
  '    plugins: {' \
  '      enabled: ["nemoclaw"],' \
  '    },' \
  '};' \
  '' \
  '  applyHermesManagedRoute(config, {' \
  '    model: settings.model,' \
  '    baseUrl: settings.baseUrl,' \
  '    upstreamProvider: settings.upstreamProvider,' \
  '    inferenceApi: settings.inferenceApi,' \
  '    contextWindow: settings.contextWindow,' \
  '  });' \
  > "$IMAGE_FIXTURE/agents/hermes/config/hermes-config.ts"
"$PYTHON_BIN" "$ROOT/scripts/prepare-hermes-image.py" --nemoclaw-source "$IMAGE_FIXTURE"
"$PYTHON_BIN" "$ROOT/scripts/prepare-hermes-image.py" --nemoclaw-source "$IMAGE_FIXTURE"
test -s "$IMAGE_FIXTURE/local-plugins/ask-nemoclaw/dashboard/plugin_api.py"
test -x "$IMAGE_FIXTURE/local-plugins/ask-nemoclaw/configure_dashboard_auth.py"
test -x "$IMAGE_FIXTURE/local-plugins/ask-nemoclaw/configure_dashboard_public_url.py"
test -s "$IMAGE_FIXTURE/local-relay/browser-context-knowledge-assistant/plugins.toml"
grep -Fq '# BEGIN browser-context-knowledge-assistant' "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
test "$(grep -Fc '# BEGIN browser-context-knowledge-assistant' "$IMAGE_FIXTURE/agents/hermes/Dockerfile")" -eq 1
grep -Fq 'COPY local-plugins/ask-nemoclaw/ /opt/hermes/plugins/ask-nemoclaw/' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq 'ADD --checksum=sha256:0ce7103aec546766649c182619d16aa6ad07439e4d0ebd16d95c5004afb3e56a' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq 'nemo_relay-0.7.2-cp311-abi3-manylinux_2_17_x86_64.manylinux2014_x86_64.whl' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq 'assert version("nemo-relay") == "0.7.2"' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq 'uv pip check --python /opt/hermes/.venv/bin/python' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq 'HERMES_NEMO_RELAY_PLUGINS_TOML=/etc/nemo-relay/config/plugins.toml' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq 'HERMES_ASK_NEMOCLAW_LOOPBACK_MODE=1' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq '/etc/nemoclaw/ask-nemoclaw-loopback-mode' \
  "$IMAGE_FIXTURE/agents/hermes/Dockerfile"
grep -Fq 'enabled: ["nemoclaw", "ask-nemoclaw", "observability/nemo_relay", "dashboard_auth/basic"]' \
  "$IMAGE_FIXTURE/agents/hermes/config/hermes-config.ts"
grep -Fq '"plugins",' \
  "$IMAGE_FIXTURE/agents/hermes/config/hermes-config.ts"
grep -Fq 'settings.model === "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"' \
  "$IMAGE_FIXTURE/agents/hermes/config/hermes-config.ts"
grep -Fq '(config.model as Record<string, unknown>).supports_vision = true;' \
  "$IMAGE_FIXTURE/agents/hermes/config/hermes-config.ts"
if grep -Fq '"plugins.enabled",' \
  "$IMAGE_FIXTURE/agents/hermes/config/hermes-config.ts"; then
  printf 'plugin enablement must not extend Hermes profile managed paths\n' >&2
  exit 1
fi
grep -Fq 'output_directory = "/sandbox/.hermes-data/nemo-relay/atif"' \
  "$IMAGE_FIXTURE/local-relay/browser-context-knowledge-assistant/plugins.toml"
if grep -Eq 'opentelemetry|https?://' \
  "$IMAGE_FIXTURE/local-relay/browser-context-knowledge-assistant/plugins.toml"; then
  printf 'base Relay configuration unexpectedly contains an external collector\n' >&2
  exit 1
fi

printf '%s\n' "Verification completed."
