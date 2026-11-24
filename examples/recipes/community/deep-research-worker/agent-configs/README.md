<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Deep Research Worker With NemoClaw Agent Configs

Deploy the [Deep Research Worker](../README.md) with NemoClaw Agent Configs.
This path replaces Classic sandbox creation, `policy-add`, and skill uploads
with `nemoclaw plan`, an attachable asset volume, and `nemoclaw apply`.
It preserves the community contribution from [issue #110](https://github.com/NVIDIA/nemoclaw-community/issues/110)
and reuses `../src` without copying the worker implementation.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | Community Recipe |
| Contributor or provenance | Adaptation of the existing independent community Deep Research Worker recipe. |
| Use this when | You want to queue research, return later, and retrieve text or JSON results through a dedicated Agent Configs sandbox. |
| You will get | One OpenClaw agent and a separate Compose worker with a persistent SQLite task queue. |
| Runs on | A local Docker engine on Linux or Docker Desktop on macOS; runtime validation is pending. |
| Requires | NemoClaw v0.1.0-rc.4, its OpenClaw image, OpenShell CLI 0.1.9, Docker Compose v2, Python 3.10+, `jq`, and inference API keys. Optional search helpers must already exist. |
| Verified on | Local/static checks only; see Verification. |
| Evidence level | local/static |
| Support and maturity | Draft deployment path; best-effort [community support](../../../../../SUPPORT.md). |
| External access, data, and actions | Agent prompts go to NVIDIA Endpoints. Worker prompts and configured search requests leave the host worker; provider usage can incur charges. Queue and reports are stored on the Docker host. |
| Start here | [Setup](#setup) |
| Confirm success | [Run The Workflow](#run-the-workflow) |

## Credentials And Boundaries

The sandbox agent's `NVIDIA_INFERENCE_API_KEY` is registered with OpenShell.
The separate worker's `OPENAI_API_KEY` lives in its Docker environment and can
be read by Docker administrators. You may use the same NVIDIA Endpoints key
for both, but they are separate credential paths.

`prepare.sh` generates a worker access token in `.run/worker-token`. The same
token goes into a mode-0600 file in the read-only asset volume and into the
worker's environment through `.run/worker.env`. Sandbox code running as the
agent user can read that worker token and submit, list, retrieve, or cancel
any task in this dedicated worker. The mount prevents modifications; it does
not hide the token from the agent. Do not share this worker across trust domains.

The worker publishes no host port. It joins the managed gateway's Docker
network under `research-worker:9050`. The sandbox receives only GET health and
task routes, POST task submission, and DELETE task cancellation, plus managed
inference. The host worker itself is outside the sandbox network policy and
can contact its configured inference and search services. Do not expose the
Docker network or add unrelated containers to it.

Only send public or approved data. Empty search-helper endpoints disable those
tools; without helpers, the worker cannot research current web or document
sources. A model-only response is not evidence of retrieval.

## Setup

Run from this directory on the host that runs Docker. Do not run the parent
Classic `bring-up.sh` or `teardown.sh` for this deployment.

1. Install [NemoClaw v0.1.0-rc.4](https://github.com/NVIDIA/NemoClaw/releases/tag/v0.1.0-rc.4)
   and [its prerequisites](https://github.com/NVIDIA/NemoClaw/blob/v0.1.0-rc.4/docs/get-started/prerequisites.md).
   This release is a draft at the time of authoring. Downloading it and pulling
   the pinned image can require NVIDIA repository and package access. Do not
   substitute a Classic CLI or an unreviewed image when access fails.

2. Pull the release image. It supplies the agent and the volume-copy tools:

   ```bash
   docker pull ghcr.io/nvidia/nemoclaw/v1/openclaw@sha256:bd4d5483797673c83d1dc607893c6e61b84b92cc467a181c2c278614344c168d
   ```

3. On Docker Desktop for macOS, edit `spec.gateway.target.docker.engine` in
   `nemoclaw.yaml` to your Docker socket, such as
   `unix:///Users/YOU/.docker/run/docker.sock`. Keep the default on Linux.
   Use the same engine for all Docker and Compose commands below.

4. Copy `.env.example` to `.env`, replace both API-key placeholders, configure
   any existing search helpers, and load the file. It is shell input; only
   source a file you control. Do not commit it or share rendered Compose output.

   ```bash
   cp .env.example .env
   # Edit .env before continuing.
   chmod 600 .env
   set -a; . ./.env; set +a
   ```

5. Preview the deployment and prepare the assets for the reported workspace:

   ```bash
   nemoclaw plan nemoclaw.yaml
   bash prepare.sh nc-3bd5e6a335b52fd4
   ```

   The fixed UID in this configuration produces workspace
   `nc-3bd5e6a335b52fd4`. If you change the UID, pass the workspace printed by
   your plan instead. The script reuses its worker token on subsequent runs
   and refuses an asset volume labeled for a different workspace.

6. Create the gateway, inference provider, and sandbox:

   ```bash
   nemoclaw apply nemoclaw.yaml
   ```

7. Start the worker on the gateway's Docker network. The network name is the
   workspace followed by `-network`; change it if you changed the UID:

   ```bash
   export RESEARCH_GATEWAY_NETWORK=nc-3bd5e6a335b52fd4-network
   docker compose up -d --build --wait
   ```

   A healthy worker proves HTTP startup, not inference or search readiness.
   Compose builds the existing `../src/Dockerfile`; its dependency ranges
   remain as documented by the original recipe.

## Run The Workflow

Select this gateway and workspace in every terminal that uses OpenShell:

```bash
unset OPENSHELL_GATEWAY
export OPENSHELL_GATEWAY_ENDPOINT=http://127.0.0.1:17672
export OPENSHELL_WORKSPACE=nc-3bd5e6a335b52fd4
```

First verify the deterministic client path without asking the agent:

```bash
openshell sandbox exec -n deep-research --no-tty -- \
  /sandbox/research/deep-research --list 5
```

Submit a bounded task and save the returned ID:

```bash
openshell sandbox exec -n deep-research --no-tty -- \
  /sandbox/research/deep-research --depth shallow --task-id-only \
  "Compare polling and callbacks for an asynchronous task queue. State assumptions."
```

Expected result: a task ID. Submission alone does not show that the task
completed. Replace `<task-id>` below with that value:

```bash
openshell sandbox exec -n deep-research --no-tty -- \
  /sandbox/research/deep-research --resume '<task-id>' --json
```

Expected result: a completed task and a nonempty result in the client JSON
envelope. A failed task must be investigated in `docker compose logs`, rather
than reported as successful research. With search helpers configured, repeat
with a question requiring current sources and check the returned citations.

To verify agent skill discovery and delegation:

```bash
RUNTIME_ID=$(nemoclaw plan -o json --progress off --non-interactive nemoclaw.yaml \
  | jq -er '.agents["deep-research"].runtimeId')
printf '%s\n' '"Use the deep-research skill to queue a shallow comparison of polling and callbacks. Return the task ID immediately; do not wait for completion."' \
  | openshell sandbox exec -n deep-research --no-tty -- \
      fabric-agent-ctl invoke --agent main --runtime-id "$RUNTIME_ID" --input - \
  | jq -r '.result.output.response'
```

The task ID must also appear in `--list 5`. Long jobs should use
`--task-id-only` and a later `--resume`; the agent invocation timeout is 300
seconds, while worker jobs may take longer. Cancellation and retention retain
the [original recipe's behavior](../README.md#task-lifecycle-and-state-management).

## Verification

**Evidence level:** local/static. The configuration passes the v0.1.0-rc.4
JSON schema and a native `nemoclaw plan` with a nonfunctional validation-only
credential. The plan reports nine new resources in the expected workspace;
it does not verify the credential or the unavailable image. Live setup,
sandbox DNS and network grants,
agent delegation, provider-backed research, helper retrieval, and cleanup
remain to be verified before this path is marked ready.

From the parent recipe directory, run the existing client and worker checks:

```bash
bash scripts/verify.sh
```

From this directory, check the new setup script:

```bash
bash -n prepare.sh
python3 -m unittest -v test_prepare.py
```

The new configuration must validate against the schema distributed with
NemoClaw v0.1.0-rc.4. The setup tests check credential reuse, skill-path
adaptation, and refusal to modify a volume owned by another workspace. They
use a temporary Docker command stub and do not prove a real deployment.

For live acceptance, complete Setup and Run The Workflow, verify an
ungranted host is denied from the sandbox, then complete Cleanup. Record the
exact CLI, image, host, helper-service versions, and results in the pull request.

## Cleanup

Run from this directory with the same Docker engine and
`RESEARCH_GATEWAY_NETWORK` value used at setup. Stop the Compose worker first,
so its external-network attachment does not prevent gateway-network removal:

```bash
docker compose down
nemoclaw destroy
```

Destroy removes the sandbox and its conversation history. The worker database
in `state/`, the asset volume, gateway storage, and `.nemoclaw` remain. Pulling
images and building the worker also leaves local images and build cache.

To permanently delete this recipe's queue, reports, and worker token after
destroy has completed:

```bash
docker volume rm deep-research-assets
rm -r state .run
```

Remove each directory only if it exists. The worker runs as root in Docker,
so removing `state/` on Linux can require host administrator privileges.
These commands cannot undo provider
requests or revoke API keys. Keep `.nemoclaw` until you have reviewed the
[retained-resource removal procedure](https://github.com/NVIDIA/NemoClaw/blob/v0.1.0-rc.4/docs/build-deploy/usage.md#removing-retained-resources)
and removed only this deployment's retained gateway objects. Deleting state
before then loses their management record.

## Limitations

- This adds a deployment path to the existing community recipe. It does not
  change the worker's research engine, tool budgets, authentication, or model
  quality guarantees.
- The Classic deployment and this path have separate tokens, queues, sandbox
  state, and lifecycle commands. Existing tasks are not migrated.
- The fixed UID, gateway port, subnet, Compose project name, and asset volume
  support one copy on an engine. Change all of them for a second deployment.
- The worker and sandbox share the gateway network; the worker is a trusted
  host-side component, not another sandbox. Its inference key is not protected
  by the sandbox's OpenShell provider store.
- Model changes may replace the sandbox and delete its conversation and
  client-side last-task marker. The worker's SQLite queue persists in `state/`.
- Updating the skill or client requires rerunning `prepare.sh`. Do not delete
  `.run/worker-token` while preserving a running worker or existing assets;
  that rotates the client credential and requires restarting the worker too.
- The first end-to-end run is pending release-package access and working
  inference credentials. This document provides expected results, not a claim
  that those live checks passed.

The dependency licenses and support boundary are unchanged from the
[parent recipe](../README.md#third-party-dependencies-and-license-notes).
