# Fixtures

`world-v2.json` is the canonical tutorial world: over 500 deterministic records
across people, mail, chat, calendar, knowledge, files, project tasks,
analytics, and support. It also fixes connector state, time, pagination
pressure, a large structured file, and one transient fault. Every MCP session
gets a fresh copy.

```bash
python3 scripts/generate_world_v2.py --check
PYTHONPATH=src:. python3 scripts/validate_world_v2.py
```

`generate_world_v2.py` deterministically expands the small `world-v1.json`
seed. Data Designer can instead propose additional fictional source records,
but generated rows should be reviewed, frozen as a new version, and paired with
new traces and evaluation contracts. It should not generate traces, judgments,
or evidence the tested agent never retrieved.
