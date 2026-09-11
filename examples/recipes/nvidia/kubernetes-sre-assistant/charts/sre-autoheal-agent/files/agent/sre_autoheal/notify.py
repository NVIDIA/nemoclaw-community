# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Notifications: Slack (incoming webhook or bot token), SMTP email, generic webhook, stdout.

One incident is rendered once into ordered, typed sections, then each sink
renders those sections in its own format: Slack mrkdwn, plain text, or a styled
HTML email with real tables and numbered steps.

Message kinds:
* healed / heal_failed              - what was detected, what the agent did, how it verified
* escalated / approval_needed       - what is happening, the evidence, and the operator's next steps
"""
from __future__ import annotations

import html as html_module
import json
import logging
import smtplib
import ssl
import urllib.error
import urllib.request
from email.message import EmailMessage
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Incident, iso

log = logging.getLogger(__name__)

SEVERITY_EMOJI = {"critical": ":rotating_light:", "high": ":red_circle:", "medium": ":large_orange_circle:",
                  "low": ":large_yellow_circle:", "info": ":information_source:"}
SEVERITY_COLOR = {"critical": "#b91c1c", "high": "#c2410c", "medium": "#b45309",
                  "low": "#a16207", "info": "#374151"}
SEVERITY_TINT = {"critical": "#fef2f2", "high": "#fff7ed", "medium": "#fffbeb",
                 "low": "#fefce8", "info": "#f9fafb"}
EVENT_TITLES = {
    "healed": "Auto-healed",
    "heal_failed": "Auto-heal FAILED - human action needed",
    "escalated": "Escalation - human action needed",
    "approval_needed": "Approval needed for remediation",
    "observed": "Observed (no action taken)",
    "posture": "Posture audit",
    "digest": "Digest",
}
FACT_LABELS = {
    "cause": "Cause", "restart_count": "Restarts", "last_exit_code": "Exit code",
    "last_termination_reason": "Termination reason", "waiting_reason": "Waiting reason",
    "affected_pods": "Affected pods", "container": "Container", "image": "Image",
    "node": "Node", "pod": "Pod",
}
COMMAND_PREFIXES = ("kubectl", "oc ", "helm", "argocd", "curl", "python3")
MAX_LOG_TAIL_CHARS = 2000


class Section:
    """One rendered block. kind: kv | text | table | steps | code."""

    def __init__(self, kind: str, title: str, body: Any):
        self.kind = kind
        self.title = title
        self.body = body


def _clean_kv(pairs: Iterable[Tuple[str, Any]]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for key, value in pairs:
        if value is None or value == "" or value == []:
            continue
        out.append((key, str(value)))
    return out


class Message:
    def __init__(self, event: str, title: str, sections: List[Section], severity: str, payload: Dict[str, Any]):
        self.event = event
        self.title = title
        self.sections = sections
        self.severity = severity
        self.payload = payload

    # -- shared rendering ----------------------------------------------------
    @property
    def lines(self) -> List[str]:
        """Slack mrkdwn lines. Also used by the stdout sink and the tests."""
        out: List[str] = []
        for section in self.sections:
            if section.kind == "kv":
                if not section.body:
                    continue
                out.append(f"*{section.title}*")
                out.extend(f"• {key}: {value}" for key, value in section.body)
            elif section.kind == "text":
                if not section.body:
                    continue
                out.append(f"*{section.title}*")
                out.append(str(section.body))
            elif section.kind == "table":
                headers, rows = section.body
                if not rows:
                    continue
                out.append(f"*{section.title}*")
                for row in rows:
                    out.append("• " + " | ".join(str(cell) for cell in row))
            elif section.kind == "steps":
                if not section.body:
                    continue
                out.append(f"*{section.title}*")
                out.extend(f"{index}. {step}" for index, step in enumerate(section.body, 1))
            elif section.kind == "code":
                if not section.body:
                    continue
                out.append(f"*{section.title}*")
                out.append(f"`{section.body}`")
        return out

    @property
    def markdown(self) -> str:
        return f"*{self.title}*\n" + "\n".join(self.lines)

    @property
    def text(self) -> str:
        plain = [self.title, "=" * min(len(self.title), 78), ""]
        for line in self.lines:
            plain.append(line.replace("*", "").replace("`", ""))
        return "\n".join(plain)

    # -- email ---------------------------------------------------------------
    @property
    def html(self) -> str:
        color = SEVERITY_COLOR.get(self.severity, "#374151")
        tint = SEVERITY_TINT.get(self.severity, "#f9fafb")
        event_label = EVENT_TITLES.get(self.event, self.event)
        blocks = [
            '<div style="font-family:-apple-system,Segoe UI,Helvetica,Arial,sans-serif;'
            'color:#111827;font-size:14px;line-height:1.5;max-width:900px">',
            f'<div style="border-left:6px solid {color};background:{tint};padding:12px 16px;margin-bottom:18px">'
            f'<div style="font-size:12px;letter-spacing:.06em;text-transform:uppercase;color:{color};'
            f'font-weight:700">{_esc(event_label)}</div>'
            f'<div style="font-size:18px;font-weight:600;margin-top:4px">{_esc(self.headline)}</div>'
            "</div>",
        ]
        for section in self.sections:
            blocks.append(self._html_section(section))
        blocks.append(
            '<details style="margin-top:22px"><summary style="cursor:pointer;color:#6b7280;font-size:13px">'
            "Raw incident JSON</summary>"
            '<pre style="background:#f3f4f6;padding:12px;overflow-x:auto;font-size:12px;line-height:1.4">'
            f"{_esc(json.dumps(self.payload, indent=1, default=str)[:60000])}</pre></details>"
        )
        blocks.append("</div>")
        return "<!doctype html><html><body>" + "".join(blocks) + "</body></html>"

    @property
    def headline(self) -> str:
        """Title without the event prefix, used as the email banner line."""
        _prefix, _sep, rest = self.title.partition(": ")
        return rest or self.title

    def _html_section(self, section: Section) -> str:
        heading = (
            f'<div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:.04em;'
            f'color:#374151;margin:18px 0 8px">{_esc(section.title)}</div>'
        )
        if section.kind == "kv":
            if not section.body:
                return ""
            rows = "".join(
                '<tr>'
                f'<td style="padding:6px 12px 6px 0;color:#6b7280;white-space:nowrap;'
                f'vertical-align:top;border-bottom:1px solid #f3f4f6">{_esc(key)}</td>'
                f'<td style="padding:6px 0;border-bottom:1px solid #f3f4f6">{_esc(value)}</td>'
                "</tr>"
                for key, value in section.body
            )
            return heading + f'<table style="border-collapse:collapse;width:100%">{rows}</table>'
        if section.kind == "text":
            if not section.body:
                return ""
            return heading + f'<p style="margin:0">{_esc(str(section.body))}</p>'
        if section.kind == "table":
            headers, data = section.body
            if not data:
                return ""
            head = "".join(
                f'<th align="left" style="padding:6px 10px;background:#f3f4f6;'
                f'border-bottom:1px solid #d1d5db;white-space:nowrap">{_esc(item)}</th>'
                for item in headers
            )
            body = "".join(
                "<tr>"
                + "".join(
                    f'<td style="padding:6px 10px;border-bottom:1px solid #f3f4f6;vertical-align:top">'
                    f"{_esc(str(cell))}</td>"
                    for cell in row
                )
                + "</tr>"
                for row in data
            )
            return heading + (
                '<table style="border-collapse:collapse;width:100%">'
                f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"
            )
        if section.kind == "steps":
            if not section.body:
                return ""
            items = "".join(f'<li style="margin-bottom:6px">{_step_html(step)}</li>' for step in section.body)
            return heading + f'<ol style="margin:0;padding-left:22px">{items}</ol>'
        if section.kind == "code":
            if not section.body:
                return ""
            return heading + (
                '<pre style="background:#f3f4f6;padding:10px 12px;overflow-x:auto;margin:0;'
                f'font-size:13px">{_esc(str(section.body))}</pre>'
            )
        return ""


def _esc(value: Any) -> str:
    return html_module.escape(str(value), quote=True)


def _step_html(step: str) -> str:
    text = str(step)
    if any(text.startswith(prefix) for prefix in COMMAND_PREFIXES):
        return f'<code style="background:#f3f4f6;padding:2px 5px">{_esc(text)}</code>'
    return _esc(text)


# ---------------------------------------------------------------------------
# Message construction
# ---------------------------------------------------------------------------
def build_message(incident: Incident, event: str, context: Dict[str, Any], cluster_summary: Dict[str, Any]) -> Message:
    finding = incident.finding
    diagnosis = incident.diagnosis or {}
    evidence = finding.get("evidence") or {}
    subject = finding.get("owner") or finding.get("resource") or {}
    namespace = subject.get("namespace")
    workload = f"{subject.get('kind')}/{subject.get('name')}"
    severity = finding.get("severity", "medium")
    environment = (context.get("environment") or "").strip()
    cluster = context.get("cluster_name") or cluster_summary.get("server") or "cluster"

    location = f"{workload}" + (f" in namespace {namespace}" if namespace else "")
    title = f"{EVENT_TITLES.get(event, event)}: {finding.get('pattern_id')} on {location}"
    if environment:
        title = f"[{environment}] {title}"

    sections: List[Section] = []

    overview = [("Environment", environment)] if environment else []
    overview += [
        ("Cluster", f"{cluster} ({cluster_summary.get('platform', 'unknown')}, {cluster_summary.get('version', 'unknown')})"),
        ("Namespace", namespace),
        ("Workload", workload),
        ("Node", evidence.get("node")),
        ("Severity", severity.upper()),
        ("Pattern", finding.get("pattern_id")),
        ("Detected (UTC)", finding.get("detected_at_iso")),
        ("Incident", incident.id),
        ("Fingerprint", incident.fingerprint),
    ]
    sections.append(Section("kv", "Overview", _clean_kv(overview)))
    sections.append(Section("text", "Symptom", finding.get("summary")))

    availability = evidence.get("availability") or {}
    management = evidence.get("management") or {}
    signals = [(FACT_LABELS.get(key, key.replace("_", " ").capitalize()), evidence.get(key))
               for key in ("cause", "container", "restart_count", "last_exit_code",
                           "last_termination_reason", "waiting_reason", "affected_pods", "image")]
    if availability:
        signals.append(("Replicas ready", f"{availability.get('ready')}/{availability.get('desired')}"))
    if management.get("managed_by"):
        owner = management.get("owner")
        signals.append(("Managed by", management["managed_by"] + (f" ({owner})" if owner else "")))
    sections.append(Section("kv", "Signals", _clean_kv(signals)))

    events = evidence.get("events") or []
    event_rows = [
        (item.get("reason") or "", f"x{item.get('count') or 1}", (item.get("message") or "")[:400])
        for item in events[:5]
    ]
    sections.append(Section("table", "Recent cluster events", (["Reason", "Count", "Message"], event_rows)))

    if diagnosis:
        confidence = diagnosis.get("confidence")
        details = _clean_kv([
            ("Source", diagnosis.get("source")),
            ("Confidence", f"{round(float(confidence) * 100)}%" if confidence is not None else None),
        ])
        sections.append(Section("text", "Root cause", diagnosis.get("root_cause")))
        sections.append(Section("kv", "Diagnosis details", details))
        sections.append(Section("text", "Rationale", diagnosis.get("rationale")))

    sections.extend(_outcome_sections(incident, event, context))

    steps = (diagnosis.get("human_steps") or [])[:12]
    sections.append(Section("steps", "Suggested next steps", steps))

    health = _clean_kv([
        ("Unhealthy pods", cluster_summary.get("unhealthy_pods")),
        ("Pending pods", cluster_summary.get("pending_pods")),
        ("Nodes not ready", cluster_summary.get("nodes_not_ready")),
        ("Degraded ClusterOperators", cluster_summary.get("degraded_operators")),
        ("Open findings", cluster_summary.get("open_findings")),
        ("Incident history", context.get("history_note")),
    ])
    sections.append(Section("kv", "Cluster health", health))

    if context.get("runbook_base_url"):
        runbook = f"{str(context['runbook_base_url']).rstrip('/')}/{finding.get('pattern_id')}"
        sections.append(Section("kv", "Runbook", [("Pattern runbook", runbook)]))

    logs = evidence.get("logs_tail")
    if logs:
        sections.append(Section("code", "Container log tail", str(logs)[-MAX_LOG_TAIL_CHARS:]))

    payload = {"event": event, "incident": incident.to_dict(), "cluster": cluster_summary, "context": context}
    return Message(event, title, sections, severity, payload)


def _outcome_sections(incident: Incident, event: str, context: Dict[str, Any]) -> List[Section]:
    result = incident.action_result or {}
    diagnosis = incident.diagnosis or {}
    if event == "healed":
        return [Section("kv", "Action taken", _clean_kv([
            ("Action", incident.action),
            ("Result", result.get("detail")),
            ("Verification", ("PASSED - " if incident.verified else "FAILED - ") + (incident.verify_detail or "")),
            ("Rollback hint", result.get("rollback_hint")),
        ]))]
    if event == "heal_failed":
        return [Section("kv", "Action attempted", _clean_kv([
            ("Action", incident.action),
            ("Result", result.get("detail")),
            ("Verification", "FAILED - " + (incident.verify_detail or "")),
            ("Why escalating", incident.decision_reason),
        ]))]
    if event == "approval_needed":
        sections = [Section("kv", "Proposed remediation", _clean_kv([
            ("Action", incident.action),
            ("Parameters", json.dumps(diagnosis.get("params") or {})),
            ("Why not automatic", incident.decision_reason),
        ]))]
        if context.get("approval_command"):
            sections.append(Section("code", "To approve, run", context["approval_command"]))
        return sections
    return [Section("kv", "Agent decision", _clean_kv([
        ("Decision", incident.decision),
        ("Why the agent did not act", incident.decision_reason),
    ]))]


def cluster_health_line(summary: Dict[str, Any]) -> str:
    parts = []
    for key, label in (("unhealthy_pods", "unhealthy pods"), ("nodes_not_ready", "nodes NotReady"),
                       ("pending_pods", "pending pods"), ("degraded_operators", "degraded ClusterOperators"),
                       ("open_findings", "open findings")):
        if key in summary:
            parts.append(f"{summary[key]} {label}")
    return ", ".join(parts) if parts else "n/a"


# ---------------------------------------------------------------------------
# Sinks
# ---------------------------------------------------------------------------
class Sink:
    name = "sink"

    def send(self, message: Message) -> bool:
        raise NotImplementedError


class StdoutSink(Sink):
    name = "stdout"

    def send(self, message: Message) -> bool:
        print("\n" + "=" * 78 + "\n" + message.text + "\n" + "=" * 78, flush=True)
        return True


class SlackSink(Sink):
    name = "slack"

    def __init__(self, webhook_url: Optional[str], bot_token: Optional[str], channel: str,
                 mention: str = "", timeout: int = 15):
        self.webhook_url = webhook_url
        self.bot_token = bot_token
        self.channel = channel
        self.mention = mention
        self.timeout = timeout

    def _blocks(self, message: Message) -> List[Dict[str, Any]]:
        emoji = SEVERITY_EMOJI.get(message.severity, "")
        text = f"{emoji} *{message.title}*\n" + "\n".join(message.lines)
        if message.event in {"escalated", "heal_failed", "approval_needed"} and self.mention:
            text = f"{self.mention} " + text
        blocks = []
        for index in range(0, len(text), 2900):  # Slack section blocks cap at 3000 characters
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": text[index:index + 2900]}})
        return blocks[:45]

    def send(self, message: Message) -> bool:
        emoji = SEVERITY_EMOJI.get(message.severity, "")
        body: Dict[str, Any] = {"text": f"{emoji} {message.title}".strip(), "blocks": self._blocks(message)}
        headers = {"Content-Type": "application/json"}
        if self.bot_token and self.channel:
            url = "https://slack.com/api/chat.postMessage"
            body["channel"] = self.channel
            headers["Authorization"] = f"Bearer {self.bot_token}"
        elif self.webhook_url:
            url = self.webhook_url
        else:
            log.warning("slack sink enabled but no webhook URL or bot token+channel configured")
            return False
        request = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read().decode("utf-8", "replace")
        except urllib.error.URLError as exc:
            log.warning("slack send failed: %s", exc)
            return False
        if raw.startswith("{"):
            data = json.loads(raw)
            if data.get("ok") is False:
                log.warning("slack API error: %s", data.get("error"))
                return False
        return True


class EmailSink(Sink):
    name = "email"

    def __init__(self, cfg: Dict[str, Any], username: Optional[str], password: Optional[str]):
        self.cfg = cfg
        self.username = username
        self.password = password

    def recipients(self) -> List[str]:
        """Configured recipients filtered by the optional domain allow-list."""
        allowed = [item.lower().lstrip("@") for item in (self.cfg.get("allowed_recipient_domains") or []) if item]
        out: List[str] = []
        for address in self.cfg.get("to_addrs") or []:
            address = str(address).strip()
            if not address or "@" not in address:
                continue
            domain = address.rsplit("@", 1)[1].lower()
            if allowed and domain not in allowed:
                log.warning("dropping email recipient %s: domain not in allowed_recipient_domains", address)
                continue
            if address not in out:
                out.append(address)
        return out

    def send(self, message: Message) -> bool:
        host = self.cfg.get("smtp_host")
        to_addrs = self.recipients()
        if not host or not to_addrs:
            log.warning("email sink enabled but smtp_host/to_addrs missing (after domain filtering)")
            return False
        mail = EmailMessage()
        mail["Subject"] = message.title
        mail["From"] = self.cfg.get("from_addr") or (self.username or "sre-autoheal@localhost")
        mail["To"] = ", ".join(to_addrs)
        mail["Auto-Submitted"] = "auto-generated"
        mail["X-Auto-Response-Suppress"] = "All"
        mail.set_content(message.text)
        mail.add_alternative(message.html, subtype="html")
        port = int(self.cfg.get("smtp_port", 587))
        try:
            if self.cfg.get("ssl"):
                server = smtplib.SMTP_SSL(host, port, timeout=20, context=ssl.create_default_context())
            else:
                server = smtplib.SMTP(host, port, timeout=20)
            with server:
                if self.cfg.get("starttls", True) and not self.cfg.get("ssl"):
                    server.starttls(context=ssl.create_default_context())
                if self.username and self.password:
                    server.login(self.username, self.password)
                server.send_message(mail)
        except (smtplib.SMTPException, OSError) as exc:
            log.warning("email send failed: %s", exc)
            return False
        return True


class WebhookSink(Sink):
    name = "webhook"

    def __init__(self, url: Optional[str], headers: Dict[str, str], timeout: int = 15):
        self.url = url
        self.headers = headers or {}
        self.timeout = timeout

    def send(self, message: Message) -> bool:
        if not self.url:
            return False
        body = {"title": message.title, "text": message.text, "severity": message.severity,
                "event": message.event, "sent_at": iso(), **message.payload}
        headers = {"Content-Type": "application/json", **self.headers}
        request = urllib.request.Request(self.url, data=json.dumps(body, default=str).encode("utf-8"),
                                         headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout):
                return True
        except urllib.error.URLError as exc:
            log.warning("webhook send failed: %s", exc)
            return False


class Notifier:
    def __init__(self, sinks: List[Sink], events: List[str]):
        self.sinks = sinks
        self.events = set(events)

    @classmethod
    def build(cls, cfg: Dict[str, Any], secret_lookup) -> "Notifier":
        sinks: List[Sink] = []
        if (cfg.get("stdout") or {}).get("enabled", True):
            sinks.append(StdoutSink())
        slack = cfg.get("slack") or {}
        if slack.get("enabled"):
            sinks.append(SlackSink(secret_lookup(slack.get("webhook_url_env", "")),
                                   secret_lookup(slack.get("bot_token_env", "")),
                                   slack.get("channel", ""), slack.get("mention_on_escalation", "")))
        email = cfg.get("email") or {}
        if email.get("enabled"):
            sinks.append(EmailSink(email, secret_lookup(email.get("username_env", "")),
                                   secret_lookup(email.get("password_env", ""))))
        hook = cfg.get("webhook") or {}
        if hook.get("enabled"):
            sinks.append(WebhookSink(secret_lookup(hook.get("url_env", "")), hook.get("headers") or {}))
        return cls(sinks, cfg.get("events") or ["healed", "escalated", "approval_needed"])

    def wants(self, event: str) -> bool:
        if event == "heal_failed":
            return "escalated" in self.events or "heal_failed" in self.events
        return event in self.events

    def send(self, message: Message) -> Dict[str, bool]:
        results = {}
        for sink in self.sinks:
            try:
                results[sink.name] = sink.send(message)
            except Exception as exc:  # noqa: BLE001 - one sink must not block the others
                log.warning("sink %s raised: %s", sink.name, exc)
                results[sink.name] = False
        return results
