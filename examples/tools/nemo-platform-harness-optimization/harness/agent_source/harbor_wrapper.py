# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Harbor entry point for the NeMo ``cad-agent``.

Harbor imports this class into the *host* process (``harbor-native``), which is
what makes a GUI-bound agent evaluable: the run below reaches the FreeCAD
session on this machine, while the task container only hosts the verifier.

Three jobs: run the agent, publish its trace to ``/app/traces`` where the
verifier can read it, and measure the result against the reference mesh.

This module must live in the directory named by ``agent_source`` in
``optimizer.yaml``: Harbor's ``_scoped_import_path`` resolves the default entry
point ``harbor_wrapper:WrappedAgent`` against the agent directory alone.

The agent runs from ``agent.yaml`` *in this directory*
==========================================================
Each candidate is a full copy of this directory, and the run below invokes the
agent from the copy's own ``agent.yaml``. That is what makes a candidate's
edits real: change the model, the system prompt, the MCP server set, or drop a
skill into ``workspace/skills/``, and the next trial measures it.

The change surface is ``agent.yaml`` and ``workspace/skills/`` - the two
things that survive promotion to a deployed agent. A skill belongs in
``workspace/skills/<name>/SKILL.md`` with a pointer to ``/skills/`` in
``instructions.system.content``, which is how the deployed agent loads it too.

This file is the harness, not the agent, so it is pinned. The check below
catches an accidental edit immediately, but it cannot enforce the rule: it lives
in the file it protects, so a candidate that rewrites the wrapper removes the
check in the same edit. ``scorer/verify_candidates.py`` is the authoritative
gate, outside the candidate and never copied into one.

``agent.yaml`` must keep ``api_key_env`` and ``base_url`` under
``models.default``. The deepagents adapter's preflight requires both when the
agent is built from a config file rather than served by a deployment.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import importlib.util
import fcntl
import xmlrpc.client
import subprocess
import sys
import time
import json
import os
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

# Guarded so the pure helpers below (span conversion, id encoding, tool-call
# extraction) stay importable - and therefore unit-testable - without Harbor or
# httpx installed. A real run imports them successfully; the stubs only ever
# stand in when the module is imported for its helpers.
try:  # pragma: no cover - exercised by every real run, never by the tests
    import httpx
    from harbor.agents.base import BaseAgent
    from harbor.environments.base import BaseEnvironment
    from harbor.models.agent.context import AgentContext

except ImportError:  # pragma: no cover - exercised by the tests, never by a run
    httpx = None  # type: ignore[assignment]
    BaseAgent = object  # type: ignore[assignment,misc]
    BaseEnvironment = Any  # type: ignore[assignment,misc]
    AgentContext = Any  # type: ignore[assignment,misc]


BASE = os.environ.get("NMP_BASE_URL", "http://localhost:8080")
WORKSPACE = os.environ.get("NMP_WORKSPACE", "default")
# The candidate copy this wrapper was imported from. Resolved per copy, so
# every candidate runs its own configuration.
AGENT_DIR = Path(__file__).resolve().parent
AGENT_CONFIG = AGENT_DIR / "agent.yaml"
def _agent_name() -> str:
    """Read the agent name out of the config this wrapper runs.

    Traces are correlated by agent name, and the name is a property of the
    config, not of the environment. Reading it here keeps the two in step: a
    candidate that renames its agent still matches its own trace.
    """
    for line in AGENT_CONFIG.read_text(encoding="utf-8").splitlines():
        if line.startswith("name:"):
            return line.split(":", 1)[1].strip()
    raise RuntimeError(f"no top-level 'name:' in {AGENT_CONFIG}")


AGENT_NAME = _agent_name()


@contextlib.contextmanager
def _trial_config() -> Any:
    """Yield a config identical to the candidate's but under a unique name.

    Trace correlation has no identifier to work with: no id the gateway returns
    reaches Intake, so a trace can only be found by agent name and a time
    window. Under one shared name that is ambiguous whenever anything else is
    running, and the Experimentalist evaluates candidates concurrently.

    Giving every trial its own name removes the ambiguity at the source rather
    than resolving it after the fact. The candidate's own `agent.yaml` is never
    touched: this writes a sibling file, uses it for one invocation, and deletes
    it.
    """
    name = f"{AGENT_NAME}-{uuid.uuid4().hex[:12]}"
    text = re.sub(r"^name:.*$", f"name: {name}", AGENT_CONFIG.read_text(encoding="utf-8"),
                  count=1, flags=re.MULTILINE)
    path = AGENT_DIR / f".trial-{name}.yaml"
    path.write_text(text, encoding="utf-8")
    try:
        yield name, path
    finally:
        path.unlink(missing_ok=True)
def _nemo_cli() -> str:
    """Locate the ``nemo`` CLI without depending on PATH.

    Harbor imports this module into the interpreter that owns the CLI, so its
    sibling is the first and usual answer. The fallbacks cover being imported
    from another interpreter, which is what the unit tests do.
    """
    override = os.environ.get("NEMO_CLI")
    if override:
        return override
    sibling = Path(sys.executable).parent / "nemo"
    if sibling.is_file():
        return str(sibling)
    found = shutil.which("nemo")
    if found:
        return found
    return str(Path.home() / ".local" / "bin" / "nemo")


NEMO = _nemo_cli()
TRACE_DIR = "/app/traces"
# Ground truth. The verifier runs in a container and can never touch geometry,
# so IoU has to be measured here — on the host, where FreeCAD is — and published
# into the trace. Without this the loop can only optimize proxies.
FREECAD_RPC = os.environ.get("FREECAD_RPC", "http://127.0.0.1:9875")
# Resolved relative to this file so the harness runs from any checkout location:
# agent_source/ -> harness/ -> the example root, which holds scorer/score.py.
# Override with CAD_SCORER to point at a scorer kept outside the example.
def _example_root() -> Path:
    """Find the example root by walking up until the scorer is in sight.

    A fixed number of parents does not work here. The Experimentalist copies
    this whole directory into ``experiment/eval-and-optimize/agents/agent-N``
    for every candidate, so a relative offset that is correct in the checkout
    points inside the run output for every trial - where ``scorer/`` and
    ``meshes/`` do not exist, and every measurement is silently discarded.
    Searching upward is correct from both locations.
    """
    for candidate in Path(__file__).resolve().parents:
        if (candidate / "scorer" / "score.py").is_file():
            return candidate
    # Fall back to the checkout layout so the failure names a real path.
    return Path(__file__).resolve().parents[2]


EXAMPLE_ROOT = _example_root()
SCORER = os.environ.get("CAD_SCORER", str(EXAMPLE_ROOT / "scorer" / "score.py"))

PRISTINE = EXAMPLE_ROOT / "harness" / "agent_source"


#: The only ``agent.yaml`` blocks a candidate may change. Both promote by
#: copying the file to a deployment: the system prompt lives under
#: ``instructions``, subagents under ``harnesses``. Skills are files under
#: ``workspace/skills/`` and are not in this config at all.
MUTABLE_CONFIG_KEYS = ("instructions:", "harnesses:")


def _pinned_config(config: Path) -> str:
    """Return *config* with the mutable blocks removed, for comparison."""
    kept, dropping = [], False
    for line in config.read_text().splitlines():
        if line[:1] not in (" ", "\t", ""):  # a new top-level key
            dropping = line.startswith(MUTABLE_CONFIG_KEYS)
        if not dropping:
            kept.append(line)
    return "\n".join(kept).strip()


IGNORED_PATHS = ("__pycache__", "artifacts", "traces", ".fabric")


def _tracked(root: Path) -> dict[str, Path]:
    """Map relative path to file for everything under *root* worth comparing."""
    found = {}
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if any(part in IGNORED_PATHS for part in rel.parts) or rel.name.startswith(".trial-"):
            continue
        if path.is_symlink() or path.is_file():
            found[rel.as_posix()] = path
    return found


def _surface_violations(candidate: Path, pristine: Path) -> list[str]:
    """Return what *candidate* changed outside the promotable surface."""
    out: list[str] = []
    ours, theirs = _tracked(pristine), _tracked(candidate)
    for rel, path in sorted(theirs.items()):
        if path.is_symlink():
            out.append(f"{rel} is a symlink")
        elif rel.startswith("workspace/skills/"):
            continue
        elif rel == "agent.yaml":
            if rel not in ours or _pinned_config(path) != _pinned_config(ours[rel]):
                out.append("agent.yaml changed a pinned block")
        elif rel not in ours:
            out.append(f"{rel} is not in the original")
        elif path.read_bytes() != ours[rel].read_bytes():
            out.append(f"{rel} differs from the original")
    for rel in sorted(ours):
        if rel not in theirs and not rel.startswith("workspace/skills/"):
            out.append(f"{rel} was deleted")
    return out


def _assert_promotable_change_surface() -> None:
    """Refuse to score a candidate that changed something it cannot promote.

    The change surface is the whole candidate tree minus two openings: the
    ``instructions`` and ``harnesses`` blocks of ``agent.yaml``, and anything
    under ``workspace/skills/``. Everything else is pinned, including
    ``pyproject.toml`` and any file the original does not ship, because a new
    module is only a shadowed import away from running.

    **This check is fast feedback, not enforcement.** Harbor resolves the entry
    point inside the agent directory, so this function ships inside the tree it
    guards: a candidate that rewrites the wrapper deletes the check along with
    it, and by the time anything here runs, the candidate's own copy of this
    module has already been imported into the host process. It catches the
    accidental case immediately, which is most of them.
    ``scorer/verify_candidates.py`` applies the same rule from outside the
    candidate and is what decides whether a run's results can be trusted.
    """
    if AGENT_DIR == PRISTINE.resolve():
        return  # the checkout itself, not a candidate copy
    if not (PRISTINE / "harbor_wrapper.py").is_file():
        raise RuntimeError(f"cannot verify the candidate: {PRISTINE} is missing")
    found = _surface_violations(AGENT_DIR, PRISTINE)
    if found:
        raise RuntimeError(
            f"{AGENT_DIR} changed what it cannot promote: {'; '.join(found)}. "
            "Propose the change in the system prompt, subagents or "
            "workspace/skills/ instead."
        )


_assert_promotable_change_surface()


def _load_trial_metric() -> Any:
    """Load the guardrail metric from outside the candidate directory.

    The optimizer copies this file into every candidate and lets a coding agent
    edit it. The metric that decides whether a candidate is kept must not be
    editable by that candidate, so it is loaded from the example root and the
    path is checked before use.
    """
    module_path = (EXAMPLE_ROOT / "scorer" / "trial_metric.py").resolve()
    if AGENT_DIR.resolve() in module_path.parents:
        raise RuntimeError(
            f"guardrail metric resolved inside the candidate directory "
            f"({module_path}); it must come from the example root so a "
            "candidate cannot rewrite the measure that selects it."
        )
    spec = importlib.util.spec_from_file_location("cad_trial_metric", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load the guardrail metric from {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TRIAL_METRIC = _load_trial_metric()
MESH = Path(os.environ.get("CAD_REFERENCE_MESH",
                           EXAMPLE_ROOT / "meshes" / "reference_mug.obj"))
TIMEOUT = float(os.environ.get("CAD_AGENT_TIMEOUT", "3600"))

# The gateway caps a response at NEMO_AGENTS_GATEWAY_READ_TIMEOUT (300 s) and
# returns 502 while the agent keeps running, so the trace can appear long after
# the request fails. Waiting only a little past the cap scores a still-running
# reconstruction as a failed trial, which the aggregate counts as zero.
TRACE_WAIT = float(os.environ.get("CAD_AGENT_TRACE_WAIT", "3600"))

# Intake field -> OpenInference attribute key. Emitting the standard convention
# matters: trace-reading metrics select tool spans by `openinference.span.kind`,
# so a non-standard key hides every tool result from the verifier and scores a
# working run as zero.
ATTRIBUTE_KEYS = {
    "kind": "openinference.span.kind",
    "input": "input.value",
    "output": "output.value",
    "model": "llm.model_name",
    "status": "status.code",
    "agent_name": "agent.name",
}
# raw_attributes is deliberately absent. It is a superset of input/output on a
# model span, so publishing it doubles the body against Intake's 5 MB cap, and
# nothing downstream reads it: the verifier selects on eval.iou, and authored
# metrics select on openinference.span.kind and tool.name. It is still walked
# for nested tool calls in _tool_call_spans, which is where its value is.


# One live FreeCAD session and one Intake stream are shared by every trial, but
# the Experimentalist evaluates candidates concurrently: `n_concurrent_trials`
# only serialises trials *inside* one candidate's job. Two candidates running at
# once build documents of the same name in the same application, close each
# other's documents, and cannot be told apart in the trace stream because they
# share an agent name. This lock makes a trial the unit of exclusion.
TRIAL_LOCK = Path(os.environ.get(
    "CAD_TRIAL_LOCK", str(Path(tempfile.gettempdir()) / "cad-harness-trial.lock")))


# In-process half of the lock. The Experimentalist evaluates candidates with
# asyncio.gather on one event loop, so a bare blocking flock would stall the
# loop that the lock holder needs in order to finish: the first trial can never
# complete while the second is blocking inside it.
_TRIAL_GATE = asyncio.Lock()


@contextlib.asynccontextmanager
async def _exclusive_trial() -> Any:
    """Hold an exclusive lock for one trial, in-process and host-wide.

    The asyncio lock orders coroutines on this event loop without blocking it;
    the file lock then excludes any other process using the same FreeCAD
    session. The flock is taken in a worker thread for the same reason.
    """
    TRIAL_LOCK.parent.mkdir(parents=True, exist_ok=True)
    async with _TRIAL_GATE:
        handle = open(TRIAL_LOCK, "w")
        try:
            await asyncio.to_thread(fcntl.flock, handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


class WrappedAgent(BaseAgent):
    """Drive the deployed cad-agent and publish its trace for the verifier."""

    @staticmethod
    def name() -> str:
        return "nemo-cad-agent"

    def version(self) -> str | None:
        return "0.1.0"

    async def setup(self, environment: BaseEnvironment) -> None:
        await environment.exec(f"mkdir -p {TRACE_DIR}")

    async def run(
        self, instruction: str, environment: BaseEnvironment, context: AgentContext
    ) -> None:
        # Serialised across candidates: see TRIAL_LOCK. Held for the whole trial,
        # because the agent run, the score and the document close all touch the
        # one FreeCAD session, and the trace correlation below assumes nothing
        # else is producing traces under this agent name meanwhile.
        async with _exclusive_trial():
            await self._run_locked(instruction, environment, context)

    async def _run_locked(
            self, instruction: str, environment: BaseEnvironment, context: AgentContext
        ) -> None:
            # The task ships with a @MESH_PATH@ placeholder because the path has to
            # be absolute for FreeCAD and an absolute path cannot be committed.
            # Resolving it here keeps the checkout clean and avoids a setup step.
            instruction = instruction.replace("@MESH_PATH@", str(MESH))

            # Wait for FreeCAD before spending a trial on it. Trials are serial, and
            # a heavy reconstruction can leave GUI dispatch busy well past the point
            # where the previous trial returned. An agent that starts against a
            # wedged session burns its turns polling get_rpc_status instead of
            # building, and the scorer then finds no solid to measure - which reads
            # as an agent failure rather than the environment problem it is.
            if not _await_idle():
                raise RuntimeError(
                    "FreeCAD GUI dispatch did not become healthy before this trial; "
                    "refusing to score a run that never had a working application."
                )

            # Build the agent from this candidate's own config, so agent.yaml, the
            # system prompt and workspace/skills/ are inside the measurement.
            with _trial_config() as (trial_name, trial_config):
                completed = await asyncio.to_thread(
                    subprocess.run,
                    [NEMO, "agents", "invoke",
                     "--agent-config", str(trial_config),
                     "--input", instruction,
                     "--no-progress"],
                    capture_output=True, text=True, timeout=TIMEOUT, cwd=AGENT_DIR,
                )
            context.metadata = {"invoke_returncode": completed.returncode}
            if completed.returncode != 0:
                # The CLI reports adapter and config errors on stdout and keeps only
                # a banner on stderr, so quoting stderr alone loses the reason.
                detail = (completed.stderr.strip() + "\n" + completed.stdout.strip()).strip()
                raise RuntimeError(
                    f"agent invocation failed ({completed.returncode}): {detail[-600:]}"
                )

            async with httpx.AsyncClient(timeout=TIMEOUT) as client:
                # Recorded so a trial can be traced back to the exact config
                # that produced it. Without this a mis-correlated trace is
                # invisible: every candidate looks alike in the trial output.
                context.metadata["agent_config"] = str(AGENT_CONFIG)
                context.metadata["agent_name"] = trial_name
                trace_id = await _await_trace(client, trial_name)
                if trace_id is None:
                    return
                context.metadata["trace_id"] = trace_id
                spans = await _get(client, "spans", filter=json.dumps({"trace_id": trace_id}))

            # Publishing nothing lets the verifier exit non-zero on absent evidence
            # rather than scoring a confident zero it has not earned.
            if spans:
                emitted: list[dict[str, Any]] = []
                # One set for the whole trace: see _tool_call_spans on why the tool
                # history is replayed and must be de-duplicated across spans.
                seen_calls: set[str] = set()
                for raw in spans:
                    emitted.append(_otlp(raw))
                    emitted.extend(_tool_call_spans(raw, seen_calls))
                # Ground truth, measured on the host and carried into the trace so a
                # container-bound verifier can gate on it.
                document, mesh = _task_targets(instruction)
                scored = TRIAL_METRIC.iou_span(document, mesh, trace_id, SCORER)
                if scored is not None:
                    emitted.append(scored)
                    context.metadata["eval_iou"] = scored["attributes"][2]["value"]["stringValue"]
                # After scoring, so the scorer still sees the document.
                _close_document(document)
                await _upload(environment, emitted)


async def _get(client: httpx.AsyncClient, path: str, **params: Any) -> list[dict[str, Any]]:
    response = await client.get(
        f"{BASE}/apis/intake/v2/workspaces/{WORKSPACE}/{path}",
        params={"page_size": 1000, **params},
    )
    response.raise_for_status()
    return response.json().get("data", [])


async def _await_trace(client: httpx.AsyncClient, name: str) -> str | None:
    """Poll Intake for the trace of the trial that ran under *name*.

    Polled because ingestion is asynchronous: the response returns before the
    spans have landed. *name* is unique to this trial, so a second match is not
    an ambiguity to resolve but evidence that the assumption behind correlation
    has broken, and the trial is refused rather than scored on a guess.
    """
    deadline = asyncio.get_running_loop().time() + TRACE_WAIT
    while True:
        matches = [
            trace["id"]
            for trace in await _get(client, "traces", page_size=20)
            # `ended_at` gates on a *finished* run: ATIF is posted at the end, so
            # a trace without it is still being written.
            if trace.get("agent_name") == name and trace.get("ended_at")
        ]
        if len(matches) > 1:
            raise RuntimeError(
                f"{len(matches)} traces carry the unique trial name {name}: "
                f"{matches}. Correlation cannot be trusted, so this trial is "
                "not scored."
            )
        if matches:
            return matches[0]
        if asyncio.get_running_loop().time() >= deadline:
            return None
        await asyncio.sleep(5)


def _otlp(span: dict[str, Any]) -> dict[str, Any]:
    """Convert one Intake span into OTLP, which is what the verifier reads.

    Intake stores flat ATIF-derived records; OTLP hangs every value off an
    ``attributes`` list. Without this the verifier sees no inspectable
    attributes and refuses to score.
    """
    return {
        "name": span.get("name", ""),
        "spanId": _otlp_id(span.get("span_id", ""), 8),
        "traceId": _otlp_id(span.get("trace_id", ""), 16),
        "attributes": [
            {"key": key, "value": {"stringValue": str(span[field])}}
            for field, key in ATTRIBUTE_KEYS.items()
            if span.get(field) not in (None, "", {}, [])
        ],
    }


def _otlp_id(value: str, size: int) -> str:
    """Render an Intake id as OTLP's base64 form.

    Intake ids are strings like ``span-579fad…`` and ``01a09fe5-da06-…``; OTLP
    expects base64-encoded fixed-width bytes. Passing the raw string through
    makes Intake reject the whole payload when it persists evaluation results.
    """
    digits = re.sub(r"[^0-9a-fA-F]", "", value)
    raw = bytes.fromhex(digits[: size * 2].ljust(size * 2, "0")) if digits else bytes(size)
    return base64.b64encode(raw).decode()


def _task_targets(instruction: str) -> tuple[str, str]:
    """Pull the document name and source mesh out of the task instruction.

    Both appear verbatim in the prompt, which is the only task content the
    host-side wrapper reliably receives — its working directory is the run's,
    not the task's.
    """
    doc = re.search(r"document named `([^`]+)`", instruction)
    mesh = re.search(r"mesh at\s*\n?`([^`]+)`", instruction)
    return (doc.group(1) if doc else "", mesh.group(1) if mesh else "")


def _freecad(method: str, *args: Any) -> Any:
    """Call one FreeCAD RPC method, returning None on any failure."""
    try:
        return getattr(xmlrpc.client.ServerProxy(FREECAD_RPC, allow_none=True), method)(*args)
    except Exception:
        return None


def _close_document(document: str) -> None:
    """Close the trial's document; documents otherwise stay resident all session."""
    if document:
        _freecad("execute_code",
                 f"import FreeCAD\n"
                 f"if {document!r} in [d.Name for d in FreeCAD.listDocuments().values()]:\n"
                 f"    FreeCAD.closeDocument({document!r})\n")


def _await_idle(timeout: float = 600.0) -> bool:
    """Wait for GUI dispatch to go idle.

    The agent's last `execute_code` often outlives the trial, and scoring into a
    busy dispatch fails — which would look like a bad model rather than a missed
    measurement.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        status = _freecad("get_rpc_status")
        if status and status["gui_dispatch"]["state"] == "healthy":
            return True
        time.sleep(2)
    return False


def _tool_call_spans(
    span: dict[str, Any], seen: set[str] | None = None
) -> list[dict[str, Any]]:
    """Surface the tool calls buried inside an Intake span's JSON payloads.

    Intake records one span per LangGraph node (`model`, `tools`), while the
    actual MCP calls — `execute_code`, `read_file` — sit nested inside those
    payloads. A trace-reading metric looking for `execute_code` finds nothing
    unless each call is emitted as its own span.

    *seen* carries the ids already emitted across earlier spans of the same
    trace. Pass one set for the whole trace: every model turn replays the entire
    tool history, so without it the same call is emitted once per turn that
    mentioned it. Measured on one reconstruction, that is 1,241 emitted spans
    for 17 real calls — a ~70x inflation of every per-tool count a metric reads.
    """
    calls: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "tool_call" and node.get("name"):
                calls.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for field in ("output", "raw_attributes", "input"):
        raw = span.get(field)
        if isinstance(raw, str) and raw.strip()[:1] in "{[":
            try:
                walk(json.loads(raw))
            except ValueError:
                continue

    parent = _otlp_id(span.get("span_id", ""), 8)
    trace = _otlp_id(span.get("trace_id", ""), 16)
    seen = seen if seen is not None else set()
    out: list[dict[str, Any]] = []
    for index, call in enumerate(calls):
        # A tool call is identified by its own `id`, which is stable across every
        # replay of the history. Position is the fallback for the rare call that
        # carries no id, and is scoped to the span so two spans cannot collide.
        call_id = str(call.get("id") or f"{span.get('span_id', '')}#{index}")
        if call_id in seen:
            continue
        seen.add(call_id)
        name = str(call.get("name"))
        body = json.dumps(call, ensure_ascii=False)
        failed = "traceback (most recent call last)" in body.lower()
        out.append({
            "name": name,
            "spanId": _otlp_id(call_id, 8),
            "parentSpanId": parent,
            "traceId": trace,
            # OTLP status is an enum, not free text. Intake's protobuf parser
            # rejects the whole payload on anything else.
            "status": {"code": "STATUS_CODE_ERROR" if failed else "STATUS_CODE_OK"},
            "attributes": [
                {"key": "openinference.span.kind", "value": {"stringValue": "TOOL"}},
                {"key": "tool.name", "value": {"stringValue": name}},
                {"key": "tool.output", "value": {"stringValue": body[:20000]}},
            ],
        })
    return out


async def _upload(environment: BaseEnvironment, spans: list[dict[str, Any]]) -> None:
    """Write one OTLP request object into the environment as JSONL."""
    envelope = {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]}
    with tempfile.TemporaryDirectory() as tmp:
        local = Path(tmp) / "agent.jsonl"
        with local.open("w", encoding="utf-8") as handle:
            json.dump(envelope, handle)
        await environment.upload_file(local, f"{TRACE_DIR}/agent.jsonl")
