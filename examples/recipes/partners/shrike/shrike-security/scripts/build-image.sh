#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-FileCopyrightText: Copyright (c) 2026, Shrike Security, Inc. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# INSTALL_MODE=image only. Bake the Shrike governance plugin into a
# version-matched custom sandbox image and onboard from it, so the plugin
# survives `nemoclaw <sb> rebuild` and warm recreation (provenance-guarded on
# NemoClaw >= v0.0.76). This is the durable install path.
#
# It follows the documented custom-image contract:
#   docs/deployment/install-openclaw-plugins.mdx  (nemoclaw onboard --from)
# The runtime path (scripts/install.sh) is the lighter, tested default; use
# this when you need rebuild-durable governance baked into the image.
#
# Because our plugin imports nothing from `openclaw` (structural types), it
# carries no `openclaw` dependency and no node_modules — so the appended stages
# below OMIT the doc's `node_modules/openclaw` symlink assertions, which only
# apply to plugins that import the runtime. Everything else matches the doc.
#
# Requirements:
#   - A NemoClaw source checkout that EXACTLY matches the installed CLI, as the
#     Docker build context. Point NEMOCLAW_SOURCE_DIR at it, or let this script
#     clone the matching release tag from GitHub.
#   - Docker reachable by the OpenShell gateway.
#
# This script never mutates NEMOCLAW_SOURCE_DIR: it copies the checkout into a
# gitignored work dir and patches the copy.

set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$DIR/_lib.sh"

command -v nemoclaw >/dev/null || { echo "nemoclaw not in PATH" >&2; exit 1; }
command -v git      >/dev/null || { echo "git not in PATH" >&2; exit 1; }
load_dependencies
require_nemoclaw_contract

# 1) Use the validated example contract for the source tag and base image.
NEMOCLAW_VERSION="$NEMOCLAW_INSTALL_TAG"
BASE_IMAGE_REF="${NEMOCLAW_SANDBOX_BASE_IMAGE_REF:-ghcr.io/nvidia/nemoclaw/sandbox-base:${NEMOCLAW_VERSION}}"
echo "NemoClaw $NEMOCLAW_VERSION — baking plugin against base image $BASE_IMAGE_REF"

# 2) Build the plugin's dist/ on the host (the Docker build re-builds it too,
#    but building here fails fast on a source error before the slow image build).
build_plugin

# 3) Establish the build context (a copy — never the pristine checkout).
WORK_DIR="${SHRIKE_IMAGE_WORKDIR:-$EXAMPLE_DIR/.image-build/nemoclaw-$NEMOCLAW_VERSION}"
echo "Build context: $WORK_DIR"
rm -rf "$WORK_DIR"
mkdir -p "$(dirname "$WORK_DIR")"

if [[ -n "${NEMOCLAW_SOURCE_DIR:-}" ]]; then
  [[ -f "$NEMOCLAW_SOURCE_DIR/Dockerfile" ]] || {
    echo "NEMOCLAW_SOURCE_DIR='$NEMOCLAW_SOURCE_DIR' has no Dockerfile at its root" >&2; exit 1; }
  echo "Copying matched source from NEMOCLAW_SOURCE_DIR"
  # Copy the whole checkout (the full managed image copies repo scripts +
  # blueprint files); honor the checkout's .dockerignore during the build.
  cp -R "$NEMOCLAW_SOURCE_DIR" "$WORK_DIR"
else
  REPO_URL="${NEMOCLAW_REPO_URL:-https://github.com/NVIDIA/NemoClaw.git}"
  echo "Cloning $REPO_URL @ $NEMOCLAW_VERSION (set NEMOCLAW_SOURCE_DIR to skip)"
  git clone --depth 1 --branch "$NEMOCLAW_VERSION" "$REPO_URL" "$WORK_DIR"
fi

ACTUAL_NEMOCLAW_COMMIT="$(git -C "$WORK_DIR" rev-parse HEAD)"
[[ "$ACTUAL_NEMOCLAW_COMMIT" == "$NEMOCLAW_INSTALL_REF" ]] || {
  echo "NemoClaw $NEMOCLAW_VERSION resolved to unexpected commit $ACTUAL_NEMOCLAW_COMMIT" >&2
  exit 1
}

CONTEXT_DOCKERFILE="$WORK_DIR/Dockerfile"
[[ -f "$CONTEXT_DOCKERFILE" ]] || { echo "no Dockerfile in build context $WORK_DIR" >&2; exit 1; }

# 4) Copy the plugin's build inputs into the context.
PLUGIN_STAGE_IN_CTX="$WORK_DIR/shrike-plugin"
rm -rf "$PLUGIN_STAGE_IN_CTX"
mkdir -p "$PLUGIN_STAGE_IN_CTX/src"
cp "$PLUGIN_DIR/package.json"         "$PLUGIN_STAGE_IN_CTX/"
cp "$PLUGIN_DIR/package-lock.json"    "$PLUGIN_STAGE_IN_CTX/"
cp "$PLUGIN_DIR/tsconfig.json"        "$PLUGIN_STAGE_IN_CTX/"
cp "$PLUGIN_DIR/openclaw.plugin.json" "$PLUGIN_STAGE_IN_CTX/"
cp -R "$PLUGIN_DIR/src/." "$PLUGIN_STAGE_IN_CTX/src/"

# 5) Patch the Dockerfile: pin the base image + name the final runtime stage.
#    Verify each edit landed — if the stock shape differs across releases, fail
#    loud rather than build a subtly wrong image.
patch_line() {
  local pattern="$1" replacement="$2" desc="$3"
  grep -qE "$pattern" "$CONTEXT_DOCKERFILE" || {
    echo "error: expected to find '$desc' in the stock Dockerfile but did not." >&2
    echo "       The custom-image contract may have changed for $NEMOCLAW_VERSION;" >&2
    echo "       reconcile scripts/build-image.sh with the current Dockerfile." >&2
    exit 1
  }
  # Portable in-place sed (GNU + BSD).
  sed -i.bak -E "s|$pattern|$replacement|" "$CONTEXT_DOCKERFILE" && rm -f "$CONTEXT_DOCKERFILE.bak"
}
patch_line \
  '^ARG BASE_IMAGE=ghcr.io/nvidia/nemoclaw/sandbox-base:latest' \
  "ARG BASE_IMAGE=${BASE_IMAGE_REF}" \
  'ARG BASE_IMAGE=...:latest'
patch_line \
  '^FROM \$\{BASE_IMAGE\}$' \
  'FROM ${BASE_IMAGE} AS nemoclaw-runtime' \
  'FROM ${BASE_IMAGE} (final runtime stage)'

# 6) Append the plugin build + extend stages (idempotent — guard on a marker).
MARKER="# >>> shrike-security plugin stages"
if ! grep -qF "$MARKER" "$CONTEXT_DOCKERFILE"; then
  cat >>"$CONTEXT_DOCKERFILE" <<'DOCKERFILE'

# >>> shrike-security plugin stages (appended by scripts/build-image.sh)
# Build the plugin from its lockfile in an isolated stage.
FROM builder AS shrike-plugin-builder
WORKDIR /opt/shrike-plugin
COPY shrike-plugin/package.json shrike-plugin/package-lock.json shrike-plugin/tsconfig.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY shrike-plugin/openclaw.plugin.json ./
COPY shrike-plugin/src/ ./src/
RUN npm run build \
    && npm prune --omit=dev --ignore-scripts --no-audit --no-fund

# Extend the completed managed runtime with the plugin. No openclaw symlink
# assertion: this plugin imports nothing from the runtime and carries no
# node_modules, so the doc's link check does not apply.
FROM nemoclaw-runtime AS shrike-runtime
ARG NEMOCLAW_TOOL_DISCLOSURE=progressive
ENV NEMOCLAW_TOOL_DISCLOSURE=${NEMOCLAW_TOOL_DISCLOSURE}
# Stage the plugin OUTSIDE the managed extensions dir, then install FROM there.
COPY --from=shrike-plugin-builder --chown=sandbox:sandbox \
    /opt/shrike-plugin/package.json \
    /opt/shrike-plugin/openclaw.plugin.json \
    /opt/shrike-plugin-stage/
COPY --from=shrike-plugin-builder --chown=sandbox:sandbox \
    /opt/shrike-plugin/dist/ /opt/shrike-plugin-stage/dist/
USER sandbox
RUN HOME=/sandbox openclaw plugins install /opt/shrike-plugin-stage \
    && HOME=/sandbox openclaw plugins enable shrike-security \
    && HOME=/sandbox openclaw plugins inspect shrike-security --json > /dev/null

# Enabling the plugin changes openclaw.json after the managed runtime hashed it.
# Regenerate the integrity hash from INSIDE /sandbox/.openclaw so the entry in
# .config-hash names the file as `openclaw.json` (a bare, relative filename),
# matching what NemoClaw's config-integrity guard expects. Hashing the absolute
# path (`sha256sum /sandbox/.openclaw/openclaw.json`) records `.../openclaw.json`
# in the entry and trips the guard on re-bless.
# hadolint ignore=DL3002
USER root
RUN chown sandbox:sandbox /sandbox/.openclaw/openclaw.json \
    && chmod 660 /sandbox/.openclaw/openclaw.json \
    && ( cd /sandbox/.openclaw && sha256sum openclaw.json > .config-hash ) \
    && chown sandbox:sandbox /sandbox/.openclaw/.config-hash \
    && chmod 660 /sandbox/.openclaw/.config-hash
# <<< shrike-security plugin stages
DOCKERFILE
  echo "Appended shrike-security plugin stages to the Dockerfile."
else
  echo "Plugin stages already present in the Dockerfile — reusing."
fi

# 7) Onboard from the custom image. Pin the base-image resolver to the same
#    release so warm rebuilds resolve the same cached base.
echo "Onboarding sandbox '$NEMOCLAW_SANDBOX_NAME' from the baked image"
export NEMOCLAW_NON_INTERACTIVE=1
export NEMOCLAW_ACCEPT_THIRD_PARTY_SOFTWARE=1
export NEMOCLAW_SANDBOX_NAME
export NEMOCLAW_SANDBOX_BASE_IMAGE_REF="$BASE_IMAGE_REF"
run nemoclaw onboard \
  --non-interactive \
  --name "$NEMOCLAW_SANDBOX_NAME" \
  --agents "$EXAMPLE_DIR/agents.yaml" \
  --from "$CONTEXT_DOCKERFILE"

echo
echo "Image onboard complete. Keep the build context at:"
echo "  $WORK_DIR"
echo "so 'nemoclaw $NEMOCLAW_SANDBOX_NAME rebuild --yes' can reproduce the plugin."
