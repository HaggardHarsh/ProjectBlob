import re
import logging
from datetime import datetime, timedelta
from blob.terminal import terminal_text

logger = logging.getLogger(__name__)

_EVENT = r"presentation|exam|test|meeting|appointment|interview|deadline|flight|trip"
PERSONAL_PLAN_TOPIC = re.compile(
    rf"\b(?:{_EVENT}|plans?|schedule|tomorrow|next week)\b", re.IGNORECASE
)
PERSONAL_EVENT_CLAIM = re.compile(
    rf"\b(?:your\s+(?P<possessive>{_EVENT})s?\s+(?:is|starts|happens|takes place)\b"
    rf"|you\s+have\s+(?:(?:a|an|the)\s+)?(?P<have>{_EVENT})s?\b)",
    re.IGNORECASE,
)
NEGATED_EVENT = re.compile(r"\b(?:no|not|never|don't|do not|without)\b", re.IGNORECASE)
CANCELLED_EVENT = re.compile(r"\b(?:cancelled|canceled)\b", re.IGNORECASE)
UNCERTAIN_CLAIM = re.compile(r"\b(?:not sure|don't know|do not know|unsure|might|maybe)\b", re.IGNORECASE)
USER_EVENT_ASSERTION = re.compile(
    r"\b(?:I\s+(?:have|will have|am giving|am attending|booked|scheduled)|"
    r"we\s+have|my(?:\s+\w+){0,3}|our(?:\s+\w+){0,3})\b",
    re.IGNORECASE,
)
TOMORROW = re.compile(r"\btomorrow\b", re.IGNORECASE)
TODAY = re.compile(r"\btoday\b", re.IGNORECASE)
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")


def _event_date(statement: str, said_on):
    if TOMORROW.search(statement):
        return said_on + timedelta(days=1)
    if TODAY.search(statement):
        return said_on
    match = ISO_DATE.search(statement)
    if match:
        try:
            return datetime.fromisoformat(match.group()).date()
        except ValueError:
            return None
    return None


def unsupported_personal_event_claim(
    reply: str, user_evidence: list[str | tuple[str, float | None]]
) -> bool:
    """Catch a definite personal event claim unsupported by newest-first user words."""
    reply_sentences = re.split(r"(?<=[.!?])\s+|\n+", reply)
    today = datetime.now().astimezone().date()
    for match in PERSONAL_EVENT_CLAIM.finditer(reply):
        reply_sentence = next((part for part in reply_sentences if match.group() in part), reply)
        local_start = reply_sentence.find(match.group())
        if reply_sentence.strip().endswith("?") or UNCERTAIN_CLAIM.search(reply_sentence[:local_start]):
            continue
        claims_tomorrow = bool(TOMORROW.search(reply_sentence[local_start + len(match.group()):]))
        event = (match.group("possessive") or match.group("have")).casefold()
        event_pattern = re.compile(rf"\b{re.escape(event)}s?\b", re.IGNORECASE)
        supported = False
        for evidence in user_evidence:
            statement, timestamp = evidence if isinstance(evidence, tuple) else (evidence, None)
            said_on = (datetime.fromtimestamp(timestamp).astimezone().date()
                       if isinstance(timestamp, (int, float)) else today)
            for sentence in reversed(re.split(r"(?<=[.!?])\s+|\n+", statement)):
                event_match = event_pattern.search(sentence)
                if event_match is None or sentence.strip().endswith("?"):
                    continue
                before_event = sentence[:event_match.start()]
                if NEGATED_EVENT.search(before_event) or CANCELLED_EVENT.search(sentence[event_match.end():]):
                    break
                if USER_EVENT_ASSERTION.search(before_event):
                    supported = (not claims_tomorrow or
                                 _event_date(sentence, said_on) == today + timedelta(days=1))
                    break
            else:
                continue
            break
        if not supported:
            return True
    return False

class GuardrailsEngine:
    def __init__(self, config):
        self.config = config
        
    def sanitize_input(self, text: str) -> str:
        # Sharing consent is enforced by PrivacyControls. Preserve user-selected
        # content; this is control-character normalization, not PII detection.
        return terminal_text(text)
        
    def filter_output(self, text: str) -> str:
        text = terminal_text(text)
        for name in ("nebius_api_key", "brave_search_api_key"):
            secret = getattr(self.config, name, "")
            if isinstance(secret, str) and len(secret) >= 8:
                text = text.replace(secret, "[credential redacted]")
        return text

    def preview_buffer_chars(self):
        return max([32, *(len(value) for value in (
            getattr(self.config, "nebius_api_key", ""), getattr(self.config, "brave_search_api_key", ""))
            if isinstance(value, str))])
