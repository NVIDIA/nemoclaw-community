---
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
name: agent-memory-benchmark-results
display_name: Reference Results
parent: ../README.md
corpus: corpus A only
base_models: 1
runs: [agentic-rag_corpus-a_nemotron, self-model_corpus-a_nemotron]
questions: 186
reproducible_as_is: false
cost_comparable: false
license: Apache-2.0
---

# 📈 Reference Results

One pair of runs on **corpus A only**, both on the same base model, both graded
by the grader in this repository. They are here so a reader can see what the
benchmark produces and check a number against the verdicts that produced it —
**not as a ranking, and not as a claim about either architecture in general.**

> ⚠️ **Four limits govern everything below:** corpus A only, one base model, not
> reproducible as-is, and cost that these artifacts cannot compare. Each is
> explained in [What These Numbers Are Not](#-what-these-numbers-are-not) and in
> [Cost](#-cost). Read those before quoting anything from the tables.

---

## 📑 Table of Contents

- [⚖️ The Two Settings](#️-the-two-settings)
- [📊 Corpus A, NVIDIA Nemotron 3 Ultra](#-corpus-a-nvidia-nemotron-3-ultra)
- [💰 Cost](#-cost)
- [🚫 What These Numbers Are Not](#-what-these-numbers-are-not)
- [🔤 The Rename, And Why The Answers Were Transformed](#-the-rename-and-why-the-answers-were-transformed)
- [🗂️ Where The Files Are](#️-where-the-files-are)

---

## ⚖️ The Two Settings

Both runs read the same 425 documents, answer the same 186 questions, are graded
by the same answer key and the same grader, and answer with the same base model.
The difference the benchmark is built to price is **when the reasoning
happens**. It is not the only difference — the baseline is a round-capped
configuration and also calls an embedding model — and the rows below say which
of them the artifacts can show.

| | Agentic RAG | Self-model |
| --- | --- | --- |
| Where the reasoning happens | at question time | at ingest time |
| What it does while reading the corpus | embeds each document into an index; no model reasoning | spends 1,603 model calls and 182.8M tokens in the ingest phase |
| What its memory is when questions start | the raw documents, plus the index | whatever ingest produced; it does not ship, so this page cannot say |
| How it answers | writes its own search queries, retrieves, and repeats for up to three rounds | 1,675 calls in the answer phase; the mechanism is not observable here |
| Where the cost falls | per question, every question | once, up front |
| Ships in this repository | ✅ `adapters/agentic_rag/`, hashed into its report | ❌ |

That last row is the important caveat about these numbers. The agentic baseline
is code you can run: its adapter ships here, and its report records the hash of
that adapter **as it ships today** — enough to tell whether it has moved since,
which is not the same as a hash captured while the run was executing. The run
predates the field. The self-model is a system that exists
elsewhere; only its outputs ship. Its rows are a data point, not something you
can re-execute from this repository — [`docs/SUBMITTING.md`](../docs/SUBMITTING.md)
describes the contract any consolidating system would implement to be scored the
same way.

The two rows of the cost table below follow directly from this table: a design
that front-loads its reasoning and a design that defers it do not have one
comparable "total", so ingest cost and per-question cost are reported separately
and never summed.

---

## 📊 Corpus A, NVIDIA Nemotron 3 Ultra

| Metric | Agentic RAG | Self-model | Difference |
| --- | ---: | ---: | ---: |
| Overall accuracy (186 questions) | 82.8% | 90.3% | +7.5 pp |
| Hard questions (31) | 67.7% | 87.1% | +19.4 pp |
| Tracking facts that changed over time — `chain_freshness` (5) | 60.0% | 100.0% | +40.0 pp |
| Point-in-time reasoning — `as_of` (6) | 33.3% | 66.7% | +33.3 pp |
| Entity disambiguation — `disambiguation` (15) | 66.7% | 86.7% | +20.0 pp |
| Multi-source synthesis — `multi_source` (73) | 87.7% | 94.5% | +6.8 pp |
| Refusing to answer when the corpus cannot — `abstention` (13) | 100.0% | 84.6% | -15.4 pp |
| Single-hop lookup — `single_hop` (30) | 86.7% | 83.3% | -3.3 pp |
| Citation coverage (186) | 92.5% | 97.8% | +5.4 pp |

Two rows go the other way, and they are in the table above rather than left out
of it. **What the artifacts establish is the counts.** On `abstention`, the
agentic baseline answered 13 of 13 correctly and the self-model 11 of 13. On
`single_hop`, the baseline scored 86.7% against the self-model's 83.3%. Both
differences are visible per question in each run's `verdicts.jsonl`.

**Why is not established here, and the difference matters.** These artifacts do
not include the self-model's adapter or the memory it built, so nothing in them
can show what a wrong answer was derived from. One hypothesis worth testing is
that a system answering from a consolidated record is less able to tell "the
record does not establish this" from "the record does not mention this" — but
this pair of runs cannot confirm or refute it, and it says nothing about
ingest-time consolidation in general. Testing it needs runs where the memory is
inspectable, on more than one corpus and more than one base model. Read the two
rows as measurements, not as a finding about either architecture.

---

## 💰 Cost

The benchmark reports cost separately and never blends it into accuracy.

| | Agentic RAG | Self-model |
| --- | ---: | ---: |
| Ingest tokens | 169,852 | 182,760,709 |
| Tokens per question | 14,509 | 241,240 |

> 🚫 **Read the two tables together, but not as a ratio.** Each cost column is
> what that run observed for itself. Neither report carries a forwarded-call
> record, so nothing in these artifacts establishes that the two runs counted the
> same events — which is why both set `comparable_on_cost` to false, and why no
> multiple between the columns is stated here or in the reports.

What each run's own counts do show is where it spends: 80% of the self-model's
tokens fall in the ingest phase, and 94% of the baseline's fall in the answer
phase. What those tokens were spent *on* is not in these artifacts. Whether that trade is worth making depends
on how many questions the memory will ever be asked — a judgement
[`docs/methodology.md`](../docs/methodology.md) declines to collapse into one
number. A run that wants a defensible cost comparison has to be executed under
the current harness, which records forwarded calls.

Two notes on the cost table. The agentic baseline's ingest cost is an embedding
pass and nothing else, which is why its output tokens are zero; it does no
reasoning at ingest time, which is the whole distinction being measured. And the
reports price only what `bench/pricing.py` knows. That embedding model has an
entry, so the agentic ingest phase carries a real figure, $0.0034; the Nemotron
model that answers in both runs has none, so every other phase reports token
counts with a null price rather than inventing one. **Read the tables in tokens,
not dollars**: with three of the four phases unpriced, one dollar figure cannot
be ranked against them.

---
## 🚫 What These Numbers Are Not

**Corpus A only.** Corpus B ships with the benchmark and was not run on this
model. Corpus B exists precisely because a result on one corpus is a result
about that corpus — see [`corpus_b/README.md`](../corpus_b/README.md) — so the
table above says nothing about how either design behaves on documents shaped
differently. Do not read it as a general finding.

**One base model.** [`docs/methodology.md`](../docs/methodology.md) asks a
submission to run at least two and publish the difference, on the grounds that
an advantage appearing under one model and vanishing under another is not an
architectural advantage. This is one. Treat it as a worked example of the output
format rather than as a submission that meets that bar.

**Not reproducible as-is.** The systems answered against the corpus as it stood
before publication, when a set of identifiers carried different names. See
below.

---

## 🔤 The Rename, And Why The Answers Were Transformed

Publishing the corpus renamed 20 text identifiers and 4 question ids. The text
side covers a project name and its lowercase form, several code symbols, a
database filename, a workspace directory, a service module, a mailbox folder,
and six documentation paths; the full list, in the order it was applied, is in
each `report.json` under `provenance_note.substitutions`. The stored answers were
produced before that and use the old names.

The same substitution applied to the corpus was applied to the answers, because
an answer is derived from the corpus that produced it: a system reading the
published corpus would have written the published name. Nothing else was
changed, and each run ships `answers.as-answered.jsonl` — the output as
answered, save for the one substitution noted below — so the transform can be
checked rather than believed.

> 🔒 **Two changes are deliberately outside that map.** The self-model run's
> `run_id` was de-identified at publication; it names no answer row, so it is
> not part of a map whose only job is to reproduce `answers.jsonl`, and each
> report records it under `provenance_note.run_id_note`. The other:
>
> **Two further substitutions are applied but not listed.** One replaced an
> email and URL domain that is a registrable `.com` with a domain reserved by
> RFC 2606. The other replaced an internal source-repository identifier that a
> model named in one answer — the corpus never contained it, so the corpus-side
> rename could not reach it.
> Publishing its pre-image would put a registrable domain back into a public
> artifact, which is the boundary the corpus sanitization exists to hold — so it is
> **pre-applied** in `answers.as-answered.jsonl` rather than left there and listed
> for reversal; publishing either pre-image would put back exactly what the
> substitution removed. The published map therefore reproduces `answers.jsonl` from that
> file exactly, and no artifact in this repository carries the domain.

What it changed, measured:

| | Agentic RAG | Self-model |
| --- | ---: | ---: |
| As answered, against the published key | 80.1% | 87.6% |
| After the substitution | 82.8% | 90.3% |
| Answers reported unanswered before the id map | 4 | 4 |

The id map does more work than the text map. Four question ids were renamed at
publication; without mapping them those four answers look absent, and an absent
answer invalidates a run. That is the runner behaving correctly — it is also why
a transformed result is weaker evidence than a fresh run.

---

## 🗂️ Where The Files Are

One directory per run, all siblings under `results/runs/`. **Nothing nests:**
each run directory holds its own complete copy of the same five files, and
neither run lives inside the other.

```text
results/
├── README.md                              this file
└── runs/
    ├── agentic-rag_corpus-a_nemotron/     the baseline's run — five files
    └── self-model_corpus-a_nemotron/      the self-model's run — the same five
```

A directory is named `<system>_<corpus>_<base model>`, so a second corpus or a
second base model adds a sibling rather than overwriting one of these. Both
directories here end in `corpus-a_nemotron` because that is the only pair that
was run; corpus B and a second model would appear alongside them.

Inside each one:

| File | What it holds |
| --- | --- |
| `report.json` | the machine-readable row: accuracy by question type, evidence, cost, fingerprint, provenance |
| `summary.md` | the same run, written to be read |
| `answers.jsonl` | what was scored — the answers after the publication rename |
| `answers.as-answered.jsonl` | what the system actually wrote, before the rename |
| `verdicts.jsonl` | per question: correct or not, which accepted value matched, and the evidence the answer cited |

Two reports are comparable only when their `fingerprint` blocks match — same
corpus, same questions, same answer key, same normalization, same scorer. Both
of these were graded at the fingerprint the repository carries today.

> 🧪 A generated run is ignored by `.gitignore`, not merely untracked. The two
> directories above are published deliberately, by name.
