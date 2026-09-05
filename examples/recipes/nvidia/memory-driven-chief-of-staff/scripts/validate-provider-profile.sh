#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Validate a registered provider profile, field by field.
#
# One file for every connector rather than one per connector. A second copy of
# a check like this is a copy that drifts: the one nobody edited keeps passing
# a profile the other would refuse, and the difference surfaces as a boundary
# that was narrower in one setup flow than the other.
#
# Its own file because two paths need it — reusing an attached provider and
# creating a fresh one — and because the setup script cannot be driven this
# far in a test: step 5 exchanges an authorization code against Slack, so a
# run that reaches the profile check has already talked to a live service.
# Sourced by `setup-slack.sh`; invoked directly by the tests and by anybody
# who wants to check what is registered:
#
#     WANT_HOST=slack.com USABLE_KEY=SLACK_USER_TOKEN \
#         bash scripts/validate-provider-profile.sh <id>

# The registered profile, checked field by field rather than by looking for
# strings anywhere in a rendered blob.
#
# The previous version grepped for `host: slack.com` and `access: read-only`
# independently. Those can belong to different endpoints — a profile with a
# read-only entry for one host and a read-write entry for slack.com passes
# both greps — and enforcement was not checked at all, so a profile in
# `observe` mode read as enforced. This exports the profile as JSON and
# validates the exact endpoint: the host, the port, the access level, the
# enforcement mode, and that the credential this recipe uses is the one the
# profile declares.
validate_profile() {
  local id="$1" exported
  if ! exported="$(openshell provider profile export "$id" -o json 2>&1)"; then
    echo "     could not export provider profile '$id'" >&2
    return 1
  fi
  PROFILE_JSON="$exported" USABLE_KEY="$USABLE_KEY" \
  WANT_HOST="$WANT_HOST" WANT_PORT="${WANT_PORT:-443}" \
  python3 - <<'PYCHECK'
import json, os, sys

want_host = os.environ["WANT_HOST"]
want_port = int(os.environ.get("WANT_PORT", "443"))
try:
    profile = json.loads(os.environ["PROFILE_JSON"])
except json.JSONDecodeError as exc:
    sys.exit(f"     provider profile is not valid JSON: {exc}")

endpoints = profile.get("endpoints") or []
matching = [e for e in endpoints
            if e.get("host") == want_host and int(e.get("port", 0)) == want_port]
if not matching:
    hosts = ", ".join(sorted({str(e.get("host")) for e in endpoints})) or "none"
    sys.exit(f"     profile declares no {want_host}:{want_port} endpoint "
             f"(found: {hosts})")
if len(matching) > 1:
    sys.exit(f"     profile declares {len(matching)} {want_host} endpoints; "
             "exactly one is expected")

endpoint = matching[0]
if endpoint.get("access") != "read-only":
    sys.exit(f"     {want_host} is declared {endpoint.get('access')!r}, not "
             "read-only. This recipe never writes to Slack and the boundary "
             "is what enforces that.")
if endpoint.get("enforcement") != "enforce":
    sys.exit(f"     {want_host} enforcement is {endpoint.get('enforcement')!r}, "
             "not 'enforce'. Anything else observes rather than refuses.")

# Anything the profile allows beyond that one endpoint widens the boundary
# without saying so.
extra = [e for e in endpoints if e is not endpoint]
if extra:
    hosts = ", ".join(sorted({str(e.get("host")) for e in extra}))
    sys.exit(f"     profile allows more than {want_host}: {hosts}")

key = os.environ["USABLE_KEY"]
declared = {v for c in (profile.get("credentials") or [])
            for v in (c.get("env_vars") or [])}
if key not in declared:
    sys.exit(f"     profile does not declare {key} "
             f"(declares: {', '.join(sorted(declared)) or 'nothing'})")

if not (profile.get("binaries") or []):
    sys.exit("     profile declares no binary allow-list, so any process in "
             "the sandbox could spend the credential")
PYCHECK
}

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  : "${WANT_HOST:?WANT_HOST is required}"
  : "${USABLE_KEY:?USABLE_KEY is required}"
  validate_profile "$1"
fi
