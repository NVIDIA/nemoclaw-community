<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Local-Only Workspace Assistant Documentation

These pages explain what the recipe is, how it works, and what state it is in.
To run the recipe, start with the [recipe README](../README.md#quickstart).

| Page | Read it to learn |
| --- | --- |
| [Overview](overview.md) | What the recipe is, who it is for, what you get, and what it does not do |
| [How It Works](how-it-works.md) | The components, the three controls, and what happens during setup, a request, and teardown |
| [Test Suite](test-suite.md) | How the denied-action tests decide a verdict, what they record, and how to add a case or a backend |
| [Configuration](configuration.md) | Every setting, the default model, the files, and the state that the recipe keeps |
| [Status And Planned Work](status.md) | What has run, what remains unverified, and what comes next |

## Status In One Paragraph

Setup, the live test suite, and teardown completed on one host: macOS with
Docker Desktop, OpenShell 0.1.8, and CPU inference. Every ready case of the
test suite passed. Nobody has run the recipe on Linux, on WSL2, or with a GPU,
and the agent has not answered a question in the sandbox.
[Status And Planned Work](status.md) has the details and the evidence.

## Where Each Fact Lives

These pages explain. They are not the source of truth for values that change.
When a page and a source disagree, the source is correct.

| Fact | Source of truth |
| --- | --- |
| Commands to run the recipe | [README, Quickstart](../README.md#quickstart) |
| Known limitations | [README, Known Limitations](../README.md#known-limitations) |
| Diagrams | The Mermaid diagrams in [README, Architecture](../README.md#architecture) |
| Test cases | [`src/localonly/cases.py`](../src/localonly/cases.py) |
| Settings and defaults | [`.env.example`](../.env.example) and [`scripts/_lib.sh`](../scripts/_lib.sh) |
| Sandbox policy | [`policies/local-only.yaml`](../policies/local-only.yaml) |
| Provider profile, the one network endpoint | [`policies/ollama-provider-profile.yaml`](../policies/ollama-provider-profile.yaml) |

## Images

The images in [`images/`](images/) were made on 2026-11-12.

| Image | Shows | Made from |
| --- | --- | --- |
| `architecture-components.png` | Components and trust zones | Mermaid diagram in the README |
| `setup-sequence.png` | What setup does, in order | Mermaid diagram in the README |
| `request-flows.png` | An allowed request, a denied request to another host, a denied request to another path, and a stopped local server | Mermaid diagram in the README |
| `test-suite-design.png` | The parts of the test suite | Mermaid diagram in the README |
| `static-checks.png` | Output of `bash scripts/verify.sh` | Captured terminal output |
| `test-cases.png` | Output of `python3 -m localonly cases` | Captured terminal output |
| `setup-run.png` | Output of `bash scripts/bring-up.sh` through all seven stages | Captured terminal output |
| `live-suite.png` | Output of `bash scripts/verify.sh --live` | Captured terminal output |

The four diagram images are renderings of the README diagrams with Mermaid
11.17.2. When a README diagram changes, render its image again. The four
terminal images show the exact output of the named command on macOS with
Docker Desktop, drawn as an image. Nothing in them was typed by hand. The setup
image leaves out the progress lines of the image build and of the file uploads.
The live suite image shows the evidence file path relative to the recipe
directory.
