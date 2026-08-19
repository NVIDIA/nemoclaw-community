---
name: obligation-review
description: Re-judge open obligations against their current state in the world and re-rank them, on a schedule that does not depend on new mail arriving.
version: 0.1.0
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, triage, ranking]
---

# Reviewing open obligations

You receive the stalest open obligations — those never reviewed, or reviewed
longest ago — and re-judge each one. This runs on its own schedule. A quiet
week still re-ranks, because a list that only changes when mail arrives is a
list that goes wrong precisely when nothing is happening.

You never write to the database. Return one envelope; the writer commits it.

## Read first

`$HERMES_HOME/workspace/memory/index.md`, then the pages that bear on this batch:
`attention/current_priorities.md` always, plus the `projects/` and `people/`
pages the rows touch. Load them once for the whole batch rather than per row.

## Step 1 — has the user already dealt with it?

Before anything else, look for evidence the obligation is finished:

- a reply sent from the user's own address on the thread,
- a later message in the same thread that resolves the ask,
- the requester withdrawing or superseding it,
- the underlying artifact having shipped.

When you find it, emit `MARK_DONE` and put a short user-readable reason in
`urgency_reason` — "replied on the thread 2 days ago", "requester withdrew the
ask". The completed view is an audit trail, so a row must never simply vanish;
the user has to be able to see why it closed. The row keeps its old tier
deliberately.

## Step 2 — re-rank what remains

Order rows by weighing these together. None of them is a formula; they are the
things that actually move an item up or down.

- **Deadline proximity.** Overdue or due within a day outranks due this week,
  which outranks no deadline at all.
- **State change since the last review.** Escalated outranks unchanged, which
  outranks resolved-upstream.
- **Sender and freshness.** A high-importance sender's still-unanswered
  request outranks a peripheral one. A request quietly superseded by a later
  message in the same thread loses its claim.
- **Quiet decay.** Read the originating message's timestamp, not when the row
  was created. If the message is more than about five days old and nothing in
  this batch touches the same subject — no new reply, no follow-up, no related
  update — the world has gone quiet on it. The user has implicitly let it go;
  push it down, usually to the bottom. Genuine urgency produces new signal
  within five days.
- **Manual priority.** When a row carries `manual_priority`, the user has told
  you directly where it belongs. Treat it as strong evidence for your ordering.
  Do not copy it into the tier and do not clear it — it is the user's standing
  instruction, not a value you own.

**On ties, keep the higher position.** Demote only on evidence. Quiet decay is
evidence. "I am not sure" is not.

## Step 3 — the intent gate

Set `intent_gated` per row. It is true when the obligation maps to something
the user has chosen:

- **(a)** an entry in `attention/current_priorities.md`, or
- **(b)** an active goal or project page — active meaning `updated` within 30
  days and Health not a closing state.

A row that has only external urgency — a hard deadline, a senior sender, a
broadcast mention — and matches neither is `false`.

This is the whole point of keeping a memory, so it is worth being explicit
about what it buys: the top tier is reserved for *what the user has chosen to
work on*, not *what the world has chosen to escalate at them*. Without the
memory you can only measure the second. An un-gated row is still visible and
can still rank highly within the middle tier; it simply cannot crowd out the
work the user actually committed to.

**A stale `current_priorities.md` still counts.** Past its decay window, use it
and note in `urgency_reason` that the intent signal was last confirmed on the
page's `updated` date. Turning the gate off because the page is old would empty
the top tier entirely, which is a worse answer than acting on last week's
intent.

## Step 4 — emit

You supply the order and the gate. The caps — at most ten rows in the top tier
and ten in the middle, with un-gated rows cascading down rather than being
dropped — are applied afterwards in code. Do not assign tiers.

```json
{
  "version": 1,
  "pass": "review",
  "decisions": [
    {"source_id": "...", "decision": "KEEP_OPEN", "rank": 1, "intent_gated": true,
     "title": "...", "context": "...", "urgency_reason": "...",
     "kind": "action", "est_effort": "hours"},
    {"source_id": "...", "decision": "MARK_DONE",
     "urgency_reason": "replied on the thread 2 days ago"}
  ]
}
```

Refresh `title` and `context` when the world moved — a title that was accurate
last week can be stale now. Every row you were given appears exactly once.

## Then write it

Save the envelope and run the writer:

```bash
python3 "$HERMES_HOME/scripts/apply_decisions.py" < envelope.json
```

Report the counts it prints. An envelope that was printed but never written is
a run that did nothing.
