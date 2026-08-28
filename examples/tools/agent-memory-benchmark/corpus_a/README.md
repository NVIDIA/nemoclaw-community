<!-- markdownlint-disable MD013 -->
<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->
<!-- markdownlint-enable MD013 -->

# Corpus A — software platform engineering

Six weeks of synthetic email and team chat from a software platform company.
All published results and questions use this corpus.

| | |
| --- | --- |
| Documents | 425 — 200 emails and 225 channel-days of chat (559 messages) |
| Period | 2026-04-16 → 2026-05-27 |
| Split point | after 2026-05-11 — `part_a` 212 documents, `part_b` 213 |
| Domain | a software platform-engineering team |
| Questions asked about it | 186, in [`questions/questions.jsonl`](questions/questions.jsonl) |

> Everyone and everything in it is fictional. See
> [Provenance](#provenance-and-what-was-checked).

---

## Why It Ships In Two Halves

```text
corpus_a/corpus/part_a/   2026-04-16 .. 2026-05-11   212 documents
corpus_a/corpus/part_b/   2026-05-12 .. 2026-05-27   213 documents — supersedes part_a in places
```

The runner ingests both parts in order. The split tests whether a system handles
later claims that supersede earlier ones:

| Question type | What the split lets it test |
| --- | --- |
| `freshness` | reporting a superseded value as if it were current |
| `chain_freshness` | a value that moved twice — where it started and where it ended |
| `as_of` | what was true *at a date*, which a memory that keeps only the current value has thrown away |

A system may rebuild on the second call; its ingest cost records that choice.

---

## Layout

> This README stays outside `corpus_a/corpus/` because the fingerprint hashes
> every file under the corpus root. Adding documentation there would invalidate
> comparison with published results. Corpus B uses the same layout.

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

## What A Document Looks Like

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

## Using It

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

> Corpus A and B reports have different fingerprints. Compare one system across
> both corpora; do not average or compare unmatched reports.

---

## Provenance And What Was Checked

**Fully synthetic.** All identities, organizations, projects, domains, messages,
and technical identifiers are fictional. Nothing came from a live account.

Every address uses an RFC 2606 reserved `.example` domain.

`CANARY.txt` contains a unique training-data marker. The benchmark does not scan
answers for it; a reviewer must check any suspected match.

Full generation and screening record, plus the content hashes that decide whether
two scores are comparable: [`../docs/provenance.md`](../docs/provenance.md).

---

## Known Limitations

- **Synthetic.** Real email is messier: quoted forwards, dead threads, meaning
  that depends on a conversation held in a corridor.
- **One persona, one domain, one language, one scale.** A result here is a result
  about six weeks of one fictional engineering team — which is why
  [`../corpus_b/`](../corpus_b/README.md) exists.
- **Edited for publication.** Corpus B used a different key-first procedure and
  documents its own unresolved defects.

---

## Metadata

```yaml
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
```
