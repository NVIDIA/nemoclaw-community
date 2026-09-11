# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Configuration loading.

Precedence (highest first): CLI flags -> environment variables -> overlay
files in ``SRE_AUTOHEAL_CONFIG_DIR`` (lexical order) -> config file(s) (JSON,
or YAML when PyYAML is importable) -> built-in defaults. The overlay directory
is how a parent Helm chart (for example hermes-webui-openshell) hands the agent
its mail-gateway, recipient, and inference settings without duplicating them. Secrets (LLM
API key, Slack token/webhook, SMTP password) are read from environment
variables or files only and are never written to logs or memory.
"""
from __future__ import annotations

import copy
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

ENV_PREFIX = "SRE_AUTOHEAL_"

DEFAULTS: Dict[str, Any] = {
    "cluster": {
        # auto | kubernetes | openshift
        "platform": "auto",
        # http (in-cluster token or explicit API/token env) | kubectl (shell out)
        "transport": "auto",
        "kubectl_binary": "",
        "request_timeout_seconds": 30,
    },
    "scope": {
        # Namespaces the agent may inspect AND remediate. Empty = all namespaces
        # except the deny list.
        "include_namespaces": [],
        "exclude_namespaces": [
            "kube-system", "kube-public", "kube-node-lease",
            "openshift", "openshift-*",
        ],
        # Only remediate workloads carrying this label (empty = no label gate)
        "opt_in_label": "",
        # Never remediate workloads carrying this label; still detect & notify.
        "opt_out_label": "sre-autoheal.nvidia.com/managed=false",
        "include_cluster_scope": True,
    },
    "policy": {
        # observe   : detect + diagnose + notify, never act
        # safe      : additionally execute SAFE-tier actions
        # assisted  : SAFE auto; MEDIUM only when an approval annotation exists
        "mode": "assisted",
        "dry_run": False,
        "max_actions_per_cycle": 5,
        "max_actions_per_hour": 20,
        # Same fingerprint is not acted on again inside this window.
        "cooldown_seconds": 600,
        # If the same fingerprint was healed this many times in the window the
        # agent stops healing and escalates instead (flapping protection).
        "flap_threshold": 3,
        "flap_window_seconds": 21600,
        # Per-action tier overrides, e.g. {"scale": "SAFE"}
        "tier_overrides": {},
        # Actions that are never executed regardless of tier.
        "disabled_actions": [],
        "approval_annotation": "sre-autoheal.nvidia.com/approve",
        # Cron-like maintenance windows are out of scope; a simple global gate:
        "paused": False,
        # Minimum LLM confidence (0-1) required before acting on an LLM-chosen
        # action that the rule engine did not already rank first.
        "min_llm_confidence": 0.6,
        # Pods whose controller has fewer ready replicas than this fraction are
        # treated as an availability risk and get the higher severity.
        "unavailable_ratio_high": 0.5,
    },
    "detection": {
        "interval_seconds": 60,
        "crashloop_min_restarts": 3,
        "pending_pod_min_age_seconds": 300,
        "stuck_terminating_min_age_seconds": 900,
        "rollout_stuck_min_age_seconds": 600,
        "pvc_pending_min_age_seconds": 300,
        "node_not_ready_min_age_seconds": 300,
        "events_lookback_seconds": 1800,
        "log_tail_lines": 40,
        "max_findings_per_cycle": 50,
        "include_posture_audit": True,
    },
    "llm": {
        "enabled": True,
        # openai (any OpenAI-compatible endpoint: NVIDIA NIM, vLLM, OpenAI...) | anthropic | none
        "provider": "openai",
        "base_url": "",
        "model": "",
        "api_key_env": "SRE_AUTOHEAL_LLM_API_KEY",
        "api_key_file": "",
        "timeout_seconds": 120,
        "max_tokens": 4096,
        "temperature": 0.1,
        # anthropic only: low | medium | high
        "effort": "medium",
        # Evidence sent to the LLM is capped to this many characters.
        "max_evidence_chars": 12000,
        # Never send container logs to the LLM (only events/status) when true.
        "redact_logs": False,
    },
    "memory": {
        # file | configmap | none
        "backend": "file",
        "path": "/var/lib/sre-autoheal/memory.json",
        "configmap_name": "sre-autoheal-memory",
        "configmap_namespace": "",
        "max_incidents": 2000,
        "learning": {
            "enabled": True,
            # Skip the LLM when an action has this many samples and success rate
            "fast_path_min_samples": 5,
            "fast_path_min_success_rate": 0.9,
            # Stop proposing an action for a pattern below this rate
            "demote_min_samples": 4,
            "demote_max_success_rate": 0.3,
            "few_shot_examples": 5,
        },
    },
    "verify": {
        "timeout_seconds": 300,
        "poll_seconds": 15,
    },
    "notify": {
        "slack": {
            "enabled": False,
            "webhook_url_env": "SRE_AUTOHEAL_SLACK_WEBHOOK_URL",
            "bot_token_env": "SRE_AUTOHEAL_SLACK_BOT_TOKEN",
            "channel": "",
            "mention_on_escalation": "",
        },
        "email": {
            "enabled": False,
            "smtp_host": "",
            "smtp_port": 587,
            "starttls": True,
            "ssl": False,
            "username_env": "SRE_AUTOHEAL_SMTP_USERNAME",
            "password_env": "SRE_AUTOHEAL_SMTP_PASSWORD",
            "from_addr": "",
            "to_addrs": [],
            # Recipients outside these domains are dropped before sending
            # (empty = no restriction). Mirrors hermes-webui-openshell's
            # agentEmail.allowedRecipientDomains.
            "allowed_recipient_domains": [],
        },
        "webhook": {
            "enabled": False,
            "url_env": "SRE_AUTOHEAL_WEBHOOK_URL",
            "headers": {},
        },
        "stdout": {"enabled": True},
        # healed | escalated | approval_needed | posture | digest
        "events": ["healed", "escalated", "approval_needed"],
        # Repeat window for an unresolved incident: the same fingerprint is not
        # re-notified inside it. `healed` always notifies and is never deduped.
        "dedupe_seconds": 21600,
        # Posture digests are daily regardless of the incident repeat window.
        "posture_dedupe_seconds": 86400,
        "cluster_name": "",
        # Optional deployment label. Empty (the default) keeps it out of the
        # subject line and the body entirely.
        "environment": "",
        "runbook_base_url": "",
    },
    "log_level": "INFO",
}


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_structured_file(path: str) -> Dict[str, Any]:
    """Load a JSON or YAML file. YAML needs PyYAML; JSON is always available."""
    text = Path(path).read_text(encoding="utf-8")
    stripped = text.lstrip()
    if stripped.startswith("{") or stripped.startswith("["):
        return json.loads(text)
    try:
        import yaml  # type: ignore
    except ImportError as exc:  # pragma: no cover - environment dependent
        raise RuntimeError(
            f"{path} looks like YAML but PyYAML is not installed; "
            "convert it to JSON or install pyyaml"
        ) from exc
    data = yaml.safe_load(text)
    return data or {}


def _coerce(value: str, template: Any) -> Any:
    if isinstance(template, bool):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if isinstance(template, int) and not isinstance(template, bool):
        return int(value)
    if isinstance(template, float):
        return float(value)
    if isinstance(template, list):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(template, dict):
        return json.loads(value)
    return value


def _apply_env(config: Dict[str, Any], environ: Dict[str, str]) -> None:
    """Map SRE_AUTOHEAL_<SECTION>__<KEY>[__<SUBKEY>] to nested config keys."""
    for name, raw in environ.items():
        if not name.startswith(ENV_PREFIX) or "__" not in name:
            continue
        parts = [p.lower() for p in name[len(ENV_PREFIX):].split("__") if p]
        node = config
        for part in parts[:-1]:
            if not isinstance(node.get(part), dict):
                node[part] = {}
            node = node[part]
        leaf = parts[-1]
        template = node.get(leaf)
        try:
            node[leaf] = _coerce(raw, template) if template is not None else raw
        except (ValueError, json.JSONDecodeError):
            node[leaf] = raw


@dataclass
class Config:
    data: Dict[str, Any] = field(default_factory=lambda: copy.deepcopy(DEFAULTS))
    source_files: List[str] = field(default_factory=list)
    environ: Dict[str, str] = field(default_factory=lambda: dict(os.environ))

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def section(self, name: str) -> Dict[str, Any]:
        value = self.data.get(name, {})
        return value if isinstance(value, dict) else {}

    def secret(self, env_name: str, file_path: str = "") -> Optional[str]:
        """Read a secret from a file path or an environment variable."""
        if file_path and Path(file_path).is_file():
            return Path(file_path).read_text(encoding="utf-8").strip() or None
        if env_name:
            value = self.environ.get(env_name)
            if value:
                return value.strip()
            file_env = self.environ.get(env_name + "_FILE")
            if file_env and Path(file_env).is_file():
                return Path(file_env).read_text(encoding="utf-8").strip() or None
        return None

    def redacted(self) -> Dict[str, Any]:
        """Configuration safe for logging (secrets are only referenced by name)."""
        return copy.deepcopy(self.data)


def load_config(paths: Optional[List[str]] = None, environ: Optional[Dict[str, str]] = None) -> Config:
    environ = dict(os.environ if environ is None else environ)
    merged = copy.deepcopy(DEFAULTS)
    used: List[str] = []
    candidates = list(paths or [])
    env_path = environ.get(ENV_PREFIX + "CONFIG")
    if env_path:
        candidates.insert(0, env_path)
    for path in candidates:
        if path and Path(path).is_file():
            merged = _deep_merge(merged, load_structured_file(path))
            used.append(path)
    overlay_dir = environ.get(ENV_PREFIX + "CONFIG_DIR", "/etc/sre-autoheal/conf.d")
    if overlay_dir and Path(overlay_dir).is_dir():
        for overlay in sorted(Path(overlay_dir).iterdir()):
            if overlay.is_file() and overlay.suffix in {".json", ".yaml", ".yml"} and not overlay.name.startswith("."):
                try:
                    merged = _deep_merge(merged, load_structured_file(str(overlay)))
                    used.append(str(overlay))
                except (RuntimeError, ValueError, json.JSONDecodeError) as exc:
                    raise RuntimeError(f"invalid config overlay {overlay}: {exc}") from exc
    _apply_env(merged, environ)
    return Config(data=merged, source_files=used, environ=environ)
