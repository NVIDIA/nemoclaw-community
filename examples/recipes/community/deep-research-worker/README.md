<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Deep Research Worker

Deep Research Worker is a community recipe for asynchronous, long-horizon
research with a NemoClaw-managed sandbox. It installs a `deep-research` skill
and CLI wrapper into one existing sandbox, then routes requests from that
sandbox to a host-side FastAPI worker that runs a LangChain DeepAgents graph,
stores task state in SQLite, and can call bounded host-side helper services.

This example is based on the public proposal in issue `#110`. It is an
independent community contribution, not a supported part of NemoClaw core. Its
catalog placement supports discovery only; it does not imply NVIDIA support or
a support or readiness guarantee.

## Scope

This recipe stands up the host-side research worker, installs the in-sandbox
skill and CLI wrapper, and adds or applies a narrow policy that lets a
dedicated sandbox reach only that worker on `host.openshell.internal:9050`.

It does not:

- create a sandbox for you
- provision an inference provider
- stand up web-search, doc-search, or email helper services
- start a dashboard or a general-purpose OpenClaw agent runtime
- manage unrelated routes on a shared sandbox safely

Use a dedicated sandbox for this recipe. The worker can call helper services on
the same host when you configure their endpoints.

## Provenance And Intended Users

- Provenance: independent community contribution proposed in public issue `#110`
- Intended users: operators who already run NemoClaw or OpenShell and want to
  add a background research workflow to one sandbox
- Support boundary: this repository example documents one public integration
  pattern; operators remain responsible for provider credentials, host service
  availability, and any production hardening

## Requirements

- Docker with Compose support
- Python 3.10 or newer for local syntax checks
- One working OpenShell or NemoClaw host with a dedicated sandbox for this recipe
- One OpenAI-compatible inference endpoint reachable from the worker container

Optional host-side services:

- web search on `WEBSEARCH_ENDPOINT_URL`
- document search on `DOC_SEARCH_ENDPOINT_URL`

The worker currently exposes only the bounded web-search and document-search
tools. Email, MCP, write, publish, and other action tools are not supported by
this recipe.

## Credentials And Secret Handling

Copy `.env.example` to `.env` and replace placeholder values before live use.

Required values:

- `OPENAI_API_KEY`
- any non-default endpoint overrides your host requires

The worker API **requires** authentication via `DEEPAGENTS_SERVICE_SECRET`. If
you do not provide a value in `.env`, `scripts/bring-up.sh` automatically
generates a strong secret and stores it in the gitignored `.run/worker-token`
file. The script then installs the same token as a mode-`0600` credential file
for the authorized sandbox client.

Do not commit `.env`, generated state, or sandbox-local token material. The
local `.gitignore` excludes `.env`, `state/`, and `.run/`.

## Quickstart

```bash
git clone https://github.com/NVIDIA/nemoclaw-community.git
cd nemoclaw-community/examples/recipes/community/deep-research-worker

cp .env.example .env
bash scripts/bring-up.sh
```

Queue a task from inside the target sandbox:

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --depth deep \
  "Compare public agent sandboxing patterns for long-running research workflows"
```

Stop the worker and remove the installed skill assets:

```bash
bash scripts/teardown.sh
```

## Architecture

### High-Level Component Flow

```mermaid
flowchart LR
    sandbox["OpenShell sandbox"]
    cli["deep-research CLI wrapper"]
    client["DeepResearchClient"]
    worker["Host-side Deep Research Worker\nFastAPI + SQLite queue"]
    engine["DeepAgents Graph Engine\nLangGraph + LLM"]
    llm["OpenAI-compatible inference endpoint"]
    web["Optional web-search service"]
    docs["Optional doc-search service"]

    sandbox --> cli
    cli --> client
    client -->|"POST /v1/tasks"| worker
    worker --> engine
    engine --> llm
    engine -. tool calls .-> web
    engine -. tool calls .-> docs
    worker -->|"GET /v1/tasks/{id}"| client
```

### Request/Response Lifecycle

```mermaid
sequenceDiagram
    participant User as User in Sandbox
    participant CLI as deep-research CLI
    participant Client as DeepResearchClient
    participant API as Worker API<br/>Port 9050
    participant Queue as SQLite Queue
    participant Engine as DeepAgents Engine
    participant LLM as LLM Provider

    User ->> CLI: /sandbox/bin/deep-research<br/>"Research topic"
    CLI ->> Client: parse args & init
    Client ->> API: POST /v1/tasks<br/>{prompt, depth, rubric}
    API ->> Queue: enqueue task
    API -->> Client: {task_id, status: queued}
    Client -->> User: Task ID returned<br/>(--task-id-only)

    activate Engine
    API ->> Engine: [Worker thread picks up]
    Engine ->> Engine: Phase 1: Planning<br/>Phase 2: Research
    Engine ->> LLM: Tool calls & prompts
    LLM -->> Engine: Responses
    Engine ->> Engine: Phase 3: Cross-validation<br/>Phase 4: Finalization
    Engine ->> Queue: update task result
    deactivate Engine

    User ->> Client: /sandbox/bin/deep-research<br/>--resume task_id
    Client ->> API: GET /v1/tasks/{task_id}
    API ->> Queue: fetch task
    Queue -->> API: {status: completed, result: "..."}
    API -->> Client: task data
    Client -->> User: Print research report
```

### Component Responsibilities

**Sandbox Components:**
- `deep-research` CLI wrapper: User-facing command with depth presets and custom rubric options
- `DeepResearchClient`: Handles API communication, polling, output formatting, task history

**Host-Side Worker:**
- `FastAPI service` on port 9050: HTTP API for task submission, status polling, and retrieval
- `SQLite task store`: Persistent queue with retry logic, exponential backoff, and 7-day retention
- `DeepAgents graph engine`: LangGraph-based agentic loop for multi-step research
- `Circuit breaker`: Fault tolerance for tool timeouts and transient errors

### Key Boundaries

1. **Network isolation**: The sandbox can reach **only** the worker API on `host.openshell.internal:9050`, not helper services directly.
2. **Task persistence**: The worker stores task queue, state, and results in SQLite on the host; sandbox cannot access the database.
3. **Credential isolation**: Helper service endpoints and secrets are configured only on the host; the sandbox never sees them.
4. **Concurrency**: Up to 5 worker threads run research tasks in parallel; concurrent requests are queued.
5. **Process isolation**: Each task runs in a dedicated process group that the parent fully stops before a cancellation or timeout changes task state.

## Files

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | Runs the host-side worker container |
| `policies/deep-research-worker.yaml` | Narrow sandbox egress policy for the worker API |
| `scripts/bring-up.sh` | Starts the worker, applies the policy, installs the skill and CLI wrapper |
| `scripts/verify.sh` | Teardown-safe local checks for shell syntax, Python syntax, Compose rendering, and skill metadata |
| `scripts/teardown.sh` | Stops the worker and removes the installed skill assets |
| `src/` | Worker service, task store, client, and container build files |

## Execution Depth Presets

The research worker supports three depth levels that control the LangGraph
recursion limit, tool-call budget, minimum plan steps, and rubric iteration
count.

| Depth | Graph Steps (recursion_limit) | Tool Call Budget | Rubric Iterations | Min Plan Steps | Use Case |
| --- | --- | --- | --- | --- | --- |
| `shallow` | 25 | 25 | 1 | 3 | Quick fact-checking, single-topic summaries |
| `standard` | 50 | 60 | 2 | 5 | Competitive analysis, multi-source research (default) |
| `deep` | 100 | 120 | 3 | 7 | Comprehensive reviews, cross-domain synthesis |

```mermaid
graph LR
    A["Shallow<br/>--depth shallow"] -->|"25 graph steps<br/>25 tool calls<br/>1 rubric iteration"| B["Quick Summary"]
    C["Standard<br/>--depth standard<br/>(default)"] -->|"50 graph steps<br/>60 tool calls<br/>2 rubric iterations"| D["Balanced Analysis"]
    E["Deep<br/>--depth deep"] -->|"100 graph steps<br/>120 tool calls<br/>3 rubric iterations"| F["Exhaustive Research"]

    style A fill:#fff0f0
    style B fill:#ffe0e0
    style C fill:#f0f0ff
    style D fill:#e0e0ff
    style E fill:#f0fff0
    style F fill:#e0ffe0
```

These are **effort budgets**, not completion guarantees. Actual execution time
depends on tool latency, LLM inference time, and network availability. The
client polling loop will stop waiting for results when the configured
`--timeout` (or depth-based default) is exceeded.

### Custom Rubrics

Users can provide a custom rubric with `--rubric "<criteria>"`:

```bash
/sandbox/bin/deep-research --depth deep --rubric \
  "Must include: (1) current vendor landscape, (2) technical requirements, (3) cost analysis" \
  "Evaluate enterprise vector database options for 2026"
```

The custom rubric becomes an evaluation constraint. The agent iterates up to a
bounded number of times per depth level (1 iteration for shallow, 2 for standard,
3 for deep) to evaluate output against the rubric. Iteration limits are based on
depth; the agent does not guarantee that all criteria will be satisfied if the
step budget is exhausted.

If you do not provide a custom rubric, the worker generates a request-specific
but generic rubric that guides the agent toward comprehensive research coverage.

## Usage Examples

### Example 1: Quick Summary (Shallow Depth)

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --depth shallow \
  "Summarize the latest NIST cybersecurity framework updates"
```

Uses the shallow budget (25 graph steps, 25 tool calls, 1 rubric iteration).

### Example 2: Competitive Analysis (Standard Depth)

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research \
  "Compare vector database performance: Pinecone vs. Weaviate vs. Milvus in 2026"
```

Uses the standard budget (50 graph steps, 60 tool calls, 2 rubric iterations).
This is the default when `--depth` is not specified.

### Example 3: Deep Research with Custom Rubric

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --depth deep \
  --rubric "Must cover: (1) regulatory landscape, (2) technical implementation patterns, (3) case studies, (4) risk assessment" \
  "Research agentic workflow platform security and draft a technical whitepaper"
```

Uses the deep budget (100 graph steps, 120 tool calls, 3 rubric iterations).
The custom rubric drives evaluation for up to 3 iterations; the agent does not
guarantee that every rubric criterion will be satisfied within the step budget.

### Example 4: Asynchronous Task Submission and Polling

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --depth deep --task-id-only \
  "Research emerging LLM safety frameworks and draft security assessment"
```

Output: `task_id = f7e2a1b3c9d4e5f6`

Later, retrieve results:

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --resume f7e2a1b3c9d4e5f6
```

Or list recent tasks:

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --list 5
```

### Example 5: Export Results to JSON

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --json --output /tmp/research.json \
  "Compare open-source model serving frameworks"
```

The `--json` flag emits the six-field client envelope described in
[JSON Output Format](#json-output-format). The `--output` flag writes that
envelope to the given file.

## Task Lifecycle And State Management

### Task States

A research task progresses through the following states:

| State | Meaning |
| --- | --- |
| `queued` | Task received, waiting for a worker thread |
| `running` | DeepAgents graph is executing research steps |
| `cancelling` | DELETE received; process group is being stopped |
| `cancelled` | Task stopped by caller request |
| `completed` | Research finished successfully; results are ready |
| `failed` | Task failed; error message available |

Terminal tasks (completed, failed, cancelled) are automatically deleted after 7
days (TTL) via the `cleanup_expired` background job. Deleted tasks cannot be
retrieved.

### Task State Transitions

```mermaid
stateDiagram-v2
    [*] --> queued: POST /v1/tasks
    queued --> running: worker process acquired
    queued --> cancelled: DELETE while queued
    running --> cancelling: DELETE while running
    cancelling --> cancelled: process group stopped
    running --> completed: research finished successfully
    running --> failed: permanent error or retries exhausted
    running --> queued: transient failure retry
    failed --> [*]
    cancelled --> [*]
    completed --> [*]
```

### Retry Behavior

The worker uses **task-level retries** distinct from **tool-call retries**:

#### Task Retries

- **Scope**: The entire task execution restarts if it fails
- **Trigger**: Transient failures including task execution timeouts (`timeout_ms`
  exceeded), connection errors, request timeouts, and classified `TransientTaskError`
- **Configuration**: `DEEPAGENTS_TASK_MAX_RETRIES` (default: 2 retries)
- **Behavior**: Re-queued with exponential backoff (`2^retry_count` seconds,
  capped at 60 s)
- **Permanent failures**: Import failures, graph recursion limit, auth errors,
  budget exhaustion, and unhandled exceptions fail immediately with no retry
- **Cancelled tasks**: Never retried

#### Tool-Call Retries

- **Scope**: Individual tool invocations (`web_search`, `doc_search`) within a
  running task
- **Trigger**: Transient HTTP errors (429, 5xx) and network timeouts
- **Behavior**: Up to 2 in-line retries per tool call with exponential backoff
- **Failure**: If all retries exhaust, the tool call returns a structured
  error; the agent loop continues and may pivot to alternative research strategies

Tool-call retries do not affect task-level retry counts.

```mermaid
graph TD
    A["Task subprocess exits"] --> B{Exit reason?}
    B -->|"Completed
result written"| C["Task: completed"]
    B -->|"Cancelled"| D["Task: cancelled"]
    B -->|"Transient failure
(timeout, connection, etc.)"| E{"retry_count
< max_retries?"}
    B -->|"Permanent error
or budget exhausted"| F["Task: failed"]
    E -->|Yes| G["Re-queue with backoff
retry_count += 1"]
    E -->|No| F
```

## Setup And Configuration

`scripts/bring-up.sh` does four things:

1. Loads `.env` when present.
2. Starts or rebuilds the worker with Docker Compose.
3. Waits for `GET /healthz` on the worker.
4. If `openshell` and the named sandbox exist, installs the policy and then installs:
   - `SKILL.md` into `/sandbox/.openclaw/skills/deep-research/`
   - `deep_research_client.py` into the same skill directory
   - a mode-`0600` worker credential into the same skill directory
   - `/sandbox/bin/deep-research` as the user-facing wrapper

Policy behavior:

- If `nemoclaw` is available, the script adds the recipe policy additively with
  `policy-add --from-file`.
- If only `openshell` is available, the script refuses to replace the full
  sandbox policy unless you set `DEEP_RESEARCH_ALLOW_POLICY_REPLACE=1` for a
  dedicated sandbox.

The script does not create a sandbox. If the sandbox is missing, it leaves the
host-side worker running and prints the follow-up action.

## Network And Policy Permissions

The sandbox policy is intentionally narrow. It allows only:

- `host.openshell.internal:9050`
- REST methods `GET`, `POST`, and `DELETE`
- binaries that invoke the wrapper or Python client

The sandbox does not receive direct routes to host-side web search, doc search, or other helper services. Only the worker container can call configured services.

### Network Isolation Model

```mermaid
graph TB
    subgraph Sandbox ["OpenShell Sandbox (Restricted)"]
        CLI["deep-research CLI"]
        Client["DeepResearchClient"]
    end

    subgraph Host ["Host (Trusted)"]
        API["Worker API<br/>host.openshell.internal:9050"]
        Engine["DeepAgents Engine"]
        Web["Web Search Service<br/>WEBSEARCH_ENDPOINT_URL"]
        Docs["Doc Search Service<br/>DOC_SEARCH_ENDPOINT_URL"]
    end

    subgraph External ["External LLM"]
        LLM["OpenAI-compatible<br/>Inference Endpoint"]
    end

    CLI -->|"POST /v1/tasks<br/>GET /v1/tasks/{id}<br/>POLICY ENFORCED"| API
    Client -->|"Same Routes"| API

    Sandbox -.->|"No Direct Access"| Web
    Sandbox -.->|"No Direct Access"| Docs

    Engine -->|"tool_call"| Web
    Engine -->|"tool_call"| Docs
    Engine -->|"API Call"| LLM

    style Sandbox fill:#ffcccc
    style Host fill:#ccffcc
    style External fill:#ccccff
```

The host port binds to the `openshell-docker` bridge address when that network is available and otherwise binds to `127.0.0.1`. It is never intentionally published on every host interface.

Inside the worker container, helper-service defaults use `host.docker.internal`. The Compose file adds an explicit host-gateway mapping so Linux Docker hosts can resolve that name too.

The protected credential file authorizes the selected sandbox to call the worker. Code running as that sandbox user can use the credential, so install this recipe only into a dedicated sandbox whose policy and workloads you trust.

## Execution And Recovery

The queue uses these lifecycle rules:

- Each claimed task runs in an isolated child process.
- Cancellation, timeout, shutdown, and task completion terminate the entire
  process group, including descendants, before the task changes state.
- On service restart, abandoned `running` tasks become failed and abandoned
  `cancelling` tasks become cancelled. They are not replayed automatically.
- Retention cleanup removes only expired terminal tasks.

## Verification

Run the documented lightweight checks from this example directory:

```bash
bash scripts/verify.sh
```

The script is teardown-safe. It does not start external services or contact the
inference provider. It validates:

- shell syntax for `scripts/*.sh`
- Python syntax for `src/*.py`
- behavioral tests for authentication, rubric revision, tool filtering,
  cancellation, timeout, restart recovery, and retention cleanup
- Docker Compose rendering
- skill frontmatter presence
- policy file shape

Expected result:

```text
PASS: deep-research-worker local verification
```

## Output Formats And Result Handling

### Default Output Format (Plain Text)

By default, the client prints the task `result` field from the server response
directly to stdout. The format of that text is determined by the agent's
output; no wrapper or header is added by the client:

```
[Full research text from the worker]
```

### JSON Output Format

Use `--json` to write a structured envelope to stdout (or `--output <path>` to
write to a file instead). The client emits exactly these six fields:

```bash
openshell sandbox exec --name deep-research-worker -- \
  /sandbox/bin/deep-research --json --output /tmp/result.json \
  "Research AI safety frameworks"
```

```json
{
  "task_id": "f7e2a1b3c9d4e5f6",
  "status": "completed",
  "depth": "standard",
  "result": "<agent-generated markdown>",
  "duration_seconds": 743,
  "retry_count": 0
}
```

### Handling Large Results

For very long research outputs:

1. **Save to file**: Capture stdout to a file instead of printing to console
2. **Check result field**: Parse `result` from the JSON response programmatically

## Known Limitations

- The included verification does not contact the configured inference endpoint
  or prove that helper services and sandbox policy work live.
- The worker depends on third-party packages and live host-side services. The
  DeepAgents version is pinned for the tested rubric API, but the example does
  not include a complete transitive lockfile.
- There are two distinct timeout settings. `--timeout <seconds>` (or the
  depth-based default: shallow=300 s, standard=900 s, deep=2400 s) controls
  how long the **client** polls before printing a resume hint and exiting.
  `timeout_ms` in the API body (default 600 000 ms, env
  `DEEPAGENTS_TASK_TIMEOUT_MS`) controls how long the **server-side task
  process** runs before it is killed and the task is retried or failed. A
  client polling timeout does not stop the server task.
- Operators who use `openshell policy set` without a dedicated sandbox can
  replace unrelated policy rules; the script blocks that path unless
  `DEEP_RESEARCH_ALLOW_POLICY_REPLACE=1` is set explicitly.
- Domain detection and discipline-specific rubric generation are not implemented.
  The default rubric is generic and request-specific; custom rubrics must be
  provided by the user for domain-specific evaluation.
- JSON output does not include structured sections, source citations with
  confidence scores, graph-step execution counts, or rubric iteration metadata.
  It contains task metadata and the full result text only.
- Task retries restart the entire task execution; abandoned running tasks are
  not replayed on service restart.

## Third-Party Dependencies And License Notes

The worker container installs Python packages listed in `src/requirements.txt`
and uses the `python:3.11-slim` base image. The repository-level
`THIRD-PARTY-NOTICES` file records the expected notice inventory for those
components. Review the terms of any external search or inference service before
production use.
