# Methodology

## What is being measured

One task, run end to end: read a corpus of personal email and chat, build memory
from it, then answer questions. The benchmark scores the answers, not the memory
— any internal representation is allowed, and none is inspected.

Two axes are reported separately and never combined into a headline number:

* **Quality** — accuracy per question type, plus abstention behaviour.
* **Cost** — tokens spent building memory versus tokens spent per answer.

## Why the cost split matters

Systems trade these against each other. Reasoning at ingest time — resolving
entities, merging duplicates, writing a consolidated page — is expensive once and
cheap forever after. Storing raw chunks and retrieving at question time is nearly
free to ingest and pays on every query.

Neither is universally right. Which one wins depends on how many questions the
memory will ever be asked:

```
total = ingest_tokens + N × per_question_tokens
```

Reporting a single blended score would hide exactly the trade-off a practitioner
needs to make.

## Why hop count is a cost, not a penalty

An early draft scored retrieval with `recall@k`. That is a vector-store-shaped
metric: it assumes one retrieval returns k chunks. A system that reads an index
page, follows a cross-reference, and then opens a source document has no k at
all — and a fact about one person genuinely does live across eight emails.
Multi-hop retrieval is the task, not a defect.

So hops and tokens are counted on the cost axis, and never subtracted from
quality. A system that takes twenty hops and answers correctly scores the same
quality as one that takes one, and pays the difference where it belongs.

`evidence_recall` replaced `recall@k`: of the documents the answer key cites, how
many did the system actually touch or cite — however it got there. A vector store
reports retrieved chunk ids, a wiki reader reports pages and source ids, a graph
reports traversed nodes. Same measurement, no architectural bias.

## Why the base model is a leaderboard column

The same memory architecture scored with two different base models can differ
more than two architectures scored with the same one. A submission is therefore a
(system × model) pair, and rows are grouped by model rather than ranked globally.

A submission that runs two base models and publishes the difference is worth
more than one that does not. An
architectural advantage that appears under one model and vanishes under another
is not an architectural advantage.

## How the hard set was written

The 31 hard questions were written after the base set saturated, and each type
starts from a property of the corpus rather than from a document: a value that
moves twice, a set with one member that does not belong, a fact that was true
at a date but is not now, two conditions that each match several candidates
alone. Candidates were drafted against the answer key, then checked against the
corpus the same way the base set was — the expected answer must actually be
present and reachable, and a candidate whose answer could not be verified was
dropped rather than published. `as_of` was written deliberately to be
adversarial to ingest-time consolidation, since a memory that keeps only the
current value has thrown the answer away.

The two-group split is an annotation on the answer key. A corpus whose
freshness entries do not carry it reports "not annotated for this corpus"
rather than a rate, because an unannotated question is not the same as an
absent one.

## Why there is no judge model

All 186 questions grade deterministically. Answers are normalized for case,
punctuation, and date spelling, then matched by a per-mode rule set:

* `string_any` — `reject` (any of these means wrong, checked first),
  `require_all` (every element must appear), `accept` (any of these means
  correct).
* `boolean` — the same three, plus `expected` (`yes` or `no`).
* `ordering` — `sequence`: every element present, in that order.
* `abstain` — `reject`, plus `accept_as_decline` for a phrasing that rejects
  the question's premise rather than answering it.

This was a constraint, not a discovery. A judge model is a moving part: it gets
deprecated, retuned, and replaced, and every one of those events silently
re-scores history. Questions were written to have short, checkable answers so
that the scoring path contains no model at all.

The cost is expressive range — "summarize this project's trajectory" cannot be
graded this way and so is not asked. That is an acceptable trade for scores that
still mean the same thing in three years.

## Question construction

Curated questions (freshness, abstention, disambiguation, citation) were written
by hand from a structured answer key that already recorded, for each fact, the
documents supporting it and the traps that fact invites.

Factual questions were drafted by a model and then filtered twice:

1. **Groundedness.** The proposed answer must occur verbatim in the documents the
   fact cites. The model is trusted for phrasing, never for truth; anything it
   invents fails this check and is discarded.
2. **Adversarial review.** A second pass, prompted to find reasons to reject,
   removed questions that were not self-contained, had non-unique answers, or
   asked about formatting trivia (a URL slug, a username inside a link). 17 of
   120 drafts were dropped.

Every gold citation is verified against the corpus manifest at build time. The
source answer key contained one dangling reference — a channel-day with no
messages in it — which now fails the build rather than sitting unnoticed.

## Abstention

Thirteen questions have no correct answer. They ask about a project that does not
exist, a review whose date falls after the corpus ends, a merge request that
exists only as a reserved URL.

Scheduled is not done. A system that describes how the scheduled auth-changes
review went is
wrong, however plausible the description; a system that says the corpus does not
say is right. This is scored as its own type because it is the failure mode most
invisible in aggregate accuracy — confabulation reads as coverage.

## Freshness

Twelve questions ask for a value that a later document changed. They are reported
in two groups:

* **with a competing stale claim in corpus** — the superseded value is also in
  the corpus, so the system has to prefer the newer one.
* **recency-only** — the superseded value never appears; the system merely has to
  report what the corpus says.

The second group is easier and is reported separately rather than being counted
as if it were the first.

## Token accounting

The runner starts a local proxy and points the system under test at it. Tokens
are read off the responses that actually cross the wire, in either OpenAI or
Anthropic usage format, streaming or not. Nothing is self-reported.

A system running local inference makes no HTTP calls, and its row is labelled
accordingly rather than being silently credited with zero cost.

Dollar figures come from a dated price table in `bench/pricing.py`. Tokens are
the primary number; dollars are a convenience that any reader can recompute
against a newer table.

## Known limitations

* **Two corpora, two personas.** 425 documents from one invented professional
  life and 173 from another.
  Results describe behaviour on this shape of data, not on personal archives in
  general.
* **Retrieval is bundled into the score.** The benchmark measures ingestion
  through the question answering it enables, so a system with weak ingestion and strong retrieval
  can score well. Evidence recall is reported separately to expose that case, but
  the two are not fully separable by design.
* **English questions and answers.**
* **Contamination.** The corpus is public and will eventually be crawled. It
  carries a canary string (`corpus/CANARY.txt`) so future contamination can be
  detected rather than merely suspected.
* **Deterministic grading rejects some correct answers.** A correct answer phrased
  entirely outside the `accept` set scores wrong. Per-question verdicts ship with
  every run so disputes are auditable, and grading rules are versioned with the
  gold file.
