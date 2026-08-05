---
name: blender-host-sandbox-boundary
description: Route Blender, USD, OVRTX, and OVPhysX work when Hermes terminal and file tools run in an OpenShell sandbox but Blender MCP runs inside a host Blender process. Use before any task that inspects the active scene, mentions host or sandbox paths, exports or validates files, or needs artifacts to cross the boundary.
license: Apache-2.0
metadata:
  version: "0.2"
  domain: physical-ai
---

# Blender Host/Sandbox Boundary

Classify every operation by the process that executes it. A path is usable only
when that process can see it.

## Execution surfaces

| Surface | Use for | Visible paths |
| --- | --- | --- |
| Hermes terminal and file tools | Sandbox-local text, scripts, indexes, and uploaded inputs | `/sandbox/...` and sandbox `/tmp/...` |
| Blender MCP | The active scene, `bpy`, add-ons, render engines, and host artifacts | Paths reported by Blender and task-owned host output paths |
| External operator | Copying files across the boundary with `nemohermes sandbox upload` or `download` | Both sides, outside this Hermes session |

Blender MCP code executes in the host Blender process even though Hermes itself
runs in the sandbox. Do not search the sandbox for the Blender executable,
`bpy`, a host add-on, or a host path. Do not ask Blender to open `/sandbox/...`.

## Route the task

1. Read this skill before probing files or software.
2. Classify the task:
   - **MCP-only:** Blender can inspect, edit, export, render, or validate the
     requested result and write it to a task-owned host directory.
   - **Sandbox-only:** every input has already been uploaded and every tool and
     output path is sandbox-local.
   - **Hybrid:** a later step requires a file produced on the other surface.
3. Probe capabilities on their owning surface. Use Blender MCP for `bpy`, the
   active `.blend`, add-ons, OVRTX, OVPhysX, and host file existence. Use
   sandbox tools only for sandbox paths and commands.
4. Execute one surface-local milestone at a time and verify its artifacts on
   that same surface.
5. At a hybrid boundary, stop and return `TRANSFER_REQUIRED`. Hermes cannot run
   the host-side `nemohermes` transfer command from inside its sandbox.

In the normal raw-Blender profile, use `blender-python-api-verification` for
unknown Blender behavior: search the sandbox-local offline reference, then
verify version-sensitive API names through live Blender RNA over MCP. The
bounded handoff profile cannot run arbitrary reference or inspection code; use
only its exposed typed operations and report unsupported capabilities.

## Prefer bounded workflow tools

When the `blender-workflow` MCP server is available, use its typed tools before
Blender's generic execute-code tool:

- `capability_probe` before claiming USD, OVRTX, OVPhysX, or SimReady support;
- `scene_inventory` with a task-owned host JSON path for complete scene detail;
- `usd_export` for a source-preserving Blender export and hash receipt;
- `usd_inspect` for composed-stage metadata, exact prim counts, dependencies,
  and physics-schema counts;
- `artifact_receipts` immediately before reporting any host file as created.

When a typed tool is discovered through `tool_search`, call `tool_describe`
before its first invocation. Search results contain descriptions, not the full
input schema, so never guess or rename argument fields. The path contract is:

- `scene_inventory`: optional `output_path`;
- `usd_export`: required `output_path`, optional `selected_objects_only`;
- `usd_inspect`: required `input_path`, optional `output_path`;
- `artifact_receipts`: required `paths` array.

If a tool returns `invalid_arguments`, call `tool_describe`, correct the named
arguments, and retry once. This is a request validation failure, not evidence
that Blender or the MCP server is unreachable.

A workflow operation exists only when `tool_search` or `tool_describe` exposes
that exact operation. If the bounded tool set has no authoring, packaging, or
execution operation required by the prompt, report that milestone as blocked.
Search once for a missing operation. If no exact match is returned, stop
discovery and report the blocker; do not search again with synonyms.
Do not synthesize nested `tool_call` requests for disabled terminal or file
tools, edit an installed skill to create a helper, or repeat USD inspection
under new filenames; none of those actions add the missing capability.

When `capability_probe` reports that a required schema owner or authoring
runtime is unsupported, finish only independent read-only milestones already
underway, verify their receipts, and then return `BLOCKED`. Do not attempt
dependent overlays, packaging, or validation claims.

Once `scene_inventory` or `usd_inspect` writes its detailed JSON and returns a
successful receipt, treat that evidence milestone as complete. Do not try to
read the host JSON with sandbox file tools, Blender resource URIs, or raw scene
tools. The compact typed result is the conversation summary; the host JSON is
for independent verification and downstream bounded operations.

Keep tool results compact. Write detailed inventories to task-owned host JSON
artifacts and return only counts, paths, sizes, hashes, and blockers in the
conversation. Never dump a full scene or stage inventory into the model
context. Never author a long Python program inside an MCP JSON argument when a
bounded workflow tool exists.

The typed tools intentionally do not emulate SimReady. If `capability_probe`
does not find an enabled supported SimReady add-on, report its authoring and
validation milestones as blocked. Do not invent custom properties and call
them SimReady or nonvisual-material schema fields.

## Transfer receipt

Return this compact structure instead of pretending a file is visible on both
sides:

```json
{
  "status": "TRANSFER_REQUIRED",
  "direction": "host_to_sandbox|sandbox_to_host",
  "source_surface": "blender_host|hermes_sandbox",
  "source_path": "exact path on the source surface",
  "destination_path": "requested path on the destination surface",
  "sha256": "hash measured on the source surface",
  "next_milestone": "what becomes possible after transfer"
}
```

After the external operator confirms the transfer, verify the destination hash
before continuing.

## Failure rules

- If a tool reports `BLOCKED` or says the user denied a command, stop that
  workflow. Do not retry, rephrase, or seek the same outcome with another
  sandbox command.
- Do not use `find /`, inspect restricted host-looking directories from the
  sandbox, or install a second Blender to compensate for wrong-surface access.
- A missing sandbox `blender`, `bpy`, add-on, native runtime, or host file does
  not prove that the host capability is missing. Probe it through Blender MCP.
- If a required capability is unavailable on its owning surface, return
  `BLOCKED` with the exact probe and error. Do not fabricate USD schemas,
  semantic buffers, simulation results, renders, files, or validation passes.
- Preserve the source scene and source assets. Use a task-owned copy or output
  directory for mutating evaluations.
- A final narrative is not artifact evidence. Report a host output only when
  `artifact_receipts` returns `present` with a nonzero size and SHA-256.

## Closeout

Report the selected topology, every execution surface used, host and sandbox
paths separately, artifact hashes measured on their owning surfaces, completed
transfers, remaining transfer receipts, capability blockers, and any claim that
was not independently verified.
