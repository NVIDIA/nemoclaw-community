---
name: ovphysx-host-runtime-boundary
description: Run configured native OVPhysX demos and report host GIF/status receipts when Hermes is sandboxed but the OVRTX/OVPhysX runtime and visible Blender process are on the host.
license: Apache-2.0
metadata:
  version: "0.4"
  domain: physical-ai
---
# OVPhysX Host Runtime Boundary

Use this skill together with the official `ovphysx-drop-contact-acceptance`
skill for this guide's split deployment.

When a task asks for the configured or guide-owned native OVPhysX demo, select
this skill before generic scene-authoring skills. Use the installed helper and
its defaults immediately; the currently open Blender scene is not the fixture
and does not need to contain stairs or rigid bodies.

For that configured-demo request, make one Blender MCP call with exactly this
action and no overrides:

```python
import runpy
from pathlib import Path
helper = Path.home() / ".local/share/nemoclaw-blender/ovphysx_host_helper.py"
runpy.run_path(
    str(helper),
    init_globals={"OVPHYSX_REQUEST": {"action": "run_configured_demo"}},
)
```

Do not pass `fixture`, `output_dir`, `body_prims`, or the words from the user
request as path overrides. The helper reads the configured absolute host paths
and returns the final native simulation and GIF receipt in one bounded action.

## Topology

The always-on Hermes SOUL contains this deployment boundary. This skill adds
OVPhysX-specific handling, but the same rule applies to every Blender task: use
Blender MCP for Blender operations and host file access; sandbox terminal and
file tools cannot see the Blender host filesystem.

- Hermes and the installed public OV skills run inside the OpenShell sandbox.
- Visible Blender, the installed add-on, `ovphysx_grpc_server`, and the
  `ovphysx_bridge_client` native extension run on the host.
- Blender MCP is the approved control path from Hermes to host Blender.

The standard workflow does not copy the OV checkout or native runtime into the
sandbox. Source-analysis tasks may add a sandbox-local checkout separately.

The native OVPhysX binary and extension are not expected under `/sandbox`.
Their absence there does not prove that OVPhysX is unavailable. Do not run the
standalone native probe directly with sandbox Python and do not ask the user to
copy native runtime libraries into the sandbox.

## Installed helper

Use the guide-installed host helper instead of constructing Python programs,
reading host files from the sandbox, or copying native results across the
boundary. The helper is additive to the OV add-on and is installed at:

`~/.local/share/nemoclaw-blender/ovphysx_host_helper.py`

Invoke it only through the Blender MCP tool named
`mcp_blender_execute_blender_code`. If that tool is not visible yet, use tool
search for `blender execute code`, then call the discovered Blender MCP tool.
Pass the following snippet as that tool's `code` argument, changing only the
request dictionary:

```python
import runpy
from pathlib import Path
helper = Path.home() / ".local/share/nemoclaw-blender/ovphysx_host_helper.py"
runpy.run_path(str(helper), init_globals={"OVPHYSX_REQUEST": {"action": "preflight"}})
```

Do not run this snippet with sandbox `terminal`, `execute_code`, or a temporary
Python file. Those tools execute inside `/sandbox` and cannot see the installed
host helper. A successful helper action always appears as a
`mcp_blender_execute_blender_code` tool call.

Supported actions are:

- `run_configured_demo`: run the complete configured demo and return its final
  compact native simulation and GIF receipt. Prefer this for the guide demo.
- `preflight`: inspect the installed host add-on and runtime.
- `prepare`: run the configured fixture preparation script on the host.
- `preview`: import the configured USD into visible Blender and render its
  starting state.
- `simulate`: run native OVPhysX and write sampled authoritative poses.
- `replay`: render those native samples in visible Blender and create a GIF.
- `status`: return compact simulation and replay receipts.

For a complete request, call the needed actions in that order. Each action
returns a compact JSON receipt. Do not fetch or print the complete pose timeline
or native diagnostics through MCP.

The helper owns a dedicated Blender scene for each active fixture. Repeated
`preview` and `replay` calls for the same fixture reuse that scene and restore
its imported transforms before applying new samples. Do not clear the scene or
re-import the fixture manually between helper actions.

The installed configuration supplies demo defaults. For another task, put only
the necessary overrides in the request: `fixture`, `body_prims`, `output_dir`,
`steps`, `sample_every`, `fps`, `device`, optional `body_map`, and optional
render settings. A custom fixture must be a host-visible USD file. Scene
authoring and choosing valid body prims remain governed by the upstream
OVPhysX skills; do not guess them.

## Preflight

Call the helper's `preflight` action from the already-open Blender process. It
reports installed add-on diagnostics and resolved host paths without returning
the complete runtime manifest.

Treat the host preflight as blocked only when Blender reports that its installed
runtime is absent, unhealthy, or incompatible. A missing sandbox-local binary
or `.so` is not a blocker in this topology.

## Execution

Use the helper actions for normal execution. `simulate` runs a generic,
guide-owned timeline adapter against the upstream add-on API and installed
runtime without changing either one. It samples complete body states at bounded
intervals and writes `pose-timeline.json`, `ovphysx-report.json`, and a compact
`status.json` under the host output directory. `replay` accepts only a timeline
labeled `native-ovphysx-readback`, renders each authoritative sample, and
labels the output `blender-replay`.

Never use sandbox `read_file`, `terminal`, or `write_file` on `/home/...`
paths. Never ask Blender to open a `/sandbox/...` path. If the installed helper
is missing, report that setup blocker instead of recreating it ad hoc.

For Blender Python properties, enum values, operators, and animation APIs, use
the `blender-python-api-verification` skill and inspect the running API through
Blender MCP before mutation.

Do not substitute Blender rigid bodies, keyframes, or inferred motion for a
failed native run. Render or encode a GIF only from authoritative OVPhysX pose
readback, and label the rendering path accurately.
