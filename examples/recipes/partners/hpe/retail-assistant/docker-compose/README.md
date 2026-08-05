# NemoClaw Retail Demo — Docker Compose

Deploys a fully automated NemoClaw retail assistant (v0.0.50) with Telegram integration, a FastAPI retail backend, PostgreSQL with RBAC, and a local or remote vLLM inference endpoint. A single `docker compose up` produces a working Telegram bot with no manual steps.

> For common documentation (LLM endpoint setup, identity files, adding users, database schema), see the [root README](../README.md).

## Prerequisites

- A **Telegram bot token** and your **Telegram user ID** (see [Getting Your Telegram Credentials](../README.md#getting-your-telegram-credentials))
- A deployed **LLM with tool calling support** (see [LLM Inference Endpoint](../README.md#llm-inference-endpoint))
- Docker with host socket access (`/var/run/docker.sock`)

## Project Structure

```
docker-compose/
├── .env                          # Environment variables (edit before deploying)
├── docker-compose.yaml           # Service definitions
├── api/                          # FastAPI retail API
│   ├── Dockerfile
│   ├── main.py                   # JWT auth, RBAC, all endpoints
│   ├── requirements.txt
│   └── test_api.py
├── retail_database/
│   └── init.sql                  # Schema + PostgreSQL roles + RLS policies + views
├── synthetic_data/
│   └── csv/                      # Seed data (stores, products, inventory, employees...)
│       ├── Employees.csv
│       ├── TelegramAuth.csv      # Telegram ID → employee_id mappings
│       └── ...
├── docker/
│   └── daemon.json               # Docker daemon config for the workspace container
├── demo/
│   └── RBAC-questions.txt        # Sample RBAC test queries
└── scripts/
    ├── init/
    │   ├── startup.sh            # Main entrypoint — all onboarding automation
    │   ├── seed.sh               # Database CSV seeder
    │   ├── patch-openclaw.py     # Patches openclaw.json inside the sandbox
    │   └── patch-sandboxes.js    # Patches sandbox configuration
    ├── identity/
    │   ├── AGENTS.md             # Agent tone and response formatting rules
    │   ├── SOUL.md               # Auth, RBAC, tool usage rules, schema facts
    │   └── USER.md               # Runtime user context (language detection, store scoping)
    ├── skills/
    │   └── retail-api/
    │       ├── SKILL.md          # Retail API skill with nemoclaw frontmatter
    │       └── scripts/
    │           └── retail-api.js # Node.js CLI wrapper for the FastAPI
    └── policies/
        └── policy.yaml           # Sandbox network policy
```

## Environment Variables

Edit `docker-compose/.env` before deploying:

| Variable | Required | Default | Description |
|---|---|---|---|
| `OPENAI_BASE_URL` | **Yes** | — | Full base URL of an OpenAI-compatible endpoint, including `/v1` (e.g. `http://localhost:8600/v1`). Supports container names, IPs, nip.io domains, and `https://` hosted endpoints. |
| `OPENAI_API_KEY` | No | `none` | API key for `OPENAI_BASE_URL`. Leave `none` for local servers without auth. |
| `NEMOCLAW_MODEL` | **Yes** | — | Model name as served by the endpoint (e.g. `nvidia/NVIDIA-Nemotron-3-Super-120B-A12B-FP8`) |
| `TELEGRAM_BOT_TOKEN` | **Yes** | — | Bot token from @BotFather |
| `TELEGRAM_USER_ID` | **Yes** | — | Comma-separated numeric Telegram user IDs allowed to use the bot |
| `NEMOCLAW_SANDBOX_NAME` | No | `retail-demo-assistant` | Name of the OpenShell sandbox |
| `PSQL_USER` | No | `admin` | PostgreSQL user |
| `PSQL_PASSWORD` | No | `admin` | PostgreSQL password |
| `PSQL_DB` | No | `retail` | PostgreSQL database name |
| `JWT_SECRET` | No | auto | JWT signing secret for the retail API |
| `OPENCLAW_MAX_TOKENS` | No | `8192` | Max tokens per model response. Lower = faster. |
| `OPENCLAW_STREAMING_MODE` | No | `partial` | Telegram streaming: `partial` (token-by-token) or `full` (wait for complete response) |
| `OPENCLAW_TOOL_PROGRESS` | No | `false` | Show tool-call progress messages in Telegram while the agent is working |
| `DB_EXT_PORT` | No | `5432` | External port for PostgreSQL (useful when running multiple stacks) |
| `API_EXT_PORT` | No | `8002` | External port for the retail API |
| `SOCAT_INFERENCE_PORT` | No | `8000` | Workspace port for the vLLM socat proxy |
| `SOCAT_API_PORT` | No | `8001` | Workspace port for the retail API socat proxy |
| `NEMOCLAW_GATEWAY_PORT` | No | `8080` | OpenShell gateway port |
| `NEMOCLAW_DASHBOARD_PORT` | No | `18789` | NemoClaw dashboard port |
| `OPENSHELL_DOCKER_NETWORK_NAME` | No | `openshell-docker` | Docker network name (change if running multiple stacks) |
| `CHAT_UI_URL` | No | — | External URL for the NemoClaw dashboard. Leave empty if not using ingress |
| `NEMOCLAW_BIN_PATH` | No | `/tmp/nemoclaw-bin` | Host path for shared OpenShell binaries. Only set if running multiple stacks on the same host. |

> **`OPENAI_BASE_URL` with a container name:** attach the vLLM container to the same Docker network and use its name directly:
> ```bash
> docker network connect nemoclaw-docker nemotron-super
> ```
> Then set `OPENAI_BASE_URL=http://nemotron-super:8000/v1`. For a remote host use its IP, or a hosted `https://` endpoint.

## Adding a User

### Step 1 — Whitelist the Telegram ID

```env
TELEGRAM_USER_ID=existing_id_1,existing_id_2,NEW_TELEGRAM_ID
```

### Step 2 — Map Telegram ID to an employee

Add a row to `synthetic_data/csv/TelegramAuth.csv`:

```csv
telegram_id,employee_id
NEW_TELEGRAM_ID,<employee_id>
```

### Step 3 (optional) — Create the employee record

```csv
employee_id,first_name,last_name,role,store_id,email
<next_id>,First,Last,<role>,<store_id or blank>,first.last@retaildemo.com
```

Then redeploy:

```bash
docker compose down -v && docker compose up -d
```

> ⚠️ **The `-v` flag is required.** Without it, the existing PostgreSQL volume is reused and the seed scripts never run — the new `TelegramAuth` row is never inserted and the user cannot authenticate.

## Installation

### First deploy

```bash
cd docker-compose
cp .env.example .env   # if starting fresh
# Edit .env with your values
docker compose up -d
```

The `workspace` container's `startup.sh` handles everything automatically:

1. Installs packages: `docker.io`, `socat`, `curl`, Node.js 22
2. Parses `OPENAI_BASE_URL` and resolves DNS for container-name hosts
3. Starts socat proxies — inference on `:8000`, retail API on `:8001`
4. Verifies host Docker socket is available
5. Prunes stale Docker build cache
6. Exports Telegram channel config as base64 build args
7. Runs the NemoClaw v0.0.50 installer (`--fresh`)
8. If Fix #9 applies (gateway binary path issue), copies binaries to shared volume and pre-starts the gateway container
9. Waits for the sandbox container to be running
10. Applies post-deploy fixes:
    - **Fix 1**: updates the gateway provider URL to the workspace container IP
    - **Fix 2**: adds `inference.local` to the sandbox `/etc/hosts`
    - **Fix 3a**: force-installs the nemoclaw plugin (exec tool)
    - **Fix 3b**: patches `openclaw.json` — Telegram config, tool allowlist, identity files (SOUL, USER, AGENTS)
    - **Fix 4**: installs the `retail-api` skill and CLI into the sandbox
    - **Fix 5**: applies the network policy; starts Python TCP relay on `10.200.0.1:8001` inside the sandbox
    - **Fix 6**: waits for openclaw hot-reload, re-applies `openclaw.json`
    - **Fix 7**: restarts openclaw with `kill -9` for a clean Telegram poller
    - **Fix 8**: verifies end-to-end inference

The first time, `docker compose up` builds the **OpenShell sandbox** — a persistent container named `openshell-retail-demo-assistant-<suffix>`. **Allow 15–20 minutes** for a fresh deploy.

### Updating configuration (fast restart, ~2 min)

If you only need to change `.env` variables (model URL, Telegram user IDs, `OPENCLAW_*` tuning):

```bash
docker compose down   # sandbox container is preserved
# Edit .env
docker compose up -d  # workspace restarts, re-applies all configuration
```

### Full rebuild

Required when changing `openclaw.json` structure, network policy, or identity files:

```bash
docker compose down
docker rm -f $(docker ps -aq --filter "name=openshell-retail-demo-assistant")
docker compose up -d  # full rebuild — allow 10–15 minutes
```

> Find the sandbox container: `docker ps -a | grep openshell-retail-demo`

### Monitor progress

```bash
# Follow logs in real-time
docker logs -f $(docker ps --filter "ancestor=ubuntu:24.04" --format "{{.Names}}" | head -1)
```

Key log markers:

| Marker | Meaning |
|---|---|
| `[1/4] Installing packages...` | Starting up |
| `[4/4] Running NemoClaw installer...` | Installer launched (slow) |
| `[Post-deploy] Sandbox running.` | Sandbox up, applying fixes |
| `[Post-deploy] TCP relay: 10.200.0.1:8001` | API relay active |
| `[Post-deploy] Inference OK` | LLM reachable end-to-end |
| `[Post-deploy] All fixes applied.` | Ready |

### Verify

Message your bot on Telegram:

> Show me low stock products

### Tear down

```bash
docker compose down -v   # -v removes database volume
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `socat-8000 ERROR: socat failed again` | Endpoint unreachable. Check `OPENAI_BASE_URL` and that the model server is running. |
| `Docker not available via host socket` | Check `/var/run/docker.sock` is accessible on the host. |
| `[Fix9] Pre-starting gateway container...` | Normal — gateway binary workaround. |
| `Sandbox not created after second attempt` | Check `docker logs nemoclaw-openshell-gateway`. Try `docker compose down -v` and retry. |
| `WARNING: Retail API relay failed to start` | Python relay failed. Check sandbox is healthy: `docker ps`. |
| `Inference verification failed` | socat proxy died or provider URL wrong. Check `ss -tlnp \| grep 8000`. |
| Bot not responding on Telegram | Verify `TELEGRAM_BOT_TOKEN` and that the Telegram ID is in both `TELEGRAM_USER_ID` and `TelegramAuth.csv`. |
| Data from wrong store | `store_id` scoping issue. Check SOUL.md is correctly applied in the sandbox. |
