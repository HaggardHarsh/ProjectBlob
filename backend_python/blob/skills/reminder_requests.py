"""Parse unambiguous relative reminders from the current user request only."""

import re


_NUMBERS = dict(zip(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split(),
    range(20),
))
_NUMBERS.update(twenty=20, thirty=30, forty=40, fifty=50, sixty=60, seventy=70, eighty=80, ninety=90)
_NUMBERS.update(a=1, an=1, half=0.5)
_AMOUNT = r"-?\d+(?:\.\d+)?|" + "|".join(_NUMBERS)
_DURATION = rf"(?P<amount>{_AMOUNT})\s*(?:an?\s+)?(?P<unit>seconds?|secs?|s|minutes?|mins?|m|hours?|hrs?|h|days?|d)\b"
_REQUEST = re.compile(
    r"^(?:(?:hey\s+)?blob[,\s]+)?"
    r"(?:(?:please|(?:can|could|would|will) you(?: please)?)\s+)?"
    r"(?:remind me|(?:set|start|create|add)(?: me)? (?:a |an )?(?:reminder|timer|alarm))\s+"
    r"(?P<body>.+)$", re.I,
)
_TIME_FIRST = re.compile(
    rf"(?:in|after|for)\s+{_DURATION}(?:\s+from now)?(?:\s+(?:to|about)\s+(?P<topic>.+))?", re.I,
)
_TOPIC_FIRST = re.compile(
    rf"(?:to|about)\s+(?P<topic>.+?)\s+(?:in|after)\s+{_DURATION}(?:\s+from now)?", re.I,
)
_COMPLEX = re.compile(
    r"\b(?:then|every|repeat|repeating|instead|actually|unless|if|don't|do not)\b"
    r"|\b(?:and|or)\s+(?:remind|set|start|create|add|cancel|list|show|snooze)\b", re.I,
)


def relative_reminder_request(text: str) -> dict | None:
    """Leave calendar, conditional and multi-action requests to normal routing.

    Return even invalid numeric delays so the reminder tool rejects them instead
    of letting a model invent a replacement time. Never consult chat history.
    """
    request = _REQUEST.fullmatch(text.strip())
    if request is None:
        return None
    body = request["body"].strip().rstrip(".!?")
    body = re.sub(r",?\s+please$", "", body, flags=re.I)
    if _COMPLEX.search(body):
        return None
    match = _TIME_FIRST.fullmatch(body) or _TOPIC_FIRST.fullmatch(body)
    if match is None:
        return None
    topic = match["topic"]
    if topic and re.search(rf"\b(?:in|after)\s+{_DURATION}", topic, re.I):
        return None
    amount = match["amount"].casefold()
    value = _NUMBERS[amount] if amount in _NUMBERS else float(amount)
    unit = match["unit"].casefold()
    minutes = value * (1 / 60 if unit.startswith("s") else
                       60 if unit.startswith("h") else 1440 if unit.startswith("d") else 1)
    return {"action": "set", "minutes": minutes,
            "message": topic.strip() if topic else text.strip()}
