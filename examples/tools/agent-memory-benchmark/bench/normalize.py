# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Answer-text normalization shared by every deterministic grading mode.

Grading has to survive cosmetic variation ("May 28" / "2026-05-28" / "28 May
2026") without becoming so permissive that a wrong answer slips through. Every
transform here is lossless with respect to *meaning*: case, punctuation,
whitespace, date spelling, and thousands separators only.
"""

from __future__ import annotations

import os
import re
import unicodedata

_MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}

_PUNCT = re.compile(r"[\"'`~!@#$%^&*()\[\]{}<>?,.;:/\\|_+=—–-]+")
_SPACE = re.compile(r"\s+")
# "May 28", "May 28 2026", "28 May 2026", "May 28, 2026"
_MONTH_DAY = re.compile(
    r"\b(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
    re.IGNORECASE,
)
_DAY_MONTH = re.compile(
    r"\b(\d{1,2})\s+(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")(?:\s*,?\s*(\d{4}))?\b",
    re.IGNORECASE,
)
_ISO = re.compile(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b")
_SLASH = re.compile(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{2,4}))?\b")

# A bare "September 7" has to become some year. Corpus A is set in 2026 and
# corpus B in 2027, so a hardcoded default silently failed every corpus-B date
# comparison: the system said "September 7", the key said 2027-09-07, and the
# grader compared it against 2026-09-07. The year is therefore configurable, and
# both interpretations are tried when matching.
DEFAULT_YEAR = os.environ.get("MNEMO_DEFAULT_YEAR", "2026")
ALT_YEARS = [y for y in os.environ.get("MNEMO_ALT_YEARS", "2027").split(",") if y]


def _iso(year: str | None, month: int, day: int) -> str:
    return f"{year or DEFAULT_YEAR}-{month:02d}-{int(day):02d}"


def canonicalize_dates(text: str) -> str:
    """Rewrite every recognized date spelling to ISO ``YYYY-MM-DD``."""
    text = _ISO.sub(lambda m: _iso(m.group(1), int(m.group(2)), int(m.group(3))), text)
    text = _MONTH_DAY.sub(
        lambda m: _iso(m.group(3), _MONTHS[m.group(1).lower()], int(m.group(2))), text
    )
    text = _DAY_MONTH.sub(
        lambda m: _iso(m.group(3), _MONTHS[m.group(2).lower()], int(m.group(1))), text
    )
    # 6/8 -> 2026-06-08 (US month/day; the corpus is US-authored)
    text = _SLASH.sub(
        lambda m: _iso(
            (("20" + m.group(3)) if m.group(3) and len(m.group(3)) == 2 else m.group(3)),
            int(m.group(1)),
            int(m.group(2)),
        ),
        text,
    )
    return text


# "2026-06-03 - 6" (what a range collapses to after date canonicalization) is
# expanded so both endpoints are matchable; "June 3-6" and "June 3 to June 6"
# then normalize identically.
_ISO_RANGE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\s*[-\u2013\u2014]\s*(\d{1,2})\b")


def expand_date_ranges(text: str) -> str:
    return _ISO_RANGE.sub(
        lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)} {m.group(1)}-{m.group(2)}-{int(m.group(4)):02d}",
        text,
    )


_WEEKDAYS = {
    "mon": "monday", "tue": "tuesday", "tues": "tuesday", "wed": "wednesday",
    "weds": "wednesday", "thu": "thursday", "thur": "thursday", "thurs": "thursday",
    "fri": "friday", "sat": "saturday", "sun": "sunday",
}
_WEEKDAY_RE = re.compile(r"\b(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + r")\b\.?", re.IGNORECASE)

# "24 seconds" and "24s" are the same answer; so are "14 days" and "14d".
_UNITS = {
    "seconds": "s", "second": "s", "secs": "s", "sec": "s",
    "minutes": "min", "minute": "min", "mins": "min",
    "hours": "h", "hour": "h", "hrs": "h", "hr": "h",
    "days": "d", "day": "d",
    "weeks": "w", "week": "w",
}
_UNIT_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + r")\b", re.IGNORECASE)


def canonicalize_units(text: str) -> str:
    """Collapse spelled-out durations onto their short form."""
    return _UNIT_RE.sub(lambda m: f"{m.group(1)}{_UNITS[m.group(2).lower()]}", text)


def expand_weekdays(text: str) -> str:
    """"Mon" and "Monday" are the same day; make them the same string."""
    return _WEEKDAY_RE.sub(lambda m: _WEEKDAYS[m.group(1).lower()], text)


def normalize(text: str, year: str | None = None) -> str:
    """Case/punctuation/whitespace/date-insensitive form used for matching."""
    global DEFAULT_YEAR
    previous = DEFAULT_YEAR
    if year:
        DEFAULT_YEAR = year
    try:
        return _normalize(text)
    finally:
        DEFAULT_YEAR = previous


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("’", "'").replace("‘", "'")
    text = canonicalize_dates(text)
    text = expand_date_ranges(text)
    text = text.lower()
    text = expand_weekdays(text)
    text = canonicalize_units(text)
    text = re.sub(r"(\d),(\d{3})\b", r"\1\2", text)  # 1,000 -> 1000
    text = _PUNCT.sub(" ", text)
    return _SPACE.sub(" ", text).strip()


def _contains_one(haystack: str, needle: str, year: str | None) -> bool:
    hay, ned = normalize(haystack, year), normalize(needle, year)
    if not ned:
        return False
    if " " in ned:
        return ned in hay
    return re.search(rf"(?<![a-z0-9]){re.escape(ned)}(?![a-z0-9])", hay) is not None


def contains(haystack: str, needle: str) -> bool:
    """Whole-token containment of ``needle`` inside ``haystack`` after normalization.

    Bare month-day dates are resolved under each candidate year, so a corpus set
    in a different year than the default still matches.
    """
    for year in [None, *ALT_YEARS]:
        if _contains_one(haystack, needle, year):
            return True
    return False
