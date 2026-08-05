---
name: blender-python-api-verification
description: Verify Blender Python properties, enums, operators, animation APIs, and add-on interfaces against the running Blender build before writing or executing uncertain bpy code. Use for any Blender scene edit, render setup, animation, import/export, or add-on task where an API detail could vary by version.
license: Apache-2.0
metadata:
  version: "0.1"
  domain: blender
---
# Verify Blender Python APIs

The visible host Blender process is the source of truth. This installation also
provides the official Blender 5.1 Python API under:

`/sandbox/reference/blender-python-api-5.1`

Use `scripts/search_blender_api.py` with sandbox terminal tools to find relevant
official documentation. The docs cover Blender itself, not OVRTX, OVPhysX, or
other add-ons.

## Required workflow

Before an uncertain Blender mutation:

1. Search the version-matched reference for the type or operator.
2. Make a separate, non-mutating `mcp_blender_execute_blender_code` call to
   inspect the running object, RNA properties, enum items, or operator RNA.
3. Check every uncertain property and enum value. Do not infer API availability
   from an older Blender example.
4. Only then make the mutation in a second Blender MCP call.
5. Return a compact receipt. Do not dump complete RNA schemas into chat.

Do not import `bpy` with sandbox Python. Blender MCP code runs inside Blender on
the host; sandbox code does not.

## Runtime inspection patterns

Inspect an RNA object:

```python
target = bpy.context.scene.display.shading
props = target.bl_rna.properties
name = "type"
result = {
    "blender": bpy.app.version_string,
    "rna_type": target.bl_rna.identifier,
    "property_exists": name in props,
    "readonly": props[name].is_readonly if name in props else None,
    "enum_values": [item.identifier for item in props[name].enum_items]
        if name in props and props[name].type == "ENUM" else [],
}
print(result)
```

Inspect an operator before calling it:

```python
operator = bpy.ops.wm.usd_import
rna = operator.get_rna_type()
print({
    "operator": rna.identifier,
    "properties": [p.identifier for p in rna.properties if p.identifier != "rna_type"],
    "poll": operator.poll(),
})
```

For non-RNA Python objects, use narrowly filtered `dir()` or `hasattr()`.
Prefer direct data API operations over context-sensitive `bpy.ops` calls. If an
operator is required, inspect `poll()` and establish its context explicitly.

## Failure behavior

If the requested API is absent, read-only, has different enum values, or fails
operator polling, stop before mutation and report the observed Blender version
and API shape. Do not retry guessed property names or execute a long script that
mixes discovery with destructive changes.
