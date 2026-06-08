#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Small read-only market-data helper for the NemoHermes finance example."""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable


YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
MAX_TICKERS = 20


@dataclass(frozen=True)
class Quote:
    symbol: str
    exchange_name: str | None
    currency: str | None
    timestamp: int | None
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    previous_close: float | None
    volume: int | None

    @property
    def change(self) -> float | None:
        if self.previous_close is None or self.close is None:
            return None
        return round(self.close - self.previous_close, 4)

    @property
    def change_percent(self) -> float | None:
        if self.previous_close in (None, 0) or self.close is None:
            return None
        return round(
            ((self.close - self.previous_close) / self.previous_close) * 100, 4
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "exchange_name": self.exchange_name,
            "currency": self.currency,
            "timestamp": self.timestamp,
            "timestamp_utc": unix_to_utc(self.timestamp),
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "previous_close": self.previous_close,
            "volume": self.volume,
            "change": self.change,
            "change_percent": self.change_percent,
        }


def normalize_symbol(symbol: str) -> str:
    cleaned = symbol.strip().upper().replace("/", "-")
    if not cleaned:
        raise ValueError("empty ticker")
    return cleaned


def latest_value(values: list[object] | None) -> object | None:
    if not values:
        return None
    for value in reversed(values):
        if value is not None:
            return value
    return None


def unix_to_utc(value: int | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()


def fetch_quote(symbol: str, timeout: int) -> Quote:
    normalized = normalize_symbol(symbol)
    url = f"{YAHOO_CHART_URL.format(symbol=normalized)}?range=5d&interval=1d"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 nemoclaw-community-financial-analyst-example/1.0",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.load(response)

    chart = payload.get("chart", {})
    if chart.get("error"):
        raise ValueError(f"{normalized}: {chart['error']}")
    result = (chart.get("result") or [None])[0]
    if not result:
        raise ValueError(f"{normalized}: no chart result")

    meta = result.get("meta", {})
    quote = (result.get("indicators", {}).get("quote") or [{}])[0]
    timestamps = result.get("timestamp") or []
    return Quote(
        symbol=str(meta.get("symbol") or normalized).upper(),
        exchange_name=meta.get("exchangeName"),
        currency=meta.get("currency"),
        timestamp=latest_value(timestamps),  # type: ignore[arg-type]
        open=latest_value(quote.get("open")),  # type: ignore[arg-type]
        high=latest_value(quote.get("high")),  # type: ignore[arg-type]
        low=latest_value(quote.get("low")),  # type: ignore[arg-type]
        close=meta.get("regularMarketPrice") or latest_value(quote.get("close")),
        previous_close=meta.get("chartPreviousClose") or meta.get("previousClose"),
        volume=latest_value(quote.get("volume")),  # type: ignore[arg-type]
    )


def fetch_quotes(symbols: Iterable[str], timeout: int) -> list[Quote]:
    normalized = [normalize_symbol(symbol) for symbol in symbols]
    if not normalized:
        raise ValueError("provide at least one ticker")
    if len(normalized) > MAX_TICKERS:
        raise ValueError(f"provide at most {MAX_TICKERS} tickers")
    return [fetch_quote(symbol, timeout=timeout) for symbol in normalized]


def load_watchlist(path: str) -> list[str]:
    symbols: list[str] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.split("#", 1)[0].strip()
            if stripped:
                symbols.extend(
                    part.strip() for part in stripped.split(",") if part.strip()
                )
    return symbols


def emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--timeout", type=int, default=20, help="request timeout in seconds"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    quote = subparsers.add_parser("quote", help="fetch public quote snapshots")
    quote.add_argument("symbols", nargs="+", help="tickers such as NVDA or MSFT")

    watchlist = subparsers.add_parser(
        "watchlist", help="fetch symbols from a text file"
    )
    watchlist.add_argument(
        "--file", required=True, help="newline or comma separated ticker file"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        symbols = args.symbols if args.command == "quote" else load_watchlist(args.file)
        quotes = fetch_quotes(symbols, timeout=args.timeout)
        emit(
            {
                "ok": True,
                "source": "yahoo-finance-chart-json",
                "source_url": "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}",
                "retrieved_at_unix": int(time.time()),
                "retrieved_at_utc": unix_to_utc(int(time.time())),
                "count": len(quotes),
                "quotes": [quote.as_dict() for quote in quotes],
                "caveat": "Public quote snapshot; may be delayed and is not investment advice.",
            }
        )
        return 0
    except Exception as exc:
        emit({"ok": False, "error": type(exc).__name__, "message": str(exc)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
