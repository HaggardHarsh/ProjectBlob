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

_SUPPORT_OFFER = re.compile(
    r"\b(?:i['’]m (?:(?:just|right|still|always) )*here|"
    r"(?:just|right|still|always) here|here (?:if|whenever|for you|with you|to listen)|"
    r"(?:want to|wanna) (?:vent|talk)|if you (?:want|feel like) (?:to )?(?:talk|vent|shar)\w*|"
    r"(?:sit|sitting|hang) (?:here |in |together )?(?:quiet|silence))", re.I)

_REASSURANCE_REQUEST = re.compile(
    r"\b(?:are you (?:still )?there|(?:can|could|may) i (?:vent|talk)|"
    r"(?:stay|sit) with me|(?:need|want|give me) reassurance|"
    r"tell me (?:you're|you are) here)\b", re.I)
_SAFETY_DISCLOSURE = re.compile(
    r"\b(?:suicid\w*|self[- ]?harm|(?:hurt|harm|kill|cut)\w* (?:myself|me|yourself)|"
    r"end (?:my|it all)|don't want to (?:live|be alive)|not safe|overdos\w*)\b", re.I)
_NO_QUESTIONS = re.compile(
    r"\b(?:no (?:\w+[- /]+){0,3}questions|without (?:any )?questions|"
    r"(?:don't|do not|stop) ask(?:ing)?(?: me)?(?: any)? questions)\b", re.I)


def requests_no_questions(user_text):
    return bool(_NO_QUESTIONS.search(user_text.replace("’", "'")))


def conversation_revision_reason(answer, recent, user_text):
    # Never revise safety-oriented replies merely to enforce a style preference.
    if (_SAFETY_DISCLOSURE.search(user_text.replace("’", "'")) or
            re.search(r"\b(?:safe|safety|emergency|crisis|suicid\w*)\b", answer, re.I)):
        return ""
    if requests_no_questions(user_text) and "?" in answer:
        return "The user explicitly requested no questions, but the draft asks one."
    if repeats_support_offer(answer, recent, user_text):
        return "The draft repeats an offer to listen even though the user is already sharing."
    return ""


def repeats_support_offer(answer, recent, user_text):
    """Narrow style check, never a safety classifier or general phrase ban."""
    return bool(
        support_loop_guidance(recent) and _SUPPORT_OFFER.search(answer)
        and not _REASSURANCE_REQUEST.search(user_text.replace("’", "'"))
        and not _SAFETY_DISCLOSURE.search(user_text.replace("’", "'"))
        and not re.search(r"\b(?:safe|safety|emergency|crisis|suicid\w*)\b", answer, re.I)
    )


def support_loop_guidance(recent):
    """Remind the model of exhausted support offers, without labelling user moods.

    Only recent assistant wording triggers this note. It does not rewrite user
    messages, remove history, or block an explicit request for reassurance.
    """
    replies = [item["content"] for item in recent if item["role"] == "assistant"][-3:]
    if not any(_SUPPORT_OFFER.search(reply) for reply in replies):
        return ""
    return (
        "\n## This turn: move past the support offer\n"
        "You already offered listening or quiet company in recent replies. The user "
        "is already in the conversation. Do not repeat that offer, even in different "
        "words, or end with another invitation. Engage with the specific thing they "
        "just said. Add an observation, answer, or one relevant question instead of "
        "another generic sympathy sentence. Don't enumerate their hardships. "
        "If they explicitly ask for reassurance, answer that request warmly. "
        "Follow their latest topic and boundaries; do not assume they are still sad.\n"
    )


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
