# Live Multi-Agent Studio runtime

## Execution path

Hiring creates an agent with its own identity, instructions, skills and workspace. A Lounge message goes to that agent through OpenClaw. In Open Task, a message to Casey starts a conversation. A message beginning with `/goal` starts a team job. Selecting a room or opening Mission Control does not dispatch work.

## Agent collections and ownership

The browser session identifies the participant. Each agent-scoped request selects an agent that participant owns. Tabs in the same browser session share the collection, but track their selected agents separately. Agents, documents and saved results survive room changes. See [session lifetime and reset](runtime-settings.md#demo-session-cleanup) and [credential storage](session-credentials.md).

## Explicit team requests with /goal

The job captures the team mode and available hires when submitted. Casey chooses up to three suitable specialists. **Hired only** uses the attendee's hires. **Hired + Standby** also permits built-in specialists. The protected standby researcher **Shell** participates when explicitly named.

Each specialist gets an assignment, its expected result and relevant inputs. Later specialists can use files delivered by earlier ones. A request for independent review requires another suitable agent. If the team cannot produce the core deliverable, Casey should explain the missing capability before dispatch. Failures during work can leave useful partial results and identified gaps.

Open Task finishes as soon as the result is ready. The team shares an initial seven-minute execution budget across planning, specialist work and review. Waiting for permission pauses that clock. Stop prevents further dispatch; a native operation already underway can take time to settle. See [OpenShell in Open Task](openshell-open-task.md) for retry, timeout and cancellation behavior.

## Shared connections and scenario models

New hires prefer a connected local model in the Lounge. In Open Task, local hires follow the available external default unless overridden. Explicit external model selections are preserved. Returning to the Lounge restores the hiring choice. Casey and standby specialists inherit the configured Open Task connection and model. See [team and model selection](plan-team-models.md), including NeMo Switchyard and image routing.

## What the UI observes

- **Mission Control** shows the saved plan, assignments, handoffs and final response. A planned step can remain uncalled. Activity reports observed tool calls and elapsed time.
- **Advanced reasoning** displays text the model provider returned for the authorized job. Availability varies by model and connection. Opening the panel adds no model call. Recorded model badges identify the model used when telemetry is available.
- **Results** shows saved artifacts from the selected job. **Preview webpage** opens generated HTML in an isolated frame with network access restricted. A saved file confirms delivery; it does not establish that the page passed a browser test.
- Any closing reactions from idle hires are personal comments. They do not change the deliverable or count as independent reviews.

## Web access and OpenShell

Standard research agents can use search and URL-fetch tools according to their skills. Protected agents perform supported web reads inside their OpenShell environment. Policies apply per agent. A URL suggested for approval can appear before a blocked request is observed. Mission Control requires native denial evidence for a permission pause.

Use the [demo journey](../DEMO_WORKFLOW.md) for the demonstration and [OpenShell in Open Task](openshell-open-task.md) for the website approval workflow. The Docker deployment supplies the runtime. The optional host-development installation has its own [OpenShell setup](ubuntu-setup.md#openshell-for-protected-personal-agents).

## Storage and deployment

SQLite stores jobs and ownership. Native agent workspaces hold instructions, inputs and generated files. Browser-entered keys have a session lease; `api.json` keys are stored separately on the host. The [Docker guide](docker-setup.md) covers mounts, backup limits and exactly which commands clear data.

The [runtime lock](../docker/runtime-lock.json) defines the shipped OpenClaw and OpenShell versions. For module boundaries and compatibility with older saved data, see [architecture](architecture.md). Follow the [verification steps](../README.md#verification) on your host.
