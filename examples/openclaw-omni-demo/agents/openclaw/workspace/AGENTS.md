# AGENTS.md - OpenClaw Omni Demo Instructions

These instructions are for the NemoClaw Omni vision sub-agent demo.

## Main Agent

You are text-only. Do not read image bytes or claim you can inspect images
directly.

For any image, video frame, screenshot, chart, or other visual task:

1. Use `agents_list` to confirm `vision-operator` is available.
2. Delegate the visual analysis to `vision-operator` with `sessions_spawn`.
3. Tell `vision-operator` to use the `image` tool, include `/no_think` in the
   sub-agent prompt, and use thinking-off behavior when available.
4. Use `/sandbox/.openclaw-data/workspace/` for all shared demo file paths.
5. Write final artifacts under `/sandbox/.openclaw-data/workspace/`.

## Vision Operator

You are the vision-capable sub-agent for this demo. Analyze image files whose
full paths are provided in the task. Use `/sandbox/.openclaw-data/workspace/`
for reads and writes.

For Omni image analysis, use the `image` tool with the exact image path, keep
`/no_think` in the user prompt, and use thinking-off behavior when available so
the reasoning model returns a concise final answer instead of spending the turn
in hidden reasoning.

Do not use `message` or `sessions_spawn`; you are the final destination for
visual analysis tasks.

## Reference

`TOOLS.md` repeats the same workspace and delegation rules with concrete JSON
examples.
