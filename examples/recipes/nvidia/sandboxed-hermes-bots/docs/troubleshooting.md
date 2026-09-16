# Troubleshooting

By symptom, in the order that finds the cause fastest. Every entry here is
something that broke while we built this, with the real error text. I'd rather
you read a slightly blunt list than rediscover any of it.

## Start here: is a bot really down?

Most "bot X is down" reports turn out not to be about the bot. Go in this order
and stop at the first thing that fails.

**1. Is the Desktop app running?** On your laptop:

```bash
pgrep -f "Hermes.app/Contents/MacOS/Hermes" >/dev/null && echo RUNNING || echo DOWN
```

If it says DOWN, nothing on the host matters yet. Relaunch it and stop here.
Several bots erroring at once with no error text is almost always the client
having quit on you.

**2. Does the bot answer a direct turn?** On the host:

```bash
hermes -p nemoclaw-researcher chat -q "Reply with exactly OK"
```

A reply means the bot is fine and the fault is on the Desktop side. Skip to 5.

**3. Is the model endpoint up?**

```bash
./swarm doctor      # auth 200? model listed?
```

Since Hermes 0.21 a dead endpoint shows in Desktop as `[reason: model_unavailable]`
instead of a bare error. A bot whose endpoint is down is not a broken bot.

**4. `./swarm status`.** Each rung is a real probe: sandbox Ready, api_server
200, a chat turn through the sandbox, relay active, host profile running.

**5. Restart the Desktop app.** Cheap and usually right for anything room-level:
a quit client, stale backends after a gateway restart, routing that reverted.
Every in-sandbox gateway restart invalidates the Desktop's backend, so after
`./swarm up` on a rebooted host, restart the app too. And don't restart gateways
five minutes before a demonstration. I have done this. It goes badly.

## A bot receives nothing in a group chat

Every health check passes and it still says nothing.

First, rule out correct behaviour. The room prompt tells bots to reply only
with something new; `(pass)` is a valid answer. Read what it said:

```bash
openshell sandbox exec -n nemoclaw-researcher -- /sandbox/.hermes/hermes-agent/venv/bin/python - <<'PY'
import sqlite3
c = sqlite3.connect("/sandbox/.hermes/state.db")
for role, text in reversed(list(c.execute("select role, substr(content,1,200) from messages order by rowid desc limit 6"))):
    print(role, "|", " ".join((text or "").split())[:180])
PY
```

Then check whether the message arrived. Search the same table for a phrase
unique to your prompt. Zero hits means the bot never got it; the fault is
upstream of the bot.

The usual cause is an orphaned Desktop backend. The Desktop keeps one backend
process per profile under `~/.hermes/desktop-ssh/<hash>/backend.lock.json` on
the host. On relaunch it can latch onto one that survived a previous session,
which looks alive but is not wired to the current room. The tell is uptime skew:
three backends at 10 minutes, one at 1h23m. Kill the old one, remove its lock
directory, restart the app.

Chained tasks amplify it. `@b research, @c consolidate, @a brief` deadlocks
when `@b` is the silent one; everyone else correctly waits. Check the first bot
in the chain before debugging the rest.

Nothing schedules follow-up work. A room turn is one request, one response. A
bot that says "on it, I'll report back" then does nothing. Ask for the result in
the same message; see the soul guidance in [customizing.md](customizing.md).

## Deleted bots keep reappearing as `stopped` profiles

You ran `swarm rm` (or deleted profiles by hand), and a minute later
`~/.hermes/profiles/<name>/cron/ticker_heartbeat` is back and `hermes profile
list` shows the name as `stopped`.

The Desktop's backend on the host (`hermes serve --isolated`, spawned over SSH)
snapshots the profile list when it starts and runs a cron ticker for each one
every 60 seconds, recreating the directory. It does not notice deletions. Find
it with `pgrep -fa "hermes serve --isolated"`, kill it, remove its
`~/.hermes/desktop-ssh/<hash>/` directory, delete the ghost directories once
more, and restart the Desktop app. Desktop respawns a backend that only knows
the profiles that exist now. `swarm rm` cannot do this for you because the
backend belongs to the Desktop session, not to the swarm.

## A bot is missing from the roster

Works from the CLI, api_server returns 200, `hermes profile list` says `stopped`.

Two gateways per bot: one inside the sandbox serving the api_server, one on the
host that makes the profile report `running`. The roster lists only the second.
`./swarm up` starts it; `./swarm status` checks it. `hermes profile list`
computes `running` from `gateway.lock` plus a `gateway.pid` whose recorded start
time matches the live process, so `kill -0 $(cat gateway.pid)` is not enough,
and `gateway.pid` is JSON, not a bare PID.

## Desktop shows no bots at all

The app reads its connection config at launch and rewrites it on exit. If the
Bots pane is empty, the app is probably talking to your laptop's local runtime
instead of the host. Settings, Connections: make sure the SSH connection exists
and is selected, then restart the app.

## Nothing responds after a reboot

```bash
./swarm up
```

Sandboxes and profiles survive a reboot; processes do not. `up` restores every
bot in `BOTS` plus bots recorded by earlier `swarm add` commands, re-applies the
current tracing setting, re-checks the mesh, and prints status. It does not
start your inference endpoint.

## A request from inside a sandbox is blocked

| Code | Meaning | Fix |
|---|---|---|
| 403 | policy denied it | host not allowed, or the calling binary is not in `binaries` |
| 000 + `CONNECT tunnel failed, response 403` on stderr | policy denied an HTTPS request | same |
| 502 | allowed, nothing listening | a service on host `127.0.0.1`; sandboxes have their own netns, use the bridge |
| 401 | reached the target | credential wrong or stale |
| 200 | working | |

Policies bind to binaries as well as hosts. With `pypi.org` allowed, `curl` gets
200 and `uv` gets 403 until `uv` is listed. Redirects are separate decisions:
allow both `astral.sh` and `releases.astral.sh`.

## `policy-add` rejects the file

```
Preset must declare preset.name (lowercase, hyphenated RFC 1123 label)
```

Files given to `nemoclaw <sandbox> policy-add` are presets: top-level
`preset: {name, description}`, no `version:`, filename ending in `.yaml`.
`policies/otlp-export.yaml` is the reference shape. The `version: 3` document is
only for the initial policy at sandbox creation.

## Sandbox creation fails

| Error | Cause |
|---|---|
| `sandbox user 'sandbox' not found in image` | image needs a user and group literally named `sandbox` |
| `ContainerRestarting` | image entrypoint exits; use `CMD ["sleep","infinity"]` |
| `ContainerRestarting` and `docker logs` on the container says `OCI USER 'root' selects root` | OpenShell 0.0.101 and later refuse an image whose final `USER` is root. The Dockerfile ends with `USER sandbox`; an image built from an older revision does not, and `swarm up` rebuilds it when it sees that. Found on a fresh Ubuntu 24.04 install; OpenShell 0.0.85 accepted the root image. |
| `missing field 'version'` | the creation policy needs `version: 3` |

`openshell sandbox logs` does not exist in the CLI. To see why a sandbox went to
`Error`, read the Docker container behind it:

```bash
docker logs "$(docker ps -a --filter name=<sandbox> -q | head -1)" 2>&1 | tail -20
```

Creation takes about a minute. `openshell sandbox create` can block after the
sandbox is already Ready; `swarm` bounds it and polls `sandbox list` instead.

## Hermes inside a sandbox is the wrong version or missing

Hermes is baked into the image at `HERMES_REF`. If a sandbox reports a different
version, it was created from an older image: `./swarm rm <bot> --yes`, then
`./swarm add`. Do not `hermes update` inside a sandbox; egress to GitHub is not
allowed and the image is the source of truth.

## `message_teammate` says "Unknown teammate"

Peers must be registered inside the sandbox, because the agent loop runs there
and reads that config. `./swarm add` does this for every pair in both
directions. Check `./swarm ls`; the `peers` column is read from inside each
sandbox. Also check port direction: A's `peer-B` preset must allow B's port, not
A's own. Reversed, you get a 403 that reads like an auth failure.

## Relay says "not active" but the collector receives spans

The activation line is written at INFO to `/sandbox/.hermes/logs/agent.log`
inside the sandbox, not to `gateway.log` and not to the stderr captured on the
host. `./swarm traces <bot>` reads the right file. Trust the collector's counters
over any log grep.

## The same test prompt returns instantly and no new session appears

The api_server dedupes identical requests through its response store. Use a
unique token per probe. `./swarm test` does.

## Every model call returns 400

Hermes asks for the whole context window as output tokens unless told otherwise.
`swarm.env` sets `INFERENCE_MAX_TOKENS` and `INFERENCE_CONTEXT_LENGTH`; make sure
the second does not exceed what your server serves.

## A bot claims it verified something it did not

We watched a bot report nine GitHub issues as open, by number. Four were closed.
It had made zero tool calls that turn. Models produce real-looking identifiers
from training data when they can't reach a source, and they do it with total
confidence. Two things help: a hard rule in the soul (never state a fact a tool
didn't return this session), and tracing, where a confident turn with no tool
spans under it jumps out at you.

## A bot loops on a blocked tool and burns the whole turn

An HTML scrape failed, so the bot tried `terminal` three different ways and hit
`Operation interrupted` six minutes later with nothing to show. One paragraph in
the soul fixed it: report what you have, name the blocker, stop after three
failures with the same tool. Same task afterwards: 57 seconds, ten sources.

## `swarm rm` printed nothing and removed nothing

It asked for confirmation on a closed stdin. Pass `--yes` when scripting or
running over SSH.

## Multimodal handoffs

Everything in this section came from rehearsing the two-beat demonstration in
`examples/README.md` until three passes in a row were clean. Each entry is a
thing that looked like it worked and did not.

**The vision bot says "file not found" for an image the reviewer was given.**
The reviewer's model copied the host path from the message text and sent that.
Paths do not cross sandboxes. Fixed in the plugin: when a call explicitly sets
`with_images=true`, `message_teammate` forwards the current turn's image parts,
strips path hints from the text, and tells the receiver the image is attached.
The default is text-only. If you see this after updating, run `./swarm up`; the
plugin is re-synced only when its content hash changes.

**The image never reached the reviewer's sandbox at all.** The host profile
(`hermes -p nemoclaw-reviewer`) is itself a Hermes agent. With
`model.supports_vision` off it replaces the image with `[Image attached at:
/tmp/...]` before forwarding. `swarm` now sets it on for every shim; whether a
bot can see is decided by the model config inside its sandbox.

**The vision bot ignores the picture and calls `vision_analyze` on a path.**
The omni model reaches for the tool whenever a filename is in view, and the
tool only takes a path or URL. `swarm` disables the `vision` toolset on any
bot with `INFERENCE_VISION_<NAME>=on`; its model already sees, and the tool
had nothing to add.

**Two specialist turns for one ask, and one of them has no image.** The shim's
title generation defaults to the "main model", which for a shim is the bot, so
every Desktop message spawned a second full agent turn inside the sandbox.
`swarm` turns title generation off on shims. If you see sessions created a few
milliseconds apart in a bot's `state.db`, this is it.

**The reviewer quotes a teammate that has no new session.** Probably not a
fabrication. The api_server derives a session id from the first message, so
an identical ask reuses the earlier session. Count turns by message timestamp,
not by session creation.

**A vision bot describes an image it was never sent.** The forwarded ask had a
sender-local image path or an explicit attachment reference, but no pixels. The
plugin strips the path and marks the ask (`[No image is attached to this
message...]`); ordinary wording such as "look into this issue" is left alone.
The vision soul says to answer that it was not given an image. If you write your
own vision soul, keep that line.

**The VSS bot cannot find a clip on the host.** A chat message or Desktop
attachment does not import host files. On the host, run
`./swarm video-add /absolute/path/to/clip.mp4`, then use the filename printed by
that command in chat. The VSS tools accept only a filename or relative path that
already exists beneath `/sandbox/videos`; they reject URLs, host paths, and
traversal paths.

## Traps in your own diagnostics

- `gateway.pid` holds JSON, so `ps -p $(cat gateway.pid)` reports every gateway
  dead. Ask `hermes profile list` instead.
- Nested shell quoting mangles keys. Read them from files inside a script and
  never interpolate through `ssh '… "… \"…\" …" …'`. Same for `python -c`
  through `sandbox exec`; feed python a heredoc on stdin.
- `pkill -f <pattern>` over SSH can match your own session, because a pattern
  containing a sandbox name matches the ssh command that contains it. Kill by
  PID or by a substring the outer command cannot have.
- `docker ps` showing `Up` proves nothing. Probe the port.
- Do not probe a sandbox while `swarm add` is mid-flight. Concurrent execs
  return empty output and look exactly like a dead sandbox.

## On a shared host

- Never background a remote command whose first line is destructive.
- Never `docker rm` with a broad filter or `ancestor=`.
- Never bind a probe to a port a working service owns. The victim exits on its
  next restart with no visible connection to what you changed.
- `swarm` only touches sandboxes it has a key file for, profiles by those names,
  and its own collector. Other people's sandboxes on the
  same host are invisible to it.
