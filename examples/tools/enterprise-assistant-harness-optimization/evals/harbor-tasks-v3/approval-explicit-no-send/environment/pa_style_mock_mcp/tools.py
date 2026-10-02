"""Transport-independent mock enterprise tool definitions and behavior."""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .world import EnterpriseWorld


def _matches(query: str, value: Any) -> bool:
    terms = query.lower().split()
    haystack = json.dumps(value).lower()
    return all(term in haystack for term in terms)


def _page(items: list[dict[str, Any]], page: int, page_size: int) -> dict[str, Any]:
    page = max(page, 1)
    page_size = max(1, min(page_size, 25))
    total = len(items)
    start = (page - 1) * page_size
    return {
        "items": items[start : start + page_size],
        "pagination": {
            "page": page,
            "page_size": page_size,
            "total_items": total,
            "total_pages": (total + page_size - 1) // page_size,
        },
    }


class ToolRegistry:
    """Tool behavior that can be used by MCP now and a Gym adapter later."""

    def __init__(
        self,
        world: EnterpriseWorld | None = None,
        catalog: str | None = None,
        call_log_path: str | Path | None = None,
    ) -> None:
        self.world = world or EnterpriseWorld.default()
        self.catalog = catalog or os.environ.get("PA_STYLE_TOOL_CATALOG", "focused")
        if self.catalog not in {"focused", "extended"}:
            raise ValueError("catalog must be focused or extended")
        self.calls: list[dict[str, Any]] = []
        self.call_log_path = Path(call_log_path) if call_log_path else None
        self._handlers: dict[str, Callable[..., dict[str, Any]]] = {
            "connectors.get_status": self.get_connector_status,
            "people.search": self.search_people,
            "mail.search": self.search_mail,
            "mail.read_thread": self.read_mail_thread,
            "chat.search": self.search_chat,
            "chat.read_thread": self.read_chat_thread,
            "calendar.list_events": self.list_events,
            "knowledge.search": self.search_knowledge,
            "actions.prepare_message": self.prepare_message,
            "actions.send_message": self.send_message,
        }
        if self.catalog == "extended":
            self._handlers.update(
                {
                    "files.search": self.search_files,
                    "files.read_json": self.read_json_file,
                    "projects.search_tasks": self.search_project_tasks,
                    "analytics.query_metrics": self.query_analytics_metrics,
                    "support.search_tickets": self.search_support_tickets,
                }
            )

    def schemas(self) -> list[dict[str, Any]]:
        schemas = [
            self._schema("connectors.get_status", "Check a connector's availability or auth state.", {"connector": {"type": "string"}}, ["connector"]),
            self._schema("people.search", "Search the company directory.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
            self._schema("mail.search", "Search mail thread metadata. Read a returned thread before citing its messages.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
            self._schema("mail.read_thread", "Read the messages in a mail thread returned by mail.search.", {"thread_id": {"type": "string"}}, ["thread_id"]),
            self._schema("chat.search", "Search chat-thread metadata. Read a returned thread before citing messages.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
            self._schema("chat.read_thread", "Read the messages in a chat thread returned by chat.search.", {"thread_id": {"type": "string"}}, ["thread_id"]),
            self._schema("calendar.list_events", "List calendar events matching a query.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
            self._schema("knowledge.search", "Search approved enterprise knowledge documents.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
            self._schema("actions.prepare_message", "Prepare a draft and receive an approval token. This does not send anything.", {"channel": {"type": "string", "enum": ["mail", "chat"]}, "recipient": {"type": "string"}, "body": {"type": "string"}}, ["channel", "recipient", "body"]),
            self._schema("actions.send_message", "Send an approved draft. Requires a current approval token.", {"approval_token": {"type": "string"}}, ["approval_token"]),
        ]
        if self.catalog == "extended":
            schemas.extend(
                [
                    self._schema("files.search", "Search enterprise file metadata. Search never returns file bodies; inspect a returned JSON file with files.read_json.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
                    self._schema("files.read_json", "Read a bounded section of a JSON file returned by files.search. Use an RFC 6901 JSON Pointer such as /evidence/security; the root pointer returns only a key index.", {"file_id": {"type": "string"}, "json_pointer": {"type": "string"}, "max_items": {"type": "integer"}}, ["file_id"]),
                    self._schema("projects.search_tasks", "Search project task records.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
                    self._schema("analytics.query_metrics", "Search product analytics metrics.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
                    self._schema("support.search_tickets", "Search customer-support ticket records.", {"query": {"type": "string"}, "page": {"type": "integer"}, "page_size": {"type": "integer"}}, ["query"]),
                ]
            )
        return schemas

    @staticmethod
    def _schema(name: str, description: str, properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
        return {"name": name, "description": description, "inputSchema": {"type": "object", "properties": properties, "required": required, "additionalProperties": False}}

    def call(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        arguments = arguments or {}
        call = {"index": len(self.calls), "name": name, "arguments": arguments}
        self.calls.append(call)
        handler = self._handlers.get(name)
        if handler is None:
            result = self._error("TOOL_NOT_FOUND", f"Unknown tool: {name}")
        else:
            fault = self.world.consume_fault(name, arguments)
            if fault:
                result = self._error(fault["code"], fault["message"])
            else:
                try:
                    result = handler(**arguments)
                except TypeError as error:
                    result = self._error("INVALID_ARGUMENTS", str(error))
        if self.call_log_path:
            self.call_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.call_log_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(call | {"result": result}, sort_keys=True) + "\n")
        return result

    @staticmethod
    def _error(code: str, message: str) -> dict[str, Any]:
        return {"ok": False, "error": {"code": code, "message": message}}

    @staticmethod
    def _ok(**payload: Any) -> dict[str, Any]:
        return {"ok": True, **payload}

    def get_connector_status(self, connector: str) -> dict[str, Any]:
        return self._ok(**self.world.connector_status(connector))

    def search_people(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        people = [person for person in self.world.state["people"] if _matches(query, person)]
        return self._ok(**_page(people, page, page_size))

    def search_mail(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        results = [
            {key: thread[key] for key in ("id", "subject", "participants", "updated_at")}
            for thread in self.world.state["mail_threads"]
            if _matches(query, thread)
        ]
        return self._ok(**_page(results, page, page_size))

    def read_mail_thread(self, thread_id: str) -> dict[str, Any]:
        return self._read_thread("mail_threads", thread_id)

    def search_chat(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        results = [
            {key: thread[key] for key in ("id", "channel", "updated_at")}
            for thread in self.world.state["chat_threads"]
            if _matches(query, thread)
        ]
        return self._ok(**_page(results, page, page_size))

    def read_chat_thread(self, thread_id: str) -> dict[str, Any]:
        return self._read_thread("chat_threads", thread_id)

    def _read_thread(self, collection: str, thread_id: str) -> dict[str, Any]:
        for thread in self.world.state[collection]:
            if thread["id"] == thread_id:
                return self._ok(thread=thread)
        return self._error("NOT_FOUND", f"Thread not found: {thread_id}")

    def list_events(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        events = [event for event in self.world.state["calendar_events"] if _matches(query, event)]
        return self._ok(**_page(events, page, page_size))

    def search_knowledge(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        docs = [doc for doc in self.world.state["knowledge_documents"] if _matches(query, doc)]
        return self._ok(**_page(docs, page, page_size))

    def search_files(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        files = self.world.state["files"] + self.world.state.get("structured_files", [])
        results = [
            {key: item[key] for key in ("id", "name", "owner", "updated_at")}
            | ({"content_type": item["content_type"]} if "content_type" in item else {})
            for item in files
            if _matches(query, item)
        ]
        return self._ok(**_page(results, page, page_size))

    def read_json_file(self, file_id: str, json_pointer: str = "/", max_items: int = 10) -> dict[str, Any]:
        """Expose a selected JSON section with a strict item bound.

        This preserves the normal search → opaque ID → inspect workflow.  The
        root intentionally supplies an index rather than a potentially large
        object, so callers have to identify an evidence-bearing section.
        """
        file = next((item for item in self.world.state.get("structured_files", []) if item["id"] == file_id), None)
        if file is None:
            return self._error("NOT_FOUND", f"Structured JSON file not found: {file_id}")
        if not isinstance(json_pointer, str) or not json_pointer.startswith("/"):
            return self._error("INVALID_JSON_POINTER", "json_pointer must start with '/'.")
        max_items = max(1, min(max_items, 25))
        if json_pointer == "/":
            return self._ok(file_id=file_id, json_pointer="/", keys=sorted(file["content"].keys()), note="Use a JSON Pointer to inspect one named section.")
        value: Any = file["content"]
        try:
            for segment in json_pointer[1:].split("/"):
                key = segment.replace("~1", "/").replace("~0", "~")
                value = value[int(key)] if isinstance(value, list) else value[key]
        except (KeyError, IndexError, ValueError):
            return self._error("JSON_POINTER_NOT_FOUND", f"No value exists at pointer: {json_pointer}")
        if isinstance(value, dict):
            items = [{"key": key, "value": value[key]} for key in sorted(value)[:max_items]]
            return self._ok(file_id=file_id, json_pointer=json_pointer, items=items, truncated=len(value) > max_items)
        if isinstance(value, list):
            return self._ok(file_id=file_id, json_pointer=json_pointer, items=value[:max_items], truncated=len(value) > max_items)
        return self._ok(file_id=file_id, json_pointer=json_pointer, value=value, truncated=False)

    def search_project_tasks(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return self._search_collection("project_tasks", query, page, page_size)

    def query_analytics_metrics(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return self._search_collection("analytics_metrics", query, page, page_size)

    def search_support_tickets(self, query: str, page: int = 1, page_size: int = 10) -> dict[str, Any]:
        return self._search_collection("support_tickets", query, page, page_size)

    def _search_collection(self, collection: str, query: str, page: int, page_size: int) -> dict[str, Any]:
        items = [item for item in self.world.state[collection] if _matches(query, item)]
        return self._ok(**_page(items, page, page_size))

    def prepare_message(self, channel: str, recipient: str, body: str) -> dict[str, Any]:
        token_input = f"{channel}|{recipient}|{body}|{len(self.world.approvals)}"
        token = f"approval_{hashlib.sha256(token_input.encode()).hexdigest()[:12]}"
        draft = {"channel": channel, "recipient": recipient, "body": body}
        self.world.approvals[token] = draft
        return self._ok(draft=draft, approval_token=token, status="awaiting_user_approval")

    def send_message(self, approval_token: str) -> dict[str, Any]:
        draft = self.world.approvals.pop(approval_token, None)
        if draft is None:
            return self._error("APPROVAL_REQUIRED", "A valid approval token from actions.prepare_message is required.")
        self.world.outbox.append(draft)
        return self._ok(status="sent", message=draft)
