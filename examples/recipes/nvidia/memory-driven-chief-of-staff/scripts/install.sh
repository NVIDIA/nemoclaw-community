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
# No file is copied. The model settings are carried over key by key through
# `hermes config set`, and no credential is: a profile with no `model.api_key`
# of its own still authenticates, because Hermes resolves the credential from
# the config it inherits. The installer stops before registering jobs if the
# profile cannot resolve a model.

set -euo pipefail

# The scheduled path is Linux only. Every shipped skill declares
# `platforms: [linux]`, and Hermes refuses to load a skill outside its declared
# platforms — so on macOS the jobs fire, the model is called, and no skill
# loads. Registering them there buys a scheduled expense and no assistant.
# Refuse before anything is installed or registered rather than after.
require_linux() {
  local kernel
  kernel="$(uname -s)"
  if [[ "$kernel" != "Linux" ]]; then
    echo "This installs a scheduled path that only works on Linux." >&2
    echo "  detected: $kernel" >&2
    echo "" >&2
    echo "Every shipped skill declares 'platforms: [linux]'. On $kernel the" >&2
    echo "jobs would fire and the model would be called with no skill loaded." >&2
    echo "Windows Subsystem for Linux reports Linux and is supported." >&2
    echo "" >&2
    echo "The fixture path needs none of this and runs anywhere:" >&2
    echo "  python3 profile/scripts/walkthrough.py --fixtures fixtures" >&2
    exit 1
  fi
}
require_linux

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RECIPE_ROOT="$(dirname "$HERE")"
PROFILE="${PROFILE_NAME:-memory-driven-chief-of-staff}"

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

echo "2/3  Carrying over the model settings"

# Named settings through the CLI, never a copy of the file.
#
# Copying `config.yaml` wholesale duplicated a credential for no benefit. The
# `model:` block is documented to hold an inline `api_key`, and a generated
# config really does put one there — on the NemoClaw runtime this recipe was
# checked against, `model:` carries `default`, `provider`, `base_url` and
# `api_key` together. A wholesale copy writes that key into a second file.
#
# Carrying nothing but the three settings loses nothing: a profile whose own
# `model.api_key` is unset still sends an authenticated request, because the
# credential resolves from the config the profile inherits. Verified on Hermes
# 0.19.0 by reading the request dump of a cron-driven turn — `model.api_key`
# unset on the profile, `Authorization` present on the wire.
for key in model.default model.provider model.base_url; do
  value="$(hermes config get "$key" 2>/dev/null | head -1 || true)"
  [[ -z "$value" || "$value" == *"not set"* ]] && continue
  hermes -p "$PROFILE" config set "$key" "$value" >/dev/null 2>&1 \
    && echo "     $key = $value"
done

# A profile that cannot resolve a model is not runnable, and registering jobs
# on it schedules failures. Stop here instead, while nothing is scheduled yet.
resolved="$(hermes -p "$PROFILE" config get model.default 2>/dev/null | head -1 || true)"
if [[ -z "$resolved" || "$resolved" == *"not set"* ]]; then
  echo "" >&2
  echo "No model is set on profile '$PROFILE', so its jobs would fail." >&2
  echo "Set one, then re-run this script:" >&2
  echo "  hermes -p $PROFILE config set model.default <model>" >&2
  exit 1
fi

echo "     credentials are not copied. Hermes keeps them in .env and auth.json,"
echo "     and this profile needs its own. Check with:"
echo "       hermes -p $PROFILE info"

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
