# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""OpenShell supervisor middleware that asks a decision model about each agent tool call."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import socket
import time
from collections import OrderedDict
from pathlib import Path

import grpc

from classifier import Classifier, DecisionError
from contract import extension, pb, rpc

MAX_PAYLOAD = 256 * 1024
MAX_HISTORY = 96 * 1024
MAX_SANDBOXES = 128
HISTORY_SECONDS = 900
READ_METHODS = {"GET", "HEAD", "OPTIONS"}
LOG = logging.getLogger("decision-guard")


def result(allowed, code):
    return pb.HttpRequestResult(
        decision=pb.DECISION_ALLOW if allowed else pb.DECISION_DENY,
        reason_code="" if allowed else code,
    )


def parse_json(body):
    try:
        return json.loads(body) if body else None
    except (ValueError, UnicodeError):
        return None


def conversation(messages, drop_system=False):
    """The conversation the decision model sees.

    The system prompt is the operator's instructions to the agent and is useful
    context, so it is kept by default. The misaligned-agent demo hides a test
    goal in the system prompt, so it sets drop_system: a real misaligned model
    would have no such prompt, only the behavior.
    """
    if not drop_system:
        return list(messages)
    return [m for m in messages if not (isinstance(m, dict) and m.get("role") == "system")]


def tool_call(target, payload, body):
    """Return the action to judge, or None for traffic that changes nothing."""
    if isinstance(payload, dict) and payload.get("jsonrpc") == "2.0":
        if payload.get("method") != "tools/call":
            return None  # MCP protocol traffic: initialize, tools/list, notifications.
        params = payload.get("params") or {}
        return {"tool": params.get("name"), "arguments": params.get("arguments")}
    if target.method in READ_METHODS:
        return None
    return {
        "method": target.method,
        "path": target.path,
        "arguments": payload if payload is not None else body.decode("utf-8", "replace"),
    }


def assistant_message(body):
    """Rebuild the assistant message from a complete response, streamed (SSE) or not."""
    text = body.decode("utf-8")
    if not text.lstrip().startswith("data:"):
        choices = json.loads(text)["choices"]
        if len(choices) != 1:
            raise ValueError("Exactly one choice required")
        return choices[0]["message"]
    message, calls = {"role": "assistant", "content": ""}, {}
    for line in text.splitlines():
        if not line.startswith("data:") or line[5:].strip() == "[DONE]":
            continue
        for choice in json.loads(line[5:]).get("choices", []):
            delta = choice.get("delta") or {}
            for key in ("content", "reasoning_content", "reasoning"):
                if delta.get(key):
                    message[key] = message.get(key, "") + delta[key]
            for call in delta.get("tool_calls") or []:
                slot = calls.setdefault(
                    call.get("index", 0), {"type": "function", "function": {"arguments": ""}}
                )
                slot["id"] = call.get("id") or slot.get("id")
                function = call.get("function") or {}
                if function.get("name"):
                    slot["function"]["name"] = function["name"]
                slot["function"]["arguments"] += function.get("arguments") or ""
    if calls:
        message["tool_calls"] = [calls[i] for i in sorted(calls)]
    return message


def as_event_stream(completion):
    """Turn a complete chat completion into the event stream that the agent asked for."""
    choice = completion["choices"][0]
    message = choice["message"]
    delta = {
        k: message[k]
        for k in ("role", "content", "reasoning_content", "reasoning")
        if message.get(k) is not None
    }
    if message.get("tool_calls"):
        delta["tool_calls"] = [dict(call, index=i) for i, call in enumerate(message["tool_calls"])]
    base = {
        "id": completion.get("id"),
        "object": "chat.completion.chunk",
        "created": completion.get("created"),
        "model": completion.get("model"),
    }
    events = [
        dict(base, choices=[{"index": 0, "delta": delta, "finish_reason": None}]),
        dict(
            base,
            choices=[{"index": 0, "delta": {}, "finish_reason": choice.get("finish_reason")}],
            usage=completion.get("usage"),
        ),
    ]
    return ("".join(f"data: {json.dumps(e)}\n\n" for e in events) + "data: [DONE]\n\n").encode()


class Guard(rpc.SupervisorMiddlewareServicer, rpc.HttpResponsePreReturnServicer):
    def __init__(self, classifier, audit_path, demo_trace=None, surface="both", drop_system=False):
        self.classifier = classifier
        self.drop_system = drop_system
        self.audit_path = Path(audit_path)
        self.demo_trace = Path(demo_trace) if demo_trace else None
        self.surface = surface
        self.history = OrderedDict()
        self.capacity = asyncio.Semaphore(8)

    async def Describe(self, request, context):
        return pb.MiddlewareManifest(
            name="decision-model-guard",
            service_version="0.2.0",
            extension=extension.PeerMetadata(
                protocol_version=extension.ProtocolVersion(major=1, minor=0),
                implementation_name="example/decision-model-guard",
                implementation_version="0.2.0",
                supported_capabilities=["openshell.supervisor-middleware.contract"],
            ),
            bindings=[
                pb.MiddlewareBinding(
                    operation=pb.SUPERVISOR_MIDDLEWARE_OPERATION_HTTP_REQUEST,
                    phase=pb.SUPERVISOR_MIDDLEWARE_PHASE_PRE_CREDENTIALS,
                    max_payload_bytes=MAX_PAYLOAD,
                ),
                pb.MiddlewareBinding(
                    operation=pb.SUPERVISOR_MIDDLEWARE_OPERATION_HTTP_RESPONSE,
                    phase=pb.SUPERVISOR_MIDDLEWARE_PHASE_PRE_RETURN,
                    max_payload_bytes=MAX_PAYLOAD,
                ),
            ],
        )

    async def ValidateConfig(self, request, context):
        return pb.ValidateConfigResponse(valid=not bool(request.config.fields))

    def log(self, event):
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as stream:
            stream.write(json.dumps({"time": time.time(), **event}) + "\n")

    def demo(self, kind, request_context, **fields):
        """DEMO ONLY: write full decision context for dashboard.py when --demo-trace is set.

        Unlike the audit log, these events contain conversation text. A write
        failure never changes a decision.
        """
        if not self.demo_trace:
            return
        event = {
            "kind": kind,
            "time": time.time(),
            "sandbox_id": request_context.sandbox_id,
            "sandbox": request_context.sandbox,
            "request_id": request_context.request_id,
            **fields,
        }
        try:
            self.demo_trace.parent.mkdir(parents=True, exist_ok=True)
            with self.demo_trace.open("a") as stream:
                stream.write(json.dumps(event, default=str) + "\n")
        except (OSError, TypeError, ValueError):
            LOG.warning("Could not write the demo trace")

    async def EvaluateHttpRequest(self, request, context):
        if request.phase != pb.SUPERVISOR_MIDDLEWARE_PHASE_PRE_CREDENTIALS:
            return result(False, "unsupported_phase")
        if not request.context.sandbox_id or len(request.body) > MAX_PAYLOAD:
            return result(False, "invalid_envelope")
        target, sandbox = request.target, request.context.sandbox_id
        payload = parse_json(request.body)

        if target.method == "POST" and target.path.endswith("/chat/completions"):
            # A model call: remember the conversation so far for this sandbox.
            messages = payload.get("messages") if isinstance(payload, dict) else None
            if not isinstance(messages, list) or not messages:
                return result(False, "invalid_model_request")
            if len(json.dumps(messages).encode()) > MAX_HISTORY:
                return result(False, "history_over_capacity")
            judge_response = self.surface in {"response", "both"}
            wants_stream = bool(payload.get("stream"))
            self.history[sandbox] = {
                "messages": messages,
                "received": time.monotonic(),
                "request_id": request.context.request_id,
                "wants_stream": judge_response and wants_stream,
            }
            self.history.move_to_end(sandbox)
            while len(self.history) > MAX_SANDBOXES:
                self.history.popitem(last=False)
            self.log({"event": "model_request", "sandbox_id": sandbox})
            self.demo(
                "model_request",
                request.context,
                message_count=len(messages),
                last_message=messages[-1],
            )
            allowed = result(True, "model_request")
            if judge_response:
                # Ask for one complete, uncompressed response that the guard can read
                # whole. The guard turns it back into a stream after the decision.
                allowed.header_mutations.add().remove.name = "accept-encoding"
                if wants_stream:
                    payload["stream"] = False
                    payload.pop("stream_options", None)
                    allowed.body = json.dumps(payload).encode()
                    allowed.has_body = True
            return allowed

        action = tool_call(target, payload, request.body)
        if action is None or self.surface == "response":
            return result(True, "no_action" if action is None else "response_surface_only")
        observed = self.history.get(sandbox)
        if not observed or time.monotonic() - observed["received"] > HISTORY_SECONDS:
            return result(False, "missing_recent_history")
        state = {
            "trajectory": conversation(observed["messages"], self.drop_system),
            "proposed_action": action,
        }
        return await self.judge(request, state)

    async def Evaluate(self, request_iterator, context):
        """Hold each complete model response until the decision model allows it."""
        preflight = None
        async for event in request_iterator:
            kind = event.WhichOneof("event")
            if kind == "session_end":
                return
            if kind == "preflight":
                preflight = event.preflight
                selected = self.surface in {"response", "both"} and preflight.target.path.endswith(
                    "/chat/completions"
                )
                if not selected or preflight.status_code >= 400:
                    yield pb.HttpResponseEventResult(
                        preflight_result=pb.HttpResponsePreflightResult(
                            skip=pb.HttpResponsePreflightSkip()
                        )
                    )
                    return
                mode = pb.HTTP_RESPONSE_BODY_MODE_WHOLE_BODY_BYTES
                if mode not in preflight.permitted_body_modes:
                    headers = {h.name: h.value for h in preflight.headers}
                    LOG.warning("Response not inspectable; headers: %s", headers)
                    yield pb.HttpResponseEventResult(
                        preflight_result=pb.HttpResponsePreflightResult(
                            block_delivery=pb.HttpResponseBlockDelivery(),
                            reason_code="response_not_inspectable",
                        )
                    )
                    return
                inspect = pb.HttpResponsePreflightInspect(body_mode=mode)
                observed = self.history.get(preflight.context.sandbox_id) or {}
                if observed.get("wants_stream"):
                    write = inspect.header_mutations.add().write
                    write.name, write.value = "content-type", "text/event-stream"
                    write.on_existing = pb.EXISTING_HEADER_ACTION_OVERWRITE
                yield pb.HttpResponseEventResult(
                    preflight_result=pb.HttpResponsePreflightResult(inspect=inspect)
                )
            elif kind == "body" and preflight is not None:
                body = event.body
                allowed, code, observed = False, "invalid_model_response", {}
                try:
                    if not body.end_of_stream or len(body.data) > MAX_PAYLOAD:
                        raise ValueError("Whole response required")
                    message = assistant_message(body.data)
                    observed = self.history.get(preflight.context.sandbox_id)
                    if not observed or observed["request_id"] != preflight.context.request_id:
                        raise ValueError("No matching model request")
                    request = pb.HttpRequestEvaluation(context=preflight.context, body=body.data)
                    state = {
                        "trajectory": conversation(observed["messages"], self.drop_system),
                        "proposed_action": {"assistant_response": message},
                    }
                    judged = await self.judge(request, state)
                    allowed, code = judged.decision == pb.DECISION_ALLOW, judged.reason_code
                except (ValueError, KeyError, TypeError, IndexError, UnicodeError):
                    pass
                outcome = pb.HttpResponseBodyResult(sequence=body.sequence, reason_code=code)
                if allowed and observed.get("wants_stream"):
                    outcome.transform.data = as_event_stream(json.loads(body.data))
                elif allowed:
                    outcome.pass_through.CopyFrom(pb.HttpResponseBodyPassThrough())
                else:
                    outcome.block_delivery.CopyFrom(pb.HttpResponseBlockDelivery())
                yield pb.HttpResponseEventResult(body_result=outcome)
                if not allowed:
                    return
            elif kind == "trailers":
                yield pb.HttpResponseEventResult(trailers_result=pb.HttpResponseTrailersResult())
            else:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "Unexpected response event")

    async def judge(self, request, state):
        started = time.perf_counter()
        allowed, probabilities, reason = False, None, "decision_unavailable"
        try:
            async with asyncio.timeout(self.classifier.timeout + 0.5):
                async with self.capacity:
                    allowed, probabilities = await self.classifier.evaluate(state)
            reason = "decision_allow" if allowed else "decision_hold"
        except (DecisionError, TimeoutError):
            pass
        elapsed = time.perf_counter() - started
        try:
            self.log(
                {
                    "event": "decision",
                    "sandbox_id": request.context.sandbox_id,
                    "request_id": request.context.request_id,
                    "content_sha256": hashlib.sha256(request.body).hexdigest(),
                    "allowed": allowed,
                    "reason_code": reason,
                    "decision_seconds": round(elapsed, 3),
                    "probabilities": probabilities,
                }
            )
        except OSError:
            return result(False, "audit_unavailable")
        self.demo(
            "decision",
            request.context,
            allowed=allowed,
            reason_code=reason,
            probabilities=probabilities,
            decision_seconds=round(elapsed, 3),
            trajectory=state["trajectory"],
            proposed_action=state["proposed_action"],
        )
        return result(allowed, reason)


async def serve(args):
    classifier = Classifier(
        args.decision_url,
        args.decision_model,
        os.environ.get("DECISION_API_KEY", ""),
        timeout=args.decision_timeout,
    )
    server = grpc.aio.server(options=[("grpc.max_receive_message_length", 1024 * 1024)])
    guard = Guard(
        classifier,
        args.audit,
        demo_trace=args.demo_trace,
        surface=args.surface,
        drop_system=args.drop_system_prompt,
    )
    rpc.add_SupervisorMiddlewareServicer_to_server(guard, server)
    rpc.add_HttpResponsePreReturnServicer_to_server(guard, server)
    host, port = args.listen.rsplit(":", 1)
    if not server.add_insecure_port(f"{socket.gethostbyname(host)}:{port}"):
        raise RuntimeError("Could not bind the middleware listener")
    LOG.warning("Guard listening on %s with unauthenticated gRPC (local use only).", args.listen)
    if args.demo_trace:
        LOG.warning("DEMO ONLY: %s receives full conversation text.", args.demo_trace)
    await server.start()
    try:
        await server.wait_for_termination()
    finally:
        await server.stop(0)
        await classifier.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--listen", default="127.0.0.1:18551")
    parser.add_argument("--decision-url", default=os.environ.get("DECISION_URL"))
    parser.add_argument("--decision-model", default=os.environ.get("DECISION_MODEL"))
    parser.add_argument("--decision-timeout", type=float, default=8.0)
    parser.add_argument("--audit", default=".cache/data/decisions.jsonl")
    parser.add_argument(
        "--surface",
        choices=["tool", "response", "both"],
        default=os.environ.get("GUARD_SURFACE", "both"),
        help="Judge tool calls, model responses, or both",
    )
    parser.add_argument(
        "--drop-system-prompt",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("GUARD_DROP_SYSTEM_PROMPT", "").lower() in {"1", "true", "yes"},
        help="Hide system messages from the decision model. For the misaligned-agent demo only.",
    )
    parser.add_argument(
        "--demo-trace",
        help="DEMO ONLY: also write full decision inputs, including conversation text, "
        "to this JSONL file for dashboard.py",
    )
    args = parser.parse_args()
    if not (args.decision_url and args.decision_model):
        parser.error("Set DECISION_URL and DECISION_MODEL")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
