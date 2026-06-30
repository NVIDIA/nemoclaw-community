#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Enable Hermes's native NeMo Relay plugin in a NemoClaw source checkout."""

from __future__ import annotations

import argparse
from pathlib import Path


LEGACY_MARKER = "# financial-assistant-native-relay\n"
DOCKERFILE_MARKER = "# financial-assistant-native-relay-v2"
STARTUP_MARKER = "# financial-assistant-native-relay-env-v2"
DOCKERFILE_INSERT = f"""{DOCKERFILE_MARKER}
# Install the NeMo Relay version locked by Hermes. Object-store export is not
# enabled here because the released wheel does not include that native feature.
WORKDIR /opt/hermes
RUN /usr/local/bin/uv sync --extra nemo-relay --locked

COPY agents/hermes/nemo-relay-plugins.toml /etc/nemo-relay/plugins.toml
RUN chmod 444 /etc/nemo-relay/plugins.toml
ENV HERMES_NEMO_RELAY_PLUGINS_TOML=/etc/nemo-relay/plugins.toml

"""

STARTUP_ENV_INSERT = f"""{STARTUP_MARKER}
# OpenShell's gateway privilege boundary intentionally resets the image env.
# Pass the native Relay config path to the Hermes process explicitly.
NEMO_RELAY_GATEWAY_ENV=(
  "HERMES_NEMO_RELAY_PLUGINS_TOML=/etc/nemo-relay/plugins.toml"
)

"""


def replace_once(path: Path, old: str, new: str, marker: str) -> None:
    text = path.read_text(encoding="utf-8")
    if marker in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"Expected exactly one integration point in {path}; found {count}. "
            "Review the current NemoClaw Hermes image before updating this demo."
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_nemoclaw(
    source: Path,
    relay_config: Path,
) -> None:
    dockerfile = source / "agents/hermes/Dockerfile"
    hermes_config = source / "agents/hermes/config/hermes-config.ts"
    startup = source / "agents/hermes/start.sh"
    relay_target = source / "agents/hermes/nemo-relay-plugins.toml"

    for path in (dockerfile, hermes_config, startup, relay_config):
        if not path.is_file():
            raise FileNotFoundError(path)

    if LEGACY_MARKER in dockerfile.read_text(encoding="utf-8"):
        raise RuntimeError(
            f"Legacy financial assistant patch found in {source}; remove the "
            "runtime checkout and retry."
        )

    replace_once(
        dockerfile,
        "WORKDIR /sandbox\nUSER sandbox\n",
        f"{DOCKERFILE_INSERT}WORKDIR /sandbox\nUSER sandbox\n",
        DOCKERFILE_MARKER,
    )
    replace_once(
        hermes_config,
        'enabled: ["nemoclaw"],',
        'enabled: ["nemoclaw", "observability/nemo_relay"],',
        '"observability/nemo_relay"',
    )
    replace_once(
        startup,
        "# ── Main ─────────────────────────────────────────────────────────\n",
        f"{STARTUP_ENV_INSERT}# ── Main ─────────────────────────────────────────────────────────\n",
        STARTUP_MARKER,
    )
    replace_once(
        startup,
        'HERMES_HOME="${HERMES_DIR}" \\\n    nohup "$HERMES" gateway run >/tmp/gateway.log 2>&1 &',
        'HERMES_HOME="${HERMES_DIR}" \\\n    nohup env "${NEMO_RELAY_GATEWAY_ENV[@]}" "$HERMES" gateway run >/tmp/gateway.log 2>&1 &',
        'nohup env "${NEMO_RELAY_GATEWAY_ENV[@]}" "$HERMES" gateway run',
    )
    replace_once(
        startup,
        'nohup "${STEP_DOWN_PREFIX_GATEWAY[@]}" sh -c',
        'nohup "${STEP_DOWN_PREFIX_GATEWAY[@]}" env "${NEMO_RELAY_GATEWAY_ENV[@]}" sh -c',
        '"${STEP_DOWN_PREFIX_GATEWAY[@]}" env "${NEMO_RELAY_GATEWAY_ENV[@]}"',
    )
    relay_target.write_bytes(relay_config.read_bytes())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--relay-config", type=Path, required=True)
    args = parser.parse_args()

    patch_nemoclaw(
        args.source.resolve(),
        args.relay_config.resolve(),
    )
    print(f"Patched NemoClaw Hermes native Relay support in {args.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
