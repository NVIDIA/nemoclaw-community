# Eval Author proof receipts

Each directory contains Eval Author's reviewed export metadata for its matching
Harbor task: the trace-derived candidate decision, reproducibility digest, and
declassified result. Every task passed two NOP, two Oracle, and one
unauthorized-send negative-control run under separate no-network verification.
Human task/Relevant experience review is pending, so environment status remains
`unproven` despite passing technical controls.

These receipts do not contain source traces, private ground truth, or job files.
The [walkthrough](../../docs/walkthrough.md) explains how Codex uses Eval Author
to retain the full authoring and proof evidence privately. To check the public
task trees against the receipts without claiming human approval:

```bash
python3 scripts/validate_task_products.py --allow-unreviewed
```

This is an integrity check, not a new Harbor execution. Image digests are pinned;
transitive dependency closure and fresh-container identity remain unverified.
