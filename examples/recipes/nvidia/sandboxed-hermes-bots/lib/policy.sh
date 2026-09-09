# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Render and apply OpenShell policies.
#
# `openshell policy set` REPLACES a sandbox's whole policy. After creation we
# only ever ADD with `nemoclaw <sandbox> policy-add --from-file --yes`. Those
# files are presets: `preset.name` is required, no top-level `version`, and the
# file must end in .yaml.

# Split INFERENCE_BASE_URL into host/port/tls for the policy.
_inference_endpoint() {
  local url="$INFERENCE_BASE_URL" scheme hostport host port tls
  scheme="${url%%://*}"
  hostport="${url#*://}"; hostport="${hostport%%/*}"
  host="${hostport%%:*}"
  if [[ "$hostport" == *:* ]]; then port="${hostport##*:}"
  elif [[ "$scheme" == https ]]; then port=443
  else port=80; fi
  # OpenShell's proxy terminates nothing; "skip" means it does not inspect TLS.
  tls=skip
  # A host-loopback endpoint is unreachable from a sandbox; steer to the bridge.
  case "$host" in
    127.0.0.1|localhost) host="host.openshell.internal" ;;
  esac
  printf '%s %s %s' "$host" "$port" "$tls"
}

# Render the base policy for a bot to $SWARM_STATE/policies/<sandbox>.yaml
policy_render_base() {
  local name="$1" sb out
  sb=$(sandbox_of "$name")
  out="$SWARM_STATE/policies/$sb.yaml"
  read -r ihost iport itls < <(_inference_endpoint)
  sed -e "s|__INFERENCE_HOST__|$ihost|" -e "s|__INFERENCE_PORT__|$iport|" \
      -e "s|__INFERENCE_TLS__|$itls|" "$SWARM_ROOT/policies/bot.template.yaml" > "$out"
  printf '%s' "$out"
}

# policy_add SANDBOX FILE.yaml  (additive)
policy_add() {
  local sb="$1" f="$2"
  [[ "$f" == *.yaml ]] || die "policy_add: NemoClaw requires a .yaml extension: $f"
  nemoclaw "$sb" policy-add --from-file "$f" --yes >/dev/null 2>&1 \
    || die "policy-add failed for $sb ($f)"
}

# Additive group allowing SANDBOX to reach a teammate api_server on the bridge.
policy_add_peer() {
  local sb="$1" peer="$2" port="$3" f
  f="$SWARM_STATE/policies/$sb-peer-$peer.yaml"
  cat > "$f" <<EOF
preset:
  name: peer-$peer
  description: Reach teammate $peer api_server
network_policies:
  peer-$peer:
    name: peer-$peer
    endpoints:
      - { host: host.openshell.internal, port: $port, tls: skip }
    binaries:
      - { path: /sandbox/.hermes/hermes-agent/venv/bin/python }
      - { path: /sandbox/.hermes/hermes-agent/venv/bin/* }
      - { path: /usr/bin/curl }
      - { path: /bin/sh }
EOF
  policy_add "$sb" "$f"
}

# Print "group host port" lines of a sandbox's current network policy.
policy_endpoints() {
  openshell policy get "$1" --full -o json 2>/dev/null | python3 -c '
import sys, json
d = json.load(sys.stdin)
np = (d.get("policy") or d).get("network_policies") or {}
for g, v in np.items():
    for e in v.get("endpoints", []):
        print(g, e.get("host"), e.get("port"))'
}
