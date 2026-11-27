# Install and run Multi-Agent Studio

Use Ubuntu 24.04 on AMD64 or ARM64 (including DGX Spark), with local rootful Docker Engine **28+**, Docker Compose **2.24+**, and internet for initial downloads. The demo has also run on Windows RTX Spark. Run the launcher **inside WSL** with Docker Engine and the Compose plugin installed and running there.

Hosted inference needs no GPU on the studio host. The launcher runs OpenClaw and OpenShell in isolation and needs no host Python or Node installation. Minimum CPU and RAM requirements have not been benchmarked.

## Provider keys

For a hosted model, enter your key in **Settings → Model → External Endpoint**. For a local-only demo, skip this step.

For a custom NVIDIA NIM endpoint, enter its HTTPS address ending in `/v1` and a key for that address. To preconfigure a demo, copy `api.json.example` to `api.json` if needed and fill in the provider’s `apiKey` and `baseUrl` before starting.

Get a key from [NVIDIA NIM API](https://build.nvidia.com/settings/api-keys), [OpenAI](https://platform.openai.com/api-keys), or [Anthropic (Claude)](https://platform.claude.com/settings/keys).

**Use a demo-only API key.** Multi-Agent Studio is designed for demos and does not provide enterprise-grade protection for API keys. Create a dedicated key and revoke it after the demo, or rotate it if you plan to use it again.

## First start

From the project folder, check Docker and start a fresh demo. This clears previous agents, chats and results.

```bash
docker info
docker compose version
./bac start
```

The first start creates `.env` from the supplied example, builds the pinned runtime image from source (or loads the supplied release image) and downloads the OpenShell images. Later starts reuse the image unless its dependencies changed.

On the demo machine, open **http://localhost:8080** or **http://127.0.0.1:8080**.

### Connect to a remote DGX Spark

1. From your laptop, connect to the Spark over SSH. Replace `USER@SPARK` with your usual SSH account.

   ```bash
   ssh -o ExitOnForwardFailure=yes -L 127.0.0.1:18080:127.0.0.1:8080 USER@SPARK
   ```

2. On the Spark, follow [First start](#first-start) for a new installation. If Studio is already running, leave it running.
3. Keep the SSH session open and visit **http://127.0.0.1:18080** on your laptop. Port 18080 forwards to Studio on the Spark, so your laptop's port 8080 stays available.

## Connect a model

In **Settings → Model**, either connection can run every stage. Choose a model that supports tool calling.

- **Local** - Start vLLM, llama.cpp, Ollama or another OpenAI-compatible model server. Enter its URL as seen from the studio host, including `/v1` (for example, `http://127.0.0.1:8000/v1`). A local-only demo needs no hosted API key.
- **External Endpoint** - Choose a provider, confirm its endpoint and enter your API key if needed. Click **Connect**, choose a model, then click **Use model**.

With both connections ready, new hires default to **Local** in Agent Lounge. In **Open Task**, agents on the default use the external model and return to their Lounge choice afterward. An API model selected at hiring stays selected in both stages unless you choose a different Open Task model for that agent.

## Commands

| Action | Command |
| --- | --- |
| Start fresh, clearing runtime data | `./bac start` |
| Apply updated code and keep runtime data | `./bac start --keep-data` |
| Check status | `./bac status` |
| View recent logs | `./bac logs` |
| Reset the Compose stack, data, and OpenShell policies | `./bac stop` |
| Stop, preserving agents, conversations, app data, volumes, and OpenShell policies | `./bac stop --keep-data` |
| **Uninstall Multi-Agent Studio and its data** | **`./bac remove`** |

`./bac start` may interrupt active work and clears runtime data by default. Keys entered in the browser need reconnecting after refresh or restart; a provider key from `api.json` can supply all stages. Keyless local models need no credential re-entry.

## Update

For a source checkout, finish active tasks. To update and start a fresh demo, run the commands below from the same directory. To preserve your agents and results, add `--keep-data` to the start command.

```bash
git pull --ff-only
./bac start
```

Keep your local `.env`, `shared` and `backups`; Git excludes them. If Git reports local edits or a diverged branch, resolve those before starting so you run the intended version.

| Layer | Updates |
| --- | --- |
| Runtime image: Python, Node, OpenClaw, OpenShell | Only when dependencies change |
| App files: UI, server, skills, characters | On the next start after `git pull --ff-only` |
| User data: agents, conversations, results | Preserved with `--keep-data`; cleared by plain `start` |

Keep the repository folder: app files are copied into the container at startup, so host edits do not alter a running session. `./bac start` checks compatibility and rebuilds the runtime image only when necessary.

## If startup fails

| Message or symptom | Action |
| --- | --- |
| Provider rejects the key | Check that the key matches the provider and endpoint. After changing `api.json`, restart the studio to load it. |
| Inference API unavailable or rate-limited | Check connectivity or wait, then retry; the existing key is not replaced |
| Docker unavailable | Start Docker; check `docker info` works for your account |
| Wrong architecture | Use Docker running locally on this PC and its native architecture |
| Missing source files | Check `git status`; restore missing tracked files before starting |
| Port occupied | Change the relevant port in `.env`, then restart the studio |
| Model unreachable | Check the host model server and its actual port; use a `/v1` endpoint |
| Model answers but tools fail | Try a tool-capable model and inspect the agent's Activity |
| Other startup failure | Check `./bac logs`, fix the reported issue and restart the studio |

Default ports: app **8080**, OpenClaw **28689**, OpenShell **28680**, health **28681**. Settings → Location changes the default city (Zurich). Settings → Reset deliberately clears demo data.

## Data and removal

Data lives in `bac-demo_studio-data`, `bac-demo_client-certs`, and `/var/lib/bac-openshell`. `shared/` is exposed as `/host-files`; Linux file permissions must allow container UID 10001. One Multi-Agent Studio installation is supported per machine.

`./bac stop` is a destructive reset: it removes the Compose stack, deletes the `studio-data` and `client-certs` volumes, and clears Multi-Agent Studio-managed OpenShell gateway state including policies. On upgraded installations, it also stops a model still owned by the previous launcher. Independently started model servers, model weights, `shared/`, and the managed `/var/lib/bac-openshell` directory itself remain. Use `./bac stop --keep-data` to preserve agents, conversations, app data, volumes, and OpenShell policies for a later `./bac start --keep-data`.

`./bac remove` asks you to type `remove` once. It deletes Multi-Agent Studio containers, agents, chats, results, shared files, backups, recorded current/previous project images, local settings and local API credential files. The repository code remains. Host model servers and other projects remain. Images still used elsewhere are reported rather than forcibly removed. Docker's shared build cache and manually copied backups outside this folder are not searched or pruned.

For a same-host backup, finish active work, then:

```bash
docker compose exec studio python3 scripts/container_runtime.py idle
./bac stop --keep-data
mkdir -p backups
docker compose run --rm --no-deps --user 0 -v "$PWD/backups:/backup" init backup
./bac start --keep-data
```

Backups contain app data and gateway metadata/certificates, not every sandbox's mutable filesystem. The studio's provider and team API key files are excluded. Use these backups for same-host recovery. Never use `docker compose down -v` for an update.
