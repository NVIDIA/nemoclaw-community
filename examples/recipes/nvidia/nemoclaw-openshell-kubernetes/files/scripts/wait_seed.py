# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Wait for the chart-owned state seed to finish before OpenShell bootstrap."""

from __future__ import annotations

import json
import os
from pathlib import Path
import time


MARKER = Path("/state/.nemoclaw-helm-owner.json")


def main() -> None:
    expected_release = os.environ["RELEASE_ID"]
    expected_revision = int(os.environ["RELEASE_REVISION"])
    timeout_seconds = int(os.environ.get("SEED_WAIT_TIMEOUT_SECONDS", "300"))
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        if MARKER.exists():
            if MARKER.is_symlink() or not MARKER.is_file():
                raise SystemExit("invalid chart ownership marker")
            try:
                marker = json.loads(MARKER.read_text(encoding="utf-8"))
            except json.JSONDecodeError as error:
                raise SystemExit("invalid chart ownership marker JSON") from error
            if marker.get("schema") != 1 or marker.get("release") != expected_release:
                raise SystemExit("PVC is owned by another Helm release")
            if marker.get("revision") == expected_revision:
                print(f"seed Job completed for Helm revision {expected_revision}")
                return
        time.sleep(2)

    raise SystemExit(
        f"timed out waiting for seed Job marker for Helm revision {expected_revision}"
    )


if __name__ == "__main__":
    main()
