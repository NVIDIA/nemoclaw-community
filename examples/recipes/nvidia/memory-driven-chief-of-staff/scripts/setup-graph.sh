#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Connect a mailbox, so the scheduled intake can read it.
#
# Runs on the host, not in the sandbox: it talks to `openshell`, which is where
# the credential is registered and refreshed. `install.sh` is the opposite —
# that one talks to `hermes` and belongs in the sandbox.
#
# The device-code flow is used rather than a redirect. There is no browser on a
# server and no port to redirect to, and the code is shown on this terminal
# while the sign-in happens on whatever machine the operator already trusts.
# What comes back is a refresh token, which is handed to the gateway and never
# written into the sandbox.
#
#     SANDBOX_STORAGE_PATH=/var/lib/docker bash scripts/setup-graph.sh

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE_ROOT="$(dirname "$HERE")"
PROFILE_ID="memory-driven-cos-graph-user"
PROFILE_YAML="$RECIPE_ROOT/providers/graph-user.yaml"
PROVIDER="${GRAPH_PROVIDER_NAME:-memory-driven-cos-graph}"
SANDBOX="${OPENSHELL_SANDBOX_NAME:-${SANDBOX_NAME:-hermes}}"
USABLE_KEY="MS_GRAPH_ACCESS_TOKEN"
# Named for the shared helpers, so their error paths tell the user to re-run
# the script they actually ran.
SETUP_SCRIPT="scripts/setup-graph.sh"
WANT_HOST="graph.microsoft.com"

# Microsoft's own public client id for the device-code flow, and the tenant
# most people want. Both are overridable: an organisation that registers its
# own application passes its ids rather than editing this file.
CLIENT_ID="${GRAPH_CLIENT_ID:-}"
TENANT_ID="${GRAPH_TENANT_ID:-common}"
# Exactly what the collector uses. `User.Read` is not incidental: it is
# what makes `/me` readable, and `/me` is how the collector learns which
# mailbox it is reading — which decides whether a message addressed the
# user or copied them. Requesting `Mail.Read` alone produced a setup that
# depended on a permission it never asked for.
SCOPES="offline_access https://graph.microsoft.com/Mail.Read https://graph.microsoft.com/User.Read"

# First, and before the device-code flow: an Entra consent granted on a
# machine that cannot register the jobs is a consent spent for nothing, and
# it is granted in a browser to a tenant an administrator may have to approve.
. "$HERE/require-linux.sh"
require_linux

if ! command -v openshell >/dev/null 2>&1; then
  if [[ -n "${OPENSHELL_SANDBOX:-}" ]]; then
    echo "This is running inside the sandbox, where openshell is not." >&2
    echo "" >&2
    echo "Unlike install.sh, this step belongs on the host. From there:" >&2
    echo "  cd <this recipe> && bash scripts/setup-graph.sh" >&2
    exit 1
  fi
  echo "openshell is not on PATH, and this is not a NemoClaw sandbox." >&2
  echo "This recipe's mailbox credential is held and refreshed by the" >&2
  echo "OpenShell gateway, so there is no supported path without it." >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to complete the device-code flow." >&2
  exit 1
}

# The storage prerequisite, shared by every connector.
# shellcheck source=scripts/require-encrypted-storage.sh
. "$HERE/require-encrypted-storage.sh"
# Field-by-field profile validation, shared by every connector.
# shellcheck source=scripts/validate-provider-profile.sh
. "$HERE/validate-provider-profile.sh"

echo "1/6  Storage encryption"
require_encrypted_storage

echo "2/6  Looking for a mailbox credential this sandbox can already read"
if ! attached="$(openshell sandbox provider list "$SANDBOX" 2>&1)"; then
  echo "Could not list providers on sandbox '$SANDBOX'." >&2
  echo "Check the name with: openshell sandbox list" >&2
  exit 1
fi

reusable=""
while read -r name; do
  [[ -z "$name" ]] && continue
  keys="$(openshell provider get "$name" 2>/dev/null \
    | sed -n 's/.*Credential keys:[[:space:]]*//p' || true)"
  if [[ "$keys" == *"$USABLE_KEY"* ]]; then
    type="$(openshell provider get "$name" 2>/dev/null \
      | sed 's/\x1b\[[0-9;]*m//g' \
      | sed -n 's/^[[:space:]]*Type:[[:space:]]*//p')"
    if [[ "$type" != "$PROFILE_ID" ]]; then
      echo "     '$name' exposes $USABLE_KEY but is type '$type', not" >&2
      echo "     '$PROFILE_ID'. Refusing to reuse it: this recipe's endpoint" >&2
      echo "     policy is read-only and that provider carries its own." >&2
      echo "" >&2
      echo "     Renaming does not help. Two providers cannot both supply" >&2
      echo "     $USABLE_KEY to one sandbox, so GRAPH_PROVIDER_NAME changes" >&2
      echo "     nothing here — the clash is the key, not the name." >&2
      echo "" >&2
      echo "     Either detach '$name' from this sandbox, or attach this" >&2
      echo "     recipe to a sandbox that does not have it:" >&2
      echo "       openshell sandbox provider detach $SANDBOX $name" >&2
      echo "       OPENSHELL_SANDBOX_NAME=<other> bash scripts/setup-graph.sh" >&2
      echo "" >&2
      echo "     Until then the collector still reads $USABLE_KEY on every" >&2
      echo "     tick and will collect mail through '$name' — this refusal" >&2
      echo "     stops the provider being registered, not the reading. From" >&2
      echo "     inside the sandbox a credential carries no provenance, so" >&2
      echo "     the collector cannot tell which provider supplied it." >&2
      exit 1
    fi
    if ! validate_profile "$type"; then
      echo "     '$name' does not carry this recipe's endpoint policy" >&2
      exit 1
    fi
    # And that something renews it. A provider with the right key, the right
    # type and the right policy but no refresh chain attaches cleanly and
    # stops within the hour — reported here as "nothing to do", which is the
    # least useful moment to be told nothing.
    if ! status="$(openshell provider refresh status "$name" \
        --credential-key "$USABLE_KEY" 2>&1)"; then
      echo "     '$name' has no refresh configured; its credential would" >&2
      echo "     expire within the hour. Re-run with FORCE_REAUTH=1." >&2
      exit 1
    fi
    if ! printf '%s' "$status" | grep -q "oauth2_refresh_token"; then
      echo "     '$name' is not configured for token rotation" >&2
      exit 1
    fi
    reusable="$name"
    break
  fi
done < <(printf '%s\n' "$attached" \
         | sed 's/\x1b\[[0-9;]*m//g' \
         | awk 'NR > 1 && NF { print $1 }')

if [[ -n "$reusable" ]]; then
  echo "     reusing attached provider '$reusable' (type and policy verified)"
  if [[ "${FORCE_REAUTH:-0}" != "1" ]]; then
    echo ""
    echo "Nothing to do. To replace its credential — after revoking consent,"
    echo "or if the refresh chain was broken — re-run with:"
    echo "  FORCE_REAUTH=1 bash scripts/setup-graph.sh"
    exit 0
  fi
  echo "     FORCE_REAUTH=1, so its credential will be replaced"
  PROVIDER="$reusable"
else
  echo "     none attached that exposes $USABLE_KEY"
fi

echo "3/6  Application registration"
if [[ -z "$CLIENT_ID" ]]; then
  echo ""
  echo "This needs an Entra application with delegated Mail.Read and"
  echo "offline_access, and public-client (device code) flow enabled."
  echo "docs/set-up-graph.md walks through registering one."
  echo ""
  echo "Then re-run with its ids:"
  echo "  GRAPH_CLIENT_ID=<id> GRAPH_TENANT_ID=<tenant> \\"
  echo "      SANDBOX_STORAGE_PATH=<path> bash scripts/setup-graph.sh"
  exit 1
fi
echo "     client $CLIENT_ID in tenant $TENANT_ID"

echo "4/6  Sign in"
# The device-code flow in two calls. The secret never appears in argv, where
# `ps` would show it; the refresh token comes back on stdout and is consumed by
# the next step through the environment.
if ! DEVICE="$(CLIENT_ID="$CLIENT_ID" TENANT_ID="$TENANT_ID" SCOPES="$SCOPES" \
    python3 - <<'PY'
import json, os, sys, urllib.parse, urllib.request

body = urllib.parse.urlencode({
    "client_id": os.environ["CLIENT_ID"],
    "scope": os.environ["SCOPES"],
}).encode()
url = ("https://login.microsoftonline.com/%s/oauth2/v2.0/devicecode"
       % os.environ["TENANT_ID"])
try:
    with urllib.request.urlopen(urllib.request.Request(url, data=body),
                                timeout=30) as response:
        payload = json.loads(response.read().decode())
except Exception as exc:  # noqa: BLE001
    print(f"could not start the device-code flow: {type(exc).__name__}",
          file=sys.stderr)
    raise SystemExit(1)

print(payload["device_code"])
print(payload["user_code"], file=sys.stderr)
print(payload["verification_uri"], file=sys.stderr)
PY
)"; then
  echo "Sign-in could not be started. Nothing has been configured." >&2
  exit 1
fi

echo ""
echo "Open the address printed above on any machine you trust, and enter the"
echo "code. This terminal waits; nothing is stored until it completes."
echo ""

if ! REFRESH_TOKEN="$(CLIENT_ID="$CLIENT_ID" TENANT_ID="$TENANT_ID" \
    DEVICE_CODE="$DEVICE" python3 - <<'PY'
import json, os, sys, time, urllib.error, urllib.parse, urllib.request

url = ("https://login.microsoftonline.com/%s/oauth2/v2.0/token"
       % os.environ["TENANT_ID"])
body = urllib.parse.urlencode({
    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
    "client_id": os.environ["CLIENT_ID"],
    "device_code": os.environ["DEVICE_CODE"],
}).encode()

deadline = time.time() + 600
while time.time() < deadline:
    try:
        with urllib.request.urlopen(urllib.request.Request(url, data=body),
                                    timeout=30) as response:
            payload = json.loads(response.read().decode())
        break
    except urllib.error.HTTPError as exc:
        detail = json.loads(exc.read().decode() or "{}")
        error = detail.get("error")
        if error == "authorization_pending":
            time.sleep(5)
            continue
        if error == "slow_down":
            time.sleep(10)
            continue
        print(f"sign-in failed: {error or exc.code}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:  # noqa: BLE001
        print(f"could not reach the identity platform: {type(exc).__name__}",
              file=sys.stderr)
        raise SystemExit(1)
else:
    print("sign-in timed out", file=sys.stderr)
    raise SystemExit(1)

# By name, and only this one. The response also carries an access token, which
# expires within the hour; configuring that as the refresh material would give
# a provider that works today and stops tomorrow, reporting healthy throughout.
refresh = payload.get("refresh_token")
if not refresh:
    print("the sign-in returned no refresh token; check that offline_access "
          "is among the application's delegated permissions", file=sys.stderr)
    raise SystemExit(1)
print(refresh)
PY
)"; then
  echo "Nothing has been configured." >&2
  exit 1
fi
echo "     signed in; the refresh token stays on this host"

echo "5/6  Registering the provider"
# Delete-then-import, because import rejects an existing id rather than
# upserting. A profile in use by a live sandbox cannot be deleted, so on a
# re-run the delete is a no-op and the import collides — which is fine, it is
# already registered. What is not fine is suppressing both and carrying on:
# that leaves whatever was registered before in force, including an older
# endpoint policy, and the provider is then created against it.
openshell provider profile delete "$PROFILE_ID" >/dev/null 2>&1 || true
import_out="$(openshell provider profile import --file "$PROFILE_YAML" 2>&1 ||
true)"
if ! openshell provider profile export "$PROFILE_ID" >/dev/null 2>&1; then
  echo "Provider profile '$PROFILE_ID' is not registered." >&2
  printf '%s\n' "$import_out" >&2
  exit 1
fi
if ! validate_profile "$PROFILE_ID"; then
  echo "The registered '$PROFILE_ID' profile is not the one this recipe" >&2
  echo "describes. An older profile is still in force; delete it and re-run:"
  >&2
  echo "  openshell provider profile delete $PROFILE_ID" >&2
  exit 1
fi

if openshell provider get "$PROVIDER" >/dev/null 2>&1; then
  if ! openshell provider update "$PROVIDER" >/dev/null 2>&1; then
    echo "Could not update provider '$PROVIDER'." >&2
    exit 1
  fi
  echo "     updated provider '$PROVIDER'"
else
  if ! openshell provider create --name "$PROVIDER" --type "$PROFILE_ID" \
        --runtime-credentials >/dev/null 2>&1; then
    echo "Could not create provider '$PROVIDER'." >&2
    exit 1
  fi
  echo "     created provider '$PROVIDER'"
fi

if ! GRAPH_REFRESH_TOKEN="$REFRESH_TOKEN" openshell provider refresh configure \
    "$PROVIDER" --credential-key "$USABLE_KEY" \
    --strategy oauth2-refresh-token \
    --material "tenant_id=$TENANT_ID" \
    --material "client_id=$CLIENT_ID" \
    --secret-material-env refresh_token=GRAPH_REFRESH_TOKEN >/dev/null 2>&1;
    then
  echo "Could not configure refresh on '$PROVIDER'." >&2
  echo "Nothing renews the credential, so it would stop within the hour." >&2
  exit 1
fi
unset REFRESH_TOKEN
echo "     refresh configured; the gateway owns renewal from here"

echo "6/6  Attaching to sandbox '$SANDBOX'"
if ! openshell sandbox provider attach "$SANDBOX" "$PROVIDER" >/dev/null 2>&1;
then
  echo "Could not attach. Attach it by hand with:" >&2
  echo "  openshell sandbox provider attach $SANDBOX $PROVIDER" >&2
  exit 1
fi

cat <<EOF

Connected. The collector reads the mailbox on the intake schedule.

The first synchronisation is bounded to a window you choose — seven days by
default. Set it before the first run, in the profile's environment file so the
scheduled job sees it too:

  ENV=\$(hermes -p <profile> config env-path)
  echo 'GRAPH_BACKFILL_DAYS=14' >> "\$ENV"

Seven, fourteen and thirty are the usual answers; any number of days from 1 to
3650 works. The window decides where the first round starts and nothing else:
once the baseline exists, every later change in the folder is reported,
including an older message being deleted.

Check it by running the collector once, inside the sandbox:

  python3 <profile home>/scripts/ingest_graph.py

To revoke: remove consent for the application in your Microsoft account, then

  openshell sandbox provider detach $SANDBOX $PROVIDER
  openshell provider delete $PROVIDER

That ends collection. It does not remove what was already collected — see
docs/data-lifecycle.md for export and reset.
EOF
