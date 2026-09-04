# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Per-bot extras: anything beyond model + soul + mesh that one bot needs and
# the others do not. Everything here keys off the bot name and is a no-op when
# the matching file or directory is absent, so the default two bots pay nothing.
#
#   souls/<bot>.md        or examples/souls/<bot>.md        the role (bot_soul_file)
#   policies/<bot>.yaml   or examples/policies/<bot>.yaml   extra egress (bot_policy_extras, lib/bot.sh)
#   plugins/<bot>/        or examples/plugins/<bot>/        a Hermes plugin dir, installed and enabled
#   skills/<bot>/         or examples/skills/<bot>/         a Hermes skill dir (SKILL.md), installed
#   bot_env_extras        env lines this bot's sandbox .env gets (VSS_* for nemoclaw-vss)
#   bot_files_extras      files copied into the sandbox (VSS_VIDEOS_DIR -> /sandbox/videos)
#
# Plugin and skill directories are matched by the bot's short name (the part
# after "nemoclaw-"), so examples/plugins/vss serves nemoclaw-vss.

# First existing path among the candidates, or nothing.
_first_existing() { local p; for p in "$@"; do [[ -e "$p" ]] && { printf '%s' "$p"; return 0; }; done; return 1; }

bot_short() { printf '%s' "${1#nemoclaw-}"; }

bot_soul_file() {
  _first_existing "$SWARM_ROOT/souls/$1.md" "$SWARM_ROOT/examples/souls/$1.md" \
    || die "no souls/$1.md or examples/souls/$1.md; pass --soul FILE or --role \"text\""
}

bot_policy_file() {
  _first_existing "$SWARM_ROOT/policies/$1.yaml" "$SWARM_ROOT/examples/policies/$1.yaml" || true
}

_bot_plugin_dir() {
  local s; s=$(bot_short "$1")
  _first_existing "$SWARM_ROOT/plugins/$s" "$SWARM_ROOT/examples/plugins/$s" || true
}

_bot_skill_dir() {
  local s; s=$(bot_short "$1")
  _first_existing "$SWARM_ROOT/skills/$s" "$SWARM_ROOT/examples/skills/$s-video" "$SWARM_ROOT/examples/skills/$s" || true
}

# Install a directory into the sandbox as one tarball (per-file writes are
# capped near 32KB of argument; a tarball is one write).
_bot_install_dir() {
  local sb="$1" src="$2" dest_parent="$3" tgz b64 name
  name=$(basename "$src")
  tgz=$(mktemp /tmp/bot-dir.XXXXXX.tgz)
  tar czf "$tgz" -C "$(dirname "$src")" --exclude=__pycache__ --exclude='._*' "$name"
  b64=$(b64 "$tgz"); rm -f "$tgz"
  sbx "$sb" "mkdir -p $dest_parent && printf '%s' '$b64' | base64 -d | tar xzf - -C $dest_parent && echo DIR-OK" 180 \
    | grep -q DIR-OK || die "installing $name into $sb:$dest_parent failed"
}

# Plugin + skill for this bot, if any. Idempotent.
bot_install_extras() {
  local name="$1" sb pdir sdir pname
  sb=$(sandbox_of "$name")
  pdir=$(_bot_plugin_dir "$name")
  if [[ -n "$pdir" ]]; then
    pname=$(basename "$pdir")
    _bot_install_dir "$sb" "$pdir" /sandbox/.hermes/plugins
    sbx "$sb" "\$H -m hermes_cli.main plugins enable $pname >/dev/null 2>&1 || true; echo ENABLED" 120 >/dev/null
    ok "plugin $pname installed"
  fi
  sdir=$(_bot_skill_dir "$name")
  if [[ -n "$sdir" ]]; then
    _bot_install_dir "$sb" "$sdir" /sandbox/.hermes/skills
    ok "skill $(basename "$sdir") installed"
  fi
  bot_env_extras "$name"
  bot_files_extras "$name"
  bot_toolset_extras "$name"
}

# A bot whose model sees natively has no use for the vision_analyze tool: the
# picture is already in its context, and the tool only takes a path or URL.
# Left on, the model reads "[Image attached at: /tmp/x.jpg]" in the message
# text (a hint Hermes adds on the sender's side) and calls the tool on that
# path, which does not exist in this sandbox, instead of looking at the image
# it was given. Turn the toolset off for vision bots.
bot_toolset_extras() {
  local name="$1" sb
  [[ "$(bot_vision "$name")" == true ]] || return 0
  sb=$(sandbox_of "$name")
  # `config set` accepts a bare toolset name here and stores the list form.
  sbx "$sb" '$H -m hermes_cli.main config set agent.disabled_toolsets vision >/dev/null 2>&1 && echo TS-OK' 120 \
    | grep -q TS-OK || die "could not disable the vision toolset in $sb"
  ok "vision_analyze disabled (model sees natively)"
}

# Extra .env lines for one bot. Only nemoclaw-vss has any today.
bot_env_extras() {
  local name="$1" sb
  [[ "$(bot_short "$name")" == vss ]] || return 0
  sb=$(sandbox_of "$name")
  local url="${VSS_BASE_URL:-}" model="${VSS_MODEL:-}"
  [[ -n "$url" ]] || { warn "nemoclaw-vss: VSS_BASE_URL is not set in swarm.env; its video tools will report that"; return 0; }
  sbx "$sb" "sed -i '/^VSS_BASE_URL=/d; /^VSS_MODEL=/d' /sandbox/.hermes/.env
printf 'VSS_BASE_URL=%s\nVSS_MODEL=%s\n' '$url' '$model' >> /sandbox/.hermes/.env; echo ENV-OK" 60 | grep -q ENV-OK \
    || die "writing VSS env into $sb failed"
  ok "VSS_BASE_URL=$url"
}

# Files for one bot. nemoclaw-vss gets the clips from VSS_VIDEOS_DIR.
# `openshell sandbox upload DIR DEST` lands DIR *inside* DEST by basename, so
# stage the clips in a directory literally named "videos" and upload that to
# /sandbox. Seconds, versus minutes for base64 through exec.
bot_files_extras() {
  local name="$1" sb dir stage n
  [[ "$(bot_short "$name")" == vss ]] || return 0
  dir="${VSS_VIDEOS_DIR:-$SWARM_ROOT/examples/videos}"
  [[ -d "$dir" ]] || { warn "VSS_VIDEOS_DIR=$dir does not exist"; return 0; }
  sb=$(sandbox_of "$name")
  stage=$(mktemp -d /tmp/swarm-videos.XXXXXX); mkdir -p "$stage/videos"
  n=0
  for f in "$dir"/*.mp4 "$dir"/*.webm "$dir"/*.mov; do
    [[ -f "$f" ]] && { cp "$f" "$stage/videos/"; n=$((n+1)); }
  done
  if (( n > 0 )); then
    timeout 300 openshell sandbox upload --no-git-ignore "$sb" "$stage/videos" /sandbox >/dev/null 2>&1 \
      || { rm -rf "$stage"; die "uploading clips into $sb failed"; }
  fi
  rm -rf "$stage"
  ok "$n clip(s) in /sandbox/videos"
}
