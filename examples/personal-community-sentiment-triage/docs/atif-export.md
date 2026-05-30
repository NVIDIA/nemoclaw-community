---
title:
  page: "ATIF Trace Export to S3 via the atif-export-relay"
  nav: "ATIF S3 Export"
description:
  main: "Configure the sandboxed Hermes agent to upload completed ATIF trajectories to S3-compatible object storage (real AWS S3 or local MinIO) via a host-side atif-export-relay service. Real AWS credentials stay on the host; the sandbox carries only a per-VM bearer token managed by OpenShell."
  agent: "Explains how Nemo Relay's ATIF S3 export plugin reaches its downstream from inside an OpenShell sandbox: the SDK reads AWS_SESSION_TOKEN containing an OpenShell placeholder (`openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN`), emits it as a standalone `x-amz-security-token` HTTP header, the L7 proxy substitutes the real bearer token at egress, and the host-side atif-export-relay validates the token, re-signs with real downstream credentials, and forwards to MinIO or AWS S3. The sandbox never holds real AWS credentials. Use when setting up trace export for production or local-testing scenarios."
keywords: ["atif export", "nemo relay s3", "openshell credential substitution", "sandbox object storage", "minio s3 export"]
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

NeMo-Relay's S3 plugin uploads completed ATIF trajectories to object storage. This example wires the sandbox-side plugin through a host-side **`atif-export-relay`** that holds the real downstream credentials and exposes an S3-compatible interface to the sandbox. **Real AWS or MinIO credentials never enter the sandbox process** — the sandbox carries a per-VM bearer token managed by OpenShell's provider store, transparently substituted into outbound traffic by the L7 proxy.

The deployment model is **one tenant per VM**, with a bucket per tenant and a single bearer token per VM. Tenant isolation lives at the VM and bucket boundary, not inside the relay's bearer check (see "[Deployment model](#deployment-model-one-tenant-per-vm)" below for the rationale).

Three backend values are supported by the same wiring:

- **`local`** *(default if unset)* — traces stay in the sandbox at `/tmp/atif`; recoverable via `scripts/download-traces.sh`. No host services or AWS infrastructure involved. Use for solo development with no remote-storage dependency.
- **`minio`** — local MinIO container, no AWS infrastructure required. Use for testing the full upload path before AWS infra exists.
- **`s3`** — real AWS S3. Uses the host EC2 instance profile for the relay's outbound credentials (no static keys on the host).

Switching between them is a one-line edit in `.env`.

## Quick start — MinIO

Local-only flow, no AWS account needed.

```bash
cat >>.env <<'EOF'
ATIF_STORAGE_BACKEND=minio
ATIF_STORAGE_BUCKET=nemo-relay-traces
ATIF_STORAGE_KEY_PREFIX=hermes/
EOF

bash scripts/00-host-services.sh   # starts MinIO + atif-export-relay; creates the bucket
bash scripts/bring-up.sh           # issues ATIF_RELAY_AUTH_TOKEN, registers it with OpenShell,
                                   # rebuilds the sandbox with the new wiring
```

Trigger an agent run, then verify ATIF objects land in MinIO:

```bash
docker run --rm --network=host \
  -e "MC_HOST_local=http://minioadmin:minioadmin@localhost:9000" \
  minio/mc ls --recursive local/nemo-relay-traces/
# expect: hermes/<session_id>.atif.json files
```

The MinIO web console at `http://localhost:9001` (login: `minioadmin/minioadmin`) is a convenient way to browse uploaded traces.

## Quick start — AWS S3

Production flow. Requires the EC2 host to have an IAM instance profile with `s3:PutObject` on the target bucket.

```bash
cat >>.env <<'EOF'
ATIF_STORAGE_BACKEND=s3
ATIF_STORAGE_BUCKET=your-traces-bucket-name
ATIF_S3_REGION=us-west-2
ATIF_STORAGE_KEY_PREFIX=hermes/
EOF

bash scripts/00-host-services.sh   # starts atif-export-relay (boto3 picks up IMDS creds)
bash scripts/bring-up.sh
```

The host EC2's IAM role is what authenticates to S3 — there are no static AWS keys anywhere in this flow. The relay's `boto3.Session()` automatically fetches and rotates short-lived STS credentials from IMDS.

### Required IAM policy for the EC2 instance role

Minimum-privilege policy. Scope per-host via `${aws:userid}` or per-instance via your own provisioning:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "AllowS3Write",
      "Effect": "Allow",
      "Action": ["s3:PutObject", "s3:PutObjectAcl"],
      "Resource": "arn:aws:s3:::your-traces-bucket-name/*"
    },
    {
      "Sid": "AllowS3BucketRead",
      "Effect": "Allow",
      "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
      "Resource": "arn:aws:s3:::your-traces-bucket-name"
    }
  ]
}
```

If the bucket uses SSE-KMS, add:

```json
{
  "Sid": "AllowKMSEncrypt",
  "Effect": "Allow",
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "arn:aws:kms:<region>:<account>:key/<key-id>"
}
```

The relay's per-request policy boundary (bucket allowlist enforced at `extras/atif-export-relay/relay.py`) ensures the sandbox can only target the configured bucket even if the IAM policy is broader.

## How the auth model works

The challenge: NeMo-Relay's S3 plugin reads `AWS_*` env vars at startup and uses them as inputs to AWS SigV4 signing on every PutObject. We want the per-sandbox bearer to ride to the relay through OpenShell's L7 proxy, which substitutes placeholders into the outbound request at egress — but SigV4's signature is a cryptographic hash, and the bearer token can't be embedded *inside* a SigV4 `Credential=AKID/.../aws4_request` field where the proxy's text-substitution path can't reach it (none of the proxy's recognized header patterns match a placeholder buried in that comma-separated, slash-delimited substring).

The solution: ride the bearer in the standalone `x-amz-security-token` HTTP header, which the AWS SDK emits verbatim from `AWS_SESSION_TOKEN`. A whole-header-value placeholder is exactly the substitution shape OpenShell's L7 proxy handles via its first match branch.

1. `scripts/02-providers.sh` generates a random bearer token (`atif-<hex>`) and stores it in OpenShell's provider store as a credential named `ATIF_RELAY_AUTH_TOKEN`. The same value also goes into the host's `.env` so the relay container can pre-populate its accept-set.
2. The sandbox's env (set by `agents/hermes/start.sh`) carries:
   ```
   AWS_SESSION_TOKEN=openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN
   AWS_ACCESS_KEY_ID=nemo-relay-sandbox          # literal, vestigial
   AWS_SECRET_ACCESS_KEY=relay-ignores-this-value # literal, vestigial
   AWS_ENDPOINT_URL=http://127.0.0.1:18444        # in-container atif-bridge sidecar (see below)
   ```
3. NeMo-Relay's `object_store` reads these env vars at startup and emits each PutObject with:
   ```
   x-amz-security-token: openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN   ← whole-value placeholder
   Authorization: AWS4-HMAC-SHA256 Credential=nemo-relay-sandbox/.../aws4_request, Signature=<junk>
   ```
   The destination is the in-container **atif-bridge** sidecar — a pure HTTP→HTTPS protocol shim running as `gateway` uid. The bridge does not inspect or modify headers; it re-emits each request as HTTPS to `host.openshell.internal:18443` using Python's `ssl` module (OpenSSL backend). The bridge exists because nemo-relay's rustls TLS client cannot validate OpenShell's L7-proxy MITM cert — see "Sandbox→relay TLS via Python protocol-bridge sidecar" below.
4. OpenShell's L7 proxy intercepts the bridge's HTTPS outbound, MITM-terminates it, iterates outbound headers, and matches the standalone placeholder in `x-amz-security-token` against `rewrite_header_value`'s direct-match branch. The proxy substitutes the real bearer:
   ```
   x-amz-security-token: atif-<hex>                                    ← resolved
   ```
   The `Authorization` SigV4 envelope contains no placeholder, so it passes through untouched. The fail-closed scan confirms no placeholders remain in the rewritten request, and the proxy forwards upstream.
5. `atif-export-relay` reads the bearer header (default `X-Amz-Security-Token`; configurable via `ATIF_RELAY_AUTH_HEADER`) and compares it constant-time against `ATIF_RELAY_AUTH_TOKEN`. The SigV4 envelope is ignored entirely — neither the proxy nor the relay verifies its signature, and the relay's outbound leg is freshly signed by boto3 with real downstream credentials.
6. The relay verifies the bucket against its allowlist, then constructs a fresh PutObject via boto3 (which signs correctly with real downstream credentials from IMDS or MinIO admin) and forwards to the configured downstream.

**Threat model**:

- Real AWS / MinIO credentials are only present on the host, only in the `atif-export-relay` process. Never enter the sandbox.
- Sandbox-side credentials are scoped bearer tokens. If exfiltrated, the attacker can submit S3-shaped PutObject requests to the relay but is bounded by (a) the relay's bucket allowlist, (b) the downstream IAM policy (PutObject-only on the configured prefix), and (c) network access to the host's `:18443`. They cannot reach AWS APIs directly, cannot read or delete existing objects, and cannot reach other AWS services.
- Revocation granularity: the bearer token is **per VM, not per sandbox**, and that's the chosen granularity given one tenant per VM (see "[Deployment model](#deployment-model-one-tenant-per-vm)"). Rotating `ATIF_RELAY_AUTH_TOKEN` revokes export access for every sandbox on the VM — which is the same scope of trust anyway, since they belong to the same tenant. To rotate: remove the token from OpenShell, regenerate `ATIF_RELAY_AUTH_TOKEN`, restart the relay so it reloads the new value from env.

### Sandbox→relay TLS via Python protocol-bridge sidecar

The sandbox→relay leg is **TLS end-to-end on the bytes that cross the trust boundary** (sandbox container → host relay), accomplished via a small in-sandbox protocol-bridge sidecar. The only in-container plaintext hop is loopback HTTP between nemo-relay-cli and the bridge — same network namespace, never on the wire. Bearer credentials remain in the OpenShell L7 proxy's process memory only; they never enter nemo-relay, the bridge, or any sandbox-uid memory.

#### Wire diagram

```
nemo-relay-cli (rustls, gateway uid)
  └─ plain HTTP to 127.0.0.1:18444 (loopback, in-container)
                       │
                       ▼
       atif-bridge.py (gateway uid, Python ssl = OpenSSL)
       Pure HTTP→HTTPS protocol shim. Holds no bearer.
                       │
                       ▼ HTTPS to host.openshell.internal:18443
                       │
       OpenShell L7 proxy (MITMs; OpenSSL accepts cert w/o EKU)
       ├─ decrypts, substitutes x-amz-security-token placeholder
       │   with real bearer from provider store
       └─ re-encrypts, forwards
                       │
                       ▼ HTTPS (real wire)
       atif-export-relay (host) — reads real bearer in header
                       │
                       ▼ HTTPS (boto3, SigV4-signed with real AWS creds)
       AWS S3 or MinIO
```

#### Why the bridge is needed

OpenShell's L7 proxy MITM-terminates HTTPS to inspect traffic and do credential placeholder substitution. It generates per-hostname leaf certs signed by a per-sandbox ephemeral CA. The cert generation at [`crates/openshell-sandbox/src/l7/tls.rs:115-135`](https://github.com/NVIDIA/OpenShell/blob/main/crates/openshell-sandbox/src/l7/tls.rs#L115-L135) does not set `extended_key_usages`:

```rust
fn generate_leaf(&self, hostname: &str) -> Result<CertifiedLeaf> {
    let leaf_key = KeyPair::generate().into_diagnostic()?;
    let mut params = CertificateParams::new(vec![hostname.to_string()]).into_diagnostic()?;
    params.distinguished_name.push(DnType::CommonName, hostname);
    params.use_authority_key_identifier_extension = true;
    let leaf_cert = params.signed_by(&leaf_key, &self.ca.ca_cert, &self.ca.ca_key)...
```

**rustls 0.23+** (in `object_store` 0.13's reqwest, the only Rust-rustls HTTPS client in the example) strictly enforces `id-kp-serverAuth` in the cert's EKU extension and rejects certs without it. **OpenSSL is more permissive** — RFC 5280 §4.2.1.12 says "if the extension is not present, the certificate is valid for all purposes," and OpenSSL implements that reading. That's why curl, Python `requests`, httpx, openai-python, and git all work fine through the same L7 proxy today.

The bridge sidecar inherits OpenSSL's permissive behavior via Python's `ssl` module. nemo-relay still uses rustls, but it now only talks plain HTTP to a loopback peer (the bridge) — never the L7 proxy directly. The bridge does the HTTPS handshake with the proxy and inherits the same trust posture as every other Hermes outbound.

The bridge is a pure protocol shim — it does not inspect or modify headers, does not read any credential env vars (defense-in-depth: it actively refuses to start if any are present), and adds no logic on top of the existing substitution flow. The bearer continues to travel as the placeholder string `openshell:resolve:env:ATIF_RELAY_AUTH_TOKEN` from nemo-relay through the bridge to the L7 proxy, where substitution happens exactly as for every other authenticated outbound.

#### Trust-boundary properties

| Component | Sees real bearer? |
|---|---|
| sandbox uid (Hermes agent code) | No |
| gateway uid (nemo-relay) | No — only the placeholder string |
| gateway uid (atif-bridge) | No — only the placeholder string |
| proxy uid (OpenShell L7 proxy) | **Yes** — resolves placeholder during MITM |
| atif-export-relay (host) | Yes — receives substituted value |
| AWS S3 / MinIO | No (relay re-signs with its own creds via boto3) |

Identical to the pre-rollback / pre-EKU-discovery design. The bridge introduces no new credential-handling surface.

#### Sunset: removing the bridge

When OpenShell ships the EKU fix (the one-line patch below), the bridge becomes unnecessary. nemo-relay can talk HTTPS directly to `host.openshell.internal:18443` again, with rustls validating the L7 proxy's MITM cert. To sunset:

1. Bump OpenShell to a version containing the EKU fix.
2. Delete [`agents/hermes/bridges/atif/`](../agents/hermes/bridges/atif/). It rides on the existing `COPY agents/hermes/bridges/ /usr/local/lib/nemoclaw-bridges/` line in [`agents/hermes/Dockerfile`](../agents/hermes/Dockerfile), so no Dockerfile edit is needed beyond the source deletion.
3. Delete the `start_atif_bridge` function + `start_atif_bridge` call in [`agents/hermes/start.sh`](../agents/hermes/start.sh).
4. Flip `AWS_ENDPOINT_URL` back to `https://host.openshell.internal:18443` in both env blocks of `start.sh`.

The OpenShell patch is one line:

```rust
use rcgen::{..., ExtendedKeyUsagePurpose};
let mut params = CertificateParams::new(vec![hostname.to_string()]).into_diagnostic()?;
params.distinguished_name.push(DnType::CommonName, hostname);
params.use_authority_key_identifier_extension = true;
params.extended_key_usages = vec![ExtendedKeyUsagePurpose::ServerAuth];  // ← add this
```

Track this as the gating change. File against OpenShell as a P1.

#### Alternative upstream paths (open follow-ups)

| Where | Change | What it gives us |
|---|---|---|
| **OpenShell (smallest fix)** | Add `ExtendedKeyUsagePurpose::ServerAuth` to MITM cert generation. | rustls 0.23+ clients work through the L7 proxy; the bridge can be deleted. |
| NeMo-Relay | Add an HTTP storage backend variant on `AtifStorageConfig` with `Authorization: Bearer` support. | Eliminates the AWS_SESSION_TOKEN/SigV4-shaped wire entirely; bearer would ride in a normal `Authorization` header. |
| `object_store` upstream | Surface `ClientOptions::with_root_certificate(...)` AND verifier customization through `AmazonS3Builder::from_env()`. | NeMo-Relay (and any downstream caller) can configure trust + verification policy via TOML. |

#### Production downstream still uses TLS

The relay's outbound leg to real AWS S3 (or MinIO) is signed and TLS-encrypted by boto3 inside the relay container. That's a different leg from sandbox→relay; it's always end-to-end HTTPS regardless of what the in-sandbox leg looks like.

## Operational tasks

### Rotating the auth token

```bash
sed -i '/^ATIF_RELAY_AUTH_TOKEN=/d' .env
bash scripts/bring-up.sh
```

`scripts/02-providers.sh` notices the missing line, generates a fresh token, appends it to `.env`, force-recreates the relay container, and re-registers with OpenShell. The old token is rejected on the next request.

### Deployment model: one tenant per VM

This example assumes **one tenant per VM**, with a bucket per tenant and a single bearer token (`ATIF_RELAY_AUTH_TOKEN`) per VM. Multiple sandboxes on the same VM are treated as the same tenant and share the bearer by design — they're already inside the same VM trust boundary and the same downstream bucket. Cross-tenant deployments use separate VMs: separate relays, separate buckets, separate bearers.

This means tenant isolation lives at two layers — the VM (network + uid + filesystem) and the bucket (downstream IAM / MinIO policy) — and not inside the relay's bearer check. The relay validates a single token (`ATIF_RELAY_AUTH_TOKEN`) because that's all this model needs. If a future deployment ever needs per-sandbox-on-same-VM token isolation, the right answer is to either re-introduce the multi-token accept-set (a comma-separated env var + `in` check) or front each sandbox with its own relay container — but neither is needed today.

### Forcing a fresh device-code-like rotation

There is no "force" verb here — credentials are issued by the local script, not by an upstream identity provider. Just delete the `.env` line and re-run bring-up.

### Migrating env-var prefixes from `NEMOCLAW_` to `ATIF_`

Four env vars previously lived under the generic `NEMOCLAW_` prefix; they're now under `ATIF_` to identify the subsystem they actually configure. If your `.env` carries the old names, rename them once:

```bash
sed -i \
  -e 's/^NEMOCLAW_STORAGE_BACKEND=/ATIF_STORAGE_BACKEND=/' \
  -e 's/^NEMOCLAW_STORAGE_BUCKET=/ATIF_STORAGE_BUCKET=/' \
  -e 's/^NEMOCLAW_STORAGE_KEY_PREFIX=/ATIF_STORAGE_KEY_PREFIX=/' \
  -e 's/^NEMOCLAW_S3_REGION=/ATIF_S3_REGION=/' \
  .env
```

Then re-run `bash scripts/bring-up.sh`. The old names are not accepted (no compat shim).

### Migrating from the legacy `codex/` key prefix

The default `ATIF_STORAGE_KEY_PREFIX` was renamed from `codex/` to `hermes/` to match the agent's actual name. Existing object stores keep their old keys — only *new* uploads land under `hermes/`. Three handling options:

1. **New deployments** — no action; everything lands under `hermes/`.
2. **Preserve continuity with existing data** — pin `ATIF_STORAGE_KEY_PREFIX=codex/` in `.env` before bring-up. New uploads continue to use the old prefix.
3. **Consolidate** — pin the new default and move existing objects once:
   ```bash
   # MinIO
   docker run --rm --network=host \
     -e "MC_HOST_local=http://minioadmin:minioadmin@localhost:9000" \
     minio/mc cp --recursive local/<bucket>/codex/ local/<bucket>/hermes/
   docker run --rm --network=host \
     -e "MC_HOST_local=http://minioadmin:minioadmin@localhost:9000" \
     minio/mc rm --recursive --force local/<bucket>/codex/

   # S3 (run from a host with the right IAM)
   aws s3 mv --recursive s3://<bucket>/codex/ s3://<bucket>/hermes/
   ```

### Tearing down

```bash
bash scripts/00-host-services.sh down   # stops minio + relay (preserves volumes)
```

To also wipe the MinIO data:

```bash
bash scripts/00-host-services.sh down --volumes
```

## Troubleshooting

| Symptom | Probable cause | Fix |
|---|---|---|
| Sandbox logs `403 bad bearer token` from the relay | The sandbox's `AWS_SESSION_TOKEN` placeholder didn't get substituted, OR the relay's `ATIF_RELAY_AUTH_TOKEN` doesn't match | Confirm the OpenShell provider exists: `openshell provider get hermes-direct-atif-export-relay`. Confirm the relay's env: `docker exec atif-export-relay env \| grep ATIF_RELAY_AUTH_TOKEN`. The provider-stored token and the relay's env must match. Also check the supervisor log for `credential injection failed` warnings — if present, the placeholder didn't resolve at egress (provider not attached or credential revision drift from re-running `provider create`; the idempotent path in `scripts/02-providers.sh` prevents the latter). |
| Sandbox logs `403 missing x-amz-security-token` from the relay | `AWS_SESSION_TOKEN` is unset in the sandbox env, or the sandbox image predates the AWS_SESSION_TOKEN transport switch | Rebuild and recreate the sandbox: `openshell sandbox delete --name hermes-direct && bash scripts/03-sandbox.sh`. Confirm with `openshell sandbox exec --name hermes-direct -- env \| grep AWS_SESSION_TOKEN` that the placeholder is set. |
| Relay log `downstream_error code=AccessDenied` | The relay's IAM identity (instance profile, for `s3`) lacks `s3:PutObject` on the bucket | Verify with `aws s3 cp /tmp/probe s3://<bucket>/probe.txt` from the host. Update the IAM policy if denied. |
| Relay log `downstream_error code=NoSuchBucket` | Bucket doesn't exist or the relay is pointing at the wrong region | For `s3`: confirm bucket exists in `ATIF_S3_REGION`. For `minio`: confirm `00-host-services.sh` created the bucket. |
| Relay log `downstream_exception` with connection error | Downstream container (MinIO) is down, or network egress blocked | Check `docker ps`. For `s3`, verify HTTPS:443 to `s3.<region>.amazonaws.com` is allowed by your VPC. |
| Sandbox uploads succeed but objects don't show up | Bucket name mismatch between `ATIF_STORAGE_BUCKET` (relay accept-list) and the bucket the relay's downstream client targets | Both must match. The relay's accept-list is the source of truth; `s3_client.put_object` uses the bucket from the request path. |
| `mc: <ERROR> Access Denied` when running `mc` directly | `docker run --rm minio/mc alias set ...` doesn't persist between invocations | Use the inline form: `docker run --rm -e MC_HOST_local=http://USER:PASS@localhost:9000 minio/mc <cmd>` |
| Supervisor logs `NET:FAIL [LOW] host.openshell.internal:18443` and no traffic at the relay | Likely a transport mismatch: sandbox env says `https://` but the relay is HTTP, or someone re-enabled TLS without the upstream OpenShell EKU fix landing | Confirm both sides: `openshell sandbox exec --name hermes-direct -- env \| grep AWS_ENDPOINT_URL` should be `http://...:18443`. `docker logs atif-export-relay \| head` should show `transport=http`. See "Why this leg is plain HTTP" above. |
| Relay won't start: `required env var unset: ATIF_RELAY_AUTH_TOKEN` | `.env` has no `ATIF_RELAY_AUTH_TOKEN` set | Run `bash scripts/02-providers.sh` to issue a token, or set the var manually in `.env`. |

## Files

| Path | Role |
|---|---|
| [`extras/atif-export-relay/relay.py`](../extras/atif-export-relay/relay.py) | The relay service. Validates bearer tokens, forwards PUTs to the configured downstream via boto3. |
| [`extras/atif-export-relay/Dockerfile`](../extras/atif-export-relay/Dockerfile) | python:3.13-slim + aiohttp + boto3. |
| [`extras/atif-export-relay/generate-tls-cert.sh`](../extras/atif-export-relay/generate-tls-cert.sh) | Dormant. One-shot 10-year self-signed cert generator for the relay listener — kept on disk for re-enabling TLS once the upstream OpenShell EKU fix lands (see "Why this leg is plain HTTP"). Not currently called by any bring-up step. |
| [`extras/docker-compose.yml`](../extras/docker-compose.yml) | Adds `atif-export-relay` (profiles: minio, s3) and `minio` (profile: minio). |
| [`providers/atif-export-relay.yaml`](../providers/atif-export-relay.yaml) | OpenShell v2 provider profile (`nemoclaw-atif-export-relay`) holding the per-sandbox `ATIF_RELAY_AUTH_TOKEN` credential. |
| [`policy.yaml`](../policy.yaml) | `atif_export_relay` network-policy block: HTTPS:18443 to `host.openshell.internal`, PUT-only, IP-restricted. |
| [`agents/hermes/nemo-relay/plugins.toml.in`](../agents/hermes/nemo-relay/plugins.toml.in) | NeMo-Relay observability config; the `[[components.config.atif.storage]]` block is patched in at sandbox-create time when `ATIF_STORAGE_BUCKET` is set. |
