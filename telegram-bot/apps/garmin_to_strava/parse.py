"""Turns the user's text into an activity selector, a title and a description.

Format:  [dry] <selector> | <title> | <description>
Without '|': if the first line is a valid selector naming a day or `last` it is
used as one (so a one-word title like "Ride" stays a title), otherwise the
selector is 'today'; the next line is the title and the rest the description.

Selector words (any order): today, yesterday, YYYY-MM-DD, `last N` (`last` = `last 1`),
an activity type (ride/run/walk/hike/swim, singular or plural), and filler
words such as 'latest', 'activities', 'all', 'from', 'my'.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

# Garmin activityType.typeKey substrings per family.
TYPE_FAMILIES = {
    "ride": ("cycling", "biking"),
    "run": ("running",),
    "walk": ("walking",),
    "hike": ("hiking",),
    "swim": ("swimming",),
}
TYPE_ALIASES = {
    "ride": "ride", "rides": "ride", "bike": "ride", "bikes": "ride", "cycling": "ride",
    "run": "run", "runs": "run", "running": "run",
    "walk": "walk", "walks": "walk", "walking": "walk",
    "hike": "hike", "hikes": "hike", "hiking": "hike",
    "swim": "swim", "swims": "swim", "swimming": "swim",
}
FILLER = {"latest", "activities", "activity", "all", "from", "my", "of", "the", "on", "for"}


class SelectorError(ValueError):
    pass


@dataclass(frozen=True)
class Selector:
    date_from: date | None = None
    date_to: date | None = None
    limit: int | None = None         # 'last N': the N most recent matching activities
    family: str | None = None        # key of TYPE_FAMILIES

    def matches_type(self, type_key: str) -> bool:
        return self.family is None or any(s in type_key for s in TYPE_FAMILIES[self.family])

    def describe(self) -> str:
        parts = []
        if self.limit:
            parts.append(f"last {self.limit}")
        parts.append(f"{self.family}s" if self.family else "activities")
        if self.date_from:
            parts.append(f"on {self.date_from}" if self.date_from == self.date_to
                         else f"{self.date_from}..{self.date_to}")
        return " ".join(parts)


@dataclass(frozen=True)
class Request:
    selector: Selector
    title: str | None
    description: str | None
    dry_run: bool = False


def _anchors_selector(text: str) -> bool:
    """True if the text names a day or 'last', i.e. can't be just a title word."""
    return bool(re.search(r"\b(today|yesterday|last|\d{4}-\d{2}-\d{2})\b", text.lower()))


def parse_selector(text: str, today: date) -> Selector:
    words = re.findall(r"[\w-]+", text.lower())
    day: date | None = None
    limit = family = None
    i = 0
    while i < len(words):
        w = words[i]
        if w == "today":
            day = today
        elif w == "yesterday":
            day = today - timedelta(days=1)
        elif re.fullmatch(r"\d{4}-\d{2}-\d{2}", w):
            try:
                day = date.fromisoformat(w)
            except ValueError as e:
                raise SelectorError(f"bad date {w!r}") from e
        elif w in ("last", "latest") and i + 1 < len(words) and words[i + 1].isdigit():
            limit = int(words[i + 1])
            i += 1
        elif w == "last":
            limit = 1
        elif w in TYPE_ALIASES:
            family = TYPE_ALIASES[w]
        elif w not in FILLER:
            raise SelectorError(f"unknown word {w!r} in selector {text!r}")
        i += 1
    if limit is not None and limit < 1:
        raise SelectorError("'last N' needs N >= 1")
    if day is None and limit is None:
        day = today
    return Selector(day, day, limit, family)


def parse_request(text: str, today: date) -> Request:
    text = text.strip()
    dry = False
    if m := re.match(r"(--dry-run|dry-run|dry)(?=\s|\||$)\s*", text, re.IGNORECASE):
        dry, text = True, text[m.end():]

    if "|" in text:
        sel_text, _, rest = text.partition("|")
        title, _, desc = rest.partition("|")
        selector = parse_selector(sel_text, today)
    else:
        lines = text.splitlines()
        first = lines[0] if lines else ""
        selector = None
        if _anchors_selector(first):
            try:
                selector = parse_selector(first, today)
                lines = lines[1:]
            except SelectorError:
                pass
        if selector is None:
            selector = parse_selector("", today)
        title = lines[0] if lines else ""
        desc = "\n".join(lines[1:])
    return Request(selector, title.strip() or None, desc.strip() or None, dry)
