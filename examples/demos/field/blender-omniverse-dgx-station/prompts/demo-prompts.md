# Demo Prompts

Use the direct prompts from the Hermes dashboard or `hermes` CLI. Use the
coaching prompts in Codex after completing the supplementary Codex setup.

## Ask Hermes Directly

Inspect the visible scene:

```text
Inspect the current Blender scene. Tell me the file name, render engine, active
camera, object count, and whether OVRTX and OVPhysX are ready. Do not modify it.
```

Render a beauty shot:

```text
Render the current scene as a beauty shot with OVRTX. Preserve the scene and
report the host PNG path.
```

Load and render another scene:

```text
Load SCENE_PATH in the visible Blender window and render it as a beauty shot
with OVRTX. Preserve the source file and save the result under OUTPUT_DIR.
```

Run the prepared physics demo:

```text
Run the configured native OVPhysX stair-drop demo. Create a GIF of the blocks
falling down the stairs and report the native simulation status and host GIF
path.
```

Observe the physics workflow in stages:

```text
Prepare the configured OVPhysX stair-drop demo and show the starting scene in
visible Blender. Do not run the simulation yet.
```

```text
Run the prepared scene with native OVPhysX and record authoritative poses. Do
not render the replay yet; report whether native simulation passed.
```

```text
Replay the recorded native poses in visible Blender and create a GIF. Report
the host path and distinguish the native simulation from the Blender replay.
```

## Ask Codex To Coach Hermes

Render example:

```text
Use $coach-nemoclaw-hermes. Coach Hermes through this task: render the current
Blender scene as an OVRTX beauty shot. Delegate the Blender and OVRTX work to
Hermes, avoid overlapping Hermes runs, allow it enough time to finish, and
verify the resulting host PNG. Do not control Blender directly unless I
authorize fallback execution.
```

Physics example:

```text
Use $coach-nemoclaw-hermes. Coach Hermes through this task: run the configured
native OVPhysX stair-drop simulation and create a GIF of the blocks falling
down the stairs. Delegate runtime work to Hermes, prevent overlapping runs,
allow it enough time to iterate, and verify the native receipt and host GIF.
Do not control Blender directly unless I authorize fallback execution.
```

Reusable template:

```text
Use $coach-nemoclaw-hermes. Coach Hermes through this task: TASK.

Delegate Blender and Omniverse execution to Hermes. Prevent overlapping Hermes
runs, respect host and sandbox filesystem boundaries, and allow long-running
tool work enough time to complete. Use measurable milestones when the task is
complex. Independently verify the returned host artifacts and native runtime
evidence. Do not control Blender directly unless I authorize fallback
execution. Report what Hermes executed, what you verified, and any blocker or
unverified claim.
```
