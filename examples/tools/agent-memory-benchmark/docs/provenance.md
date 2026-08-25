# Provenance

Where the corpora came from, how they were made, what was checked before
publication, and how to tell whether two scores are comparable.

## Contributor

Authored and maintained by NVIDIA, contributed to NemoClaw Community under
Apache-2.0. See the repository `LICENSE`.

## What the corpora are

Both corpora are **fully synthetic**. Every person, company, project, domain
and address in them is invented, and every message body was generated from a
fixed fictional cast defined before any document existed. Nothing was collected
from a live mailbox, workspace or account, and no real message, identifier,
address or organization appears in either.

| | Documents | Period | Domain |
| --- | ---: | --- | --- |
| Corpus A | 425 | 2026-04-16 .. 2026-05-27 | a software platform engineering team |
| Corpus B | 173 | 2027-07-19 .. 2027-09-24 | a construction program manager |

## How they were generated

**Corpus A** was generated from a fixed cast — people, organizations, projects
and domains — written before any document. A language model produced the
message bodies constrained to that cast, so an identity outside it cannot
appear. The documents were then split at a cutoff into `part_a` and `part_b`,
where the second half supersedes the first in places, and the answer key was
written against the result.

**Corpus B** was written key-first: the entities, the timeline and the planted
structure (values that get overturned, records that look alike, things
scheduled but never held, facts split across several documents, one
disagreement nobody settles) were all fixed before generation, and the
documents were generated from that key. It used a different model family from
corpus A's, in a deliberately unrelated domain, so that a result on one corpus
can be checked against the other. `corpus_b/README.md` records what its audit
fixed and what it did not.

## What was checked before publication

**Domains.** Every address and URL in both corpora sits under a domain reserved
by RFC 2606 — the `.example` top-level domain. This matters more than it looks:
corpus A previously used `example-co.com`, which reads like a placeholder but
is an ordinary registrable `.com`, and is in fact registered. A name that
merely *looks* fake is not reserved. Verified: no address in either corpus
resolves to a domain a third party can own.

**Other identifiers that can be accidentally real.** The corpora contain no IP
addresses and no telephone numbers, so the equivalent reserved ranges
(RFC 5737 documentation networks, the `555-01xx` telephone block) do not
arise. Every URL points at a `.example` host.

**Organization and project names.** The invented project names were screened
against internal sources for collision with real projects. Where a name
collided with something publicly marketed, it was renamed — the project now
called Quillon was one such rename. Names that collide only with unrelated
internal work were kept: the corpus describes an ingest pipeline, an evaluation
framework and a migration, and none of that content has anything to do with the
work it shares a word with. A shared word is not a disclosure.

**No real content.** Because every body was generated rather than collected or
redacted, there is no underlying real message that a reader could recover.

Any resemblance to a real project or organization is coincidental.

## Canary

`corpus/CANARY.txt` carries a unique string. If a language model emits it, that
model was trained on this corpus, and any score it produces here is
meaningless. Leave the file in place.

## Content hashes

A score is comparable to another score only if both were produced against the
same documents, the same questions and the same grading rules. Every
`report.json` carries a `fingerprint` block; compare it against the values
below to know which version a stored run was graded at.

Hashing rule `sha256-v1`: every file under the tree, in sorted order, with its
path and bytes fed into one SHA-256. A renamed document changes the hash even
if its contents did not.

| Artifact | Files | SHA-256 |
| --- | ---: | --- |
| `corpus/` (corpus A) | 428 | `c36ca1db72ebab8fd962701ffaffacf679de66d1d713d763f651b47cda3f1110` |
| `corpus_b/corpus/` (corpus B) | 176 | `ef57ca34e3937b5c4ae847428676550d3a036c5a73b7ed9ae3c6a038e9187e96` |
| `questions/questions.jsonl` | 1 | `ab24142d7392bf02a764187e9ef410d52e60f9aba2b8afe74bca0c31fd6412f5` |
| `gold/answers.jsonl` | 1 | `9bfd81ad88da5adbd0273d896add1dcda8e87a26786aa8d637f44928789a400e` |
| `corpus_b/questions/questions.jsonl` | 1 | `8ea778aa8abb4e4e7c86a6517f5ea33b1b79f43b359186cbb9be2284375714e3` |

Recompute at any time:

```bash
python3 -c "import sys; sys.path.insert(0, '.'); \
from pathlib import Path; from bench.fingerprint import hash_tree; \
print(hash_tree(Path('corpus')))"
```

Scores graded under different hashes should not be compared. If a grading rule
turns out to be wrong, fix it and re-score the stored answers with
`tools/regrade.py` — no tokens, no re-run — and record the new hash.
