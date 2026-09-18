<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Reference measurement runs

`runs.json` holds the per-run numbers behind the summary table in the main
[README](../README.md). The comparison and what it means are there; what follows
is only the fine print.

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
