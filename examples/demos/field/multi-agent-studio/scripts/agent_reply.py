# SPDX-License-Identifier: Apache-2.0

"""Interpret assistant replies from the OpenClaw gateway."""
import json
import re

from personal_voice import EDITED_VOICE_HEADER, VOICE_HEADER


_REPLY_PREFIX = re.compile(
    r'\A(?:\[\[[ \t]*(?:reply_to_current|reply_to:[ \t]*[^\s\[\]]+)[ \t]*\]\]'
    r'|\[reply_to_current\](?=\s|$))[ \t]*(?:\r?\n)?'
)


def without_reply_prefix(text):
    """Remove delivery metadata and an echoed persona heading before publishing a reply."""
    if not isinstance(text, str):
        return text
    text = _REPLY_PREFIX.sub('', text, count=1)
    first, _, rest = text.partition('\n')
    if first.rstrip('\r') in (VOICE_HEADER, EDITED_VOICE_HEADER):
        return rest.lstrip('\r\n')
    return text


def object_reply(answer):
    candidates = re.findall(r'```(?:json)?\s*(\{.*?\})\s*```', answer, re.S) + [answer]
    for raw in candidates:
        try:
            value = json.loads(raw)
            if isinstance(value, dict):
                return value
        except (ValueError, TypeError):
            pass
    return {}
