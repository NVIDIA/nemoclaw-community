# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

---

## Agent-Specific Instructions

### If you are `main` (the primary agent)

You are text-only. You CANNOT see images with the `read` tool. NEVER use `read` on image files — you will get raw bytes, not visual content.

To analyze any image, delegate to the vision-operator sub-agent using `sessions_spawn`. Always use the full path under `/sandbox/.openclaw-data/workspace/`, which is the shared demo workspace configured for the vision operator:

```json
{
  "agentId": "vision-operator",
  "message": "Use the image tool to inspect /sandbox/.openclaw-data/workspace/red.png, then describe it in detail. /no_think"
}
```

Use `agents_list` to confirm vision-operator is available before spawning.

Delegate ANY task involving images (JPG, PNG, etc.), video frames, or visual content to vision-operator.

When writing files, always use `/sandbox/.openclaw-data/workspace/` as the base path so the main agent and vision operator read and write the same files.

### If you are `vision-operator` (the vision sub-agent)

You ARE the vision-capable agent. You CAN see images. You use the Nemotron-3 Nano Omni model which supports image input.

To analyze an image, use the `image` tool with the **exact file path** provided in your task message. Keep `/no_think` in Omni image prompts; the reasoning checkpoint can otherwise spend the turn in reasoning output instead of returning final content. If your runtime presents images through `read`, `read` is also acceptable, but do not treat raw image bytes as visual understanding.

IMPORTANT:
- The demo shared workspace is `/sandbox/.openclaw-data/workspace/`. ALL reads and writes MUST use this path. `/sandbox/.openclaw/workspace` may exist for the main agent, but it is not the shared vision-operator workspace for this demo.
- When writing output files (e.g. `image-description.md`), always write to `/sandbox/.openclaw-data/workspace/` (e.g. `/sandbox/.openclaw-data/workspace/image-description.md`).
- Do NOT analyze directories. Only pass the specific image file path to `image` (for example, `/sandbox/.openclaw-data/workspace/red.png`).
- Do NOT try to use `sessions_spawn` — you do not have it and do not need it.
- You are the final destination for image analysis tasks. Analyze the image yourself and return your findings directly.
