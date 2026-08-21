#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Give the intake collector a Slack credential, reusing whatever is already
# there.
#
# A machine that has run another NemoClaw recipe often already has a Slack
# provider attached to its sandbox. Creating a second one would mean a second
# app, a second token, and two things to rotate — so this script looks first
# and only creates when it finds nothing usable.
#
# What it will not reuse is a provider whose credential key is one of the names
# Hermes strips from every subprocess it spawns. `SLACK_BOT_TOKEN` and
# `SLACK_APP_TOKEN` are on that list, so a bot-shaped Slack provider attaches
# cleanly and delivers nothing a cron pre-step can read. That is a silent
# failure, and the whole point of looking is to not walk into it.

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
USABLE_KEY="SLACK_USER_TOKEN"

# This script runs on the HOST, not inside the sandbox — unlike install.sh.
#
# The two CLIs live in different places and neither can see the other's: a
# NemoClaw sandbox has `hermes` and no `openshell`, and the host has
# `openshell` and no `hermes`. Running this where install.sh belongs finds no
# `openshell`, and a naive fallback would quietly write the token into the
# profile's .env — abandoning the gateway-held credential the user asked for,
# with no error and no sign anything was skipped.
#
# `OPENSHELL_SANDBOX` is set inside a sandbox and unset on the host, which is
# what tells the two situations apart from the identical symptom.
if ! command -v openshell >/dev/null 2>&1; then
  if [[ -n "${OPENSHELL_SANDBOX:-}" ]]; then
    echo "This is running inside the sandbox, where openshell is not." >&2
    echo "" >&2
    echo "Unlike install.sh, this step belongs on the host. From there:" >&2
    echo "  cd <this recipe> && bash scripts/setup-slack.sh" >&2
    echo "" >&2
    echo "The credential is held by the OpenShell gateway and substituted at" >&2
    echo "egress, so it is configured from outside the sandbox by design." >&2
    exit 1
  fi
  echo "openshell is not on PATH, and this is not a NemoClaw sandbox." >&2
  echo "" >&2
  echo "On a plain Hermes install, put the token in the profile's .env:" >&2
  echo "  SLACK_USER_TOKEN=xoxp-..." >&2
  echo "See docs/set-up-slack.md." >&2
  exit 1
fi

echo "1/3  Looking for a Slack credential this sandbox can already read"

attached="$(openshell sandbox provider list "$SANDBOX" 2>/dev/null || true)"
reusable=""
while read -r name; do
  [[ -z "$name" ]] && continue
  keys="$(openshell provider get "$name" 2>/dev/null \
    | sed -n 's/.*Credential keys:[[:space:]]*//p' || true)"
  if [[ "$keys" == *"$USABLE_KEY"* ]]; then
    reusable="$name"
    break
  fi
  if [[ -n "$keys" ]]; then
    echo "     skipping '$name' — its credential key ($keys) is stripped"
    echo "     from cron subprocesses, so the collector would never see it"
  fi
done < <(printf '%s\n' "$attached" | sed -n 's/^[[:space:]]*_provider_//p' | tr '_' '-')

if [[ -n "$reusable" ]]; then
  echo "     reusing attached provider '$reusable'"
  echo ""
  echo "Nothing to do. Verify with:"
  echo "  python3 profile/scripts/ingest_slack.py --recheck"
  exit 0
fi

echo "     none attached that exposes $USABLE_KEY"

echo "2/3  Creating one"
echo ""
echo "This needs a Slack User OAuth Token (xoxp-). If you do not have one:"
echo "  1. Create an app from $RECIPE_ROOT/docs/slack_app_manifest.json"
echo "     at https://api.slack.com/apps -> Create New App -> From a manifest"
echo "  2. Install it to your workspace"
echo "  3. Copy the *User* OAuth Token from OAuth & Permissions — it starts"
echo "     with xoxp-, and sits above the bot token on that page"
echo ""
echo "Full walkthrough: docs/set-up-slack.md"
echo ""

# Read it without echoing it, and without it landing in shell history.
read -r -s -p "Paste the User OAuth Token (xoxp-...): " TOKEN
echo ""

case "$TOKEN" in
  xoxp-*) ;;
  xoxb-*)
    echo "That is a bot token. A bot cannot read your direct messages." >&2
    echo "Copy the User OAuth Token instead." >&2
    exit 1 ;;
  xoxe.xoxp-*)
    echo "That is a rotating user token. This recipe supports static ones" >&2
    echo "only; create the app from the bundled manifest, which turns" >&2
    echo "token rotation off." >&2
    exit 1 ;;
  "")
    echo "Nothing pasted." >&2
    exit 1 ;;
  *)
    echo "That does not look like a Slack User OAuth Token (expected xoxp-)." >&2
    exit 1 ;;
esac

if openshell provider get "$PROVIDER" >/dev/null 2>&1; then
  openshell provider update "$PROVIDER" --credential "$USABLE_KEY=$TOKEN" >/dev/null
  echo "     updated provider '$PROVIDER'"
else
  openshell provider create --name "$PROVIDER" --type generic \
    --credential "$USABLE_KEY=$TOKEN" >/dev/null
  echo "     created provider '$PROVIDER'"
fi
unset TOKEN

echo "3/3  Attaching it to sandbox '$SANDBOX'"
# Attaching an existing sandbox works; it does not have to be recreated. The
# credential reaches the sandbox as an `openshell:resolve:` placeholder and the
# egress proxy substitutes the real value on the way to slack.com, so the
# collector never holds anything it could leak.
if ! openshell sandbox provider attach "$SANDBOX" "$PROVIDER" >/dev/null 2>&1; then
  echo "" >&2
  echo "Could not attach '$PROVIDER' to sandbox '$SANDBOX'." >&2
  echo "Check the sandbox name with: openshell sandbox list" >&2
  echo "Then: openshell sandbox provider attach <sandbox> $PROVIDER" >&2
  exit 1
fi

echo ""
echo "Done. Confirm the collector can see it:"
echo "  python3 profile/scripts/ingest_slack.py --recheck"
echo ""
echo "If slack.com is blocked by this sandbox's egress policy, that command"
echo "reports it. Allow it with:"
echo "  nemohermes $SANDBOX policy add <preset>"
