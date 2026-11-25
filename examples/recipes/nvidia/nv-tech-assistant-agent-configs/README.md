<!--
  SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
  SPDX-License-Identifier: Apache-2.0
-->

# NV Tech Assistant

| Catalog field | Value |
| --- | --- |
| Description | Helps developers choose and troubleshoot NVIDIA technologies by searching allowlisted documentation, repositories, model catalogs, and forums for current, evidence-linked answers, deployed with NemoClaw Agent Configs from one configuration file. |
| Industry | 🖥️ Hardware/Semiconductor |
| Requirements | Docker · NemoClaw CLI · NVIDIA Endpoints API key · no web search · no offline corpus |
| NemoClaw | v0.1.0-rc.4 |
| Harness | OpenClaw 2026.9.34 |
| OpenShell | 0.1.9 |

NV Tech Assistant answers NVIDIA technical questions with citations to pages
it retrieved during the task, not from model memory. It searches authorized
NVIDIA sources, GitHub, Hugging Face, and arXiv. This version deploys the
assistant with NemoClaw Agent Configs: one YAML file declares the gateway, the
inference provider, the OpenClaw agent, its read-only network grants, and its skill, and
`nemoclaw plan` and `nemoclaw apply` create them.

The [NemoClaw Classic version](../nv-tech-assistant/README.md) of this example
remains for deployments made with `nemoclaw onboard`.

Use it for questions such as:

- How do I use an NVIDIA SDK or find an official sample?
- Which NVIDIA model, NIM, or library fits my use case?
- How do I troubleshoot an NVIDIA SDK error?
- Where is a documented NVIDIA customer success story?

## Example Result

Asked to recommend a speech recognition model, the agent fetched model cards
and catalog pages, then answered with a table and its sources. Abridged reply:

```text
Recommend NVIDIA Nemotron 3.5 ASR Streaming (nvidia/nemotron-3.5-asr-streaming-0.6b)
as the primary NVIDIA speech recognition (ASR) model. If your use case is
English-only, use Nemotron 3 ASR Streaming (nvidia/nemotron-speech-streaming-en-0.6b)
instead ...

Sources
1. Nemotron 3.5 ASR Streaming model card (Hugging Face)
   https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b
2. Nemotron ASR Streaming English model card (Hugging Face)
   https://huggingface.co/nvidia/nemotron-speech-streaming-en-0.6b
3. Nemotron ASR Streaming NIM endpoint (build.nvidia.com)
   https://build.nvidia.com/nvidia/nemotron-asr-streaming
```

The sandbox's policy log records each fetch and the grant that allowed it,
such as `ALLOWED GET https://huggingface.co/nvidia/nemotron-3.5-asr-streaming-0.6b [policy:huggingface]`.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | NVIDIA Recipe |
| Contributor or provenance | NVIDIA. Adapted from the [NemoClaw Classic NV Tech Assistant](../nv-tech-assistant/README.md). |
| Use this when | You run NemoClaw Agent Configs and want a research assistant whose network reach is limited to named NVIDIA, GitHub, Hugging Face, and arXiv hosts. |
| You will get | One OpenClaw sandbox on a local NemoClaw gateway that answers NVIDIA questions with cited sources and drafts network grants for blocked sites. |
| Runs on | A host with Docker. Verified on macOS with Docker Desktop on Apple silicon. |
| Requires | The NemoClaw v0.1.0-rc.4 CLI, Docker, the OpenShell CLI (the release's [prerequisites](https://github.com/NVIDIA/NemoClaw/blob/v0.1.0-rc.4/docs/get-started/prerequisites.md) name 0.1.9), `jq`, and an NVIDIA Endpoints API key from [build.nvidia.com](https://build.nvidia.com). |
| Verified on | NemoClaw v0.1.0-rc.4 (`darwin_arm64` CLI, `linux/arm64` OpenClaw image), OpenShell CLI 0.1.8, Docker Desktop 29.9.3, macOS, 2026-11-24. |
| Evidence level | live end-to-end |
| Support and maturity | Best-effort community support under the repository [support policy](../../../../SUPPORT.md). NemoClaw v0.1.0-rc.4 is a release candidate. |
| External access, data, and actions | Prompts and fetched page text go to NVIDIA Endpoints (`integrate.api.nvidia.com`), which can incur usage charges. The agent sends read-only GET and HEAD requests to the hosts in [Network Grants](#network-grants). It writes nothing outside its sandbox. |
| Start here | [Quickstart](#quickstart) |
| Confirm success | [Verification](#verification) |

## Quickstart

Run these steps from this directory on the host that runs Docker.

1. Install the NemoClaw v0.1.0-rc.4 CLI and put it on `PATH`, following
   [Installing the CLI](https://github.com/NVIDIA/NemoClaw/blob/v0.1.0-rc.4/docs/get-started/install.md).
   Until v0.1.0 is published, the release is a draft: only accounts that can
   see drafts in NVIDIA/NemoClaw can download it.

2. Pull the OpenClaw agent image that the release lists. The plan reads the
   image from your Docker engine.

   ```bash
   docker pull ghcr.io/nvidia/nemoclaw/v1/openclaw@sha256:bd4d5483797673c83d1dc607893c6e61b84b92cc467a181c2c278614344c168d
   ```

   While the release is a draft, the pull needs a `docker login ghcr.io` with
   a token that can read NVIDIA's packages.

3. On Docker Desktop for macOS, change `engine` in `nemoclaw.yaml` to
   `unix:///Users/YOU/.docker/run/docker.sock`, with your user name.
   Leave it unchanged on Linux.

4. Put your API key in `.env`, which Git ignores, and load it:

   ```bash
   cp .env.example .env   # then set NVIDIA_INFERENCE_API_KEY
   set -a; . ./.env; set +a
   ```

5. Preview the deployment.

   ```bash
   nemoclaw plan nemoclaw.yaml
   ```

   The plan reports `OpenShell workspace: nc-c8e2a94a705afdd9`. If you changed
   `metadata.uid`, use the workspace your plan reports in the next step.

6. Create the skill volume, labeled so that the workspace's sandboxes can
   mount it, and copy the skill into it:

   ```bash
   docker volume create \
     --label openshell.ai/sandbox-attachable=true \
     --label openshell.ai/sandbox-attachable-workspace=nc-c8e2a94a705afdd9 \
     nv-tech-assistant-skills
   docker run --rm --user 0 --entrypoint cp \
     -v nv-tech-assistant-skills:/skills -v "$PWD/skills:/src:ro" \
     ghcr.io/nvidia/nemoclaw/v1/openclaw@sha256:bd4d5483797673c83d1dc607893c6e61b84b92cc467a181c2c278614344c168d \
     -R /src/. /skills/
   ```

7. Create the gateway, provider, and sandbox, and start the agent:

   ```bash
   nemoclaw apply nemoclaw.yaml
   ```

   Apply reports `Apply complete` and prints the agent's runtime ID and an
   invoke command.

## Asking a Question

Select the deployment's gateway and workspace in each terminal that sends
requests:

```bash
unset OPENSHELL_GATEWAY
export OPENSHELL_GATEWAY_ENDPOINT=http://127.0.0.1:17671
export OPENSHELL_WORKSPACE=nc-c8e2a94a705afdd9
```

Read the agent's runtime ID and send one prompt:

```bash
RUNTIME_ID=$(nemoclaw plan -o json --progress off --non-interactive nemoclaw.yaml \
  | jq -er '.agents["nv-tech-assistant"].runtimeId')
echo '"/nv_tech_assistant recommend an NVIDIA model for speech recognition"' \
  | openshell sandbox exec -n nv-tech-assistant --no-tty -- \
      fabric-agent-ctl invoke --agent main --runtime-id "$RUNTIME_ID" --input - \
  | jq -r '.result.output.response'
```

A research question took about four minutes in verification. The agent stops
a request after 300 seconds (`harness.runtime.timeout_seconds`). The agent
keeps its conversation between requests, so a later answer can refer to an
earlier one.

More prompts:

- `/nv_tech_assistant show an official TensorRT-LLM sample`
- `/nv_tech_assistant I'm getting CUDA error: out of memory with Triton`
- `/nv_tech_assistant show a documented customer success story for NVIDIA Riva`
- `/nv_tech_assistant draft a read-only policy for medium.com`

## Architecture

`nemoclaw.yaml` declares one deployment:

- A NemoClaw-managed OpenShell gateway on the local Docker engine, listening on
  `127.0.0.1:17671`.
- An NVIDIA Endpoints inference provider. NemoClaw registers the key from
  `NVIDIA_INFERENCE_API_KEY` with OpenShell; the sandbox never receives it.
- One sandbox running the OpenClaw agent `main` with
  `nvidia/nemotron-3.5-super-vl-120b-a12b`.
- The isolated network preset plus four read-only grants.
- The `nv-tech-assistant-skills` volume, mounted read-only at
  `/sandbox/skills`, which OpenClaw loads skills from.

The skill in [`skills/nv-tech-assistant`](skills/nv-tech-assistant/SKILL.md)
plans source searches and cited answers inside the sandbox.

## Network Grants

The agent's own executables get read-only (GET and HEAD) REST access, with
TLS inspection and enforcement, to:

- `www.nvidia.com`, `docs.nvidia.com`, `developer.nvidia.com`,
  `blogs.nvidia.com`, `build.nvidia.com`, `forums.developer.nvidia.com`, and
  `catalog.ngc.nvidia.com`
- `github.com`, `api.github.com`, and `raw.githubusercontent.com`
- `huggingface.co`
- `arxiv.org` and `export.arxiv.org`

Subdomains aren't implied; each hostname is listed. Every other destination is
denied, apart from the inference endpoint that NemoClaw grants.

When a source is blocked, the skill drafts a grant for it and tells you how to
apply it, because the agent can't change its own policy. Add the grant under
`spec.sandboxes.nv-tech-assistant.network.grants` in `nemoclaw.yaml`, then run
`nemoclaw plan nemoclaw.yaml` and `nemoclaw apply nemoclaw.yaml`. The plan
shows `update sandbox/nv-tech-assistant`, and apply changes the running
sandbox's policy without replacing it.

## Updating the Skill

Copy the edited skill into the volume again with the `docker run` command in
[Quickstart](#quickstart) step 6. The next request uses it.

## Verification

**Evidence level:** live end-to-end

Follow the [Quickstart](#quickstart), then:

1. Ask the speech recognition question in [Asking a Question](#asking-a-question).
2. Check that a host outside the grants is blocked and a granted one isn't:

   ```bash
   openshell sandbox exec -n nv-tech-assistant --no-tty -- python3 -c '
   import urllib.request as u
   for url in ("https://docs.nvidia.com/", "https://medium.com/"):
       try: print(url, u.urlopen(url, timeout=20).status)
       except Exception as e: print(url, "blocked:", e)'
   ```

3. Ask `/nv_tech_assistant draft a read-only policy for medium.com`.

**Expected result:**

```text
1. A reply with a direct answer, evidence, and a Sources list of
   huggingface.co, build.nvidia.com, or other granted URLs.
2. https://docs.nvidia.com/ 200
   https://medium.com/ blocked: <urlopen error [Errno 13] Permission denied>
3. A medium-com grant with access: read-only entries, and instructions to add
   it to nemoclaw.yaml and run nemoclaw plan and nemoclaw apply on the host.
```

**This verifies:** the deployment applies at NemoClaw v0.1.0-rc.4, the agent
loads the skill from the volume, answers with sources it fetched through the
grants, the sandbox denies other hosts, and the skill's grant instructions
match NemoClaw Agent Configs. In verification, applying the drafted grant
updated the running sandbox in place, after which the policy log allowed `medium.com`.

**This does not verify:** Linux hosts, AMD64 images, the other example prompts,
answer quality across questions, or OpenClaw's interactive terminal UI
([agent interfaces](https://github.com/NVIDIA/NemoClaw/blob/v0.1.0-rc.4/docs/agents-inference/interfaces.md#openclaws-terminal-ui)).

## Cleanup

Destroy the deployment from this directory:

```bash
nemoclaw destroy
```

Destroy deletes the sandbox, its conversation history, the provider
registration, and the gateway. It retains the gateway's storage and leaves the
skill volume, the pulled images, and the `.nemoclaw` state directory.

To remove everything, first confirm that `nemoclaw plan --destroy` prints
`No resource changes planned.` and lists only `gateway storage` under
`Retained resources:`. Then remove the Docker objects labeled with this
deployment's `metadata.uid`, the skill volume, and the state directory. On
Docker Desktop for macOS, use the `engine` value from `nemoclaw.yaml` as
`--host`.

```bash
owner_label="label=nemoclaw.nvidia.com/uid=3c49bcbc-6b47-4145-80d1-a8dcfb3ff6ab"
docker container ls --all --quiet --filter "$owner_label" | xargs docker container rm
docker volume ls --quiet --filter "$owner_label" | xargs docker volume rm
docker network ls --quiet --filter "$owner_label" | xargs docker network rm
docker volume rm nv-tech-assistant-skills
rm -r .nemoclaw
```

This permanently deletes the gateway's database and keys. It doesn't revoke
your API key. See
[Removing Retained Resources](https://github.com/NVIDIA/NemoClaw/blob/v0.1.0-rc.4/docs/build-deploy/usage.md#removing-retained-resources).

## Known Limitations

- No web search. OpenClaw's Brave and Tavily plugins can't be configured
  through NemoClaw Agent Configs yet
  ([NVIDIA/NemoClaw#13361](https://github.com/NVIDIA/NemoClaw/issues/13361)),
  so the skill fetches its allowlisted sources directly. Pages that render in
  the browser, such as `build.nvidia.com` search, return little text.
- NVIDIA Endpoints no longer serves `nvidia/nemotron-3-super-120b-a12b`, the
  Classic example's default model, so this example uses
  `nvidia/nemotron-3.5-super-vl-120b-a12b`.
- Changing the model replaces the sandbox and deletes its conversation
  history. The skill volume is kept.
- `metadata.uid`, port `17671`, network `172.20.0.0/24`, and the volume name
  are fixed. To run a second copy on the same host, change all four.
- Retrieval is limited to the granted hosts. A source that redirects to a new
  hostname or CDN needs its own grant.
- Results depend on the availability and current contents of external public
  sources; the example provides no offline corpus.

## Layout

```text
nv-tech-assistant-agent-configs/
├── .env.example          # NVIDIA_INFERENCE_API_KEY
├── .gitignore            # keeps the .nemoclaw state directory out of Git
├── nemoclaw.yaml         # the NemoClaw Agent Configs deployment
└── skills/
    └── nv-tech-assistant/
        ├── SKILL.md
        └── references/
            ├── nvidia-landscape.md
            ├── sources-and-search.md
            ├── nemoclaw-network-policy.md
            └── nemoclaw-policy-template.yaml
```

## Third-Party Services and Dependencies

This example vendors no packages. It runs the OpenClaw image that NemoClaw
v0.1.0-rc.4 lists and contacts NVIDIA Endpoints and the public sites in
[Network Grants](#network-grants). Each external service is subject to its own
availability and terms.

## Security Notes

- Never commit the populated `.env`.
- The API key stays on the host and in OpenShell's provider store; the sandbox
  receives only a placeholder that OpenShell replaces on inference requests.
- All source grants are read-only and inspect each request's method.
- The agent can't change its own network policy; grants change only when you
  apply `nemoclaw.yaml` from the host.
- The skill volume is mounted read-only in the sandbox.
