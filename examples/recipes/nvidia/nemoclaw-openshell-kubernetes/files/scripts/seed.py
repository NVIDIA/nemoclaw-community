# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Safely seed chart-owned Hermes state on the retained PVC."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil


STATE = Path("/state")
MARKER = STATE / ".nemoclaw-helm-owner.json"
RELEASE = os.environ["RELEASE_ID"]
RELEASE_REVISION = int(os.environ["RELEASE_REVISION"])
PROXY_TOKEN_SOURCE = Path("/proxy-auth/token")
PROXY_TOKEN_DESTINATION = STATE / "hermes" / ".sre-proxy-token"
# OpenShell resolves the same sandbox identity used by the seed Job: UID/GID
# 1000 on Kubernetes, or the start of the namespace SCC range on OpenShift.
# State therefore never needs world-readable or world-writable fallback modes.
DIRECTORY_MODE = 0o700
PROXY_TOKEN_MODE = 0o600


def checked_directory(path: Path) -> None:
    if path.is_symlink():
        raise SystemExit(f"refusing symlinked state path: {path}")
    path.mkdir(mode=DIRECTORY_MODE, parents=True, exist_ok=True)
    path.chmod(DIRECTORY_MODE)


def checked_mount_root(path: Path) -> None:
    """Validate the CSI-owned mount root without changing its ownership or mode."""
    if path.is_symlink() or not path.is_dir():
        raise SystemExit(f"invalid state mount root: {path}")
    if not os.access(path, os.W_OK | os.X_OK):
        raise SystemExit(f"state mount root is not writable: {path}")


def existing_owner() -> dict[str, object] | None:
    if not MARKER.exists():
        return None
    if MARKER.is_symlink() or not MARKER.is_file():
        raise SystemExit("invalid chart ownership marker")
    data = json.loads(MARKER.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("release") != RELEASE:
        raise SystemExit("PVC is owned by another Helm release")
    return data


def reconcile_skill(name: str, enabled: bool) -> None:
    destination = STATE / "hermes" / "skills" / name
    source = Path("/source") / name
    owner = existing_owner()
    if destination.exists() and owner is None:
        raise SystemExit(f"refusing to replace unowned skill directory: {destination}")
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise SystemExit(f"invalid chart-owned skill path: {destination}")
        shutil.rmtree(destination)
    if enabled:
        shutil.copytree(source, destination, symlinks=False)
        for path in destination.rglob("*"):
            if path.is_symlink():
                raise SystemExit(f"skill source produced a symlink: {path}")
            path.chmod(0o755 if path.is_dir() else 0o644)


def reconcile_proxy_token(enabled: bool) -> None:
    """Copy the proxy credential into chart-owned state without exposing it in a pod spec."""
    owner = existing_owner()
    if PROXY_TOKEN_DESTINATION.exists():
        if owner is None:
            raise SystemExit(f"refusing to replace unowned proxy token: {PROXY_TOKEN_DESTINATION}")
        if PROXY_TOKEN_DESTINATION.is_symlink() or not PROXY_TOKEN_DESTINATION.is_file():
            raise SystemExit(f"invalid chart-owned proxy token path: {PROXY_TOKEN_DESTINATION}")
    if not enabled:
        PROXY_TOKEN_DESTINATION.unlink(missing_ok=True)
        return
    if PROXY_TOKEN_SOURCE.is_symlink() or not PROXY_TOKEN_SOURCE.is_file():
        raise SystemExit("invalid SRE proxy token source")
    token = PROXY_TOKEN_SOURCE.read_bytes()
    if not token or len(token) > 4096:
        raise SystemExit("invalid SRE proxy token length")
    temporary = PROXY_TOKEN_DESTINATION.with_suffix(".tmp")
    temporary.write_bytes(token)
    temporary.chmod(PROXY_TOKEN_MODE)
    temporary.replace(PROXY_TOKEN_DESTINATION)


def main() -> None:
    checked_mount_root(STATE)
    checked_directory(STATE / "hermes")
    checked_directory(STATE / "hermes" / "skills")
    checked_directory(STATE / "workspace")
    existing_owner()
    sre_enabled = os.environ.get("SRE_ENABLED") == "true"
    reconcile_skill("kubernetes-sre", sre_enabled)
    reconcile_skill("openshift-llm-deploy", os.environ.get("MODEL_DELETE_ENABLED") == "true")
    reconcile_proxy_token(sre_enabled)
    temporary = MARKER.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(
            {"schema": 1, "release": RELEASE, "revision": RELEASE_REVISION},
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    # The marker contains no secret and must be readable by the separately
    # scheduled bootstrap Job, including OpenShift's per-pod randomized UIDs.
    temporary.chmod(0o644)
    temporary.replace(MARKER)
    print("seeded chart-owned Hermes state")


if __name__ == "__main__":
    main()
