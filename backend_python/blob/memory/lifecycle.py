"""Time limits and correction keys for grounded user memories."""

from datetime import datetime, timedelta
import re
import time


SHORT_RECALL_DAYS = 7
MIDDLE_LIFETIME_DAYS = 30

_FAVORITE = re.compile(r"\bfavou?rite\s+([a-z][a-z0-9 ]{0,40}?)\s+(?:is|are)\b", re.I)
_LIKE = re.compile(r"\bI\s+(?:(?:no longer|don't|do not|still)\s+)?(?:like|love|enjoy)\s+"
                   r"([^,.!?;]+?)(?=\s+(?:and|but|now)\b|$|[,.!?;])", re.I)
_EVENT = re.compile(r"\b(?:exam|test|meeting|appointment|interview|deadline|flight|trip)\b", re.I)
_WEEKDAY = re.compile(r"\b(?:(next|this)\s+)?(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", re.I)
_ON_DATE = re.compile(r"\bon\s+(\d{4}-\d{2}-\d{2})\b", re.I)


def topic_key(text: str) -> str:
    """Identify a few explicit single-topic statements that can supersede each other."""
    match = _FAVORITE.search(text)
    if match:
        return "favorite:" + " ".join(match.group(1).casefold().split())
    if re.search(r"\bmy name is\b|\bcall me\b", text, re.I):
        return "name"
    if re.search(r"\bmy hobb(?:y is|ies are)\b", text, re.I):
        return "hobbies"
    match = _LIKE.search(text)
    if match:
        return "likes:" + " ".join(match.group(1).casefold().split())
    return ""


def middle_expiry(text: str, source_timestamp: float) -> float:
    """Expire a dated event after its day; otherwise give it a 30-day lifetime."""
    default = source_timestamp + MIDDLE_LIFETIME_DAYS * 86400
    if not _EVENT.search(text):
        return default
    source = datetime.fromtimestamp(source_timestamp).astimezone()
    target = None
    if re.search(r"\btomorrow\b", text, re.I):
        target = source.date() + timedelta(days=1)
    else:
        match = _ON_DATE.search(text)
        if match:
            try:
                target = datetime.fromisoformat(match.group(1)).date()
            except ValueError:
                pass
        if target is None:
            match = _WEEKDAY.search(text)
            if match:
                weekday = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"].index(match.group(2).casefold())
                days = (weekday - source.weekday()) % 7
                if match.group(1) and match.group(1).casefold() == "next":
                    days = days + 7 if days else 7
                target = source.date() + timedelta(days=days)
    if target is None:
        return default
    end_of_day = datetime.combine(target + timedelta(days=1), datetime.min.time(), source.tzinfo).timestamp()
    return end_of_day if end_of_day > source_timestamp else default


def is_active(metadata: dict | None, now: float | None = None) -> bool:
    meta = metadata or {}
    current = time.time() if now is None else now
    return not meta.get("superseded_by") and meta.get("expires_at", current + 1) > current
