# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Safely seed chart-owned Hermes state on the retained PVC.

The core seed owns exactly three things on the state volume: the ownership
marker, the ``hermes`` and ``workspace`` directory roots, and the plugin
run order. Everything else (skills, kubeconfigs, staged binaries) belongs to
seed plugins declared through ``lifecycle.seed.plugins``. Plugins are separate
Python entrypoints mounted at ``/plugins/<name>`` that may import this module
from ``/runtime`` for the ownership-aware helpers below.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile


STATE = Path(os.environ.get("SEED_STATE", "/state"))
MARKER = STATE / ".nemoclaw-helm-owner.json"
RELEASE = os.environ["RELEASE_ID"]
RELEASE_REVISION = int(os.environ["RELEASE_REVISION"])
PLUGIN_ROOT = Path("/plugins")
DIRECTORY_MODE = 0o700
# Filesystem artifacts that a freshly provisioned volume may legitimately hold.
TOLERATED_EMPTY_VOLUME_ENTRIES = frozenset({"lost+found"})
PLUGIN_NAME_PATTERN = re.compile(r"[a-z0-9]([-a-z0-9]{0,30}[a-z0-9])?")
PLUGIN_ENTRYPOINT_PATTERN = re.compile(r"[A-Za-z0-9_][A-Za-z0-9_.-]*\.py")


def checked_directory(path: Path) -> None:
    """Create or normalize one chart-owned directory. Call only on owned state."""
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
    """Read the ownership marker without mutating anything.

    Returns ``None`` for an unmarked volume, the marker for a volume owned by
    this release, and exits for a volume owned by another release.
    """
    if MARKER.is_symlink():
        raise SystemExit("invalid chart ownership marker")
    if not MARKER.exists():
        return None
    if not MARKER.is_file():
        raise SystemExit("invalid chart ownership marker")
    data = json.loads(MARKER.read_text(encoding="utf-8"))
    if data.get("schema") != 1 or data.get("release") != RELEASE:
        raise SystemExit("PVC is owned by another Helm release")
    if data.get("status", "ready") not in {"seeding", "ready"}:
        raise SystemExit("invalid chart ownership marker status")
    return data


def refuse_unmarked_populated_state() -> None:
    """Refuse to adopt a volume that has content but no ownership marker.

    A volume without a marker is claimed only when it is empty (apart from
    filesystem bookkeeping such as ``lost+found``). Anything else may belong
    to a person or another tool and is left byte-for-byte untouched.
    """
    foreign = sorted(
        entry.name
        for entry in STATE.iterdir()
        if entry.name not in TOLERATED_EMPTY_VOLUME_ENTRIES
    )
    if foreign:
        preview = ", ".join(foreign[:10])
        raise SystemExit(
            "refusing to adopt an unmarked state volume that already contains: "
            f"{preview}; remove the content or use a fresh claim"
        )


def atomic_write(destination: Path, payload: bytes, mode: int) -> None:
    """Replace one regular file without following an attacker-controlled temp link."""
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(mode)
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def write_owner_marker(status: str = "ready") -> None:
    if status not in {"seeding", "ready"}:
        raise ValueError("invalid ownership marker status")
    payload = (
        json.dumps(
            {
                "schema": 1,
                "release": RELEASE,
                "revision": RELEASE_REVISION,
                "status": status,
            },
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    atomic_write(MARKER, payload, 0o644)


def claim_state_for_reconciliation() -> None:
    """Establish retry-safe ownership before the first mutation.

    ``existing_owner`` and ``refuse_unmarked_populated_state`` are read-only, so
    a claim owned by another release or an unmarked populated claim is never
    changed. Writing the ``seeding`` marker first lets the same release resume
    after any later failure while ``wait_seed.py`` still refuses to treat the
    revision as complete.
    """
    if existing_owner() is None:
        refuse_unmarked_populated_state()
    write_owner_marker("seeding")


def replace_owned_directory(staged: Path | None, destination: Path) -> None:
    """Atomically replace (or remove, when ``staged`` is None) an owned directory."""
    owner = existing_owner()
    if destination.is_symlink():
        raise SystemExit(f"invalid chart-owned directory: {destination}")
    if destination.exists() and owner is None:
        raise SystemExit(f"refusing to replace unowned chart directory: {destination}")
    if destination.exists() and not destination.is_dir():
        raise SystemExit(f"invalid chart-owned directory: {destination}")
    if staged is None:
        if destination.exists():
            set_directory_tree_mode(destination, 0o700)
            shutil.rmtree(destination)
        return
    backup = destination.with_name(f".{destination.name}.previous-{os.getpid()}")
    if backup.exists():
        raise SystemExit(f"unexpected chart backup path: {backup}")
    if destination.exists():
        os.replace(destination, backup)
    try:
        os.replace(staged, destination)
    except Exception:
        if backup.exists() and not destination.exists():
            os.replace(backup, destination)
        raise
    if backup.exists():
        set_directory_tree_mode(backup, 0o700)
        shutil.rmtree(backup)


def set_directory_tree_mode(root: Path, mode: int) -> None:
    """Set only directory modes for a verified chart-owned tree."""
    if root.is_symlink() or not root.is_dir():
        raise SystemExit(f"invalid chart-owned directory tree: {root}")
    directories = [root]
    for path in root.rglob("*"):
        if path.is_symlink():
            raise SystemExit(f"unexpected symlink in chart-owned directory tree: {path}")
        if path.is_dir():
            directories.append(path)
    for directory in sorted(directories, key=lambda path: len(path.parts), reverse=True):
        directory.chmod(mode)


def replace_owned_file(destination: Path, payload: bytes, mode: int) -> None:
    """Write one chart-owned regular file, refusing unowned or non-regular targets."""
    if destination.is_symlink():
        raise SystemExit(f"invalid chart-owned file: {destination}")
    if destination.exists():
        if existing_owner() is None:
            raise SystemExit(f"refusing to replace unowned file: {destination}")
        if not destination.is_file():
            raise SystemExit(f"invalid chart-owned file: {destination}")
    atomic_write(destination, payload, mode)


def remove_owned_file(destination: Path) -> None:
    """Remove one chart-owned file when present, refusing unowned targets."""
    if destination.is_symlink() or destination.exists():
        if existing_owner() is None:
            raise SystemExit(f"refusing to remove unowned file: {destination}")
        destination.unlink(missing_ok=True)


def plugin_manifest() -> list[dict[str, str]]:
    """Parse and validate the plugin run order declared by the chart."""
    try:
        manifest = json.loads(os.environ.get("SEED_PLUGINS", "[]"))
    except json.JSONDecodeError as error:
        raise SystemExit("invalid seed plugin manifest") from error
    if not isinstance(manifest, list):
        raise SystemExit("invalid seed plugin manifest")
    seen: set[str] = set()
    plugins: list[dict[str, str]] = []
    for entry in manifest:
        if not isinstance(entry, dict) or set(entry) != {"name", "entrypoint"}:
            raise SystemExit("invalid seed plugin manifest entry")
        name = entry["name"]
        entrypoint = entry["entrypoint"]
        if (
            not isinstance(name, str)
            or not PLUGIN_NAME_PATTERN.fullmatch(name)
            or not isinstance(entrypoint, str)
            or not PLUGIN_ENTRYPOINT_PATTERN.fullmatch(entrypoint)
            or name in seen
        ):
            raise SystemExit(f"invalid seed plugin declaration: {entry!r}")
        seen.add(name)
        plugins.append({"name": name, "entrypoint": entrypoint})
    return plugins


def run_seed_plugins() -> None:
    """Run each declared plugin entrypoint after the core claim succeeded."""
    for plugin in plugin_manifest():
        root = PLUGIN_ROOT / plugin["name"]
        try:
            mount_root = root.resolve(strict=True)
            script = (root / plugin["entrypoint"]).resolve(strict=True)
        except OSError as error:
            raise SystemExit(f"seed plugin {plugin['name']} entrypoint is missing") from error
        # ConfigMap volumes publish files through a ..data symlink, so resolve
        # the entrypoint and require it to stay inside its own mount.
        if not script.is_file() or not script.is_relative_to(mount_root):
            raise SystemExit(f"seed plugin {plugin['name']} entrypoint escapes its mount")
        environment = os.environ.copy()
        environment.update(
            {
                "SEED_STATE": str(STATE),
                "SEED_PLUGIN_NAME": plugin["name"],
                "SEED_PLUGIN_ROOT": str(root),
                "SEED_CORE_MODULE_PATH": str(Path(__file__).resolve().parent),
            }
        )
        completed = subprocess.run(
            [sys.executable, "-B", str(script)],
            check=False,
            env=environment,
        )
        if completed.returncode != 0:
            raise SystemExit(
                f"seed plugin {plugin['name']} failed with exit status {completed.returncode}; "
                "the ownership marker stays at 'seeding' so the same release can retry"
            )
        print(f"seed plugin {plugin['name']} completed")


def main() -> None:
    # Read-only inspection first: nothing below this line runs for a claim owned
    # by another release or for an unmarked claim that already holds content.
    checked_mount_root(STATE)
    claim_state_for_reconciliation()
    checked_directory(STATE / "hermes")
    checked_directory(STATE / "hermes" / "skills")
    checked_directory(STATE / "workspace")
    run_seed_plugins()
    write_owner_marker("ready")
    print("seeded chart-owned Hermes state")


if __name__ == "__main__":
    main()
