# Multi-Agent Studio architecture


## Runtime path

```text
Browser → Python API + SQLite queue → OpenClaw gateway → selected model endpoint(s)
                                   ↳ host tools, or OpenShell for protected hires and the Shell standby
```

The app owns accounts/agent selection, durable jobs, team orchestration, validation and rendering. OpenClaw owns native agent execution, file/tool calls and conversation sessions. Hires keep their Lounge model and optional Open Task override. Without an override, Open Task promotes Local to the connected API default and preserves hiring API choices. Routing follows the submitted request, not later navigation; Casey and backups use the scenario connection. Agent contexts remain separate; the scene visualizes observed app events rather than deciding task execution.

## Main code boundaries

| Area | Files |
| --- | --- |
| Single operator entry point | `bac`, `scripts/manage.py` |
| Service/model lifecycle | `scripts/ops_common.py`, `scripts/ops_deploy.py`, `scripts/ops_runtime.py`, `scripts/ops_llm.py` |
| HTTP and ownership checks | `scripts/serve.py` |
| Jobs, profiles, persistence | `scripts/studio.py` |
| Native runtime, activity and files | `scripts/agent_runtime.py`, `scripts/agent_activity.py`, `scripts/agent_documents.py` |
| Provider-returned reasoning | `scripts/model_reasoning.py`, `src/studio-crew.js` |
| Open Task planning, handoffs and reactions | `scripts/collaboration_plan.py`, `scripts/collaboration_prompts.py`, `scripts/visitor_teams.py`, `scripts/plan_handoff.py`, `scripts/plan_revision.py`, `scripts/crew_roundtable.py` |
| Build identity and support diagnostics | `scripts/build_info.py`, `scripts/diagnostics.py`, `src/studio-diagnostics.js` |
| Shared connections and credentials | `scripts/model_connections.py`, `scripts/scenario_models.py`, `scripts/runtime_settings.py`, `scripts/session_secrets.py`, `scripts/team_models.py` |
| OpenShell website approvals | `scripts/agent_policy.py`, `scripts/studio_policy.py` |
| Workflow-specific research/read limits | `runtime/research-guard/index.mjs`, `scripts/collaboration_prompts.py`, `scripts/collaboration_plan.py`, `scripts/runtime_settings.py` |
| UI / 3D scene | `src/studio*`, `src/world-*`, `src/campus*`, `src/agent-character.js` |

## Open Task execution and attribution

Lounge and direct specialist chats include the current equipped-skill scope on each turn, including edited personas. A familiar topic does not authorize another kind of work: webpage implementation requires Coding. Page-generation instructions and automatic HTML export are limited to Coding-equipped agents; ordinary conversation and in-scope notes remain available. This is a model-guided role boundary, not an operating-system file restriction.

Casey plans work for up to three specialists. Hired only uses available hired agents; Hired + Standby also permits Scout, Cody, Ada, Iris and Vera. Shell is a protected researcher available when explicitly named. The dispatcher validates captured team mode, identities, tools, dependencies and required handoffs before each call. A substantive assignment must fit the explicitly equipped skill, as well as permitted tools. Naming an agent does not override this boundary. Role suitability is model-guided; tool and policy enforcement are separate. Model claims alone do not prove that a file was saved.

Each worker receives its assignment, selected input files and verified earlier handoffs. Casey checks observed results and has one shared repair/recovery allowance. Partial work remains available when a required contribution fails. Independent review uses a different agent; closing personal reactions are separate opinions.

File-workflow prompts reuse available input text and successful write/edit receipts instead of routine save-confirmation reads. Missing content, uncertain writes, concrete repairs and assigned reviews can still require targeted reads. The application's handoff checks remain unchanged; a saved file does not prove correct content or successful browser execution.

## Results presentation

Casey’s chat and Mission Control show saved assignment reasons and declined named participants. Mission Control also shows actual plan bindings, assignments, handoffs and Casey's review. Old plans without recorded reasons do not gain invented explanations. Results shows the team response and verified saved files, with partial work labeled clearly. HTML previews run in a restricted iframe; file access remains scoped to the authenticated account and selected workspace. Usage & time reports recorded calls and token totals without claiming provider billing accuracy.

Mission Control opens the final response by default and shows the same elapsed/total time as Casey. Advanced reasoning displays provider-returned text only, without another model call. Updates preserve the reader's position; an explicit notice offers a jump to new content.

## Persistence and compatibility

SQLite and workspaces live outside the checkout. The session cookie authenticates the participant; `X-BaC-Agent` selects only an agent they own. Browser-entered model keys are memory-only; `api.json` provider keys are stored separately on the host. Neither is included in browser state or native agent definitions. See [credential storage](session-credentials.md). Native files are separate per personal agent and crew role.

The Lounge shows Ready or Busy from actual work. Open Task reserves selected hires until their calls and result writes finish. Entering Open Task pauses hired Heartbeats without starting model calls. Completed workers stay at their desks while the visitor remains in Open Task. Returning to Lounge brings all hires back; re-entering Open Task seats idle hires on the waiting benches.

Open Task preserves stable role slots and native identities across upgrades. Retired Event Brief slots are never eligible for new tasks or workspace preparation. Its historical database records remain for ownership and safe cleanup; its routes reject new work.

Deletion fences an identity before stopping active work. Cleanup operates only on explicitly owned native agents, sandboxes and workspaces, records partial progress, and retries failures without deleting unrelated resources. Inactive browser sessions retire after 60 minutes. See [session and model settings](runtime-settings.md).

## Polling and performance

While visible, the page checks state every 650 ms during active work and for eight seconds afterward, or every 3.5 seconds when idle. Requests do not overlap; failures back off to 30 seconds and hidden tabs pause polling. `/api/state` authenticates and builds the snapshot before computing its ETag. An unchanged response returns 304 without a history body or UI rebuild. Agent-specific caches and stale-response guards remain in place. Conditional requests save transfer/render work, not the server's state calculation.

A state response lists each exact workspace/query only once and reuses the result for file indicators and reset state. The next poll reads files again, including native writes that bypass HTTP. Listings retain the existing 100-file cap and ordering, but stop path validation/stat calls after that cap. Retired role slots are excluded from current chat queries while their stored rows remain intact. SQLite indexes serve per-owner history and per-role crew chats. Runtime readiness and host metrics have short caches. The scene limits rendering to roughly 30 FPS and pauses expensive work while hidden. Large model inference remains the dominant task latency; these changes do not claim higher model tokens/second.

## Build and development

`scripts/build.py` assembles explicit UI modules, bundled Three.js and local art into `app/index.html`. No old playground code is included and no remote UI dependency is needed. Frontend rebuilds need a browser refresh; backend changes need a restart. `./bac start` manages the Docker distribution. `./bac dev preview` serves a source checkout in the foreground. Advanced Linux `./bac dev start` uses committed release snapshots and user services.
