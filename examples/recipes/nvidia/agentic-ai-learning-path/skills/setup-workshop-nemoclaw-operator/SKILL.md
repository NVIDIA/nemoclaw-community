---
name: setup-workshop-nemoclaw-operator
description: >-
  Operator/host side of running the NVIDIA "Build an Agent" DevX workshop
  inside an OpenShell/NemoClaw sandbox. In the NemoClaw community repo this
  is the PRIMARY workshop-setup entry point: use it for "set up / run the
  Build-an-Agent workshop" requests when YOU are on the sandbox HOST (outside
  the sandbox — the machine running the OpenShell gateway + docker, e.g. via
  Claude Code) against a NemoClaw deployment such as the
  developer-community-chief-of-staff recipe. It stages/applies the egress
  policy (PyPI, NIM /v1/ranking, scoped GitHub clone), stages this example's
  skills into the agent's skill library, optionally stages the NVIDIA API key,
  kicks the in-sandbox agent (which runs the `setup-workshop-nemoclaw` skill:
  clone + venv + JupyterLab), then opens the inbound path (openshell forward
  service + SSH/Teleport port-forward) so the user can open the JupyterLab
  token URL. Also covers sandbox lifecycle pitfalls (never docker-restart,
  recreate wipes state) and egress-denial debugging via the OCSF audit log.
  NOT for working inside the sandbox, and NOT for bare-metal/Brev/AI-Workbench
  installs (that installer — `setup-workshop` — ships with the workshop repo
  itself, not with this example).
disable-model-invocation: false
user-invocable: true
---

# setup-workshop-nemoclaw-operator (host side)

Prepares an OpenShell/NemoClaw sandbox so the **in-sandbox agent** can stand up
the Build-an-Agent workshop, then opens the access path from the user's laptop
to the resulting JupyterLab. This is one half of a two-skill pair:

| Skill | Runs | Does |
|---|---|---|
| **this skill** | on the sandbox **host** (outside) | egress policy, secrets staging, kick + unblock the sandbox agent, port-forward, lifecycle |
| `setup-workshop-nemoclaw` | **inside** the sandbox | venv + deps, netlink shim, launcher/bridge fixes, Jupyter launch, URL hand-off |

## Should this skill run at all?

In the NemoClaw community repo, **yes — this is the default setup path.**
This example exists to run the workshop on a NemoClaw deployment (the
`developer-community-chief-of-staff` recipe), so a generic "set up the
build-an-agent workshop" request lands here. The prerequisite is a deployed
sandbox: if `docker ps` shows no `openshell-<sandbox>-…` container, deploy the
recipe first (its `scripts/bring-up.sh`) — this skill configures an existing
deployment, it does not create one.

Not this skill's territory: installing the workshop OUTSIDE a sandbox (bare
metal on Brev, local install via AI Workbench, GPU hosts). That installer —
the `setup-workshop` skill — ships with the upstream workshop repo, not with
this example; point the user there.

## Which side am I on?

**On the host** (use this skill): `docker ps` shows an
`openshell-<sandbox>-…` container, the `openshell` CLI is on PATH, and you are
NOT user `sandbox`. **Inside the sandbox** (use the other skill): `whoami` →
`sandbox`, `/sandbox/` exists, no `docker`/`sudo`.

## Conventions

```bash
SANDBOX=hermes-direct                                    # the sandbox name (adjust)
C=$(docker ps --format '{{.Names}}' | grep "openshell-$SANDBOX")   # its container
# The deployment (policy files + .env) is the chief-of-staff recipe:
cd <nemoclaw-community>/examples/recipes/nvidia/developer-community-chief-of-staff
# This example's skills (staged into the sandbox in Phase 2b):
EXAMPLE=<nemoclaw-community>/examples/recipes/nvidia/agentic-ai-learning-path
```

Two policy files matter in the community example: **`policy.yaml`** (the
TEMPLATE — re-rendered into the sandbox at every recreate) and
**`policy.hermes-direct.yaml`** (the live-policy capture you hand-edit). Keep
BOTH in sync with any change, or a recreate/re-apply silently reverts it.

> **If you are an agent (e.g. Claude Code) driving this:** egress-widening
> `openshell policy set` runs are typically denied by the permission layer
> unless the human runs them or explicitly names the exact hosts being opened.
> That denial is correct. Your job is to *stage and verify* the policy file,
> then hand the human one copy-paste command with a precise "this opens
> exactly: …" description. Same for the secrets write (it moves a credential).

## Phase 0 — Discover state (all read-only)

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep "$SANDBOX"   # container up?
openshell policy get "$SANDBOX" | head -5                        # live revision + hash
docker exec "$C" ls -la /sandbox/workshop-build-an-agent 2>&1 | head -3   # repo cloned?
docker exec "$C" ls -l /sandbox/workshop-build-an-agent/secrets.env 2>&1  # key staged?
```

`docker exec` is fine for these *filesystem* peeks. It is **NOT** a valid
probe for egress/syscall behavior — exec'd processes bypass the per-process
Landlock/seccomp layers and yield false "allowed" results. Egress tests go
through `openshell sandbox exec` only (single-line commands; it rejects
multi-line args).

## Phase 1 — Egress policy (one-time)

The sandbox denies all egress by default, and the chief-of-staff recipe's
stock policy does not include any workshop route — you apply the additions
below (live policy + your local template). Exact YAML in
`references/policy-blocks.md`:

| Block | Opens | Needed for |
|---|---|---|
| `github_git_clone` | git smart-HTTP on `github.com`, scoped to the one workshop repo, for the git binaries | cloning the repo (skip if already cloned) |
| `pypi_install` | read-only `GET` to `pypi.org` + `files.pythonhosted.org` | `uv pip install` of the workshop deps |
| `nvidia_retrieval` | `POST /v1/retrieval/**` on `ai.api.nvidia.com` | modules 2/3 `NVIDIARerank` — ⚠️ the legacy `/v1/ranking` rule on `integrate.api.nvidia.com` does NOT cover `llama-nemotron-rerank-1b-v2` |
| `tavily_search` | `POST /search`+`/extract` on `api.tavily.com` | module-1 docgen, module-2 local-MCP web search, module-5 search (key: `TAVILY_API_KEY`) |
| `langsmith_api` | all methods on `api.smith.langchain.com` | module-3 eval/tracing AND silencing tracing-retry spam in every notebook (`variables.env` turns tracing on globally; key: `LANGSMITH_API_KEY`) |
| `tiktoken_encodings` | `GET /encodings/**` on `openaipublic.blob.core.windows.net` | module-7 harness_lab (tiktoken BPE download at first use) |
| `npm_install` | read-only `GET` to `registry.npmjs.org` (binary: `/usr/local/bin/node`) | module-5 "Deep Agents Client" tile — `demo/` needs `npm install` or the tile only serves its "setup required" page; also fetches the `mcp-remote` transport for the block below |
| `mcp_tavily` | `GET`/`POST`/`DELETE` on `mcp.tavily.com` (binary: `/usr/local/bin/node`) | module-2 PART 2A remote MCP — the shipped default. ⚠️ Policy alone is not enough: the MCP stdio transport drops the proxy env, so the in-sandbox `tune_remote_mcp_env.py` is also required |
| `/dev/pts` fs grant | rw on the devpts filesystem (PTY allocation) — under `filesystem_policy`, not `network_policies` | JupyterLab's Terminal tile (terminado → `pty.fork`); without it the tile pops "Launcher Error: Unhandled error" |

Not needed: `build.nvidia.com` (notebook prose only — every model call goes to
`integrate.api.nvidia.com`), torch/conda mirrors, npm.

⚠️ The supervisor parses `filesystem_policy` ONCE at container **boot** —
`openshell policy set` hot-reloads network rules but NOT filesystem grants
(verified live: after applying a `/dev/pts` grant, new spawns still built
the old ruleset). The grant must be in the TEMPLATE (`policy.yaml`) and
takes effect at the next sandbox **recreate**. There is no restart command,
and raw `docker restart` hits the stale-bootstrap-JWT crash loop.

Workflow (details + YAML in the reference):

1. Capture live policy: `openshell policy get "$SANDBOX" --full > /tmp/live.yaml`.
2. Build the apply file = **live policy + the new blocks and nothing else**
   (minimal delta), and structurally verify it (same block names ± the
   additions) before applying. Update `policy.yaml` AND
   `policy.hermes-direct.yaml` in the repo to the same desired state.
3. Apply (human runs it if the permission layer blocks you):
   ```bash
   openshell policy set "$SANDBOX" --policy <file> --wait
   # success: "✓ Policy version N submitted … loaded (active version: N)"
   ```
   **⚠️ `policy set` REPLACES the entire policy document — it does not
   merge.** Applying a partial/stale file silently revokes whatever it omits
   (this exact mistake once reverted a GitHub grant here). OpenShell ≥ 0.0.53
   also has `openshell policy update` for incremental adds — prefer it for
   one-block changes if available.
4. Verify under real enforcement (NOT docker exec):
   ```bash
   openshell sandbox exec -n "$SANDBOX" --no-tty -- sh -lc 'curl -s -o /dev/null -w "%{http_code}\n" https://pypi.org/simple/'   # expect 200
   ```
   `scripts/verify-sandbox-ready.sh` runs the full probe set.

## Phase 2 — Keys: leave NVIDIA_API_KEY UNSET (default)

**Do nothing here in the normal flow.** The learner sets `NVIDIA_API_KEY` in
the workshop's own **Secrets Manager** tile, which writes the repo-root
`secrets.env` that every notebook `load_dotenv()`s. Leaving the variable absent
at server-launch time is deliberate, not an oversight:

`start-jupyter.sh` `set -a`-sources `secrets.env` into the Jupyter server env at
launch, and kernels inherit that env. `load_dotenv()` does **not** override
variables already present in the environment — so anything baked in at launch
**shadows later edits to the file**. Stage a key before launch and the learner's
Secrets Manager change is silently ignored until the server restarts; leave it
unset and `load_dotenv()` stays authoritative, so the key takes effect on the
next cell run with no restart. This is exactly why the Tavily and LangSmith
keys never exhibited the problem — they were never injected.

`scripts/verify-sandbox-ready.sh` agrees: an absent key is a PASS in its
default mode. Set `EXPECT_PRESEEDED=1` only when auditing an image that is
supposed to carry a baked-in key.

⚠️ **Never fall back to `COMPATIBLE_API_KEY` / `OPENAI_API_KEY`.** Those name
the NemoClaw *agent's* inference credential — in the community example an
`sk-…` key for the host TLS proxy (`NEMOCLAW_ENDPOINT_URL`), not a
build.nvidia.com `nvapi-…` key. The old one-liner did this and produced a
`secrets.env` that looked correctly populated while every notebook died with
`AuthenticationError: 401` against `integrate.api.nvidia.com`. Real incident;
`stage-nvidia-key.sh` now refuses that fallback and warns on any non-`nvapi-`
key.

Only pre-seed a key when you actually want one baked in (unattended classroom
image), and pass a real `nvapi-…` key explicitly:

```bash
printf '%s' 'nvapi-…' | SANDBOX=<sandbox> bash scripts/stage-nvidia-key.sh
# or, from a dotenv file that carries a genuine NVIDIA_API_KEY:
SANDBOX=<sandbox> bash scripts/stage-nvidia-key.sh --env-file ./.env
```

The script merges (never truncates) — the Secrets Manager tile rewrites the
same file wholesale, so a truncating write would destroy keys the learner
already set. It reports key NAMES only, never values. If you pre-seed while
JupyterLab is already up, re-run `start-jupyter.sh` (token/URL survive) so
kernels pick the key up.

Never paste keys through the agent's chat channel (the in-sandbox agent will
itself refuse them). Tavily (modules 1/2/5 search) and LangSmith (module-3
tracing) are handled the same way — set them in the Secrets Manager, or pass
them to the same script; their policy blocks are in `references/policy-blocks.md` too.

## Phase 2b — Stage this example's skills into the agent library

A fresh sandbox has neither the workshop repo nor any workshop skill, so the
in-sandbox agent has nothing to run yet. Stage this example's skill copies
into the agent's skill library — they register as `local`/`enabled` on the
agent's next session, and `setup.sh`'s final step deliberately treats staged
copies as canonical (it never overwrites them from the clone):

```bash
for d in "$EXAMPLE"/skills/*/; do
  name=$(basename "$d")
  [ "$name" = "setup-workshop-nemoclaw-operator" ] && continue  # host-side; would only mislead the in-sandbox agent
  docker exec "$C" rm -rf "/sandbox/.hermes-data/skills/$name"  # avoid docker-cp nesting on re-stage
  docker cp "$d" "$C:/sandbox/.hermes-data/skills/$name"
done
docker exec "$C" chown -R sandbox:sandbox /sandbox/.hermes-data/skills
docker exec "$C" ls /sandbox/.hermes-data/skills                # verify
```

`docker cp`/`docker exec` are fine here — this is filesystem staging, not an
egress/syscall probe. Minimum viable staging is `setup-workshop-nemoclaw`
alone (setup then fills the tutor skills from the clone), but staging the
full set keeps the library on this example's adjusted copies.

## Phase 3 — Kick the in-sandbox agent

Message the sandbox agent. Without a chat channel wired up, the working path
is a one-shot `hermes` session under real sandbox enforcement (`openshell
sandbox exec` rejects multi-line args — keep the prompt on one line):

```bash
openshell sandbox exec -n "$SANDBOX" --no-tty -- sh -lc \
  'cd /sandbox && hermes --accept-hooks -z "<the message below, one line>"'
```

> Egress policy for the Build-an-Agent workshop is applied: the workshop-repo
> clone route, PyPI installs, and the NIM/reranking endpoints are open. The
> `setup-workshop-nemoclaw` skill is staged in your skill library
> (`/sandbox/.hermes-data/skills/`). Run it (NOT the workshop repo's
> bare-metal `setup-workshop`): it clones the workshop repo, then runs
> preflight, setup, and start-jupyter. When JupyterLab is up, save the token
> URL to `/sandbox/workshop-url.txt` and report back; I'll open the forward.
> `NVIDIA_API_KEY` is deliberately not staged — the learner sets it in the
> Secrets Manager tile.

NemoClaw-specific gotcha: the agent's persona (`SOUL.md`) may still say
GitHub/PyPI/serving are off-limits, making it refuse without trying. The
gateway caches `SOUL.md` at startup — after editing the durable copy and
uploading to `/sandbox/.hermes-data/SOUL.md`, either restart the agent stack
or (simpler) tell the live agent explicitly what is now allowed, as above.
Do not relay environment guesses as facts — a wrong relayed TLS path once
cost real round-trips; the in-sandbox skill now carries the correct values.

## Phase 4 — Open the access path (per session)

The agent's Jupyter binds the sandbox **inner** loopback (`127.0.0.1:8888`).
Agent processes live in an inner network namespace — a server bound even to
0.0.0.0 is unreachable at the container IP. The only inbound path:

```bash
# 1. On this host (FOREGROUND — leave the terminal open). Note: `openshell
#    forward list`/`stop` do NOT track `forward service` tunnels — stop it
#    with Ctrl-C or pkill -f "forward service $SANDBOX".
openshell forward service "$SANDBOX" --target-port 8888 --local 8888

# 2. Sanity check from another host shell (302 = alive, auth redirect):
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8888/lab

# 3. Get the token URL (gateway masks tokens in agent chat, hence the file):
docker exec "$C" cat /sandbox/workshop-url.txt
```

Then from the **laptop**, ONE of (full Teleport troubleshooting in
`references/access-and-lifecycle.md`):

```bash
ssh -N -L 8888:localhost:8888 <user>@<sandbox-host>          # vanilla ssh
tsh ssh -N -L 8888:localhost:8888 <user>@<node-name>         # Teleport: NODE NAME from `tsh ls`, not DNS/IP
```

**`-N` is silent when it works** — no output means the tunnel is UP; open the
browser before assuming a hang. Finally open the token URL:
`http://localhost:8888/lab?token=…`.

## Phase 5 — When something is denied

The L7 proxy/OCSF audit log names the exact process path and rule for every
verdict:

```bash
docker logs "$C" | grep -E "DENIED|NET:FAIL" | tail
```

Feed that line back into the policy (right block, right binary — enforcement
resolves symlinks, so e.g. `git-remote-https` → list `git-remote-http` too),
re-apply, re-verify. If the in-sandbox agent reports a blocked call, ask it
for the exact URL/error and match it against the log.

Two verdict patterns that are NOT policy gaps (both observed live):

- **Boot-time noise:** a `/usr/bin/python3.13` DENIED to `github.com:443`
  ("binary not allowed in policy 'github_git_clone'") right after sandbox
  start is agent-stack startup traffic. Python is deliberately absent from
  that block's `binaries` — ignore it; it is not workshop breakage.
- **First-touch flake:** a probe reports curl `000` while the audit log shows
  ALLOWED at both engines for that same request — the first request to a host
  through the L7 proxy can stall past curl's timeout. Retry before editing
  policy (`verify-sandbox-ready.sh` retries its clone-route probe once for
  exactly this reason).

## Lifecycle pitfalls (each caused real breakage)

- **NEVER `docker restart` the sandbox container.** It boots from a static
  bootstrap JWT (1-hour TTL, not refreshed on disk); a restarted container
  re-reads the stale token and crash-loops (`Policy fetch failed …
  ExpiredSignature`), sticking the sandbox in `Provisioning`. Recovery needs a
  re-minted token or a delete/recreate/restore cycle.
- **A container restart does NOT relaunch the agent stack** (`nemoclaw-start`:
  agent, relay, bridges — and JupyterLab). Relaunch the stack (e.g. the
  chief-of-staff recipe's autoheal `watchdog.sh`), then have the agent re-run
  `start-jupyter.sh`.
- **A sandbox recreate wipes the container filesystem** (venv, shim,
  `secrets.env`, the server). Policy is re-rendered from the `policy.yaml`
  TEMPLATE at recreate — which is why the workshop blocks must live in the
  template too. After recreate: redo Phase 2, then have the agent re-run
  `setup.sh` + `start-jupyter.sh` (both idempotent).
- **`docker exec` proves nothing about the agent's sandbox** (1 seccomp filter
  vs the agent's 4, no Landlock). Egress/syscall tests: `openshell sandbox
  exec` only.
- **The netlink/seccomp kernel-startup block has NO operator knob** — it is
  compiled into the in-container OpenShell supervisor (Rust seccompiler), not
  the Docker seccomp JSON, not the policy schema. The sanctioned fix is the
  in-sandbox LD_PRELOAD shim (the sandbox skill builds it). Do not edit Docker
  seccomp JSON for this; it has no effect.
- **Never route workshop execution through `docker exec`** to dodge seccomp —
  it also escapes Landlock egress enforcement. Forbidden.

## End-to-end verification checklist

- [ ] `openshell policy get "$SANDBOX"` shows the new revision; probes via
      `openshell sandbox exec`: pypi 200, `integrate.api.nvidia.com/v1/models` 200.
- [ ] Skills staged: `docker exec "$C" ls /sandbox/.hermes-data/skills` lists
      `setup-workshop-nemoclaw` (+ `workshop`, `module-1`…`module-7` if the full
      set was staged).
- [ ] (only if a key was pre-seeded) `docker exec "$C" ls -l /sandbox/workshop-build-an-agent/secrets.env` → present, mode 600.
- [ ] Sandbox agent reports JupyterLab up; `docker exec "$C" cat /sandbox/workshop-url.txt` → URL.
- [ ] Forward running; host `curl …:8888/lab` → 302.
- [ ] Laptop tunnel up; browser shows 11 launcher tiles; a module-2 rerank cell returns 200.
- [ ] Terminal tile opens a shell (`POST /api/terminals` with token → 200) —
      needs the `/dev/pts` grant; when absent the tile is auto-hidden.
