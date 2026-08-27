---
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
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
---

# 🏗️ Corpus B — construction program management

A second corpus, in a domain deliberately far from corpus A's software
engineering, so that a result on one can be checked against the other. Dana
Okafor runs three building sites across permits, inspections, change orders,
concrete pours and steel deliveries. **Everyone and everything in it is
fictional.**

| | |
| --- | --- |
| Documents | 173 |
| Questions | 96 |
| Period | 2027-07-20 → 2027-09-24 |
| Split point | after 2027-08-28 — `part_a` 90 documents, `part_b` 83 (no document falls on 2027-08-29) |
| Written by | DeepSeek V4 Pro, key-first |
| Audited by | a second frontier model from a different family, nine rounds |

---

## 📑 Table of Contents

- [🎯 Why It Exists](#-why-it-exists)
- [🔨 How It Was Made, And What That Guarantees](#-how-it-was-made-and-what-that-guarantees)
- [🗂️ Layout](#️-layout)
- [🚀 Using It](#-using-it)
- [⚠️ Known Limitations](#️-known-limitations)

---

## 🎯 Why It Exists

One corpus cannot tell you whether a result is about the memory system or about
the corpus. Corpus A is one domain, one cast, one set of conventions — and a
system whose design happens to suit material like it will look better than it
is.

This corpus was written from scratch in an unrelated domain, by a different
model family, from an answer key drafted before any document existed. **A result
that holds on both is a result about the system.**

---

## 🔨 How It Was Made, And What That Guarantees

The answer key was written **before** any document existed: entities, a timeline,
and deliberately planted structure — values that get overturned, records that
look alike, things scheduled but never held, facts split across several
documents, one disagreement nobody settles. Documents were then generated from
that key, which is why nothing had to be annotated afterwards and why every fact
has exact provenance.

Two models were used, and **neither is a baseline shipped with this benchmark**:
the corpus was written by **DeepSeek V4 Pro** and audited by a second frontier
model from a different family. The audit ran nine times. It is worth being
precise about what it fixed and what it did not.

### ✅ Fixed, and checked at generation time

- documents that described events later than their own date
- supersession chains recited in a single message
- filler inventing change-order and permit numbers
- facts attached to the wrong site
- cross-document facts collapsed into one place
- planted sentences missing altogether

A generation-time checker enforced all of these before publication and reported
zero. **That checker is not part of this contribution**, so nothing in this
repository re-checks them; what ships is the corpus it produced. The tests that
do run here cover the answer key — id agreement, dangling citations, empty-body
citations, grading-rule sanity — not the six items above.

> 📌 The checker did **not** test for an empty body, and two documents ship with
> frontmatter and no body — `E:2027-08-24T12-40-00__1886520e` and
> `E:2027-08-25T15-01-00__42183c16`. No published question depends on either.

### ❌ Not fixed

The reviewer still flags prose-level imperfections: a phrase that reads like an
answer key, two similar records mentioned in one thread, an incidental date that
does not line up. Across nine rounds those counts moved between roughly 30 and
130 without converging, because each regeneration resamples all 173 documents and
grows a fresh tail of one-off defects. Those are generation-time observations;
the review records behind them are not part of this contribution.

### 🎯 So what is actually guaranteed

**The guarantee this corpus makes is about its questions, not about every
sentence of its prose.** Each question is checked against the corpus before it
ships: the expected answer must actually be present, and a question whose answer
cannot be verified is dropped rather than published.

| Draft pool | Drafted | Dropped | Shipped | Reasons recorded in |
| --- | ---: | ---: | ---: | --- |
| Curated candidates | 50 | 13 | 37 | `questions/dropped.json` |
| Drafted factual | 70 | 11 | 59 | `questions/factual_dropped.json` |
| **Total** | **120** | **24** | **96** | |

---

## 🗂️ Layout

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

The generator, the answer-key spec it was written from, and the drafts it
produced are **not** shipped: they are how the corpus was made, not evidence
about it. What ships is the corpus, its questions, and the record of what was
dropped.

---

## 🚀 Using It

Point the runner at this corpus instead of corpus A:

```bash
python3 -m bench.runner \
    --adapter adapters/naive_rag \
    --corpus corpus_b/corpus \
    --questions corpus_b/questions/questions.jsonl \
    --gold corpus_b/questions/answers.jsonl
```

> 🔍 A corpus B report is **not** comparable with a corpus A report: the
> `fingerprint` block differs by construction, which is the mechanism that stops
> the two being averaged together. Compare a system against itself across the two
> corpora, not one system on A against another on B.

---

## ⚠️ Known Limitations

- **Synthetic.** Real email is messier: quoted forwards, dead threads, meaning
  that depends on a conversation held in a corridor.
- **One persona, one domain, one language, one scale.**
- **The two models are not fully independent.** The auditing model proposed some
  of the planted structure and, in one round, authored line edits to bring
  documents onto the key. It never invented facts — the key is ours — but they
  are not independent.
