<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Agent Memory Benchmark

**mnemo measures what a memory system can answer after ingesting email and chat,
and what ingesting and answering cost.** It reports quality and cost separately
across two synthetic corpora.

---

## Table of Contents

- [What A Run Looks Like](#what-a-run-looks-like)
- [What Is In The Corpora](#what-is-in-the-corpora)
- [What It Asks](#what-it-asks)
- [Getting Started](#getting-started)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Adding Your System](#adding-your-system)
- [How The Runner Treats Your Adapter](#how-the-runner-treats-your-adapter)
- [Reading A Result](#reading-a-result)
- [Published Results](#published-results)
- [Verification](#verification)
- [Troubleshooting](#troubleshooting)
- [Cleanup](#cleanup)
- [Provenance And License](#provenance-and-license)
- [Metadata](#metadata)

---

## What A Run Looks Like

![Terminal session: the offline self-test scoring exactly 1.0 on every question type, followed by the test suite passing](docs/assets/offline-self-test.png)

The offline oracle scores `1.0` on a six-document fixture. The text version
below keeps the result searchable and agent-readable.

```text
$ python3 -m bench.runner --adapter selftest/oracle \
      --corpus selftest/corpus --questions selftest/questions.jsonl \
      --gold selftest/gold.jsonl

* corpus: 6 docs (4 part_a / 2 part_b)
* questions: 6 (graded deterministically: 6, deferred to judge: 0)

## Quality
* accuracy overall: **1.0**
  * [base] 1.0
  * [hard] 1.0
  * abstention: 1.0
  * citation: 1.0
  * freshness: 1.0
  * multi_source: 1.0
  * ordering: 1.0
  * single_hop: 1.0
  * freshness with a competing stale claim in corpus: 1.0
  * freshness recency-only: n/a — not annotated for this corpus
```

---

## What Is In The Corpora

| | Documents | Period | Domain |
| --- | ---: | --- | --- |
| **Corpus A** (`corpus_a/`) — [details](corpus_a/README.md) | 425 — 200 emails, 225 channel-days of chat (559 messages) | 2026-04-16 → 2026-05-27 | a software platform-engineering team |
| **Corpus B** (`corpus_b/`) — [details](corpus_b/README.md) | 173 — 100 emails, 73 channel-days (383 messages) | 2027-07-20 → 2027-09-24 | a construction program manager running three sites |

Corpus B uses a different domain and generation model so results can be checked
across corpora. Both corpora are fully synthetic; see their READMEs for
provenance and limitations.

Corpus A ships in two halves, and both are ingested **in order**:

```text
corpus_a/corpus/part_a/   2026-04-16 .. 2026-05-11
corpus_a/corpus/part_b/   2026-05-12 .. 2026-05-27   # supersedes part_a in places
```

The runner makes two `ingest` calls in order, testing whether memory handles
later information that supersedes earlier claims.

---

## What It Asks

### Base set (155)

| Type | Count | What it catches |
| --- | ---: | --- |
| `single_hop` | 30 | a fact stated in one document |
| `multi_source` | 73 | a fact corroborated across several documents |
| `disambiguation` | 15 | merging two things that only look alike, or splitting one that is not two |
| `abstention` | 13 | answering confidently about something the corpus never says |
| `freshness` | 12 | reporting a superseded value as if it were current |
| `citation` | 12 | recalling a detail only one document carries; cited ids are a diagnostic, not accuracy |

### Hard set (31)

Added when the base set stopped separating systems.

| Type | Count | What it catches |
| --- | ---: | --- |
| `set_difference` | 6 | which member of a plausible set does *not* belong |
| `as_of` | 6 | what was true *at a date*, not what is true now |
| `constraint` | 5 | two or three conditions at once, each matching several candidates alone |
| `chain_freshness` | 5 | a value that moved twice — where it started and where it ended |
| `attribution` | 5 | who proposed something versus who carried it out |
| `ordering` | 4 | placing events relative to each other rather than looking one up |

> `as_of` tests whether a system retained historical values instead of only the
> latest one.

**All 186 questions are graded deterministically; no model runs in the scoring
path.** Answers are normalized for case, punctuation, whitespace, date spelling,
and thousands separators before applying each mode's explicit rule set. Reports
still include `deferred_to_judge`, which is always zero for shipped questions.

Abstention questions have no correct answer. Something merely scheduled has not
happened; a merge request that exists only as a reserved URL has not been
reviewed. Confidently describing either is scored wrong, and saying "the corpus
does not say" is scored right.

---

## Getting Started

Use Python 3.9+ on macOS or Linux and install `pytest`. A real run also needs an
API key for the configured endpoint. The shipped adapters invoke `python3`,
which a default Windows installation does not provide.

### 1. Check it works — offline, free, no API key

> **Offline and free.** This path sends nothing over the network.

```bash
cd examples/tools/agent-memory-benchmark
python3 -m pip install pytest
python3 -m pytest tests/     # expected: 219 passed
```

Then run the whole pipeline against a fixture whose score is known in advance:

```bash
python3 -m bench.runner \
    --adapter selftest/oracle \
    --corpus selftest/corpus \
    --questions selftest/questions.jsonl \
    --gold selftest/gold.jsonl
```

The oracle scores exactly `1.0`; its sibling `selftest/wrong` scores exactly
`0.0`, wrong in a different way per grading mode. Any drift between the runner
and the report moves a number the tests pin.

### 2. Score a real system

> **This spends money and sends data.** Corpus text and questions are sent to
> the endpoint you point `--upstream` at, and you pay for those tokens. The
> harness itself writes only under `results/` — but an adapter you add is not
> sandboxed and can write anywhere your user can.

```bash
export OPENAI_API_KEY=<your key>
python3 -m bench.runner --adapter adapters/naive_rag
```

The runner ingests both corpus halves in order, feeds
`corpus_a/questions/questions.jsonl` to your system, grades the answers, and writes
`report.json` + `summary.md` under `results/runs/`.

| Baseline adapter | What it is |
| --- | --- |
| `adapters/naive_rag` | embedding index, single retrieval pass |
| `adapters/agentic_rag` | embedding index; the model writes its own queries over up to three rounds |
| `adapters/ledger_rag` | drives the [Memory-Driven Chief of Staff](../../recipes/nvidia/memory-driven-chief-of-staff/README.md) ledger; SQLite ingest needs no network |

> **`ledger_rag` does not score the recipe itself.** The adapter adds candidate
> selection and answer generation to a ledger designed for triage and ranking.
> It does not modify the recipe.

---

## Project Structure

```text
agent-memory-benchmark/
├── bench/                       the harness — no third-party imports
│   ├── runner.py                orchestrates ingest → answer → grade → report
│   ├── grader.py                deterministic scoring; denial scope, normalization
│   ├── fingerprint.py           hashes corpus+questions+gold+scorer → comparability
│   ├── proxy.py                 local proxy that counts tokens crossing the wire
│   ├── normalize.py             case, punctuation and date-spelling normalization
│   ├── answer_contract.py       what an adapter is told about the answer format
│   ├── report.py                renders report.json into summary.md
│   └── pricing.py               model → USD table; unknown model ⇒ null, never a guess
├── corpus_a/                    corpus A — the default corpus
│   ├── README.md                what it is, and why the split matters
│   ├── corpus/                  425 documents in two dated halves
│   │   ├── part_a/              2026-04-16 .. 2026-05-11
│   │   ├── part_b/              2026-05-12 .. 2026-05-27 — supersedes part_a in places
│   │   ├── manifest.jsonl       per-document provenance
│   │   ├── counts.json          the document/message counts this README quotes
│   │   └── CANARY.txt           a string that must not appear in any model output
│   └── questions/               the questions and the answer key, kept out of corpus/
│       ├── questions.jsonl      the 186 questions asked of every system
│       ├── answers.jsonl        the answer key and its grading rules
│       └── factual_*.json       the drafting record — 103 kept, 17 dropped with a reason, 0 rejected
├── corpus_b/                    corpus B — a second domain, same shape as corpus_a/
├── adapters/                    one directory per system under test
│   ├── naive_rag/               ┐
│   ├── agentic_rag/             ├ shipped baselines, each with an adapter.json
│   ├── ledger_rag/              ┘
│   └── _lib/                    shared helpers adapters may import
├── selftest/                    six documents, six questions, two known-score adapters
│   ├── oracle/                  answers everything correctly — scores exactly 1.0
│   └── wrong/                   wrong in a different way per mode — scores exactly 0.0
├── results/                     published reference runs — see results/README.md
├── tools/regrade.py             re-score stored answers against the current rules
├── docs/                        SUBMITTING.md, methodology.md, provenance.md
└── tests/                       the benchmark's own tests
```

**Dependency files:** there are none to install for the harness — `bench/`
imports only the Python standard library. The offline check needs `pytest`
(`python3 -m pip install pytest`). An adapter for a third-party system declares
its own requirements separately, inside its own directory.

---

## Configuration

### `adapter.json` — the contract for a system under test

Every adapter is one JSON file. `name`, `ingest` and `answer` are required —
omitting any of them is an uncaught `KeyError`, not a default. `model` is
optional despite naming the id a result is filed under: without it the runner
falls back to the model it observed most.

```json
{
  "name": "my-system",
  "model": "some-model-id",
  "accounting": "proxy",
  "ingest": ["my-cli", "ingest", "--corpus", "{corpus}", "--state", "{state}"],
  "answer": ["my-cli", "answer", "--state", "{state}"],
  "env": { "MY_SYSTEM_PYTHON": "python3" }
}
```

Field reference — the shape the runner validates:

```typescript
interface AdapterConfig {
  /** Filed under this name in the report. */
  name: string;
  /** The model id a result is filed under. Not resolved by the harness. */
  model: string;
  /**
   * Argument arrays, never shell strings.
   * ingest receives {corpus} (the part directory), {state} and {part}.
   * answer receives {state} and {questions} — NOT {corpus}. Using {corpus}
   * there fails after both ingest calls have already run.
   */
  ingest: string[];
  answer: string[];
  /**
   * "proxy" (default) — calls go through the local proxy and are counted.
   * "local"           — a locally-hosted model; nothing crosses the wire, and
   *                     the run says so instead of reading as a cost of zero.
   */
  accounting?: "proxy" | "local";
  /** Defaults for adapter-specific variables. Anything already exported wins. */
  env?: Record<string, string>;
}
```

> **A declared accounting mode is enforced in both directions.** Three things
> make a run invalid:
>
> - it declares `proxy` and nothing crossed the proxy — the adapter either
>   bypassed it or runs a local model and should say so;
> - it declares `local` and requests crossed the proxy anyway — the declaration
>   and the traffic disagree, and the traffic wins;
> - a forwarded request came back without countable usage, because a cost nobody
>   measured must not read as a cost of zero.
>
> A `local` run that really is local stays valid, and stays out of cost
> comparisons. Only a fully counted run carries `comparable_on_cost: true`.

### Environment variables

| Variable | Default | What it does |
| --- | --- | --- |
| `OPENAI_API_KEY` | *(none)* | Required to score a real system; `MNEMO_API_KEY` is accepted instead. Not needed offline. |
| `MNEMO_UPSTREAM` | `https://api.openai.com` | Where the accounting proxy forwards. Also `--upstream`. |
| `MNEMO_EMBED_MODEL` | `text-embedding-3-small` | Embedding model for the retrieval baselines. |
| `MNEMO_TIMEOUT_SECONDS` | `21600` (six hours) | Wall-clock budget **per phase call**. `0` waits indefinitely. Also `--timeout-seconds`. |
| `MNEMO_RAG_WORKERS` | `6` | Answer-phase concurrency for all three shipped baselines. |
| `MNEMO_LEDGER_TOP_K` | `12` | Candidates `ledger_rag` selects per question. |
| `MNEMO_LEDGER_SCHEMA` | recipe default path | Where `ledger_rag` finds the recipe's `schema.sql`, if the recipe is not at its usual place. |
| `MNEMO_MODEL` | *(unset)* | Overrides the model id passed to the adapter. |
| `MNEMO_PROXY_LOG` | *(unset)* | Writes a proxy request log. |
| `MNEMO_DEFAULT_YEAR` | `2026` | Date-normalization year. **Part of the fingerprint** — changing it makes a run incomparable with published ones. |
| `MNEMO_ALT_YEARS` | `2027` | The other year normalization accepts. **Also part of the fingerprint.** |

The shipped baselines default to `gpt-4o` and `text-embedding-3-small`, so they
run as printed. Point `--upstream` at any OpenAI-compatible gateway; model ids
are often namespaced differently there, so set `model` in the adapter to the id
that gateway expects.

An adapter that needs a host-specific path declares it in its `env` block, and
anything already exported wins — so nothing machine-specific has to be
committed:

```bash
MY_SYSTEM_PYTHON=~/src/my-system/.venv/bin/python \
    python3 -m bench.runner --adapter adapters/my_system
```

> ⏱️ The timeout applies to each phase *call*, and ingest is called twice, so a
> default run can occupy up to eighteen hours before anything is killed.

---

## Adding Your System

1. Write an `adapter.json` as above.
2. `answer` reads `questions.jsonl` on **stdin** and writes one JSON object per
   line to **stdout**:

```json
{"id": "example-launch-date", "answer": "<your short answer>", "source_ids": ["E:2027-02-05T10-00-00__bbbb0002"]}
```

```typescript
interface AnswerRow {
  /** Must match the question id it answers. */
  id: string;
  /**
   * A short, checkable answer. Blank, whitespace-only, non-string and missing
   * are all "nothing was said" — and one of them invalidates the whole run,
   * because an incomplete submission is not a lower score. A blank answer is
   * not credited as an abstention either.
   */
  answer: string;
  /** Optional. Buys the evidence diagnostics; omitting it costs nothing on accuracy. */
  source_ids?: string[];
}
```

1. Run it. Full instructions, including the path for a system that cannot be
   wrapped in a command line: [`docs/SUBMITTING.md`](docs/SUBMITTING.md).

---

## How The Runner Treats Your Adapter

> **Adapters are not sandboxed.** They run with your user, filesystem access,
> and environment credentials. Review an adapter before running it.

**Commands are argument arrays, never shell strings.** `["my-cli", "ingest",
"--corpus", "{corpus}"]` is executed directly with no shell in between, so a
path containing a space or a quote cannot become a second command.

The guards prevent accidental answer-key access, not a malicious adapter. The
benchmark root remains reachable through `PYTHONPATH`, as demonstrated by
`tests/test_isolation_is_not_a_sandbox.py`. Trust the adapter behind any score.
The guards provide:

- Adapters are launched from a scratch directory, not from the benchmark root,
  so a relative `open("corpus_a/questions/answers.jsonl")` finds nothing.
- Before each phase starts, the runner checks the phase was not handed a path it
  must not have. Ingest never receives the questions or the answer key; answer
  never receives the answer key. A run that would violate this stops before the
  adapter launches.
- Each adapter runs in its own process group, so a timeout — or a Ctrl-C —
  reaches the workers your adapter started, not just the adapter. A process that
  ignores `SIGTERM` is killed ten seconds later. Without this, a hung run leaves
  workers behind that keep the proxy open and keep spending tokens after the run
  is over.

---

## Reading A Result

Compare per-question-type accuracy, not only the overall average. Freshness
separates cases with and without a competing stale claim. Evidence recall and
citation coverage remain diagnostics rather than accuracy inputs.

Why the two axes are never combined, and what deterministic grading cannot
express: [`docs/methodology.md`](docs/methodology.md).

Two reports are comparable only when their `fingerprint` blocks match — same
corpus, same questions, same answer key, same normalization, same scorer.

---

## Published Results

The repository includes one self-model run and one agentic retrieval run on
corpus A with the same base model and grader. The artifacts show their scores
and separate ingest and answer costs, but do not include the self-model's memory
or enough accounting evidence for a cost ratio.

Read [`results/README.md`](results/README.md) **before** the table there. Those
runs are corpus A only, on one base model; their answers predate a rename at
publication; and their accounting cannot support a cost comparison. All four
limits are stated where the numbers are.

---

## Verification

**Evidence level:** `local/static`. **Verified on** Python 3.9.6, macOS. Nothing
here exercises a live endpoint.

```bash
python3 -m pytest tests/     # expected: 219 passed
```

**Expected result:**

```text
219 passed
```

This verifies the runner, grader, report renderer, ledger ingest, fixtures, and
documented corpus counts. It does not test a live endpoint, real model call, or
Windows.

---

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `No module named pytest` | `pytest` is a dev dependency and is not vendored. | `python3 -m pip install pytest` |
| `No module named 'bench'` | `python3 -m bench.runner` was run from a different directory; `-m` resolves the package from the current one. | `cd examples/tools/agent-memory-benchmark` and re-run. |
| Adapter command not found on Windows | The shipped adapters invoke `python3`, which a default Windows install does not provide. | Run on macOS or Linux, or under WSL. |
| Run marked invalid: *declared proxy, nothing crossed it* | The adapter bypassed the proxy, or it runs a locally-hosted model. | Point the client at `OPENAI_BASE_URL`, or declare `"accounting": "local"`. |
| Run marked invalid: *forwarded request without countable usage* | The upstream returned no usage block. | Use a gateway that returns usage; a cost nobody measured must not read as zero. |
| Run marked invalid: *declared local but N requests crossed the proxy* | The adapter says it runs locally but its client still points at `OPENAI_BASE_URL`. | Stop routing through the proxy, or declare `"accounting": "proxy"`. |
| Run marked invalid: *N of M questions received no answer* | One or more answer rows are missing, blank or non-string. An incomplete submission is not a lower score. | Emit one row per question; to decline, say so in the answer rather than leaving it empty. |
| USD is `null` in the report | `bench/pricing.py` has no entry for that model. | Expected. Token counts are still exact; the harness will not invent a price. |
| Two reports refuse to be compared | Their `fingerprint` blocks differ — corpus, questions, key, normalization or scorer moved. | Re-score the stored answers: `python3 tools/regrade.py --run results/runs/<dir>` |
| A phase hangs, then dies at six hours | The per-phase wall-clock budget. | Raise `MNEMO_TIMEOUT_SECONDS`, or set `0` to wait indefinitely. |
| `results/` grew by hundreds of megabytes | Each run keeps whatever memory the system under test built. | Delete the run directory; see [Cleanup](#cleanup). |

---

## Cleanup

Each run writes reports, verdicts, answers, and adapter state under
`results/runs/<timestamp>-<adapter>/`. Delete that directory to reclaim space.

By default nothing outside that directory is modified by the harness. `--out`
and `--state` will write wherever you point them, and an adapter is not
sandboxed, so one you add can write elsewhere; see
[How the runner treats your adapter](#how-the-runner-treats-your-adapter).

A generated run is ignored by Git. Publishing one requires an explicit
`.gitignore` exception.

---

## Provenance And License

Authored and maintained by NVIDIA, contributed under Apache-2.0.

Both corpora are synthetic and use invented identities, projects, messages, and
reserved `.example` domains. Nothing came from a live account.

How the corpora were generated, what was screened before publication, and the
content hashes that say whether two scores are comparable:
[`docs/provenance.md`](docs/provenance.md).

**License:** Apache-2.0 throughout — code, corpus, questions and answer key
alike, under the repository's [LICENSE](../../../LICENSE).

---

## Metadata

```yaml
name: agent-memory-benchmark
display_name: mnemo — Agent Memory Benchmark
category: Developer Tool
provenance: NVIDIA
language: python
python_requires: ">=3.9"
runtime_dependencies: none (Python standard library only)
dev_dependencies: [pytest]
entry_point: python3 -m bench.runner
offline_check: python3 -m pytest tests/
adapter_contract: docs/SUBMITTING.md
corpora: [corpus_a/, corpus_b/]
question_count: 186  # corpus A; corpus B adds 96, see corpus_b/README.md
license: Apache-2.0
evidence_level: local/static
```

## Catalog Metadata

| Catalog field | Value |
| --- | --- |
| Description | Measures memory built from synthetic email and chat, asks 186 questions on one corpus and 96 on a second, and reports accuracy by question type with ingest and answer token costs. |
| Industry | ✨ Other |
| Requirements | Python 3.9+ · pytest for offline checks · endpoint and adapter for live scoring |
