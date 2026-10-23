"""A conservative size limit for the text sent in one model request.

UTF-8 bytes are used as a conservative, tokenizer-independent prompt budget.
This is not an exact token count, so the limit leaves room for chat-template
tokens and the model's reply.
"""

import json
import re

DEFAULT_MAX_PROMPT_BYTES = 32_000
MESSAGE_OVERHEAD_BYTES = 64
IMAGE_BUDGET_BYTES = 4096  # Reserve model context for each bounded image, separately from base64 transport.
OMITTED_CONTEXT = "\n[Additional historical context omitted to fit the prompt.]"
EVIDENCE_EXCERPT = "\n[Evidence excerpt: some content omitted to fit the reply.]\n"
READ_ONLY_TOOLS = {"web_search", "web_read", "browser", "file_search", "git_status", "shell_command", "weather"}
TOOL_OBSERVATION = re.compile(r"^(\[Observation\] Tool '([^']+)' executed successfully\.\nResult: )")


class PromptMessages(list):
    """A wire-compatible message list with host-only request provenance."""

    def __init__(self, messages, *, current_request=None):
        super().__init__(messages)
        self.current_request = current_request


def compact_browser_snapshots(messages, *, native_only=False):
    """Keep the newest browser view and earlier action arguments, not stale refs.

    Other tool results, failures, user messages and source-page reads are kept.
    Both native tool messages and classic observations use this path.
    """
    tools, snapshots = {}, []
    for index, message in enumerate(messages):
        for call in message.get("tool_calls", ()):
            tools[call.get("id")] = call.get("function", {}).get("name")
        content = message.get("content")
        if not isinstance(content, str):
            continue
        prefix = ""
        if message.get("role") == "tool" and tools.get(message.get("tool_call_id")) == "blob_browser":
            pass
        elif not native_only and content.startswith("[Observation] Tool 'browser' executed successfully.\nResult: "):
            prefix, content = content.split("\nResult: ", 1)
            prefix += "\nResult: "
        else:
            continue
        try:
            wrapper = json.loads(content)
            view = json.loads(wrapper["output"]) if isinstance(wrapper.get("output"), str) else wrapper
            if not (view.get("untrusted_web_content") and "elements" in view and "url" in view):
                continue
        except (ValueError, TypeError, AttributeError):
            continue
        snapshots.append((index, prefix, wrapper, view))
    compacted = list(messages)
    for index, prefix, wrapper, view in snapshots[:-1]:
        summary = {key: view[key] for key in ("url", "title", "checked_at") if key in view}
        summary["note"] = "Earlier browser snapshot omitted. Its refs expired; use the newest snapshot. Action arguments remain in history."
        if wrapper is not view:
            wrapper = {**wrapper, "output": json.dumps(summary)}
        else:
            wrapper = summary
        compacted[index] = {**messages[index], "content": prefix + json.dumps(wrapper)}
    return compacted


def prompt_size_bytes(messages: list[dict]) -> int:
    def content_size(content):
        if content is None:
            return 0
        if isinstance(content, str):
            return len(content.encode("utf-8"))
        return sum(len(part.get("text", "").encode("utf-8")) if part.get("type") == "text"
                   else IMAGE_BUDGET_BYTES for part in content)
    return sum(content_size(message.get("content", "")) + MESSAGE_OVERHEAD_BYTES +
               (len(json.dumps(message["tool_calls"], ensure_ascii=False).encode("utf-8")) if message.get("tool_calls") else 0)
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


def _evidence_excerpt(text, max_bytes):
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    remaining = max_bytes - len(EVIDENCE_EXCERPT.encode("utf-8"))
    head = max(0, remaining // 2)
    tail = max(0, remaining - head)
    return (encoded[:head].decode("utf-8", errors="ignore") + EVIDENCE_EXCERPT +
            (encoded[-tail:].decode("utf-8", errors="ignore") if tail else ""))


def _shorten_evidence(output, max_bytes):
    """Keep structured source metadata and mark shortened evidence explicitly."""
    try:
        data = json.loads(output)
    except (ValueError, TypeError, RecursionError):
        return _evidence_excerpt(output, max_bytes)
    if not isinstance(data, dict):
        return _evidence_excerpt(output, max_bytes)

    def shorten(value, limit, depth=0):
        if depth >= 8:
            return value
        if isinstance(value, dict):
            return {key: (_evidence_excerpt(item, limit)
                          if key in {"text", "snippet", "body", "content"} and isinstance(item, str)
                          else shorten(item, limit, depth + 1)) for key, item in value.items()}
        if isinstance(value, list):
            return [shorten(item, max(128, limit // max(1, len(value))), depth + 1) for item in value]
        return value

    shortened = shorten(data, max_bytes)
    if shortened == data:
        return output
    shortened["truncated"] = True
    shortened["context_note"] = "Evidence excerpts; omitted content is not verified by this excerpt."
    return json.dumps(shortened, ensure_ascii=False)


def _evidence_messages(messages):
    calls = {}
    for index, message in enumerate(messages):
        for call in message.get("tool_calls", ()):
            calls[call.get("id")] = call.get("function", {}).get("name", "").removeprefix("blob_")
        content = message.get("content")
        if not isinstance(content, str):
            continue
        if message.get("role") == "tool":
            name = calls.get(message.get("tool_call_id"))
            if name not in READ_ONLY_TOOLS:
                continue
            try:
                wrapper = json.loads(content)
            except ValueError:
                continue
            if not isinstance(wrapper, dict) or wrapper.get("success") is not True or not isinstance(wrapper.get("output"), str):
                continue
            yield index, "", wrapper, wrapper["output"]
        elif message.get("role") == "user":
            match = TOOL_OBSERVATION.match(content)
            if match and match.group(2) in READ_ONLY_TOOLS:
                yield index, match.group(1), None, content[match.end():]
            elif content.startswith(("[Observation] Fresh public source", "[Observation] Fresh public web evidence")):
                prefix, separator, output = content.partition("\n")
                if separator:
                    yield index, prefix + separator, None, output


def _preferred_request(messages, current_index, current_request):
    latest = messages[current_index - 2:current_index] if current_index >= 2 else []
    if (len(latest) == 2 and latest[0].get("role") == "user" and
            latest[1].get("role") == "assistant" and not (
                isinstance(latest[0].get("content"), str) and
                latest[0]["content"].startswith("Historical background"))):
        return latest[0]
    return current_request


def fit_tool_messages(messages: list[dict], current_request: dict,
                      max_bytes: int = DEFAULT_MAX_PROMPT_BYTES) -> list[dict] | None:
    """Fit a growing tool loop without cutting user input or action receipts.

    Old history goes first. If evidence alone exceeds the budget, progressively
    excerpt successful read-only results, keeping their metadata and call pairs.
    Failed tools and tools that change state retain their full receipts.
    """
    current_index = next((i for i, item in enumerate(messages) if item is current_request), None)
    if current_index is None:
        raise ValueError("Current user request is missing from the prompt")
    working = [*messages[:current_index + 1], *compact_browser_snapshots(messages[current_index + 1:])]
    # A short follow-up needs its preceding exchange even when source results
    # grow. Excerpt those sources before sacrificing the question's referent.
    preferred = _preferred_request(working, current_index, current_request)
    fitted = fit_messages(working, preferred, max_bytes)
    if fitted is not None:
        return fitted
    candidates = [item for item in _evidence_messages(working) if item[0] > current_index]
    for limit in (2048, 1024, 512, 256, 128):
        for index, prefix, wrapper, output in candidates:
            shortened = _shorten_evidence(output, limit)
            content = (json.dumps({**wrapper, "output": shortened}, ensure_ascii=False)
                       if wrapper is not None else prefix + shortened)
            if len(content.encode("utf-8")) >= len(working[index]["content"].encode("utf-8")):
                continue
            working[index] = {**working[index], "content": content}
            fitted = fit_messages(working, preferred, max_bytes)
            if fitted is not None:
                return fitted
    # If the preceding exchange itself is too large, retain the actual current
    # request and all its receipts rather than forcing an unnecessary failure.
    return (fit_messages(messages, current_request, max_bytes) or
            fit_messages(working, current_request, max_bytes))


def tool_schema_size_bytes(tools):
    return len(json.dumps(tools, ensure_ascii=False).encode("utf-8")) if tools else 0


def fit_agent_messages(messages: list[dict], original_messages: list[dict],
                       max_bytes: int = DEFAULT_MAX_PROMPT_BYTES, *, reserve_bytes=0) -> list[dict] | None:
    """Trim history as a native tool loop grows, preserving the current turn.

    The application's original request fixes the boundary. Worker-added tool
    calls, action receipts and screen observations must never become disposable history.
    """
    original = getattr(original_messages, "current_request", None)
    if original is None:
        users = [item for item in original_messages if item.get("role") == "user"]
        original = users[-1] if users else None
        if (len(users) > 1 and isinstance(original.get("content"), str) and
                original["content"].startswith("[Observation] A fresh screen capture succeeded.")):
            original = users[-2]
    current = next((item for item in reversed(messages)
                    if original is not None and item.get("role") == "user" and
                    item.get("content") == original.get("content")), None)
    if current is None:
        compacted = compact_browser_snapshots(messages, native_only=True)
        return compacted if prompt_size_bytes(compacted) <= max_bytes else None
    current_index = next(i for i, item in enumerate(messages) if item is current)
    working = [*messages[:current_index + 1], *compact_browser_snapshots(messages[current_index + 1:])]
    if reserve_bytes:
        fitted = fit_messages(working, _preferred_request(working, current_index, current), max_bytes - reserve_bytes)
        if fitted is not None:
            return fitted
    return fit_tool_messages(working, current, max_bytes)


def is_context_limit_error(error):
    """Only structured input-size failures qualify for a smaller-request retry."""
    if getattr(error, "status_code", None) not in {400, 413, 422}:
        return False
    body = getattr(error, "body", None)
    if isinstance(body, dict) and isinstance(body.get("error"), dict):
        body = body["error"]
    code = getattr(error, "code", None) or (body.get("code") if isinstance(body, dict) else None)
    if isinstance(code, str) and code in {"context_length_exceeded", "context_window_exceeded", "max_context_length", "input_too_long"}:
        return True
    message = body.get("message", "") if isinstance(body, dict) else ""
    return isinstance(message, str) and bool(re.search(
        r"(?:context (?:length|window)|input (?:length|tokens?)).{0,100}(?:exceed|too (?:long|large))"
        r"|maximum context length", message, re.I))
