<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Corpus B — construction program management

A synthetic construction-program corpus for checking whether results transfer
beyond corpus A's software-engineering domain. Dana Okafor manages three
fictional building sites.

| | |
| --- | --- |
| Documents | 173 |
| Questions | 96 |
| Period | 2027-07-20 → 2027-09-24 |
| Split point | after 2027-08-28 — `part_a` 90 documents, `part_b` 83 (no document falls on 2027-08-29) |
| Written by | DeepSeek V4 Pro, key-first |
| Audited by | a second frontier model from a different family, nine rounds |

---

## Why It Exists

Corpus B uses a different domain, cast, and generation model. Results that hold
across both corpora are less likely to depend on one corpus's conventions.

---

## How It Was Made, And What That Guarantees

The answer key defined entities, timelines, superseded values, ambiguous
records, and multi-document facts before generation. DeepSeek V4 Pro wrote the
corpus; a second model family audited it over nine rounds. Neither model is a
shipped benchmark baseline.

### Fixed, and checked at generation time

- documents that described events later than their own date
- supersession chains recited in a single message
- filler inventing change-order and permit numbers
- facts attached to the wrong site
- cross-document facts collapsed into one place
- planted sentences missing altogether

A generation-time checker reported zero violations for these items. It does not
ship; repository tests cover answer-key IDs, citations, bodies, and grading
rules instead.

> The checker did **not** test for an empty body, and two documents ship with
> frontmatter and no body — `E:2027-08-24T12-40-00__1886520e` and
> `E:2027-08-25T15-01-00__42183c16`. No published question depends on either.

### Not fixed

The audit still found prose defects, including answer-like phrasing, similar
records in one thread, and inconsistent incidental dates. Regeneration did not
converge, and the audit records do not ship.

### Guarantee

The guarantee applies to questions, not every sentence. Each expected answer
must appear in the corpus; unverifiable questions are dropped.

| Draft pool | Drafted | Dropped | Shipped | Reasons recorded in |
| --- | ---: | ---: | ---: | --- |
| Curated candidates | 50 | 13 | 37 | `questions/dropped.json` |
| Drafted factual | 70 | 11 | 59 | `questions/factual_dropped.json` |
| **Total** | **120** | **24** | **96** | |

---

## Layout

```text
corpus_b/
├── corpus/                        same document format as corpus A for chat;
│                                 its emails carry 8 of corpus A's 14 fields
│   ├── part_a/                    90 documents, 2027-07-20 .. 2027-08-28
│   │                              (chat/, and `source: chat` — corpus A uses slack/)
│   │   ├── email/
│   │   └── chat/
│   ├── part_b/                    83 documents, 2027-08-30 .. 2027-09-24
│   │   ├── email/
│   │   └── chat/
│   ├── manifest.jsonl             per-document provenance
│   ├── counts.json                the document and message counts
│   └── CANARY.txt                 a string that must not appear in any model output
└── questions/
    ├── questions.jsonl            the 96 questions that ship
    ├── answers.jsonl              the answer key
    ├── dropped.json               the 13 curated candidates dropped, with reasons
    ├── factual_dropped.json       the 11 drafted factual ones dropped, with reasons
    └── factual_items.json         the 59 drafted factual questions that were kept
```

The generator, answer-key specification, and drafts do not ship. The corpus
includes its questions and dropped-question records.

---

## Using It

Point the runner at this corpus instead of corpus A:

```bash
python3 -m bench.runner \
    --adapter adapters/naive_rag \
    --corpus corpus_b/corpus \
    --questions corpus_b/questions/questions.jsonl \
    --gold corpus_b/questions/answers.jsonl
```

> Corpus A and B reports have different fingerprints. Compare one system across
> both corpora; do not compare systems on unmatched corpora.

---

## Known Limitations

- **Synthetic.** Real email is messier: quoted forwards, dead threads, meaning
  that depends on a conversation held in a corridor.
- **One persona, one domain, one language, one scale.**
- **The two models are not fully independent.** The auditor proposed some
  structure and authored line edits in one round.

---

## Metadata

```yaml
name: agent-memory-benchmark-corpus-b
display_name: Corpus B — construction program management
parent: ../README.md
documents: 173
questions: 96
period: 2027-07-20 .. 2027-09-24
split_after: 2027-08-28
domain: construction program management
synthetic: true
authored_by: DeepSeek V4 Pro (key-first), audited by a second frontier model
license: Apache-2.0
```
