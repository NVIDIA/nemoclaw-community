---
name: preference-update
description: Update a bounded preference policy from the user's repeated corrections, without ever overwriting the user's own choices.
version: 0.1.0
license: Apache-2.0
platforms: [linux]
metadata:
  hermes:
    tags: [memory, policy, preferences]
---

# Updating preferences from corrections

Every time the user ignores a row or overrides its priority, they are
correcting a judgment. One correction is an accident. Three of the same shape
is a preference, and a preference belongs in writing where the next run can
read it.

Nothing here trains a model. The output is a bounded text policy that later
runs read as input — it can be inspected, edited by hand, and deleted, and
deleting it returns the system to its default judgment.

This skill reads the audit trail and edits one file. It never touches an
obligation.

## The invariant

**Never write to `obligations`.** Not `priority`, not `manual_priority`, not
`status`. The user's overrides are theirs; this skill only reads them.
A run that changes a row has failed, however good its reasoning was.

The policy lands in `workspace/policy/preferences.md`, which
`inbound-judging` reads as a prior and `obligation-review` reads as context.

## Step 1 — collect

Read the audit trail for user-authored corrections since the last run:

```sql
SELECT e.event_type, e.after_json, o.title, o.kind, i.source, i.sender
  FROM events e
  JOIN obligations o ON o.id = e.obligation_id
  JOIN items i ON i.source_id = o.source_id
 WHERE e.actor = 'user'
   AND e.event_type IN ('ignored', 'priority_override')
   AND e.ts > :last_run
```

Note that `actor` matters. Rows this agent changed are not corrections;
reading your own output back as evidence is how a system talks itself into a
belief.

## Step 2 — group

Group the corrections by what they have in common. Useful groupings, roughly
in order of how often they turn out to be real:

- the same sender, or the same sender domain,
- the same recurring subject shape — a build notification, a newsletter, an
  automated digest,
- the same `kind` from the same source.

A pattern is one plain sentence that would describe most rows in its group. If
you cannot write that sentence without listing exceptions, it is not a pattern.

## Step 3 — apply the threshold

**A pattern qualifies only when it covers at least three corrections.** Below
that, leave it alone and let the next run decide — two of anything is a
coincidence you would be encoding forever.

The threshold is deliberately fixed. A system permitted to lower its own bar
for what counts as a preference eventually accepts everything.

## Step 4 — write

Read `workspace/policy/preferences.md`, creating it with an empty
`## Observed Preferences` section if absent.

If an existing entry already says the same thing — the same pattern in other
words counts — do nothing. Restating a known pattern inflates the file and
teaches the reader nothing.

Otherwise append under `## Observed Preferences`, newest first:

```markdown
- [2026-08-18] Automated build notifications from ci@example.com — the user
  ignores these; do not create a row unless a human is named in the body.
```

Each entry states the pattern and what to do about it. "Deprioritize
newsletters" is not actionable; "newsletters from the vendor list are
review-only unless they name a deadline" is.

**Cap the section at 20 entries.** Past that, drop the oldest. A policy file
longer than one screen stops being read, and an unread policy is worse than
none — it implies the system is adapting when it is not.

Read the file back after editing and confirm both that the entry landed and
that the cap held.

## Step 5 — log

Append one entry to `workspace/memory/log.md`, including runs that changed
nothing:

```markdown
## [2026-08-18T09:20:00Z] preference-update
- 7 user corrections since last run, 2 patterns above threshold, 1 already known
- appended: automated build notifications from ci@example.com
```

A run that changed nothing is a useful signal — it means the judging skill is
currently matching the user's taste.
