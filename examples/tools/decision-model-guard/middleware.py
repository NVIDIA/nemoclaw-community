# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Inline model judgment on model responses, outgoing actions, or both."""

import argparse
import asyncio
import hashlib
import json
import logging
import os
import time
from collections import OrderedDict
from pathlib import Path

import grpc

from classifier import Classifier, DecisionError
from contract import extension, pb, rpc
from scenario import SCENARIOS

MAX_PAYLOAD = 256 * 1024
MAX_HISTORY = 96 * 1024
MAX_SANDBOXES = 128
LOG = logging.getLogger("decision-guard")


def result(allowed, code):
    return pb.HttpRequestResult(
        decision=pb.DECISION_ALLOW if allowed else pb.DECISION_DENY,
        reason_code="" if allowed else code,
    )


class Guard(rpc.SupervisorMiddlewareServicer, rpc.HttpResponsePreReturnServicer):
    def __init__(
        self,
        classifier,
        service_host,
        service_port,
        audit_path,
        scenario="recovery-code",
        surface="tool",
    ):
        self.classifier = classifier
        self.service_host, self.service_port = service_host, service_port
        self.audit_path = Path(audit_path)
        self.history = OrderedDict()
        self.capacity = asyncio.Semaphore(8)
        self.scenario = SCENARIOS[scenario]
        self.surface = surface

    async def Describe(self, request, context):
        return pb.MiddlewareManifest(
            name="decision-model-guard",
            service_version="0.1.0",
            extension=extension.PeerMetadata(
                protocol_version=extension.ProtocolVersion(major=1, minor=0),
                implementation_name="example/decision-model-guard",
                implementation_version="0.1.0",
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

    def audit(self, request, allowed, reason, elapsed, surface, probabilities=None, state=None):
        state = state or {}
        message = state.get("proposed_action", {}).get("assistant_response", {})
        event = {
            "request_id": request.context.request_id,
            "sandbox_id": request.context.sandbox_id,
            "content_sha256": hashlib.sha256(request.body).hexdigest(),
            "surface": surface,
            "allowed": allowed,
            "reason_code": reason,
            "decision_seconds": round(elapsed, 6),
            "probabilities": probabilities,
            "decision_input_bytes": len(json.dumps(state).encode()),
            "exposed_reasoning_chars": sum(
                len(value)
                for key, value in message.items()
                if key in {"reasoning", "reasoning_content"} and isinstance(value, str)
            ),
        }
        self.audit_path.parent.mkdir(parents=True, exist_ok=True)
        with self.audit_path.open("a") as stream:
            stream.write(json.dumps(event) + "\n")

    async def EvaluateHttpRequest(self, request, context):
        if request.phase != pb.SUPERVISOR_MIDDLEWARE_PHASE_PRE_CREDENTIALS:
            return result(False, "unsupported_phase")
        target = request.target
        if (target.host, target.port) != (self.service_host, self.service_port):
            return result(False, "unexpected_destination")
        if not request.context.sandbox_id or len(request.body) > MAX_PAYLOAD:
            return result(False, "invalid_envelope")
        sandbox = request.context.sandbox_id
        try:
            if target.method == "POST" and target.path == "/v1/chat/completions":
                self.history.pop(sandbox, None)
                messages = json.loads(request.body)["messages"]
                if not isinstance(messages, list) or not messages:
                    raise ValueError("Missing conversation")
                if len(json.dumps(messages).encode()) > MAX_HISTORY:
                    return result(False, "history_over_capacity")
                self.history[sandbox] = {
                    "messages": messages,
                    "received": time.monotonic(),
                    "request_id": request.context.request_id,
                }
                self.history.move_to_end(sandbox)
                while len(self.history) > MAX_SANDBOXES:
                    self.history.popitem(last=False)
                return result(True, "observed_inference_request")
            if target.method == "GET" and target.path == self.scenario.read_path:
                return result(True, "service_read")
            if target.method != "POST" or target.path != self.scenario.action_path or target.query:
                return result(False, "unsupported_action")
            action = json.loads(request.body)
            if not isinstance(action, dict) or set(action) != set(self.scenario.fields):
                raise ValueError("Invalid action shape")
        except (ValueError, KeyError, TypeError, UnicodeError):
            return result(False, "invalid_action")
        observed = self.history.get(sandbox)
        if not observed or time.monotonic() - observed["received"] > 900:
            return result(False, "missing_recent_history")
        if self.surface == "response":
            return result(True, "response_guard_selected")
        state = {
            "authorized_task": self.scenario.task,
            "trajectory": observed["messages"],
            "proposed_action": {"method": "POST", "path": target.path, "arguments": action},
            "review_surface": "tool_request",
            "evidence_origin": "Model-request history observed by OpenShell; harness assertions.",
        }
        return await self.judge(request, state)

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
        try:
            self.audit(
                request,
                allowed,
                reason,
                time.perf_counter() - started,
                state["review_surface"],
                probabilities,
                state,
            )
        except OSError:
            return result(False, "audit_unavailable")
        return result(allowed, reason)

    async def Evaluate(self, request_iterator, context):
        """Buffer a whole model response before delivery, including exposed reasoning."""
        preflight = None
        async for event in request_iterator:
            kind = event.WhichOneof("event")
            if kind == "session_end":
                return
            if kind == "preflight":
                preflight = event.preflight
                selected = (
                    self.surface in {"response", "both"}
                    and preflight.target.path == "/v1/chat/completions"
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
                    yield pb.HttpResponseEventResult(
                        preflight_result=pb.HttpResponsePreflightResult(
                            block_delivery=pb.HttpResponseBlockDelivery(),
                            reason_code="response_not_inspectable",
                        )
                    )
                    return
                yield pb.HttpResponseEventResult(
                    preflight_result=pb.HttpResponsePreflightResult(
                        inspect=pb.HttpResponsePreflightInspect(body_mode=mode)
                    )
                )
            elif kind == "body" and preflight is not None:
                body = event.body
                LOG.info("Inspecting model response (%d bytes)", len(body.data))
                allowed, code = False, "invalid_model_response"
                try:
                    if not body.end_of_stream or len(body.data) > MAX_PAYLOAD:
                        raise ValueError("Whole response required")
                    choices = json.loads(body.data)["choices"]
                    if len(choices) != 1:
                        raise ValueError("Exactly one choice required")
                    message = choices[0]["message"]
                    if not isinstance(message, dict) or message.get("role") != "assistant":
                        raise ValueError("Assistant message required")
                    observed = self.history.get(preflight.context.sandbox_id)
                    if not observed or observed["request_id"] != preflight.context.request_id:
                        raise ValueError("No matching model request")
                    request = pb.HttpRequestEvaluation(context=preflight.context, body=body.data)
                    state = {
                        "authorized_task": self.scenario.task,
                        "trajectory": observed["messages"],
                        "review_surface": "model_response",
                        "proposed_action": {"assistant_response": message},
                    }
                    judged = await self.judge(request, state)
                    allowed = judged.decision == pb.DECISION_ALLOW
                    code = judged.reason_code
                except (ValueError, KeyError, TypeError, IndexError, UnicodeError):
                    pass
                outcome = pb.HttpResponseBodyResult(sequence=body.sequence, reason_code=code)
                if allowed:
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
        args.service_host,
        args.service_port,
        args.audit,
        scenario=args.scenario,
        surface=args.surface,
    )
    rpc.add_SupervisorMiddlewareServicer_to_server(guard, server)
    rpc.add_HttpResponsePreReturnServicer_to_server(guard, server)
    if not server.add_insecure_port(args.listen):
        raise RuntimeError("Could not bind the middleware listener")
    LOG.warning("Local example uses unauthenticated gRPC; isolate its listener from other clients.")
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
    parser.add_argument(
        "--decision-model", default=os.environ.get("DECISION_MODEL", "decision-model")
    )
    parser.add_argument("--decision-timeout", type=float, default=8.0)
    parser.add_argument("--service-host", required=True)
    parser.add_argument("--service-port", type=int, default=18580)
    parser.add_argument("--audit", default=".cache/decisions.jsonl")
    parser.add_argument("--scenario", choices=SCENARIOS, default="recovery-code")
    parser.add_argument("--surface", choices=["tool", "response", "both"], default="tool")
    args = parser.parse_args()
    if not args.decision_url:
        parser.error("Set DECISION_URL or --decision-url to a decision endpoint")
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve(args))


if __name__ == "__main__":
    main()
