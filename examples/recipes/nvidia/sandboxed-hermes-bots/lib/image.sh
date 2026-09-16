# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Sandbox image with Hermes baked in at $HERMES_REF.

image_tag() { printf 'hermes-bot:%s' "$HERMES_REF"; }

image_present() { docker image inspect "$(image_tag)" >/dev/null 2>&1; }

# image_ensure [--rebuild]
# An image built by an earlier revision of this Dockerfile has OCI USER root,
# which OpenShell 0.0.101+ refuses to start. Rebuild it rather than leaving a
# present-but-unusable image in place.
image_ensure() {
  if image_present && [[ "${1:-}" != "--rebuild" ]]; then
    if [[ "$(docker image inspect "$(image_tag)" --format '{{.Config.User}}')" == "sandbox" ]]; then
      ok "image $(image_tag) present"
      return 0
    fi
    log "image $(image_tag) runs as root; rebuilding for current OpenShell"
  fi
  local logf="$SWARM_STATE/logs/image-build.log"
  log "building $(image_tag) (first build ~5-8 min: installs Hermes and Node)"
  if DOCKER_BUILDKIT=1 docker build --build-arg "HERMES_REF=$HERMES_REF" \
       -t "$(image_tag)" "$SWARM_ROOT/image" > "$logf" 2>&1; then
    ok "image built"
  else
    tail -30 "$logf" >&2
    die "image build failed; full log: $logf"
  fi
  local baked
  baked=$(docker run --rm --entrypoint /bin/sh "$(image_tag)" -c \
            '/sandbox/.hermes/hermes-agent/venv/bin/python -m hermes_cli.main --version 2>/dev/null | head -1')
  dim "baked: $baked"
}
