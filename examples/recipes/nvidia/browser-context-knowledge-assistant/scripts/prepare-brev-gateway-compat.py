#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Match the pinned NemoClaw compatibility gateway's user to its private files."""

import argparse
from pathlib import Path
import re


MARKER = "// Ask NemoClaw: retain private gateway file ownership in compatibility mode."


def patched_launcher(text: str, compiled: bool) -> str:
    # Fail closed if the pinned launcher's structure or security flags change.
    pattern = re.compile(
        r'(?P<indent> +)const args = \[\s*"run",\s*"--rm",\s*"--name",\s*'
        r'containerName,\s*"--network",\s*"host",\s*"--cap-drop",\s*"ALL",\s*'
        r'"--security-opt",\s*"no-new-privileges",\s*\];'
    )
    matches = list(pattern.finditer(text))
    if len(matches) != 1:
        raise ValueError("Unsupported gateway launcher; expected the pinned restricted container arguments")
    match = matches[0]
    fs_name = "node_fs_1.default" if compiled else "fs"
    if f"{fs_name}.existsSync(dockerSocket)" not in text:
        raise ValueError("Unsupported gateway launcher filesystem import")
    lines = [
        MARKER,
        'env.XDG_STATE_HOME = options.stateDir;',
        'addEnv(args, "XDG_STATE_HOME", options.stateDir);',
        'if (typeof process.getuid !== "function" || typeof process.getgid !== "function") {',
        '  throw new Error("The Brev compatibility gateway requires a Unix host user");',
        '}',
        'args.push("--user", `${process.getuid()}:${process.getgid()}`);',
        f'if ({fs_name}.existsSync(dockerSocket)) {{',
        f'  args.push("--group-add", String({fs_name}.statSync(dockerSocket).gid));',
        '}',
    ]
    insertion = "\n" + "\n".join(match["indent"] + line for line in lines)
    if MARKER in text:
        # Check every prepared line, including the environment value; a marker
        # alone must not hide a partial or modified patch.
        prepared = re.compile(r"\s*" + r"\s*".join(re.escape(line.strip()) for line in lines))
        if prepared.match(text, match.end()):
            return text
        raise ValueError("Incomplete compatibility patch; reinstall the pinned runtime before retrying")
    return text[:match.end()] + insertion + text[match.end():]


def prepare(source: Path) -> None:
    targets = [
        (source / "src/lib/onboard/docker-driver-gateway-compat.ts", False),
        (source / "dist/lib/onboard/docker-driver-gateway-compat.js", True),
    ]
    # Validate both files before changing either; the compiled CLI is what runs.
    updates = [(path, patched_launcher(path.read_text(), compiled)) for path, compiled in targets]
    for path, text in updates:
        path.write_text(text)
    print("Prepared compatibility gateway to use the host UID/GID and Docker socket group.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--nemoclaw-source", type=Path, required=True)
    args = parser.parse_args()
    try:
        prepare(args.nemoclaw_source)
    except (OSError, ValueError) as error:
        parser.exit(1, f"Cannot prepare the Brev compatibility gateway: {error}\n")
