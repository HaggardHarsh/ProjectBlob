"""Keep provider serialization tokens out of replies and tool execution."""

import re

PROTOCOL_MARKER = re.compile(r"<\|(?:tool_|im_|start_header_id|end_header_id|eot_id|python_tag)", re.I)
FORMAT_CORRECTION = (
    "The previous completion contained invalid provider tool-serialization text and was discarded. "
    "It executed no actions. Continue the original user request using the actual conversation and tool receipts. "
    "Return ordinary answer text, or use the tool-call interface supplied by this conversation for a requested tool. "
    "Never print model control tokens, fictional tool calls, tool responses, or a simulated transcript. "
    "Do not repeat completed actions."
)
FORMAT_FAILURE = "The model returned malformed tool text, so I discarded that reply. Please try again."


def has_tool_protocol(text):
    return isinstance(text, str) and PROTOCOL_MARKER.search(text) is not None


def display_text(text):
    """Hide a corrupted transcript tail, including incomplete streamed markers."""
    match = PROTOCOL_MARKER.search(text)
    if match:
        text = text[:match.start()]
    return re.sub(r"<(\/?)\|emote>", r"<\1emote>", text, flags=re.I)


def correction_messages(messages):
    corrected = list(messages)
    if corrected and corrected[0].get("role") == "system":
        corrected[0] = {**corrected[0], "content": corrected[0]["content"] + "\n\n" + FORMAT_CORRECTION}
    else:
        corrected.insert(0, {"role": "system", "content": FORMAT_CORRECTION})
    return corrected
