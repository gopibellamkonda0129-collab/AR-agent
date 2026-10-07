"""Resolve natural-language payment dates into real dates.

"We will pay next Friday." + today = 2026-09-08 (Tuesday) -> 2026-09-18
"end of the month"                                      -> 2026-09-30
"in 3 days", "by the 15th", "before Friday", ISO dates... -> actual date
"""
from __future__ import annotations

import calendar
import re
from datetime import date, timedelta

ISO_RE = re.compile(r"\b(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})\b")
US_RE = re.compile(r"\b(\d{1,2})/(\d{1,2})/(\d{2,4})\b")
DAY_MONTH_RE = re.compile(r"\b(?:the\s+)?(by|on|before)?\s*(\d{1,2})(?:st|nd|rd|th)?\b")
MONTH_DAY_RE = re.compile(
    r"\b([A-Za-z]{3,9})\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?\b"
)

WEEKDAYS = {
    "monday": 0, "mon": 0,
    "tuesday": 1, "tue": 1, "tues": 1,
    "wednesday": 2, "wed": 2,
    "thursday": 3, "thu": 3, "thur": 3, "thurs": 3,
    "friday": 4, "fri": 4,
    "saturday": 5, "sat": 5,
    "sunday": 6, "sun": 6,
}

_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december",
         "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
         "oct", "nov", "dec"]
    )
}

# "end of this month" / "end of month" / "end of the week"
_END_PAT = re.compile(r"\bend\s+of\s+(?:the\s+)?(this\s+|the\s+)?(month|week|year)\b")


def _parse_absolute(text: str) -> date | None:
    m = ISO_RE.search(text)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            pass
    m = US_RE.search(text)
    if m:
        y = int(m.group(3))
        y = y + 2000 if y < 100 else y
        try:
            return date(y, int(m.group(1)), int(m.group(2)))
        except ValueError:
            pass
    return None


def _weekday_occ(base: date, wd: int) -> date:
    """Next occurrence of weekday wd on or after base."""
    days = (wd - base.weekday()) % 7
    return base + timedelta(days=days)


def resolve_promise_date(text: str, base: date) -> date | None:
    """Return the concrete date promised in `text`, relative to `base`."""
    if not text:
        return None

    abs_d = _parse_absolute(text)
    if abs_d:
        return abs_d

    low = text.lower()

    # "end of the month/week/year"
    m = _END_PAT.search(low)
    if m:
        unit = m.group(2)
        if unit == "month":
            return date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])
        if unit == "year":
            return date(base.year, 12, 31)
        # week -> end of the current week
        days_until_sun = (6 - base.weekday()) % 7
        return base + timedelta(days=days_until_sun)

    # "<prefix> <weekday>" e.g. "next friday", "this friday", "by friday"
    wd_m = re.search(
        r"(\b(?:next|this|coming|following)\b\s+)?"
        r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday"
        r"|mon|tue|tues|wed|thu|thur|thurs|fri|sat|sun)\b", low)
    if wd_m:
        wd = WEEKDAYS[wd_m.group(2)]
        prefix = (wd_m.group(1) or "").lower()
        if "next" in prefix:
            return _weekday_occ(base, wd) + timedelta(days=7)
        return _weekday_occ(base, wd)

    # "in N days/weeks"
    n_m = re.search(r"\bin\s+(\d{1,2})\s*(day|week|month)s?\b", low)
    if n_m:
        n = int(n_m.group(1))
        unit = n_m.group(2)
        if unit == "day":
            return base + timedelta(days=n)
        if unit == "week":
            return base + timedelta(days=n * 7)
        if unit == "month":
            y, m0 = base.year, base.month
            for _ in range(n):
                m0 += 1
                if m0 == 13:
                    m0, y = 1, y + 1
            d = min(base.day, calendar.monthrange(y, m0)[1])
            return date(y, m0, d)

    # "August 15" / "15 August" -> stated fact, taken literally that year.
    # Checked BEFORE the bare day-number rule so "by September 15" is never
    # misread as "by the 15th" (which would roll to the next month once the
    # stated 15th has passed). A named month + day is a fact, not a hint,
    # so it is never shifted to a different date.
    m = MONTH_DAY_RE.search(low)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        day = int(m.group(2))
        year = int(m.group(3)) if m.group(3) else None
        if month and day <= 31:
            if year:
                try:
                    return date(year, month, day)
                except ValueError:
                    return None
            try:
                return date(base.year, month, day)
            except ValueError:
                return None

    # "by the 15th" / "the 15th" -> current month (next month if passed)
    m = DAY_MONTH_RE.search(low)
    if m:
        hint = (m.group(1) or "").lower()
        day = int(m.group(2))
        if day <= 31:
            target = date(base.year, base.month, day)
            if (target - base).days < 0:
                y, mo = base.year, base.month + 1
                if mo == 13:
                    mo, y = 1, y + 1
                target = date(y, mo, day)
            if "before" in hint or "by" in hint or target >= base:
                try:
                    return target
                except ValueError:
                    return None
            return target

    return None


# ---------------------------------------------------------------------------
# promise phrases: "We will pay next Friday" -> (phrase, date)
# ---------------------------------------------------------------------------

_PROMISE_HINTS = (
    r"\b(?:are|will|we.?ll|is going to|be|will be)\s+"
    r"(?:going to\s+)?(?:pay|send|wire|transfer|remit|settle|clear|release)",
    r"\b(?:payment|the payment|balance|invoice|funds|check|wire|transfer)\s+"
    r"(?:will|would|should|going to)?\s*"
    r"(?:be\s+)?(?:sent|made|paid|wired|transferred|remitted|cleared|mailed)",
    r"\b(?:will\s+|going to\s+)?(?:pay|settle|remit|send)\s+(?:the\s+)?(?:balance|amount)?",
    r"\bby\s+(?:next\s+)?(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|week|month|end)",
    r"\bpay\s+(?:by|on|before)\s+",
)

_VERB_RE = re.compile(
    r"\b(?:are|will|we.?ll|is going to|be|will be)\s+(?:going to\s+)?"
    r"(?:pay|send|wire|transfer|remit|settle|clear|release)"
    r"|\b(?:payment|the payment|balance|invoice|funds|check|wire|transfer)\s+"
    r"(?:will|would|should|going to)?\s*(?:be\s+)?"
    r"(?:sent|made|paid|wired|transferred|remitted|cleared|mailed)"
    r"|\b(?:will\s+|going to\s+)?(?:pay|settle|remit|send)\s+(?:the\s+)?(?:balance|amount)?",
    re.IGNORECASE,
)

_DATE_TOK_RE = re.compile(
    r"(next\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
    r"|end\s+of\s+(?:the\s+)?(?:this\s+|the\s+)?(?:month|week|year)"
    r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}"
    r"|in\s+\d+\s+(?:days?|weeks?|months?)"
    + f"|(?:{'|'.join(sorted(_MONTHS.keys(), key=len, reverse=True))})\\s+\\d{{1,2}}(?:,?\\s+\\d{{4}})?"
    + r"|(?:by|on|before|the)\s+\d{1,2}(?!\d)(?:st|nd|rd|th)?"
    + r"|monday|tuesday|wednesday|thursday|friday|saturday|sunday)"
)


def extract_promise(text: str) -> tuple[str, str]:
    """Return (phrase, raw_date_token) for a 'we will pay <date>' expression.

    The date token is only looked for in the text that FOLLOWS the promise
    verb, so unrelated numbers (invoice refs, amounts) earlier in the message
    can never be misread as a payment date. Plain day numbers must be preceded
    by 'by / on / before / the' to avoid matching digits in dollar amounts.
    """
    low = " ".join(text.lower().split())
    if not any(re.search(p, low) for p in _PROMISE_HINTS):
        return "", ""
    verb = _VERB_RE.search(low)
    if not verb:
        return "", ""
    lookahead = low[verb.end():verb.end() + 120]
    m = _DATE_TOK_RE.search(lookahead)
    if not m:
        return "", ""
    start = max(0, verb.start() - 60)
    tok_end = verb.end() + m.start() + len(m.group(1))
    phrase = low[start:tok_end].strip().rstrip(".")
    return phrase, m.group(1)