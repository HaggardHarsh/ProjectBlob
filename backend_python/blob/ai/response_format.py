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


def correction_messages(messages):
    corrected = list(messages)
    if corrected and corrected[0].get("role") == "system":
        corrected[0] = {**corrected[0], "content": corrected[0]["content"] + "\n\n" + FORMAT_CORRECTION}
    else:
        corrected.insert(0, {"role": "system", "content": FORMAT_CORRECTION})
    return corrected
