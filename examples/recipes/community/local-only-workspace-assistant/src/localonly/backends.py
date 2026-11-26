# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Run one shell script inside a sandbox and report what happened.

A backend is the only part of the suite that knows which sandbox technology is
under test. To test another boundary, add a class with the same `run` method.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from typing import List, Optional, Protocol

# The wrapped script prints this line last. A result without it means the
# script did not run to completion inside the sandbox.
EXIT_MARKER = "__LOCALONLY_EXIT__="
_EXIT_RE = re.compile(r"^" + re.escape(EXIT_MARKER) + r"(\d+)\s*$", re.MULTILINE)

ERROR_TIMEOUT = "backend error: timeout"
ERROR_NOT_FOUND = "backend error: command not found"
ERROR_NO_EXIT_MARKER = "backend error: script did not complete in the sandbox"


@dataclass(frozen=True)
class ExecResult:
    exit_code: Optional[int]
    output: str = ""
    error: Optional[str] = None


class Backend(Protocol):
    name: str

    def run(self, script: str, timeout_seconds: float) -> ExecResult:
        ...


def wrap(script: str) -> str:
    """Merge the output streams and append the exit status as the last line."""
    return "( " + script + " ) 2>&1; printf '\\n" + EXIT_MARKER + "%s\\n' \"$?\""


def parse(raw_output: str) -> ExecResult:
    matches = list(_EXIT_RE.finditer(raw_output))
    if not matches:
        return ExecResult(exit_code=None, output=raw_output, error=ERROR_NO_EXIT_MARKER)
    last = matches[-1]
    return ExecResult(exit_code=int(last.group(1)), output=raw_output[: last.start()])


class OpenShellBackend:
    """Run scripts with `openshell sandbox exec` as the sandbox user."""

    name = "openshell"

    def __init__(self, sandbox_name: str, executable: str = "openshell") -> None:
        self.sandbox_name = sandbox_name
        self.executable = executable

    def command(self, script: str) -> List[str]:
        return [
            self.executable, "sandbox", "exec", "-n", self.sandbox_name, "--no-tty",
            "--", "sh", "-c", wrap(script),
        ]

    def run(self, script: str, timeout_seconds: float) -> ExecResult:
        try:
            completed = subprocess.run(
                self.command(script),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return ExecResult(exit_code=None, error=ERROR_TIMEOUT)
        except FileNotFoundError:
            return ExecResult(exit_code=None, error=ERROR_NOT_FOUND)
        return parse(completed.stdout.decode("utf-8", errors="replace"))
