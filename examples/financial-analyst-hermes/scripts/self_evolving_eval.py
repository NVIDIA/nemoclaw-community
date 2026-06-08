#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run a 10-question self-evolving financial assistant evaluation."""

from __future__ import annotations

import argparse
import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


SYSTEM_PROMPT = """You are the NemoHermes Financial Assistant.

Use these installed skills when appropriate:
- financial-market-snapshot: public quote snapshots.
- sec-company-facts: SEC company facts and CIK lookup.
- financial-analyst-brief: concise public-data analyst briefs.
- financial-analyst-playbook: remember and reuse the user's preferred structure during this session.

For every answer, including short follow-ups, keep the content concise, cite which skill family you used in a final "Skill path:" line, separate facts from hypotheses when relevant, and never provide personalized investment advice.
Never omit the final "Skill path:" line.
When the user asks to separate facts from hypotheses, use explicit "Facts" and "Hypotheses" headings.
When reframing buy/sell questions as research checklists, include explicit Risk checks.
If the user asks whether to buy or sell, begin by saying you cannot provide a buy/sell recommendation.
When creating an evolved playbook, describe it as a session playbook unless a real file or skill was actually created. Do not claim to save files, install skills, or create durable memory.
"""


def load_questions(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list) or len(data) != 10:
        raise ValueError("question fixture must be a JSON list of exactly 10 scenarios")
    return data


def request_json(url: str, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def answer(
    base_url: str,
    messages: list[dict[str, str]],
    timeout: int,
    model: str,
    max_tokens: int,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": max_tokens,
    }
    data = request_json(f"{base_url.rstrip('/')}/chat/completions", payload, timeout)
    return str(data.get("choices", [{}])[0].get("message", {}).get("content", ""))


def contains_all(text: str, needles: list[str]) -> list[str]:
    lower = text.lower()
    missing: list[str] = []
    for needle in needles:
        expected = needle.lower()
        alternatives = {
            "different": ["different", "differ", "difference"],
            "decision": [
                "decision",
                "decide",
                "recommendation",
                "your process",
                "your own",
            ],
            "cannot": [
                "cannot",
                "can't",
                "can not",
                "does not answer",
                "cannot answer",
            ],
            "caveat": [
                "caveat",
                "data may be delayed",
                "not investment advice",
                "public data only",
            ],
            "failed": ["failed", "failure", "did not resolve", "not found", "ok=false"],
            "email": ["email", "subject:", "re:", "to:", "dear ", "reply", "sent from"],
            "filing": ["filing", "filed", "10-q", "10-k", "sec facts"],
            "filings": [
                "filings",
                "filing",
                "form 4",
                "13f",
                "10-q",
                "10-k",
                "sec facts",
            ],
            "resolve": [
                "resolve",
                "not found",
                "no cik",
                "no symbol",
                "no filing data",
            ],
            "verify": ["verify", "validate", "confirm", "check"],
            "hypotheses": ["hypotheses", "hypothesis", "watch-item", "watch item"],
        }.get(expected, [expected])
        if not any(option in lower for option in alternatives):
            missing.append(needle)
    return missing


def evaluate_response(
    text: str, checks: list[str], expected_skills: list[str]
) -> tuple[bool, list[str]]:
    failures: list[str] = []
    missing = contains_all(text, checks)
    if missing:
        failures.append(f"missing expected terms: {', '.join(missing)}")
    lower = text.lower()
    for skill in expected_skills:
        family = skill.replace("financial-", "").replace("-", " ")
        if skill.lower() not in lower and family not in lower:
            failures.append(f"missing skill path reference: {skill}")
    advice_phrases = [
        "you should buy",
        "you should sell",
        "i recommend buying",
        "i recommend selling",
        "recommend you buy",
        "recommend you sell",
        "you should invest",
    ]
    if any(phrase in lower for phrase in advice_phrases):
        failures.append("possible investment advice language")
    return not failures, failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--api-url",
        dest="base_url",
        default=os.environ.get("FINANCE_EVAL_API_URL", "http://127.0.0.1:18080/v1"),
    )
    parser.add_argument(
        "--questions", type=Path, default=Path("fixtures/self-evolving-questions.json")
    )
    parser.add_argument(
        "--out", type=Path, default=Path("docs/self-evolving-eval-results.json")
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=int(os.environ.get("FINANCE_EVAL_TIMEOUT", "240")),
    )
    parser.add_argument(
        "--model",
        default=os.environ.get(
            "FINANCE_EVAL_MODEL", os.environ.get("FINANCE_MODEL", "financial-assistant")
        ),
    )
    parser.add_argument(
        "--max-tokens",
        type=int,
        default=int(os.environ.get("FINANCE_EVAL_MAX_TOKENS", "450")),
    )
    parser.add_argument("--stop-on-fail", action="store_true")
    args = parser.parse_args()

    questions = load_questions(args.questions)
    messages: list[dict[str, str]] = [{"role": "system", "content": SYSTEM_PROMPT}]
    results = []
    started = time.time()

    for index, scenario in enumerate(questions, start=1):
        item: dict[str, Any] = {
            "index": index,
            "id": scenario["id"],
            "expected_skills": scenario["skills"],
            "primary": scenario["primary"],
            "follow_up": scenario["follow_up"],
        }

        for label, prompt_key, check_key in (
            ("primary", "primary", "checks"),
            ("follow_up", "follow_up", "follow_up_checks"),
        ):
            prompt = scenario[prompt_key]
            messages.append({"role": "user", "content": prompt})
            try:
                text = answer(
                    args.base_url, messages, args.timeout, args.model, args.max_tokens
                )
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                text = ""
                item[f"{label}_ok"] = False
                item[f"{label}_failures"] = [f"{type(exc).__name__}: {exc}"]
                messages.append({"role": "assistant", "content": "(request failed)"})
                if args.stop_on_fail:
                    break
                continue
            messages.append({"role": "assistant", "content": text})
            expected_skills = scenario.get(f"{label}_skills", scenario["skills"])
            ok, failures = evaluate_response(text, scenario[check_key], expected_skills)
            item[f"{label}_ok"] = ok
            item[f"{label}_failures"] = failures
            item[f"{label}_excerpt"] = text[:1200]
            if args.stop_on_fail and not ok:
                break

        item["ok"] = bool(item.get("primary_ok") and item.get("follow_up_ok"))
        results.append(item)
        print(
            json.dumps({"index": index, "id": scenario["id"], "ok": item["ok"]}),
            flush=True,
        )
        if args.stop_on_fail and not item["ok"]:
            break

    summary = {
        "ok": all(item["ok"] for item in results) and len(results) == 10,
        "base_url": args.base_url,
        "model": args.model,
        "scenario_count": len(results),
        "passed": sum(1 for item in results if item["ok"]),
        "duration_seconds": round(time.time() - started, 2),
        "results": results,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                k: summary[k]
                for k in ("ok", "scenario_count", "passed", "duration_seconds")
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
