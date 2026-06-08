---
name: financial-analyst-playbook
description: Learn and reuse a user's preferred analyst brief format, caveat style, and follow-up workflow during a financial research session.
---

# financial-analyst-playbook

Use this skill when the user asks the assistant to remember a format, improve
future answers, apply a previous structure, create a repeatable workflow, or
answer a follow-up that depends on earlier preferences in the same session.

This skill does not store secrets, account data, or trading instructions. It
only captures public-data research preferences and answer format choices.

## What to remember

Track these preferences from the conversation:

- preferred section order
- preferred length and density
- whether the user wants tables, bullets, or email prose
- recurring caveats they want included
- tickers, sector scope, and comparison set from the current session
- "facts vs hypotheses vs checks" distinctions

If the user says "remember this", "use this format next time", "make this the
default", or similar, acknowledge the preference explicitly and restate it in
one concise sentence.

## Default learned format

When the user has not specified a format, prefer:

1. **Snapshot** — public quote context, source, timestamp, and caveat.
2. **SEC Facts** — reported metrics with fiscal period and filing date.
3. **Hypotheses** — what the facts could imply, clearly labeled.
4. **Checks** — what to verify before acting.
5. **Caveat** — public-data only, not investment advice.

## Follow-up behavior

For follow-up questions:

- Reuse the tickers and scope from the prior answer unless the user changes
  them.
- Do not re-ask for information already present in the session.
- Say which remembered preference is being applied.
- If a follow-up needs fresh data, call the relevant data skill again.
- If a follow-up only asks to reformat or explain prior output, do not invent
  new facts.

## Skill coordination

Use this skill alongside:

- `financial-market-snapshot` when the learned workflow needs quote context.
- `sec-company-facts` when the learned workflow needs reported company facts.
- `financial-analyst-brief` when producing a concise memo or email reply.

## Pitfalls

- Do not claim permanent cross-session memory unless a persistent skill or
  saved artifact was actually created.
- Do not claim a new skill, file, or durable playbook was saved unless an
  external tool actually created that artifact.
- Do not remember private information, credentials, or trading instructions.
- Do not turn a learned format into investment advice.
- Do not let a remembered preference override data freshness or caveats.
