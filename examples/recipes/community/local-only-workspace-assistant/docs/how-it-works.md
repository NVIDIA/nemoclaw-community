<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# How It Works

This page describes the design for OpenShell 0.1. A live run on macOS with
Docker Desktop and CPU inference confirmed it. No Linux, WSL2, or GPU host has
run it yet. [Status And Planned Work](status.md) lists what has run.

## The Big Picture

![Components and trust zones: host, Docker, OpenShell gateway, and sandbox](images/architecture-components.png)

Everything runs on one host. The host is trusted: the operator, the scripts,
Docker, and the OpenShell gateway. The sandbox is the untrusted zone, because
it runs the agent and any code that the agent starts.

Follow the solid arrows to see what is allowed:

1. The operator runs the scripts. The scripts check the inputs and ask the
   OpenShell gateway to store a provider profile and a provider, and to create
   the sandbox with the policy and that provider.
2. The gateway composes the sandbox's effective policy: the sandbox policy
   plus the provider layer.
3. Setup passes the approved folder through the copy filter and uploads the
   accepted files into `/sandbox/workspace`.
4. The agent reads the copy.
5. The agent sends prompts to `host.openshell.internal` port 11434. Policy
   enforcement in the sandbox checks the program, the host, the port, and the
   path against the provider layer, and forwards the request to the Ollama
   container on the same host.

The dotted arrows are what the policy is designed to deny: any other network
destination, and any host file outside the short list in the policy.

## Three Controls

Three controls keep file contents and prompts on the machine. None of them
runs inside the model or the agent process, so the agent cannot switch them
off.

| Control | What it does | Where it runs |
| --- | --- | --- |
| Sandbox policy | Lists a short set of file paths and no network endpoint | OpenShell enforces it |
| Provider profile | Names one endpoint, `host.openshell.internal` port 11434, the five inference API paths, and four programs. Attaching the provider adds these entries, and only these, to the effective policy | OpenShell enforces it. Setup checks the file and reads the effective policy back |
| Copy, not mount | The sandbox receives a copy of the approved folder. No host folder is mounted. A filter rejects links, special files, and oversized files before the copy | Setup script, on the host |

OpenShell 0.1 has no gateway-wide inference route. The sandbox calls the model
server itself, and the request passes the same policy enforcement as any other
connection. So the provider profile is the one place that says where prompts
may go. Setup also checks that the URL that OpenClaw and the test cases call,
`INFERENCE_BASE_URL`, names a local host and matches the profile endpoint.

## Who Does What

The recipe configures and tests. It does not enforce.

| Party | Responsibility |
| --- | --- |
| OpenShell and the host kernel | Compose the effective policy from the sandbox policy and the provider layer. Enforce the filesystem allowlist and the network entries |
| Docker | Run the Ollama container and publish its port on one host address |
| Ollama | Serve the model through an OpenAI-compatible API |
| The recipe scripts | Check inputs, create and remove resources in order, and record what they created |
| The `localonly` package | Check the sandbox policy, the provider profile, the addresses, and the approved folder. Run the test cases and write evidence |
| The operator | Choose the approved folder, read the test results, and decide whether to trust them |

## Setup, Stage By Stage

![Sequence of calls that setup makes to the checks, Docker, the gateway, and the sandbox](images/setup-sequence.png)

`scripts/bring-up.sh` runs seven stages. It stops at the first stage that
fails. Stages 1 and 2 change nothing outside the `.run` directory.

| Stage | What setup does | What it changes |
| --- | --- | --- |
| 1. Check inputs | Confirms that Docker, Compose, and OpenShell exist and that the gateway answers. Checks the sandbox policy, the provider profile, the publish address, the endpoint address, and the approved folder | Writes the list of files to copy to `.run` |
| 2. Select the device and check the kernel | Chooses the NVIDIA GPU or the CPU. On Linux, checks that the kernel lists the Landlock security module | Records the device in `.run/created` |
| 3. Start the inference server | Starts the recipe-owned Ollama container and waits until it is healthy | Creates one container and one volume. The first run downloads the image |
| 4. Make the model available | Downloads the model if the volume does not hold it | The first run downloads the model |
| 5. Register the local server as a provider | Lints and imports the provider profile, then creates a provider from it | Adds one profile and one provider to the gateway. No other sandbox is affected |
| 6. Build the image and create the sandbox | Builds the sandbox image from the `Dockerfile`, creates the sandbox from that image with the policy and the provider, waits until it is ready, applies the policy again, reads the effective policy back, and checks it | Creates one image and one sandbox |
| 7. Copy the folder and the skill | Uploads each accepted file to `/sandbox/workspace` and the skill to the agent's skill directory | Writes files inside the sandbox |

Setup refuses to reuse a sandbox, a provider, or a provider profile that it
did not create. That rule keeps setup from replacing the policy of a sandbox
that belongs to something else.

Stage 6 reads the policy back because a policy that the gateway did not apply
is worth nothing. Setup accepts the sandbox only when every network entry of
the effective policy is a provider entry and every host is
`host.openshell.internal`. It also rejects an effective policy with no host,
which is what a sandbox without the provider has.

The `Dockerfile` adapts the published OpenClaw sandbox image. That image
configures OpenClaw for OpenShell 0.0: it sends model requests to
`https://inference.local/v1` through an explicit proxy. OpenShell 0.1 removed
both, and it does not run the image entry point that would apply a model
override. The `Dockerfile` points the OpenClaw configuration at the local
server, names the model, and turns the explicit proxy off.

## What Happens To A Request

![Four request flows: allowed local inference, a denied remote request, a denied request to another path, and a stopped local server](images/request-flows.png)

**Allowed.** The agent sends a chat request to
`http://host.openshell.internal:11434/v1/chat/completions`. The program, the
host, the port, and the path match the provider layer, so OpenShell forwards
the request to Ollama, and the answer returns to the agent. Test case S00
exercises this flow.

**Denied, another host.** The agent, or a program that it starts, connects to
any other host. The effective policy lists no such endpoint, so the connection
fails inside the sandbox with `Permission denied`. Cases S06, S06b, and S06c
try this with two programs, because network entries name programs. Case S09
tries a remote inference service directly.

**Denied, another path or program.** A request to the local server on a path
that the profile does not list, such as the model download API, receives
`HTTP Error 403` with `policy_denied`. Case S09b tests this. A program that the
profile does not name, such as `curl`, cannot connect to the local server at
all. Case S09c tests this.

**Local server stopped.** The agent sends a chat request while the Ollama
container is stopped. The sandbox has one provider and no other endpoint, so
the request fails. A completion in this state would mean that another
inference service answered. Case S08 stops the container, sends the request,
and starts the container again. On macOS with Docker Desktop, the request
failed when the client timed out after 120 seconds.

## How The Recipe Tests Itself

![Parts of the test suite: case table, runner, backend interface, OpenShell backend, host actions, and evidence](images/test-suite-design.png)

A claim that an action is denied needs evidence. The test suite runs each
action inside the running sandbox and records the result.

The design has one rule that matters most: a denied case passes only when the
failure carries text that the boundary produces. A missing file, a stopped
network, or a missing sandbox also makes an action fail. Those failures are
reported as `INCONCLUSIVE`, not as a pass.

Two cases read a canary file. The recipe image places the file in `/srv`, and
file permissions let every user read it. The policy does not list `/srv`. Only
the sandbox policy can deny the read, so a denial is evidence that the policy
is enforced.

[Test Suite](test-suite.md) describes the cases, the verdict rules, and the
evidence records.

## Teardown

`scripts/teardown.sh` reads `.run/created` and removes what setup recorded:

1. It deletes the sandbox, if setup created it, and waits until OpenShell no
   longer lists it.
2. It deletes the provider and the provider profile, if setup created them.
   OpenShell does not delete a provider that a sandbox still holds, so this
   step comes second.
3. It deletes the sandbox image, if setup built it.
4. It stops the Ollama container, if setup started it. It keeps the model
   volume unless you pass `--purge-models`.

Teardown does not change an Ollama installation that exists outside this
recipe.

## OpenShell Versions

The scripts use the OpenShell 0.1 command set. They were run with OpenShell
0.1.8. OpenShell 0.0 releases use a gateway-wide inference route and other
commands, and the scripts do not run with them.
[Status And Planned Work](status.md) lists the differences.
