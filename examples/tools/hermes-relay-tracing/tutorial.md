<!--
SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Inspect Hermes Agent Execution with NeMo Relay

## Overview

This guide picks up after Example 1 in the Quick Start in the README. In the
next section, you will learn how
ATOF, ATIF, and OpenTelemetry with OpenInference provide different views of an
agent's lifecycle and inspect the ATOF event stream and ATIF trajectory from
Example 1. After learning about these traces, you will run Example 2 using the
same environment. In this more realistic task, Hermes reads a travel plan,
finds and verifies a matching conference, and saves a report. You will then
open the run in Phoenix and follow its model and tool calls, timing, token
usage, errors, and captured inputs and outputs.

## Understand the Observability Outputs

These representations describe the same agent run in different ways:

| Representation | What it is | When to use it |
| --- | --- | --- |
| [ATOF](https://docs.nvidia.com/nemo/relay/latest/configure-plugins/observability/atof) | A JSONL stream of agent lifecycle events. Each line records either the start or end of a scope, or a point-in-time mark, with the identifiers and timestamps needed to reconstruct the run. | Use ATOF for low-level debugging or auditing when you need individual lifecycle events, timestamps, and parent-child relationships. |
| [ATIF](https://docs.nvidia.com/nemo/relay/latest/configure-plugins/observability/atif) | A JSON step-based trajectory assembled from agent lifecycle events. It organizes the run into agent interaction steps, tool calls, and observations. | Use ATIF when you need a step-by-step record of the agent's path for human review, offline analysis, or evaluation. |
| [OpenTelemetry](https://opentelemetry.io/docs/concepts/signals/traces/) with [OpenInference](https://github.com/Arize-ai/openinference/blob/main/spec/README.md) | OpenTelemetry represents the agent run as a parent-child hierarchy of spans. OpenInference defines how agent, LLM, and tool spans are labeled and which attributes describe them. | Use this view to explore a run in a tracing tool such as Phoenix and compare model and tool calls, duration, token usage, and errors. |

Both examples save ATOF and ATIF files locally, so you can inspect them
directly. An ATIF tool request shows what the model asked to run, but it does
not confirm the outcome. To verify what happened, inspect ATOF for the matching
tool start and end events and any recorded error. Their shared `uuid` pairs the
events, `parent_uuid` connects the tool call to its parent, and the tool-call
identifier links the model's request to the invocation when the integration
supplies one.

Example 2 also uses [Relay's OpenInference
projection](https://docs.nvidia.com/nemo/relay/latest/configure-plugins/observability/openinference)
to create an OpenTelemetry trace. Relay sends that trace to [Arize
Phoenix](https://arize.com/phoenix/), the observability platform used in this
tutorial, over the [OpenTelemetry Protocol
(OTLP)](https://opentelemetry.io/docs/specs/otlp/). OTLP is OpenTelemetry's
protocol for sending telemetry to compatible backends. Phoenix receives the
OpenTelemetry trace directly; it does not read the saved ATOF or ATIF files.

This tutorial uses Phoenix, but the exported OpenTelemetry trace is not tied
to it. To send the trace to another OTLP-compatible observability platform,
such as [LangSmith](https://docs.langchain.com/langsmith/trace-with-opentelemetry),
you only need to update the endpoint and authentication settings. The setup
and trace view may vary by platform.

Relay supports additional exporters and configuration options. See the
[NeMo Relay observability guide](https://docs.nvidia.com/nemo/relay/latest/configure-plugins/observability/about)
for details about the available outputs and configuration.

> [!CAUTION]
> Traces can include prompts, model responses, tool inputs and outputs, and file
> paths. Review them before sharing.

## Review the Example 1 Trace Files

The Quick Start prints an `Artifacts:` path for the run. That directory
contains:

- `atof/run.jsonl`, the raw, ordered lifecycle event stream.
- `atif/trajectory-*.json`, the run organized into agent steps, tool calls, and
  observations.

### Summarize the Run

To summarize and validate token usage for a saved run, set `RUN_DIRECTORY` to
the path printed by the tutorial:

```bash
HERMES_PYTHON=".tutorial-runtime/venv/bin/python"
RUN_DIRECTORY="artifacts/runs/<timestamp-pid>"
"$HERMES_PYTHON" scripts/summarize_atof.py \
  "$RUN_DIRECTORY/atof/run.jsonl" \
  --require-token-usage
"$HERMES_PYTHON" scripts/summarize_atif.py \
  "$RUN_DIRECTORY"/atif/trajectory-*.json
```

The `Task verified: VALUE=42` line confirms the result. The two summaries show
the model calls, tool calls, token usage, and trajectory steps for the run.

The repository also includes a minimal
[ATOF example](examples/terminal-task.atof.jsonl), its matching
[ATIF example](examples/terminal-task.atif.json), and an
[example walkthrough](examples/README.md) that highlights the key fields.

## Example 2: Find a Conference That Fits Your Travel Plans

Now that you have verified the basic setup, use the same Hermes and Relay
environment for a task that combines file access and web search.

Imagine that you will be in San Diego from June 29 through July 3, 2026, and
want to attend a conference about the theoretical foundations of machine
learning. The included [`travel-plan.md`](conference-task/travel-plan.md) file
lists the dates, location, and subject, but leaves out the conference name.
Hermes must read the plan, search the web for a matching conference, confirm
the dates and location on the official event website, and save the verified
details in a report.

During the run, Hermes uses `read_file`, `web_search`, `web_extract`, and
`write_file`. The runner checks the final answer, saved report, and required
tool calls. Phoenix displays the run as an interactive trace, where you can
inspect the model and tool calls, timing, token usage, errors, and available
inputs and outputs.

This example reuses the Nemotron model and `NVIDIA_API_KEY` from Example 1.
Hermes Agent includes keyless web search, so you do not need a separate search
credential. The runner also starts Phoenix from a pinned Docker image, so you
do not need to install Phoenix. The
[Phoenix Docker guide](https://arize.com/docs/phoenix/self-hosting/deployment-options/docker)
explains this deployment option.

### Run Example 2

Run the following command:

```bash
./scripts/run_conference_research_with_phoenix.sh
```

Phoenix uses port `6006` by default. If that port is already in use, run
Example 2 on another local port. The script does not stop or replace the
existing service.

```bash
PHOENIX_UI_PORT=6007 ./scripts/run_conference_research_with_phoenix.sh
```

Because the search service is public, the task can fail if the service
rate-limits the request.

### Verify the Result

The runner checks both the task result and the trace outputs:

- The final answer is `COLT 2026`.
- The saved report identifies `COLT 2026`, June 29 through July 3, 2026, San
  Diego, and an official `learningtheory.org` source.
- The ATOF event stream contains successful `read_file`, `web_search`,
  `web_extract`, and `write_file` calls.
- The runner creates a nonempty ATIF trajectory.
- Phoenix receives the model and tool spans and reports a positive token total
  for the run.

When verification passes, the script prints the Phoenix URL and the run
directory. The run directory is under
`artifacts/conference-research/nemotron/` and contains the response,
verification report, ATOF events, and ATIF trajectory. The file tools can read
the task input and write only to a separate output directory. The Docker
container never receives your API key.

### Review One Verified Run

In one verified run with Hermes Agent `0.21.1`, NeMo Relay `0.8.3`, and Nemotron
3.5 Lightning, the
[result summary](results/conference-research-nemotron-3.5-lightning.json)
records the configuration and verifier result. Phoenix received five model
calls, four tool calls, no tool errors, and 31,554 tokens over 46.3 seconds. It
did not calculate a cost because no pricing information was available for the
model.

### Explore the Run in Phoenix

Open Phoenix in your browser at `http://localhost:6006/projects`. If you
selected a different port, replace `6006` with that port. The trace tree
appears on the left. Select a model or tool call to view its details on the
right.

Start with the first and final model calls. The first call shows the request to
read the travel plan, find the matching conference, verify it on an official
website, and save a report. In a successful run, the final call returns
`COLT 2026`.

Expand the trace tree and select the calls between the first and final model
calls in order. A model call shows the request Hermes sent, the model's
response, and any tool calls requested by the model. A tool call shows the
arguments generated by the model and the result returned by the tool. For a
failed run, start with the final completed span and look for an error, a missing
tool call, or an unexpected result.

Compare the token counts and durations shown beside the model calls. If one
call stands out, open it and check its request for repeated context. Then check
the preceding and following tool calls for repeated work or errors. A large or
slow call deserves investigation, but it is not automatically inefficient.
Phoenix also shows estimated cost when it has pricing information for the
model.

Select the first model call to inspect the conference request and the
`read_file` request generated by the model.

[![Phoenix trace showing the user's research request and the first read-file call](screenshots/phoenix-nemotron-user-query.png)](screenshots/phoenix-nemotron-user-query.png)

Select the `web_search` span to inspect the query and the sources returned to
Hermes.

[![Phoenix web-search span showing the query and returned sources](screenshots/phoenix-nemotron-web-search-span.png)](screenshots/phoenix-nemotron-web-search-span.png)

Select the `write_file` span to verify the report content, destination, and
successful write result.

[![Phoenix write-file span showing the saved conference report and successful result](screenshots/phoenix-nemotron-write-file-span.png)](screenshots/phoenix-nemotron-write-file-span.png)

Select the final model call to inspect the response, duration, and token usage.

[![Phoenix final model span showing the verified response, duration, and token usage](screenshots/phoenix-nemotron-final-llm-span.png)](screenshots/phoenix-nemotron-final-llm-span.png)

### Try the Same Task with Another Model

To repeat Example 2 with another model without changing the task or verifier,
copy the model profile template:

```bash
cp config/model_profile.env.example model-profile.env
```

Update `model-profile.env` with the model, endpoint, API mode, and the name of
the environment variable that holds your provider API key. Add that variable
and its value to `keys.env`, then run:

```bash
./scripts/run_conference_research_with_phoenix.sh \
  --model-profile model-profile.env
```

The runner supports the `chat_completions`, `anthropic_messages`, and
`codex_responses` API modes provided by Hermes. The selected endpoint must
support tool use. These live-search runs are useful for exploring agent
behavior, not ranking models. For a controlled comparison, follow
the **Use Traces to Evaluate a Harness Change** section below.

#### Claude Sonnet 5 Example

These screenshots show Example 2 with Claude Sonnet 5. The task and verifier
remain unchanged; only the model configuration changes. Use the traces to
compare the sequence of model and tool calls, token usage, duration, errors,
and any cost reported by Phoenix. You can configure your own compatible model
endpoint to repeat Example 2. The
[result summary](results/conference-research-claude-sonnet-5.json) records the
configuration and verifier result. Phoenix reported five model calls, five tool
calls, no tool errors, 60,059 tokens, and an estimated cost of `$0.053960`.

The trace tree shows the total estimated cost above the span list and token
counts beside the model spans. Select the image to open it at full resolution.

[![Phoenix trace tree showing total cost, token counts, and model, file, and web spans](screenshots/phoenix-trace-tree.png)](screenshots/phoenix-trace-tree.png)

| Web-Search Call | Final Model Call |
|---|---|
| [![Phoenix web-search span showing the query and returned results](screenshots/phoenix-web-search-span.png)](screenshots/phoenix-web-search-span.png) | [![Phoenix final model span showing the response and model-call metrics](screenshots/phoenix-final-llm-span.png)](screenshots/phoenix-final-llm-span.png) |

## Use Traces to Evaluate a Harness Change

The two examples show how to verify a result and inspect one agent run. To
determine whether a change improves the harness, repeat those checks under
controlled conditions:

1. **Pick a task you can grade automatically.** Decide what result counts as a
   success, then choose one prompt, tool, configuration, or harness behavior to
   change.
2. **Establish a baseline.** Run the current version several times and save the
   verifier results and Relay traces from every run.
3. **Change one thing and run the task again.** Use the same number of runs and
   keep the model version, endpoint, task input, tools, limits, and timeout the
   same. Reuse the seed and sampling settings when the provider supports them.
4. **Compare the outcomes before the traces.** Check how often each version
   completed the task. Then use the traces to understand differences in model
   calls, tool calls, retries, errors, duration, token usage, and cost.
5. **Check that the result holds.** Repeat the comparison with the other models
   or workloads that the change is expected to support.

Treat a change as an improvement only when the result holds across repeated
runs. It should either complete more tasks or preserve task completion while
consistently improving the reliability, latency, or cost measure you targeted.
A single faster run or one run with fewer calls is useful evidence, but it is
not enough to establish an improvement.

Example 2 is useful for learning this process, but it is not a controlled
benchmark because live search results can change. To reuse it for an A/B test,
capture the search responses and give both versions the same fixed responses.

## Stop Phoenix

When you finish, stop and remove the tutorial's Phoenix container:

```bash
./scripts/stop_phoenix.sh
```

If you ran Phoenix on another port, set that port again when you stop it:

```bash
PHOENIX_UI_PORT=6007 ./scripts/stop_phoenix.sh
```

## Troubleshooting

- **NVIDIA API authentication fails:** Confirm that `keys.env` contains a valid
  `NVIDIA_API_KEY` with access to the Nemotron model configured in
  [config/smoke.env](config/smoke.env).

- **Another model cannot authenticate:** The default run uses
  `NVIDIA_API_KEY`. A comparison run uses the credential variable named by
  `MODEL_PROFILE_API_KEY_ENV` in `model-profile.env`. Confirm that `keys.env`
  defines that variable and that its value can access the model and endpoint in
  `model-profile.env`.

- **The tutorial image is unavailable:** Run
  `./scripts/build_tutorial_image.sh`, then rerun the tutorial.
