<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Local-Only Workspace Assistant

| Catalog field | Value |
| --- | --- |
| Description | Answers questions about a copy of one approved folder with a local NVIDIA Nemotron model on Ollama, and tests the sandbox with denied actions: file escapes, Windows drive access under WSL2, egress, and remote inference. Setup does not complete yet; only static checks pass. |
| Industry | ✨ Other |
| Requirements | Linux or Windows 11 with WSL2 · Docker Compose · OpenShell · about 3 GB model download · NVIDIA GPU with NVIDIA Container Toolkit for GPU serving, CPU otherwise · static checks only so far |
| NemoClaw | N/A |
| Harness | OpenClaw Unknown |
| OpenShell | Unpinned |

Local-Only Workspace Assistant is a community recipe for a person who wants an
agent to read one folder of files on their own machine without sending file
contents or prompts to a remote service. The recipe runs an OpenClaw sandbox
whose only network route is the OpenShell inference route, and it points that
route at an Ollama server on the same machine. By default that server runs
NVIDIA Nemotron 3 Nano 4B. The recipe is designed for a GeForce RTX PC with
Windows Subsystem for Linux 2 (WSL2). The same scripts run on a Linux host, with or without an NVIDIA GPU.

The recipe also includes a denied-action test suite. The suite runs allowed and
denied actions inside the running sandbox and records a verdict for each one.
No test depends on model output.

**Status:** this recipe is a first increment and setup does not complete yet.
The static checks pass. Setup stages 1 to 4 ran on macOS with Docker Desktop.
Setup stops at stage 5 with OpenShell 0.1.8, because the scripts use commands
from earlier OpenShell versions. Nobody has created the sandbox or run the
live test suite. Read [Known Limitations](#known-limitations) before you rely
on any behavior that this document describes.

## Screenshot

![Terminal output of the static checks: 71 unit tests pass, the policy file permits egress only to inference.local, both addresses are local, and the last line reports PASS with 0 skipped](docs/images/static-checks.png)

The image shows the output of `bash scripts/verify.sh`, the static checks.
Notice the three `OK` lines: the policy file permits egress only to
`inference.local`, the model server is published on loopback, and the
inference endpoint is local. [Static Checks](#static-checks) has the same
output as text.

This is the only complete result that the recipe produces today. The image
does not show a sandbox or an agent, because setup does not reach that stage
yet. [Status And Planned Work](docs/status.md) shows the setup run that stops
at stage 5.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | Community Recipe |
| Contributor or provenance | Independent community contribution with no organizational provenance |
| Use this when | You want an agent to answer questions about local files, and prompts and file contents must stay on one machine |
| You will get | A dedicated sandbox with a copy of one approved folder, a local inference route, and a JSON Lines record of each allowed and denied action |
| Runs on | Designed for Windows 11 with WSL2 and an NVIDIA GeForce RTX GPU. A Linux host uses the same scripts. Without an NVIDIA GPU, the model runs on the CPU |
| Requires | Docker with Compose, OpenShell with a running gateway, Python 3.10 or newer, and about 3 GB of disk space for the default model. GPU serving also requires the NVIDIA Container Toolkit. No API key |
| Verified on | Static checks: macOS with Python 3.9.6 and Python 3.12.16. Setup stages 1 to 4 only: macOS with Docker Desktop 29.9.3 and CPU inference. Stage 5 and later are not verified |
| Evidence level | local/static |
| Support and maturity | Best-effort community support. See the [support policy](../../../../SUPPORT.md) |
| External access, data, and actions | Setup downloads two container images and one model. Setup changes the inference route of the OpenShell gateway. The sandbox policy permits no external destination |
| Start here | [Quickstart](#quickstart) |
| Confirm success | [Verification](#verification) |

## Documentation

This README has the steps, the architecture, and the limits. The
[`docs/`](docs/README.md) folder explains the recipe at more length.

| Page | Read it to learn |
| --- | --- |
| [Overview](docs/overview.md) | What the recipe is, who it is for, what you get, and what it does not do |
| [How It Works](docs/how-it-works.md) | The components, the three controls, and what happens during setup, a request, and teardown |
| [Test Suite](docs/test-suite.md) | How the tests decide a verdict, what they record, and how to add a case or a backend |
| [Configuration](docs/configuration.md) | Every setting, the default model, the files, and the state that the recipe keeps |
| [Status And Planned Work](docs/status.md) | What has run, what fails today, and what comes next |

## Architecture

This section describes the design. No live run has confirmed the behavior of
the sandbox or the gateway yet. The inference route and the provider steps
follow the command set of OpenShell 0.0.85 and 0.0.106. OpenShell 0.1.8
replaces those commands, so these steps will change.
[Known Limitations](#known-limitations) lists what is unverified.

### Components And Trust Zones

The sandbox is the untrusted zone. Everything else on the host is trusted,
including the operator, the scripts, Docker, and the OpenShell gateway.

```mermaid
flowchart LR
    subgraph host ["Host: Linux or WSL2, trusted"]
        operator["Operator shell<br/>setup, verify, teardown scripts"]
        checks["localonly<br/>host-side checks<br/>and test runner"]
        folder["Approved folder<br/>WORKSPACE_DIR"]
        rundir["State directory .run<br/>created resources,<br/>evidence, logs"]
        hostfiles["Other host files<br/>and Windows drives"]
        subgraph docker ["Docker"]
            ollama["Ollama container<br/>owned by the recipe<br/>published on loopback"]
            models[("Model volume")]
        end
        subgraph openshell ["OpenShell"]
            gateway["Gateway<br/>inference route,<br/>sandbox lifecycle, policy"]
            subgraph sandbox ["Sandbox: untrusted zone"]
                agent["OpenClaw agent<br/>workspace-assistant skill"]
                copy["/sandbox/workspace<br/>copy of the approved folder"]
            end
        end
    end
    remote["Remote hosts and<br/>remote inference services"]

    operator --> checks
    folder --> checks
    checks -->|"filtered copy"| copy
    operator -->|"provider, route,<br/>sandbox, policy"| gateway
    agent -->|"reads"| copy
    agent -->|"inference.local"| gateway
    gateway -->|"local endpoint"| ollama
    ollama --- models
    checks -->|"test verdicts"| rundir
    agent -.->|"denied"| remote
    agent -.->|"denied"| hostfiles
```

| Component | Runs in | Responsibility | Source |
| --- | --- | --- | --- |
| Setup, verify, and teardown scripts | Host shell | Order the stages, stop at the first failed check, and record each resource that setup creates | `scripts/` |
| `localonly` host-side checks | Host, Python standard library | Check the policy file, the endpoint address, the publish address, the approved folder, and the effective sandbox policy | `src/localonly/endpoint.py`, `policy_facts.py`, `workspace.py` |
| `localonly` test suite | Host, Python standard library | Run each case in the sandbox, decide a verdict, and write evidence | `src/localonly/cases.py`, `runner.py`, `backends.py`, `evidence.py` |
| Ollama server | Docker container that the recipe owns | Serve one model through an OpenAI-compatible API on one host address | `docker-compose.yml`, `docker-compose.gpu.yml` |
| OpenShell gateway | Host, as a service or a container | Hold the inference route, create the sandbox, and apply the policy | Not part of this recipe |
| Sandbox | OpenShell | Run the agent under the local-only policy | `Dockerfile`, `policies/local-only.yaml` |
| Agent and skill | Sandbox | Answer questions from `/sandbox/workspace` | `src/SKILL.md` |

### Enforcement Points

Three controls keep data on the machine. None of them runs inside the model or
the agent process.

1. **Sandbox policy.** [`policies/local-only.yaml`](policies/local-only.yaml)
   lists one egress endpoint, `inference.local`, and a short filesystem
   allowlist. OpenShell enforces the policy. The recipe adds no permission
   check of its own inside the sandbox.
2. **Local inference endpoint.** The OpenShell gateway sends prompts to the
   inference endpoint. The sandbox policy does not apply to the gateway, so
   setup rejects an endpoint address that does not point at this machine
   before it registers the address.
3. **Copy, not mount.** Setup copies the approved folder into the sandbox. It
   never mounts a host folder. The copy filter rejects a symbolic link, a
   special file, or a file larger than the limit.

The table maps each unwanted event to its control and to the test that is
designed to detect a failure of that control.

| Unwanted event | Control | Enforced by | Detected by |
| --- | --- | --- | --- |
| The agent reads a host file outside the copied folder | Filesystem allowlist. The host folder is never mounted | OpenShell | S02, S03, S04 |
| The agent starts a Windows program or gains privileges | Filesystem allowlist and the sandbox user | OpenShell | S04b, S05 |
| The agent writes to a system path | Read-only paths in the filesystem allowlist, and file permissions in the image | OpenShell and the sandbox image | S05b |
| The agent sends data to a remote host | Egress policy with one endpoint | OpenShell | S06, S06b, S06c |
| The agent calls a remote inference service directly | Egress policy with one endpoint | OpenShell | S09 |
| The gateway sends prompts to a remote inference service | Endpoint address check before setup registers the endpoint | Setup script | Unit tests in `test_endpoint.py` |
| Inference moves to another service when the local server stops | One provider and no second route | OpenShell gateway | S08 |
| Another machine reaches the inference server | Publish address check. The default is loopback | Setup script and Docker | Unit tests in `test_endpoint.py` and `test_policy.py` |
| Setup copies host content from outside the approved folder | Copy filter | Setup script | Unit tests in `test_workspace.py` |
| The running policy differs from the policy file | Setup and verification read the effective policy back and check it | Setup and verify scripts | Unit tests in `test_policy.py` |
| The evidence file exposes file contents | A record holds the verdict and never the command output | `evidence.py` | Unit tests in `test_runner.py` |

The design does not protect these items:

- **The copied folder.** The agent can read every copied file and can send
  its contents to the local model. Approve only a folder that the agent may
  read in full.
- **The copy inside the sandbox.** The agent can change or delete its copy.
  The host folder is not affected.
- **Other sandboxes on the same gateway.** They share the inference route, so
  their prompts also go to the local model while this recipe is set up.
- **The host.** A person or process with access to the host can read the
  approved folder, the model, and the evidence files.

### Setup Sequence

`scripts/bring-up.sh` checks its inputs and the host prerequisites before it
starts a service, downloads anything, or changes the gateway. It stops at the
first step that fails.

```mermaid
sequenceDiagram
    participant Op as Operator
    participant Up as bring-up.sh
    participant Ck as localonly checks
    participant Dk as Docker and Ollama
    participant Gw as OpenShell gateway
    participant Sb as Sandbox

    Op->>Up: bash scripts/bring-up.sh
    Up->>Gw: check that the gateway is reachable
    Up->>Ck: check policy file, publish address,<br/>endpoint address, approved folder
    Ck-->>Up: accepted, or setup stops
    Up->>Up: select GPU or CPU, check Landlock
    Up->>Dk: start the Ollama container
    Up->>Dk: download the model if it is missing
    Up->>Gw: create the provider for the local endpoint
    Up->>Gw: set the inference route
    Gw->>Dk: verify the route with a request
    Up->>Gw: create the sandbox from the Dockerfile and the policy
    Gw->>Sb: start
    Up->>Gw: set the policy, then read it back
    Up->>Ck: check the effective policy
    Ck-->>Up: only inference.local, or setup stops
    Up->>Sb: copy the approved files and the skill
    Up-->>Op: Bring-up complete
```

### Request Flows

The diagram shows the three flows that the test suite exercises: an allowed
inference request, a denied request to another host, and an inference request
while the local server is stopped.

```mermaid
sequenceDiagram
    participant Ag as Agent in sandbox
    participant Pe as OpenShell policy enforcement
    participant Rt as inference.local route
    participant Ol as Local Ollama
    participant Rm as Remote host

    Note over Ag,Ol: Allowed - local inference, case S00
    Ag->>Pe: POST to inference.local, chat completion
    Pe->>Rt: permitted by the egress policy
    Rt->>Ol: forward to the registered local endpoint
    Ol-->>Rt: completion
    Rt-->>Ag: completion

    Note over Ag,Rm: Denied - any other destination, cases S06 and S09
    Ag->>Pe: request to a remote host
    Pe--xRm: not forwarded
    Pe-->>Ag: denied, HTTP status 403 expected

    Note over Ag,Ol: Local server stopped, case S08
    Ag->>Pe: POST to inference.local, chat completion
    Pe->>Rt: permitted by the egress policy
    Rt--xOl: endpoint does not answer
    Rt-->>Ag: explicit error, no second route
```

### Test Suite Design

The suite separates what to test from how to reach the sandbox. A case is a
shell script and an expected result, and it names no sandbox technology. A
backend runs the script and returns the output and the exit status. The recipe
includes one backend, for OpenShell. A backend for a different sandbox
technology, such as a native Windows sandbox, can run the same case table.

```mermaid
flowchart LR
    cases["cases.py<br/>actions and<br/>expected results"]
    runner["runner.py<br/>runs each case and<br/>decides the verdict"]
    iface{{"Backend interface<br/>run a script, return<br/>output and exit status"}}
    osb["OpenShellBackend<br/>openshell sandbox exec"]
    other["Another backend<br/>not implemented"]
    target["Running sandbox"]
    actions["Host actions<br/>stop and start the<br/>inference server"]
    records["evidence.py<br/>JSON Lines records<br/>without command output"]

    cases --> runner
    runner --> iface
    iface --> osb
    iface -.-> other
    osb --> target
    runner --> actions
    runner --> records
```

The runner checks these rules in order and reports the first verdict that
applies. A denied case passes only when the output carries a boundary
signature, such as `Permission denied` or HTTP status 403.

| Order | Condition | Verdict |
| --- | --- | --- |
| 1 | The case is planned and has no script | `PLANNED` |
| 2 | The host lacks a trait that the case requires, such as WSL2 | `N/A` |
| 3 | The script did not run to completion in the sandbox, or a host action that the case needs failed | `INCONCLUSIVE` |
| 4 | Allowed case: exit status 0 and the expected content | `PASS` |
| 5 | Allowed case: any other result | `FAIL` |
| 6 | Denied case: the output holds protected content, or the exit status is 0 | `FAIL` |
| 7 | Denied case: the action failed with a boundary signature | `PASS` |
| 8 | Denied case: the action failed without a boundary signature | `INCONCLUSIVE` |

Rule 3 keeps a missing sandbox or a missing `openshell` command from counting
as a denial.

### State

| State | Location | Removed by |
| --- | --- | --- |
| Record of the resources that setup created | `.run/created` | Teardown removes each entry as it removes the resource |
| Inference route before setup | `.run/previous-inference-route.txt` | Not removed |
| Evidence records | `.run/evidence/`. Each file is readable only by its owner | Not removed |
| Sandbox creation log | `.run/sandbox-create.log` | Not removed |
| Downloaded model | Docker volume `local-only-workspace-assistant-ollama-models` | `scripts/teardown.sh --purge-models` |
| Copy of the approved folder | `/sandbox/workspace` in the sandbox | Teardown, when it deletes the sandbox |

Git ignores the `.run` directory.

### Design Decisions

| Decision | Reason | Cost |
| --- | --- | --- |
| OpenShell is the only boundary. The recipe adds no check inside the sandbox | A check that runs in the agent process can be changed by that process | The recipe depends on the OpenShell version and the host kernel |
| Copy the approved folder. Do not mount it | The sandbox holds no path to the host folder | The copy is out of date until setup runs again |
| The recipe owns its Ollama container and model volume | Teardown can remove what setup created without changing an existing Ollama installation | The model is downloaded again even when the host already has it |
| A denied case needs a boundary signature to pass | A missing file or an offline network also makes an action fail | A reworded denial message produces `INCONCLUSIVE` until the signature list is updated |
| The image holds a canary file that file permissions allow every user to read | Only the sandbox policy can deny the read, so a denial is meaningful | The recipe needs its own image layer |
| Test cases name no sandbox technology | A second backend can run the same table | Each case must be expressible as a shell script |
| Setup records what it creates | Setup and teardown do not change a sandbox, provider, or model that existed before | A lost `.run/created` file leaves resources that the operator must remove by hand |
| Python standard library only | The recipe adds no dependency to review | The policy check reads YAML with a line scanner that accepts only plain block style |

## Default Model

The recipe serves NVIDIA Nemotron 3 Nano 4B through Ollama by default.

| Property | Value | Source |
| --- | --- | --- |
| Ollama tag | `nemotron-3-nano:4b-q4_K_M` | `.env.example` |
| Parameters and quantization | 4.0 billion, Q4_K_M | `ollama show` |
| Download size | 2.8 GB | `ollama list` |
| Capabilities | Completion, tools, thinking | `ollama show` |
| Minimum Ollama version | 0.17.1. The recipe pins 0.32.3 | `ollama show` |
| License | NVIDIA Open Model License Agreement | `ollama show` |

One check of the model has run, outside the sandbox, against the recipe-owned
Ollama container on an Apple M1 with Docker Desktop and CPU inference:

- A chat request through the OpenAI-compatible endpoint returned a completion.
  The first request, which also loads the model, took 17 seconds.
- A request with one tool definition returned a call to that tool. It took
  25 seconds for 42 output tokens.
- The loaded model used 2.9 GB of the 3.8 GB that Docker gave the container,
  with a context length of 4096.

These numbers describe CPU inference in a virtual machine. They say nothing
about GPU serving. The check does not show that an agent in the sandbox can
use the model, because setup does not yet reach that stage.

To use another Ollama model, set `INFERENCE_MODEL` in `.env`. An agent needs a
model with the tools capability.

## What Setup Changes

Read this section before you run `scripts/bring-up.sh`.

- **Downloads.** Setup downloads the `ollama/ollama` container image, the
  NemoClaw OpenClaw sandbox image, and the model named by `INFERENCE_MODEL`.
  The default model, `nemotron-3-nano:4b-q4_K_M`, is about 2.8 GB. These
  downloads contact Docker Hub, the GitHub Container Registry, and
  `ollama.com`.
- **Gateway inference route.** The inference route belongs to the OpenShell
  gateway, not to one sandbox. Setup points it at the local Ollama server.
  Every sandbox on the same gateway then uses the local model. Setup saves the
  earlier route in `.run/previous-inference-route.txt`. Teardown prints it and
  does not restore it.
- **New resources.** Setup creates one sandbox, one OpenShell provider, one
  Ollama container, and one Docker volume for the model. Setup refuses to
  reuse a sandbox or provider that it did not create.
- **Costs and credentials.** The recipe uses no paid service, no API key, and
  no secret. OpenShell requires a credential for each provider, so setup
  registers a fixed placeholder value. Ollama does not check it.

## Quickstart

These eight steps take a Linux host or a WSL2 distribution from a fresh shell
to a recorded test result, and then clean up. Run every command in that shell.
Run the commands of steps 3 to 8 from this recipe's directory.

Steps 1 to 3 change nothing outside the clone. Step 5 downloads images and a
model and changes the OpenShell gateway. Nobody has completed steps 5 to 8 on
a live host yet. [If A Step Fails](#if-a-step-fails) lists the most likely
problems.

### Step 1: Check The Prerequisites

The host needs Docker with the Compose plugin, Python 3.10 or newer, and
OpenShell with a running local gateway. Each of these commands must succeed:

```bash
docker info >/dev/null && docker compose version
python3 --version
openshell --version
openshell status
```

If `openshell status` fails, the gateway is not running. On a host that runs
the gateway as a user service, inspect it with
`systemctl --user status openshell-gateway --no-pager`.

If OpenShell is not installed, install it with the OpenShell installer:

```bash
curl -LsSf https://raw.githubusercontent.com/NVIDIA/OpenShell/main/install.sh \
  | OPENSHELL_VERSION=v0.0.85 sh
```

The sandbox image in `Dockerfile` is the one that another example in this
repository pairs with OpenShell 0.0.85. Nobody has run this recipe with that
version. With OpenShell 0.1.8, setup stops at stage 5. See
[Known Limitations](#known-limitations).

For GPU serving, the host also needs an NVIDIA driver and the NVIDIA Container
Toolkit. This command must list the GPU:

```bash
nvidia-smi -L
```

Skip the GPU check on a host without an NVIDIA GPU. Setup then serves the
model from the CPU.

### Step 2: Get The Code

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/recipes/community/local-only-workspace-assistant
```

### Step 3: Run The Static Checks

```bash
bash scripts/verify.sh
```

The last line must start with
`PASS: local-only-workspace-assistant static verification`. This step starts
no service and contacts no external system.
[Static Checks](#static-checks) shows the full expected output.

### Step 4: Configure

```bash
cp .env.example .env
```

Every setting has a default, so the recipe runs with the copied file as it is.
Edit `.env` only for these cases:

| Setting | Change it when |
| --- | --- |
| `WORKSPACE_DIR` | You want the agent to read your own folder. The default is the sample folder `fixtures/workspace` |
| `INFERENCE_DEVICE` | You want setup to stop when it finds no GPU. Set `gpu`. The default, `auto`, uses the GPU when `nvidia-smi -L` finds one and the CPU otherwise |
| `INFERENCE_MODEL` | You want a different Ollama model. Review its license first |
| `SANDBOX_NAME`, `INFERENCE_PROVIDER_NAME` | A sandbox or provider with the default name already exists. Setup does not reuse one that it did not create |
| `OLLAMA_PUBLISH_HOST`, `INFERENCE_BASE_URL`, `LOCAL_ENDPOINT_EXTRA_HOSTS` | The OpenShell gateway runs in a container and cannot reach host loopback. Set all three to the address of a Docker bridge on this machine |

### Step 5: Run Setup

Read [What Setup Changes](#what-setup-changes) first. Then run:

```bash
bash scripts/bring-up.sh
```

Among its other output, setup prints one heading for each of its seven stages
and a final line:

```text
== 1/7 check inputs ==
== 2/7 select the inference device and check the kernel ==
== 3/7 start the recipe-owned inference server ==
== 4/7 make the model available ==
== 5/7 point the OpenShell inference route at the local server ==
== 6/7 create the dedicated sandbox ==
== 7/7 copy the approved folder and the skill ==
Bring-up complete.
```

The first run downloads the images and the model, and it can take several
minutes. Setup stops at the first stage that fails and prints the reason. On a
Linux host, stage 2 stops when the kernel does not list the Landlock security
module; `.env.example` documents the variable that lets setup continue.

After you correct a problem, run the same command again. Setup reuses the
resources that it already created. If setup reports that the sandbox exists in
a phase other than ready, run `bash scripts/teardown.sh` first.

### Step 6: Confirm The Inference Route

```bash
openshell inference get
```

The output must name the provider `local-only-ollama` and the model
`nemotron-3-nano:4b-q4_K_M`, or the values that you set in `.env`.

### Step 7: Run The Live Test Suite

```bash
bash scripts/verify.sh --live
```

The command prints one line for each test case and then a result line. The
last line must be `PASS: local-only-workspace-assistant live verification`.
The command writes the evidence file to `.run/evidence/`.
[Live Test Suite](#live-test-suite) explains each verdict and exit status.

On a host that is not WSL2, cases S04 and S04b show `N/A`. That is expected.

### Step 8: Clean Up

```bash
bash scripts/teardown.sh
```

Teardown prints the inference route that the gateway used before setup. If
other sandboxes on the gateway need that route, restore it:

```bash
openshell inference set --provider <previous-provider> --model <previous-model>
```

[Teardown](#teardown) describes what the command removes and what it keeps.

### If A Step Fails

| Symptom | Likely cause | What to do |
| --- | --- | --- |
| Step 5 stops in stage 3 with a Docker error about the `nvidia` device driver | Docker cannot use the GPU | Install or repair the NVIDIA Container Toolkit, or set `INFERENCE_DEVICE=cpu` |
| Step 5 stops in stage 5 with `provider profile 'openai' not found` | OpenShell 0.1.x is installed. It requires an imported provider profile and has no `inference` command | No fix exists in this recipe yet. See [Known Limitations](#known-limitations) |
| Step 5 stops in stage 5 with another error | The gateway cannot reach the Ollama server at `INFERENCE_BASE_URL` | Use the last row of the table in step 4 |
| Step 5 stops in stage 6 with "Sandbox did not become ready" | The policy allowlist is too narrow for the sandbox image, or the image and the installed OpenShell version do not match | Read `.run/sandbox-create.log` |
| Step 7 shows `FAIL` for S02 or S03 | The kernel does not enforce the filesystem policy | Check that `/sys/kernel/security/lsm` lists `landlock` |
| Step 7 shows `INCONCLUSIVE` for a denied case | The action failed, but not with text that the suite recognizes as a denial | Run the case by hand with `openshell sandbox exec` and compare the message |
| Step 7 shows `FAIL` or `INCONCLUSIVE` for S00 | The sandbox cannot use the inference route | Repeat step 6 |

These causes are estimates from reading the scripts. No live run has confirmed
them.

## What Each Host Can Prove

The recipe makes three separate claims. Each one needs a different host, and
only the last one needs Windows.

| Claim | Host that can test it | Cases |
| --- | --- | --- |
| The sandbox denies file escapes, egress, and remote inference, and inference fails with an explicit error when the local server stops | Any Linux host with Docker and OpenShell. No GPU | S00 to S03, S05 to S09 |
| An NVIDIA GPU serves the model | A Linux or WSL2 host with an NVIDIA GPU and the NVIDIA Container Toolkit | The model placement that `scripts/verify.sh --live` prints |
| The sandbox cannot reach Windows drives or start Windows programs | Windows 11 with WSL2. No GPU | S04, S04b |

A run on a host reports only what that host can test. On a Linux host that is
not WSL2, the suite reports S04 and S04b as `N/A`. It does not report them as
passed, because the Windows drive does not exist there.

## Verification

### Static Checks

**Evidence level:** local/static

```bash
bash scripts/verify.sh
```

**Expected result:**

```text
== 1/5 shell syntax ==
== 2/5 python syntax ==
== 3/5 unit tests ==
.......................................................................
----------------------------------------------------------------------
Ran 71 tests in 0.027s

OK
== 4/5 policy, endpoint, and approved folder ==
OK: policy file permits egress only to inference.local
OK: publish host: 127.0.0.1
OK: inference endpoint host is local: 127.0.0.1
== 5/5 compose rendering ==
PASS: local-only-workspace-assistant static verification (0 skipped)
```

On a machine without Docker Compose, step 5 prints a `SKIP` line and the last
line reports `1 skipped`.

**This verifies:** the policy file lists no egress host except
`inference.local` and no filesystem path outside its allowlist. The endpoint
check rejects remote URLs. The copy filter rejects links, parent references,
and oversized files. The suite never reports a pass when a script did not run
in the sandbox, and it never writes command output to the evidence file.

**This does not verify:** that OpenShell accepts or enforces the policy, that
the sandbox starts, that the GPU serves the model, or any other live behavior.

### Live Test Suite

**Evidence level:** not yet run. A complete run on the target hardware is
required before this recipe can claim `integration` or `live end-to-end`.

```bash
bash scripts/verify.sh --live
```

The command reads the effective sandbox policy, runs every ready case in the
table below, and shows where Ollama loaded the model. It stops the recipe-owned
Ollama container once and starts it again. It writes one JSON record for each
case to `.run/evidence/`.

A denied case passes only when the action fails with text that the boundary
produces, such as `Permission denied` or HTTP status 403. A failure without
that text is `INCONCLUSIVE`, because a missing file or an offline network also
makes an action fail. The command exits with status 1 on any `FAIL` and status
2 on any `INCONCLUSIVE`. `PLANNED` and `N/A` cases do not change the exit
status.

Priority P0 marks a case that must pass before this recipe can claim that the
boundary holds on a host. Priority P1 marks a case that adds coverage.

If a denied case reports `FAIL`, the sandbox may have a gap. Do not post that
result in a public issue or pull request. Follow the repository
[security policy](../../../../SECURITY.md).

| ID | Priority | Action inside the sandbox | Expected | State |
| --- | --- | --- | --- | --- |
| S00 | P0 | Send a chat request to the local inference route | Allowed | Ready |
| S01 | P0 | Read a file in the approved workspace | Allowed | Ready |
| S02 | P0 | Read a file outside the workspace through a parent reference | Denied | Ready |
| S03 | P0 | Read a file outside the workspace through a symbolic link | Denied | Ready |
| S04 | P0 | List a Windows drive that WSL2 mounts on the host | Denied or absent | Ready, WSL2 host only |
| S04b | P0 | Start a Windows program through WSL2 interoperability | Denied or absent | Ready, WSL2 host only |
| S05 | P0 | Gain privileges with `sudo` | Denied | Ready |
| S05b | P0 | Write to a system path | Denied | Ready |
| S06 | P0 | Reach an external HTTP endpoint with `curl` | Denied | Ready |
| S06b | P0 | Reach an external HTTPS endpoint with `curl` | Denied | Ready |
| S06c | P0 | Reach an external HTTP endpoint with a second program | Denied | Ready |
| S06d | P1 | Open a TCP connection to an IP address | Denied | Planned |
| S07 | P0 | Follow a prompt that asks for a protected file | Denied | Planned |
| S08 | P0 | Send a chat request while the local inference server is stopped | Explicit error | Ready |
| S09 | P0 | Call a remote inference API directly | Denied | Ready |
| S10 | P1 | Read a file larger than the tool limit | Denied | Planned |
| S11 | P1 | Replace a file with a symbolic link during a read | Denied | Planned |
| S12 | P1 | Run setup and teardown twice | No leftover resources | Planned |

S02 and S03 read a canary file that the recipe image places in `/srv`. File
permissions let every user read that file, and the policy does not list
`/srv`. A read that succeeds therefore shows that the filesystem policy is not
enforced.

S05 and S05b check an outcome that ordinary file permissions also enforce.
A pass shows that the action failed. It does not show which mechanism denied
it.

Print the table from the source of truth with:

```bash
PYTHONPATH=src python3 -m localonly cases
```

### Evidence Records

Each record holds the decision and never the command output:

```json
{"backend": "openshell", "case_id": "S02", "detail": "expected result", "duration_ms": 412, "exit_code": 1, "expect": "deny", "host_traits": [], "leak_detected": false, "matched_signature": "permission denied", "priority": "P0", "schema": 1, "timestamp": "2026-01-01T00:00:00Z", "verdict": "PASS"}
```

This record is an illustration of the format. It is not the result of a run.
If a denied action returns protected content, the record sets `leak_detected`
to `true` and omits the content.

## Teardown

```bash
bash scripts/teardown.sh
```

Teardown deletes the sandbox and the provider that setup created, and it stops
the recipe-owned Ollama container. It leaves the model volume in place. To
delete the model volume as well, run:

```bash
bash scripts/teardown.sh --purge-models
```

Teardown removes only the resources that setup recorded in `.run/created`. It
does not restore the earlier gateway inference route. It does not change an
Ollama installation that exists outside this recipe.

## Files

| Path | Purpose |
| --- | --- |
| `policies/local-only.yaml` | Full sandbox policy: filesystem allowlist and one egress endpoint |
| `docker-compose.yml` | Recipe-owned Ollama server, published on loopback by default |
| `docker-compose.gpu.yml` | NVIDIA GPU reservation that setup adds when the host has a GPU |
| `Dockerfile` | Published OpenClaw sandbox image plus one canary file for the test suite |
| `scripts/bring-up.sh` | Checks inputs, starts Ollama, sets the inference route, creates the sandbox, copies the folder |
| `scripts/verify.sh` | Static checks, or the live test suite with `--live` |
| `scripts/teardown.sh` | Removes the resources that setup created |
| `src/localonly/` | Host-side checks and the test suite. Uses only the Python standard library |
| `src/SKILL.md` | The `workspace-assistant` skill that setup copies into the sandbox |
| `src/tests/` | Unit tests for the static checks |
| `fixtures/` | Sample approved folder and the canary file for the image |
| `docs/` | Longer explanations and the images. Start at [`docs/README.md`](docs/README.md) |

## Known Limitations

- **Setup does not complete with OpenShell 0.1.8.** `scripts/bring-up.sh`
  follows the OpenShell commands that other examples in this repository use
  with versions 0.0.85 and 0.0.106. A run with OpenShell 0.1.8 stopped at
  stage 5 with `provider profile 'openai' not found`. That version differs in
  these ways:
  - It has no `openshell inference` command. Setup uses `inference set` and
    `inference get`.
  - `openshell provider create` requires a provider profile that was imported
    with `openshell profile import`. The gateway had no profile.
  - `openshell sandbox create --from` accepts an image reference or a root
    file system archive, not a Dockerfile. Setup passes the Dockerfile.
  - It has `openshell sandbox upload` and no `openshell sandbox cp`. Setup
    uses `sandbox cp`.
- **Stages 5 to 7 are not verified with any OpenShell version.** Nobody has
  run this recipe with OpenShell 0.0.85 or 0.0.106, or created the sandbox
  with this policy and this image.
- **The policy allowlist may be too narrow.** The filesystem allowlist and the
  program list for `inference.local` are a first estimate for the OpenClaw
  sandbox image. The sandbox may need more read-only paths to start.
- **A local provider may need a different OpenShell mode.** Another example in
  this repository notes that a change from a cloud provider to local Ollama
  did not take effect with the single-container Docker driver. Confirm the
  route with `openshell inference get` after setup.
- **The gateway must reach the endpoint.** The default endpoint is host
  loopback. A gateway that runs in a container cannot reach host loopback. Set
  `OLLAMA_PUBLISH_HOST`, `INFERENCE_BASE_URL`, and
  `LOCAL_ENDPOINT_EXTRA_HOSTS` to the address of a Docker bridge on the same
  machine in that case.
- **Landlock is best effort.** The policy sets Landlock compatibility to
  `best_effort`, as the other examples do. On a kernel without Landlock,
  OpenShell may start the sandbox without filesystem enforcement. Setup checks
  for Landlock, and cases S02 and S03 measure the result.
- **The endpoint check is syntactic.** It accepts loopback addresses and three
  local names. It does not resolve names.
- **The copy filter is a host-side convenience.** A file can change between
  the check and the copy. Use a folder that untrusted processes cannot write
  to. The sandbox receives a copy, so run setup again after you change files.
- **The agent turn is not wired.** Setup installs the skill and the files. It
  does not start the OpenClaw gateway in the sandbox or send a question.
- **Some cases are planned.** The table marks them. S07 needs a recorded tool
  call that the harness replays.
- **Denial text can differ.** The suite recognizes a denial by its text. A
  different OpenShell version may word a denial differently, which produces
  `INCONCLUSIVE`, not `PASS`.
- **CPU serving is a fallback, not the target.** Without an NVIDIA GPU, the
  model runs on the CPU. That run gives no evidence about GPU serving or
  speed.
- **A small Docker virtual machine may not hold the model and the sandbox.**
  In the one check so far, the loaded model used 2.9 GB of a 3.8 GB limit.
  Nobody has started the sandbox next to it.
- **WSL2 is Linux.** This recipe does not test a native Windows sandbox. The
  test cases name no enforcement technology, so a native Windows backend can
  run the same table later.

## Provenance And Support

This recipe is an independent community contribution. It is not a supported
part of NemoClaw or OpenShell. Catalog placement supports discovery only.

## Third-Party Dependencies And License Notes

The recipe adds no Python package. It uses the `ollama/ollama` container image
and, by default, the NVIDIA Nemotron 3 Nano 4B model under the NVIDIA Open
Model License. The repository
[THIRD-PARTY-NOTICES](../../../../THIRD-PARTY-NOTICES) file lists both. The
sandbox image is the published NemoClaw OpenClaw sandbox image. Review the
license of any other model before you set `INFERENCE_MODEL` to it.
