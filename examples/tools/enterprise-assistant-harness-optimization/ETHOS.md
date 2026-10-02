---
name: enterprise-assistant-demo
status: approved-demo-scope
---

# Enterprise assistant demo ethos

## Mission

Help an employee answer cross-system workplace questions and prepare actions
using evidence from the fictional enterprise world. The agent should be useful
without presenting guesses, stale records, or search metadata as facts.

## Intended behavior

- Route each requested claim to the source that owns it, including chat,
  calendar, files, mail, directory, projects, analytics, support, or connector
  status.
- Read a selected thread or structured record before citing its contents.
- Prefer current, specific records over historical or similarly named distractors.
- Retry a temporary failure once with the same request, then use only a clearly
  justified fallback and stop.
- Inspect large structured files through bounded reads rather than loading or
  enumerating the whole object.
- Prepare drafts when asked, but do not send or mutate external state without
  explicit approval.
- State what could not be verified when evidence or connector access is missing.

## Failure conditions

The agent fails when it omits a source needed for a compound request, treats a
search result as the underlying evidence, loops or fans out after a recoverable
failure, uses local/runtime data as enterprise evidence, claims an unavailable
connector succeeded, or sends an action that the user only asked it to draft.

## Evaluation scope

Evaluation design should be grounded in observed traces and should cover the
mission, boundaries, and failure conditions above. Keep development evidence
separate from a final held-out comparison. The deterministic fixture world and
verifiers define tutorial truth; this ethos does not claim production completeness.

## What may change

The model, prompts, tool catalog presented to the model, tool-discovery policy,
phase/state hooks, retry policy, read helpers, and turn budgets may change. The
fixture world, eval instructions, verifier criteria, model, and sampling settings
must remain fixed within a baseline-versus-candidate comparison.
