#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for the host-side release gate (release_gate.py). Stdlib only, no
network: the forecast/sign/settle seams are injected.

The release contract has exactly TWO authorization paths, and these tests pin
each one separately (same rule as the README and the module docstring):
  * Automated release  -> ProcessIntent: settles unattended ONLY on a fresh
    GO; HOLD/STOP/failure never settle here.
  * Human-approved release -> ReviewRound2 (B3) + AuditRegressions (A1/A2):
    a HELD intent needs a named human + host-side token AND a fresh re-screen;
    a fresh STOP still refuses. A STOP is terminal on both paths.

MUTATION NOTES per class: each names the invariant that block pins, so a
surviving mutant points at the exact contract broken.
"""

import unittest

from release_gate import (
    HOLD,
    REFUSE,
    RELEASE,
    approve_record,
    decide_release,
    finalize_release,
    new_record,
    process_approval,
    process_intent,
    reserve_slot,
    resolve_gate_bind,
    simulate_signature,
    validate_intent,
)

PAYEE = "0x02c2FCAFce36b4AADb39625866Bc6b1699D83043"


def verdict(v, **extra):
    out = {"verdict": v, "hard_stop": v == "STOP",
           "reasons": ["r1", "r2"], "receipt_id": "bw_x"}
    out.update(extra)
    return out


class ValidateIntent(unittest.TestCase):
    # MUTATION NOTES: the address gate is the anti-garbage filter; the
    # lowercase step pins reputation-key canonicalization; plain-decimal
    # amounts only (no scientific notation reaches the verdict service).

    def test_valid_intent_normalizes(self):
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": "0.014"})
        self.assertIsNone(err)
        self.assertEqual(intent["counterparty"], PAYEE.lower())
        self.assertEqual(intent["amount"], "0.014")
        self.assertEqual(intent["asset"], "USDC")
        self.assertEqual(intent["chain"], "base")

    def test_optional_fields_pass_through(self):
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": "1", "asset": "USDC",
             "chain": "base-sepolia", "resource": "https://api.example.com/x"})
        self.assertIsNone(err)
        self.assertEqual(intent["chain"], "base-sepolia")
        self.assertEqual(intent["resource"], "https://api.example.com/x")

    def test_rejects_bad_counterparty_and_amounts(self):
        for payload in (
            {"counterparty": "bob", "amount": "1"},
            {"counterparty": PAYEE},
            {"counterparty": PAYEE, "amount": "0"},
            {"counterparty": PAYEE, "amount": "-1"},
            {"counterparty": PAYEE, "amount": "1e3"},
            {"amount": "1"},
            "not-a-dict",
            None,
        ):
            intent, err = validate_intent(payload)
            self.assertIsNone(intent, payload)
            self.assertIsNotNone(err, payload)


class DecideRelease(unittest.TestCase):
    # MUTATION NOTES: the family contract (langchain/wallet/openclaw guards).
    # A mutant that releases on HOLD, on an unknown verdict, or on a service
    # failure is the gate failing open on the MANDATORY layer.

    def test_go_releases(self):
        self.assertEqual(decide_release(verdict("GO")), RELEASE)

    def test_hold_holds(self):
        self.assertEqual(decide_release(verdict("HOLD")), HOLD)

    def test_stop_refuses(self):
        self.assertEqual(decide_release(verdict("STOP")), REFUSE)

    def test_hard_stop_refuses_even_with_weird_text(self):
        self.assertEqual(
            decide_release(verdict("WEIRD", hard_stop=True)), REFUSE)

    def test_unknown_and_missing_hold_never_release(self):
        self.assertEqual(decide_release(verdict("???")), HOLD)
        self.assertEqual(decide_release({}), HOLD)
        self.assertEqual(decide_release(None), HOLD)


class ProcessIntent(unittest.TestCase):
    # MUTATION NOTES: the ORDER invariant — verdict first, signature second,
    # settlement third, and neither of the latter two exists on any path but
    # RELEASE. This is the "genuinely pre-signature" property as code.

    def setUp(self):
        self.calls = []
        self.intent = {"counterparty": PAYEE.lower(), "amount": "0.014",
                       "asset": "USDC", "chain": "base"}

    def _sign(self, intent):
        self.calls.append("sign")
        return "sig_test"

    def _settle(self, intent, signature):
        self.calls.append("settle")
        self.assertEqual(signature, "sig_test")  # settle gets the signature
        return {"settled": True, "tx": "sim_1"}

    def test_go_forecasts_then_signs_then_settles(self):
        def forecast(intent):
            self.calls.append("forecast")
            return verdict("GO")
        status, detail = process_intent(
            self.intent, forecast, self._sign, self._settle)
        self.assertEqual(status, "released")
        self.assertEqual(self.calls, ["forecast", "sign", "settle"])
        self.assertEqual(detail["settlement"]["tx"], "sim_1")
        self.assertEqual(detail["verdict"]["verdict"], "GO")

    def test_hold_never_touches_signature_or_rail(self):
        status, detail = process_intent(
            self.intent, lambda i: verdict("HOLD"), self._sign, self._settle)
        self.assertEqual(status, "held")
        self.assertEqual(self.calls, [])
        self.assertIn("r1", detail["verdict"]["reasons"])

    def test_stop_refuses_and_never_touches_signature_or_rail(self):
        status, _ = process_intent(
            self.intent, lambda i: verdict("STOP"), self._sign, self._settle)
        self.assertEqual(status, "refused")
        self.assertEqual(self.calls, [])

    def test_forecast_failure_holds_never_releases(self):
        def broken(intent):
            raise OSError("verdict service unreachable")
        status, detail = process_intent(
            self.intent, broken, self._sign, self._settle)
        self.assertEqual(status, "held")
        self.assertEqual(self.calls, [])
        self.assertIn("unreachable", detail["error"])

    def test_settle_failure_reports_error_after_go(self):
        def bad_settle(intent, signature):
            self.calls.append("settle")
            raise OSError("rail down")
        status, detail = process_intent(
            self.intent, lambda i: verdict("GO"), self._sign, bad_settle)
        self.assertEqual(status, "error")
        self.assertIn("rail down", detail["error"])


class SimulatedSignature(unittest.TestCase):
    # MUTATION NOTES: the simulation must be honest — clearly labeled, and
    # deterministic over the intent so the rail can bind it to the claim.

    def test_labeled_and_deterministic(self):
        intent = {"counterparty": PAYEE.lower(), "amount": "0.014",
                  "asset": "USDC", "chain": "base"}
        s1 = simulate_signature(intent)
        s2 = simulate_signature(intent)
        self.assertTrue(s1.startswith("SIMULATED_"))
        self.assertEqual(s1, s2)
        intent2 = dict(intent, amount="0.015")
        self.assertNotEqual(s1, simulate_signature(intent2))



class AuditRegressions(unittest.TestCase):
    """Session audit of the initial gate implementation.

    MUTATION NOTES: A1 pins the double-release race (two concurrent approvals
    of one HELD intent must yield exactly one settlement); A2 pins the
    approval token (a named header alone must never release — the token is
    printed host-side only, where the sandbox cannot read); A3 pins the
    intent-store cap; A4 pins input size bounds.
    """

    def _held_record(self):
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": "0.014"})
        self.assertIsNone(err)
        return new_record(intent, "held", {"verdict": verdict("HOLD")})

    def test_a1_second_approval_of_same_intent_is_rejected(self):
        record = self._held_record()
        code, _ = approve_record(record, "samuel", "tok", "tok")
        self.assertEqual(code, 0)                # first approval proceeds
        self.assertEqual(record["status"], "releasing")
        code2, err2 = approve_record(record, "mallory", "tok", "tok")
        self.assertEqual(code2, 409)             # concurrent second: rejected
        finalize_release(record, {"settled": True, "tx": "sim_a"}, "samuel")
        self.assertEqual(record["status"], "released")
        code3, _ = approve_record(record, "mallory", "tok", "tok")
        self.assertEqual(code3, 409)             # after release: rejected

    def test_a2_approval_requires_the_host_side_token(self):
        from release_gate import approve_record
        record = self._held_record()
        code, _ = approve_record(record, "samuel", None, "tok")
        self.assertEqual(code, 403)              # no token
        code, _ = approve_record(record, "samuel", "wrong", "tok")
        self.assertEqual(code, 403)              # wrong token
        code, _ = approve_record(record, None, "tok", "tok")
        self.assertEqual(code, 403)              # token but no named human
        self.assertEqual(record["status"], "held")  # nothing changed state

    def test_a3_intent_store_is_bounded(self):
        # A3's capacity cap is now enforced atomically by reserve_slot
        # (see ReviewRound2.test_b4_*); a full store rejects new reservations.
        store = {"a": 1, "b": 2}
        rec = new_record(validate_intent(
            {"counterparty": PAYEE, "amount": "1"})[0], "processing", {})
        self.assertFalse(reserve_slot(store, 2, rec))
        self.assertTrue(reserve_slot({}, 2, rec))

    def test_a4_oversized_fields_are_rejected(self):
        big_amount = "9" * 60
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": big_amount})
        self.assertIsNone(intent)
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": "1",
             "resource": "https://x/" + "a" * 3000})
        self.assertIsNone(intent)
        # sane values still pass
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": "1",
             "resource": "https://api.example.com/v1/data"})
        self.assertIsNone(err)


class ConcurrencyGuard(unittest.TestCase):
    """Deterministic proof of the double-release lock (A1).

    A single-threaded test cannot catch a missing lock (check-then-act still
    passes sequentially), and an HTTP-level race test cannot catch it either
    (CPython's GIL makes the tiny window near-impossible to interleave). So we
    force the interleave in-process: a record whose status-read inside the
    critical section pauses thread A, during which thread B attempts its own
    approval. With the lock, B blocks on acquire and later sees 'releasing'
    (409); without it, B reads 'held' and also releases (two 0s -> caught).
    """

    def test_a1_lock_serializes_concurrent_approvals(self):
        import threading
        import time

        base = self._held_record()
        a_in_section = threading.Event()
        release_a = threading.Event()

        class CoordDict(dict):
            first = True

            def __getitem__(self, key):
                val = dict.__getitem__(self, key)
                if key == "status" and self.first \
                        and threading.current_thread().name == "A":
                    self.first = False
                    a_in_section.set()      # A has read status; let B start
                    release_a.wait(3)       # pause A between check and set
                return val

        record = CoordDict(base)
        results = {}

        def call(name):
            results[name] = approve_record(record, name, "tok", "tok")[0]

        a = threading.Thread(target=call, args=("A",), name="A")
        b = threading.Thread(target=call, args=("B",), name="B")
        a.start()
        self.assertTrue(a_in_section.wait(3), "A never entered its section")
        b.start()
        time.sleep(0.2)          # B blocks on the lock (fixed) or completes (mutant)
        release_a.set()          # resume A
        a.join(3)
        b.join(3)

        releases = [k for k, v in results.items() if v == 0]
        self.assertEqual(len(releases), 1,
                         "exactly one approval may release; got %s" % results)

    def _held_record(self):
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": "0.014"})
        self.assertIsNone(err)
        return new_record(intent, "held", {"verdict": verdict("HOLD")})


class ReviewRound2(unittest.TestCase):
    """Second review round (PR #105, commit 54345d0).

    MUTATION NOTES:
      B1 gate must bind an address reachable from the sandbox (not host
         loopback); the rail must stay loopback (the denied edge).
      B2 covered by verify.sh stage 3 (in-sandbox fresh submission), not here.
      B3 human approval RE-SCREENS: a fresh STOP refuses even a named human
         with a valid token; GO/HOLD let the override stand. Signature never
         appears on a refused path.
      B4 slot reservation is atomic under the lock (check + insert together),
         so the store cannot exceed its cap under concurrent submits.
    """

    def _intent(self):
        intent, err = validate_intent(
            {"counterparty": PAYEE, "amount": "0.014"})
        self.assertIsNone(err)
        return intent

    # B1 -------------------------------------------------------------
    def test_b1_submit_bind_defaults_safe_never_promiscuous(self):
        from release_gate import resolve_gate_bind, RAIL_URL
        # SAFE default: host loopback, and NEVER 0.0.0.0 (which would expose
        # submission on every host interface). Reachability from the sandbox is
        # an explicit opt-in (operator sets the specific bridge interface).
        self.assertEqual(resolve_gate_bind(None), "127.0.0.1")
        self.assertNotEqual(resolve_gate_bind(None), "0.0.0.0")
        self.assertEqual(resolve_gate_bind("10.0.2.2"), "10.0.2.2")  # honored
        self.assertTrue(RAIL_URL.startswith("http://127.0.0.1"))

    def test_b1_listeners_are_split_approval_host_only(self):
        # The maker (submit) and human (approve) surfaces are DIFFERENT
        # listeners: submit never serves /approve, approve never serves
        # /v1/intents, and approve is bound to host loopback.
        import http.client
        import json
        import threading
        from http.server import ThreadingHTTPServer
        import release_gate as rg

        # Route-only test: inject fast fakes so a submit never makes a live
        # forecast/settle call, and restore module state afterward.
        saved = (dict(rg.INTENTS), rg.APPROVE_TOKEN, rg.forecast, rg.settle)
        rg.INTENTS.clear()
        rg.APPROVE_TOKEN = "tok"
        rg.forecast = lambda intent: {"verdict": "HOLD"}
        rg.settle = lambda intent, sig: {"tx": "x"}
        submit = ThreadingHTTPServer(("127.0.0.1", 0), rg.SubmitHandler)
        approve = ThreadingHTTPServer(("127.0.0.1", 0), rg.ApproveHandler)
        for s in (submit, approve):
            threading.Thread(target=s.serve_forever, daemon=True).start()
        sp = submit.server_address[1]
        ap = approve.server_address[1]

        def req(port, method, path, body=None, headers=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request(method, path,
                      body=json.dumps(body) if body is not None else None,
                      headers=headers or {})
            r = c.getresponse(); r.read(); c.close()
            return r.status
        try:
            # submit listener serves submit, NOT approve
            self.assertEqual(req(sp, "POST", "/v1/intents",
                                 {"counterparty": PAYEE, "amount": "0.014"},
                                 {"Content-Type": "application/json"}), 201)
            self.assertEqual(
                req(sp, "POST", "/v1/intents/anything/approve",
                    {}, {"X-Operator": "x", "X-Approve-Token": "tok"}), 404)
            # approve listener serves approve, NOT submit
            self.assertEqual(
                req(ap, "POST", "/v1/intents",
                    {"counterparty": PAYEE, "amount": "0.014"},
                    {"Content-Type": "application/json"}), 404)
            # approve is bound to host loopback
            self.assertEqual(approve.server_address[0], "127.0.0.1")
        finally:
            submit.shutdown(); approve.shutdown()
            submit.server_close(); approve.server_close()
            rg.INTENTS.clear(); rg.INTENTS.update(saved[0])
            rg.APPROVE_TOKEN, rg.forecast, rg.settle = saved[1], saved[2], saved[3]

    # B3 -------------------------------------------------------------
    def test_b3_approval_reforecasts_fresh_stop_refuses_human(self):
        from release_gate import approve_record, process_approval
        record = new_record(self._intent(), "held", {"verdict": verdict("HOLD")})
        code, _ = approve_record(record, "samuel", "tok", "tok")
        self.assertEqual(code, 0)                 # authz + claim ok
        calls = []
        status, detail = process_approval(
            record,
            forecast_fn=lambda i: verdict("STOP"),          # became sanctioned
            sign_fn=lambda i: calls.append("sign") or "sig",
            settle_fn=lambda i, s: calls.append("settle") or {"tx": "x"},
            operator="samuel")
        self.assertEqual(status, "refused")
        self.assertEqual(record["status"], "refused")
        self.assertEqual(calls, [])               # never signed, never settled

    def test_b3_approval_go_lets_override_stand(self):
        from release_gate import approve_record, process_approval
        record = new_record(self._intent(), "held", {"verdict": verdict("HOLD")})
        approve_record(record, "samuel", "tok", "tok")
        calls = []
        status, detail = process_approval(
            record, lambda i: verdict("GO"),
            lambda i: calls.append("sign") or "sig",
            lambda i, s: calls.append("settle") or {"tx": "x"}, "samuel")
        self.assertEqual(status, "released")
        self.assertEqual(calls, ["sign", "settle"])   # order preserved
        self.assertEqual(record["detail"]["approved_by"], "samuel")

    def test_b3_approval_hold_is_a_human_override(self):
        from release_gate import approve_record, process_approval
        record = new_record(self._intent(), "held", {"verdict": verdict("HOLD")})
        approve_record(record, "samuel", "tok", "tok")
        # a still-HOLD re-forecast: the named human's override stands
        status, _ = process_approval(
            record, lambda i: verdict("HOLD"),
            lambda i: "sig", lambda i, s: {"tx": "x"}, "samuel")
        self.assertEqual(status, "released")

    def test_b3_reforecast_failure_returns_to_held(self):
        from release_gate import approve_record, process_approval
        record = new_record(self._intent(), "held", {"verdict": verdict("HOLD")})
        approve_record(record, "samuel", "tok", "tok")

        def broken(i):
            raise OSError("verdict service down")
        calls = []
        status, _ = process_approval(
            record, broken, lambda i: calls.append("s") or "sig",
            lambda i, s: calls.append("t") or {}, "samuel")
        self.assertEqual(status, "held")
        self.assertEqual(record["status"], "held")   # claim released, retryable
        self.assertEqual(calls, [])

    # B4 -------------------------------------------------------------
    def test_b4_reserve_slot_is_atomic_and_bounded(self):
        from release_gate import reserve_slot
        store = {}
        r1 = new_record(self._intent(), "processing", {})
        r2 = new_record(self._intent(), "processing", {})
        r3 = new_record(self._intent(), "processing", {})
        self.assertTrue(reserve_slot(store, 2, r1))
        self.assertTrue(reserve_slot(store, 2, r2))
        self.assertFalse(reserve_slot(store, 2, r3))   # at cap
        self.assertEqual(len(store), 2)
        self.assertIn(r1["id"], store)
        self.assertNotIn(r3["id"], store)

    def test_b4_reserve_slot_lock_prevents_overshoot(self):
        # Deterministic: a store whose length-check inside reserve_slot pauses
        # thread A between "is there room?" and the insert, during which thread
        # B attempts its own reservation at cap-1. With the lock, B blocks on
        # acquire and later sees the store full; without it, both insert and
        # the store overshoots cap. (A single-threaded or barrier test cannot
        # catch a missing lock here — CPython's GIL hides the window.)
        import threading
        import time

        a_checked = threading.Event()
        release_a = threading.Event()

        class CoordStore(dict):
            armed = True

            def __len__(self):
                n = dict.__len__(self)
                if self.armed and threading.current_thread().name == "A":
                    self.armed = False
                    a_checked.set()       # A has read the length; let B start
                    release_a.wait(3)     # pause A between check and insert
                return n

        store = CoordStore()
        store["existing"] = 1             # cap 2, so exactly one slot free
        cap = 2
        results = {}

        def call(name):
            rec = new_record(self._intent(), "processing", {})
            results[name] = reserve_slot(store, cap, rec)

        a = threading.Thread(target=call, args=("A",), name="A")
        b = threading.Thread(target=call, args=("B",), name="B")
        a.start()
        self.assertTrue(a_checked.wait(3), "A never entered reserve_slot")
        b.start()
        time.sleep(0.2)          # B blocks on the lock (fixed) or inserts (mutant)
        release_a.set()
        a.join(3)
        b.join(3)

        self.assertEqual(dict.__len__(store), cap,
                         "store overshot cap: %d" % dict.__len__(store))
        self.assertEqual(list(results.values()).count(True), 1,
                         "exactly one reservation may succeed; got %s" % results)


if __name__ == "__main__":
    unittest.main()
