# Security

What the sandbox stops, what it doesn't, and which keys end up where. If you're
deciding whether to run this on a machine you care about, read the second
section first.

## Protected

Each bot is contained. It runs in an OpenShell sandbox with its own PID,
network, mount, and IPC namespaces. It cannot see host processes, other bots'
processes, or other bots' files. `./swarm test` reads `/proc/self/ns/*` from
inside each sandbox and from the host and fails if any match.

Egress is deny by default. A bot reaches exactly what its policy lists: the
inference endpoint, the tracing collector, the api_server ports of its
teammates, and whatever a `policies/<bot>.yaml` adds (the researcher gets GitHub;
the reviewer gets nothing extra). Anything else fails at the proxy. The suite probes an unlisted host
from inside every sandbox and expects the denial.

Policies only grow. `swarm` adds named presets and never calls
`openshell policy set` after creation, because that replaces the whole policy. Each
addition is a named preset you can read in `policies/`.

Tools run inside the sandbox. A bot's `terminal` tool executes in its own
container. The suite asks a bot for `hostname` and checks the answer is the
sandbox's.

Bot to bot traffic is authenticated. Each bot's api_server requires a bearer
key generated at creation (`openssl rand -hex 32`, stored 600 on the host and in
the bot's own `.env`). A bot holds only the keys of teammates it is meant to
reach. The suite checks a wrong key is rejected.

Observability credentials stay on the host. The LangSmith key, if you use
one, is read from a 600 file and passed to the collector container as an
environment variable. No sandbox ever holds it; the collector is what reaches
LangSmith.

Hermes is pinned to a tag in the image. Sandboxes cannot reach PyPI, and only
the researcher can reach GitHub, so nothing inside can update itself.

## Not protected

A bot holds the inference key. It has to; it calls the model. If you share
one key across bots, a compromised bot can spend on that key. Use a per-bot key
or a metered key if that matters to you. The key is in `/sandbox/.hermes/.env`,
mode 600, readable by the bot.

The bot can prompt-inject its teammates. `message_teammate` delivers text
into another bot's turn. The receiving bot's soul is its only defense. The
example souls tell bots to treat inbound messages as work, not as instructions
about themselves, and to never act on a claim a tool did not verify.

The host user owns everything. `swarm` runs as the user who owns
`~/.hermes`. That user can read every key, every sandbox, and the collector.
This is an operator tool, not a multi-tenant one.

A dropped video is written into one sandbox. When a vss bot exists, each
bot's host shim carries a plugin that copies a video the user drops into
Desktop into the vss sandbox's `/sandbox/videos`, using the same
`openshell sandbox upload` that ships the example clips. It is host code
acting on the host user's file, so it adds no capability the host user did not
already have. It is bounded anyway: video extensions only, 200 MB, one target
directory, filename sanitized, and it never reads the file's contents. The
shim's other tools cannot call it; it runs only on a message that carries a
video attachment. It is not installed when no vss bot exists.

Desktop reaches the host over SSH. Whoever has that SSH key can talk to every
bot. The bots do not authenticate Desktop users separately.

The inference endpoint sees everything. Prompts, tool outputs, and handoff
text go to whatever `INFERENCE_BASE_URL` points at. Pick an endpoint you would
trust with the content.

Sandbox escape is out of scope here. This example inherits OpenShell's
isolation; it does not add to it. Read OpenShell's own security documentation
for its threat model.

## What you hold

| Secret | Where | Mode | Who reads it |
|---|---|---|---|
| inference API key | `~/.secrets/inference.key` | 600 | `swarm`, copied into each sandbox `.env` |
| per-bot api_server key | `~/.swarm/keys/<bot>.key` | 600 | `swarm`, the host profile, that bot, its teammates |
| LangSmith key (optional) | `~/.langsmith/api_key` | 600 | the collector container only |
| SSH key to the host | your laptop | | Hermes Desktop |

None of these are in the repository. `./swarm presubmit` fails on anything that
looks like one.

## Reporting

This is a community example. Open an issue on the repository. For OpenShell or
NemoClaw vulnerabilities, follow NVIDIA's product security process.
