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

Two `.env` knobs control export, split by scope:

- **`ATIF_EXPORT_MODE`** *(deployment-wide)* — `local` *(default)* keeps traces in the sandbox at `/tmp/atif` (recoverable via `scripts/download-traces.sh`; no host services); `relay` sends them through the host-side `atif-export-relay`.
- **`ATIF_RELAY_BACKEND`** *(relay-only, required when `mode=relay`)* — the relay's downstream:
  - **`minio`** — local MinIO container, no AWS infrastructure required. Use for testing the full upload path before AWS infra exists.
  - **`s3`** — real AWS S3. Uses the host EC2 instance profile for the relay's outbound credentials (no static keys on the host).
  - **`s3-compatible`** — any external S3-compatible store reached via an explicit endpoint + static/HMAC creds (`ATIF_RELAY_S3_ENDPOINT` / `ATIF_RELAY_S3_ACCESS_KEY` / `ATIF_RELAY_S3_SECRET_KEY`): OCI Object Storage (S3 Compat API), Nebius, GCS XML/interop, self-hosted. See "[Extending to other clouds](#extending-to-other-clouds)".

Switching is a one- or two-line edit in `.env`.

## Quick start — MinIO

Local-only flow, no AWS account needed.

```bash
cat >>.env <<'EOF'
ATIF_EXPORT_MODE=relay
ATIF_RELAY_BACKEND=minio
ATIF_RELAY_BUCKET=nemo-relay-traces
ATIF_RELAY_KEY_PREFIX=hermes/      # optional static folder (relay-applied)
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
ATIF_EXPORT_MODE=relay
ATIF_RELAY_BACKEND=s3
ATIF_RELAY_BUCKET=your-traces-bucket-name
ATIF_RELAY_S3_REGION=us-west-2
# Relay scopes every object key under the EC2 instance-id (matches the IAM
# policy below) → final keys are "<instance-id>/<session>.atif.json".
ATIF_RELAY_PREFIXER=ec2-instance-id
EOF

bash scripts/00-host-services.sh   # starts atif-export-relay (boto3 picks up IMDS creds)
bash scripts/bring-up.sh
```

The host EC2's IAM role is what authenticates to S3 — there are no static AWS keys anywhere in this flow. The relay's `boto3.Session()` automatically fetches and rotates short-lived STS credentials from IMDS.

**The relay owns the bucket and the prefix; the sandbox bakes neither.** Neither S3 nor the sandbox auto-applies them — the sandbox sends a *vestigial placeholder* bucket and a *bare* object key (`PUT /atif-export/<session>.atif.json`), and the relay rewrites both: it writes to the configured `ATIF_RELAY_BUCKET` under a key prefix it composes itself (see "[Key prefixing](#key-prefixing)"). With `ATIF_RELAY_PREFIXER=ec2-instance-id`, the relay resolves the EC2 instance-id from IMDSv2 **at startup** (fail-loud: it refuses to start if IMDS is unreachable) and prepends `"<instance-id>/"`, so traces land exactly where the instance-scoped IAM policy below permits. The sandbox image therefore carries no real bucket, prefix, or credentials and is fully generic — and a compromised sandbox cannot influence where traces land.

### Key prefixing

The relay composes every object key from two relay-owned knobs (the sandbox is not trusted to assert its own scope):

```
effective_prefix = prefixer.compute() + ATIF_RELAY_KEY_PREFIX
final key         = effective_prefix + <bare key from sandbox>
```

| `ATIF_RELAY_PREFIXER` | `ATIF_RELAY_KEY_PREFIX` | Resulting key |
|---|---|---|
| `none` *(default)* | *(empty)* | `<session>.atif.json` (bucket root) |
| `none` | `hermes/` | `hermes/<session>.atif.json` (e.g. MinIO dev) |
| `ec2-instance-id` | *(empty)* | `<instance-id>/<session>.atif.json` |
| `ec2-instance-id` | `hermes/` | `<instance-id>/hermes/<session>.atif.json` |

`ec2-instance-id` resolves the EC2 instance-id via IMDSv2 once at relay startup and memoizes it; a replaced instance (new id) self-corrects on the next relay restart with no sandbox rebuild. Add your own strategy (hostname, date-partition, tenant-from-tag, …) by subclassing `KeyPrefixer` and registering it in [`extras/atif-export-relay/backends/prefixers.py`](../extras/atif-export-relay/backends/prefixers.py) — same extension pattern as storage backends. Prefixing is applied uniformly to both backends ([`s3_compatible.py`](../extras/atif-export-relay/backends/s3_compatible.py)); MinIO normally runs `prefixer=none`.

### Required IAM policy for the EC2 instance role

Minimum-privilege policy. With `ATIF_RELAY_PREFIXER=ec2-instance-id` the relay writes
only under `<instance-id>/`, so scope `s3:PutObject` to that path — the instance
role then physically cannot write outside its own prefix:

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

`${instance-id}` is a placeholder you substitute at provisioning time (Terraform/
CloudFormation/etc.) with the actual `i-…` of the host — the same id the relay
resolves from IMDS, so the policy's allowed path and the relay's key prefix match.
Only `s3:PutObject` is needed: the relay sets no ACL (no `s3:PutObjectAcl`) and
makes no `ListBucket`/`GetBucketLocation` call (its startup probe only checks that
boto3 has usable credentials). For an unscoped setup, use
`arn:aws:s3:::your-traces-bucket-name/*` with `ATIF_RELAY_PREFIXER=none`.

If the bucket uses SSE-KMS, add:

```json
{
  "Sid": "AllowKMSEncrypt",
  "Effect": "Allow",
  "Action": ["kms:GenerateDataKey", "kms:Decrypt"],
  "Resource": "arn:aws:kms:<region>:<account>:key/<key-id>"
}
```

The relay is the per-request policy boundary: it writes every object to its single configured `ATIF_RELAY_BUCKET` (the sandbox's request bucket is a vestigial placeholder, ignored — `extras/atif-export-relay/relay.py`), and its prefixer scopes every key under the resolved `<instance-id>/`. So a compromised sandbox can influence neither the bucket nor the prefix, regardless of what it requests — strictly stronger than an allowlist.

## How the auth model works

The challenge: NeMo-Relay's S3 plugin reads `AWS_*` env vars at startup and uses them as inputs to AWS SigV4 signing on every PutObject. We want the per-sandbox bearer to ride to the relay through OpenShell's L7 proxy, which substitutes placeholders into the outbound request at egress — but SigV4's signature is a cryptographic hash, and the bearer token can't be embedded *inside* a SigV4 `Credential=AKID/.../aws4_request` field where the proxy's text-substitution path can't reach it (none of the proxy's recognized header patterns match a placeholder buried in that comma-separated, slash-delimited substring).

The solution: ride the bearer in the standalone `x-amz-security-token` HTTP header, which the AWS SDK emits verbatim from `AWS_SESSION_TOKEN`. A whole-header-value placeholder is exactly the substitution shape OpenShell's L7 proxy handles via its first match branch.

1. Bring-up generates a random bearer token (`atif-<hex>`) once into the gitignored `.bootstrap/cache/atif-relay-token` (via `scripts/_lib.sh`, like the Outlook refresh token — never written to `.env`). The same value is then read from that cache by both consumers: `scripts/00-host-services.sh` passes it to the relay container, and `scripts/02-providers.sh` registers it in OpenShell's provider store as the credential `ATIF_RELAY_AUTH_TOKEN`. (Set `ATIF_RELAY_AUTH_TOKEN` in `.env` to override.)
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
   The destination is the in-container **atif-bridge** sidecar — a pure HTTP→HTTPS protocol shim running as the sandbox uid. The bridge does not inspect or modify headers; it re-emits each request as HTTPS to `host.openshell.internal:18443` using Python's `ssl` module (OpenSSL backend). The bridge exists because nemo-relay's rustls TLS client cannot validate OpenShell's L7-proxy MITM cert — see "Sandbox→relay TLS via Python protocol-bridge sidecar" below.
4. OpenShell's L7 proxy intercepts the bridge's HTTPS outbound, MITM-terminates it, iterates outbound headers, and matches the standalone placeholder in `x-amz-security-token` against `rewrite_header_value`'s direct-match branch. The proxy substitutes the real bearer:
   ```
   x-amz-security-token: atif-<hex>                                    ← resolved
   ```
   The `Authorization` SigV4 envelope contains no placeholder, so it passes through untouched. The fail-closed scan confirms no placeholders remain in the rewritten request, and the proxy forwards upstream.
5. `atif-export-relay` reads the bearer header (default `X-Amz-Security-Token`; configurable via `ATIF_RELAY_AUTH_HEADER`) and compares it constant-time against `ATIF_RELAY_AUTH_TOKEN`. The SigV4 envelope is ignored entirely — neither the proxy nor the relay verifies its signature, and the relay's outbound leg is freshly signed by boto3 with real downstream credentials.
6. The relay ignores the request's vestigial placeholder bucket and constructs a fresh PutObject to its configured `ATIF_RELAY_BUCKET`, under the relay-owned key prefix, via boto3 (which signs correctly with real downstream credentials from IMDS or MinIO admin) and forwards to the configured downstream.

**Threat model**:

- Real AWS / MinIO credentials are only present on the host, only in the `atif-export-relay` process. Never enter the sandbox.
- Sandbox-side credentials are scoped bearer tokens. If exfiltrated, the attacker can submit S3-shaped PutObject requests to the relay but is bounded by (a) the relay writing only to its single configured `ATIF_RELAY_BUCKET` — the request's bucket is a vestigial placeholder, ignored, so the sandbox cannot choose the target bucket at all, (b) the relay's key prefixer — with `ec2-instance-id` the relay forces every key under `<instance-id>/`, server-side, regardless of the key the request asks for, (c) the downstream IAM policy (PutObject-only on `<bucket>/<instance-id>/*`), and (d) network access to the host's `:18443`. They cannot reach AWS APIs directly, cannot read or delete existing objects, and cannot reach other AWS services.
- Revocation granularity: the bearer token is **per VM, not per sandbox**, and that's the chosen granularity given one tenant per VM (see "[Deployment model](#deployment-model-one-tenant-per-vm)"). Rotating `ATIF_RELAY_AUTH_TOKEN` revokes export access for every sandbox on the VM — which is the same scope of trust anyway, since they belong to the same tenant. To rotate: delete the cache file and re-run bring-up (see "[Rotating the auth token](#rotating-the-auth-token)").

### Sandbox→relay TLS via Python protocol-bridge sidecar

The sandbox→relay leg is **TLS end-to-end on the bytes that cross the trust boundary** (sandbox container → host relay), accomplished via a small in-sandbox protocol-bridge sidecar. The only in-container plaintext hop is loopback HTTP between nemo-relay-cli and the bridge — same network namespace, never on the wire. Bearer credentials remain in the OpenShell L7 proxy's process memory only; they never enter nemo-relay, the bridge, or any sandbox process memory.

#### Wire diagram

```
nemo-relay-cli (rustls, sandbox uid)
  └─ plain HTTP to 127.0.0.1:18444 (loopback, in-container)
                       │
                       ▼
       atif-bridge.py (sandbox uid, Python ssl = OpenSSL)
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
| Hermes agent code | No |
| nemo-relay | No — only the placeholder string |
| atif-bridge | No — only the placeholder string |
| OpenShell L7 proxy | **Yes** — resolves placeholder during MITM |
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
rm -f .bootstrap/cache/atif-relay-token .bootstrap/cache/atif-relay-token.registered
bash scripts/bring-up.sh
```

Bring-up regenerates the token into the cache, recreates the relay with the new value (its env changed), and re-registers with OpenShell (the fingerprint no longer matches). The old token is rejected on the next request. (To pin a specific value instead, set `ATIF_RELAY_AUTH_TOKEN` in `.env` — it overrides the cache.)

### Deployment model: one tenant per VM

This example assumes **one tenant per VM**, with a bucket per tenant and a single bearer token (`ATIF_RELAY_AUTH_TOKEN`) per VM. Multiple sandboxes on the same VM are treated as the same tenant and share the bearer by design — they're already inside the same VM trust boundary and the same downstream bucket. Cross-tenant deployments use separate VMs: separate relays, separate buckets, separate bearers.

This means tenant isolation lives at two layers — the VM (network + uid + filesystem) and the bucket (downstream IAM / MinIO policy) — and not inside the relay's bearer check. The relay validates a single token (`ATIF_RELAY_AUTH_TOKEN`) because that's all this model needs. If a future deployment ever needs per-sandbox-on-same-VM token isolation, the right answer is to either re-introduce the multi-token accept-set (a comma-separated env var + `in` check) or front each sandbox with its own relay container — but neither is needed today.

### Forcing a fresh device-code-like rotation

There is no "force" verb here — credentials are issued by the local script, not by an upstream identity provider. Just delete the `.env` line and re-run bring-up.

### Customizing the relay endpoint

The relay's public endpoint is one operator-facing knob: `ATIF_RELAY_ENDPOINT` (default `https://host.openshell.internal:18443`). Everything that depends on it — the relay bind port, the sandbox-side bridge upstream URL, the OpenShell provider profile endpoint, the policy egress rule, and the leaf cert CN/SAN — is derived from that value during bring-up.

Common cases:

- **Port conflict** — set `ATIF_RELAY_ENDPOINT=https://host.openshell.internal:19443` in `.env` and re-run bring-up. No cert regeneration needed (the cert SAN is host-bound, not port-bound).
- **Different DNS name** — set `ATIF_RELAY_ENDPOINT=https://my-vm.local:18443`. The next bring-up auto-detects the CN mismatch and regenerates the leaf cert with the new primary SAN. Use `ATIF_RELAY_FORCE_CERT=1` to force regen explicitly.

The host's `.env` is the source of truth; `scripts/_lib.sh` validates the URL on load (must be `https://`, must include `host:port`, port must be numeric) and exports `ATIF_RELAY_HOST` / `ATIF_RELAY_PORT` for downstream consumers.

### Tearing down

```bash
bash scripts/00-host-services.sh down   # stops minio + relay (preserves volumes)
```

To also wipe the MinIO data:

```bash
bash scripts/00-host-services.sh down --volumes
```

## Extending to other clouds

The relay pattern is cloud-agnostic by design: the sandbox→relay leg is always
S3-shaped (nemo-relay's `object_store` speaks S3) and carries only a bearer
placeholder, so the relay is the single translation point where real credentials
live and the downstream is chosen. Two extension axes, both registries:

**1. Storage backend** (`ATIF_RELAY_BACKEND`, registry in
[`backends/__init__.py`](../extras/atif-export-relay/backends/__init__.py)). Most
clouds expose an S3-compatible API, so they need **no new code** — just
`ATIF_RELAY_BACKEND=s3-compatible` + the `ATIF_RELAY_S3_*` endpoint/keys:

| Target | Object store | Backend | How |
|---|---|---|---|
| AWS | S3 | `s3` | IMDS creds, no endpoint |
| MinIO | S3-compatible | `minio` | zero-config local preset of `s3-compatible` (defaults to `http://localhost:9000` + `minioadmin`) |
| OCI | Object Storage (S3 Compat API) | `s3-compatible` | per-namespace endpoint + Customer Secret Keys |
| Nebius | S3-compatible | `s3-compatible` | Nebius endpoint + access/secret keys |
| GCP | GCS XML / interop | `s3-compatible` | interop endpoint + HMAC keys |
| Azure | Blob (**not** S3-compatible) | *new backend* | implement the generic `StorageBackend` ABC ([`base.py`](../extras/atif-export-relay/backends/base.py)) with `azure-storage-blob` (map bucket→container, key→blob); it does **not** inherit `S3CompatibleBackend` |

`minio` and `s3-compatible` are the **same class** ([`s3_endpoint.py`](../extras/atif-export-relay/backends/s3_endpoint.py)) reading the **same env** (`ATIF_RELAY_S3_ENDPOINT` / `_ACCESS_KEY` / `_SECRET_KEY` / `_REGION`); `minio` just supplies local-dev defaults instead of requiring them. A **remote endpoint must be `https://`** — the relay refuses cleartext credentials (only loopback, e.g. local MinIO, may be `http://`). The generic↔S3-compatible ABC split ([`base.py`](../extras/atif-export-relay/backends/base.py) vs [`s3_compatible.py`](../extras/atif-export-relay/backends/s3_compatible.py)) is what lets Azure slot in without S3 baggage.

**2. Key-prefix strategy** (`ATIF_RELAY_PREFIXER`, registry in
[`prefixers.py`](../extras/atif-export-relay/backends/prefixers.py)). Each cloud's
instance-identity comes from a different metadata service, so each gets a ~20-line
`KeyPrefixer` sibling of `ec2-instance-id`: `gcp-instance-id`
(`metadata.google.internal`, `Metadata-Flavor: Google`), `azure-vm-id` (IMDS
`/metadata/instance`, `Metadata:true`), `oci-instance-id` (`/opc/v2/instance/id`),
etc. Drop-in via the registry; no core changes.

## Troubleshooting

| Symptom | Probable cause | Fix |
|---|---|---|
| Sandbox logs `403 bad bearer token` from the relay | The sandbox's `AWS_SESSION_TOKEN` placeholder didn't get substituted, OR the relay's `ATIF_RELAY_AUTH_TOKEN` doesn't match | Confirm the OpenShell provider exists: `openshell provider get hermes-direct-atif-export-relay`. Confirm the relay's env: `docker exec atif-export-relay env \| grep ATIF_RELAY_AUTH_TOKEN`. The provider-stored token and the relay's env must match. Also check the supervisor log for `credential injection failed` warnings — if present, the placeholder didn't resolve at egress (provider not attached or credential revision drift from re-running `provider create`; the idempotent path in `scripts/02-providers.sh` prevents the latter). |
| Sandbox logs `403 missing x-amz-security-token` from the relay | `AWS_SESSION_TOKEN` is unset in the sandbox env, or the sandbox image predates the AWS_SESSION_TOKEN transport switch | Rebuild and recreate the sandbox: `openshell sandbox delete --name hermes-direct && bash scripts/03-sandbox.sh`. Confirm with `openshell sandbox exec --name hermes-direct -- env \| grep AWS_SESSION_TOKEN` that the placeholder is set. |
| Relay won't start: `downstream credentials unavailable at startup: could not resolve EC2 instance-id from IMDS` | `ATIF_RELAY_PREFIXER=ec2-instance-id` but IMDS is unreachable — not on EC2, IMDS disabled (`AWS_EC2_METADATA_DISABLED`), or the hop limit is too low for the relay's network namespace | This is fail-loud by design (better than silent runtime 403s). Confirm the host is EC2 and IMDS works: `TOKEN=$(curl -sX PUT http://169.254.169.254/latest/api/token -H 'X-aws-ec2-metadata-token-ttl-seconds: 60'); curl -s -H "X-aws-ec2-metadata-token: $TOKEN" http://169.254.169.254/latest/meta-data/instance-id`. The relay uses `network_mode: host`, so if boto3 creds resolve, the instance-id should too. To export without instance scoping, set `ATIF_RELAY_PREFIXER=none`. |
| Relay log `downstream_error code=AccessDenied` | The relay's IAM identity (instance profile, for `s3`) lacks `s3:PutObject`, OR the key prefix doesn't match the IAM-scoped path (e.g. policy allows `<bucket>/<instance-id>/*` but the key isn't under `<instance-id>/`) | Check the relay's resolved prefix in `docker logs atif-export-relay \| grep key_prefix`; it must match the `${instance-id}` in the IAM policy. Verify writeability with `aws s3api put-object --bucket <bucket> --key "<instance-id>/probe.txt" --body /etc/hostname --region <region>`. Update the IAM policy or the prefixer if mismatched. |
| Relay log `downstream_error code=NoSuchBucket` | Bucket doesn't exist or the relay is pointing at the wrong region | For `s3`: confirm `ATIF_RELAY_BUCKET` exists in `ATIF_RELAY_S3_REGION`. For `minio`: confirm `00-host-services.sh` created the bucket. |
| Relay log `downstream_exception` with connection error | Downstream container (MinIO) is down, or network egress blocked | Check `docker ps`. For `s3`, verify HTTPS:443 to `s3.<region>.amazonaws.com` is allowed by your VPC. |
| Sandbox uploads succeed (relay logs `forwarded status=200`) but objects aren't where you expect | Looking under the wrong bucket/prefix | The relay writes to `ATIF_RELAY_BUCKET` under `<prefixer output><ATIF_RELAY_KEY_PREFIX>`. Check the relay's startup log (`bucket=… key_prefix=…`) and the per-PUT `put … key=…` line for the exact destination — that's the source of truth, not anything in the sandbox. |
| `mc: <ERROR> Access Denied` when running `mc` directly | `docker run --rm minio/mc alias set ...` doesn't persist between invocations | Use the inline form: `docker run --rm -e MC_HOST_local=http://USER:PASS@localhost:9000 minio/mc <cmd>` |
| Supervisor logs `NET:FAIL [LOW] host.openshell.internal:18443` and no traffic at the relay | Likely a transport mismatch: sandbox env says `https://` but the relay is HTTP, or someone re-enabled TLS without the upstream OpenShell EKU fix landing | Confirm both sides: `openshell sandbox exec --name hermes-direct -- env \| grep AWS_ENDPOINT_URL` should be `http://...:18443`. `docker logs atif-export-relay \| head` should show `transport=http`. See "Why this leg is plain HTTP" above. |
| Relay won't start: `required env var unset: ATIF_RELAY_AUTH_TOKEN` | The relay was started outside the bring-up scripts (which export the token from `.bootstrap/cache/atif-relay-token`), or `ATIF_EXPORT_MODE` isn't `relay` | Bring it up via `bash scripts/00-host-services.sh` (it generates/reads the cache and exports the token before `docker compose up`). To pin a value, set `ATIF_RELAY_AUTH_TOKEN` in `.env`. |

## Files

| Path | Role |
|---|---|
| [`extras/atif-export-relay/relay.py`](../extras/atif-export-relay/relay.py) | The relay service. Validates bearer tokens; writes every PUT to `ATIF_RELAY_BUCKET` (ignoring the request's placeholder bucket). Key-agnostic — the backend owns key prefixing. |
| [`extras/atif-export-relay/backends/base.py`](../extras/atif-export-relay/backends/base.py) | Generic `StorageBackend` ABC (the contract `relay.py` depends on) + `PutResult` and error types. A future non-S3 backend implements this directly. |
| [`extras/atif-export-relay/backends/s3_compatible.py`](../extras/atif-export-relay/backends/s3_compatible.py) | `S3CompatibleBackend` ABC shared by every boto3 backend: the PutObject + error translation, the key-prefix lifecycle, and per-request effective-key logging. The single place the prefix contract lives. |
| [`extras/atif-export-relay/backends/s3_endpoint.py`](../extras/atif-export-relay/backends/s3_endpoint.py) | `S3CompatibleEndpointBackend` — generic custom-endpoint + static-creds backend (`ATIF_RELAY_S3_*`) for any external S3-compatible store (OCI/Nebius/GCS/self-hosted). `MinioBackend` is its local-dev preset. |
| [`extras/atif-export-relay/backends/prefixers.py`](../extras/atif-export-relay/backends/prefixers.py) | Pluggable key-prefix strategies (`none`, `ec2-instance-id`) selected by `ATIF_RELAY_PREFIXER`. The `ec2-instance-id` strategy resolves the EC2 instance-id via botocore's `IMDSFetcher` at relay startup (fail-loud). Add new strategies (e.g. `gcp-instance-id`) here. |
| [`extras/atif-export-relay/Dockerfile`](../extras/atif-export-relay/Dockerfile) | python:3.13-slim + aiohttp + boto3. |
| [`extras/atif-export-relay/generate-tls-cert.sh`](../extras/atif-export-relay/generate-tls-cert.sh) | Dormant. One-shot 10-year self-signed cert generator for the relay listener — kept on disk for re-enabling TLS once the upstream OpenShell EKU fix lands (see "Why this leg is plain HTTP"). Not currently called by any bring-up step. |
| [`extras/docker-compose.yml`](../extras/docker-compose.yml) | Adds `atif-export-relay` (profiles: minio, s3) and `minio` (profile: minio). |
| [`providers/atif-export-relay.yaml`](../providers/atif-export-relay.yaml) | OpenShell v2 provider profile (`nemoclaw-atif-export-relay`) holding the per-sandbox `ATIF_RELAY_AUTH_TOKEN` credential. |
| [`policy.yaml`](../policy.yaml) | `atif_export_relay` network-policy block: HTTPS:18443 to `host.openshell.internal`, PUT-only, IP-restricted. |
| [`agents/hermes/nemo-relay/plugins.toml.in`](../agents/hermes/nemo-relay/plugins.toml.in) | NeMo-Relay observability config; the `[[components.config.atif.storage]]` block (with a placeholder bucket + empty key_prefix) is patched in at sandbox-create time when `ATIF_EXPORT_MODE=relay`. The relay owns the real bucket/prefix. |
