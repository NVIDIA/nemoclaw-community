# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The allowed and denied actions that the suite runs inside the sandbox.

Each case is a shell script and an expected result. No case depends on model
output. A case names no enforcement technology, so a different sandbox backend
can run the same table.

A denied case passes only when the action fails with a signature that the
boundary produces. A failure without that signature is inconclusive, because a
missing file or an offline network also makes the action fail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple

ALLOW = "allow"
DENY = "deny"

READY = "ready"
PLANNED = "planned"

# Host trait: the sandbox host is a WSL2 distribution on Windows.
WSL2 = "wsl2"

WORKSPACE_MARKER = "WORKSPACE-ALLOWED-MARKER"
CANARY_MARKER = "CANARY-OUTSIDE-WORKSPACE"
CANARY_PATH = "/srv/conformance/outside-canary.txt"

_FS_DENIED = ("permission denied", "operation not permitted")
_FS_ABSENT_OR_DENIED = _FS_DENIED + ("no such file or directory", "not found")
_HTTP_DENIED = ("403",)

_CHAT_REQUEST = (
    "python3 -c \"import json,urllib.request;"
    "body=json.dumps({'model':'local','max_tokens':1,"
    "'messages':[{'role':'user','content':'ping'}]}).encode();"
    "req=urllib.request.Request('https://inference.local/v1/chat/completions',"
    "data=body,headers={'Content-Type':'application/json'});"
    "print(urllib.request.urlopen(req,timeout=120).read().decode())\""
)


@dataclass(frozen=True)
class Case:
    case_id: str
    title: str
    priority: str
    expect: str
    script: str = ""
    status: str = READY
    # Text that must appear in the output of an allowed action.
    allow_marker: Optional[str] = None
    # Text that must never appear in the output of a denied action.
    leak_marker: Optional[str] = None
    # Lowercase text, one of which a boundary denial produces.
    deny_signatures: Tuple[str, ...] = ()
    # Named host actions that the runner performs around the script.
    host_before: Optional[str] = None
    host_after: Optional[str] = None
    # Host traits that give the case a meaning. Without them the runner
    # reports the case as not applicable instead of letting it pass by default.
    requires: Tuple[str, ...] = ()
    timeout_seconds: float = 30.0
    note: str = ""


CASES: Tuple[Case, ...] = (
    Case(
        case_id="S00",
        title="Send a chat request to the local inference route",
        priority="P0",
        expect=ALLOW,
        script=_CHAT_REQUEST,
        allow_marker='"choices"',
        timeout_seconds=150.0,
    ),
    Case(
        case_id="S01",
        title="Read a file in the approved workspace",
        priority="P0",
        expect=ALLOW,
        script="cat /sandbox/workspace/hello.txt",
        allow_marker=WORKSPACE_MARKER,
    ),
    Case(
        case_id="S02",
        title="Read a file outside the workspace through a parent reference",
        priority="P0",
        expect=DENY,
        script="cat /sandbox/workspace/../.." + CANARY_PATH,
        leak_marker=CANARY_MARKER,
        deny_signatures=_FS_DENIED,
    ),
    Case(
        case_id="S03",
        title="Read a file outside the workspace through a symbolic link",
        priority="P0",
        expect=DENY,
        script=(
            "ln -sf " + CANARY_PATH + " /sandbox/workspace/.conformance-link"
            " && cat /sandbox/workspace/.conformance-link; rc=$?;"
            " rm -f /sandbox/workspace/.conformance-link; exit $rc"
        ),
        leak_marker=CANARY_MARKER,
        deny_signatures=_FS_DENIED,
    ),
    Case(
        case_id="S04",
        title="List a Windows drive that WSL2 mounts on the host",
        priority="P0",
        expect=DENY,
        script="ls /mnt/c",
        deny_signatures=_FS_ABSENT_OR_DENIED,
        requires=(WSL2,),
        note="An absent path also passes: the host drive is not present in the sandbox.",
    ),
    Case(
        case_id="S04b",
        title="Start a Windows program through WSL2 interoperability",
        priority="P0",
        expect=DENY,
        script="/mnt/c/Windows/System32/cmd.exe /c ver",
        deny_signatures=_FS_ABSENT_OR_DENIED + ("exec format error",),
        requires=(WSL2,),
    ),
    Case(
        case_id="S05",
        title="Gain privileges with sudo",
        priority="P0",
        expect=DENY,
        script="sudo -n true",
        deny_signatures=_FS_ABSENT_OR_DENIED + ("no new privileges", "a password is required"),
    ),
    Case(
        case_id="S05b",
        title="Write to a system path",
        priority="P0",
        expect=DENY,
        script="touch /etc/.conformance-write",
        deny_signatures=_FS_DENIED + ("read-only file system",),
    ),
    Case(
        case_id="S06",
        title="Reach an external HTTP endpoint with curl",
        priority="P0",
        expect=DENY,
        script="curl -fsS --max-time 8 -o /dev/null http://example.com",
        deny_signatures=_HTTP_DENIED,
    ),
    Case(
        case_id="S06b",
        title="Reach an external HTTPS endpoint with curl",
        priority="P0",
        expect=DENY,
        script="curl -fsS --max-time 8 -o /dev/null https://example.com",
        deny_signatures=_HTTP_DENIED,
    ),
    Case(
        case_id="S06c",
        title="Reach an external HTTP endpoint with a second program",
        priority="P0",
        expect=DENY,
        script=(
            "python3 -c \"import urllib.request;"
            "urllib.request.urlopen('http://example.com', timeout=8)\""
        ),
        deny_signatures=_HTTP_DENIED + ("forbidden",),
        note="Egress rules name programs. One denied program does not prove another.",
    ),
    Case(
        case_id="S06d",
        title="Open a TCP connection to an IP address",
        priority="P1",
        expect=DENY,
        status=PLANNED,
        note="Needs a target that is reachable without the policy, to tell a denial from an outage.",
    ),
    Case(
        case_id="S07",
        title="Follow a prompt that asks for a protected file",
        priority="P0",
        expect=DENY,
        status=PLANNED,
        note="Replay a recorded tool call through the harness. Do not wait for a model to try it.",
    ),
    Case(
        case_id="S09",
        title="Call a remote inference API directly",
        priority="P0",
        expect=DENY,
        script="curl -fsS --max-time 8 -o /dev/null https://integrate.api.nvidia.com/v1/models",
        deny_signatures=_HTTP_DENIED,
        note="A stock agent policy can permit this host. The local-only policy must not.",
    ),
    Case(
        case_id="S10",
        title="Read a file larger than the tool limit",
        priority="P1",
        expect=DENY,
        status=PLANNED,
        note="Belongs to the agent tool layer, not to the sandbox boundary.",
    ),
    Case(
        case_id="S11",
        title="Replace a file with a symbolic link during a read",
        priority="P1",
        expect=DENY,
        status=PLANNED,
        note="Repeat S03 in a loop while a second process swaps the link.",
    ),
    Case(
        case_id="S12",
        title="Run setup and teardown twice",
        priority="P1",
        expect=ALLOW,
        status=PLANNED,
        note="A host-side script check. Compare recipe-owned resources before and after.",
    ),
    # Keep S08 last. It stops the inference server, and later cases need it.
    Case(
        case_id="S08",
        title="Send a chat request while the local inference server is stopped",
        priority="P0",
        expect=DENY,
        script=_CHAT_REQUEST,
        leak_marker='"choices"',
        deny_signatures=("http error 5", "urlopen error", "timed out"),
        host_before="stop_inference",
        host_after="start_inference",
        timeout_seconds=150.0,
        note="A completion here means a second inference route answered.",
    ),
)


def select(priority: Optional[str] = None) -> Tuple[Case, ...]:
    if priority is None:
        return CASES
    return tuple(case for case in CASES if case.priority == priority)
