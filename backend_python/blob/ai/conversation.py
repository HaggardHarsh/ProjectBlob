"""Resolve task closure and social acknowledgements before historical recall."""

import re


_CLOSURE = re.compile(
    r"(?:(?:no|nope|nah)(?: (?:thanks|thank you|not really))?|not really|"
    r"never ?mind|(?:please )?(?:skip|drop|leave|forget) (?:it|that)|"
    r"(?:please )?(?:don't|dont|do not) (?:do|continue|resume) (?:it|that)|"
    r"(?:i |we )?(?:don't|dont|do not) (?:need|want) (?:it|that)(?: anymore| any more)?|"
    r"(?:we're|we are|i'm|i am) (?:already )?done(?: with (?:it|that))?|"
    r"that's all|that is all|no need(?: for (?:it|that))?)"
    r"(?: (?:please|thanks|thank you))?"
)
_ACK = re.compile(
    r"(?:sure(?: thing)?|ok(?:ay)?|alright|all right|got it|sounds good|"
    r"cool|great|nice|fine|yep|yeah|yes|thanks|thank you|all good)"
    r"(?: (?:thanks|thank you|then))?"
)
_CELEBRATION = re.compile(r"(?:ya+y+|woo+|woo+hoo+)")


def conversation_reply(text, recent):
    """Return a local reply only for a whole-message closure/acknowledgement.

    Corrections with new instructions keep the ordinary task path. A short yes
    after the latest assistant question stays available to answer that question;
    an old question in retrieved history is never an outstanding offer.
    """
    if len(text) > 240 or text.lstrip().startswith("/"):
        return None
    normalized = re.sub(r"[^\w']+", " ", text.casefold().replace("’", "'")).strip()
    clauses = re.split(r"[.!?;,]+\s*", text.strip().casefold().replace("’", "'"))
    clauses = [re.sub(r"[^\w']+", " ", clause).strip() for clause in clauses if clause.strip()]
    if clauses and all(_CLOSURE.fullmatch(clause) for clause in clauses):
        return "Got it. I'll leave that there."
    if "?" in text:
        return None
    if _CELEBRATION.fullmatch(normalized):
        return "Yay!"
    if not (_ACK.fullmatch(normalized) or text.strip() in {"👍", "🙂", "😊"}):
        return None
    if normalized in {"thanks", "thank you"}:
        return "You're welcome."
    latest = next((item["content"] for item in reversed(recent) if item["role"] == "assistant"), "")
    if "?" in latest:
        return None
    return "Okay."
