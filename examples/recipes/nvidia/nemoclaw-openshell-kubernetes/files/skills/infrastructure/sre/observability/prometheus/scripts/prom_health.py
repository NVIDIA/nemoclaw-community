#!/usr/bin/env python3
"""
Prometheus Health Check Tool

Check Prometheus server health, targets status, and basic statistics.

Usage:
    python prom_health.py <prometheus_url> [options]

Examples:
    python prom_health.py http://localhost:9090
    python prom_health.py http://localhost:9090 --targets
    python prom_health.py http://localhost:9090 --rules
    python prom_health.py http://localhost:9090 --all
"""

import argparse
import json
import sys
import urllib.request
from typing import Any


def fetch_endpoint(base_url: str, endpoint: str) -> dict[str, Any]:
    """Fetch data from Prometheus endpoint."""
    url = f"{base_url.rstrip('/')}{endpoint}"
    try:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        return {"status": "error", "error": f"HTTP {e.code}", "errorType": "http_error"}
    except urllib.error.URLError as e:
        return {"status": "error", "error": str(e.reason), "errorType": "connection_error"}
    except Exception as e:
        return {"status": "error", "error": str(e), "errorType": "unknown"}


def check_ready(base_url: str) -> bool:
    """Check if Prometheus is ready."""
    url = f"{base_url.rstrip('/')}/-/ready"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def check_healthy(base_url: str) -> bool:
    """Check if Prometheus is healthy."""
    url = f"{base_url.rstrip('/')}/-/healthy"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status == 200
    except Exception:
        return False


def print_section(title: str) -> None:
    """Print section header."""
    print(f"\n{'='*60}")
    print(f" {title}")
    print(f"{'='*60}")


def print_status(label: str, status: bool, details: str = "") -> None:
    """Print status line with icon."""
    icon = "✓" if status else "✗"
    status_text = "OK" if status else "FAIL"
    detail_str = f" ({details})" if details else ""
    print(f"  [{icon}] {label}: {status_text}{detail_str}")


def check_build_info(base_url: str) -> dict[str, Any] | None:
    """Get build info."""
    result = fetch_endpoint(base_url, "/api/v1/status/buildinfo")
    if result.get("status") == "success":
        return result.get("data", {})
    return None


def check_runtime_info(base_url: str) -> dict[str, Any] | None:
    """Get runtime info."""
    result = fetch_endpoint(base_url, "/api/v1/status/runtimeinfo")
    if result.get("status") == "success":
        return result.get("data", {})
    return None


def check_targets(base_url: str) -> None:
    """Check and display target status."""
    result = fetch_endpoint(base_url, "/api/v1/targets")

    if result.get("status") != "success":
        print(f"  Error fetching targets: {result.get('error', 'Unknown')}")
        return

    data = result.get("data", {})
    active = data.get("activeTargets", [])
    dropped = data.get("droppedTargets", [])

    # Count by health status
    health_counts = {"up": 0, "down": 0, "unknown": 0}
    for target in active:
        health = target.get("health", "unknown")
        health_counts[health] = health_counts.get(health, 0) + 1

    print(f"  Active targets: {len(active)}")
    print(f"    - Up: {health_counts.get('up', 0)}")
    print(f"    - Down: {health_counts.get('down', 0)}")
    print(f"    - Unknown: {health_counts.get('unknown', 0)}")
    print(f"  Dropped targets: {len(dropped)}")

    # List down targets
    down_targets = [t for t in active if t.get("health") == "down"]
    if down_targets:
        print("\n  Down targets:")
        for target in down_targets[:10]:  # Limit to 10
            labels = target.get("labels", {})
            job = labels.get("job", "unknown")
            instance = labels.get("instance", "unknown")
            error = target.get("lastError", "No error info")
            print(f"    - {job}/{instance}: {error[:60]}")
        if len(down_targets) > 10:
            print(f"    ... and {len(down_targets) - 10} more")


def check_rules(base_url: str) -> None:
    """Check and display rules status."""
    result = fetch_endpoint(base_url, "/api/v1/rules")

    if result.get("status") != "success":
        print(f"  Error fetching rules: {result.get('error', 'Unknown')}")
        return

    groups = result.get("data", {}).get("groups", [])

    total_rules = 0
    alerting_rules = 0
    recording_rules = 0
    firing_alerts = 0
    unhealthy_rules = 0

    for group in groups:
        for rule in group.get("rules", []):
            total_rules += 1
            rule_type = rule.get("type")

            if rule_type == "alerting":
                alerting_rules += 1
                alerts = rule.get("alerts", [])
                firing = [a for a in alerts if a.get("state") == "firing"]
                firing_alerts += len(firing)
            elif rule_type == "recording":
                recording_rules += 1

            if rule.get("health") != "ok":
                unhealthy_rules += 1

    print(f"  Rule groups: {len(groups)}")
    print(f"  Total rules: {total_rules}")
    print(f"    - Alerting: {alerting_rules}")
    print(f"    - Recording: {recording_rules}")
    print(f"  Firing alerts: {firing_alerts}")
    print(f"  Unhealthy rules: {unhealthy_rules}")


def check_tsdb(base_url: str) -> None:
    """Check TSDB statistics."""
    result = fetch_endpoint(base_url, "/api/v1/status/tsdb")

    if result.get("status") != "success":
        print(f"  Error fetching TSDB stats: {result.get('error', 'Unknown')}")
        return

    data = result.get("data", {})
    head_stats = data.get("headStats", {})

    print(f"  Series count: {head_stats.get('numSeries', 'N/A')}")
    print(f"  Chunk count: {head_stats.get('chunkCount', 'N/A')}")

    # Top metrics by series count
    series_by_metric = data.get("seriesCountByMetricName", [])
    if series_by_metric:
        print("\n  Top 5 metrics by series count:")
        for item in series_by_metric[:5]:
            print(f"    - {item.get('name', 'unknown')}: {item.get('value', 0)}")


def check_alerts(base_url: str) -> None:
    """Check active alerts."""
    result = fetch_endpoint(base_url, "/api/v1/alerts")

    if result.get("status") != "success":
        print(f"  Error fetching alerts: {result.get('error', 'Unknown')}")
        return

    alerts = result.get("data", {}).get("alerts", [])

    # Group by state
    by_state = {}
    for alert in alerts:
        state = alert.get("state", "unknown")
        by_state[state] = by_state.get(state, 0) + 1

    print(f"  Total active alerts: {len(alerts)}")
    for state, count in sorted(by_state.items()):
        print(f"    - {state}: {count}")

    # List firing alerts
    firing = [a for a in alerts if a.get("state") == "firing"]
    if firing:
        print("\n  Firing alerts:")
        for alert in firing[:10]:
            name = alert.get("labels", {}).get("alertname", "unknown")
            severity = alert.get("labels", {}).get("severity", "unknown")
            print(f"    - {name} (severity: {severity})")
        if len(firing) > 10:
            print(f"    ... and {len(firing) - 10} more")


def main():
    parser = argparse.ArgumentParser(
        description="Check Prometheus server health and status",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("url", help="Prometheus server URL")
    parser.add_argument("--targets", "-t", action="store_true", help="Show detailed target info")
    parser.add_argument("--rules", "-r", action="store_true", help="Show detailed rules info")
    parser.add_argument("--tsdb", "-d", action="store_true", help="Show TSDB statistics")
    parser.add_argument("--alerts", "-a", action="store_true", help="Show active alerts")
    parser.add_argument("--all", action="store_true", help="Show all information")

    args = parser.parse_args()

    if args.all:
        args.targets = args.rules = args.tsdb = args.alerts = True

    base_url = args.url.rstrip("/")

    # Basic health checks
    print_section("Health Checks")

    ready = check_ready(base_url)
    healthy = check_healthy(base_url)

    print_status("Ready", ready)
    print_status("Healthy", healthy)

    if not (ready and healthy):
        print("\n  ⚠ Prometheus is not fully operational")
        sys.exit(1)

    # Build info
    build_info = check_build_info(base_url)
    if build_info:
        print_section("Build Information")
        print(f"  Version: {build_info.get('version', 'N/A')}")
        print(f"  Revision: {build_info.get('revision', 'N/A')[:12]}")
        print(f"  Go version: {build_info.get('goVersion', 'N/A')}")

    # Runtime info
    runtime_info = check_runtime_info(base_url)
    if runtime_info:
        print_section("Runtime Information")
        print(f"  Start time: {runtime_info.get('startTime', 'N/A')}")
        print(f"  Time series: {runtime_info.get('timeSeriesCount', 'N/A')}")
        print(f"  Goroutines: {runtime_info.get('goroutineCount', 'N/A')}")
        print(f"  Storage retention: {runtime_info.get('storageRetention', 'N/A')}")

        reload_success = runtime_info.get("reloadConfigSuccess")
        if reload_success is not None:
            print_status("Config reload", reload_success)

    # Optional detailed sections
    if args.targets:
        print_section("Targets")
        check_targets(base_url)

    if args.rules:
        print_section("Rules")
        check_rules(base_url)

    if args.alerts:
        print_section("Alerts")
        check_alerts(base_url)

    if args.tsdb:
        print_section("TSDB Statistics")
        check_tsdb(base_url)

    print()


if __name__ == "__main__":
    main()
