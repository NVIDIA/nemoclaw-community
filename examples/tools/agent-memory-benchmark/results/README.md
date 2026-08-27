<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Reference results

One pair of runs on **corpus A only**, both on the same base model, both graded
by the grader in this repository. They are here so a reader can see what the
benchmark produces and check a number against the verdicts that produced it —
not as a ranking, and not as a claim about either architecture in general.

**Agentic RAG** is `adapters/agentic_rag/`, which ships here: an embedding index
over the raw documents, with the model writing its own search queries over up to
three rounds before answering. **Self-model** is a consolidating design — it
reasons at ingest time and writes a structured record it later answers from. No
adapter for it ships here, so its rows are a data point rather than something
you can re-run from this repository; `docs/SUBMITTING.md` describes the contract
any such system would implement.

## Corpus A, NVIDIA Nemotron 3 Ultra

| Metric | Agentic RAG | Self-model | Difference |
| --- | ---: | ---: | ---: |
| Overall accuracy (186 questions) | 82.8% | 89.2% | +6.5 pp |
| Hard questions (31) | 67.7% | 87.1% | +19.4 pp |
| Tracking facts that changed over time (5) | 60.0% | 100.0% | +40.0 pp |
| Point-in-time reasoning (6) | 33.3% | 66.7% | +33.3 pp |
| Entity disambiguation (15) | 66.7% | 86.7% | +20.0 pp |
| Multi-source synthesis (73) | 87.7% | 93.2% | +5.5 pp |
| Citation coverage (186) | 92.5% | 97.9% | +5.4 pp |

Cost, which the benchmark reports separately and never blends into the above. Both runs
predate the forwarded-call record the harness now keeps, so their reports mark cost as
not comparable: the counts below are what each run observed, not a proven total.

| | Agentic RAG | Self-model |
| --- | ---: | ---: |
| Ingest tokens | 169,852 | 182,760,709 |
| Tokens per question | 14,509 | 241,240 |

Read the two tables together, but not as a ratio. Each cost column is what that
run observed for itself. Neither report carries a forwarded-call record, so
nothing in these artifacts establishes that the two runs counted the same
events — which is why both set `comparable_on_cost` to false, and why no
multiple between the columns is stated here or in the reports.

What each run's own counts do show is where it spends. The self-model does its
reasoning while reading the corpus; the agentic baseline defers that to question
time and spends per question instead. Whether that trade is worth making depends
on how many questions the memory will ever be asked — a judgement
`docs/methodology.md` declines to collapse into one number. A run that wants a
defensible cost comparison has to be executed under the current harness, which
records forwarded calls.

Two notes on the cost table. The agentic baseline's ingest cost is an embedding
pass and nothing else, which is why its output tokens are zero; it does no
reasoning at ingest time, which is the whole distinction being measured. And no
dollar figure is reported for either run: `bench/pricing.py` has no entry for
this model, so the report carries token counts and declines to invent a price.

## What these numbers are not

**Corpus A only.** Corpus B ships with the benchmark and was not run on this
model. Corpus B exists precisely because a result on one corpus is a result
about that corpus — see [`corpus_b/README.md`](../corpus_b/README.md) — so the
table above says nothing about how either design behaves on documents shaped
differently. Do not read it as a general finding.

**One base model.** `docs/methodology.md` asks a submission to run at least two
and publish the difference, on the grounds that an advantage appearing under one
model and vanishing under another is not an architectural advantage. This is
one. Treat it as a worked example of the output format rather than as a
submission that meets that bar.

**Not reproducible as-is.** The systems answered against the corpus as it stood
before publication, when a set of identifiers carried different names. See
below.

## The rename, and why the answers were transformed

Publishing the corpus renamed a set of identifiers — a project, a class, a
mailbox folder, a documentation path, an email domain, and four question ids.
The stored answers were produced before that and use the old names.

The same substitution applied to the corpus was applied to the answers, because
an answer is derived from the corpus that produced it: a system reading the
published corpus would have written the published name. Nothing else was
changed, and each run ships `answers.as-answered.jsonl` — the untransformed
output — so the transform can be checked rather than believed.

What it changed, measured:

| | Agentic RAG | Self-model |
| --- | ---: | ---: |
| As answered, against the published key | 80.1% | 86.6% |
| After the substitution | 82.8% | 89.2% |
| Answers reported unanswered before the id map | 4 | 4 |

The id map does more work than the text map. Four question ids were renamed at
publication; without mapping them those four answers look absent, and an absent
answer invalidates a run. That is the runner behaving correctly — it is also
why a transformed result is weaker evidence than a fresh run.

**This is not a run against the published corpus.** Reproducing these numbers
means re-running the answer phase against what ships here. The full substitution
map is in each `report.json` under `provenance_note`.

## Reading a run directory

```
report.json                 the row: accuracy by type, evidence, cost, fingerprint
summary.md                  the same, readable
answers.jsonl               what was scored, after the publication rename
answers.as-answered.jsonl   what the system actually wrote, before it
verdicts.jsonl              per question: correct, why, and the evidence it cited
```

Two reports are comparable only when their `fingerprint` blocks match — same
corpus, same questions, same answer key, same normalization, same scorer. Both
of these were graded at the fingerprint the repository carries today.
