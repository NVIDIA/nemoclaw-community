#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Give the intake collector a Slack credential the gateway can refresh.
#
# Slack rotates user tokens: the access half lasts twelve hours and each refresh
# token is single-use. The OpenShell gateway holds and refreshes the pair; the
# sandbox only ever sees a placeholder that the egress proxy substitutes on the
# way to slack.com. Nothing here writes a Slack credential into the profile, and
# nothing outside the gateway refreshes one — a second refresher does not fail
# loudly, it forks the chain and surfaces days later as an expired credential
# with no obvious cause.
#
# This runs on the HOST, not inside the sandbox — unlike install.sh. A NemoClaw
# sandbox has `hermes` and no `openshell`; the host has `openshell` and no
# `hermes`. Both scripts sit in this directory, so running this one where the
# other belongs is the easy mistake, and it has to fail rather than improvise.

set -euo pipefail

# Same reason as install.sh: every shipped skill declares `platforms: [linux]`,
# so the scheduled path this credential feeds does not run anywhere else.
require_linux() {
  local kernel
  kernel="$(uname -s)"
  if [[ "$kernel" != "Linux" ]]; then
    echo "The scheduled path is Linux only; detected $kernel." >&2
    echo "The fixture walkthrough needs no credential and runs anywhere." >&2
    exit 1
  fi
}
require_linux

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE_ROOT="$(dirname "$HERE")"
SANDBOX="${OPENSHELL_SANDBOX_NAME:-${SANDBOX_NAME:-hermes}}"
PROVIDER="${SLACK_PROVIDER_NAME:-memory-driven-cos-slack-user}"
PROFILE_ID="memory-driven-cos-slack-user"
PROFILE_YAML="$RECIPE_ROOT/providers/slack-user.yaml"
USABLE_KEY="SLACK_USER_TOKEN"
REDIRECT="https://localhost:8899/slack/oauth"
USER_SCOPES="im:read,im:history,mpim:read,mpim:history,channels:read,channels:history,users:read"

if ! command -v openshell >/dev/null 2>&1; then
  if [[ -n "${OPENSHELL_SANDBOX:-}" ]]; then
    echo "This is running inside the sandbox, where openshell is not." >&2
    echo "" >&2
    echo "Unlike install.sh, this step belongs on the host. From there:" >&2
    echo "  cd <this recipe> && bash scripts/setup-slack.sh" >&2
    exit 1
  fi
  echo "openshell is not on PATH, and this is not a NemoClaw sandbox." >&2
  echo "This recipe's Slack credential is held and refreshed by the OpenShell" >&2
  echo "gateway, so there is no supported path without it." >&2
  exit 1
fi
command -v python3 >/dev/null 2>&1 || {
  echo "python3 is required to exchange the authorization code." >&2
  exit 1
}

echo "1/7  Looking for a Slack credential this sandbox can already read"

# `|| true` here would turn every failure into "nothing attached" — a mistyped
# sandbox name, an unauthenticated gateway, a stopped one — and answer by
# creating a duplicate. Ask, then check.
if ! attached="$(openshell sandbox provider list "$SANDBOX" 2>&1)"; then
  echo "Could not list providers on sandbox '$SANDBOX'." >&2
  echo "Check the name with: openshell sandbox list" >&2
  exit 1
fi

# The output is a table whose first column is the provider name, with a header
# row. Take field one from every line after the first, and do not transform it —
# a name is what gets passed back to the same CLI.
#
# Finding a `SLACK_USER_TOKEN` key is not enough to reuse something. A provider
# with the right key but the wrong type carries a different endpoint policy,
# and one with no refresh configured will simply expire in twelve hours. Both
# would attach cleanly and fail later, quietly. So the state is validated and a
# mismatch stops the run rather than being worked around.
validate_provider() {
  local name="$1" detail
  if ! detail="$(openshell provider get "$name" 2>&1)"; then
    echo "     could not read provider '$name'" >&2
    return 1
  fi
  detail="$(printf '%s' "$detail" | sed 's/\x1b\[[0-9;]*m//g')"
  local type
  type="$(printf '%s\n' "$detail" | sed -n 's/^[[:space:]]*Type:[[:space:]]*//p')"
  if [[ "$type" != "$PROFILE_ID" ]]; then
    echo "     '$name' is type '$type', not '$PROFILE_ID'" >&2
    return 1
  fi
  local status
  if ! status="$(openshell provider refresh status "$name" \
      --credential-key "$USABLE_KEY" 2>&1)"; then
    echo "     '$name' has no refresh configured" >&2
    return 1
  fi
  if ! printf '%s' "$status" | grep -q "oauth2_refresh_token"; then
    echo "     '$name' is not configured for token rotation" >&2
    return 1
  fi
  return 0
}

reusable=""
while read -r name; do
  [[ -z "$name" ]] && continue
  keys="$(openshell provider get "$name" 2>/dev/null \
    | sed -n 's/.*Credential keys:[[:space:]]*//p' || true)"
  if [[ "$keys" == *"$USABLE_KEY"* ]]; then
    if validate_provider "$name"; then
      reusable="$name"
      break
    fi
    echo "     '$name' exposes $USABLE_KEY but does not match this recipe;" >&2
    echo "     refusing to reuse it. Remove it, or set SLACK_PROVIDER_NAME to" >&2
    echo "     a different name." >&2
    exit 1
  fi
  # A bot-shaped Slack provider attaches cleanly and delivers nothing a cron
  # pre-step can read: Hermes removes `SLACK_BOT_TOKEN` and `SLACK_APP_TOKEN`
  # from the environment of the subprocesses it spawns, so a shell command an
  # agent wrote cannot read them. `providers/slack-user.yaml` carries the
  # command to check that list on your own install.
  if [[ -n "$keys" ]]; then
    echo "     skipping '$name' — its credential key ($keys) is removed from"
    echo "     cron subprocesses, so the collector would never see it"
  fi
done < <(printf '%s\n' "$attached" \
         | sed 's/\x1b\[[0-9;]*m//g' \
         | awk 'NR > 1 && NF { print $1 }')

if [[ -n "$reusable" ]]; then
  echo "     reusing attached provider '$reusable' (type and rotation verified)"
  if [[ "${FORCE_REAUTH:-0}" != "1" ]]; then
    echo ""
    echo "Nothing to do. To replace its credential — after regenerating the"
    echo "app's tokens, or if the refresh chain was broken — re-run with:"
    echo "  FORCE_REAUTH=1 bash scripts/setup-slack.sh"
    exit 0
  fi
  echo "     FORCE_REAUTH=1, so its credential will be replaced"
  PROVIDER="$reusable"
else
  echo "     none attached that exposes $USABLE_KEY"
fi

echo "2/7  Storage encryption"
# Attaching this provider is the moment real message bodies start landing in
# the store, and the prerequisite is that they land on an encrypted volume.
# Owner-only permissions are not that: they stop another account reading the
# file on a running system and do nothing for a disk that is lost, imaged, or
# backed up.
#
# Which volume is the whole question, and it is not one this script can guess.
# `HERMES_HOME` inside a sandbox is an overlay with no block device behind it,
# so encryption is unobservable from in there. On the host it depends on the
# driver: Docker keeps sandbox storage under its data-root, a VM keeps it in a
# disk image, Kubernetes in a volume — none of which is reliably `$HOME`. An
# earlier version inspected `$HOME` and would have approved the wrong volume on
# every one of those.
#
# So the path is asserted rather than inferred. `SANDBOX_STORAGE_PATH` names
# where this sandbox's storage actually lives; the script then verifies *that*
# path, which is a real check rather than a plausible one.
storage_path="${SANDBOX_STORAGE_PATH:-}"
if [[ -z "$storage_path" ]]; then
  echo "     where this sandbox's storage lives is not something this script"
  echo "     can determine — it differs by driver, and guessing would mean"
  echo "     checking the wrong volume."
  echo ""
  echo "Find it, then re-run with it named. For the Docker driver:"
  echo "  docker info --format '{{.DockerRootDir}}'"
  echo ""
  echo "  SANDBOX_STORAGE_PATH=<path> bash scripts/setup-slack.sh"
  echo ""
  echo "docs/encrypted-storage.md explains what to look for and why."
  exit 1
fi
if [[ ! -e "$storage_path" ]]; then
  echo "SANDBOX_STORAGE_PATH does not exist: $storage_path" >&2
  exit 1
fi

encrypted="unknown"
if command -v findmnt >/dev/null 2>&1 && command -v lsblk >/dev/null 2>&1; then
  source_dev="$(findmnt -no SOURCE --target "$storage_path" 2>/dev/null || true)"
  if [[ -n "$source_dev" ]]; then
    if lsblk -no TYPE "$source_dev" 2>/dev/null | grep -q crypt; then
      encrypted="yes"
    else
      encrypted="no"
    fi
  fi
fi

case "$encrypted" in
  yes)
    echo "     $storage_path is on an encrypted volume" ;;
  no)
    echo "     $storage_path does NOT appear to be on an encrypted volume" ;;
  *)
    echo "     could not determine whether $storage_path is encrypted" ;;
esac

if [[ "$encrypted" != "yes" ]]; then
  echo ""
  echo "This recipe stores message subjects, senders and bodies once a"
  echo "connector is attached. See docs/encrypted-storage.md."
  echo ""
  if [[ "${STORE_ENCRYPTION_ACKNOWLEDGED:-0}" == "1" ]]; then
    echo "     STORE_ENCRYPTION_ACKNOWLEDGED=1 — continuing."
  else
    read -r -p "Type 'encrypted' to confirm the prerequisite is met: " ACK
    if [[ "$ACK" != "encrypted" ]]; then
      echo "Not confirmed. Nothing has been configured." >&2
      exit 1
    fi
  fi
fi

echo "3/7  App credentials"
echo ""
echo "Create the app first if you have not: https://api.slack.com/apps"
echo "  -> Create New App -> From a manifest, and paste"
echo "     $RECIPE_ROOT/docs/slack_app_manifest.json"
echo ""
echo "Then take Client ID and Client Secret from Basic Information."
echo ""
read -r -p "Client ID: " CLIENT_ID
[[ -n "$CLIENT_ID" ]] || { echo "Nothing entered." >&2; exit 1; }
if ! read -r -s -p "Client Secret: " CLIENT_SECRET; then
  echo "" >&2
  echo "No input; run this from a terminal." >&2
  exit 1
fi
echo ""

echo "4/7  Authorize"
echo ""
# The manifest requests user scopes and no bot scopes, so the app has no bot
# user and therefore no "Install to Workspace" button — that button installs a
# bot. A user-scopes-only app is authorized by visiting the OAuth URL directly.
echo "Open this, approve, and copy the value of 'code' from the address bar."
echo ""
echo "The page will fail to load — nothing is listening on that port, which is"
echo "the point. Slack sends the authorization code to whatever redirect the"
echo "app declares, so it must be an address only you can reach. A loopback"
echo "URL sends it to your own machine and no further; the browser still shows"
echo "it in the address bar, which is where you copy it from."
echo ""
echo "https://slack.com/oauth/v2/authorize?client_id=${CLIENT_ID}&user_scope=${USER_SCOPES}&redirect_uri=${REDIRECT}"
echo ""
if ! read -r -p "code: " CODE; then
  echo "No input; run this from a terminal." >&2
  exit 1
fi
[[ -n "$CODE" ]] || { echo "Nothing entered." >&2; exit 1; }

echo "5/7  Exchanging the code"
# The refresh token is taken from `authed_user.refresh_token` by name, and from
# nowhere else. An app that also had bot scopes returns a second refresh token
# at the top level belonging to the bot; configuring that one refreshes the
# bot's credential under this user-token key, reports healthy, and produces a
# collector that never sees a direct message. Extracting by name means that
# cannot happen even if the manifest later gains bot scopes.
#
# Secrets travel in the environment rather than argv, where `ps` would show
# them.
if ! EXCHANGED="$(CLIENT_ID="$CLIENT_ID" CLIENT_SECRET="$CLIENT_SECRET" \
    CODE="$CODE" REDIRECT="$REDIRECT" python3 - <<'PY'
import json, os, sys, urllib.parse, urllib.request

body = urllib.parse.urlencode({
    "client_id": os.environ["CLIENT_ID"],
    "client_secret": os.environ["CLIENT_SECRET"],
    "code": os.environ["CODE"],
    "redirect_uri": os.environ["REDIRECT"],
}).encode()
request = urllib.request.Request(
    "https://slack.com/api/oauth.v2.access", data=body,
    headers={"Content-Type": "application/x-www-form-urlencoded"})
try:
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.loads(response.read().decode())
except Exception as exc:  # noqa: BLE001
    print(f"could not reach Slack: {type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1)

if not payload.get("ok"):
    print(f"Slack refused the exchange: {payload.get('error')}", file=sys.stderr)
    raise SystemExit(1)

user = payload.get("authed_user") or {}
access, refresh = user.get("access_token"), user.get("refresh_token")
if not access or not refresh:
    print("The response carried no user credential under authed_user. The app "
          "must request user scopes; check the manifest.", file=sys.stderr)
    raise SystemExit(1)
if not refresh.startswith("xoxe-"):
    print("That credential does not rotate. Enable token rotation on the app "
          "and authorize again — this recipe will not install a token that "
          "never expires.", file=sys.stderr)
    raise SystemExit(1)

print(access)
print(refresh)
print(user.get("id", ""))
PY
)"; then
  echo "Nothing has been configured." >&2
  exit 1
fi
unset CODE

ACCESS_TOKEN="$(printf '%s\n' "$EXCHANGED" | sed -n 1p)"
REFRESH_TOKEN="$(printf '%s\n' "$EXCHANGED" | sed -n 2p)"
SLACK_USER_ID="$(printf '%s\n' "$EXCHANGED" | sed -n 3p)"
unset EXCHANGED
echo "     authorized as ${SLACK_USER_ID:-unknown}"

echo "6/7  Registering the provider"
# The profile carries `endpoints: slack.com` with `access: read-only`, which is
# what scopes the egress substitution and stops the sandbox writing to Slack. A
# provider created without it would get neither.
# Delete-then-import, because import rejects an existing id rather than
# upserting. A profile in use by a live sandbox cannot be deleted, so on a
# re-run the delete is a no-op and the import collides — which is fine, the
# profile is already registered. What is not fine is suppressing both and
# carrying on: that leaves whatever was registered before in force, including
# an older endpoint policy, and the provider is then created against it.
# So the outcome is verified rather than the commands being trusted.
openshell provider profile delete "$PROFILE_ID" >/dev/null 2>&1 || true
import_out="$(openshell provider profile import --file "$PROFILE_YAML" 2>&1 || true)"
if ! registered="$(openshell provider profile export "$PROFILE_ID" 2>&1)"; then
  echo "Provider profile '$PROFILE_ID' is not registered." >&2
  printf '%s\n' "$import_out" >&2
  exit 1
fi
if ! printf '%s' "$registered" | grep -q "host: slack.com"; then
  echo "The registered '$PROFILE_ID' profile does not declare slack.com." >&2
  echo "An older profile is still in force. Delete it and re-run:" >&2
  echo "  openshell provider profile delete $PROFILE_ID" >&2
  exit 1
fi
if ! printf '%s' "$registered" | grep -q "access: read-only"; then
  echo "The registered '$PROFILE_ID' profile is not read-only." >&2
  echo "An older profile is still in force. Delete it and re-run:" >&2
  echo "  openshell provider profile delete $PROFILE_ID" >&2
  exit 1
fi

if openshell provider get "$PROVIDER" >/dev/null 2>&1; then
  if ! SLACK_USER_TOKEN="$ACCESS_TOKEN" openshell provider update "$PROVIDER" \
        --credential "$USABLE_KEY" >/dev/null 2>&1; then
    echo "Could not update provider '$PROVIDER'." >&2
    exit 1
  fi
  echo "     updated provider '$PROVIDER'"
else
  if ! SLACK_USER_TOKEN="$ACCESS_TOKEN" openshell provider create \
        --name "$PROVIDER" --type "$PROFILE_ID" \
        --credential "$USABLE_KEY" >/dev/null 2>&1; then
    echo "Could not create provider '$PROVIDER'." >&2
    exit 1
  fi
  echo "     created provider '$PROVIDER'"
fi
unset ACCESS_TOKEN

if ! SLACK_CLIENT_SECRET="$CLIENT_SECRET" SLACK_REFRESH_TOKEN="$REFRESH_TOKEN" \
    openshell provider refresh configure "$PROVIDER" \
      --credential-key "$USABLE_KEY" \
      --strategy oauth2-refresh-token \
      --material "client_id=$CLIENT_ID" \
      --secret-material-env client_secret=SLACK_CLIENT_SECRET \
      --secret-material-env refresh_token=SLACK_REFRESH_TOKEN >/dev/null 2>&1; then
  echo "Could not configure refresh on '$PROVIDER'." >&2
  echo "The credential is installed but expires in twelve hours and will not" >&2
  echo "renew. Re-run this script." >&2
  exit 1
fi
unset CLIENT_SECRET REFRESH_TOKEN
echo "     refresh configured; the gateway owns renewal from here"

echo "7/7  Attaching to sandbox '$SANDBOX'"
# Attaching works on a sandbox that already exists; it does not have to be
# recreated.
if ! openshell sandbox provider attach "$SANDBOX" "$PROVIDER" >/dev/null 2>&1; then
  echo "Could not attach '$PROVIDER' to sandbox '$SANDBOX'." >&2
  echo "  openshell sandbox provider attach <sandbox> $PROVIDER" >&2
  exit 1
fi

echo ""
echo "Done. Confirm the collector can see it, from inside the sandbox:"
echo "  openshell sandbox exec --name $SANDBOX -- \\"
echo "      python3 <profile home>/scripts/ingest_slack.py --recheck"
echo ""
echo "Renewal state:"
echo "  openshell provider refresh status $PROVIDER --credential-key $USABLE_KEY"
echo ""
echo "To revoke, uninstall the app from your workspace, then:"
echo "  openshell sandbox provider detach $SANDBOX $PROVIDER"
echo "  openshell provider delete $PROVIDER"
