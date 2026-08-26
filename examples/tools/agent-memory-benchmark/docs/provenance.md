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
from a live mailbox, workspace or account, and no real message, address or
organization appears in either. The technical identifiers in corpus A's
engineering threads — file paths, module names, table names — belong to the
fictional codebase the corpus describes; they were reviewed before publication
and renamed where they were not.

| | Documents | Period | Domain |
| --- | ---: | --- | --- |
| Corpus A | 425 | 2026-04-16 .. 2026-05-27 | a software platform engineering team |
| Corpus B | 173 | 2027-07-20 .. 2027-09-24 | a construction program manager |

## How they were generated

**Corpus A** began as an existing synthetic test fixture and was reviewed and
edited for publication. It was generated from a fixed cast — people,
organizations, projects and domains — written before any document. A language model produced the
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

**Organization and project names.** The invented project names were checked for collision with real products. Where a name
collided with something publicly marketed, it was renamed — the project now
called Quillon was one such rename. A shared word is not a disclosure, so a
name was changed only where the collision was with something publicly
marketed.

**No real content.** Because every body was generated rather than collected or
redacted, there is no underlying real message that a reader could recover.

Any resemblance to a real project or organization is coincidental.

## Canary

`corpus/CANARY.txt` and `corpus_b/corpus/CANARY.txt` each carry a unique
string — one per corpus, so a leak can be attributed to the corpus it came
from. If a language model emits either, that model was trained on that corpus,
and any score it produces there is meaningless. Leave both files in place.

## Content hashes

A score is comparable to another score only if both were produced against the
same documents, the same questions and the same grading rules. Every
`report.json` carries a `fingerprint` block; compare it against the values
below to know which version a stored run was graded at.

Hashing rule `sha256-v1`: for a directory, every file under it in sorted order (excluding `__pycache__`),
with its path and bytes fed into one SHA-256, so a renamed document changes the
hash even if its contents did not (`bench.fingerprint.hash_tree`). A
single-file artifact is hashed as its bytes alone, with no path framing
(`bench.fingerprint.hash_file`).

| Artifact | Files | SHA-256 |
| --- | ---: | --- |
| `corpus/` (corpus A) | 428 | `12772a521d95bd777625924d8ec7b151d0d9c0e388f4dc4bafbd7540130cc9a9` |
| `corpus_b/corpus/` (corpus B) | 176 | `ef57ca34e3937b5c4ae847428676550d3a036c5a73b7ed9ae3c6a038e9187e96` |
| `questions/questions.jsonl` | 1 | `6d38f6c11edbefb4baa77b8014af1920c48ab65f3647a2bb10daa691e9259b06` |
| `gold/answers.jsonl` | 1 | `55a66b80ff0f62d8b3a340dcbb9cc970a011922b1e509269c4402192f9504970` |
| `corpus_b/questions/answers.jsonl` | 1 | `d2543be56bbf072b5c68b94f1939d16d0b7c6472812951acbc9913c803803671` |
| `corpus_b/questions/questions.jsonl` | 1 | `e5d8414e712911e04d314ef2b5fa81caa0058e794eb95c12533f8cbe3d43f0d4` |

Recompute at any time:

```bash
python3 -c "import sys; sys.path.insert(0, '.'); \
from pathlib import Path; from bench.fingerprint import hash_tree, hash_file; \
print(hash_tree(Path('corpus'))); \
print(hash_file(Path('questions/questions.jsonl')))"
```

Grading also depends on the date-normalization years (`MNEMO_DEFAULT_YEAR`,
default `2026`; `MNEMO_ALT_YEARS`, default `2027`). Both are recorded in the
report's `fingerprint` block. Leave them at their defaults for a comparable
run.

Scores graded under different hashes must not be compared. If a grading rule
turns out to be wrong, fix it and re-score the stored answers with
`tools/regrade.py` — no tokens, no re-run — and record the new hash.
