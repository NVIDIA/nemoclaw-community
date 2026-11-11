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
| [Status And Planned Work](status.md) | What has run, what fails today, and what comes next |

## Status In One Paragraph

The recipe is a first increment, and setup does not complete yet. The static
checks pass. Setup stages 1 to 4 ran on one host. Stage 5 fails with OpenShell
0.1.8, because the scripts use commands from earlier OpenShell versions.
Nobody has created the sandbox or run the live test suite.
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

## Images

The images in [`images/`](images/) were made on 2026-11-11.

| Image | Shows | Made from |
| --- | --- | --- |
| `architecture-components.png` | Components and trust zones | Mermaid diagram in the README |
| `setup-sequence.png` | What setup does, in order | Mermaid diagram in the README |
| `request-flows.png` | An allowed request, a denied request, and a stopped local server | Mermaid diagram in the README |
| `test-suite-design.png` | The parts of the test suite | Mermaid diagram in the README |
| `static-checks.png` | Output of `bash scripts/verify.sh` | Captured terminal output |
| `test-cases.png` | Output of `python3 -m localonly cases` | Captured terminal output |
| `setup-run.png` | Output of `bash scripts/bring-up.sh`, which stops at stage 5 | Captured terminal output |

The four diagram images are renderings of the README diagrams with Mermaid
11.17.2. When a README diagram changes, render its image again. The three
terminal images show the exact output of the named command, drawn as an image.
Nothing in them was typed by hand.
