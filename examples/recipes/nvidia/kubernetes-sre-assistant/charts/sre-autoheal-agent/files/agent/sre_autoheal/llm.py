# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""LLM diagnosis.

Two providers:

* ``openai``    any OpenAI-compatible ``/chat/completions`` endpoint (NVIDIA NIM,
                build.nvidia.com, vLLM, Dynamo, OpenAI...). Standard library only.
* ``anthropic`` the official ``anthropic`` SDK (optional dependency).

The model never executes anything. It returns a JSON diagnosis whose ``action``
must be one of the allow-listed catalog ids offered in the prompt; anything else
is discarded and treated as "escalate".
"""
from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from .models import Diagnosis

log = logging.getLogger(__name__)

SYSTEM_PROMPT_TEMPLATE = """You are an expert Kubernetes/OpenShift Site Reliability Engineer embedded in an automated \
self-healing agent. {environment_clause}

You receive one detected problem with evidence (status, events, logs), the matching knowledge-base pattern, \
the list of remediation actions the agent is allowed to execute (with risk tiers and historical success), and \
similar past incidents with their outcomes.

Your job: identify the most likely root cause and pick at most ONE action id from the offered list, or none.

Rules:
- Never invent actions, commands, or parameters outside the offered list and parameter schemas.
- Prefer the least invasive action that plausibly fixes the root cause. Restarting a pod does not fix a bad \
image reference, a missing ConfigMap/Secret, a wrong probe, or a persistent OOM; for those pick a human-only \
action (or null) and write precise human_steps instead.
- If the evidence points at the control plane, storage backend, certificates, RBAC/SCC, or data loss risk, \
choose null / a NEVER_AUTO action and escalate.
- Respect history: an action with a low success rate for this pattern, or that already failed for this \
subject, should not be repeated.
- confidence is your probability (0-1) that the chosen action resolves the incident.
- human_steps are concrete kubectl/oc commands or checks an on-call engineer should run, in order.
- lesson is one sentence of reusable insight for future incidents of this pattern (or empty).

Respond with ONLY a JSON object, no prose, with exactly these keys:
{"root_cause": str, "confidence": float, "action": str|null, "params": object, "rationale": str,
 "human_steps": [str], "lesson": str, "escalate_reason": str}"""


def system_prompt(environment: Optional[str]) -> str:
    """Build the system prompt for the configured environment tier.

    The tier comes from ``notifications.environment``. When it is not declared
    the prompt says so and asks for production-grade caution rather than
    asserting a permissive staging context.
    """
    env = (environment or "").strip()
    if env:
        clause = f"The cluster is the {env} environment."
    else:
        clause = ("The cluster's environment tier is not declared; treat it as production "
                  "and prefer the least invasive option.")
    return SYSTEM_PROMPT_TEMPLATE.replace("{environment_clause}", clause)


# Backwards-compatible name for callers that import the constant directly.
SYSTEM_PROMPT = system_prompt(None)


class LLMUnavailable(RuntimeError):
    pass


class LLMClient:
    def __init__(self, cfg: Dict[str, Any], api_key: Optional[str]):
        self.cfg = cfg
        self.provider = (cfg.get("provider") or "openai").lower()
        self.api_key = api_key
        self.model = cfg.get("model") or ""
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        self.timeout = int(cfg.get("timeout_seconds", 120))
        self.max_tokens = int(cfg.get("max_tokens", 2048))
        self.temperature = float(cfg.get("temperature", 0.1))
        self._anthropic = None
        if self.provider == "anthropic":
            try:
                import anthropic  # type: ignore
            except ImportError as exc:
                raise LLMUnavailable("provider=anthropic needs `pip install anthropic`") from exc
            kwargs: Dict[str, Any] = {"timeout": self.timeout}
            if self.api_key:
                kwargs["api_key"] = self.api_key
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._anthropic = anthropic.Anthropic(**kwargs)
            self.model = self.model or "claude-opus-5"
        elif self.provider == "openai":
            if not self.base_url:
                raise LLMUnavailable("llm.base_url is required for the openai-compatible provider")
            if not self.model:
                self.model = self._discover_model()
        elif self.provider in {"none", ""}:
            raise LLMUnavailable("llm.provider=none")
        else:
            raise LLMUnavailable(f"unknown llm.provider {self.provider!r}")

    # -- provider calls ------------------------------------------------------
    def _discover_model(self) -> str:
        req = urllib.request.Request(self.base_url + "/models", headers=self._headers())
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, json.JSONDecodeError, OSError) as exc:
            raise LLMUnavailable(f"could not list models at {self.base_url}: {exc}") from exc
        models = [m.get("id") for m in data.get("data", []) if m.get("id")]
        if not models:
            raise LLMUnavailable("endpoint returned no models; set llm.model explicitly")
        return models[0]

    def _headers(self) -> Dict[str, str]:
        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _complete_openai(self, system: str, user: str, max_tokens: Optional[int] = None) -> str:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "temperature": self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
        }
        req = urllib.request.Request(self.base_url + "/chat/completions", data=json.dumps(body).encode("utf-8"),
                                     headers=self._headers(), method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise LLMUnavailable(f"LLM HTTP {exc.code}: {detail}") from None
        except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
            raise LLMUnavailable(f"LLM request failed: {exc}") from None
        try:
            choice = data["choices"][0]
            message = choice["message"]
            content = message.get("content") or ""
            if isinstance(content, list):  # some servers return content parts
                content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMUnavailable(f"unexpected LLM response shape: {str(data)[:200]}") from exc
        # Reasoning models can spend the budget on thinking and cut the JSON off;
        # retry once with a much larger budget before giving up.
        if choice.get("finish_reason") == "length" and (max_tokens or self.max_tokens) < 16384:
            log.info("LLM output truncated at %s tokens; retrying with a larger budget", max_tokens or self.max_tokens)
            return self._complete_openai(system, user, max_tokens=16384)
        return content

    def _complete_anthropic(self, system: str, user: str) -> str:
        assert self._anthropic is not None
        import anthropic  # type: ignore
        effort = self.cfg.get("effort") or "medium"
        try:
            response = self._anthropic.messages.create(
                model=self.model,
                max_tokens=max(self.max_tokens, 4096),
                system=system,
                messages=[{"role": "user", "content": user}],
                thinking={"type": "adaptive"},
                output_config={"effort": effort},
            )
        except anthropic.RateLimitError as exc:
            raise LLMUnavailable(f"anthropic rate limited: {exc}") from None
        except anthropic.APIStatusError as exc:
            raise LLMUnavailable(f"anthropic API error {exc.status_code}: {exc.message}") from None
        except anthropic.APIConnectionError as exc:
            raise LLMUnavailable(f"anthropic connection error: {exc}") from None
        if response.stop_reason == "refusal":
            raise LLMUnavailable("anthropic model refused the request")
        return "".join(block.text for block in response.content if getattr(block, "type", "") == "text")

    def complete(self, system: str, user: str) -> str:
        if self.provider == "anthropic":
            return self._complete_anthropic(system, user)
        return self._complete_openai(system, user)

    # -- diagnosis -----------------------------------------------------------
    def diagnose(self, payload: Dict[str, Any], allowed_actions: List[str]) -> Diagnosis:
        user = json.dumps(payload, indent=1, default=str)
        limit = int(self.cfg.get("max_evidence_chars", 12000)) * 2
        if len(user) > limit:
            user = user[:limit] + "\n...[truncated]"
        environment = (payload.get("policy") or {}).get("environment") if isinstance(payload, dict) else None
        raw = self.complete(system_prompt(environment), user)
        parsed = parse_json_object(raw)
        if parsed is None:
            raise LLMUnavailable(f"LLM did not return JSON: {raw[:200]!r}")
        action = parsed.get("action")
        if action in {"", "null", "none", "None"}:
            action = None
        if action is not None and action not in allowed_actions:
            log.warning("LLM proposed non-allow-listed action %r; escalating", action)
            parsed["escalate_reason"] = (parsed.get("escalate_reason") or "") + f" (model proposed unsupported action {action})"
            action = None
        try:
            confidence = float(parsed.get("confidence", 0))
        except (TypeError, ValueError):
            confidence = 0.0
        steps = parsed.get("human_steps") or []
        if isinstance(steps, str):
            steps = [steps]
        params = parsed.get("params") or {}
        if not isinstance(params, dict):
            params = {}
        return Diagnosis(
            root_cause=str(parsed.get("root_cause") or "unknown")[:1000],
            confidence=max(0.0, min(1.0, confidence)),
            action=action,
            params=params,
            rationale=str(parsed.get("rationale") or "")[:1500],
            human_steps=[str(s)[:400] for s in steps][:12],
            lesson=str(parsed.get("lesson") or "")[:500],
            escalate_reason=str(parsed.get("escalate_reason") or "")[:500],
            source="llm",
        )

    def draft_text(self, instruction: str, payload: Dict[str, Any]) -> str:
        """Free-form drafting helper (used for escalation summaries)."""
        return self.complete(
            "You are an SRE writing a concise, factual incident notification for on-call engineers. "
            "Use plain sentences, no speculation beyond the evidence, and list concrete next steps.",
            instruction + "\n\n" + json.dumps(payload, indent=1, default=str)[: int(self.cfg.get("max_evidence_chars", 12000))],
        )


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    """Extract the first JSON object from model output (tolerates code fences and reasoning prose)."""
    if not text:
        return None
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=re.S)
    candidates = [fenced.group(1)] if fenced else []
    start = text.find("{")
    if start != -1:
        depth = 0
        for idx in range(start, len(text)):
            ch = text[idx]
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidates.append(text[start: idx + 1])
                    break
    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            continue
    return None
