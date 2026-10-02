# Trace artifacts

`world-v3/production/` is the starting corpus: 36–48 distinct baseline Hermes
requests recorded by NeMo Relay while the agent ran in OpenShell and called the
host-side HTTP MCP through `openshell/policy.yaml`. The ATIF files are the
trace-derived task evidence; `insights.jsonl` is the canonical Trace Analyst
input; `index.json` records stable IDs, source prompts, and behavior families.
It also binds the exact trace and analysis-input bytes with SHA-256 digests.
Public projections redact non-fixture tool payloads and declare normalization
losses. Recorded token usage is preserved when available; missing totals are
omitted rather than inferred as zero.
Public projections retain requests, tool observations and final answers, not
every intermediate assistant/LLM message. Use the walkthrough's model selector
for new runs; recorded identifiers are preserved as provenance.

`world-v3/baseline-development/insights.jsonl` contains every repeated baseline
development rollout joined to its Harbor reward and verifier findings. It is
the second Trace Analyst input and must contain exactly `D × K` traces with at
least three per development task.

`world-v3/verification-baseline-development/` holds the independent baseline
input joined to the measured reference comparison. It corroborates the frozen
candidate; it does not replace the original design traces above.

Validate a corpus and scored bundle with:

```bash
python3 scripts/validate_trace_corpus.py traces/world-v3/production/index.json
python3 scripts/validate_scored_trace_bundle.py \
  traces/world-v3/baseline-development/insights.jsonl --minimum-attempts 3
```

Fresh source collection and normalization commands are in the
[walkthrough](../docs/walkthrough.md). For your own agent, retain stable IDs,
user instructions, tool calls/results, recorded evaluation outcomes, and trace
provenance; record normalization losses rather than filling missing fields.
