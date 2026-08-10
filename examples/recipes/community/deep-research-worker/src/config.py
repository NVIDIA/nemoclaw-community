#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Configuration loader for deepagents-worker.
Loads environment variables with fallback runtime-config.json settings.
"""
import json
import os
from typing import Any, Dict


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def load_config() -> Dict[str, Any]:
    """Load runtime configuration for DeepAgents Worker Service."""
    config: Dict[str, Any] = {
        "enabled": os.getenv("DEEPAGENTS_SERVICE_ENABLED", "true").lower() in ("true", "1", "yes"),
        "host": os.getenv("DEEPAGENTS_SERVICE_HOST", "0.0.0.0"),
        "port": _int_env("DEEPAGENTS_SERVICE_PORT", 9050),
        "service_secret": (os.getenv("DEEPAGENTS_SERVICE_SECRET") or "").strip(),
        "container_name": os.getenv("DEEPAGENTS_CONTAINER_NAME", "nemoclaw-deepagents-worker"),
        "mode": os.getenv("DEEPAGENTS_SERVICE_MODE", "live").lower(),
        "worker_concurrency": _int_env("DEEPAGENTS_WORKER_CONCURRENCY", 5),
        "task_ttl_hours": _int_env("DEEPAGENTS_TASK_TTL_HOURS", 168),
        "task_timeout_ms": _int_env("DEEPAGENTS_TASK_TIMEOUT_MS", 600000),
        "default_task_max_retries": _int_env("DEEPAGENTS_TASK_MAX_RETRIES", 2),
        "default_model": os.getenv(
            "DEEPAGENTS_DEFAULT_MODEL",
            os.getenv("LLM_GATEWAY_MODEL", os.getenv("NEMOCLAW_MODEL", "gpt-5")),
        ),
        "default_tool_profile": os.getenv("DEEPAGENTS_TOOL_PROFILE", "research").strip().lower() or "research",
        "allowed_mcp_tools": {
            name.strip()
            for name in os.getenv("DEEPAGENTS_ALLOWED_MCP_TOOLS", "").split(",")
            if name.strip()
        },
        "tool_call_budget_shallow": _int_env("DEEPAGENTS_TOOL_CALL_BUDGET_SHALLOW", 25),
        "tool_call_budget_standard": _int_env("DEEPAGENTS_TOOL_CALL_BUDGET_STANDARD", 60),
        "tool_call_budget_deep": _int_env("DEEPAGENTS_TOOL_CALL_BUDGET_DEEP", 120),
        "tool_timeout_web_search": _int_env("DEEPAGENTS_TOOL_TIMEOUT_WEB_SEARCH", 15),
        "tool_timeout_doc_search": _int_env("DEEPAGENTS_TOOL_TIMEOUT_DOC_SEARCH", 20),
        "openai_api_base": os.getenv("OPENAI_API_BASE", "http://host.docker.internal:9001/v1"),
        "openai_api_key": os.getenv("OPENAI_API_KEY", "dummy"),
        "websearch_endpoint_url": os.getenv("WEBSEARCH_ENDPOINT_URL", "http://host.docker.internal:8190"),
        "websearch_service_secret": os.getenv("WEBSEARCH_SERVICE_SECRET", ""),
        "doc_search_endpoint_url": os.getenv("DOC_SEARCH_ENDPOINT_URL", "http://host.docker.internal:8185"),
        "doc_search_service_secret": os.getenv("DOC_SEARCH_SERVICE_SECRET", ""),
        "state_dir": os.getenv(
            "DEEPAGENTS_STATE_DIR",
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "state"),
        ),
        "log_level": os.getenv("LOG_LEVEL", "INFO"),
        "mcp_servers_raw": os.getenv("DEEPAGENTS_MCP_SERVERS", ""),
    }

    config_path = os.getenv("RUNTIME_CONFIG_PATH")
    if config_path and os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                service_data = data.get("deepagents_worker", {})
                config.update(service_data)
        except Exception as err:
            print(f"[config] Warning: Failed to load runtime config from {config_path}: {err}")

    return config
