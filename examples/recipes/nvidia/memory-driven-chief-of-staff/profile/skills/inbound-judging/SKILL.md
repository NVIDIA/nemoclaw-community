---
name: inbound-judging
description: Decide which newly-arrived email and Slack messages create an obligation for the user, and craft the row that represents each one.
version: 0.1.0
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, triage, intake]
---

# Judging inbound messages

You receive a slice of messages that have never been judged, plus the user's
currently open obligations. Decide which messages create an obligation, craft a
row for each, and return one JSON envelope. You never write to the database —
`scripts/apply_decisions.py` does that.

## Read first

- `workspace/memory/index.md`, then only the pages it names that bear on this
  slice — typically `people/` for the senders and the relevant `projects/`.
- `workspace/policy/preferences.md` if it exists. It records what this user
  has repeatedly ignored or re-ranked. Treat it as a strong prior, not a rule:
  a pattern ignored eight times is probably noise, but an unmistakably urgent
  instance of it is still an obligation.

## Stage 1 — flag

Mark a message when **any** of these hold:

1. The sender's `people/<slug>.md` has `importance: high`.
2. `addressing` is `direct` or `mentioned`, and the body carries a priority
   signal — a deadline, a date, "before you leave today", an explicit ask.
   A `broadcast` item needs a stronger reason than urgency alone; being sent
   to a list is not being asked.
3. `unread` is 1 and the sender is a person rather than a `noreply@` /
   `do-not-reply@` style address. Slack items leave `unread` empty, so this
   rule simply does not apply to them.
4. It refers to something already represented in the open obligations —
   the same ticket, thread, or deliverable.

**Suppress your own output.** Summaries, briefings and digests this agent
generated are derived text, not evidence. If one mentions a real obligation,
act only when the original message is in this slice or already has a row.

**Suppress the already-handled.** Compare each candidate against the recently
completed and ignored obligations in your input. A reminder, a re-send, an
"overdue" nudge or a thank-you about work the user already finished gets no
row, even though it arrived as a new message with a new id. Match on the
underlying real-world obligation — same person, same artifact, same request —
not on wording. The exception is a genuinely new and distinct ask: propose
that new action alone, and say in `context` that the earlier related task was
already resolved.

Everything you do not flag is `SKIP`. That is a terminal state, so an item is
never re-judged, and the cost of a slice stays bounded. Be willing to use it.

## Stage 2 — craft the row

### Title

The title is the only field the user sees without opening anything. It must
stand alone.

1. **At most 80 characters.** Hard cap. Trim tail tags; the priority field
   already carries urgency.
2. **Lead with the verb the user will execute** — Draft, Reply to, Review,
   Investigate, Decide, Schedule, Renew, Verify, Prepare, Ship.
3. **Self-sufficient.** Someone reading only the title, with no source and no
   context, must know what to do.
4. **Never open with** `Work on`, `Coordinate with`, `Monitor`, `Track`,
   `Follow up on`, `Handle`, `Look into`, `Check on`. Those are labels
   pretending to be actions.
5. **Never reuse a subject line.** Translate the intent into an action.

| Subject | Wrong | Right |
| --- | --- | --- |
| `Q3 capacity planning` | `Work on Q3 capacity planning` | `Send Q3 headcount numbers to Dana by Thursday` |
| `Re: vendor contract` | `Follow up on vendor contract` | `Decide whether to accept the vendor's Sept 2 window` |
| `BILL-441: migration dry run` | `Track BILL-441` | `Schedule the billing migration dry run (BILL-441)` |

### Context

At most three bullets. What the user needs in order to act without opening the
source. Not a summary of the message — the parts that change what they would
do.

### `kind`

`response` when the deliverable is the reply itself. `action` when the work
happens elsewhere and a reply is incidental. A message that asks for both
takes the one holding the bulk of the effort; mention the other in `context`.
There is deliberately no third value.

### `est_effort`

`minutes` (5-30), `hours` (1-4), `day` (4-8), `multi_day`. One focused
sitting, not elapsed calendar time. `response` rows are almost always
`minutes`; use `hours` only for a genuinely substantial write-up.

**When uncertain, choose the higher tier.** Over-estimating costs the user
nothing. Under-estimating lures them into starting something they cannot
finish.

### `intent_gated`

Set `true` when the obligation maps to something the user has chosen to work
on, judged against the memory:

- an entry in `attention/current_priorities.md`, or
- an active project or goal page — a project is active when its `updated` is
  within 30 days and Health is not a closing state.

Set `false` when the message is merely urgent — a tight deadline, an important
sender, a broadcast mention. External pressure is not the same as intent, and
only intent earns the top tier.

**A stale `current_priorities.md` still counts.** If the page is past its decay
window, use it anyway and note in `urgency_reason` that the priorities it
reflects were last confirmed on its `updated` date. Out of date is not the same
as wrong, and switching the gate off entirely would push every row into the
middle tier — worse than acting on slightly old intent.

## Stage 3 — rank and emit

Order the rows you are keeping by how much they deserve the user's attention.
You decide the order; the caps and tiers are applied afterwards in code, so do
not assign priorities yourself.

Emit exactly one envelope, nothing else:

```json
{
  "version": 1,
  "pass": "intake",
  "decisions": [
    {"source_id": "...", "decision": "CREATE", "rank": 1, "intent_gated": true,
     "title": "...", "context": "...", "urgency_reason": "...",
     "kind": "response", "est_effort": "minutes"},
    {"source_id": "...", "decision": "SKIP"}
  ],
  "cursor": {"source": "email", "scope": "inbox", "value": "..."}
}
```

Every message in the slice appears exactly once. A message you neither create
nor skip is a bug — the item stays `pending` and will be re-judged forever.
