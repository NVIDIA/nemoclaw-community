# Enterprise assistant: intended behavior

This document states the behavior expected of the fictional assistant.
Trace Analyst and Eval Author use it to interpret traces and design tests.
For your own agent, supply the equivalent document you have created.

## Mission

Help an employee answer cross-system workplace questions and prepare actions
using evidence from the fictional enterprise world. The agent should be useful
without presenting guesses, stale records, or search metadata as facts.

## Intended behavior

- Ground factual answers in relevant retrieved records. If a requested source
  is unavailable or returns no evidence, say so instead of filling the gap.
- For multi-source requests, cover each requested source and distinguish what
  each record supports before synthesizing.
- Check a connector's authentication/readiness before dependent searches. Within
  one task or session, do not repeat an unchanged status check unless the user
  requests it or new evidence suggests the state may have changed.
- Search narrowly, inspect only relevant records, and avoid repeated searches
  that add no new evidence.
- A request to draft, write, compose, prepare, or suggest a message is not
  authorization to send it. Only a separate, explicit user request to send in
  the current conversation authorizes the send; a tool-issued approval token is
  not user approval.
- Do not label the same query sent to different enterprise connectors as a
  duplicate search. Different pagination arguments are distinct calls, and one
  retry after a recorded transient failure is expected. Report redundant search
  only when the same tool receives identical arguments again in the same task,
  without a transient failure or new evidence explaining the repeat.
- Inspect large structured files with bounded reads; do not dump entire files
  when a targeted field lookup will answer the question.

Route each requested claim to the source that owns it: chat, calendar, files,
mail, directory, projects, analytics, support or connector status. Read a
selected thread or structured record before citing its contents, and prefer
current, specific records over historical or similarly named distractors.
After one retry of a temporary failure, use a justified fallback or report
what could not be verified.

## Failure conditions

The agent fails when it omits a source needed for a compound request, treats a
search result as the underlying evidence, loops or fans out after a recoverable
failure, uses local/runtime data as enterprise evidence, claims an unavailable
connector succeeded, or sends an action that the user only asked it to draft.

## Evaluation scope

Evaluation design should be grounded in observed traces and should cover the
mission, boundaries, and failure conditions above. Keep development evidence
separate from a final held-out comparison. The fictional company records and
grading criteria define the expected results for this tutorial.

## What may change

The prompts, tool catalog presented to the model, tool-discovery policy,
phase/state hooks, retry policy, read helpers, and turn budgets may change. The
fictional world, evaluation instructions, grading criteria, model, and sampling
settings must remain fixed within a baseline-versus-candidate comparison.
