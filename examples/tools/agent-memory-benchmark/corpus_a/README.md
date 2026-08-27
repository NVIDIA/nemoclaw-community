---
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
name: agent-memory-benchmark-corpus-a
display_name: Corpus A — software platform engineering
parent: ../README.md
location_note: kept outside corpus_a/corpus/ because every file under the corpus root is hashed into the corpus fingerprint
documents: 425
emails: 200
chat_documents: 225
chat_messages: 559
period: 2026-04-16 .. 2026-05-27
split_after: 2026-05-11
questions: 186
synthetic: true
license: Apache-2.0
---

# 💼 Corpus A — software platform engineering

Six weeks of one person's inbox and team chat at a fictional software platform
company: an ingest pipeline being rebuilt, a launch date that moves, a hire, a
cost figure that drops, and the ordinary traffic around all of it. **This is the
corpus every question in `questions/` is asked about, and the one every published
result was produced on.**

| | |
| --- | --- |
| Documents | 425 — 200 emails and 225 channel-days of chat (559 messages) |
| Period | 2026-04-16 → 2026-05-27 |
| Split point | after 2026-05-11 — `part_a` 212 documents, `part_b` 213 |
| Domain | a software platform-engineering team |
| Questions asked about it | 186, in [`questions/questions.jsonl`](questions/questions.jsonl) |

> 🧪 Everyone and everything in it is fictional. See
> [Provenance](#️-provenance-and-what-was-checked).

---

## 📑 Table of Contents

- [🔀 Why It Ships In Two Halves](#-why-it-ships-in-two-halves)
- [🗂️ Layout](#️-layout)
- [📄 What A Document Looks Like](#-what-a-document-looks-like)
- [🚀 Using It](#-using-it)
- [🕵️ Provenance And What Was Checked](#️-provenance-and-what-was-checked)
- [⚠️ Known Limitations](#️-known-limitations)

---

## 🔀 Why It Ships In Two Halves

```text
corpus_a/corpus/part_a/   2026-04-16 .. 2026-05-11   212 documents
corpus_a/corpus/part_b/   2026-05-12 .. 2026-05-27   213 documents — supersedes part_a in places
```

The runner makes **two `ingest` calls, not one**, and feeds them in that order.

That is the whole point of the split. Real memory has to survive being told
something new that contradicts what it already believed — a launch date moves, a
hire is made, a cost figure drops. A system that answers from `part_a` after
reading `part_b` is not remembering, it is stuck. Several question types exist
only to catch that:

| Question type | What the split lets it test |
| --- | --- |
| `freshness` | reporting a superseded value as if it were current |
| `chain_freshness` | a value that moved twice — where it started and where it ended |
| `as_of` | what was true *at a date*, which a memory that keeps only the current value has thrown away |

A system that can only rebuild from scratch on the second call may do so. Its
ingest token count will say so.

---

## 🗂️ Layout

> 📌 This page sits at `corpus_a/README.md`, one level **above** the documents,
> because `bench.fingerprint.hash_tree` hashes **every file** under the corpus
> root — all 428 of them, not only the 425 documents. A README added there
> changes the corpus hash, and every published result stops being comparable to
> what ships. The shipped adapters would not have ingested it (the runner hands
> them `part_a` and `part_b`, and they skip a file with no `doc_id:`), but a
> third-party adapter is handed a directory and cannot be assumed to do either.
> `corpus_b/` has the same shape for the same reason.

```text
corpus_a/
├── README.md                    this page
├── corpus/                      the documents — this is what an adapter is handed
│   ├── part_a/                  212 documents, 2026-04-16 .. 2026-05-11
│   │   ├── email/               97 email documents
│   │   └── slack/               115 channel-day documents
│   ├── part_b/                  213 documents, 2026-05-12 .. 2026-05-27
│   │   ├── email/               103 email documents
│   │   └── slack/               110 channel-day documents
│   ├── manifest.jsonl           425 rows — doc_id, part, path, source, timestamp
│   ├── counts.json              the counts this page and the root README quote
│   └── CANARY.txt               a string that must not appear in any model output
└── questions/                   outside corpus/, so ingest never walks over it
    ├── questions.jsonl          the 186 questions
    ├── answers.jsonl            the answer key and its grading rules
    ├── factual_items.json       ┐
    ├── factual_dropped.json     ├ drafting records, with the reason for each
    └── factual_rejected.json    ┘
```

`counts.json` is the machine-readable form of the table at the top:

```json
{
  "part_a": 212,
  "part_b": 213,
  "email": 200,
  "slack_docs": 225,
  "slack_messages": 559,
  "total_docs": 425
}
```

---

## 📄 What A Document Looks Like

Every document is Markdown with a YAML frontmatter block. Two shapes:

**Email** — one message per file, `doc_id` prefixed `E:`:

```yaml
doc_id: E:2026-04-16T09-12-00__3471799e
source: email
id: AAMkAD3471799E6D7AA56D0980ADC5729284
conversation_id: AAQkAD80C885136280709F824E147EECA32A
folder: inbox-automated
date: 2026-04-16T09:12:00Z
from: GitLab <gitlab@gitlab.examplecorp.example>
to:
  - Alex Chen (@alex) <alex.chen@examplecorp.example>
cc: []
subject: "Atlas | feat: split ingest pipeline into typed waves (!284)"
unread: true
has_attachments: false
```

**Chat** — one channel-day per file, `doc_id` prefixed `S:`:

```yaml
doc_id: S:C200ATLD001_channel@2026-04-21
source: slack
channel_id: C200ATLD001
channel_name: atlas-design
channel_type: channel
date: 2026-04-21
message_count: 5
```

A `doc_id` is what an adapter returns in `source_ids` to earn the evidence
diagnostics, and what `verdicts.jsonl` reports as the evidence an answer cited.

---

## 🚀 Using It

This is the default corpus, so the runner uses it with no flags:

```bash
python3 -m bench.runner --adapter adapters/naive_rag
```

Naming it explicitly is equivalent, and is how you would point at a variant:

```bash
python3 -m bench.runner \
    --adapter adapters/naive_rag \
    --corpus corpus_a/corpus \
    --questions corpus_a/questions/questions.jsonl \
    --gold corpus_a/questions/answers.jsonl
```

> 🔍 A corpus A report and a corpus B report are **not** comparable: the
> `fingerprint` block differs by construction, which is the mechanism that stops
> the two being averaged together. Compare a system against itself across the two
> corpora — that is what [`../corpus_b/`](../corpus_b/README.md) is for.

---

## 🕵️ Provenance And What Was Checked

**Fully synthetic.** Every person, company, project, domain and address is
invented. Every message body was generated by a language model constrained to a
fixed fictional cast written before any document existed, so an identity outside
that cast cannot appear. Nothing was collected from a live mailbox, workspace or
account.

The technical identifiers in the engineering threads — file paths, module names,
table names — describe the fictional codebase the corpus is about. They were
reviewed before publication and renamed where they were not.

**Every address sits under an RFC 2606 reserved domain.** The corpus uses
`examplecorp.example`, `gitlab.examplecorp.example`, `chatplatform.example` and
`metricswatch.example` — all under the `.example` top-level domain, which can
never be registered. This matters more than it looks: the corpus previously used a `.com` that
*reads* like a placeholder but is registrable, so it is not named here either.

**`CANARY.txt` is a training-data marker.** It carries a unique string that
appears nowhere else in this repository. If a model ever emits it, that is
evidence this corpus reached its training data, which would make any score from
that model meaningless. Nothing here watches for it — no grader, report or test
scans an answer for the string. It is a marker for whoever looks, not a gate.

Full generation and screening record, plus the content hashes that decide whether
two scores are comparable: [`../docs/provenance.md`](../docs/provenance.md).

---

## ⚠️ Known Limitations

- **Synthetic.** Real email is messier: quoted forwards, dead threads, meaning
  that depends on a conversation held in a corridor.
- **One persona, one domain, one language, one scale.** A result here is a result
  about six weeks of one fictional engineering team — which is why
  [`../corpus_b/`](../corpus_b/README.md) exists.
- **This corpus was reviewed and edited for publication.** Corpus B was written
  key-first from scratch instead, which is a cleaner *procedure* — though both
  were edited before publication, only the editor differs, and corpus B is the
  one whose page discloses unresolved defects. Neither is the cleaner artifact
  on the evidence that ships.
