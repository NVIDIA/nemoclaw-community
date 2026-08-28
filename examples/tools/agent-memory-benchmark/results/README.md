<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Reference Results

Two reference runs show the benchmark's output and supporting verdicts. Both use
corpus A, one base model, and the repository's grader; they are not a ranking.

> **Limits:** corpus A only, one base model, not reproducible as-is, and no
> defensible cost comparison. Read [What These Numbers Are Not](#what-these-numbers-are-not)
> and [Cost](#cost) before quoting the tables.

---

## The Two Settings

Both runs read 425 documents, answer 186 questions, and use the same key, grader,
and base model. They differ primarily in when reasoning happens; the baseline
also uses embeddings and a round cap.

| | Agentic RAG | Self-model |
| --- | --- | --- |
| Where the reasoning happens | at question time | at ingest time |
| What it does while reading the corpus | embeds each document into an index; no model reasoning | spends 1,603 model calls and 182.8M tokens in the ingest phase |
| What its memory is when questions start | the raw documents, plus the index | whatever ingest produced; it does not ship, so this page cannot say |
| How it answers | writes its own search queries, retrieves, and repeats for up to three rounds | 1,675 calls in the answer phase; the mechanism is not observable here |
| Where the cost falls | per question, every question | once, up front |
| Ships in this repository | Yes: `adapters/agentic_rag/`, hashed into its report | No |

The agentic adapter ships; the self-model does not, so only its outputs are
available. The agentic report hashes the current adapter, not the version used
during the older run. See [`docs/SUBMITTING.md`](../docs/SUBMITTING.md) for the
adapter contract. Ingest and per-question costs remain separate.

---

## Corpus A, NVIDIA Nemotron 3 Ultra

| Metric | Agentic RAG | Self-model | Difference |
| --- | ---: | ---: | ---: |
| Overall accuracy (186 questions) | 82.8% | 89.8% | +7.0 pp |
| Hard questions (31) | 67.7% | 87.1% | +19.4 pp |
| Tracking facts that changed over time — `chain_freshness` (5) | 60.0% | 100.0% | +40.0 pp |
| Point-in-time reasoning — `as_of` (6) | 33.3% | 66.7% | +33.3 pp |
| Entity disambiguation — `disambiguation` (15) | 66.7% | 86.7% | +20.0 pp |
| Multi-source synthesis — `multi_source` (73) | 87.7% | 94.5% | +6.8 pp |
| Refusing to answer when the corpus cannot — `abstention` (13) | 100.0% | 76.9% | -23.1 pp |
| Single-hop lookup — `single_hop` (30) | 86.7% | 83.3% | -3.3 pp |
| Citation coverage (186) | 92.5% | 97.8% | +5.4 pp |

The agentic baseline leads on `abstention` and `single_hop`; per-question details
are in each `verdicts.jsonl`. The artifacts do not include the self-model's
adapter or memory, so they establish measurements, not causes or architectural
conclusions.

---

## Cost

The benchmark reports cost separately and never blends it into accuracy.

| | Agentic RAG | Self-model |
| --- | ---: | ---: |
| Ingest tokens | 169,852 | 182,760,709 |
| Tokens per question | 14,509 | 241,240 |

> **Do not treat the cost columns as a ratio.** Neither report carries a
> forwarded-call record proving that both counted the same events; both set
> `comparable_on_cost` to false.

The self-model spends 80% of its tokens during ingest; the baseline spends 94%
during answering. The artifacts do not show what those tokens did. A defensible
comparison requires a current run with forwarded-call records.

The baseline's ingest phase is embedding-only and reports zero output tokens.
`bench/pricing.py` prices that embedding pass at $0.0034 but has no Nemotron
price, so compare token counts rather than incomplete dollar values.

---

## What These Numbers Are Not

**Corpus A only.** Corpus B was not run, so the table does not show cross-domain
behavior.

**One base model.** The methodology asks submissions to run at least two. Treat
this as an output example, not a complete submission.

**Not reproducible as-is.** The systems answered against the corpus as it stood
before publication, when a set of identifiers carried different names. See
below.

---

## The Rename, And Why The Answers Were Transformed

Publication renamed 20 text identifiers and 4 question ids. Each `report.json`
lists the ordered substitutions under `provenance_note.substitutions`; stored
answers predate those names.

The same substitutions were applied to answers. Each run includes
`answers.as-answered.jsonl` so the transform can be checked.

> **Two changes sit outside that map.** The self-model `run_id` was de-identified
> and recorded under `provenance_note.run_id_note`.
>
> A registrable domain was also replaced by an RFC 2606 reserved domain. Its
> pre-image is intentionally absent from public artifacts and the replacement is
> pre-applied in `answers.as-answered.jsonl`.

What it changed, measured:

| | Agentic RAG | Self-model |
| --- | ---: | ---: |
| As answered, against the published key | 80.1% | 87.1% |
| After the substitution | 82.8% | 89.8% |
| Answers reported unanswered before the id map | 4 | 4 |

Without the four question-ID mappings, four answers appear absent and invalidate
the run. A transformed result remains weaker evidence than a fresh run.

---

## Where The Files Are

Each run is a sibling directory under `results/runs/` and contains five files.

```text
results/
├── README.md                              this file
└── runs/
    ├── agentic-rag_corpus-a_nemotron/     the baseline's run — five files
    └── self-model_corpus-a_nemotron/      the self-model's run — the same five
```

Directories use `<system>_<corpus>_<base model>`; new corpora or models add
siblings instead of overwriting a run.

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

> Generated runs are ignored by default. The two directories above are explicit
> published exceptions.

---

## Metadata

```yaml
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
```
