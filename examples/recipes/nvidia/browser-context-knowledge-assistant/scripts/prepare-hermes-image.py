#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Add Ask NemoClaw and local NeMo Relay tracing to a NemoClaw checkout."""

import argparse
from pathlib import Path
import shutil


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_SOURCE = ROOT / "hermes-plugin"
RELAY_SOURCE = ROOT / "relay"
BEGIN_MARKER = "# BEGIN browser-context-knowledge-assistant"
END_MARKER = "# END browser-context-knowledge-assistant"
ANCHOR = "# Verify the immutable security package inventory in the completed image."
MANAGED_POLICY_BEFORE = '      enabled: ["nemoclaw"],'
MANAGED_POLICY_AFTER = (
    '      enabled: ["nemoclaw", "ask-nemoclaw", "observability/nemo_relay", "dashboard_auth/basic"],'
)
ROUTING_KEYS_BEFORE = '  "_nemoclaw_upstream",\n] as const;'
ROUTING_KEYS_AFTER = (
    '  "_nemoclaw_upstream",\n'
    '  "plugins",\n'
    '] as const;'
)
VISION_MODEL_ID = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
VISION_ROUTE_BEFORE = """  applyHermesManagedRoute(config, {
    model: settings.model,
    baseUrl: settings.baseUrl,
    upstreamProvider: settings.upstreamProvider,
    inferenceApi: settings.inferenceApi,
    contextWindow: settings.contextWindow,
  });"""
VISION_ROUTE_AFTER = VISION_ROUTE_BEFORE + f"""

  // NemoClaw presents its enforced inference route to Hermes as a custom
  // OpenAI-compatible provider. Hermes cannot discover capabilities for that
  // provider automatically, so preserve native viewport pixels for the Omni
  // model tested by this recipe.
  if (settings.model === "{VISION_MODEL_ID}") {{
    (config.model as Record<string, unknown>).supports_vision = true;
  }}"""
LEGACY_MANAGED_PLUGIN_PATH = '  "plugins.enabled",\n'
RELAY_VERSION = "0.7.2"
RELAY_WHEEL_FILENAME = (
    "nemo_relay-0.7.2-cp311-abi3-manylinux_2_17_x86_64."
    "manylinux2014_x86_64.whl"
)
RELAY_WHEEL_URL = (
    "https://files.pythonhosted.org/packages/11/83/"
    "90230c2e9fae1aee39f768d4a9ef57e9f2716bcaed1a5923cce8b526c66b/"
    + RELAY_WHEEL_FILENAME
)
RELAY_WHEEL_SHA256 = (
    "0ce7103aec546766649c182619d16aa6ad07439e4d0ebd16d95c5004afb3e56a"
)
PLUGIN_LAYER = f"""{BEGIN_MARKER}
# This source checkout is dedicated to the community example. Keep the complete
# managed Hermes image contract above and add only this recipe's files.
COPY local-plugins/ask-nemoclaw/ /opt/hermes/plugins/ask-nemoclaw/
COPY local-relay/browser-context-knowledge-assistant/plugins.toml \\
     /etc/nemo-relay/config/plugins.toml
ADD --checksum=sha256:{RELAY_WHEEL_SHA256} \\
    {RELAY_WHEEL_URL} \\
    /tmp/{RELAY_WHEEL_FILENAME}
RUN test "$(dpkg --print-architecture)" = "amd64" \\
    && uv pip install --python /opt/hermes/.venv/bin/python \\
       --no-cache --no-deps /tmp/{RELAY_WHEEL_FILENAME} \\
    && /opt/hermes/.venv/bin/python -c \\
       'from importlib.metadata import version; assert version("nemo-relay") == "{RELAY_VERSION}"' \\
    && uv pip check --python /opt/hermes/.venv/bin/python \\
    && rm /tmp/{RELAY_WHEEL_FILENAME} \\
    && mkdir -p /sandbox/.hermes-data/nemo-relay/atif \\
    && chown -R root:root /opt/hermes/plugins/ask-nemoclaw \\
    && chmod -R a+rX /opt/hermes/plugins/ask-nemoclaw \\
    && chown -R sandbox:sandbox /sandbox/.hermes-data/nemo-relay \\
    && mkdir -p /etc/nemoclaw \\
    && printf '1\\n' > /etc/nemoclaw/ask-nemoclaw-loopback-mode \\
    && chown root:root /etc/nemoclaw /etc/nemoclaw/ask-nemoclaw-loopback-mode \\
    && chmod 555 /etc/nemoclaw \\
    && chmod 444 /etc/nemoclaw/ask-nemoclaw-loopback-mode \\
    && chown -R root:root /etc/nemo-relay \\
    && chmod 555 /etc/nemo-relay /etc/nemo-relay/config \\
    && chmod 444 /etc/nemo-relay/config/plugins.toml
ENV HERMES_NEMO_RELAY_PLUGINS_TOML=/etc/nemo-relay/config/plugins.toml
ENV HERMES_ASK_NEMOCLAW_LOOPBACK_MODE=1
{END_MARKER}

"""


def update_managed_policy(text: str) -> str:
    if MANAGED_POLICY_AFTER not in text and MANAGED_POLICY_BEFORE not in text:
        raise SystemExit(
            "The managed Hermes plugin policy has changed; review the current "
            "NemoClaw plugin configuration before applying this example"
        )
    if ROUTING_KEYS_AFTER not in text and ROUTING_KEYS_BEFORE not in text:
        raise SystemExit(
            "The managed Hermes dashboard policy has changed; review the current "
            "NemoClaw dashboard seeding contract before applying this example"
        )
    if VISION_ROUTE_AFTER not in text and VISION_ROUTE_BEFORE not in text:
        raise SystemExit(
            "The managed Hermes inference route has changed; review the current "
            "NemoClaw vision capability contract before applying this example"
        )
    return text.replace(
        MANAGED_POLICY_BEFORE, MANAGED_POLICY_AFTER, 1
    ).replace(
        ROUTING_KEYS_BEFORE, ROUTING_KEYS_AFTER, 1
    ).replace(
        VISION_ROUTE_BEFORE, VISION_ROUTE_AFTER, 1
    ).replace(
        LEGACY_MANAGED_PLUGIN_PATH, "", 1
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Prepare the managed NemoClaw Hermes image for this recipe"
    )
    parser.add_argument("--nemoclaw-source", required=True, type=Path)
    args = parser.parse_args()

    source = args.nemoclaw_source.resolve()
    dockerfile = source / "agents" / "hermes" / "Dockerfile"
    config_dir = source / "agents" / "hermes" / "config"
    plugin_config_candidates = (
        config_dir / "hermes-config.ts",
        config_dir / "managed-policy.ts",
    )
    plugin_config = next(
        (candidate for candidate in plugin_config_candidates if candidate.is_file()),
        None,
    )
    if (
        not (source / ".git").exists()
        or not dockerfile.is_file()
        or plugin_config is None
    ):
        raise SystemExit("--nemoclaw-source must be a NemoClaw source checkout")

    text = dockerfile.read_text(encoding="utf-8")
    policy_text = plugin_config.read_text(encoding="utf-8")
    destinations = (
        (PLUGIN_SOURCE, source / "local-plugins" / "ask-nemoclaw"),
        (
            RELAY_SOURCE,
            source / "local-relay" / "browser-context-knowledge-assistant",
        ),
    )
    if (BEGIN_MARKER in text) != (END_MARKER in text):
        raise SystemExit(
            "The managed example layer is incomplete; restore a clean Hermes "
            "Dockerfile before continuing"
        )
    if BEGIN_MARKER in text:
        start = text.index(BEGIN_MARKER)
        finish = text.index(END_MARKER, start) + len(END_MARKER)
        updated = text[:start] + PLUGIN_LAYER.strip() + text[finish:]
        if updated != text:
            dockerfile.write_text(updated, encoding="utf-8")
            print(f"Updated browser context assistant image layer: {dockerfile}")
        else:
            print(f"Browser context assistant image layer is current: {dockerfile}")
        updated_policy = update_managed_policy(policy_text)
        if updated_policy != policy_text:
            plugin_config.write_text(updated_policy, encoding="utf-8")
            print(f"Updated managed plugin configuration: {plugin_config}")
        else:
            print(f"Managed plugin configuration is current: {plugin_config}")
        for origin, destination in destinations:
            if destination.exists() and not destination.is_dir():
                raise SystemExit(f"Managed recipe path is not a directory: {destination}")
            shutil.copytree(origin, destination, dirs_exist_ok=True)
            print(f"Refreshed managed recipe payload: {destination}")
        return
    if ANCHOR not in text:
        raise SystemExit(
            "The managed Hermes Dockerfile layout has changed; review the current "
            "NemoClaw plugin installation guide before applying this example"
        )

    updated_policy = update_managed_policy(policy_text)

    for _, destination in destinations:
        if destination.exists():
            raise SystemExit(
                f"Refusing to replace existing path: {destination}. "
                "Use a dedicated clean checkout."
            )

    for origin, destination in destinations:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(origin, destination)
    dockerfile.write_text(
        text.replace(ANCHOR, PLUGIN_LAYER + ANCHOR, 1), encoding="utf-8"
    )
    if updated_policy != policy_text:
        plugin_config.write_text(
            updated_policy,
            encoding="utf-8",
        )

    print(f"Copied plugin to: {destinations[0][1]}")
    print(f"Copied Relay configuration to: {destinations[1][1]}")
    print(f"Updated managed Dockerfile: {dockerfile}")
    print(f"Updated managed plugin configuration: {plugin_config}")


if __name__ == "__main__":
    main()
