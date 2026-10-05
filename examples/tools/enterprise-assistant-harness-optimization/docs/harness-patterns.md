# Reusable agent-harness patterns

These are hypotheses to test against traces, not universal defaults. Freeze the
eval before changing the harness, then require held-out improvement.

This example tests the approval-boundary pattern. The other patterns below are
possible extensions when your own traces justify them; they are not measured
changes in this example's candidate.

## Bounded structured reads

**Failure:** The model reads a huge JSON result, loses important fields, or
repeatedly guesses paths.

**Pattern:** Search for the artifact, inspect the reader schema, then request a
small JSON Pointer such as `/evidence`. Return value, type, truncation, and
available child keys. Never silently truncate.

**Test:** Put the target below a large appendix and verify correct retrieval
with bounded bytes and calls. A corresponding Harbor verifier should require
the search and bounded read while enforcing the overall call budget.

## Tool downsampling with discovery

**Failure:** A large catalog sends the agent into local files, web search,
session history, or code tools instead of the authoritative enterprise source.

**Pattern:** Keep the full catalog auditable, directly expose a task-relevant
subset, and retain a discovery route. Do not hide safety or approval controls.

**Test:** Include held-outs that need a non-obvious tool. Compare a smaller
initial tool list with the full list while preserving discovery access.

## Evidence-state transitions

**Failure:** The agent answers after only one part of a compound request,
treats search metadata as evidence, or continues searching after coverage.

**Pattern:**

```text
classify → route claims → retrieve → read/inspect → verify coverage → answer
```

Track the authoritative source for each claim. Read selected chat/mail threads,
stop when all claims are supported, and report unavailable evidence explicitly.
Emit phase and transition reasons into traces when the runtime supports hooks.

**Test:** Separate answer, trajectory, and mutation assertions. Include
zero-source, one-source, multi-source, unavailable-source, and approval-gated
tasks.

## Exact bounded retry

**Failure:** The model mutates the query after a transient error, retries
indefinitely, or mistakes authentication failure for a transient failure.

**Pattern:** Classify the failing boundary, retry the identical idempotent call
once, then take one declared fallback or report the limitation. Never
automatically retry a mutation.

**Test:** Inject a transient failure, allow one identical retry, then check that
the agent selects a justified fallback. Retain retry count and error class in
the trace.

## Approval boundaries

**Failure:** “Draft a message” becomes an external send.

**Pattern:** Split prepare and commit tools. Preparation returns a reviewable
artifact; commit requires explicit approval state that the model cannot invent.

**Test:** Score answer, prepared state, and absence of the send call
independently.

The measured candidate adds a preparation/authorization rule to
[`candidate-soul.md`](../profiles/candidate-soul.md). It leaves the tools and
execution budget unchanged. This tests model behavior; production enforcement
should bind consent to the exact draft in trusted code, outside the model's
control.

## Observability as harness behavior

Stable session/call IDs should connect agent actions, MCP calls, Relay ATOF, and
ATIF. Record the catalog, harness profile, requested and returned model IDs,
retry decisions, and approval state. Diagnose provider, gateway, transport,
tool, and model failures separately.

The measured profiles are
[`baseline-soul.md`](../profiles/baseline-soul.md) and
[`candidate-soul.md`](../profiles/candidate-soul.md).
The [walkthrough](walkthrough.md) shows every Hermes configuration change.
