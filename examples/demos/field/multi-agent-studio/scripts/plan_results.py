# SPDX-License-Identifier: Apache-2.0

"""Presentation of stopped work without erasing a useful Captain synthesis."""
import re


def usable_partial_answer(answer):
    text = str(answer or '').strip()
    # A single next-action promise is not a result. Keep this deliberately
    # narrow: a useful synthesis, suggestion, or mixed answer must survive.
    promise = re.fullmatch(
        r"(?:I|We)(?: will|['’]ll)\s+(?:(?:now|first|next)\s+)?"
        r'(?:read|inspect|verify|check|review|write|create|build|implement|finish|complete)\b[^.!?;\n]*[.!]?',
        text, re.I)
    return bool(text) and not promise


def incomplete_notice(remaining):
    return ('Incomplete:\n' + '\n'.join('- ' + gap for gap in remaining) +
            '\nNo further automatic work will be started.')
