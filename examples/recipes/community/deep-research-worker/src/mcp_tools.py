#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
MCP tool loader for deepagents-worker.
"""
import asyncio
import json
import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("deepagents-mcp-tools")

PER_SERVER_TIMEOUT_SECONDS = 30
RECONNECT_INTERVAL_SECONDS = 300


def parse_mcp_config(raw: str) -> Dict[str, Dict[str, Any]]:
    if not raw or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as err:
        logger.error("Invalid DEEPAGENTS_MCP_SERVERS JSON: %s; ignoring", err)
        return {}
    if not isinstance(parsed, dict):
        logger.error("DEEPAGENTS_MCP_SERVERS must be a JSON object; ignoring")
        return {}
    normalized: Dict[str, Dict[str, Any]] = {}
    for name, entry in parsed.items():
        if not isinstance(entry, dict) or "url" not in entry:
            logger.warning("Skipping MCP server '%s': missing 'url'", name)
            continue
        transport = str(entry.get("transport", "streamable_http")).replace("streamable-http", "streamable_http")
        normalized[name] = {"transport": transport, "url": entry["url"]}
        if "headers" in entry:
            normalized[name]["headers"] = entry["headers"]
    return normalized


async def _fetch_single_server_tools_async(name: str, server_conf: Dict[str, Any]) -> List[Any]:
    try:
        from langchain_mcp_adapters.client import MultiServerMCPClient
    except ImportError as err:
        logger.warning("langchain-mcp-adapters not installed (%s); skipping MCP tools", err)
        return []
    client = MultiServerMCPClient({name: server_conf})
    return await client.get_tools()


def _fetch_single_server_tools(name: str, server_conf: Dict[str, Any]) -> List[Any]:
    result: Dict[str, Any] = {"tools": [], "error": None}

    def runner() -> None:
        try:
            result["tools"] = asyncio.run(_fetch_single_server_tools_async(name, server_conf))
        except Exception as err:
            result["error"] = err

    thread = threading.Thread(target=runner, name=f"mcp-loader-{name}", daemon=True)
    thread.start()
    thread.join(timeout=PER_SERVER_TIMEOUT_SECONDS)
    if thread.is_alive():
        raise TimeoutError(f"failed after {PER_SERVER_TIMEOUT_SECONDS}s: timeout")
    if result["error"] is not None:
        raise result["error"]
    return result["tools"]


def load_mcp_tools(config: Dict[str, Any]) -> Tuple[List[Any], Dict[str, Dict[str, Any]]]:
    raw = config.get("mcp_servers_raw") or os.getenv("DEEPAGENTS_MCP_SERVERS", "")
    server_config = parse_mcp_config(raw)
    if not server_config:
        logger.info("No MCP servers configured (DEEPAGENTS_MCP_SERVERS empty)")
        return [], {}

    aggregated_tools: List[Any] = []
    failed_servers: Dict[str, Dict[str, Any]] = {}
    logger.info("Loading MCP tools from %s server(s): %s", len(server_config), list(server_config.keys()))
    with ThreadPoolExecutor(max_workers=len(server_config)) as executor:
        future_map = {
            executor.submit(_fetch_single_server_tools, name, conf): (name, conf)
            for name, conf in server_config.items()
        }
        for future in as_completed(future_map, timeout=PER_SERVER_TIMEOUT_SECONDS + 10):
            name, conf = future_map[future]
            try:
                tools = future.result()
                aggregated_tools.extend(tools)
                logger.info("MCP server '%s' loaded %s tools", name, len(tools))
            except Exception as err:
                failed_servers[name] = conf
                logger.error("MCP server '%s' failed after 30s: %s", name, err)
    return aggregated_tools, failed_servers


class MCPToolManager:
    def __init__(
        self,
        config: Dict[str, Any],
        on_recovered_tools: Optional[Callable[[List[Any]], None]] = None,
    ):
        self.config = config
        self.on_recovered_tools = on_recovered_tools
        self._failed_servers: Dict[str, Dict[str, Any]] = {}
        self._stop_event = threading.Event()
        self._reconnect_thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> List[Any]:
        tools, failed = load_mcp_tools(self.config)
        with self._lock:
            self._failed_servers = dict(failed)
        if failed:
            self._reconnect_thread = threading.Thread(target=self._reconnect_loop, name="deepagents-mcp-reconnect", daemon=True)
            self._reconnect_thread.start()
        return tools

    def stop(self) -> None:
        self._stop_event.set()

    def _reconnect_loop(self) -> None:
        while not self._stop_event.wait(RECONNECT_INTERVAL_SECONDS):
            with self._lock:
                failed_items = list(self._failed_servers.items())
            for name, conf in failed_items:
                try:
                    tools = _fetch_single_server_tools(name, conf)
                    logger.info("Recovered MCP server '%s' with %s tools", name, len(tools))
                    if self.on_recovered_tools:
                        self.on_recovered_tools(tools)
                    with self._lock:
                        self._failed_servers.pop(name, None)
                except Exception as err:
                    logger.debug("MCP reconnect still failing for '%s': %s", name, err)


def create_mcp_tool_manager(
    config: Dict[str, Any],
    on_recovered_tools: Optional[Callable[[List[Any]], None]] = None,
) -> MCPToolManager:
    return MCPToolManager(config, on_recovered_tools=on_recovered_tools)
