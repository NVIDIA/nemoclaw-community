<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
     SPDX-License-Identifier: Apache-2.0 -->
# Chat with the CAD agent

Try an agent folder outside the evaluation loop, in the browser: upload a mesh, ask the agent
to rebuild it, watch its steps and the renders it looks at, compare its model with the mesh,
and download the model.

![The chat: the agent's model in the 3D view, and its steps and report in the chat](../assets/chat.png)

```bash
docker build -t cad-env "$(ls -d evals/train/*/environment | head -1)"   # once
chat/chat.sh [MESH]     # open the printed http://localhost:8765; Ctrl-C stops it
```

The agent runs as the eval builds it ([harness/agent.py](../harness/agent.py)): inside the
`cad-env` image, the agent folder mounted read-only at `/agent`, a work folder as `/app`, the
model through the Helix gateway (`CAD_HELIX_URL`, `NHX_WORKSPACE` from your shell, as for the
eval; `.env` is read too). The agent is the eval's: its middleware pushes every message
towards a saved, valid model, so it suits rebuild requests better than open questions. Each message
is one task with its own time limit, run in its own process group: stopping it stops
everything it started. The conversation carries over as text (your messages and the agent's
answers). A mesh (OBJ or STL), given here or uploaded in the page, becomes
`/app/reference.obj`, where the agent's skills look for it.

In the page: upload a mesh, chat (e.g. "rebuild this mesh as an editable model") and watch the
agent's steps stream in, with each render it looks at; compare the saved model (orange) with
the mesh (blue, translucent), overlaid or side by side, and download `model.FCStd`. Drag the chat's
left edge to widen it. A new mesh starts a new chat in an empty work folder; the earlier
job's files move to `.jobs/<time>/` in it. Closing the tab stops the task. The page is for this machine only: it
answers only requests addressed to `localhost`, from its own page.

| Variable | Meaning |
| --- | --- |
| `CAD_WORK` | work folder, the agent's `/app` (default `cad-work/` in the example) |
| `CAD_AGENT_DIR` | agent folder (default `results/final-agent`) |
| `CAD_MODEL` | model name on the gateway (default: the agent's `agent.yaml`) |
| `CAD_CHAT_TIMEOUT` | each message's time limit and longest shell command, seconds (default 900; the eval's `CAD_AGENT_TIMEOUT` is 300) |
| `CAD_WEB_PORT` | port on this machine (default 8765) |
| `CHAT_BASE_URL`, `CHAT_API_KEY` | any OpenAI-compatible endpoint instead of Helix |

| File | What it does |
| --- | --- |
| `chat.sh` | Starts the container. |
| `web.py`, `web.html` | The server and the page: uploads, the streamed steps, the 3D view, the download. |
| `chat.py` | The agent side: builds the agent, runs each message as a task in its own process. |
| `fc.py` | Turns a mesh or a model into the OBJ the page shows, with FreeCAD. |
