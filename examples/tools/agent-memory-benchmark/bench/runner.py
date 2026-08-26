#!/usr/bin/env python3

# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Run one system under test end to end and produce its result.

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
import signal
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bench.fingerprint import fingerprint, hash_tree  # noqa: E402
from bench.grader import Verdict, grade, is_answered  # noqa: E402
from bench.pricing import SNAPSHOT_DATE, phase_cost_usd  # noqa: E402
from bench.proxy import AccountingProxy  # noqa: E402
from bench.report import render_markdown, summarize  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
# Where the accounting proxy forwards to. Override with --upstream or
# MNEMO_UPSTREAM; the default is the public OpenAI endpoint so a fresh clone
# works without knowing about anyone's internal gateway.
DEFAULT_UPSTREAM = os.environ.get("MNEMO_UPSTREAM", "https://api.openai.com")
# How long a killed adapter gets to exit on SIGTERM before SIGKILL.
GRACE_SECONDS = 10
# report.json layout version. Bump on any change that a reader parsing an older
# report would get wrong; add fields freely without bumping.
REPORT_SCHEMA_VERSION = 1


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
        part = part.format(**subs)
        # Adapters are invoked from a scratch directory rather than from the
        # benchmark root (see ``_assert_isolated``), so a committed relative
        # path like ``adapters/naive_rag/run.py`` would no longer resolve.
        # Bind it to the benchmark root here, while the root is still known.
        if not os.path.isabs(part) and (REPO / part).exists():
            part = str((REPO / part).resolve())
        rendered.append(part)
    return rendered


def _assert_isolated(command: list[str], env: dict, phase: str, forbidden: dict[str, Path]) -> None:
    """Fail before launching if a phase was handed something it must not see.

    The benchmark is only meaningful if a system answers from the memory it
    built, so ingest is never handed the questions and no phase is handed the
    answer key. This check keeps a future edit from quietly widening the
    placeholders.

    **It is not a sandbox, and it does not make the key unreachable.** The
    runner puts the benchmark root on ``PYTHONPATH`` so adapters can import
    ``adapters._lib``; an adapter can therefore import this module, read
    ``REPO``, and open the key directly. Running an adapter you did not write
    is running a program with your filesystem and your credentials, and this
    function does not change that. What it does is keep the runner from putting
    the key in an adapter's hands by accident.

    Making the key genuinely unreachable needs a filesystem boundary the
    harness does not have. See ``tests/test_isolation_is_not_a_sandbox.py``,
    which demonstrates the bypass so that nobody has to discover it in a
    result.
    """
    haystack = " ".join(command) + " " + " ".join(f"{k}={v}" for k, v in env.items())
    for label, path in forbidden.items():
        if str(path) in haystack:
            raise SystemExit(
                f"refusing to start {phase}: it was given the {label} ({path}). "
                "The ingest phase must not see the questions, and no phase may "
                "see the answer key."
            )


def _terminate_group(process: subprocess.Popen, label: str) -> None:
    """Kill the adapter and everything it spawned.

    An adapter is often a shell or an interpreter that starts workers of its
    own. Killing only the process we launched leaves those workers running,
    holding the accounting proxy open and continuing to spend tokens after the
    run has been declared over. The child is started in its own process group
    precisely so the whole tree can be signalled here.
    """
    if process.poll() is not None:
        return
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        else:  # Windows: the child was started as its own process group.
            process.send_signal(signal.CTRL_BREAK_EVENT)
    except (ProcessLookupError, PermissionError, OSError):
        process.terminate()
    try:
        process.wait(timeout=GRACE_SECONDS)
        return
    except subprocess.TimeoutExpired:
        print(f"[runner] {label} ignored SIGTERM; killing", file=sys.stderr, flush=True)
    try:
        if hasattr(os, "killpg"):
            os.killpg(os.getpgid(process.pid), signal.SIGKILL)
        else:
            process.kill()
    except (ProcessLookupError, PermissionError, OSError):
        process.kill()
    process.wait()


def _run(
    command: list[str],
    env: dict,
    cwd: Path,
    stdin: Path | None,
    stdout: Path | None,
    label: str,
    timeout: float | None = None,
) -> float:
    started = time.monotonic()
    fin = open(stdin, "rb") if stdin else subprocess.DEVNULL
    fout = open(stdout, "wb") if stdout else subprocess.DEVNULL
    # Its own process group, so a timeout or a Ctrl-C reaches the workers the
    # adapter started and not just the adapter.
    if hasattr(os, "setsid"):
        group = {"start_new_session": True}
    else:  # Windows
        group = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    process = subprocess.Popen(
        command, env=env, cwd=cwd, stdin=fin, stdout=fout, stderr=None, **group
    )
    try:
        returncode = process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        _terminate_group(process, label)
        raise SystemExit(
            f"{label} exceeded the {timeout:.0f}s budget and was killed. "
            "Raise --timeout-seconds, or pass 0 to wait indefinitely."
        ) from None
    except BaseException:
        # Ctrl-C, or anything else on the way out: do not leave the tree running.
        _terminate_group(process, label)
        raise
    finally:
        for handle in (fin, fout):
            if hasattr(handle, "close"):
                handle.close()
    elapsed = round(time.monotonic() - started, 2)
    if returncode != 0:
        raise SystemExit(f"{label} failed with exit code {returncode}")
    return elapsed


VALID_ACCOUNTING = ("proxy", "local")


def _accounting_method(declared: str, forwarded: int, uncounted: int) -> str:
    if declared == "local":
        # Declaring a local model and then calling through the proxy is a
        # mismatch in the other direction: the cost was partly observed, and
        # calling it unmeasured would understate it.
        return "declared-local-but-called" if forwarded else "local-unmeasured"
    if not forwarded:
        return "declared-proxy-but-silent"
    return "partial" if uncounted else "proxy"


def _accounting_description(declared: str, forwarded: int, uncounted: int) -> str:
    if declared == "local":
        if forwarded:
            return (f"the adapter declares a locally-hosted model but {forwarded} requests "
                    "crossed the proxy, so its declaration does not describe what it did")
        return ("the adapter declares a locally-hosted model, so no cost was measured "
                "and this run is not comparable on the cost axis")
    if not forwarded:
        return ("the adapter declares proxy accounting but nothing crossed the proxy, "
                "so no cost was observed and this run is invalid")
    if uncounted:
        return (f"{uncounted} of {forwarded} forwarded requests returned no countable "
                "usage, so the cost below is a floor and this run is not comparable "
                "on the cost axis")
    return "counted at a local proxy the runner put in front of the model endpoint"


def _git_revision(path: Path) -> dict:
    """The commit a directory sits at, and whether it was edited since.

    Recorded for the benchmark itself as well as for the adapter: an adapter
    can live inside this repository, and then "which adapter produced this
    row" and "which benchmark scored it" are two different questions.
    """
    revision: dict = {}
    try:
        for key, argv in (
            ("commit", ["rev-parse", "HEAD"]),
            ("dirty", ["status", "--porcelain"]),
        ):
            completed = subprocess.run(
                ["git", "-C", str(path), *argv],
                capture_output=True, text=True, timeout=10, check=False,
            )
            if completed.returncode != 0:
                return revision
            revision[key] = (bool(completed.stdout.strip()) if key == "dirty"
                             else completed.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass  # git is optional
    return revision


def _adapter_revision(adapter_dir: Path) -> dict:
    """Identify the adapter that produced a row.

    The commit is the useful answer when there is one, but an adapter may be
    an untracked directory or live outside a repository, so the hash of its
    own files is always recorded and never depends on git being present.
    """
    revision: dict = {"files_sha256": hash_tree(adapter_dir)}
    try:
        completed = subprocess.run(
            ["git", "-C", str(adapter_dir), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if completed.returncode == 0:
            revision["git_commit"] = completed.stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(adapter_dir), "status", "--porcelain", "--", str(adapter_dir)],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if dirty.returncode == 0:
            revision["git_dirty"] = bool(dirty.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        pass  # git is optional; the file hash already identifies the adapter
    return revision


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
    parser.add_argument("--trial-index", type=int, default=1, help="which trial this run is (1-based)")
    parser.add_argument("--trial-count", type=int, default=1, help="how many trials the submission runs")
    parser.add_argument("--skip-ingest", action="store_true", help="reuse an existing --state and only answer")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=float(os.environ.get("MNEMO_TIMEOUT_SECONDS", 6 * 3600)),
        help="per-phase wall-clock budget; 0 waits indefinitely (default: 6h)",
    )
    args = parser.parse_args()

    # Absolute paths, always. A relative --state reaches the adapter as-is, and
    # a system that re-spawns itself with a different working directory then
    # resolves it against the wrong root: its files vanish, the turn produces
    # nothing, and the failure looks like a bad model rather than a bad path.
    args.adapter = args.adapter.resolve()
    args.corpus = args.corpus.resolve()
    args.questions = args.questions.resolve()
    args.gold = args.gold.resolve()
    if args.out is not None:
        args.out = args.out.resolve()
    if args.state is not None:
        args.state = args.state.resolve()

    spec = json.loads((args.adapter / "adapter.json").read_text(encoding="utf-8"))
    if spec.get("accounting", "proxy") not in VALID_ACCOUNTING:
        raise SystemExit(
            f'adapter.json declares accounting={spec["accounting"]!r}; '
            f"expected one of {VALID_ACCOUNTING}"
        )
    if args.trial_index < 1 or args.trial_index > args.trial_count:
        raise SystemExit(f"--trial-index {args.trial_index} is outside 1..{args.trial_count}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = (args.out or REPO / "results" / "runs" / f"{stamp}-{spec['name']}").resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    state_dir = (args.state or run_dir / "state").resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    answers_path = run_dir / "answers.jsonl"
    # Adapters run from here, not from the benchmark root: a relative open() of
    # "gold/answers.jsonl" must not find the answer key.
    work_dir = run_dir / "work"
    work_dir.mkdir(parents=True, exist_ok=True)

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

        timeout = args.timeout_seconds or None
        if not args.skip_ingest:
            proxy.set_phase("ingest")
            ingest_seconds = 0.0
            for part in ("part_a", "part_b"):
                command = _render(spec["ingest"], env, corpus=str(args.corpus / part), state=str(state_dir), part=part)
                _assert_isolated(
                    command, env, f"ingest {part}",
                    {"answer key": args.gold, "question set": args.questions},
                )
                print(f"[runner] ingest {part}: {' '.join(command)}", flush=True)
                ingest_seconds += _run(command, env, work_dir, None, None, f"ingest {part}", timeout)
            timing["ingest_seconds"] = round(ingest_seconds, 2)

        proxy.set_phase("answer")
        command = _render(spec["answer"], env, state=str(state_dir), questions=str(args.questions))
        _assert_isolated(command, env, "answer", {"answer key": args.gold})
        print(f"[runner] answer: {' '.join(command)}", flush=True)
        timing["answer_seconds"] = _run(
            command, env, work_dir, args.questions, answers_path, "answer", timeout
        )
        usage = proxy.usage.snapshot()

    answers = _read_answers(answers_path)
    verdicts: list[Verdict] = []
    for question in questions:
        row = answers.get(question["id"])
        verdicts.append(
            grade(question["id"], str((row or {}).get("answer", "")), (row or {}).get("source_ids"),
                  gold_by_id[question["id"]], answered=is_answered(row))
        )

    manifest = [json.loads(line) for line in (args.corpus / "manifest.jsonl").read_text().splitlines() if line.strip()]
    # The declared model is the one the result is filed under; a run may also
    # call auxiliary models (embeddings, rerankers) and those are priced too but
    # never rename the row.
    model = spec.get("model") or (max(usage["models"], key=usage["models"].get) if usage.get("models") else None)
    declared_accounting = spec.get("accounting", "proxy")
    forwarded = sum(usage.get("forwarded", {}).values())
    uncounted = sum(usage.get("uncounted", {}).values())
    ingest_in = usage["input_tokens"].get("ingest", 0)
    ingest_out = usage["output_tokens"].get("ingest", 0)
    answer_in = usage["input_tokens"].get("answer", 0)
    answer_out = usage["output_tokens"].get("answer", 0)
    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "adapter": {
            "name": spec["name"],
            # What was actually executed, so a row can be traced to the
            # definition that produced it even after the adapter changes.
            "revision": _adapter_revision(args.adapter),
            "declared_model": spec.get("model"),
            "declared_env": sorted(spec.get("env", {})),
            # Carried into the report so it can be printed beside the number,
            # not only in the adapter's own directory.
            "caveat": spec.get("caveat"),
        },
        # Kept at the top level as well: every existing reader looks here.
        "model": model,
        "observed_models": usage.get("models", {}),
        "run_id": run_dir.name,
        "timestamp": stamp,
        # Which benchmark scored the row, distinct from which adapter produced
        # it: an adapter shipped here moves with the tool.
        "benchmark_revision": _git_revision(REPO),
        "trial": {"index": args.trial_index, "of": args.trial_count},
        # The identity of the scoring configuration. Two rows are comparable
        # only if all three hashes match; see docs/provenance.md.
        "fingerprint": fingerprint(args.corpus, args.questions, args.gold),
        "corpus": {
            "documents": len(manifest),
            "part_a": sum(1 for m in manifest if m["part"] == "part_a"),
            "part_b": sum(1 for m in manifest if m["part"] == "part_b"),
        },
        "timing": timing,
        "accounting": {
            # What the adapter said it would do, so silence can be read. A
            # proxy-measured adapter that produced no traffic bypassed the
            # proxy; a local one is expected to.
            "declared": declared_accounting,
            "method": _accounting_method(declared_accounting, forwarded, uncounted),
            # Requests the proxy forwarded, and those whose response carried no
            # usage. Any number in the second means the cost is a floor.
            "forwarded_calls": forwarded,
            "uncounted_calls": uncounted,
            "description": _accounting_description(declared_accounting, forwarded, uncounted),
            "proxy_observed_calls": sum(usage.get("calls", {}).values()),
            # A run whose cost was not measured must never be ranked on cost,
            # whether it was honest about that or not.
            "comparable_on_cost": declared_accounting == "proxy" and forwarded > 0 and uncounted == 0,
        },
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
        "answers_missing": [q["id"] for q in questions if not is_answered(answers.get(q["id"]))],
    }
    # A system that answered nothing is a broken run, not a system that scored
    # zero. Say so in the report and mark the run invalid.
    if declared_accounting == "local" and forwarded:
        report["valid"] = False
        report["invalid_reason"] = (
            f'the adapter declares "accounting": "local" but {forwarded} requests crossed '
            "the proxy. Declare proxy accounting, or stop routing through it."
        )
        print(f"[runner] WARNING: {report['invalid_reason']}", file=sys.stderr)
    if declared_accounting == "proxy" and not forwarded:
        report["valid"] = False
        report["invalid_reason"] = (
            "the adapter declares proxy accounting but no request crossed the proxy, "
            "so its cost was never observed. Either it bypassed OPENAI_BASE_URL / "
            'ANTHROPIC_BASE_URL, or it runs a local model and should declare '
            '"accounting": "local" in its adapter.json.'
        )
        print(f"[runner] WARNING: {report['invalid_reason']}", file=sys.stderr)
    if uncounted:
        report["valid"] = False
        report["invalid_reason"] = (
            f"{uncounted} of {forwarded} forwarded requests returned no countable usage. "
            "The score may be sound but its cost is not, and the two are reported "
            "together; re-run against an endpoint that returns usage."
        )
        print(f"[runner] WARNING: {report['invalid_reason']}", file=sys.stderr)
    if report["answers_missing"]:
        report["valid"] = False
        report["invalid_reason"] = (
            f"{len(report['answers_missing'])} of {len(questions)} questions received no "
            "answer. An incomplete submission is not a lower score: a question a system "
            "declined to answer at all is not the same as one it answered by declining."
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
