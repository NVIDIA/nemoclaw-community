# Ubuntu with an existing model server

For a new machine, prefer the [Docker release](docker-setup.md): fixed application/runtime versions, no host OpenClaw/OpenShell installation. This page documents the existing **host/development** installation.

Use this path for an Ubuntu GPU machine with Docker and an Ollama, vLLM or other OpenAI-compatible model server. The app and OpenClaw run on the host; only the model server and optional OpenShell sandboxes need containers. You do not need the Spark-specific managed model installation.

## 1. Prepare the account and code

Run as your normal user account. Ubuntu 22.04/24.04 on x86-64 or ARM64 supplies the required Python 3.9+. Install these host packages once:

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv curl ca-certificates openssh-client poppler-utils

# Run from the example directory containing bac.
./bac dev doctor
```

`poppler-utils` is for PDF uploads. No system Node, npm project install, Python requirements file or vLLM install is needed for the existing-model path. Setup downloads app-managed Node/OpenClaw from their official package sources; it needs internet access.

Keep the default data directory, `~/.local/share/bac-demo`, unless you need another disk. If changing it, export `BAC_DATA_DIR` to a dedicated directory outside the checkout **before setup**, and use that value in every terminal. Copy source, not the old computer's native runtime, sandboxes or workspace database with its absolute paths.

## 2. Install and start

For a clean Git checkout and a systemd user session:

```bash
./bac dev setup
./bac dev start --model external
```

Setup installs private pinned Node/OpenClaw. `external` leaves existing model servers alone and does not start a previously selected managed model. Nothing downloads GPU model weights or changes Docker/the NVIDIA driver. Repeating start reuses healthy services.

For copied or edited source, or a machine without a systemd user session:

```bash
./bac dev setup
./bac dev preview
```

Keep that terminal open. Connect in Settings to start the installed OpenClaw gateway. `./bac dev preview` builds the frontend automatically. Do not run both app modes on port 8080. Managed deployment uses committed Git snapshots and intentionally refuses an uncommitted checkout; the foreground path runs the files you copied or edited.

For managed services to survive logout/reboot, enable lingering once:

```bash
sudo loginctl enable-linger "$USER"
```

This applies to the app's user services, not the lifecycle of an independently installed model server.

## 3. Connect the existing model

For the project's Qwen3.6 NVFP4 vLLM launch example and the recommended `enable_thinking` setting, see [Qwen3.6 with vLLM](qwen3-vllm.md).

Open **http://localhost:8080 → Settings → Model → Local → Configure**.

| Server on the Ubuntu host | API endpoint | Model ID | API key |
| --- | --- | --- | --- |
| Ollama | `http://127.0.0.1:11434/v1` | Search and choose an installed model | Leave blank for standard local Ollama |
| vLLM / another compatible server | `http://127.0.0.1:8000/v1` (use its actual port) | Choose its served model ID | Blank unless your server requires one |
| Another machine on the private network | `http://192.168.1.50:8000/v1` (example) | Choose its served model ID | As configured on that server |

Search the **Model** field, select a text model with working tool calling, then **Connect & enable**. Under **Models**, select Local for **Open Task**. Hired agents default to connected Local, otherwise the configured External Endpoint model, and can choose another model in Hiring or Edit agent. Local endpoints accept localhost or a private IP; arbitrary DNS names are not currently supported. Local/private HTTP requests bypass environment proxy settings. Hosted providers keep their normal proxy behavior.

With Ollama running in Docker, publish its API to the host's loopback interface, for example `-p 127.0.0.1:11434:11434`. The app's `127.0.0.1` refers to Ubuntu, not your laptop or the container. GPU access belongs to the model container; verify it using the [official Ollama Docker instructions](https://docs.ollama.com/docker) and `ollama ps` (inside the container if applicable). The app does not install the NVIDIA Container Toolkit.

**Context must match on both sides.** The app defaults to 32,768 tokens. Its Context limit describes the server's capacity; it does not configure Ollama's `num_ctx`. Configure the model server for the app’s context. Open **Settings → Model → Configure → Advanced → Context limit** to inspect or change the application value; see [context and output budgets](runtime-settings.md#context-and-output-budgets). Ollama supports a model-specific `Modelfile` with `PARAMETER num_ctx 32768`; see [Ollama's OpenAI compatibility guide](https://docs.ollama.com/api/openai-compatibility#setting-the-local-context-size). The [upstream request conversion](https://github.com/ollama/ollama/blob/main/openai/openai.go) maps output-token limits separately from context. A model that lists successfully can still lack reliable tool calling or enough GPU memory for concurrent work.

API keys, when used, remain in memory and require reconnecting after tab refresh/closure or app restart. A local endpoint without a key has no credential to re-enter; its saved endpoint/model remain usable while the model server and agent gateway are reachable.

### Access from a laptop

For a Docker installation on a separate Ubuntu machine, open an SSH tunnel from your laptop.

```bash
ssh -N -L 8080:127.0.0.1:8080 USER@UBUNTU_HOST
```

Open **http://localhost:8080** on the laptop. Keep the model URL pointing to the Ubuntu host's loopback address. Only port 8080 needs forwarding because the app contacts the model internally.

## OpenShell for protected personal agents

The Docker installation includes OpenShell. For this host-development setup, configure it before running a protected personal agent.

When OpenShell is configured, opening the studio prepares the team’s standby Shell workspace in the background. This warms the shared image cache without a model call. Shell uses the same workspace when assigned and verifies its live policy before starting research. Each team keeps its own website approvals.

For protected agents, Docker Engine **28+** must work under the same normal account (`docker version` and `docker info`). Docker being installed alone does not guarantee account access. A group change requires signing out and signing in again. Follow the [official installation prerequisites](https://docs.nvidia.com/openshell/latest/about/installation).

The app pins OpenShell **0.1.4** for the CLI, gateway, supervisor and sandbox runtime. For a fresh Ubuntu development account:

```bash
openshell_installer=$(mktemp)
curl -fLsS https://raw.githubusercontent.com/NVIDIA/OpenShell/v0.1.4/install.sh -o "$openshell_installer"
OPENSHELL_VERSION=v0.1.4 sh "$openshell_installer"
rm "$openshell_installer"
openshell status

./bac dev openshell enable
./bac dev runtime preflight --protected
```

The [pinned official installer](https://github.com/NVIDIA/OpenShell/blob/v0.1.4/install.sh) installs the Debian CLI/gateway packages, requests OS privileges as needed, and starts/registers the user gateway. Run it as the normal account, not through `sudo ./bac`. Do not use the old `openshell gateway create` workflow or assume the Python SDK installs the CLI. This host installation is kept explicit rather than hidden inside another app script.

`enable` installs a checksum-verified app-private CLI when the system CLI differs, requires the selected gateway to match the pinned version, and configures the pinned OpenClaw sandbox integration. It does not replace or restart an unrelated shared gateway. Preflight gives a remedy for each failed check; it does not claim that a protected model task ran. OpenShell uses host tools and networking for personal-agent tasks; the model continues to run on your existing endpoint. Approval of a website does not fix that website's own rate limits or outages.

## 4. Rehearse and operate

Before presenting, verify one chat reply, one skill/tool call, then one complete Open Task journey with the chosen model. If protection is enabled, ask an OpenShell-on agent to read its `IDENTITY.md`, inspect Policies, and exercise an approve/revoke cycle. These are needed even when every infrastructure check passes.

```bash
./bac dev status
./bac dev runtime preflight
./bac dev app logs
./bac dev runtime logs
```

Managed app/runtime logs use the systemd journal. Foreground app logs are in its terminal; an OpenClaw gateway launched without systemd logs to `$BAC_DATA_DIR/openclaw/gateway.log` (default `~/.local/share/bac-demo/openclaw/gateway.log`).

| Symptom | Check / action |
| --- | --- |
| Cannot reach the model | On Ubuntu, check `curl http://127.0.0.1:11434/v1/models` (adjust port). Check container publishing/server startup. |
| Models list, but tasks fail | Verify tool calling, context settings, server logs and available GPU memory. Model discovery is not an inference test. |
| Port 8080 already used | Stop the other app instance, or choose `--port 8081` and adjust the SSH tunnel. |
| No systemd user session | Sign in as the normal user via SSH, or use the foreground path. |
| OpenShell preparation fails | Run `openshell status`, `docker info`, then protected preflight; follow its failed check's remedy. |
| Changed source is not visible | Foreground: rebuild/restart with `./bac dev preview`. Managed: commit intended changes and deploy with `./bac dev update`. |

For a managed Git deployment, `./bac dev update` updates only the app, and `./bac dev rollback` restores its previous code snapshot. Finish pending work first. For copied source, replace the source and restart the foreground app. Saved data remains outside the source folder in both cases. Do not run Reset to apply code changes.

For optional **DGX Spark ARM64 managed NVFP4 models**, use the separate [Spark guide](spark-operations.md). Those profiles are not a generic Ubuntu GPU requirement.
