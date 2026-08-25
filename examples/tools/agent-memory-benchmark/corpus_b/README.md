# Corpus B — construction program management

A second corpus, in a domain deliberately far from corpus A's software
engineering, so that a result on one can be checked against the other. Dana
Okafor runs three building sites across permits, inspections, change orders,
concrete pours and steel deliveries. 173 documents, 2027-07-20 to 2027-09-24,
split after 2027-08-28 (no document falls on 2027-08-29). Everyone and
everything in it is fictional.

## Why it exists

One corpus cannot tell you whether a result is about the memory system or about
the corpus. Corpus A is one domain, one cast, one set of conventions, and a
system whose design happens to suit material like it will look better than it
is. This corpus was written from scratch in an unrelated domain, by a different
model family, from an answer key drafted before any document existed. A result
that holds on both is a result about the system.

## How it was made, and what that guarantees

The answer key was written **before** any document existed: entities, a timeline,
and deliberately planted structure — values that get overturned, records that look
alike, things scheduled but never held, facts split across several documents, one
disagreement nobody settles. Documents were then generated from that key, which
is why nothing had to be annotated afterwards and why every fact has exact
provenance.

Two models were used, and neither is a baseline shipped with this benchmark: the corpus
was written by **DeepSeek V4 Pro**, and audited by a second frontier model
from a different family.
The audit ran nine times. It is worth being precise about what it fixed and what
it did not:

* **Fixed, and mechanically enforced now:** documents that described events later
  than their own date; supersession chains recited in a single message; filler
  inventing change-order and permit numbers; facts attached to the wrong site;
  cross-document facts collapsed into one place; planted sentences missing
  altogether. A generation-time checker enforced all of these before
  publication and reported zero; the generator and its review records are not
  part of this contribution.
* **Not fixed:** the reviewer still flags prose-level imperfections — a phrase
  that reads like an answer key, two similar records mentioned in one thread, an
  incidental date that does not line up. Across nine rounds those counts moved
  between roughly 30 and 130 without converging, because each regeneration
  resamples 170 documents and grows a fresh tail of one-off defects. Those are
  generation-time observations; the review records behind them are not part of
  this contribution.

So the guarantee this corpus makes is **about its questions, not about every
sentence of its prose**. Each question is checked against the corpus before it
ships: the expected answer must actually be present, and a question whose answer
cannot be verified is dropped rather than published. 13 of 50 curated
candidates were dropped that
way, and 10 of 70 drafted factual ones — `dropped.json` and
`factual_dropped.json` carry the reason for each.

## Layout

```
corpus/     the documents, in the same format as corpus A
questions/  questions.jsonl, answers.jsonl, and the drop lists with reasons
```

The generator, the answer-key spec it was written from, and the drafts it
produced are not shipped: they are how the corpus was made, not evidence about
it. What ships is the corpus, its questions, and the record of what was
dropped.

## Honest limitations

* Synthetic. Real email is messier: quoted forwards, dead threads, meaning that
  depends on a conversation held in a corridor.
* One persona, one domain, one language, one scale.
* The auditing model proposed some of the planted structure and, in one round,
  authored line edits to bring documents onto the key. It never invented facts —
  the key is ours — but the two models are not fully independent.
