## Blender host boundary

This deployment has two separate execution environments:

- Hermes terminal and file tools run inside the OpenShell sandbox and see the
  sandbox filesystem.
- Blender, its add-ons, OVRTX, OVPhysX, and their files run on the host.

For every Blender operation, including scene inspection, Python execution,
rendering, import/export, add-on control, and host file access, use the Blender
MCP tools. Code passed to Blender MCP executes inside the visible host Blender
process and sees the host filesystem. Do not run `bpy` code with sandbox
terminal or Python tools.

Never give Blender a `/sandbox/...` path. Never use sandbox file or terminal
tools to inspect `/home/...`, host `/tmp/...`, Blender outputs, or host runtime
components. A path existing in one environment says nothing about the other.
Keep host-side processing inside Blender MCP when practical. When bytes must
cross the boundary, request an explicit OpenShell upload or download and name
both the source and destination paths.

Before writing Blender Python that depends on an unfamiliar property, enum,
operator argument, or add-on API, inspect the running Blender API through a
non-mutating Blender MCP call. Prefer RNA metadata (`bl_rna`, enum items, and
operator RNA) over memory or assumptions. The running Blender build is
authoritative; the installed Blender API reference is supporting evidence.

Do not interpret missing host binaries, extensions, or files inside the sandbox
as a failed host installation. Use Blender MCP or the guide-installed host
helper for host preflight and execution.
