# Verify Functionality

Run the complete deployment verification from the example root:

```bash
bash scripts/verify.sh
```

It checks:

- all six bundled payment decisions;
- Phoenix, the mock rail, and the FinGuard UI;
- NeMo Relay and Hermes health inside the sandbox;
- the rendered Relay plugin configuration;
- denial of payment-rail access from the sandbox.

## Offline-only checks

These do not require Docker, OpenShell, or inference credentials:

```bash
bash -n scripts/*.sh agents/hermes/start.sh
python3 -m py_compile $(find . -name '*.py' -not -path './.git/*' -print)
python3 scripts/smoke-payment.py
git diff --check
```

## Human checker

```bash
python3 scripts/approve_release.py --id WIRE-1007 --approver "Jane Ops"
python3 scripts/approve_release.py --id ACH-2003 --approver "Jane Ops"
curl -fsS http://127.0.0.1:8780/released
```

Expected: `WIRE-1007` is released and `ACH-2003` is refused because it is on
hold. UI-driven host decisions emit audit spans under service
`finguard-host-checker`, distinct from NeMo Relay's agent spans.

In the UI, exercise screening and **Agent: Release** before checking Phoenix.
Those actions call Hermes and produce Relay evidence. Merely loading the queue
or ledger intentionally does not create a trace.

## Relay logs and traces

```bash
openshell sandbox exec --name payment-ops -- tail -50 /tmp/nemo-relay.log
bash scripts/download-traces.sh
```
