"""Keep provider serialization tokens out of replies and tool execution."""

import json
import re
from blob.terminal import terminal_text

PROTOCOL_MARKER = re.compile(r"<\|(?!emote>)[a-z_]", re.I)
TEXT_TOOL_MARKER = re.compile(r"```tool_call\b|<tool_call\b|[\"'](?:tool|tool_calls|function_call)[\"']\s*:", re.I)
FUNCTION_ENVELOPE = re.compile(r"[\"'](?:name|function)[\"']\s*:", re.I)
ARGUMENT_MARKER = re.compile(r"[\"'](?:args|arguments)[\"']\s*:", re.I)
FORMAT_CORRECTION = (
    "The previous completion contained malformed tool-request text and was discarded. "
    "It executed no actions. Continue the original user request using the actual conversation and tool receipts. "
    "Return ordinary answer text, or use the tool-call interface supplied by this conversation for a requested tool. "
    "Never print model control tokens, fictional tool calls, tool responses, standalone arguments, "
    "multiple JSON requests, or a simulated transcript. Match the supplied tool interface exactly. "
    "Do not repeat completed actions."
)
FORMAT_FAILURE = "The model returned malformed tool text, so I discarded that reply. Please try again."
EMPTY_REPLY_CORRECTION = (
    "The previous completion contained no readable reply after presentation tags were removed. "
    "Answer the latest user message in ordinary visible text using the conversation and existing tool results. "
    "If the user gave a short acceptance, respond to the latest assistant offer; ask a brief clarification "
    "if that offer leaves multiple choices. Do not output only reasoning or animation tags. "
    "Do not call tools, repeat completed actions, or claim an action without a successful tool result. "
    "Do not mention this correction."
)

EMOTE_NAMES = "IDLE|HAPPY|SAD|ANGRY|CONFUSED|THINKING|WORRIED|CELEBRATE|EXCITED|TIRED|OFFER_COFFEE|SHY|SLEEPING|EATING|PROUD|PLAYFUL|WORKING|DEEP_THINKING|LISTENING|SHOCKED|MELTING|ERROR|SUCCESS|WAITING"
EMOTE_ALIASES = {"AMUSED": "PLAYFUL"}
EMOTE_VALUES = EMOTE_NAMES + "|" + "|".join(EMOTE_ALIASES)
# A bare mood is a control only when followed by an emote delimiter.
EMOTE_MARKER = re.compile(
    rf"<emote\s*>\s*([^<]*?)\s*</emote\s*>|\(({EMOTE_VALUES})\)"
    rf"|(?<!\w)({EMOTE_VALUES})\s*</emote\s*>",
    re.IGNORECASE | re.DOTALL)
EMOTE_OPEN = re.compile(
    rf"(?<!\w)(?:{EMOTE_VALUES})\s*</(?:e|em|emo|emot|emote)?\s*$"
    r"|<emote\s*>.*$|</?emote\b[^>]*$|</?(?:e|em|emo|emot)\s*$",
    re.IGNORECASE | re.DOTALL)
EMOTE_CLOSE = re.compile(r"</emote\s*>", re.IGNORECASE)
REASONING_BLOCK = re.compile(r"<(think|thinking|analysis)>.*?</\1>", re.IGNORECASE | re.DOTALL)
REASONING_OPEN = re.compile(r"<(?:think|thinking|analysis)>.*$", re.IGNORECASE | re.DOTALL)
REASONING_CLOSE = re.compile(r"</(?:think|thinking|analysis)>", re.IGNORECASE)


def strip_reasoning(text):
    text = REASONING_BLOCK.sub("", text)
    text = REASONING_OPEN.sub("", text)
    return REASONING_CLOSE.sub("", text).strip()


def has_tool_protocol(text, *, valid_text_call=False, search_arguments=False):
    """Detect simulated calls; classic callers may exempt a fully parsed request.

    Provider control tokens are always invalid. Parameter-only search JSON is
    ambiguous in ordinary conversation, so reject it only during a live lookup.
    This check never extracts or executes a call from prose or multiple objects.
    """
    if not isinstance(text, str):
        return False
    if PROTOCOL_MARKER.search(text):
        return True
    if valid_text_call:
        return False
    if FUNCTION_ENVELOPE.search(text) and ARGUMENT_MARKER.search(text):
        return True
    if TEXT_TOOL_MARKER.search(text):
        if re.search(r"```tool_call\b|<tool_call\b|[\"'](?:tool_calls|function_call)[\"']\s*:", text, re.I):
            return True
        if ARGUMENT_MARKER.search(text):
            return True
        try:
            data = json.loads(text)
        except (ValueError, TypeError):
            pass
        else:
            if isinstance(data, dict) and set(data) == {"tool"}:
                return True
    if search_arguments:
        candidate = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.I)
        try:
            data = json.loads(candidate)
        except (ValueError, TypeError):
            return False
        if isinstance(data, dict) and isinstance(data.get("query"), str) and set(data) <= {"query", "count", "freshness"}:
            return True
    return False


def display_text(text):
    """Hide a corrupted transcript tail, including incomplete streamed markers."""
    match = PROTOCOL_MARKER.search(text)
    if match:
        text = text[:match.start()]
    return terminal_text(re.sub(r"<(\/?)\|emote>", r"<\1emote>", text, flags=re.I))


def strip_emotes(text):
    """Hide complete markers and broken delimiters without removing ordinary mood words."""
    text = EMOTE_MARKER.sub("", text)
    text = EMOTE_OPEN.sub("", text)
    return EMOTE_CLOSE.sub("", text).strip()


def extract_emote(text):
    """Recover an animation even when the model omits its opening tag."""
    text = display_text(text)
    matches = list(EMOTE_MARKER.finditer(text))
    value = next((value for value in matches[-1].groups() if value), "IDLE") if matches else "IDLE"
    emote = value.strip().upper()
    emote = EMOTE_ALIASES.get(emote, emote)
    if emote not in EMOTE_NAMES.split("|"):
        emote = "IDLE"
    return emote, strip_emotes(text)


def visible_reply_text(text):
    """Use the same presentation rules to detect a tag-only final answer."""
    text = display_text(strip_reasoning(text or ""))
    return strip_emotes(text)


def correction_messages(messages, correction=FORMAT_CORRECTION):
    corrected = list(messages)
    if corrected and corrected[0].get("role") == "system":
        corrected[0] = {**corrected[0], "content": corrected[0]["content"] + "\n\n" + correction}
    else:
        corrected.insert(0, {"role": "system", "content": correction})
    return corrected
