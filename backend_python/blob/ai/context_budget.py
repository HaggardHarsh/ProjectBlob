"""A conservative size limit for the text sent in one model request.

UTF-8 bytes are used as a conservative, tokenizer-independent prompt budget.
This is not an exact token count, so the limit leaves room for chat-template
tokens and the model's reply.
"""

DEFAULT_MAX_PROMPT_BYTES = 32_000
MESSAGE_OVERHEAD_BYTES = 64
IMAGE_BUDGET_BYTES = 4096  # Reserve model context for each bounded image, separately from base64 transport.
OMITTED_CONTEXT = "\n[Additional historical context omitted to fit the prompt.]"


def prompt_size_bytes(messages: list[dict]) -> int:
    def content_size(content):
        if isinstance(content, str):
            return len(content.encode("utf-8"))
        return sum(len(part.get("text", "").encode("utf-8")) if part.get("type") == "text"
                   else IMAGE_BUDGET_BYTES for part in content)
    return sum(content_size(message.get("content", "")) + MESSAGE_OVERHEAD_BYTES
               for message in messages)


def _trim_context_lines(content: str, max_bytes: int) -> str:
    marker_size = len(OMITTED_CONTEXT.encode("utf-8"))
    if max_bytes < marker_size:
        return ""
    kept = []
    used = 0
    for line in content.splitlines(keepends=True):
        line_size = len(line.encode("utf-8"))
        if used + line_size + marker_size > max_bytes:
            break
        kept.append(line)
        used += line_size
    return "".join(kept).rstrip() + OMITTED_CONTEXT


def fit_messages(messages: list[dict], current_request: dict,
                 max_bytes: int = DEFAULT_MAX_PROMPT_BYTES) -> list[dict] | None:
    """Drop old turns, then trim background before the latest exchange.

    Return None if the essential messages cannot fit without silently cutting
    the user's latest message or a tool observation. Keep the latest exchange
    whenever it fits alongside those essentials, including across model routes.
    """
    current_index = next((i for i, item in enumerate(messages) if item is current_request), None)
    if current_index is None:
        raise ValueError("Current user request is missing from the prompt")
    working = [(i, dict(item)) for i, item in enumerate(messages)]
    while prompt_size_bytes([item for _, item in working]) > max_bytes:
        older = [i for i, _ in working if 1 < i < current_index]
        if not older:
            break
        if len(older) <= 2:
            # A short follow-up may depend entirely on this exchange. Prefer it
            # to retrieved background if the essential request leaves room.
            without_background = [item for i, item in working if not (
                i == 1 and isinstance(item.get("content"), str) and
                item["content"].startswith("Historical background"))]
            if prompt_size_bytes(without_background) <= max_bytes:
                break
        # Recent turns are stored in user/assistant pairs. Remove the oldest
        # complete pair so the remaining conversation stays in order.
        remove = set(older[:2])
        working = [(i, item) for i, item in working if i not in remove]

    fitted = [item for _, item in working]
    if prompt_size_bytes(fitted) <= max_bytes:
        return fitted
    background = next((item for i, item in working if i == 1 and
                       isinstance(item.get("content"), str) and
                       item["content"].startswith("Historical background")), None)
    if background is None:
        return None
    other_size = prompt_size_bytes(fitted) - len(background["content"].encode("utf-8"))
    remaining = max_bytes - other_size
    background["content"] = _trim_context_lines(background["content"], remaining)
    if background["content"] and prompt_size_bytes(fitted) <= max_bytes:
        return fitted
    # The latest request and tool observations matter more than old context.
    without_background = [item for item in fitted if item is not background]
    return without_background if prompt_size_bytes(without_background) <= max_bytes else None
