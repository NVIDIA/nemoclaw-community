# DGX Spark: install once, start with one command

For a new Spark with an existing model endpoint, use the [Docker release](docker-setup.md). The model stays on the host; this guide is the optional host-managed model workflow.

Already have Ollama or another OpenAI-compatible server? Use the [Ubuntu existing-model guide](ubuntu-setup.md); these managed NVFP4 profiles are optional and target Spark ARM64.

The normal path uses the existing `bac` entry point. You do not need separate shell scripts, manual virtualenv activation or one model server per agent.

## 1. Prepare the host

Use a normal Linux account with the Spark driver installed and a working systemd user session. Do not run `./bac` with sudo.

```bash
sudo apt-get update
sudo apt-get install -y git python3 python3-venv curl ca-certificates openssh-client poppler-utils

# Run from the example directory containing bac.
./bac dev doctor
```

`doctor` reports available tools and the next setup step. `poppler-utils` supports PDF uploads. For services to survive logout and start after reboot, enable lingering once, subject to your host’s policy:

```bash
sudo loginctl enable-linger "$USER"
```

Choose `BAC_DATA_DIR` before setup if you need another disk. The default is `~/.local/share/bac-demo`; use a dedicated directory outside the checkout and the same setting for all commands. Do not copy the Mac’s native runtime, sandbox state or absolute workspace paths onto Spark.

## 2. Install and start

With a managed local model:

```bash
./bac dev setup --model qwen
./bac dev start --model qwen
```

Use `gemma` in both commands for the alternative profile. Setup installs the pinned app-managed Node/OpenClaw runtime, creates the private vLLM environment, checks the NVFP4 kernels and downloads pinned weights. Repeating setup reuses matching installations. It does not modify system Python or install Docker/drivers.

Start verifies the checkout/app port, starts the model, waits for its endpoint, starts OpenClaw and then starts the app. Healthy running services are reused. The model wait is bounded to 10 minutes and reports progress; use `--wait 1200` for a longer cold compile. A failed model service exits early with the log command. A timeout leaves the service running, so inspect logs and rerun start when ready. Start never downloads weights.

If a compatible model server already exists, or you use a hosted API:

```bash
./bac dev setup
./bac dev start --model external
```

No managed model is downloaded. If a model was previously started with `bac`, plain `start` reuses that selection. `--model external` skips that selection without stopping existing servers. If no longer needed, stop the managed model explicitly with `./bac dev llm stop`. Continue using `--model external` for subsequent external-endpoint starts.

## 3. Open and connect

From a laptop:

```bash
ssh -N -L 8080:127.0.0.1:8080 USER@SPARK
```

Open **http://localhost:8080 → Settings → Model**. For the managed model choose **Local → Configure**, endpoint `http://127.0.0.1:8000/v1`, model `bac-local`, then **Connect & enable**. Under **Models**, select Local for **Open Task**. Hired agents default to connected Local, otherwise the configured External Endpoint model; their model can be changed in Hiring or Edit agent.

`./bac dev preview` is the foreground development/preview alternative, not another required setup step. Stop it before starting a managed app on the same port. `./bac dev start --port 8081` uses another app port; adjust the tunnel. `--host 0.0.0.0` exposes both Studio and Settings to a trusted workshop LAN; an SSH tunnel remains an optional private access path. Model and agent gateways still bind to loopback.

## Daily use

| Task | Command |
| --- | --- |
| Start/reuse installed services | `./bac dev start` |
| Inspect services and data location | `./bac dev status` |
| Update the app, keep the model installation | `./bac dev update` |
| Restore the previous app release | `./bac dev rollback` |
| Diagnose model startup | `./bac dev llm logs` / `./bac dev llm check --wait 120` |
| Diagnose OpenClaw | `./bac dev runtime logs` / `./bac dev runtime check --wait 30` |
| Diagnose the app | `./bac dev app logs` |
| Stop one service | `./bac dev app stop`, `./bac dev runtime stop`, `./bac dev llm stop` |

Finish or stop pending missions and policy updates before updates, rollback or service changes. A repeated healthy start preserves current connections. An actual app restart expires browser-entered API credentials; reconnect in Settings unless a host-saved NVIDIA key supplies the connection. Update does not install packages or warm/restart the model. A dirty or diverged checkout is rejected without discarding changes. Release snapshots include only committed source, so commit intended changes before deploying.

## Optional OpenShell protection

For the pinned installer command and first-run steps, see [Ubuntu OpenShell setup](ubuntu-setup.md#openshell-for-protected-personal-agents). Install the host prerequisites from [OpenShell installation](https://docs.nvidia.com/openshell/latest/about/installation) and the [Spark OpenShell playbook](https://build.nvidia.com/spark/openshell). For this app’s Ubuntu Docker path, Docker Engine 28+ must be reachable by the normal account; OpenShell’s CLI/gateway and SSH must work from that same account. Docker group changes may require signing out and signing in again.

```bash
./bac dev openshell enable
./bac dev runtime preflight --protected
```

These are infrastructure checks. They do not prove a protected LLM task completed. The app never silently switches a protected agent to unprotected mode.

### Before presenting on Spark

On the actual Spark, rehearse these once before attendees arrive:

1. Get a real reply from an OpenShell-off personal agent.
2. Ask an OpenShell-on agent to read `IDENTITY.md`. Inspect its actual sandbox and loaded policy.
3. Run `./bac dev openshell prove` for independent deny → allow → deny network evidence.
4. Run a complete Open Task `/goal` journey with Casey. Inspect the selected hires/backups, saved handoffs, generated artifacts, independent review when requested, and final response.
5. Restart/reboot, reconnect as needed, and repeat the protected file read.

## What is pinned, and what remains unverified

[runtime/profiles.json](../runtime/profiles.json) is the model configuration source of truth. It records Python 3.13, vLLM 0.28.0, FlashInfer 0.6.16.post3, a CUTLASS lower bound, model revisions, launch arguments and the Gemma template checksum. The installation follows the supplied Build-a-Claw model guide. The [vLLM kernel checks](https://github.com/vllm-project/vllm/blob/v0.28.0/vllm/utils/flashinfer.py) and [Gemma template](https://github.com/vllm-project/vllm/blob/v0.28.0/examples/tool_chat_template_gemma4.jinja) are checked against the pinned upstream tag.

The full resolved dependency list is recorded in `runtime/resolved-requirements.txt` on the host. This is not a complete cross-machine lockfile. Both profiles use the `bac-local` alias on port 8000; only one managed model runs at once. Existing unrelated servers are never killed to free that port.

Allow time on your Spark for the first model download and kernel compilation. Check memory use and run a protected task with the model you plan to demonstrate.

## Data and removal

```text
~/.local/share/bac-demo/
  openclaw/                   Private Node, OpenClaw and native agent state
  runtime/vllm-env/           Shared serving environment
  models/qwen/, models/gemma/ Pinned weights and installed profiles
  cache/                     Download/kernel caches
  llm.json                   Last managed model and endpoint
  studio/                    SQLite, agent workspaces and saved files
  demo/releases/             Immutable app snapshots
  demo/current, demo/previous Release links
```

`./bac dev llm remove qwen` previews a model-scoped removal; add `--yes` to apply it. `./bac dev llm remove-runtime --yes` removes the private vLLM environment while preserving weights. No command removes the global Hugging Face cache or host drivers. App rollback changes code, not the database. Release snapshots are retained; there is no automatic pruning.
