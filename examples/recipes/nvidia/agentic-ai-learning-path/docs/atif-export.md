---
title:
  page: "ATIF Trace Export to S3 via the atif-export-relay"
  nav: "ATIF S3 Export"
description:
  main: "Configure Hermes's native NeMo Relay integration to send completed ATIF trajectories to S3-compatible object storage through the host-side atif-export-relay. Real AWS credentials stay on the host; the sandbox carries only an OpenShell credential placeholder."
  agent: "Explains how Hermes 0.20.6 and NeMo Relay 0.7.2 export ATIF through OpenShell. Native Relay POSTs ATIF JSON with a standard Authorization Bearer placeholder; OpenShell resolves the bearer at egress; the host relay validates it and writes to MinIO or S3 with host-side boto3 credentials."
keywords: ["atif export", "nemo relay", "openshell credential substitution", "sandbox object storage", "minio s3 export"]
topics: ["generative_ai", "ai_agents", "observability"]
tags: ["hermes", "openshell", "nemo-relay", "atif", "s3", "minio", "deployment", "provider-v2"]
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

![NVIDIA](../assets/nvidia_header.png)

# ATIF Trace Export

Hermes `0.20.6` runs NeMo Relay `0.7.2` in process through its native core
integration, with no separate Relay installation or process. When Hermes
finalizes a session and closes its top-level Agent scope, Relay produces one
ATIF trajectory using the standard configuration selected by
`HERMES_NEMO_RELAY_PLUGINS_TOML`.

The export destination is selected at deployment time:

- **`ATIF_EXPORT_MODE=local`** (the default) writes completed trajectories to
  `/sandbox/atif/` in the sandbox.
- **`ATIF_EXPORT_MODE=relay`** POSTs completed trajectories to the host-side
  `atif-export-relay`, which writes to MinIO, AWS S3, or another S3-compatible
  store. Real storage credentials never enter the sandbox.

Remote and local storage are not parallel success paths. A successful remote
delivery creates no local file. If every configured remote target fails, NeMo
Relay `0.7.2` writes a recovery copy to `/sandbox/atif/`.

Export happens at a Hermes session boundary—an explicit `/new` or `/reset`,
CLI/TUI exit, or configured gateway expiry—not after every conversational turn.

The deployment model is **one tenant per VM**, with one downstream bucket and
one bearer token per VM. Tenant isolation lives at the VM, relay, bucket, and
IAM boundaries.

## Quick start: MinIO

Use MinIO to exercise the complete remote path without an AWS account:

```bash
cat >>.env <<'EOF'
ATIF_EXPORT_MODE=relay
ATIF_RELAY_BACKEND=minio
ATIF_RELAY_BUCKET=nemo-relay-traces
ATIF_RELAY_KEY_PREFIX=hermes/
EOF

bash scripts/00-host-services.sh
bash scripts/bring-up.sh
```

Finish a short top-level Agent session, then list the exported objects:

```bash
docker run --rm --network=host \
  -e "MC_HOST_local=http://minioadmin:minioadmin@localhost:9000" \
  minio/mc ls --recursive local/nemo-relay-traces/
```

Expect one JSON object under `hermes/` for each completed trajectory. The
MinIO console is available at `http://localhost:9001` with the example's
default development credentials, `minioadmin` / `minioadmin`.

## Quick start: AWS S3

For production, give the host EC2 instance profile `s3:PutObject` access to
the target bucket and configure:

```bash
cat >>.env <<'EOF'
ATIF_EXPORT_MODE=relay
ATIF_RELAY_BACKEND=s3
ATIF_RELAY_BUCKET=your-traces-bucket-name
ATIF_RELAY_S3_REGION=us-west-2
ATIF_RELAY_PREFIXER=ec2-instance-id
EOF

bash scripts/00-host-services.sh
bash scripts/bring-up.sh
```

The host relay's `boto3.Session()` obtains and rotates short-lived credentials
through IMDS. The sandbox image contains no AWS access key, secret, session
token, bucket name, or storage prefix.

### Key prefixing

The relay, not the sandbox, owns the destination bucket and key prefix:

```text
effective prefix = prefixer output + ATIF_RELAY_KEY_PREFIX
final key         = effective prefix + Relay-generated ATIF filename
```

| `ATIF_RELAY_PREFIXER` | `ATIF_RELAY_KEY_PREFIX` | Resulting key |
|---|---|---|
| `none` (default) | empty | `<Relay-generated filename>` |
| `none` | `hermes/` | `hermes/<Relay-generated filename>` |
| `ec2-instance-id` | empty | `<instance-id>/<Relay-generated filename>` |
| `ec2-instance-id` | `hermes/` | `<instance-id>/hermes/<Relay-generated filename>` |

`ec2-instance-id` resolves the instance ID through IMDSv2 once at relay
startup and fails loudly if it cannot. A replacement instance receives its
new prefix the next time the relay starts.

### Minimum IAM policy

With `ATIF_RELAY_PREFIXER=ec2-instance-id`, grant only `PutObject` under that
instance's prefix:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3Write",
      "Effect": "Allow",
      "Action": ["s3:PutObject"],
      "Resource": "arn:aws:s3:::your-traces-bucket-name/${instance-id}/*"
    }
  ]
}
```

Substitute `${instance-id}` during provisioning. The relay sets no ACL and
does not need `ListBucket` or `GetObject`. For an unscoped layout, use
`arn:aws:s3:::your-traces-bucket-name/*` with
`ATIF_RELAY_PREFIXER=none`.

For an SSE-KMS bucket, also grant the required KMS operations for that key:

```json
{
  "Sid": "AllowKMSEncrypt",
  "Effect": "Allow",
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "arn:aws:kms:<region>:<account>:key/<key-id>"
}
```

## Request and authentication flow

The remote path uses NeMo Relay's native HTTP ATIF storage contract; storage
translation and credentials stay in the host relay.

1. Bring-up creates a random token in the gitignored
   `.bootstrap/cache/atif-relay-token`, unless the operator supplies
   `ATIF_RELAY_AUTH_TOKEN`. The host relay reads the real value.
2. `scripts/02-providers.sh` registers the same value in OpenShell's provider
   store. The sandbox receives only OpenShell's revision-scoped credential
   placeholder in `ATIF_RELAY_AUTH_TOKEN`; `start.sh` prefixes that placeholder
   with `Bearer` for native Relay.
3. When Hermes finalizes the session, native Relay sends exactly one request to
   `https://host.openshell.internal:18443/atif` through OpenShell's L7 proxy:

   ```http
   POST /atif HTTP/1.1
   Content-Type: application/json
   Authorization: Bearer <OpenShell ATIF_RELAY_AUTH_TOKEN placeholder>
   X-NeMo-Relay-ATIF-Filename: <trajectory>.json

   { ...ATIF-v1.7 trajectory... }
   ```

   `Content-Type`, `Authorization`, and `X-NeMo-Relay-ATIF-Filename` are
   required. Relay also supplies `X-NeMo-Relay-ATIF-Session-ID` when a session
   ID is available; the host accepts it as optional metadata. The filename is
   an opaque, Relay-generated object name.

4. OpenShell's L7 proxy replaces the whole credential placeholder in
   `Authorization` with the real token and forwards the request.
5. The `atif-export-relay` trajectory route accepts only `POST /atif`, validates
   the standard Bearer token, requires the Relay-generated filename, and writes
   the JSON body to its configured bucket and prefix through boto3.
6. The relay returns `204 No Content`; native Relay treats any `2xx` as
   success. On a non-`2xx` response or transport failure, native Relay writes
   the recovery copy locally after all remote targets fail.

### Security properties

- Hermes and native NeMo Relay see only the OpenShell placeholder, never the
  resolved token.
- The OpenShell L7 proxy and host relay see the bearer. Only the host relay
  sees downstream AWS or MinIO credentials.
- The host relay's trajectory route accepts only `POST /atif`, enforces a
  request-size limit, requires the ATIF filename header, and chooses the bucket
  and prefix. The separate `GET /healthz` route returns only readiness status.
- A compromised sandbox cannot choose another bucket or obtain read/delete
  access. The downstream IAM role remains the final `PutObject`-only boundary.
- The bearer is scoped per VM in this single-tenant deployment. Separate
  tenants use separate VMs, relays, buckets, and tokens.

```text
Hermes + native NeMo Relay
  POST https://host.openshell.internal:18443/atif
                    |
                    v
OpenShell L7 proxy (resolves Authorization Bearer placeholder)
                    |
                    v
atif-export-relay (validates bearer; boto3 PutObject)
                    |
                    v
MinIO or AWS S3
```

Traffic from the sandbox to the host relay is HTTPS. Relay's native reqwest
client honors OpenShell's proxy environment, and its rustls verifier trusts the
proxy CA injected by OpenShell. No protocol shim or separate Relay process is
required.

## Operations

### Rotate the bearer

```bash
rm -f .bootstrap/cache/atif-relay-token \
  .bootstrap/cache/atif-relay-token.registered
bash scripts/bring-up.sh
```

Bring-up generates a new token, recreates the relay with it, and updates the
OpenShell provider. To pin a value instead, set `ATIF_RELAY_AUTH_TOKEN` in the
gitignored `.env` file.

### Change the relay endpoint

`ATIF_RELAY_ENDPOINT` is the HTTPS origin exposed by the host relay; its
default is `https://host.openshell.internal:18443`. The `/atif` request path is
fixed and appended by the sandbox configuration.

- For a port conflict, set
  `ATIF_RELAY_ENDPOINT=https://host.openshell.internal:19443`.
- For another host name, set
  `ATIF_RELAY_ENDPOINT=https://my-vm.local:18443`.

Bring-up derives the listener port, native Relay endpoint, provider endpoint,
and TLS certificate names from this value. Re-run bring-up after changing it.
`ATIF_RELAY_FORCE_CERT=1` forces certificate regeneration.

### Verify lifecycle and delivery

Complete a short Hermes session, then trigger a boundary with `/new`, `/reset`,
or a clean CLI/TUI exit. Do not wait for the gateway's potentially long expiry
policy during a manual check.

For local mode, verify one new trajectory file appears:

```bash
openshell sandbox exec --name hermes-direct -- sh -lc \
  'find /sandbox/atif -maxdepth 1 -type f -name "hermes-atif-*.json" -print'
```

For MinIO relay mode, verify one new remote object appears. A successful
remote delivery should not create a matching local file:

```bash
docker run --rm --network=host \
  -e "MC_HOST_local=http://minioadmin:minioadmin@localhost:9000" \
  minio/mc ls --recursive local/nemo-relay-traces/
```

If remote delivery fails, inspect `/sandbox/atif/` for the recovery copy and the
Hermes logs for the original HTTP error.

### Tear down host services

```bash
bash scripts/00-host-services.sh down
```

Add `--volumes` to wipe MinIO data as well.

## Other S3-compatible stores

Set `ATIF_RELAY_BACKEND=s3-compatible` with an HTTPS endpoint and static HMAC
credentials held by the host relay:

```bash
ATIF_RELAY_BACKEND=s3-compatible
ATIF_RELAY_BUCKET=your-bucket
ATIF_RELAY_S3_ENDPOINT=https://object-store.example.com
ATIF_RELAY_S3_ACCESS_KEY=...
ATIF_RELAY_S3_SECRET_KEY=...
ATIF_RELAY_S3_REGION=us-west-2
```

This covers providers with an S3-compatible API, including OCI Object Storage,
Nebius, GCS XML/interop, and self-hosted stores. Remote endpoints must use
HTTPS; plain HTTP is permitted only for loopback MinIO. A non-S3 store can add
a `StorageBackend` implementation without changing the sandbox-side native
Relay contract.

Prefix strategies are registered in
[`extras/atif-export-relay/backends/prefixers.py`](../extras/atif-export-relay/backends/prefixers.py).
Storage backends are registered in
[`extras/atif-export-relay/backends/__init__.py`](../extras/atif-export-relay/backends/__init__.py).

## Troubleshooting

| Symptom | Cause and fix |
|---|---|
| Relay returns `403 missing bearer` or `403 bad bearer token` | Confirm the `<sandbox>-atif-export-relay` OpenShell provider is attached and the relay received `ATIF_RELAY_AUTH_TOKEN`. Check the supervisor for credential-injection errors, then re-run bring-up. |
| Relay returns `404` or `405` | The native client must send `POST /atif`. Rebuild the sandbox so it receives the current `plugins.toml`. |
| No remote object and a new local ATIF file appears | Remote delivery failed and NeMo Relay created its recovery copy. Check Hermes logs, `docker compose -f extras/docker-compose.yml logs atif-export-relay`, and downstream availability. |
| No remote object and no new local ATIF file appears | The session has not finalized. Another conversational turn does not close it; use `/new`, `/reset`, a clean CLI/TUI exit, or wait for the configured gateway expiry, then check again. |
| Relay logs a TLS verification error | Confirm the generated relay certificate matches `ATIF_RELAY_ENDPOINT` and the host CA is staged in the sandbox image. Regenerate with `ATIF_RELAY_FORCE_CERT=1 bash scripts/bring-up.sh`. |
| Relay cannot resolve the EC2 instance ID | `ATIF_RELAY_PREFIXER=ec2-instance-id` requires reachable IMDSv2. Use an EC2 host with IMDS enabled or choose `none`. |
| Relay reports `AccessDenied` | The host instance profile lacks `s3:PutObject`, or its allowed prefix does not match the relay's resolved prefix. Compare the relay startup log with the IAM resource path. |
| Relay reports `NoSuchBucket` | Create the configured bucket and confirm `ATIF_RELAY_S3_REGION`. |
| Objects are in an unexpected path | Check `ATIF_RELAY_PREFIXER` and `ATIF_RELAY_KEY_PREFIX` in the relay startup log. The sandbox does not select either value. |

## Files

| Path | Role |
|---|---|
| [`agents/hermes/nemo-relay/plugins.toml.in`](../agents/hermes/nemo-relay/plugins.toml.in) | Native NeMo Relay observability and HTTP ATIF storage configuration. |
| [`extras/atif-export-relay/relay.py`](../extras/atif-export-relay/relay.py) | Host service that accepts authenticated `POST /atif` requests and forwards them to its configured backend. |
| [`extras/atif-export-relay/backends/`](../extras/atif-export-relay/backends/) | boto3-backed S3, MinIO, custom-endpoint, and prefix implementations. |
| [`extras/docker-compose.yml`](../extras/docker-compose.yml) | Host relay and MinIO services. |
| [`providers/atif-export-relay.yaml`](../providers/atif-export-relay.yaml) | OpenShell provider profile containing `ATIF_RELAY_AUTH_TOKEN`. |
