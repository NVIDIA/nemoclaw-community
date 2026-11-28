# SPDX-License-Identifier: Apache-2.0

"""Shorten workspace artifact references without changing files or access rights."""
import json
import re
from pathlib import Path


def relative_references(answer, workspace, structured=False):
    roots = {str(Path(workspace).absolute()), str(Path(workspace).resolve())}
    prefixes = '|'.join(re.escape(root.rstrip('/') + '/artifacts/') for root in sorted(roots, key=len, reverse=True))
    pattern = re.compile(r'(?<![\w/])(?:file://)?(?:' + prefixes + ')')

    def prose(text):
        # Code is a deliverable, not a display label. Preserve fenced blocks and
        # external URLs, even when a URL happens to contain a workspace path.
        pieces = re.split(r'(^```[^\n]*\n.*?(?:^```[^\n]*$|\Z)|^~~~[^\n]*\n.*?(?:^~~~[^\n]*$|\Z)|https?://[^\s<>]+)',
                          text, flags=re.MULTILINE | re.DOTALL)
        return ''.join(piece if index % 2 else pattern.sub('artifacts/', piece)
                       for index, piece in enumerate(pieces))

    def visit(value):
        if isinstance(value, str):
            return prose(value)
        if isinstance(value, list):
            return [visit(item) for item in value]
        if isinstance(value, dict):
            return {key: visit(item) for key, item in value.items()}
        return value

    text = str(answer)
    if structured:
        try:
            text = json.dumps(visit(json.loads(text)), ensure_ascii=False)
        except (ValueError, TypeError):
            # Leave malformed decision handling to the existing plan parser.
            return answer
    else:
        text = prose(text)
    if text == str(answer):
        return answer
    if hasattr(answer, 'metrics'):
        from telemetry import Reply
        result = Reply(text, answer.metrics)
        result.__dict__.update(answer.__dict__)
        return result
    return text


def published_references(answer, aliases):
    """Resolve only server-recorded aliases; preserve code and external URLs."""
    if not aliases:return answer
    pattern=re.compile(r'(?<![\w/.-])(?:'+ '|'.join(re.escape(key) for key in sorted(aliases,key=len,reverse=True)) +r')(?![\w/-]|\.\w)')
    pieces=re.split(r'(^```[^\n]*\n.*?(?:^```[^\n]*$|\Z)|^~~~[^\n]*\n.*?(?:^~~~[^\n]*$|\Z)|https?://[^\s<>]+)',
                    str(answer), flags=re.MULTILINE|re.DOTALL)
    text=''.join(piece if i%2 else pattern.sub(lambda m:aliases[m[0]],piece) for i,piece in enumerate(pieces))
    if hasattr(answer,'metrics'):
        from telemetry import Reply
        result=Reply(text,answer.metrics);result.__dict__.update(answer.__dict__)
        return result
    return text
