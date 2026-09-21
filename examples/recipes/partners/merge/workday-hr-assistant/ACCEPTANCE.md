<!-- SPDX-FileCopyrightText: Copyright (c) 2026 Merge. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Acceptance checks

The completed items below record contributor evidence from the original runs.
The latest second-host checks below were rerun after the verification fixes.

Record actual evidence, not expected outcomes. Use synthetic data in an
authorized test tenant. Keep credentials, one-time links, and tenant or user
identifiers out of public output, including screenshots.

`scripts/verify.sh` automates the boundary, read, and key-scope checks and exits
non-zero when an executed case misses its expected outcome. The items below that
a script cannot establish are listed separately.

## Completed

- [x] Record the NemoClaw, OpenShell, and OpenClaw versions used for evidence.
- [x] Create a Tool Pack containing only the six hr-reader tools, and confirm by
      re-reading the pack that the tool filter applied.
- [x] Issue a runtime-only access key bound to that pack and Registered User,
      with an expiry, and confirm it carries no management scope.
- [x] Register the Tool Pack with the sandbox using that runtime key.
- [x] Confirm credential resolution on the wire, and that the agent
      configuration carries the OpenShell placeholder rather than the key.
- [x] Confirm tool discovery reports exactly the intended tools, including any
      protocol or meta-tools.
- [x] Confirm the reader tool returns live tenant data over MCP.
- [x] Confirm the agent completes the same read through the sandbox, using the
      registered inference route.
- [x] Confirm an excluded tool is neither advertised nor accepted, and that the
      refusal is an authorization decision rather than a credential failure.
- [x] Confirm a direct instruction to use excluded tools produces a refusal that
      names the missing capability, with no write performed.
- [x] Confirm the runtime key cannot create a Tool Pack (case 6).
- [x] Confirm the runtime key cannot address a Tool Pack it is not bound to
      (case 7).
- [x] Capture terminal evidence of a passing run with identifiers replaced.
      Results are recorded below. Presentation captures are linked from the PR
      description and are excluded from the implementation files.
- [x] Narrow the Workday OAuth application credential to the four functional
      areas the six tools need. Operator-completed reauthorization is recorded
      below; token grants were not independently introspected.
- [x] Repeat setup on a second host, on a different operating system, processor
      architecture, and inference provider from the first. The second-host run
      recorded `passed=6 failed=0 skipped=2`; cross-pack access and revocation
      were skipped. Recorded on macOS 15 on Apple Silicon against an
      OpenAI-compatible gateway, and on Ubuntu 22.04 on x86_64 against a directly configured
      OpenAI-compatible provider.

- [x] Rerun the corrected verification script on the second host. Result:
      `passed=6 failed=0 skipped=2`. The two skipped checks were verified
      separately: revocation before key replacement, and agent tool use through
      transcript inspection.
- [x] Run the cross-pack check on the second host against another existing pack
      outside the runtime key binding. The companion pack was no longer present.
      Agent Handler returned HTTP 404 with JSON-RPC code `-32601` and message
      `Resource not in API key scope.` Generic 404s do not pass this check.
- [x] Revoke the active runtime key in the dashboard and run
      `EXPECT_REVOKED=1 bash scripts/verify.sh` on the second host. Result:
      `passed=1 failed=0 skipped=0`, HTTP 403. Issue a replacement with
      `runtime:all`, one reader pack, one Registered User, and an explicit expiry;
      register it and confirm credential resolution returns HTTP 200.
- [x] Run teardown on the second host. Confirm removal of the native MCP
      registration, policy preset, and credential provider, then restore with
      `onboard.sh` and confirm credential resolution and discovery.
- [x] Inspect the second-host agent transcript after key replacement. The agent
      called `mcp:bundle-mcp:merge-workday__workday__list_workers`; its matching
      tool result recorded `isError: false`. No tenant data is included here.
- [x] Confirm second-host discovery advertises the six configured read tools and
      `authenticate_workday`, with no additional business tools.

- [x] Complete Workday reauthorization against the configured narrowed
      application credential. The operator completed Workday sign-in and
      confirmed connection success. Post-authorization verification returned a
      successful live Workday read. The token's granted scopes were not
      independently introspected.

## Script cleanup verification

After removing the status wrapper and companion-pack creation, all 11 offline
tests passed, including reader-only setup and rejection of an incorrect persisted
allowlist. Shell syntax, license headers, catalog validation, and diff checks passed.
The simplified verifier ran on the second host with `passed=6 failed=0 skipped=2`.
The matching agent tool result at `2026-09-18T18:31:25.726Z` recorded
`workday__list_workers` with `isError: false`. Revocation was covered by regression
tests in this pass; the earlier live revocation result above remains the evidence
for that lifecycle step. Setup was tested offline without creating new live packs.

## Review fixes

The explanatory component row is named `OpenShell boundary` so catalog parsing
uses only the version row. Key creation now sends `expires_in=3600` by default,
with a positive `MERGE_AH_KEY_TTL_SECONDS` override. Both setup scripts prompt
for the management key; issuance scrubs legacy assignments from `.env` and
`.env.bak` before making the request.

After merging upstream main at `d26b655`, all 74 repository Python tests,
14 JavaScript tests, and 14 recipe tests passed. Recipe tests cover default and
custom expiry, invalid TTL rejection, and management-key removal from both files,
including the API-failure path. License headers, catalog metadata and generated
sources, label taxonomy, shell syntax, and diff checks passed. These issuance
checks use mocked API requests; no live runtime key was replaced for this review.

## Outstanding

- [ ] Confirm example name, placement, and provenance with a maintainer.

## Evidence boundaries

These checks cover one role's tool availability, the scope of the key that
reaches it, and credential handling. They do not establish Workday record-level
isolation, resistance to every prompt-injection technique, or prevention of
exfiltration through permitted destinations. No such claim belongs in the pull
request (PR).

Tool availability and record visibility are different boundaries. A role that
can call `list_workers` reaches whatever that Workday account's security groups
permit. Narrowing the Tool Pack does not narrow the account.

The access token carries the functional areas granted to the Workday API client,
which is a separate control from the Tool Pack. The application credential is
configured for four functional areas and the operator completed reauthorization.
A successful read does not independently establish every grant on that token.

If network exfiltration prevention enters scope later, first specify the entire
permitted destination set, including inference and output channels, then verify
a denied request through the permitted adapter runtime. A denied `curl` does not
establish that the agent runtime cannot reach the same destination, because the
policy is scoped to executable paths.
