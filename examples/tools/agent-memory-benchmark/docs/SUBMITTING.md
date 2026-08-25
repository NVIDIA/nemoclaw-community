# Running mnemo against your own system

Two ways in. The first needs nothing from you but a file of answers; the second
gets you the cost numbers as well.

## Path 1 — answer the questions, send the file

Do this if your system cannot be wrapped in a command line, or you just want a
score quickly.

**1. Read the corpus, in order.** `corpus/part_a/` first, then `corpus/part_b/`.
Walk it recursively rather than hardcoding subdirectory names: corpus A files
chat under `slack/` and corpus B under `chat/`, so a path-specific reader
silently ingests zero chat documents on the second corpus. The `doc_id` in each
document's frontmatter and `manifest.jsonl` are the stable interface.
Both halves are plain markdown with a `doc_id` in the frontmatter. The order
matters: `part_b` overturns things `part_a` says, and several questions ask which
version is current. If your system has no notion of ingesting twice, ingest
everything at once and say so — it changes what your ingest cost means, not
whether your answers count.

**2. Answer every question in `questions/questions.jsonl`**, each in a fresh
context. The questions are independent; answering question 40 with question 39
still in the conversation is a different task and scores differently. Use this
instruction verbatim, because every other submission does:

```
Answer the question from the memory you built out of the corpus.

Rules:
1. Be short. Answer with the specific value asked for (a name, date, number,
   version, status), not a paragraph. One sentence is usually enough.
2. Give the CURRENT state. If a later document supersedes an earlier one, the
   later one is the answer; do not present the superseded value as still true.
3. If the corpus does not support an answer, say plainly that it is not in the
   corpus. Never guess. Something that was only scheduled has not happened.
4. Cite the document ids you relied on, exactly as they appear in the corpus
   (for example "E:2026-05-14T09-29-00__eba84193" or "S:D200JOR001_dm@2026-05-21").

Reply with a single JSON object and nothing else:
{"answer": "<your short answer>", "source_ids": ["<doc id>", ...]}
```

**3. Write one JSON object per line** to `answers.jsonl`:

```json
{"id": "fresh-quillon-launch-date", "answer": "2026-07-14", "source_ids": ["S:D200SAM001_dm@2026-05-14"]}
```

`source_ids` is optional. Providing it gets you the evidence diagnostics;
omitting it costs nothing on accuracy.

**4. Score it.** Put `answers.jsonl` in a directory of its own and run:

```bash
python3 tools/regrade.py --run <dir containing your answers.jsonl>
```

That writes `report.json`, `verdicts.jsonl` and `summary.md` into that
directory. Read `summary.md` for accuracy overall and by question type;
`verdicts.jsonl` carries the reason each answer was scored the way it was.

When the answers are for corpus B, pass all three of its paths. `--gold` alone
leaves the tool reading corpus A's questions, and it fails with a `KeyError`:

```bash
python3 tools/regrade.py --run <dir containing your answers.jsonl> \
  --gold corpus_b/questions/answers.jsonl \
  --questions corpus_b/questions/questions.jsonl \
  --corpus corpus_b/corpus
```

## Path 2 — wire it into the harness

Do this if you want cost measured rather than reported. Write an
`adapters/<name>/adapter.json`:

```json
{
  "name": "my-system",
  "model": "the base model you ran on",
  "ingest": ["my-cli", "ingest", "--corpus", "{corpus}", "--state", "{state}"],
  "answer": ["my-cli", "answer", "--state", "{state}"]
}
```

`ingest` is called twice, once per corpus half. `answer` reads
`questions.jsonl` on stdin and writes `answers.jsonl` on stdout. Then:

```bash
python3 -m bench.runner --adapter adapters/my-system
```

The runner points `OPENAI_BASE_URL` and `ANTHROPIC_BASE_URL` at a local proxy and
counts the tokens that actually cross the wire, so nobody has to be trusted about
their own cost. A system running local inference makes no HTTP calls and is
labelled self-reported in the leaderboard.

## What makes a submission comparable

* **Say which base model you used.** A row is a (system × model) pair, and the
  leaderboard groups by model. Two models is better than one: an architectural
  advantage that appears under one model and vanishes under another is not an
  architectural advantage.
* **One question, one context.** See step 2.
* **Don't tune on the corpus.** The whole reason corpus B exists is that corpus A
  came from one system's own test fixture, and that system's lead on it turned out
  not to transfer.
* **Report what you left out.** A system that skips a question type should say so
  rather than let it read as a zero.

**Use the same answer instruction as Path 1.** It is importable, so it cannot
drift from what other submissions used:

```python
from bench.answer_contract import ANSWER_CONTRACT
```

The runner puts the benchmark root on `PYTHONPATH`, so an adapter can import it
directly. Prepend your own scaffolding if you need to; do not weaken these
rules, or the run stops being comparable.

## Which corpus to run

`corpus/` and `questions/` are corpus A. Corpus B lives in `corpus_b/corpus/`
and `corpus_b/questions/`. Pass them explicitly:

```bash
python3 -m bench.runner --adapter adapters/my-system \
  --corpus corpus_b/corpus \
  --questions corpus_b/questions/questions.jsonl \
  --gold corpus_b/questions/answers.jsonl
```

Corpus B is 97 questions over 173 documents. Base (86): `single_hop` 40,
`multi_source` 20, `abstention` 12, `disambiguation` 7, `freshness` 7. Hard
(11): `as_of` 7, `chain_freshness` 2, `disambiguation` 1, `ordering` 1. It is a
smaller and differently balanced set than corpus A, so read the two as separate
results rather than averaging them.

Run at least A and B. A result on one corpus is a result about that corpus.

## Where a result goes

There is no hosted leaderboard. `tools/leaderboard.py` builds a local table
from the runs in a directory you choose, and that is what "leaderboard" means
throughout these docs:

```bash
python3 tools/leaderboard.py --runs results/runs --out results/leaderboard.md
```

To contribute a system rather than just score one, open a pull request adding
`adapters/<name>/` — the adapter definition and whatever code it needs. Keep
run artifacts out of it: they are large, they age, and they are reproducible
from the adapter.
