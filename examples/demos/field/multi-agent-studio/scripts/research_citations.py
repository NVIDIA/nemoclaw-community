# SPDX-License-Identifier: Apache-2.0

"""Reject invented public citation URLs; this is not semantic fact checking."""
import re
from urllib.parse import urlsplit, urlunsplit


def bounded_sources(sources):
    """Bound excerpt context without dropping later observed citation identities."""
    unique = {}
    for source in sources:
        unique.setdefault(source['url'], source)
    selected = list(unique.values())[:24]
    result, budget = [], 6000
    for index, source in enumerate(selected):
        # Share the existing text budget; a long first search must not erase the
        # final paper or a source added during a bounded revision.
        allowance = min(1600, budget // (len(selected) - index))
        excerpt = source['text'][:allowance]
        result.append({'url': source['url'], 'text': excerpt,
                       'truncated': source.get('truncated', False) or len(excerpt) < len(source['text'])})
        budget -= len(excerpt)
    return result


def url_mentions(text):
    text = str(text)
    for match in re.finditer(r'https?://[^\s<>"\x27`]+', text):
        value = match.group()
        if re.search(r'\[[^\]\n]*\]\($', text[:match.start()]):
            # A Korean particle can immediately follow a Markdown link. End at
            # its closing delimiter while preserving parentheses inside URLs.
            depth = 0
            for index, char in enumerate(value):
                if char == '(':
                    depth += 1
                elif char == ')':
                    if not depth:
                        value = value[:index]
                        break
                    depth -= 1
        value = value.rstrip('.,;:!?')
        while value and value[-1] in ')]}':
            close = value[-1]
            if value.count(close) <= value.count({')': '(', ']': '[', '}': '{'}[close]):
                break
            value = value[:-1]
        yield value, match.start(), match.start() + len(value)


def urls(text):
    return {value for value, _, _ in url_mentions(text)}


def identity(url):
    try:
        p = urlsplit(url)
        path = p.path.rstrip('/')
        # arXiv serves one paper in several representations. Preserve explicit
        # versions: v1, v2 and the unversioned latest URL are not interchangeable.
        if p.netloc.lower() == 'arxiv.org':
            paper = re.fullmatch(r'/(?:abs|pdf|html)/(\d{4}\.\d{4,5}(?:v[1-9]\d*)?)(?:\.pdf)?', path)
            if paper:
                path = '/abs/' + paper.group(1)
        # A fragment and the HTTP-to-HTTPS upgrade do not identify another page.
        return urlunsplit(('https', p.netloc.lower(), path, p.query, ''))
    except ValueError:
        return url


def access_failure_note(text, start, end):
    """Recognize a direct access-status clause, not general negative sentiment.

    This exempts only this mention, not the URL throughout the answer. It is not
    evidence of an actual failure and must only be used for already known URLs.
    Ambiguous wording stays subject to the ordinary citation check.
    """
    before, after = text[max(0, start - 240):start], text[end:end + 160]
    # Support Markdown links and inline-code URLs without treating their labels
    # as evidence or absorbing an adjacent substantive claim.
    link = re.search(r'\[[^\]\n]{1,120}\]\($', before)
    if link and after.startswith(')'):
        before, after = before[:link.start()], after[1:]
    before, after = before.rstrip('`'), after.lstrip('`')
    direct = re.search(
        r"(?:^|[.!?;\n])\s*(?:[-*]\s*)?(?:(?:I|we)\s+)?"
        r"(?:(?:could|can|did) not|couldn['’]t|can['’]t|didn['’]t|failed to|(?:was |were )?unable to)\s+"
        r'(?:access|fetch|read|retrieve|open|reach|verify)\s*$', before, re.I)
    if direct and re.match(r'\s*(?:[.;!?\n]|$)', after):
        return True
    if not re.search(r'(?:^|[.!?;\n])\s*(?:[-*]\s*)?$', before):
        return False
    return bool(re.match(
        r"\s*(?:(?:(?:could|can) not|couldn['’]t|can['’]t) be (?:accessed|fetched|read|retrieved|opened|reached)"
        r'|(?:was |is )?(?:inaccessible|unavailable)'
        r'|(?:에|은|는|을|를)?\s*(?:접속|접근|조회|확인|읽기|가져오기)(?:에)?\s*'
        r'(?:실패했(?:습니다|어요)|실패|할 수 없(?:었)?(?:습니다|어요)|하지 못했(?:습니다|어요)))\s*(?:[.;!?\n]|$)', after, re.I))


def known_access_references(task, outputs):
    """Input URLs and actual failed fetch targets, never model-invented sources."""
    known = urls(task)
    for output in outputs:
        activity = output.get('activity') or {}
        if activity.get('source') != 'OpenClaw transcript' or not activity.get('available'):
            continue
        for call in activity.get('calls', []):
            if call.get('tool') == 'web_fetch' and call.get('status') == 'failed':
                known.update(urls(call.get('target', '')))
    return known


def unsupported_citations(answer, sources, known_references=()):
    allowed = set()
    for source in sources:
        allowed.add(identity(source['url']))
        allowed.update(identity(url) for url in urls(source['text']))
    known = {identity(url) for url in known_references}
    text = str(answer)
    return sorted({url for url, start, end in url_mentions(text) if identity(url) not in allowed
                   and not (identity(url) in known and access_failure_note(text, start, end))})
