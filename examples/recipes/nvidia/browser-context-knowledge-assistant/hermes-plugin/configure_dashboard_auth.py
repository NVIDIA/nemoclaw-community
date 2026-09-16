#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Configure Hermes dashboard basic authentication without storing plaintext."""

from __future__ import annotations

import getpass
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

import yaml
from plugins.dashboard_auth.basic import hash_password


LEGACY_ENV_KEYS = {
    "HERMES_DASHBOARD_BASIC_AUTH_USERNAME",
    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD",
    "HERMES_DASHBOARD_BASIC_AUTH_PASSWORD_HASH",
    "HERMES_DASHBOARD_BASIC_AUTH_SECRET",
}


def hermes_path(command: str) -> Path:
    result = subprocess.run(
        ["hermes", "config", command],
        check=True,
        capture_output=True,
        text=True,
    )
    path = result.stdout.strip()
    if not path:
        raise SystemExit(f"Hermes did not return its {command!r} path")
    return Path(path)


def dashboard_config_path() -> Path:
    configured = os.environ.get("HERMES_DASHBOARD_HOME", "").strip()
    if configured:
        return Path(configured) / "config.yaml"
    return hermes_path("path").parent / "profiles" / "dashboard-home" / "config.yaml"


def prompt_username() -> str:
    username = input("Dashboard username [admin]: ").strip() or "admin"
    if not username or len(username) > 128 or "\n" in username:
        raise SystemExit("Username must be 1-128 characters")
    return username


def prompt_password() -> str:
    password = getpass.getpass("Dashboard password: ")
    confirmation = getpass.getpass("Confirm dashboard password: ")
    if password != confirmation:
        raise SystemExit("Passwords do not match")
    if len(password) < 12:
        raise SystemExit("Use a password or passphrase with at least 12 characters")
    return password


def atomic_write(path: Path, content: str, default_mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.stat() if path.exists() else None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=path.parent, text=True
    )
    try:
        os.fchmod(descriptor, default_mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
        if existing is not None:
            os.chown(temporary_name, existing.st_uid, existing.st_gid)
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass
        raise


def write_basic_auth_config(
    path: Path, *, username: str, password_hash: str, signing_secret: str
) -> None:
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if config is None:
        config = {}
    if not isinstance(config, dict):
        raise SystemExit("Hermes config root must be a mapping")
    dashboard = config.setdefault("dashboard", {})
    if not isinstance(dashboard, dict):
        raise SystemExit("Hermes dashboard config must be a mapping")
    dashboard["basic_auth"] = {
        "username": username,
        "password_hash": password_hash,
        "secret": signing_secret,
    }
    plugins = config.setdefault("plugins", {})
    if not isinstance(plugins, dict):
        raise SystemExit("Hermes plugins config must be a mapping")
    enabled = plugins.get("enabled")
    if enabled is None:
        enabled = []
    if not isinstance(enabled, list) or not all(isinstance(item, str) for item in enabled):
        raise SystemExit("Hermes plugins.enabled config must be a string list")
    if "dashboard_auth/basic" not in enabled:
        enabled.append("dashboard_auth/basic")
    plugins["enabled"] = enabled
    atomic_write(
        path,
        yaml.safe_dump(config, sort_keys=False, allow_unicode=True),
        default_mode=0o640,
    )


def remove_legacy_env_entries(path: Path) -> None:
    if not path.exists():
        return
    retained = []
    for line in path.read_text(encoding="utf-8").splitlines():
        key = line.split("=", 1)[0].removeprefix("export ").strip()
        if key not in LEGACY_ENV_KEYS:
            retained.append(line)
    atomic_write(path, "\n".join(retained) + "\n", default_mode=0o640)


def main() -> None:
    username = prompt_username()
    password = prompt_password()
    password_hash = hash_password(password)
    password = ""

    write_basic_auth_config(
        dashboard_config_path(),
        username=username,
        password_hash=password_hash,
        signing_secret=secrets.token_urlsafe(48),
    )
    remove_legacy_env_entries(hermes_path("env-path"))

    print("Dashboard authentication configured in the isolated dashboard profile.")
    print("Only a scrypt password hash and a random session-signing secret were stored.")
    print("Exit the sandbox shell, then stop and start the sandbox from the Brev host.")


if __name__ == "__main__":
    main()
