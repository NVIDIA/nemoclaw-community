#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Stage the profile into a Hermes runtime and make it runnable.
#
# Three steps. The second is the one a reader skips: a freshly
# installed profile has no model configuration, so every agent-backed job fails
# on its first tick with "no model configured". The runtime already knows which
# model to use, so the profile inherits that rather than the recipe asking the
# reader to configure it twice.
#
# Only config.yaml is copied, never `.env`. Hermes keeps secrets in `.env` and
# routes them there itself, so inference reaches the provider through the
# runtime's own egress path and this profile never needs to hold a key.
# Verified on Hermes 0.19.0 — copying config.yaml alone is enough for scheduled
# jobs to run.
#
# What this cannot promise: `config.yaml` is the user's file, and two of its
# documented keys hold secrets if someone has set them there — `api_key`, which
# Hermes's own example offers as an alternative to `.env`, and `sudo_password`,
# which it marks as plaintext. The copy is wholesale, so anything there travels
# to the new profile. Read yours before running this if that matters to you.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE_ROOT="$(dirname "$HERE")"
PROFILE="${PROFILE_NAME:-memory-driven-chief-of-staff}"
SOURCE_PROFILE_CONFIG="${SOURCE_PROFILE_CONFIG:-$HOME/.hermes/config.yaml}"

command -v hermes >/dev/null 2>&1 || {
  echo "hermes is not on PATH." >&2
  exit 1
}

echo "1/3  Installing the profile distribution"
hermes profile install "$RECIPE_ROOT/profile" --name "$PROFILE" --force --yes

# `|| true` matters: `hermes profile show` exits 1 for a profile that does not
# exist, and under `set -e` the assignment would abort the script before the
# check below could explain why.
PROFILE_HOME="$(hermes profile show "$PROFILE" 2>/dev/null \
  | sed -n 's/^Path:[[:space:]]*//p' || true)"
if [[ -z "$PROFILE_HOME" ]]; then
  echo "Could not resolve the profile home for '$PROFILE'." >&2
  exit 1
fi

echo "2/3  Inheriting the runtime's model configuration"
if [[ -f "$SOURCE_PROFILE_CONFIG" ]]; then
  cp "$SOURCE_PROFILE_CONFIG" "$PROFILE_HOME/config.yaml"
  echo "     copied from $SOURCE_PROFILE_CONFIG (no credential file is copied)"
else
  echo "     no config at $SOURCE_PROFILE_CONFIG — set a model with:" >&2
  echo "       hermes -p $PROFILE config set model <name>" >&2
fi

echo "3/3  Registering scheduled jobs"
PROFILE_NAME="$PROFILE" bash "$HERE/register-jobs.sh"

cat <<EOF

Installed '$PROFILE' at $PROFILE_HOME

The store and memory live under \$PROFILE_HOME/workspace, which a profile
update leaves alone.

To load the fixture corpus instead of connecting a real account:
  HERMES_HOME="$PROFILE_HOME" python3 "$RECIPE_ROOT/profile/scripts/load_fixtures.py" --fixtures "$RECIPE_ROOT/fixtures"

Jobs fire only while a gateway is serving this profile. Check with:
  hermes -p $PROFILE cron list
EOF
