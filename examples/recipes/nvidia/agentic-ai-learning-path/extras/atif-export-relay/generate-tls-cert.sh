#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Generate a CA cert + leaf server cert pair for the atif-export-relay
# listener. The CA cert is added to the sandbox's trust bundle at image
# build time (agents/hermes/Dockerfile); the relay presents the leaf cert
# at TLS handshake time. Both certs are 10-year lifetime — they're only
# ever validated by a sandbox running on the same host, no PKI rotation
# story needed.
#
# Why two certs rather than a single self-signed cert:
# rustls 0.23+ (used by OpenShell's L7 proxy on its outbound to the relay)
# strictly enforces RFC 5280 §4.2.1.9 — a CA:TRUE cert MUST assert
# keyCertSign in keyUsage, and self-signed certs that also serve as TLS
# leafs are ambiguous about which validation path applies. A proper
# CA + leaf split gives rustls an unambiguous chain:
#   leaf (CA:FALSE, digitalSignature, EKU=serverAuth, SAN=…) →
#     CA (CA:TRUE, keyCertSign)
# The CA goes in the sandbox's trust store; the leaf is presented at
# handshake. Same files end up at /etc/atif-export-relay/tls/{cert,key}.pem
# in the relay container, but cert.pem is now the leaf, not the self-signed.
#
# Re-run to rotate. The relay container reads the new cert on restart;
# the sandbox needs to be rebuilt so the new CA is in its CA trust store.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TLS_DIR="$DIR/tls"
mkdir -p "$TLS_DIR"

# Host the cert is issued for. Normally derived from ATIF_RELAY_ENDPOINT by
# scripts/_lib.sh; falls back to the canonical default for standalone runs.
RELAY_HOST="${ATIF_RELAY_HOST:-host.openshell.internal}"

# Re-generate iff (a) any of the three files is missing, (b) the leaf is
# missing serverAuth EKU (old-format self-signed cert), (c) the existing
# leaf CN no longer matches $RELAY_HOST (operator changed the endpoint
# host), or (d) the operator explicitly forced it.
needs_regen=0
if [[ ! -f "$TLS_DIR/ca.crt" || ! -f "$TLS_DIR/server.crt" || ! -f "$TLS_DIR/server.key" ]]; then
  needs_regen=1
elif ! openssl x509 -in "$TLS_DIR/server.crt" -noout -ext extendedKeyUsage 2>/dev/null \
       | grep -q "TLS Web Server Authentication"; then
  needs_regen=1
elif ! openssl x509 -in "$TLS_DIR/server.crt" -noout -subject 2>/dev/null \
       | grep -qE "CN[[:space:]]*=[[:space:]]*${RELAY_HOST}([[:space:]]|$|,)"; then
  needs_regen=1
fi
if [[ "${ATIF_RELAY_FORCE_CERT:-}" == "1" ]]; then
  needs_regen=1
fi

if [[ "$needs_regen" != "1" ]]; then
  echo "Cert pair already present at $TLS_DIR (ATIF_RELAY_FORCE_CERT=1 to regenerate)"
  echo "  CA:     $(openssl x509 -in "$TLS_DIR/ca.crt"     -noout -subject)"
  echo "  Server: $(openssl x509 -in "$TLS_DIR/server.crt" -noout -subject)"
  exit 0
fi

# Use a temp dir for the intermediate CSR and CA key so they don't litter
# the on-disk cert dir (the CA private key isn't a runtime artifact —
# operators who care about long-term rotation can save it from here).
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

# ── CA cert (self-signed, CA:TRUE, keyCertSign) ────────────────────────────
openssl req -x509 -newkey rsa:4096 -days 3650 -nodes \
  -keyout "$TMP/ca.key" \
  -out    "$TLS_DIR/ca.crt" \
  -subj   "/CN=atif-export-relay CA" \
  -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign"

# ── Leaf server cert (CA:FALSE, digitalSignature+keyEncipherment, EKU=serverAuth) ──
# Generate a CSR, then sign it with the CA. The leaf gets the SANs nemo-relay
# uses to address the relay across docker/host networking.
openssl req -new -newkey rsa:4096 -nodes \
  -keyout "$TLS_DIR/server.key" \
  -out    "$TMP/leaf.csr" \
  -subj   "/CN=$RELAY_HOST"

# SAN list: $RELAY_HOST first, then the docker/host aliases that remain
# useful regardless of the configured primary host. Skip an alias if it
# equals $RELAY_HOST to avoid a duplicate DNS entry.
san_entries=("DNS:$RELAY_HOST")
for alias in host.openshell.internal host.containers.internal host.docker.internal localhost; do
  [[ "$alias" == "$RELAY_HOST" ]] && continue
  san_entries+=("DNS:$alias")
done
san_entries+=("IP:127.0.0.1")
san_csv="$(IFS=,; echo "${san_entries[*]}")"

cat > "$TMP/leaf.ext" <<EOF
basicConstraints = critical,CA:FALSE
keyUsage = critical,digitalSignature,keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = $san_csv
EOF

openssl x509 -req -in "$TMP/leaf.csr" -days 3650 \
  -CA "$TLS_DIR/ca.crt" -CAkey "$TMP/ca.key" -CAcreateserial \
  -out "$TLS_DIR/server.crt" \
  -extfile "$TMP/leaf.ext"

chmod 600 "$TLS_DIR/server.key"
chmod 644 "$TLS_DIR/server.crt"
chmod 644 "$TLS_DIR/ca.crt"

echo "Generated CA + leaf cert pair under $TLS_DIR:"
echo "  CA:     $(openssl x509 -in "$TLS_DIR/ca.crt"     -noout -subject)"
echo "  Server: $(openssl x509 -in "$TLS_DIR/server.crt" -noout -subject)"
