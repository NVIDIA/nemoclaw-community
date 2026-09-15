# Example ATOF and ATIF Files

These files are minimal trace examples for the terminal task in this
repository. They show the two Relay formats produced by the tutorial without
duplicating every event from a live run, so you can inspect the event and
trajectory shapes before calling a model.

The examples include the task, requested command, and verified result. They
use stable example identifiers instead of values from one machine's execution.
Run the tutorial to create the complete trace files for your own execution.

| File | Use it to inspect |
| --- | --- |
| [ATOF JSONL](terminal-task.atof.jsonl) | The ordered LLM and terminal-tool lifecycle events. |
| [ATIF JSON](terminal-task.atif.json) | The step-oriented trajectory projected from related events. |

The ATOF example records an LLM request, streaming and final response token
usage, its tool-call response, and the start and successful completion of the
`terminal` tool. The ATIF
example groups the same work into a user step and an agent step that requests
the terminal tool.

Run the repository's summaries against the examples:

```bash
python3 scripts/summarize_atof.py \
  examples/terminal-task.atof.jsonl \
  --require-token-usage
python3 scripts/summarize_atif.py examples/terminal-task.atif.json
```

The formats answer different questions. ATOF preserves lifecycle order for
diagnosis. ATIF presents the agent's work as trajectory steps for analysis and
evaluation. A requested tool call in ATIF is not necessarily an executed tool
call, so use ATOF when you need to verify execution.
