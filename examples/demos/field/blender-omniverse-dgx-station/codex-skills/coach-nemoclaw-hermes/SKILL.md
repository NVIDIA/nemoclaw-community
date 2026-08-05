---
name: coach-nemoclaw-hermes
description: Coach a NemoClaw Hermes sub-agent through Blender, OVRTX, OVPhysX, USD, rendering, simulation, and live Blender-control tasks. Use when Codex should delegate specialized execution to Hermes while managing sandbox boundaries, preventing overlapping runs, allowing tool iteration, intervening only on evidence, and independently validating artifacts.
---

# Coach NemoClaw Hermes

Codex is the coach and auditor. Hermes owns Blender, OVRTX, OVPhysX, and other
runtime-facing execution. Codex owns task decomposition, host/sandbox
transfers, milestone receipts, artifact verification, and final reporting.

## Preflight

Before delegation:

1. Verify the NemoClaw sandbox and local inference endpoint are healthy.
2. Verify Blender MCP and only the runtimes relevant to the task.
3. Check for an existing Hermes request using the shared Blender or OV
   services. Serialize shared-runtime work; parallelize only isolated
   sandbox-only work with distinct inputs and outputs.
4. Establish source ownership, a task-owned output root, and whether direct
   Codex-to-Blender fallback is authorized.

```bash
export PATH="$HOME/.local/bin:$PATH"
export NEMOCLAW_SANDBOX_NAME="${NEMOCLAW_SANDBOX_NAME:-ov-blender-hermes}"
nemohermes "$NEMOCLAW_SANDBOX_NAME" status
pgrep -af 'nemohermes .* exec.*(hermes|blenderraw|blenderhandoff).*chat|openshell sandbox exec.*(hermes|blenderraw|blenderhandoff).*chat' || true
```

Do not launch a duplicate request merely because an active request is quiet.

## Execution boundaries

Keep these environments distinct:

- **Codex host:** sees host repositories, source files, and host outputs.
- **Hermes sandbox:** terminal and file tools see `/sandbox`, not host paths.
- **Blender MCP:** runs inside visible host Blender and can see host paths.

Choose the topology before prompting:

- **Raw MCP:** run plain `hermes`; the sticky `blenderraw` profile operates
  visible Blender with exploratory Blender, OVRTX, and OVPhysX tools. The
  explicit `/sandbox/.local/bin/blenderraw` alias remains available. Host paths
  are valid only in Blender MCP operations.
- **Typed MCP:** run `/sandbox/.local/bin/blenderhandoff`; Hermes gets only the
  bounded inventory, USD, and receipt operations.
- **Sandbox-only:** Codex uploads inputs before delegation and downloads outputs
  afterward.
- **Hybrid:** Hermes inspects or exports through Blender MCP; Codex uploads the
  resulting host files; Hermes processes them in `/sandbox`; Codex downloads
  and validates the result.

Use the installed transfer wrapper for every crossing:

```bash
nemohermes sandbox upload "$NEMOCLAW_SANDBOX_NAME" HOST_PATH SANDBOX_PATH
nemohermes sandbox download "$NEMOCLAW_SANDBOX_NAME" SANDBOX_PATH HOST_PATH
```

Verify transferred file counts and SHA-256 hashes. A path in a Hermes response
does not prove that a file crossed the boundary.

## Coaching loop

Simple inspections or renders may be one request. For complex work, use one
measurable milestone at a time, such as:

- read-only scene inventory;
- task-owned export with source and output hashes;
- native render completion;
- native OVPhysX readback;
- replay or review capture;
- package reopen and validation.

Each prompt must include:

- the milestone and completion marker;
- the relevant installed Hermes skill names to use;
- exact host-only and sandbox-visible paths;
- allowed execution surfaces;
- required artifacts, evidence, and blocker behavior.

Give Hermes enough time and tool turns to reason and execute:

```bash
nemohermes "$NEMOCLAW_SANDBOX_NAME" exec --timeout 1200 -- \
  hermes chat -Q --max-turns 30 -q "$HERMES_PROMPT"
```

A new `hermes chat -q` request is a fresh conversation. Carry the prior receipt
and exact transferred paths into the next milestone. Poll an existing command
session until it exits; logs are progress evidence, not a completion receipt.

## Intervention policy

Silence alone is not failure. Intervene only when evidence shows:

- an explicit tool or runtime error;
- a wrong filesystem or execution boundary;
- a missed acceptance criterion;
- a receipt contradicted by artifacts;
- a dropped/truncated tool call or other known agent-stream failure signature.

Diagnose the narrow layer first: wrapper, transfer, sandbox, Blender MCP,
Blender operation, OVRTX/OVPhysX runtime, or artifact validation. Issue at most
one targeted corrected retry before reporting the blocker. Do not repeat a
broad prompt or casually overwrite artifacts still open in Blender or PXR.

Do not bypass Hermes with direct Codex control of Blender unless the user
explicitly authorizes fallback execution. When authorized, report the fallback
and preserve the same source-safety and evidence requirements.

## Validation

Preserve source scenes and source USD layers by default. Keep generated work
under the task root and hash source files before and after mutation-capable
milestones.

Independently validate downloaded host artifacts. Distinguish evidence:

- native OVRTX or OVPhysX receipts/readback are runtime authority;
- Blender viewport images and replay renders are visual evidence;
- Hermes text without matching artifacts is an unverified claim.

Report separately what Codex coached and verified, what Hermes executed, all
artifact paths, versions, elapsed time, validation results, fallbacks, and
remaining blockers or limitations.
