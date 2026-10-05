<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Shipped artifacts and reference measurements

Three agent improvements the loop produced, so you can promote one without
running the loop yourself. Each is a different surface, and all three deploy by
copying into `agent/`:

| Artifact | Surface | Promote with |
| --- | --- | --- |
| [`candidates/geometry-fidelity-policy/`](candidates/geometry-fidelity-policy/SKILL.md) | a skill | `cp -r` into `agent/workspace/skills/` |
| [`candidates/system-prompt.yaml`](candidates/system-prompt.yaml) | `instructions.system.content` | `cp` over `agent/agent.yaml` |
| [`candidates/subagent.yaml`](candidates/subagent.yaml) | `harnesses...deepagents.subagents` | `cp` over `agent/agent.yaml` |

One measurement accompanies them: `runs.json`, the n=3 comparison of the naive
agent against the skill, from 2026-09-18. The main [README](../README.md) quotes
its three naive-arm scores as the Step 4 baseline; the four-agent table in Step 7
is a separate n=1 out-of-loop measurement, recorded in
[optimization-run.md](optimization-run.md).

[optimization-run.md](optimization-run.md) records the two optimization runs
themselves, including the first one's failure, which is why the harness is now
pinned to promotable surfaces.

What follows is the fine print on `runs.json`.

## What these numbers are not

- **n = 3 per arm.** Enough to show a difference this size, nowhere near enough
  to resolve a small one.
- **One host, one FreeCAD session, one model, one day.** No claim is made about
  any other model, machine or FreeCAD version.
- **Not a leaderboard.** One agent configuration against another on one task. It
  does not rank models or CAD agents.
- **Specific to this reference mesh.** The scorer does not align poses, so a
  different mesh is a different measurement, not a different score on the same
  one.
- **Three of six runs returned HTTP 502** at the gateway's 300-second cap while
  the agent kept working. Those documents were built and scored; the 502 is a
  client-side timeout, not a failed run.
