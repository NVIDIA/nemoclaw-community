# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Narrow Slack compatibility patches for the pinned Hermes runtime.

The recipe adds two features around Hermes's public Slack adapter surface:

* a catch-all slash-command reply for workspace-specific command names;
* one-tap Block Kit choices for Hermes clarification prompts.

The clarification patch is feature-detected. It does not replace a Slack
``send_clarify`` implementation supplied by a future Hermes base.
"""
from __future__ import annotations

import logging
import re


LOGGER = logging.getLogger("nemoclaw.slack_compat")


def _patch_slack_adapter() -> None:
    try:
        try:
            # Hermes 0.18+ ships Slack as a bundled platform plugin.
            from plugins.platforms.slack.adapter import SlackAdapter
        except ImportError:
            # Keep compatibility with older NemoClaw Hermes base images.
            from gateway.platforms.slack import SlackAdapter
        from gateway.platforms.base import SendResult

        _orig_connect = SlackAdapter.connect
        _orig_send_clarify = SlackAdapter.send_clarify
        _needs_clarify_patch = "send_clarify" not in SlackAdapter.__dict__

        async def _update_clarify_message(
            self, channel_id, message_ts, question_text, decision_text
        ):
            blocks = [
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": question_text or "Clarification",
                    },
                },
                {
                    "type": "context",
                    "elements": [{"type": "mrkdwn", "text": decision_text}],
                },
            ]
            try:
                await self._get_client(channel_id).chat_update(
                    channel=channel_id,
                    ts=message_ts,
                    text=decision_text,
                    blocks=blocks,
                )
            except Exception as exc:
                LOGGER.warning("Slack clarify update failed: %s", exc)

        async def _handle_clarify_action(self, ack, body, action):
            await ack()

            action_id = str(action.get("action_id") or "")
            value = str(action.get("value") or "")
            message = body.get("message") or {}
            message_ts = str(message.get("ts") or "")
            channel_id = str((body.get("channel") or {}).get("id") or "")
            user = body.get("user") or {}
            user_id = str(user.get("id") or "")
            user_name = str(user.get("name") or "unknown")

            if not self._is_interactive_user_authorized(
                user_id,
                channel_id=channel_id,
                user_name=user_name,
            ):
                LOGGER.warning(
                    "Unauthorized Slack clarify click by %s (%s)",
                    user_name,
                    user_id,
                )
                return

            if "|" not in value:
                LOGGER.warning("Malformed Slack clarify value")
                return
            clarify_id, token = value.split("|", 1)

            resolved = getattr(self, "_nemoclaw_clarify_resolved", {})
            if resolved.pop(message_ts, True):
                return

            question_text = ""
            for block in message.get("blocks") or []:
                if block.get("type") == "section":
                    question_text = str((block.get("text") or {}).get("text") or "")
                    break

            from tools import clarify_gateway

            if action_id == "nemoclaw_clarify_other" or token == "other":
                if clarify_gateway.mark_awaiting_text(clarify_id):
                    await _update_clarify_message(
                        self,
                        channel_id,
                        message_ts,
                        question_text,
                        f"✏️ Awaiting typed answer from {user_name}…",
                    )
                else:
                    await _update_clarify_message(
                        self,
                        channel_id,
                        message_ts,
                        question_text,
                        "⏳ This prompt expired. Send a new request.",
                    )
                return

            try:
                index = int(token)
            except (TypeError, ValueError):
                LOGGER.warning("Invalid Slack clarify choice index")
                return

            choice = None
            try:
                entry = clarify_gateway._entries.get(clarify_id)
                if entry and entry.choices and 0 <= index < len(entry.choices):
                    choice = str(entry.choices[index])
            except Exception:
                choice = None

            if choice is None:
                await _update_clarify_message(
                    self,
                    channel_id,
                    message_ts,
                    question_text,
                    "⏳ This prompt expired. Send a new request.",
                )
                return

            if clarify_gateway.resolve_gateway_clarify(clarify_id, choice):
                await _update_clarify_message(
                    self,
                    channel_id,
                    message_ts,
                    question_text,
                    f"✅ {user_name}: {choice}",
                )
                LOGGER.info(
                    "Slack clarify resolved (id=%s, choice_index=%d, user=%s)",
                    clarify_id,
                    index,
                    user_name,
                )
            else:
                await _update_clarify_message(
                    self,
                    channel_id,
                    message_ts,
                    question_text,
                    "⏳ This prompt expired. Send a new request.",
                )

        async def _send_clarify(
            self,
            chat_id,
            question,
            choices,
            clarify_id,
            session_key,
            metadata=None,
        ):
            # Open-ended or over-limit prompts retain Hermes's text fallback.
            if not choices or len(choices) > 4:
                return await _orig_send_clarify(
                    self,
                    chat_id=chat_id,
                    question=question,
                    choices=choices,
                    clarify_id=clarify_id,
                    session_key=session_key,
                    metadata=metadata,
            )
            if not self._app:
                return SendResult(success=False, error="Not connected")

            try:
                escaped = (
                    str(question or "")
                    .replace("&", "&amp;")
                    .replace("<", "&lt;")
                    .replace(">", "&gt;")
                )
                question_text = f"❓ {escaped}"[:3000]
                elements = []
                for index, raw_choice in enumerate(choices):
                    label = str(raw_choice).strip() or f"Option {index + 1}"
                    elements.append(
                        {
                            "type": "button",
                            "text": {
                                "type": "plain_text",
                                "text": label[:75],
                                "emoji": True,
                            },
                            "action_id": f"nemoclaw_clarify_choice_{index}",
                            "value": f"{clarify_id}|{index}",
                        }
                    )
                elements.append(
                    {
                        "type": "button",
                        "text": {
                            "type": "plain_text",
                            "text": "✏️ Other…",
                            "emoji": True,
                        },
                        "action_id": "nemoclaw_clarify_other",
                        "value": f"{clarify_id}|other",
                    }
                )
                blocks = [
                    {
                        "type": "section",
                        "text": {"type": "mrkdwn", "text": question_text},
                    },
                    {"type": "actions", "elements": elements},
                ]
                kwargs = {
                    "channel": chat_id,
                    "text": question_text,
                    "blocks": blocks,
                }
                thread_ts = self._resolve_thread_ts(None, metadata)
                if thread_ts:
                    kwargs["thread_ts"] = thread_ts
                result = await self._get_client(chat_id).chat_postMessage(**kwargs)
                message_ts = str(result.get("ts") or "")
                if message_ts:
                    resolved = getattr(self, "_nemoclaw_clarify_resolved", None)
                    if resolved is None:
                        resolved = {}
                        self._nemoclaw_clarify_resolved = resolved
                    resolved[message_ts] = False
                    if len(resolved) > 1000:
                        for old_ts in list(resolved)[:500]:
                            resolved.pop(old_ts, None)

                return SendResult(
                    success=True,
                    message_id=message_ts,
                    raw_response=result,
                )
            except Exception as exc:
                LOGGER.warning("Slack clarify prompt failed: %s", exc)
                return await _orig_send_clarify(
                    self,
                    chat_id=chat_id,
                    question=question,
                    choices=choices,
                    clarify_id=clarify_id,
                    session_key=session_key,
                    metadata=metadata,
                )

        async def _patched_connect(self, *args, **kwargs):
            result = await _orig_connect(self, *args, **kwargs)
            app = getattr(self, "_app", None)
            if app is not None and getattr(
                self, "_nemoclaw_unknown_command_app", None
            ) is not app:

                @app.command(re.compile(".+"))
                async def _handle_unknown_command(ack, command, respond):
                    await ack()
                    command_name = command.get("command", "this command")
                    await respond(
                        f"I don't recognize `{command_name}`. "
                        "Send me a *direct message* or @mention me to chat"
                    )

                self._nemoclaw_unknown_command_app = app

            if (
                _needs_clarify_patch
                and app is not None
                and getattr(self, "_nemoclaw_clarify_app", None) is not app
            ):
                app.action(re.compile(r"^nemoclaw_clarify_choice_\d+$"))(
                    self._nemoclaw_handle_clarify_action
                )
                app.action("nemoclaw_clarify_other")(
                    self._nemoclaw_handle_clarify_action
                )
                self._nemoclaw_clarify_app = app
            return result

        SlackAdapter.connect = _patched_connect
        if _needs_clarify_patch:
            SlackAdapter.send_clarify = _send_clarify
            SlackAdapter._nemoclaw_handle_clarify_action = _handle_clarify_action
    except Exception as exc:
        LOGGER.debug("Slack compatibility patch was not applied: %s", exc)


_patch_slack_adapter()
