# Studio settings

Open the studio on localhost and select the Settings gear. **Model**, **Location** and **Reset** share one dialog. Switching tabs with the mouse or keyboard preserves unsaved drafts.

## Model connections

For the verified NVIDIA Lightning and Super VL models, thinking is off in the Lounge and on in Open Task. The submitted task's stage is retained through tool calls and navigation. Lightning thinking is capped at 1,024 tokens; the routing judge has a 2,048-token output cap. Custom models keep their existing provider options. Advanced reasoning displays returned text without another model call; thinking can increase response time.

Casey follows the Open Task default until you select a fixed NVIDIA model on Casey’s badge. When following Switchyard, Casey calls the configured **Capable** model directly, including direct messages, planning, retries and reviews. For other agents, Switchyard favors **Capable** for implementing, debugging or testing code. Greetings, straightforward lookups and purely mechanical edits can use **Efficient**. Each agent keeps its selected text model through the same job's tool calls.

1. Enable **Local** and/or **External Endpoint**, then choose **Configure**.
2. For **External Endpoint**, choose the provider, confirm the endpoint and enter the matching API key. Click **Connect** to load its models. Choose a model and click **Use model**. A verified connection opens directly to its model list.
3. For **Local**, enter the model server endpoint, choose a model and click **Connect & enable**.
4. Under **Models**, choose the **Open Task** connection, then **Save changes**. Existing preferences are preserved.
5. **Hired agents** sets the default connection for Hiring and the Agent Lounge. With both connections ready, it starts on Local. With one ready, it uses that connection. A model chosen directly in Hiring or Edit agent takes precedence.

The selectors show **Local** or **External Endpoint**, whichever connection new work will use. There is no Automatic option. Casey and Open Task standby specialists prefer External Endpoint by default; opening Settings or refreshing connection status does not change saved preferences. Earlier agents without an individual model keep their previous shared default, available in the collapsed **Shared default** section. Saved manual choices take precedence. When upgrading a data directory that predates shared connections, the selected host provider is retained. For Open Task and earlier agents using the shared default, an unavailable preferred connection falls back to the other ready connection for new requests. When a fallback is needed, the selector shows the connection in use and the status explains which preferred connection is unavailable. Unsaved selections stay visible with **Save to use** until saved. If neither is ready, Settings shows **No connection ready**. Active model requests are not replayed on another connection.

Open Task shows a warning when using Local because complex tasks may take longer or produce less reliable results. Start your model server separately, then connect its endpoint in **Settings → Model → Local**.

The demo manages its own skill files. Native skill file watching and autonomous skill reviews are disabled: repeated file-change notifications can rebuild metadata for every retained agent and delay the gateway. Unchanged files are left untouched; registration publishes an instruction revision when content changes. After editing skill files directly outside the app, re-prepare the agent or restart the runtime.

Registration skips the native configuration update only when all proposed fields already match the saved configuration, including the instruction revision, model connection and complete tool lists. The next request still verifies that the running gateway has loaded the expected identity. Real edits and Casey's tool-mode transitions continue through the native update path. This avoids redundant registration overhead; it does not prewarm models or guarantee faster generation.

Host-side profiling with Python logging at INFO includes registration lock/total time and readiness time/discovery counts. These entries contain no prompts, file contents or credentials; model-request time remains separate.

| Provider | Default endpoint | OpenClaw API format |
| --- | --- | --- |
| NVIDIA NIM API | `https://integrate.api.nvidia.com/v1` | `openai-completions` |
| OpenAI | `https://api.openai.com/v1` | `openai-responses` |
| Anthropic | `https://api.anthropic.com` | `anthropic-messages` |
| Local / on-prem | `http://127.0.0.1:8000/v1` | `openai-completions` |

The NVIDIA endpoint is editable. If your deployment uses another supported NVIDIA endpoint, enter its URL and matching key, then select a model from that catalog. Changing endpoints clears the model selection and requires a key for that destination; existing saved connections retain their endpoint. Model catalogs and image/reasoning options can differ between services. OpenAI and Anthropic endpoints remain fixed. The key field shows whether this provider and URL have a key in `api.json`. Browser-entered keys last for the tab’s credential lease. See [credential storage](session-credentials.md).

An enabled, unconfigured Local connection automatically checks `http://127.0.0.1:8000/v1/models` (or its saved endpoint). If exactly one supported model is advertised, Studio uses that model ID with at most 32K context by default, bounded by the server’s advertised limit. Detection repeats in the background, so vLLM can start after Studio. Multiple advertised models require a choice in Settings. Explicit model choices, disabled connections and routing preferences are preserved. Discovery does not launch or take ownership of vLLM.

Local endpoints must be reachable from the app/OpenClaw host, not from the presenter's browser computer. Use localhost or a private IP ending in `/v1`. Ollama normally uses `http://127.0.0.1:11434/v1`. The selected model must appear in the server's catalogue and support the tools needed by the demo. Readiness verifies model availability, not successful completion of every task.

## Scenario models

- **03 Open Task:** Casey and the backups follow the scenario connection. On NVIDIA, choose **Hired + Standby** and expand **Standby specialists** to change a backup’s model. Return to Hired only before starting if needed. Local and other providers use the shared connection model for Casey and backups. Hires follow the stage rules below in both modes.

**Models & connection** opens these shared settings. Connection changes are blocked while queued or active work is present; per-agent choices are locked while the team is busy or resetting. See [Open Task models](plan-team-models.md).

## Per-agent models for hired agents

Expand **Model** below **OpenShell protection**, then search by model or provider name. Results stay in a compact scrollable list; unavailable connections are disabled. New agents default to connected Local. If Local is unavailable, all roles, including Data analyst, use the configured External Endpoint default model (**Model routing (NeMo Switchyard)** on eligible NVIDIA connections). The collapsed summary shows the selected model, so presenters can hire without opening this section. If neither connection is ready, it shows **Not connected** and hiring waits for a connection. Explicit model choices and existing agents are preserved. The section starts closed and is available in **Edit agent** too.

In Open Task, Local hires use the connected External Endpoint default; hiring API choices stay unchanged. Select an idle hire's model badge to set an independent Open Task choice, including Local. **Automatic** restores the stage rule. Returning to Lounge restores the original hiring choice. Saved plan records remain historical; active or reserved agents cannot change models.

An existing offline model remains selected. You can still edit that agent’s name or persona without changing its model; choosing a different model requires a ready connection.

Automatic routing uses the available source when only one is ready. Explicit API choices and manual Open Task overrides never silently switch when unavailable. Lounge chat and Heartbeat use the hiring preference; tasks, result reactions and direct Open Task messages use the Open Task choice. The request's stage is retained during navigation. Model selection does not change tools or OpenShell protection.

## Context and output budgets

- **Context: 32,768 tokens by default.** This is the capacity the demo configures for one agent session: instructions, conversation, tool results and room for the reply. Agents have separate sessions even when they use the same model.
- **Output: at most 16,384 tokens per response.** Shared connections use `min(16,384, context / 2)`. For example, a 16K context allows at most 8K output. This is a cap, not a target reply length.
- These are application settings, not fixed OpenClaw or OpenShell limits. The model server must support the configured context and output. A larger-capacity model does not require increasing the demo budget.

Open **Configure → Advanced → Context limit** to inspect or change the budget. Advanced options start collapsed. The editor retains an existing provider context value or uses 32K for a new provider; it does not infer the model's capacity from its name. Set up local servers with sufficient context before presenting. This setting does not resize Ollama's `num_ctx` or vLLM's server context.

The runtime bounds excerpts and enables context compaction with a pre-call check. Recent-context retention scales to one quarter of the smallest configured context, capped at 8K tokens. Current workflow limits are deliberately different:

- Native web fetch defaults to 3,000 characters, with a 4,000-character cap.
- Scout research permits at most two searches with three results each, or five bounded page reads.
- Vera review permits eight reads, 120 lines per read, 5,000 characters per returned excerpt and 18,000 retained source characters. Duplicate ranges are blocked.
- Other Open Task specialist file work permits up to 16 reads, 120 lines per read and 24,000 retained source characters. Cody's focused recovery reads use 80-line ranges.
- Open Task final-answer validation caps the answer at 24,000 characters; this is not a uniform per-turn or per-tool budget.

Saved files stay intact, writes and edits remain available, and shortened excerpts disclose missing coverage. These measures reduce context growth but cannot guarantee that every request fits. Generating a large file also adds its code to the conversation, so a context error can occur after the file was saved. The executable sources of truth are `runtime/research-guard/index.mjs`, `scripts/collaboration_prompts.py`, `scripts/collaboration_plan.py` and `apply_context_limits()` in `scripts/runtime_settings.py`.

Open Task keeps shared evidence, access and handoff rules in every turn. Detailed research and coding instructions are included according to each specialist's equipped skills; multi-skilled hires receive both when applicable. Casey receives a compact research-budget summary for planning. This scopes instructions without changing team selection, tool permissions, task documents or handoff delivery.


Open Task supports one fresh-conversation recovery after a context overflow. Open Task reuses saved files and observed evidence, with focused reads instead of regenerating the whole output. Recovery shares each workflow's existing single repair allowance and respects cancellation and the remaining time budget. It does not increase the model context, switch models or reset user data. A second failure stops with partial results. Inspect saved work, narrow the task or reset the appropriate conversation/scenario before trying again.

## Optional host API keys

Set each provider’s endpoint and key in `api.json` beside `bac`. Selecting that provider in Settings reuses the matching key. [File format and startup](docker-setup.md#provider-keys)

## Location and Reset

**Location** sets the default city, initially Zurich. Explicit locations in a task take precedence. Saving updates the managed location for hired agents and every prepared specialist in Open Task without changing memory, permissions or credentials.

**Reset** offers Remove agents for Stages 1/2, Reset Open Task, and Reset all for both team work and hired agents. Reset Open Task also restores built-in standby specialists to their default model choices. Hired-agent model choices and Local/External Endpoint connection settings remain. The team utility Reset clears only Open Task.

**Resources → About Multi-Agent Studio** shows the build version, release notes and issue report.

## Access and verification

Localhost and trusted-LAN visitors have the same controls. The server still checks browser sessions, agent ownership, request origins and CSRF tokens. The demo does not distinguish remote attendees from presenters. Model inference and OpenShell tool permissions are separate.

## Demo session cleanup

Only one browser session can use the demo at a time. Other browsers, private windows and devices show **The demo is already open** before creating a session or preparing agents. Tabs in the same browser at the same address share the existing session and agents; refreshes preserve them. Close all demo tabs in that browser, then select **Try again** in the new browser. A lost connection or browser crash releases access after 90 seconds without requests, once running work finishes. This access timeout does not delete data.

Each browser session owns its personal agents and its Open Task team. Open tabs renew activity automatically. After 60 minutes without authenticated requests, the app cancels pending requests and scheduled follow-ups, then removes that session's agents, native runtime registrations, sandboxes, conversations and workspaces. Running tasks, artifact writes and policy updates finish before cleanup starts. Active browsers and their standby teams are unaffected.

Cleanup runs in the background, records completed targets, and resumes after partial failures or a server restart. A returning expired browser starts a new empty session; model requests are never replayed. Model connections and host settings are not part of session cleanup.

`./bac start` on the Docker deployment still starts fresh by default. `./bac start --keep-data` and the Mac source preview preserve data on restart, giving saved browsers 60 minutes to reconnect; abandoned sessions are then retired. The Mac preview runs `./bac dev preview` (or `scripts/serve.py`), so it does not execute Docker's fresh-start reset.
