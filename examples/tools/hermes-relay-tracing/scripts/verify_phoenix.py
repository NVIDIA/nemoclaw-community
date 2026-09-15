#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Wait for a Phoenix project to contain at least one trace."""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

QUERY = """{
  projects(first: 1000) {
    edges {
      node {
        name
        traceCount
        costSummary { total { cost tokens } }
      }
    }
  }
}"""


def project_trace_count(payload: dict[str, Any], project_name: str) -> int:
    try:
        edges = payload["data"]["projects"]["edges"]
    except (KeyError, TypeError) as error:
        raise ValueError("Phoenix returned an unexpected project response") from error
    if not isinstance(edges, list):
        raise ValueError("Phoenix returned an unexpected project list")
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if not isinstance(node, dict) or node.get("name") != project_name:
            continue
        count = node.get("traceCount", 0)
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise ValueError("Phoenix returned an invalid trace count")
        return count
    return 0


def project_cost_total(
    payload: dict[str, Any], project_name: str
) -> dict[str, Any] | None:
    try:
        edges = payload["data"]["projects"]["edges"]
    except (KeyError, TypeError) as error:
        raise ValueError("Phoenix returned an unexpected project response") from error
    if not isinstance(edges, list):
        raise ValueError("Phoenix returned an unexpected project list")
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        node = edge.get("node")
        if not isinstance(node, dict) or node.get("name") != project_name:
            continue
        summary = node.get("costSummary")
        total = summary.get("total") if isinstance(summary, dict) else None
        if total is None:
            return None
        if not isinstance(total, dict):
            raise ValueError("Phoenix returned an invalid cost summary")
        return total
    return None


def project_cost_summary(
    payload: dict[str, Any], project_name: str
) -> tuple[float, float] | None:
    total = project_cost_total(payload, project_name)
    if total is None:
        return None
    cost = total.get("cost")
    tokens = total.get("tokens")
    for name, value in (("cost", cost), ("tokens", tokens)):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or value < 0
        ):
            raise ValueError(f"Phoenix returned an invalid {name} total")
    return float(cost), float(tokens)


def project_token_total(payload: dict[str, Any], project_name: str) -> float | None:
    """Return the project's token total without requiring pricing metadata."""
    total = project_cost_total(payload, project_name)
    if total is None or total.get("tokens") is None:
        return None
    tokens = total["tokens"]
    if (
        isinstance(tokens, bool)
        or not isinstance(tokens, (int, float))
        or tokens < 0
    ):
        raise ValueError("Phoenix returned an invalid token total")
    return float(tokens)


def fetch_projects(graphql_url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        graphql_url,
        data=json.dumps({"query": QUERY}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Phoenix returned a non-object response")
    return payload


def trace_span_names(payload: dict[str, Any]) -> set[str]:
    traces = payload.get("data")
    if not isinstance(traces, list):
        raise ValueError("Phoenix returned an unexpected trace response")
    names: set[str] = set()
    for trace in traces:
        if not isinstance(trace, dict):
            raise ValueError("Phoenix returned an invalid trace")
        spans = trace.get("spans")
        if not isinstance(spans, list):
            raise ValueError("Phoenix returned an invalid span list")
        for span in spans:
            if not isinstance(span, dict):
                raise ValueError("Phoenix returned an invalid span")
            name = span.get("name")
            if isinstance(name, str) and name:
                names.add(name)
    return names


def fetch_traces(api_url: str, project_name: str) -> dict[str, Any]:
    project = urllib.parse.quote(project_name, safe="")
    url = f"{api_url.rstrip('/')}/v1/projects/{project}/traces?include_spans=true"
    with urllib.request.urlopen(url, timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise ValueError("Phoenix returned a non-object trace response")
    return payload


def wait_for_trace(
    graphql_url: str, project_name: str, *, timeout_seconds: float
) -> int:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            count = project_trace_count(fetch_projects(graphql_url), project_name)
            if count > 0:
                return count
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(1)
    detail = f": {last_error}" if last_error is not None else ""
    raise TimeoutError(f"Phoenix did not receive a trace for {project_name}{detail}")


def wait_for_positive_cost_summary(
    graphql_url: str, project_name: str, *, timeout_seconds: float
) -> tuple[float, float]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            summary = project_cost_summary(fetch_projects(graphql_url), project_name)
            if summary is not None and summary[0] > 0 and summary[1] > 0:
                return summary
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(1)
    detail = f": {last_error}" if last_error is not None else ""
    raise TimeoutError(
        f"Phoenix did not calculate positive token and cost totals for {project_name}"
        f"{detail}"
    )


def wait_for_positive_token_total(
    graphql_url: str, project_name: str, *, timeout_seconds: float
) -> float:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            tokens = project_token_total(fetch_projects(graphql_url), project_name)
            if tokens is not None and tokens > 0:
                return tokens
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(1)
    detail = f": {last_error}" if last_error is not None else ""
    raise TimeoutError(
        f"Phoenix did not calculate a positive token total for {project_name}{detail}"
    )


def wait_for_span_names(
    api_url: str,
    project_name: str,
    required_names: set[str],
    *,
    timeout_seconds: float,
) -> set[str]:
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    last_names: set[str] = set()
    while time.monotonic() < deadline:
        try:
            last_names = trace_span_names(fetch_traces(api_url, project_name))
            if required_names <= last_names:
                return last_names
        except (OSError, ValueError, urllib.error.URLError) as error:
            last_error = error
        time.sleep(1)
    missing = ", ".join(sorted(required_names - last_names))
    detail = f": {last_error}" if last_error is not None else ""
    raise TimeoutError(f"Phoenix trace is missing required spans: {missing}{detail}")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Wait for the tutorial project to appear in Phoenix."
    )
    parser.add_argument("--graphql-url", required=True)
    parser.add_argument("--api-url")
    parser.add_argument("--project-name", required=True)
    parser.add_argument("--require-span-name", action="append", default=[])
    parser.add_argument("--require-positive-token-total", action="store_true")
    parser.add_argument("--require-positive-cost-summary", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=30)
    args = parser.parse_args(argv)
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds must be greater than zero")
    if args.require_span_name and not args.api_url:
        parser.error("--api-url is required with --require-span-name")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(sys.argv[1:] if argv is None else argv)
    try:
        cost_summary: tuple[float, float] | None = None
        token_total: float | None = None
        trace_count = wait_for_trace(
            args.graphql_url,
            args.project_name,
            timeout_seconds=args.timeout_seconds,
        )
        if args.require_span_name:
            wait_for_span_names(
                args.api_url,
                args.project_name,
                set(args.require_span_name),
                timeout_seconds=args.timeout_seconds,
            )
        if args.require_positive_token_total:
            token_total = wait_for_positive_token_total(
                args.graphql_url,
                args.project_name,
                timeout_seconds=args.timeout_seconds,
            )
        if args.require_positive_cost_summary:
            cost_summary = wait_for_positive_cost_summary(
                args.graphql_url,
                args.project_name,
                timeout_seconds=args.timeout_seconds,
            )
    except (OSError, TimeoutError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    detail = ""
    if cost_summary is not None:
        cost, tokens = cost_summary
        detail = f", {tokens:g} priced tokens, ${cost:.6f}"
    elif token_total is not None:
        detail = f", {token_total:g} tokens"
    print(
        f"Phoenix project verified: {args.project_name} "
        f"({trace_count} trace{detail})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
