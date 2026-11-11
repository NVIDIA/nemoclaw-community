<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Status And Planned Work

This page records what has run, on which host, and what the result was. It
was last updated on 2026-11-11.

## Summary

The recipe does not complete setup yet. The static checks pass, and setup
stages 1 to 4 ran on one host. Stage 5 fails with OpenShell 0.1.8. Nobody has
created the sandbox, run the live test suite, or asked the agent a question.

The evidence level is `local/static`.

## What Has Run

| Item | State | Host and evidence |
| --- | --- | --- |
| Static checks: 71 unit tests, policy file, addresses, approved folder, Compose rendering | Pass | macOS, Python 3.9.6 and 3.12.16, Docker Compose 5.7.0 |
| Setup stages 1 to 4: checks, device, Ollama container, model download | Pass on one host | macOS, Docker Desktop 29.9.3, CPU inference |
| Default model answers a chat request and a tool-call request | Observed once, outside the sandbox | Ollama 0.32.3 container, Apple M1, CPU inference |
| Setup stage 5: provider and inference route | Fails with OpenShell 0.1.8 | Same host |
| Setup stages 6 and 7: sandbox, copy | Never run | None |
| Live test suite | Never run | None |
| GPU serving | Never run | None |
| Windows cases S04 and S04b on WSL2 | Never run | None |
| The agent answers a question about the folder | Not built | None |

### Static Checks

![Terminal output of the static checks, ending in a PASS line with 0 skipped](images/static-checks.png)

The image shows the output of `bash scripts/verify.sh`. The checks start no
service and contact no external system. They show that the policy file is
local-only, that the address checks reject remote addresses, that the copy
filter rejects links and oversized files, and that the suite never reports a
pass for a script that did not run in the sandbox.

They do not show that OpenShell accepts or enforces the policy.

### Setup Run

![Terminal output of setup: stages 1 to 4 succeed, and stage 5 stops with a provider profile error](images/setup-run.png)

The image shows the output of `bash scripts/bring-up.sh` on macOS with Docker
Desktop and OpenShell 0.1.8. The command exited with status 1. The last lines
are:

```text
== 5/7 point the OpenShell inference route at the local server ==
Error:   × provider profile 'openai' not found; import a matching profile before
  │ using this provider type
```

No provider and no sandbox existed after the run.

### Model Check

One check of the default model ran against the recipe-owned Ollama container,
without a sandbox:

- A chat request through the OpenAI-compatible endpoint returned a completion.
  The first request, which also loads the model, took 17 seconds.
- A request with one tool definition returned a call to that tool. It took 25
  seconds for 42 output tokens.
- The loaded model used 2.9 GB of the 3.8 GB that Docker gave the container.

These numbers describe CPU inference in a virtual machine on an Apple M1. They
say nothing about GPU serving.

## Why Stage 5 Fails

The scripts follow the OpenShell commands that other examples in this
repository use with versions 0.0.85 and 0.0.106. OpenShell 0.1.8 differs in
four ways that matter to this recipe.

| The scripts use | OpenShell 0.1.8 |
| --- | --- |
| `openshell inference set` and `inference get` | Has no `inference` command |
| `openshell provider create --type openai` | Requires a provider profile that was imported with `openshell profile import`. A new gateway has no profile |
| `openshell sandbox create --from <Dockerfile>` | `--from` accepts an image reference or a root file system archive |
| `openshell sandbox cp` | Has `openshell sandbox upload` |

These commands are the same in both: `sandbox exec`, `policy set`,
`policy get`, `sandbox list`, and `sandbox delete`.

Nobody has run the recipe with OpenShell 0.0.85 or 0.0.106 either. The
sandbox image in the `Dockerfile` is the one that another example pairs with
OpenShell 0.0.85.

## Planned Work

The items are in the planned order. None of them has started.

1. **Port setup and teardown to OpenShell 0.1.** Import a provider profile for
   the local endpoint, build the sandbox image with Docker and pass the image
   reference, and copy files with `sandbox upload`. One question is open: how
   OpenShell 0.1 routes inference for a provider that is attached to a
   sandbox.
2. **Complete one live run on Linux.** Adjust the policy allowlist until the
   sandbox starts. Run the live test suite and keep the evidence file.
3. **Run on a host with an NVIDIA GPU.** Record where Ollama loads the model.
4. **Run on Windows 11 with WSL2.** This run gives cases S04 and S04b a
   result.
5. **Write the planned cases.** S06d, S07, S10, S11, and S12 have no script.
6. **Connect the agent.** Start OpenClaw in the sandbox, ask a question about
   the sample folder, and capture the answer.
7. **Add a second backend.** Run the same case table against a native Windows
   sandbox. See [Test Suite, Add A Backend](test-suite.md#add-a-backend).

## What Evidence Each Claim Needs

| Claim | Host that can test it |
| --- | --- |
| The sandbox denies file escapes, egress, and remote inference, and inference fails with an explicit error when the local server stops | Any Linux host with Docker and OpenShell. No GPU |
| An NVIDIA GPU serves the model | A Linux or WSL2 host with an NVIDIA GPU and the NVIDIA Container Toolkit |
| The sandbox cannot reach Windows drives or start Windows programs | Windows 11 with WSL2. No GPU |

A small Docker virtual machine may not hold the model and the sandbox
together. In the model check, the loaded model used most of a 3.8 GB limit.

[README, Known Limitations](../README.md#known-limitations) has the complete
list of limits.
