<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Configuration

The recipe reads its settings from a `.env` file in the recipe directory.
Every setting has a default, so the scripts also run without that file.
[`.env.example`](../.env.example) and [`scripts/_lib.sh`](../scripts/_lib.sh)
are the source of truth for the names and defaults on this page.

```bash
cp .env.example .env
```

Git ignores `.env`. The recipe uses no API key and no secret.

## Settings

| Setting | Default | Meaning |
| --- | --- | --- |
| `SANDBOX_NAME` | `local-only-workspace-assistant` | Name of the sandbox that setup creates and teardown deletes |
| `WORKSPACE_DIR` | `./fixtures/workspace` | Host folder that setup copies to `/sandbox/workspace`. A relative path is relative to the recipe directory |
| `WORKSPACE_MAX_FILE_BYTES` | `1048576` | Largest file that the copy filter accepts |
| `INFERENCE_MODEL` | `nemotron-3-nano:4b-q4_K_M` | Ollama model that the recipe downloads and serves |
| `INFERENCE_PROVIDER_NAME` | `local-only-ollama` | Name of the OpenShell provider that setup creates |
| `INFERENCE_DEVICE` | `auto` | `auto`, `gpu`, or `cpu`. See [Device](#device) |
| `OLLAMA_PUBLISH_HOST` | `127.0.0.1` | Host address where Docker publishes the Ollama port |
| `OLLAMA_PORT` | `11434` | Host port for the Ollama server |
| `INFERENCE_BASE_URL` | `http://127.0.0.1:11434/v1` | Address that the OpenShell gateway calls for inference |
| `LOCAL_ENDPOINT_EXTRA_HOSTS` | empty | Comma-separated hosts that setup also accepts as local |
| `ALLOW_MISSING_LANDLOCK` | `0` | Set to `1` to continue on a Linux kernel that does not list Landlock |

The Compose file reads two more variables. Most runs do not need them.

| Setting | Default | Meaning |
| --- | --- | --- |
| `OLLAMA_IMAGE` | `ollama/ollama` 0.32.3, pinned by digest | Container image of the model server |
| `OLLAMA_KEEP_ALIVE` | `5m` | How long Ollama keeps an idle model in memory |

## Checks On Settings

Setup checks three settings before it starts anything. Each check stops setup
when it fails.

| Setting | Rule | Reason |
| --- | --- | --- |
| `INFERENCE_BASE_URL` | The host must be a loopback address, `localhost`, `host.docker.internal`, `host.openshell.internal`, or a host in `LOCAL_ENDPOINT_EXTRA_HOSTS` | The gateway sends prompts to this address. The sandbox policy does not apply to the gateway |
| `OLLAMA_PUBLISH_HOST` | Must be one IP address, and not `0.0.0.0` or `::` | Those two addresses publish the model server on every network interface |
| `WORKSPACE_DIR` | Must hold only regular files and folders, at most 200 files, each within the size limit | A link or a special file could bring other host content into the sandbox |

The address check reads the text of the address. It does not resolve names.
The check also rejects an address that only looks local, such as
`http://127.0.0.1.example.com` or `http://localhost@example.com`.

## Model

The default model is NVIDIA Nemotron 3 Nano 4B, from the Ollama library, under
the NVIDIA Open Model License Agreement.

| Property | Value |
| --- | --- |
| Ollama tag | `nemotron-3-nano:4b-q4_K_M` |
| Download size | 2.8 GB |
| Capabilities | Completion, tools, thinking |
| Minimum Ollama version | 0.17.1 |

To use another model, set `INFERENCE_MODEL` to its Ollama tag and run setup
again. Choose a model with the tools capability, because an agent calls tools.
Review the license of the model first.

[README, Default Model](../README.md#default-model) records the one check of
the model that has run.

## Device

`INFERENCE_DEVICE` selects where the model runs.

| Value | Behavior |
| --- | --- |
| `auto` | Use the NVIDIA GPU when `nvidia-smi -L` finds one. Use the CPU otherwise |
| `gpu` | Use the NVIDIA GPU. Stop when `nvidia-smi -L` finds none |
| `cpu` | Use the CPU |

For a GPU, setup adds `docker-compose.gpu.yml`, which holds the NVIDIA device
reservation. Docker needs the NVIDIA Container Toolkit for that reservation.
The sandbox boundary tests do not need a GPU.

## Addresses

By default, Docker publishes the Ollama port on host loopback, and the gateway
calls host loopback. No other machine can reach the model server.

A gateway that runs in a container cannot reach host loopback. In that case,
set these three settings to the address of a Docker bridge on the same
machine:

```bash
OLLAMA_PUBLISH_HOST=<bridge-address>
INFERENCE_BASE_URL=http://<bridge-address>:11434/v1
LOCAL_ENDPOINT_EXTRA_HOSTS=<bridge-address>
```

Nobody has tested this layout.

## Files

```text
local-only-workspace-assistant/
├── README.md                  Entry point, steps, and limitations
├── .env.example               Settings and defaults
├── Dockerfile                 Sandbox image: published OpenClaw image plus the canary file
├── docker-compose.yml         Recipe-owned Ollama server
├── docker-compose.gpu.yml     NVIDIA GPU reservation
├── policies/
│   └── local-only.yaml        Sandbox policy
├── scripts/
│   ├── bring-up.sh            Setup
│   ├── verify.sh              Static checks, or the live test suite with --live
│   ├── teardown.sh            Cleanup
│   └── _lib.sh                Shared helpers and defaults
├── src/
│   ├── SKILL.md               The workspace-assistant skill
│   ├── localonly/             Host-side checks and the test suite
│   └── tests/                 Unit tests
├── fixtures/
│   ├── workspace/             Sample approved folder
│   └── image/                 Canary file for the sandbox image
└── docs/                      These pages and their images
```

## State

The recipe keeps its state in the `.run` directory, which Git ignores.

| State | Location | Removed by |
| --- | --- | --- |
| Record of the resources that setup created | `.run/created` | Teardown removes each entry as it removes the resource |
| List of files to copy | `.run/workspace-files.tsv` | Not removed. Setup writes it again on each run |
| Inference route before setup | `.run/previous-inference-route.txt` | Not removed |
| Evidence records | `.run/evidence/` | Not removed |
| Sandbox creation log | `.run/sandbox-create.log` | Not removed |
| Downloaded models | Docker volume `local-only-workspace-assistant-ollama-models` | `scripts/teardown.sh --purge-models` |
| Copy of the approved folder | `/sandbox/workspace` in the sandbox | Teardown, when it deletes the sandbox |

Setup and teardown act only on resources that `.run/created` lists. If that
file is lost, remove the sandbox, the provider, and the container by hand.

## Commands Of The `localonly` Package

Run these from the recipe directory with `PYTHONPATH=src`.

| Command | Purpose |
| --- | --- |
| `python3 -m localonly check-policy <file>` | Check that a policy file is local-only |
| `python3 -m localonly check-effective-policy` | Check sandbox policy JSON from standard input |
| `python3 -m localonly check-endpoint <address>` | Check that an inference address is local |
| `python3 -m localonly check-publish-host <address>` | Check a publish address |
| `python3 -m localonly list-workspace <folder>` | List the files that setup would copy |
| `python3 -m localonly cases` | Print the test case table |
| `python3 -m localonly run --sandbox <name>` | Run the test cases against a running sandbox |

The package uses only the Python standard library.
