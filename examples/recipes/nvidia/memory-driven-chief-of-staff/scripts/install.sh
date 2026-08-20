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
# `hermes config set`; the credential is not, because a credential is not a
# thing to copy. It is also not inherited, so the target profile needs its own
# and this script refuses to register jobs until it has one.

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
# What the three settings do not carry is a credential, and nothing else
# supplies one either — see the check below.
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

# A model name is not enough to make a profile runnable. The credential is not
# inherited: a profile carrying only the three settings above sends the literal
# placeholder `no-key-required` in its Authorization header, not the key from
# the config it was installed alongside. Measured on Hermes 0.20.0 by pointing
# a scratch profile at a local endpoint and reading what arrived — the token was
# 15 bytes of placeholder while the configured key was 26 bytes, and the two
# hashes differ. Against a real endpoint that is a failed request per job, four
# times an hour, discoverable only in the logs.
#
# So require the credential here, where a person is watching, rather than at
# 03:00 on the first scheduled run. Endpoints that genuinely need no key are
# real, so there is an opt-out, but it has to be asked for.
credential="$(hermes -p "$PROFILE" config get model.api_key 2>/dev/null | head -1 || true)"
if [[ -z "$credential" || "$credential" == *"not set"* ]]; then
  if [[ "${ALLOW_NO_API_KEY:-0}" != "1" ]]; then
    echo "" >&2
    echo "Profile '$PROFILE' has no model credential of its own." >&2
    echo "" >&2
    echo "Credentials are deliberately not copied, and they are not inherited:" >&2
    echo "a profile without one sends 'no-key-required' rather than the key" >&2
    echo "belonging to the profile it was installed alongside. Every scheduled" >&2
    echo "job would fail to authenticate." >&2
    echo "" >&2
    echo "Set one, then re-run this script:" >&2
    echo "  hermes -p $PROFILE config set model.api_key <key>" >&2
    echo "" >&2
    echo "If your endpoint needs no key, say so explicitly:" >&2
    echo "  ALLOW_NO_API_KEY=1 bash scripts/install.sh" >&2
    exit 1
  fi
  echo "     no credential set; continuing because ALLOW_NO_API_KEY=1"
else
  echo "     model.api_key is set on this profile"
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
