#!/usr/bin/env python3
"""
Prometheus Query Tool

Execute instant and range queries against Prometheus HTTP API.

Usage:
    python prom_query.py <prometheus_url> <query> [options]

Examples:
    # Instant query
    python prom_query.py http://localhost:9090 'up'

    # Range query
    python prom_query.py http://localhost:9090 'rate(http_requests_total[5m])' \
        --start '2024-01-01T00:00:00Z' --end '2024-01-01T01:00:00Z' --step '1m'

    # Output formats
    python prom_query.py http://localhost:9090 'up' --format json
    python prom_query.py http://localhost:9090 'up' --format csv
    python prom_query.py http://localhost:9090 'up' --format table
"""

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Any


def query_prometheus(
    base_url: str,
    query: str,
    time: str | None = None,
    start: str | None = None,
    end: str | None = None,
    step: str | None = None,
    timeout: str | None = None,
    limit: int | None = None,
) -> dict[str, Any]:
    """Execute a Prometheus query."""

    # Determine query type
    is_range = start is not None and end is not None
    endpoint = "/api/v1/query_range" if is_range else "/api/v1/query"

    # Build parameters
    params = {"query": query}

    if is_range:
        params["start"] = start
        params["end"] = end
        params["step"] = step or "1m"
    elif time:
        params["time"] = time

    if timeout:
        params["timeout"] = timeout
    if limit:
        params["limit"] = str(limit)

    # Build URL
    url = f"{base_url.rstrip('/')}{endpoint}?{urllib.parse.urlencode(params)}"

    # Execute request
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            data = json.loads(response.read().decode())
            return data
    except urllib.error.HTTPError as e:
        error_body = e.read().decode()
        try:
            error_data = json.loads(error_body)
            return error_data
        except json.JSONDecodeError:
            return {"status": "error", "error": error_body, "errorType": str(e.code)}
    except urllib.error.URLError as e:
        return {"status": "error", "error": str(e.reason), "errorType": "connection_error"}


def format_timestamp(ts: float) -> str:
    """Format Unix timestamp as ISO 8601."""
    return datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_metric(metric: dict[str, str]) -> str:
    """Format metric labels as string."""
    name = metric.get("__name__", "")
    labels = {k: v for k, v in metric.items() if k != "__name__"}

    if not labels:
        return name or "{}"

    label_str = ", ".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    return f"{name}{{{label_str}}}" if name else f"{{{label_str}}}"


def output_json(data: dict[str, Any]) -> None:
    """Output as JSON."""
    print(json.dumps(data, indent=2))


def output_table(data: dict[str, Any]) -> None:
    """Output as formatted table."""
    if data.get("status") != "success":
        print(f"Error: {data.get('error', 'Unknown error')}")
        return

    result_type = data.get("data", {}).get("resultType")
    results = data.get("data", {}).get("result", [])

    if not results:
        print("No results")
        return

    if result_type == "vector":
        # Instant vector
        print(f"{'METRIC':<60} {'TIMESTAMP':<25} {'VALUE':>15}")
        print("-" * 100)
        for item in results:
            metric = format_metric(item.get("metric", {}))
            ts, value = item.get("value", [0, ""])
            print(f"{metric:<60} {format_timestamp(ts):<25} {value:>15}")

    elif result_type == "matrix":
        # Range vector
        for item in results:
            metric = format_metric(item.get("metric", {}))
            print(f"\n{metric}")
            print(f"{'TIMESTAMP':<25} {'VALUE':>15}")
            print("-" * 40)
            for ts, value in item.get("values", []):
                print(f"{format_timestamp(ts):<25} {value:>15}")

    elif result_type == "scalar":
        ts, value = data.get("data", {}).get("result", [0, ""])
        print(f"Scalar: {value} at {format_timestamp(ts)}")

    elif result_type == "string":
        ts, value = data.get("data", {}).get("result", [0, ""])
        print(f"String: {value} at {format_timestamp(ts)}")

    # Print warnings if any
    warnings = data.get("warnings", [])
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  - {w}")


def output_csv(data: dict[str, Any]) -> None:
    """Output as CSV."""
    if data.get("status") != "success":
        print(f"error,{data.get('error', 'Unknown error')}")
        return

    result_type = data.get("data", {}).get("resultType")
    results = data.get("data", {}).get("result", [])

    if result_type == "vector":
        print("metric,timestamp,value")
        for item in results:
            metric = format_metric(item.get("metric", {})).replace(",", ";")
            ts, value = item.get("value", [0, ""])
            print(f'"{metric}",{format_timestamp(ts)},{value}')

    elif result_type == "matrix":
        print("metric,timestamp,value")
        for item in results:
            metric = format_metric(item.get("metric", {})).replace(",", ";")
            for ts, value in item.get("values", []):
                print(f'"{metric}",{format_timestamp(ts)},{value}')

    elif result_type in ("scalar", "string"):
        print("timestamp,value")
        ts, value = data.get("data", {}).get("result", [0, ""])
        print(f"{format_timestamp(ts)},{value}")


def main():
    parser = argparse.ArgumentParser(
        description="Query Prometheus HTTP API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Instant query:
    %(prog)s http://localhost:9090 'up'
    %(prog)s http://localhost:9090 'rate(http_requests_total[5m])' --time '2024-01-01T00:00:00Z'

  Range query:
    %(prog)s http://localhost:9090 'up' --start '2024-01-01T00:00:00Z' --end '2024-01-01T01:00:00Z' --step '1m'

  Output formats:
    %(prog)s http://localhost:9090 'up' --format table
    %(prog)s http://localhost:9090 'up' --format json
    %(prog)s http://localhost:9090 'up' --format csv
        """
    )

    parser.add_argument("url", help="Prometheus server URL (e.g., http://localhost:9090)")
    parser.add_argument("query", help="PromQL query expression")
    parser.add_argument("--time", "-t", help="Evaluation timestamp (RFC3339 or Unix)")
    parser.add_argument("--start", "-s", help="Range query start time")
    parser.add_argument("--end", "-e", help="Range query end time")
    parser.add_argument("--step", help="Range query step (default: 1m)")
    parser.add_argument("--timeout", help="Query timeout duration")
    parser.add_argument("--limit", type=int, help="Max series to return")
    parser.add_argument(
        "--format", "-f",
        choices=["json", "table", "csv"],
        default="table",
        help="Output format (default: table)"
    )

    args = parser.parse_args()

    # Validate range query args
    if (args.start is None) != (args.end is None):
        parser.error("--start and --end must be used together for range queries")

    # Execute query
    result = query_prometheus(
        base_url=args.url,
        query=args.query,
        time=args.time,
        start=args.start,
        end=args.end,
        step=args.step,
        timeout=args.timeout,
        limit=args.limit,
    )

    # Output result
    if args.format == "json":
        output_json(result)
    elif args.format == "csv":
        output_csv(result)
    else:
        output_table(result)

    # Exit with error code if query failed
    if result.get("status") != "success":
        sys.exit(1)


if __name__ == "__main__":
    main()
