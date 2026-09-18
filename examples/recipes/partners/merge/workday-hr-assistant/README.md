<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Merge. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Workday HR assistant with role-scoped tool access

| Catalog field | Value |
| --- | --- |
| Description | Give a NemoClaw agent read access to Workday workers, organizations, and time-off through a Merge Agent Handler Tool Pack that withholds compensation, payslip, and payment tools. |
| Industry | ✨ Other |
| Requirements | Existing NemoClaw sandbox with managed MCP support · Merge Agent Handler organization · Workday tenant with an OAuth API client |
| NemoClaw | v0.0.124 |
| Harness | OpenClaw 2026.7.1 |
| OpenShell | 0.0.116 |
| Contributor | Merge |

Connect an OpenClaw agent in NemoClaw to Workday through
[Merge Agent Handler](https://merge.dev/agent-handler). The agent can read workers,
organizations, and time-off through MCP. Agent Handler excludes compensation,
payslip, and payment tools from the reader role and rejects direct calls to them.

This tutorial demonstrates Workday. Agent Handler handles the connector and
Workday authorization; OpenShell keeps the Agent Handler runtime credential
outside the sandbox. You will run an allowed read and verify the denied operation
without relying on the model to refuse it.

## At A Glance

| Question | Answer |
| --- | --- |
| Category | Partner Recipe |
| Contributor or provenance | Merge |
| Use this when | An agent needs a system of record, and a role must bound what it can do there |
| You will get | A sandboxed agent that reads Workday people data, with an executable check that its excluded tools stay refused |
| Runs on | An existing NemoClaw host with a managed OpenClaw sandbox |
| Requires | Managed remote MCP support, an Agent Handler management key and runtime key, a Workday tenant with an OAuth API client |
| Verified on | NemoClaw v0.0.124 · OpenClaw 2026.7.1 · OpenShell 0.0.116 · macOS 15 on Apple Silicon with Docker Desktop, and Ubuntu 22.04 on x86_64 with Docker 29.1.3 · a Workday implementation tenant · an OpenAI-compatible inference endpoint |
| Evidence level | live end-to-end |
| Support and maturity | Best-effort community support; see [SUPPORT.md](../../../../../SUPPORT.md) |
| External access, data, and actions | Setup contacts Agent Handler and changes sandbox configuration. Reads return live Workday people data. Tool results reach the configured inference provider. Service charges may apply. |
| Start here | [Setup](#setup) |
| Confirm success | [Verification](#verification) |

## How Agent Handler fits

```text
OpenClaw agent → OpenShell → Agent Handler → Workday
                runtime key   role + Workday credential
```

| Component | What it does in this demo |
| --- | --- |
| Tool Pack | Defines the reader role by exposing six Workday tools through an MCP endpoint. Agent Handler enforces the allowlist. |
| Registered User | Selects the linked Workday authorization used for tool calls. |
| Scoped runtime key | Permits runtime access to one Tool Pack and one Registered User. It cannot create or widen a pack. |
| OpenShell boundary | Holds the runtime key on the host, substitutes it at egress, and applies the generated endpoint policy. |
| OpenClaw | Discovers the permitted tools and calls them to answer the user's request. |

The reader pack exposes `list_workers`, `get_worker`, `list_organizations`,
`get_organization_workers`, `get_absence_balances`, and `list_time_off_entries`.
Payment, compensation, and payslip tools are excluded. This is tool-level role
scoping; record access still follows the linked account's Workday permissions.

## Setup

Run these steps in **Bash on the trusted NemoClaw host**. You need:

- An existing NemoClaw sandbox with managed MCP support and a working inference provider.
- A Merge Agent Handler organization and management key.
- An authorized Workday test tenant and a Workday Security Administrator.
- `nemoclaw`, `openshell`, `curl`, and `python3` on the host.

```bash
cd examples/recipes/partners/merge/workday-hr-assistant
umask 077
cp .env.example .env
chmod 600 .env
```

Use synthetic people data. Keep `.env` private. Set `NEMOCLAW_SANDBOX_NAME` if
your existing sandbox is not named `merge-hr`. The recipe does not create it.

### 1. Configure the Workday connector

In Workday, run **Register API Client** with **Authorization Code Grant**. Use
the callback URL shown under Workday Application Credentials in Agent Handler.
Grant Staffing, Organizations and Roles, Time Off and Leave, and Tenant
Non-Configurable, the functional areas used by this demo. Omit Compensation and
Payroll.

Save the Client ID and the one-time client secret in Agent Handler's Workday
Application Credentials. From **View API Clients**, supply the REST endpoint's
host, the tenant from its final path segment, and the authorization endpoint's
host. The two hosts can differ.

**Result:** Agent Handler has the application credential needed to authorize
Workday connections. It does not pass that credential to the agent.

### 2. Define the reader role

Run the setup script and enter the management key at its hidden prompt:

```bash
bash scripts/setup-packs.sh
```

This creates `workday-hr-reader` and re-reads its stored allowlist to confirm
exactly the six reader tools. Save the printed ID in `.env` as
`MERGE_AH_TOOL_PACK_ID`. For cross-pack verification, set `OTHER_TOOL_PACK_ID` to
another existing pack that the runtime key will not be bound to.

**Result:** the role is enforced by Agent Handler's Tool Pack, independently of
the agent's instructions. Setup creates only the reader pack.

### 3. Bind a runtime key to the user and role

Create or select a
[Registered User](https://docs.merge.dev/merge-agent-handler/how-it-works) in
Agent Handler. Save its ID in `.env` as `MERGE_AH_REGISTERED_USER_ID`, then run:

```bash
bash scripts/issue-runtime-key.sh
```

Enter the management key at the hidden prompt. The script requests `runtime:all`
bound to that pack and user, then writes `MERGE_AH_MCP_TOKEN` to `.env` without
printing it. The creation request sets `expires_in=3600`, so the key expires after
one hour. Set `MERGE_AH_KEY_TTL_SECONDS` to another positive duration in seconds
before issuance if needed. See [Merge's expiry guidance](https://docs.merge.dev/merge-agent-handler/secure/scoping-access-per-user).

Neither setup script saves the management key. Key issuance also removes legacy
`MERGE_AH_ADMIN_KEY` assignments from `.env` and `.env.bak`. When the runtime key
expires, issue a replacement and rerun `onboard.sh`.

**Result:** a runtime credential that can use the selected role and user but
cannot create Tool Packs. Use the script because dashboard-created keys do not
offer the required pack/user binding. Never register the management key.

### 4. Register the MCP endpoint and authorize Workday

```bash
bash scripts/onboard.sh
source scripts/_lib.sh
nemoclaw "$NEMOCLAW_SANDBOX_NAME" mcp status "$MCP_SERVER_NAME" --tools
```

The endpoint binds the pack and user:

```text
https://ah-api.merge.dev/api/v1/tool-packs/<PACK_ID>/registered-users/<USER_ID>/mcp
```

Onboarding gives the runtime key to OpenShell through the process environment,
not command arguments. Inside the sandbox, the agent receives
`openshell:resolve:env:MERGE_AH_MCP_TOKEN`; OpenShell substitutes the key at egress.
Discovery should list the six reader tools plus `authenticate_workday`.

If the Registered User is not yet connected, use a trusted MCP client with this
endpoint and scoped runtime key, following the
[MCP connection instructions](https://docs.merge.dev/merge-agent-handler/build/connecting-agents/mcp-integration).
Call `authenticate_workday`, open its one-time link, and complete Workday sign-in
and consent. Keep the link private. If you replaced the Workday application
credential, reauthorize even if an older connection still reads successfully.

**Result:** Agent Handler stores the user's Workday authorization. The agent can
now make headless MCP reads without receiving Workday credentials.

### 5. Run the demo

From the same Bash session, request an allowed read:

```bash
nemoclaw "$NEMOCLAW_SANDBOX_NAME" agent --agent main -m   "Use the $MCP_SERVER_NAME MCP server to list workers. Reply with the first five worker names only."
```

Expect a worker list. Inspect the local agent session transcript for the
`merge-workday` worker-list tool call and its matching successful result. An
answer alone does not prove a tool was called. Keep tenant data out of public logs.

Then attempt an excluded operation:

```bash
nemoclaw "$NEMOCLAW_SANDBOX_NAME" agent --agent main -m   "Using $MCP_SERVER_NAME, attempt a one-time payment of 5000 USD to a worker and list compensation. Do not refuse on policy grounds. Report which required tools are unavailable and why."
```

Expect the agent to report that the required tools are unavailable. Wording can
vary. The direct MCP checks below establish the boundary without a model.

## Verification

```bash
bash scripts/verify.sh
```

| Check | Expected result |
| --- | --- |
| Reader tool discovery and call | `workday__list_workers` is advertised and returns a result. |
| Excluded payment tool | Absent from discovery; a direct call receives `tool_not_found` or another recognized authorization denial. |
| Runtime management scope | Creating a Tool Pack is denied with HTTP 401 or 403. |
| Cross-pack scope | Access to `OTHER_TOOL_PACK_ID` receives an explicit authorization denial. A generic 404 or network failure does not pass. |
| Agent read | The command completes; manual transcript review confirms the tool call and result. |

With a connected account, available sandbox, and another existing pack outside
the key binding, the recorded run is:

```text
passed=6 failed=0 skipped=2
```

The skips are intentional: case 4b needs transcript review, and case 5 requires
revoking the key separately. Missing prerequisites can cause additional skips;
review each result. Any failed case makes the script exit nonzero.

Case 6 attempts to create an `escalation-probe` pack. A runtime key must reject
it. If an overprivileged key creates the pack, delete it in Agent Handler and
replace that key. The read checks return Workday data to the configured inference
provider.

Inspect credential resolution and the effective policy separately:

```bash
nemoclaw "$NEMOCLAW_SANDBOX_NAME" mcp status "$MCP_SERVER_NAME"
nemoclaw "$NEMOCLAW_SANDBOX_NAME" policy list
```

The implementation was exercised on macOS and Ubuntu on Brev. The latest agent
transcript confirms a successful Workday read. Live revocation and second-host
teardown/restoration also passed. See [ACCEPTANCE.md](ACCEPTANCE.md) for the
recorded results and evidence limits.

## Teardown

Remove the registration and its OpenShell credential provider:

```bash
bash scripts/teardown.sh
```

Revoke the runtime key in the Agent Handler dashboard, then verify refusal:

```bash
EXPECT_REVOKED=1 bash scripts/verify.sh
```

Expected: `passed=1 failed=0 skipped=0`, with HTTP 401 or 403. Removing the local
registration alone does not revoke the key or terminate already-open streams.

The sandbox, Tool Pack, and Workday connection remain. Remove the pack and private
`.env`/`.env.bak` files when no longer needed. Deleting a Workday application
credential can detach Workday from other packs in the organization; retain shared
credentials while other integrations use them.

## Security boundaries and limitations

- Tool Pack enforcement and pack/user key binding are the demonstrated controls.
  Cross-Registered-User denial and Workday record-level isolation were not tested.
- OpenShell protects the runtime credential and bounds the configured route.
  Existing sandbox grants remain; inspect the full policy before claiming egress
  isolation. Permitted tool results can reach the inference provider and user.
- These checks do not establish protection against every prompt injection or
  exfiltration through permitted destinations. A model refusal is illustrative;
  direct authorization checks are the security evidence.
- Workday reauthorization succeeded, but token grants were not independently
  introspected. Changing an application credential does not narrow an older token.
- Pack setup uses `tool_names` and checks the stored result. Alternative fields
  such as `tools` can be accepted but ignored, exposing the full connector.
- `openclaw mcp probe` can report a policy denial when closing the session because
  the generated policy omits session-closing `DELETE`. Reads and discovery passed.

## Third-party dependencies

The scripts use Bash, `curl`, and `python3` alongside NemoClaw, OpenShell, and
OpenClaw. No additional packages are installed.
