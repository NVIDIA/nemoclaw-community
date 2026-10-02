"""Optional native Streamable HTTP adapter for the fixture-backed MCP tools.

This module intentionally depends on the MCP SDK only when the HTTP adapter is
started.  The stdio implementation remains dependency-free for local fixture
work.  Registry state is keyed by the SDK's live server-session object, so an
approval token or transient-fault counter cannot cross between agent sessions.
"""

from __future__ import annotations

import argparse
import hmac
import os
import weakref
from pathlib import Path
from typing import Any

from .tools import ToolRegistry
from .world import EnterpriseWorld


class SessionRegistries:
    """Create one fixture world per live MCP session without retaining it forever."""

    def __init__(
        self,
        catalog: str = "extended",
        fixture: str | Path | None = None,
        call_log: str | Path | None = None,
    ) -> None:
        self.catalog = catalog
        self.fixture = fixture
        self.call_log = call_log
        self._registries: weakref.WeakKeyDictionary[Any, ToolRegistry] = weakref.WeakKeyDictionary()

    def for_session(self, session: Any) -> ToolRegistry:
        registry = self._registries.get(session)
        if registry is None:
            registry = ToolRegistry(
                world=EnterpriseWorld.default(self.fixture),
                catalog=self.catalog,
                call_log_path=self.call_log,
            )
            self._registries[session] = registry
        return registry


def build_server(
    *,
    catalog: str = "extended",
    host: str = "127.0.0.1",
    port: int = 8000,
    bearer_token: str | None = None,
    issuer_url: str = "https://mock-mcp.example.test",
    resource_server_url: str = "https://mock-mcp.example.test/mcp",
    fixture: str | Path | None = None,
    call_log: str | Path | None = None,
) -> Any:
    """Build, but do not start, a FastMCP Streamable HTTP server.

    The MCP SDK is optional because the local stdio path intentionally has no
    third-party runtime dependency.  The returned server exposes exactly the
    schemas from ``ToolRegistry`` under the same canonical names.
    """
    try:
        from mcp.server.auth.provider import AccessToken
        from mcp.server.auth.settings import AuthSettings
        from mcp.server.fastmcp import Context, FastMCP
    except ImportError as error:  # pragma: no cover - exercised by launch users
        raise RuntimeError("Install mcp==1.28.1 to start the Streamable HTTP adapter") from error

    # FastMCP evaluates postponed annotations through each tool function's
    # module globals. Keep this binding lazy so importing the stdio-only
    # package still requires no MCP dependency.
    globals()["Context"] = Context

    registries = SessionRegistries(catalog, fixture, call_log)
    fastmcp_options: dict[str, Any] = {}
    if bearer_token:
        class StaticDemoTokenVerifier:
            """Accept one deployment-owned demo token without logging it."""

            async def verify_token(self, token: str) -> Any:
                if hmac.compare_digest(token.encode(), bearer_token.encode()):
                    return AccessToken(token=token, client_id="enterprise-world-client", scopes=["mcp:tools"])
                return None

        fastmcp_options = {
            "auth": AuthSettings(issuer_url=issuer_url, resource_server_url=resource_server_url),
            "token_verifier": StaticDemoTokenVerifier(),
        }
    server = FastMCP(
        "Fictional enterprise world",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        **fastmcp_options,
    )

    def call(ctx: Context, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        return registries.for_session(ctx.session).call(name, arguments)

    @server.tool(name="connectors.get_status")
    def connectors_get_status(connector: str, ctx: Context) -> dict[str, Any]:
        return call(ctx, "connectors.get_status", {"connector": connector})

    @server.tool(name="people.search")
    def people_search(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "people.search", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="mail.search")
    def mail_search(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "mail.search", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="mail.read_thread")
    def mail_read_thread(thread_id: str, ctx: Context) -> dict[str, Any]:
        return call(ctx, "mail.read_thread", {"thread_id": thread_id})

    @server.tool(name="chat.search")
    def chat_search(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "chat.search", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="chat.read_thread")
    def chat_read_thread(thread_id: str, ctx: Context) -> dict[str, Any]:
        return call(ctx, "chat.read_thread", {"thread_id": thread_id})

    @server.tool(name="calendar.list_events")
    def calendar_list_events(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "calendar.list_events", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="knowledge.search")
    def knowledge_search(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "knowledge.search", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="actions.prepare_message")
    def actions_prepare_message(channel: str, recipient: str, body: str, ctx: Context) -> dict[str, Any]:
        return call(ctx, "actions.prepare_message", {"channel": channel, "recipient": recipient, "body": body})

    @server.tool(name="actions.send_message")
    def actions_send_message(approval_token: str, ctx: Context) -> dict[str, Any]:
        return call(ctx, "actions.send_message", {"approval_token": approval_token})

    @server.tool(name="files.search")
    def files_search(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "files.search", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="files.read_json")
    def files_read_json(file_id: str, ctx: Context, json_pointer: str = "/", max_items: int = 10) -> dict[str, Any]:
        return call(ctx, "files.read_json", {"file_id": file_id, "json_pointer": json_pointer, "max_items": max_items})

    @server.tool(name="projects.search_tasks")
    def projects_search_tasks(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "projects.search_tasks", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="analytics.query_metrics")
    def analytics_query_metrics(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "analytics.query_metrics", {"query": query, "page": page, "page_size": page_size})

    @server.tool(name="support.search_tickets")
    def support_search_tickets(query: str, ctx: Context, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return call(ctx, "support.search_tickets", {"query": query, "page": page, "page_size": page_size})

    return server


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", choices=["focused", "extended"], default="extended")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--require-bearer-token", action="store_true", help="Require token from PA_STYLE_MOCK_MCP_TOKEN")
    parser.add_argument("--issuer-url", default="https://mock-mcp.example.test")
    parser.add_argument("--resource-server-url", default="https://mock-mcp.example.test/mcp")
    parser.add_argument(
        "--fixture",
        default=os.environ.get("PA_STYLE_WORLD_FIXTURE"),
        help="Path to a frozen world fixture; defaults to PA_STYLE_WORLD_FIXTURE or world-v1.json.",
    )
    parser.add_argument("--call-log", help="Append MCP calls and results to this JSONL file.")
    args = parser.parse_args()
    bearer_token = os.environ.get("PA_STYLE_MOCK_MCP_TOKEN") if args.require_bearer_token else None
    if args.require_bearer_token and not bearer_token:
        raise SystemExit("PA_STYLE_MOCK_MCP_TOKEN is required with --require-bearer-token")
    build_server(
        catalog=args.catalog,
        host=args.host,
        port=args.port,
        bearer_token=bearer_token,
        issuer_url=args.issuer_url,
        resource_server_url=args.resource_server_url,
        fixture=args.fixture,
        call_log=args.call_log,
    ).run(transport="streamable-http")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
