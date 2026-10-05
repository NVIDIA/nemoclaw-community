"""MCP SDK 2.x stdio transport for the deterministic enterprise world.

The lightweight ``mcp_stdio`` module remains useful for direct protocol tests.
Hermes uses the current MCP SDK, whose transport and result validation are
handled here while all domain behavior stays in ``ToolRegistry``.
"""

from __future__ import annotations

import argparse
import json
from typing import Any

import anyio
from mcp import types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from .tools import ToolRegistry
from .world import EnterpriseWorld


async def _serve(registry: ToolRegistry) -> None:
    async def list_tools(
        _context: Any, _params: types.PaginatedRequestParams | None
    ) -> types.ListToolsResult:
        return types.ListToolsResult(
            tools=[types.Tool(**schema) for schema in registry.schemas()]
        )

    async def call_tool(
        _context: Any, params: types.CallToolRequestParams
    ) -> types.CallToolResult:
        result = registry.call(params.name, params.arguments)
        return types.CallToolResult(
            content=[types.TextContent(text=json.dumps(result, sort_keys=True))],
            structuredContent=result,
            isError=not result.get("ok", False),
        )

    server = Server(
        "enterprise-world-mcp",
        version="0.2.0",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--world", help="Path to a deterministic enterprise-world fixture.")
    parser.add_argument("--call-log", help="Append MCP calls and results to this JSONL file.")
    parser.add_argument("--catalog", choices=("focused", "extended"), default="extended")
    args = parser.parse_args()
    world = EnterpriseWorld.from_path(args.world) if args.world else EnterpriseWorld.default()
    registry = ToolRegistry(world, catalog=args.catalog, call_log_path=args.call_log)
    anyio.run(_serve, registry)


if __name__ == "__main__":
    main()
