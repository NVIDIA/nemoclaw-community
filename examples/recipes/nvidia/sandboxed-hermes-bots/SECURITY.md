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

Images can cross the boundary when a bot asks for it. `message_teammate`
sends text only, unless the calling bot sets `with_images`; then the images
attached to that bot's current user turn go to the teammate's sandbox and its
model. The example souls tell text bots to set it only when handing a picture
to the vision bot. The tool result reports `images_forwarded` so the sender's
transcript shows it happened. The forwarded bytes are held in the receiving
bot's session history like any other message content.

The bot can prompt-inject its teammates. `message_teammate` delivers text
into another bot's turn. The receiving bot's soul is its only defense. The
example souls tell bots to treat inbound messages as work, not as instructions
about themselves, and to never act on a claim a tool did not verify.

The host user owns everything. `swarm` runs as the user who owns
`~/.hermes`. That user can read every key, every sandbox, and the collector.
This is an operator tool, not a multi-tenant one.

A video added by the operator is written into the VSS sandbox. The host-only
command `./swarm video-add PATH` reads the selected local file and copies it to
`/sandbox/videos`; the VSS tool then reads that copy and sends its bytes inline
to RT-VLM. The host command accepts only a nonempty, regular, non-symlink video
with a supported extension, sanitizes its basename, targets the owned, Ready
`nemoclaw-vss` sandbox, and caps both staging and inline analysis at 40 MiB.
This is an explicit operator action. Chat text and Desktop attachments never
select a host path or start an upload, and bots cannot invoke the command through
their tool interface. The sandbox copy remains until it is deleted there or the
VSS sandbox is removed. Review the file before adding it, and treat the RT-VLM
endpoint as a recipient of its contents.

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
