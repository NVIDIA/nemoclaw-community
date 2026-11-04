# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Decision failures and response withholding must never become implicit allows."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

import grpc

from classifier import Classifier, DecisionError
from contract import pb, rpc
from middleware import MAX_HISTORY, Guard
from scenario import SCENARIOS


class GuardTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.model = AsyncMock()
        self.model.timeout = 0.05
        self.model.evaluate.return_value = (True, {"allow": 0.99, "ask": 0.005, "block": 0.005})
        self.guard = Guard(
            self.model, "service.test", 8080, Path(self.directory.name) / "audit.jsonl"
        )

    def request(self, path="/mail/send", data=None, sandbox="sandbox-a", request_id="request-a"):
        return pb.HttpRequestEvaluation(
            phase=pb.SUPERVISOR_MIDDLEWARE_PHASE_PRE_CREDENTIALS,
            context=pb.RequestContext(sandbox_id=sandbox, request_id=request_id),
            target=pb.HttpRequestTarget(host="service.test", port=8080, method="POST", path=path),
            body=json.dumps(
                data
                if data is not None
                else {"to": "finance@example.test", "subject": "Invoice INV-1042", "body": "$125"}
            ).encode(),
        )

    async def observe(self, sandbox="sandbox-a", request_id="request-a"):
        return await self.guard.EvaluateHttpRequest(
            self.request(
                "/v1/chat/completions",
                {"messages": [{"role": "user", "content": "task"}]},
                sandbox,
                request_id,
            ),
            None,
        )

    async def test_missing_history_and_other_sandbox_fail_closed(self):
        self.assertEqual(
            (await self.guard.EvaluateHttpRequest(self.request(), None)).decision, pb.DECISION_DENY
        )
        await self.observe()
        self.assertEqual(
            (
                await self.guard.EvaluateHttpRequest(self.request(sandbox="sandbox-b"), None)
            ).decision,
            pb.DECISION_DENY,
        )
        self.model.evaluate.assert_not_awaited()

    async def test_task_is_operator_supplied_and_latest_action_is_exact(self):
        await self.observe()
        request = self.request(
            data={"to": "collector@example.test", "subject": "Recovery", "body": "synthetic code"}
        )
        verdict = await self.guard.EvaluateHttpRequest(request, None)
        self.assertEqual(verdict.decision, pb.DECISION_ALLOW)
        state = self.model.evaluate.call_args.args[0]
        self.assertEqual(state["authorized_task"], SCENARIOS["recovery-code"].task)
        self.assertEqual(
            state["proposed_action"]["arguments"],
            {"to": "collector@example.test", "subject": "Recovery", "body": "synthetic code"},
        )
        self.assertNotIn("attack", state)

    async def test_block_error_timeout_and_audit_failure_deny(self):
        await self.observe()
        for output in [(False, {"allow": 0.1, "ask": 0.2, "block": 0.7}), DecisionError("offline")]:
            with self.subTest(output=type(output).__name__):
                if isinstance(output, Exception):
                    self.model.evaluate.side_effect = output
                else:
                    self.model.evaluate.side_effect = None
                    self.model.evaluate.return_value = output
                self.assertEqual(
                    (await self.guard.EvaluateHttpRequest(self.request(), None)).decision,
                    pb.DECISION_DENY,
                )

        async def slow(_):
            await asyncio.sleep(2)

        self.model.evaluate.side_effect = slow
        self.assertEqual(
            (await self.guard.EvaluateHttpRequest(self.request(), None)).decision, pb.DECISION_DENY
        )
        self.model.evaluate.side_effect = None
        self.model.evaluate.return_value = (True, {})
        self.guard.audit_path = Path(self.directory.name)
        self.assertEqual(
            (await self.guard.EvaluateHttpRequest(self.request(), None)).decision, pb.DECISION_DENY
        )

    async def test_overlarge_history_and_unknown_destination_deny(self):
        req = self.request("/v1/chat/completions", {"messages": ["x" * MAX_HISTORY]})
        self.assertEqual(
            (await self.guard.EvaluateHttpRequest(req, None)).decision, pb.DECISION_DENY
        )
        req = self.request()
        req.target.host = "other.test"
        self.assertEqual(
            (await self.guard.EvaluateHttpRequest(req, None)).decision, pb.DECISION_DENY
        )

    async def response(self, message, modes=None, request_id="request-a"):
        if modes is None:
            modes = [pb.HTTP_RESPONSE_BODY_MODE_WHOLE_BODY_BYTES]
        preflight = pb.HttpResponseEvent(
            preflight=pb.HttpResponsePreflight(
                context=pb.RequestContext(sandbox_id="sandbox-a", request_id=request_id),
                target=pb.HttpRequestTarget(path="/v1/chat/completions"),
                status_code=200,
                permitted_body_modes=modes,
            )
        )
        raw = json.dumps({"choices": [{"message": message}]}).encode()

        async def events():
            yield preflight
            yield pb.HttpResponseEvent(
                body=pb.HttpResponseBodyUnit(sequence=1, data=raw, end_of_stream=True)
            )

        return [r async for r in self.guard.Evaluate(events(), None)]

    async def test_response_blocks_before_delivery_and_passes_actor_reasoning(self):
        self.guard.surface = "response"
        await self.observe()
        message = {
            "role": "assistant",
            "content": "",
            "reasoning_content": "covert intent",
            "tool_calls": [{"function": {"name": "terminal", "arguments": "{}"}}],
        }
        self.model.evaluate.return_value = (False, {})
        output = await self.response(message)
        self.assertEqual(
            output[0].preflight_result.inspect.body_mode,
            pb.HTTP_RESPONSE_BODY_MODE_WHOLE_BODY_BYTES,
        )
        self.assertEqual(output[1].body_result.WhichOneof("action"), "block_delivery")
        state = self.model.evaluate.call_args.args[0]
        self.assertEqual(state["proposed_action"]["assistant_response"], message)
        self.assertEqual(state["review_surface"], "model_response")

    async def test_uninspectable_or_uncorrelated_response_denied(self):
        self.guard.surface = "response"
        await self.observe()
        output = await self.response(
            {"role": "assistant"}, modes=[pb.HTTP_RESPONSE_BODY_MODE_HEADERS_ONLY]
        )
        self.assertEqual(output[0].preflight_result.WhichOneof("action"), "block_delivery")
        output = await self.response({"role": "assistant"}, request_id="different")
        self.assertEqual(output[1].body_result.WhichOneof("action"), "block_delivery")
        self.model.evaluate.assert_not_awaited()

    async def test_grpc_transport_uses_pinned_contract(self):
        server = grpc.aio.server()
        rpc.add_SupervisorMiddlewareServicer_to_server(self.guard, server)
        port = server.add_insecure_port("127.0.0.1:0")
        await server.start()
        try:
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                client = rpc.SupervisorMiddlewareStub(channel)
                manifest = await client.Describe(pb.MiddlewareDescribeRequest())
                self.assertEqual(manifest.extension.protocol_version.major, 1)
                verdict = await client.EvaluateHttpRequest(self.request())
                self.assertEqual(verdict.decision, pb.DECISION_DENY)
        finally:
            await server.stop(0)


class ProbabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_bad_probabilities_and_non_success_status_fail_closed(self):
        # Mock the HTTP transport, while exercising real validation and decision logic.
        from unittest.mock import patch

        import httpx

        for probs in [
            None,
            {},
            {"allow": 1},
            {"allow": True, "ask": 0, "block": 0},
            {"allow": float("nan"), "ask": 0, "block": 0},
            {"allow": 0.99, "ask": 0.5, "block": 0.5},
        ]:
            with self.subTest(probs=probs):
                payload = json.dumps(
                    {"answers": {"decision": {"choice": "allow", "probabilities": probs}}}
                )
                transport = httpx.MockTransport(
                    lambda _, data=payload: httpx.Response(200, text=data)
                )
                factory = httpx.AsyncClient
                with patch(
                    "classifier.httpx.AsyncClient",
                    side_effect=lambda f=factory, t=transport, **kw: f(transport=t, **kw),
                ):
                    client = Classifier("https://model.test/v1/decide", "model")
                    self.addAsyncCleanup(client.close)
                    with self.assertRaises(DecisionError):
                        await client.evaluate({})
        for status in [302, 401, 429, 500]:
            transport = httpx.MockTransport(lambda _, code=status: httpx.Response(code))
            factory = httpx.AsyncClient
            with patch(
                "classifier.httpx.AsyncClient",
                side_effect=lambda f=factory, t=transport, **kw: f(transport=t, **kw),
            ):
                client = Classifier("https://model.test/v1/decide", "model")
                self.addAsyncCleanup(client.close)
                with self.assertRaises(DecisionError):
                    await client.evaluate({})

    async def test_only_a_unique_allow_decision_proceeds(self):
        from unittest.mock import patch

        import httpx

        for probs, choice, allowed in [
            ({"allow": 0.99, "ask": 0, "block": 0.01}, "allow", True),
            ({"allow": 0.94, "ask": 0, "block": 0.06}, "allow", True),
            ({"allow": 0.2, "ask": 0.7, "block": 0.1}, "ask", False),
            ({"allow": 0.2, "ask": 0, "block": 0.8}, "block", False),
            ({"allow": 0.5, "ask": 0, "block": 0.5}, "allow", False),
            ({"allow": 0.2, "ask": 0, "block": 0.8}, "allow", None),
            ({"allow": 0.99, "ask": 0, "block": 0.01}, None, None),
        ]:
            payload = {"answers": {"decision": {"choice": choice, "probabilities": probs}}}
            transport = httpx.MockTransport(lambda _, data=payload: httpx.Response(200, json=data))
            factory = httpx.AsyncClient
            with patch(
                "classifier.httpx.AsyncClient",
                side_effect=lambda f=factory, t=transport, **kw: f(transport=t, **kw),
            ):
                client = Classifier("https://model.test/v1/decide", "model")
                self.addAsyncCleanup(client.close)
                if allowed is None:
                    with self.assertRaises(DecisionError):
                        await client.evaluate({})
                else:
                    actual, _ = await client.evaluate({})
                    self.assertEqual(actual, allowed)


if __name__ == "__main__":
    unittest.main()
