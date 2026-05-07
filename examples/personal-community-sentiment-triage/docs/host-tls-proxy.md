---
title:
  page: "Host-side TLS proxy for inference"
  nav: "Host TLS proxy"
description:
  main: "When the inference endpoint sits behind a host-side TLS terminator (corporate proxy, mkcert-issued cert, split-horizon DNS), containers in the OpenShell sandbox cannot validate the cert. scripts/host-tls-proxy.py is a small plain-HTTP forwarder that lets the sandbox reach the upstream over plain HTTP while the proxy handles TLS on the host's behalf."
  agent: "Explains when and how to use scripts/host-tls-proxy.py to bridge the OpenShell sandbox to a host-side TLS-terminated inference endpoint. Covers the symptoms that indicate you need it, how to start it, and the matching .env settings (NEMOCLAW_ENDPOINT_URL=http://172.17.0.1:18080/v1). Use when troubleshooting TLS validation errors on inference calls or when running on hosts with corporate VPN/proxy/mkcert TLS chains the sandbox can't trust."
keywords: ["nemoclaw tls proxy", "host tls forwarder", "openshell sandbox cert", "split-horizon dns docker", "mkcert sandbox"]
topics: ["generative_ai", "ai_agents"]
tags: ["hermes", "openshell", "networking", "tls", "deployment", "troubleshooting"]
content:
  type: how_to
  difficulty: intermediate
  audience: ["developer", "engineer"]
status: published
---

<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# Host-side TLS proxy

This is an **optional** path. Most readers running the example on a personal laptop or a clean cloud VM should skip it — point [NEMOCLAW_ENDPOINT_URL](../.env.example) directly at the HTTPS inference endpoint and `bring-up.sh` will work.

You need this when the inference endpoint can't be reached cleanly from inside the OpenShell sandbox. Two common triggers:

- **Corporate VPN / split-horizon DNS.** The host resolves the inference hostname to `127.0.0.1` (or some VPN-internal address), but the Docker sandbox doesn't share that resolver — it tries to reach the public address and fails or hits TLS-validation errors.
- **Local CA / mkcert chain.** The host's TLS terminator presents a cert signed by a CA installed only on the host. Containers don't have that CA in their trust store, so TLS handshakes fail with "unable to verify the first certificate".

The fix is to give the sandbox a plain-HTTP target on the host that does the TLS handshake on its behalf using the host's own trust store. That's what [scripts/host-tls-proxy.py](../scripts/host-tls-proxy.py) does.

## How it works

```
sandbox  ──HTTP──>  host:18080 (host-tls-proxy.py)  ──HTTPS──>  upstream-inference-host
                    (uses host trust store)
```

The proxy is a thin reverse proxy:

- Listens on plain HTTP on a host port (default `0.0.0.0:18080`) so the sandbox can reach it on the Docker bridge gateway IP (e.g. `172.17.0.1:18080`).
- Forwards every request to the configured `--upstream` over HTTPS, using Python's default SSL context — which loads the host's installed root CAs.
- Streams responses back unmodified (minus hop-by-hop headers).

It's about 140 lines of stdlib Python — no third-party dependencies.

## Start the proxy

Run it on the host **before** `bash scripts/bring-up.sh`. Keep it running for as long as the sandbox is running.

```console
$ mkdir -p .tmp
$ setsid -f python3 scripts/host-tls-proxy.py \
    --upstream "https://your-inference-host" \
    --listen 0.0.0.0 \
    --port 18080 \
    > .tmp/host-tls-proxy.log 2>&1 < /dev/null
```

Notes on the invocation:

- `setsid -f` detaches the process from the current shell session — you get your prompt back and the proxy survives logout.
- `< /dev/null` closes stdin so the process doesn't try to read from your terminal.
- `> .tmp/host-tls-proxy.log 2>&1` captures stdout/stderr for debugging. The directory is gitignored.
- `--upstream` takes the full HTTPS URL of the upstream inference host (no trailing path — the proxy preserves whatever path the sandbox sends).

To stop:

```console
$ pkill -f host-tls-proxy.py
```

## Configure `.env`

Two changes:

```bash
# Point the agent at the local proxy instead of the upstream HTTPS URL.
NEMOCLAW_ENDPOINT_URL=http://172.17.0.1:18080/v1
```

`172.17.0.1` is the default Docker bridge gateway address — the same address [scripts/_lib.sh](../scripts/_lib.sh) uses for `TOKEN_MANAGER_HOST` auto-detection. If your Docker bridge subnet is different, substitute the right address.

`COMPATIBLE_API_KEY` (or `OPENAI_API_KEY`) stays unchanged — the proxy passes the `Authorization` header straight through.

## Smoke test

Before running `bring-up.sh`, confirm the proxy is reachable from the host and forwards correctly:

```console
$ curl -sf http://localhost:18080/v1/models -H "Authorization: Bearer $COMPATIBLE_API_KEY" | head -20
```

A `200 OK` with a model list means the proxy and upstream are both working. A `502` (or no response) means the proxy can't reach the upstream — check `--upstream` and `.tmp/host-tls-proxy.log`.

After `bring-up.sh`, confirm the sandbox can reach it through the Docker bridge:

```console
$ openshell sandbox exec hermes-direct curl -sf http://172.17.0.1:18080/v1/models | head -20
```

## Troubleshooting

- **`bring-up.sh` succeeds but the agent's first inference call hangs or errors with TLS verification.** Either the proxy isn't running, or `NEMOCLAW_ENDPOINT_URL` still points at the HTTPS upstream. Run the smoke tests above to isolate.
- **`502 Upstream inference proxy error` from the proxy.** The proxy reached the host but couldn't complete the upstream HTTPS handshake. Check that the host's trust store has the upstream's CA — the proxy uses `ssl.create_default_context()`, which honors `/etc/ssl/certs` (or the equivalent) and `SSL_CERT_FILE` / `REQUESTS_CA_BUNDLE` env vars.
- **Sandbox can't reach `172.17.0.1:18080`.** Verify the proxy's `--listen` is `0.0.0.0` (not `127.0.0.1`) — `127.0.0.1` only accepts connections from the host's loopback, which is not the same loopback as inside the sandbox.
- **Docker bridge isn't on `172.17.0.1`.** Run `docker network inspect bridge --format '{{(index .IPAM.Config 0).Gateway}}'` to get the actual gateway address and substitute it into `NEMOCLAW_ENDPOINT_URL`.
