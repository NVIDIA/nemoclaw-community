#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run one system under test end to end and produce its leaderboard row.

    python3 -m bench.runner --adapter adapters/naive_rag

The runner owns everything the submission must not: which documents are shown
and in what order, when the clock starts, and how tokens are counted. The
adapter only gets two commands — ``ingest`` (twice: part_a then part_b) and
``answer`` — described by its ``adapter.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.grader import Verdict, grade  # noqa: E402
from bench.pricing import SNAPSHOT_DATE, phase_cost_usd  # noqa: E402
from bench.proxy import AccountingProxy  # noqa: E402
from bench.report import render_markdown, summarize  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# Where the accounting proxy forwards to. Override with --upstream or
# MNEMO_UPSTREAM; the default is the public OpenAI endpoint so a fresh clone
# works without knowing about anyone's internal gateway.
DEFAULT_UPSTREAM = os.environ.get("MNEMO_UPSTREAM", "https://api.openai.com")


def _render(command: list[str], env: dict[str, str], **subs: str) -> list[str]:
    """Fill ``{corpus}``/``{state}`` placeholders and expand ``${VAR}`` from env.

    Adapters that shell out to another project need a path that differs per
    machine (an interpreter, a checkout). Those belong in the adapter's env
    block, not hard-coded into a committed command line.
    """
    rendered = []
    for part in command:
        # ``${VAR}`` first: it contains braces, which str.format would try to
        # read as a field name.
        for name, value in env.items():
            part = part.replace(f"${{{name}}}", value)
        part = os.path.expandvars(os.path.expanduser(part))
        rendered.append(part.format(**subs))
    return rendered


def _run(command: list[str], env: dict, cwd: Path, stdin: Path | None, stdout: Path | None, label: str) -> float:
    started = time.monotonic()
    fin = open(stdin, "rb") if stdin else subprocess.DEVNULL
    fout = open(stdout, "wb") if stdout else subprocess.DEVNULL
    try:
        completed = subprocess.run(command, env=env, cwd=cwd, stdin=fin, stdout=fout, stderr=None)
    finally:
        for handle in (fin, fout):
            if hasattr(handle, "close"):
                handle.close()
    elapsed = round(time.monotonic() - started, 2)
    if completed.returncode != 0:
        raise SystemExit(f"{label} failed with exit code {completed.returncode}")
    return elapsed


def _self_reported(state_dir: Path) -> dict | None:
    """Adapter-recorded token usage, if the adapter wrote any."""
    path = state_dir / "usage_selfreport.json"
    if not path.exists():
        return None
    try:
        snapshots = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(snapshots, dict) or not snapshots:
        return None
    latest_key = sorted(snapshots)[-1]
    return {"latest": snapshots[latest_key], "snapshots": len(snapshots)}


def _read_answers(path: Path) -> dict[str, dict]:
    answers: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("id"):
            answers[str(row["id"])] = row
    return answers


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", required=True, type=Path)
    parser.add_argument("--questions", type=Path, default=REPO / "questions" / "questions.jsonl")
    parser.add_argument("--gold", type=Path, default=REPO / "gold" / "answers.jsonl")
    parser.add_argument("--corpus", type=Path, default=REPO / "corpus")
    parser.add_argument("--out", type=Path, default=None, help="run directory (default: results/runs/<ts>-<adapter>)")
    parser.add_argument("--state", type=Path, default=None, help="memory dir for the system under test")
    parser.add_argument("--upstream", default=DEFAULT_UPSTREAM)
    parser.add_argument("--skip-ingest", action="store_true", help="reuse an existing --state and only answer")
    args = parser.parse_args()

    # Absolute paths, always. A relative --state reaches the adapter as-is, and
    # a system that re-spawns itself with a different working directory (Pi
    # does) then resolves it against the wrong root: its files vanish, the turn
    # produces nothing, and the failure looks like a bad model rather than a bad
    # path.
    args.adapter = args.adapter.resolve()
    args.corpus = args.corpus.resolve()
    args.questions = args.questions.resolve()
    args.gold = args.gold.resolve()
    if args.out is not None:
        args.out = args.out.resolve()
    if args.state is not None:
        args.state = args.state.resolve()

    spec = json.loads((args.adapter / "adapter.json").read_text(encoding="utf-8"))
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = (args.out or REPO / "results" / "runs" / f"{stamp}-{spec['name']}").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    state_dir = (args.state or run_dir / "state").resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    answers_path = run_dir / "answers.jsonl"

    gold_by_id = {}
    for line in args.gold.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            gold_by_id[row["id"]] = row
    questions = [json.loads(line) for line in args.questions.read_text(encoding="utf-8").splitlines() if line.strip()]

    timing: dict[str, float] = {}
    os.environ.setdefault("MNEMO_PROXY_LOG", str(run_dir / "proxy_errors.log"))
    with AccountingProxy(args.upstream) as proxy:
        env = os.environ.copy()
        # The adapter's env block supplies defaults; anything already exported
        # wins, so a machine-specific path (an interpreter, a checkout) can be
        # set per host without editing a committed file.
        for key, value in spec.get("env", {}).items():
            env.setdefault(key, value)
        env["OPENAI_BASE_URL"] = f"{proxy.base_url}/v1"
        env["ANTHROPIC_BASE_URL"] = proxy.base_url
        env["MNEMO_MODEL"] = spec.get("model", "")
        env["PYTHONPATH"] = str(REPO) + os.pathsep + env.get("PYTHONPATH", "")

        if not args.skip_ingest:
            proxy.set_phase("ingest")
            ingest_seconds = 0.0
            for part in ("part_a", "part_b"):
                command = _render(spec["ingest"], env, corpus=str(args.corpus / part), state=str(state_dir), part=part)
                print(f"[runner] ingest {part}: {' '.join(command)}", flush=True)
                ingest_seconds += _run(command, env, REPO, None, None, f"ingest {part}")
            timing["ingest_seconds"] = round(ingest_seconds, 2)

        proxy.set_phase("answer")
        command = _render(spec["answer"], env, state=str(state_dir), questions=str(args.questions))
        print(f"[runner] answer: {' '.join(command)}", flush=True)
        timing["answer_seconds"] = _run(command, env, REPO, args.questions, answers_path, "answer")
        usage = proxy.usage.snapshot()

    answers = _read_answers(answers_path)
    verdicts: list[Verdict] = []
    for question in questions:
        row = answers.get(question["id"], {})
        verdicts.append(
            grade(question["id"], str(row.get("answer", "")), row.get("source_ids"), gold_by_id[question["id"]])
        )

    manifest = [json.loads(line) for line in (args.corpus / "manifest.jsonl").read_text().splitlines() if line.strip()]
    # The declared model is the one the leaderboard groups by; a run may also
    # call auxiliary models (embeddings, rerankers) and those are priced too but
    # never rename the row.
    model = spec.get("model") or (max(usage["models"], key=usage["models"].get) if usage.get("models") else None)
    ingest_in = usage["input_tokens"].get("ingest", 0)
    ingest_out = usage["output_tokens"].get("ingest", 0)
    answer_in = usage["input_tokens"].get("answer", 0)
    answer_out = usage["output_tokens"].get("answer", 0)
    report = {
        "adapter": spec["name"],
        "model": model,
        "observed_models": usage.get("models", {}),
        "run_id": run_dir.name,
        "timestamp": stamp,
        "corpus": {
            "documents": len(manifest),
            "part_a": sum(1 for m in manifest if m["part"] == "part_a"),
            "part_b": sum(1 for m in manifest if m["part"] == "part_b"),
        },
        "timing": timing,
        "accounting": "proxy" if (ingest_in or answer_in) else "none observed (local inference?)",
        "cost": {
            "ingest_input_tokens": ingest_in,
            "ingest_output_tokens": ingest_out,
            "answer_input_tokens": answer_in,
            "answer_output_tokens": answer_out,
            "answer_calls": usage["calls"].get("answer", 0),
            "tokens_per_question": round((answer_in + answer_out) / len(questions), 1) if questions else None,
            "ingest_usd": phase_cost_usd(usage.get("by_phase_model", {}).get("ingest", {})),
            "answer_usd": phase_cost_usd(usage.get("by_phase_model", {}).get("answer", {})),
            "price_snapshot": SNAPSHOT_DATE,
        },
        "usage_raw": usage,
        # An adapter may also record what its own runtime believes it spent.
        # That number matters when a run is resumed: the proxy only counts the
        # segment it supervised, while the system's own counter spans every
        # segment. Reported side by side, never merged.
        "self_reported_usage": _self_reported(state_dir),
        "summary": summarize(verdicts, gold_by_id),
        "answers_missing": [q["id"] for q in questions if q["id"] not in answers],
    }
    # A system that answered nothing is a broken run, not a system that scored
    # zero. Say so in the report and keep it off the leaderboard.
    if not answers or len(report["answers_missing"]) > len(questions) // 2:
        report["valid"] = False
        report["invalid_reason"] = (
            f"only {len(answers)} of {len(questions)} questions were answered — "
            "the adapter did not run to completion"
        )
        print(f"[runner] WARNING: {report['invalid_reason']}", file=sys.stderr)
    (run_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    (run_dir / "verdicts.jsonl").write_text(
        "\n".join(json.dumps(v.to_dict()) for v in verdicts) + "\n", encoding="utf-8"
    )
    (run_dir / "summary.md").write_text(render_markdown(report), encoding="utf-8")
    print(render_markdown(report))
    print(f"[runner] wrote {run_dir}")


if __name__ == "__main__":
    main()
