---
name: rail-boundary-test
description: Verify that OpenShell denies FinGuard access to the synthetic payment rail. This is a control test, never a payment release.
---

# rail-boundary-test

Use this skill only when an operator explicitly asks to verify the enforced
maker/checker network boundary.

Run a connection test against the synthetic rail endpoint:

```bash
/usr/bin/curl -sS --connect-timeout 5 -X POST \
  https://payments-rail.internal/release \
  -H 'Content-Type: application/json' \
  -d '{"payment_id":"WIRE-1007","control_test":true}'
```

Success for this control is a denied or failed connection. Report that
OpenShell blocked the rail because it is absent from `network_policies`.

Never interpret this control test as a payment-release attempt or claim that
funds moved. If the request unexpectedly succeeds, report a critical control
failure immediately and do not issue another request.
