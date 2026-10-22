"""A small, query-focused view of memories for the model prompt.

The source records in Chroma are never shortened or deleted here.
"""

import re

from blob.memory.lifecycle import topic_key


MEMORY_CONTEXT_CHARS = 8000
RECALL_CONTEXT_CHARS = 12000
FACT_CHARS = 400
EPISODE_CHARS = 1100
RECALL_EPISODE_CHARS = 1800
STOPWORDS = {"about", "from", "have", "that", "them", "their", "this", "what", "when", "where", "which", "with", "would", "your"}


def current_profile_episode(text: str, current: dict[str, str]) -> str:
    """Omit superseded naming declarations from ordinary recall, not the archive."""
    if not current or not text.startswith("User: "):
        return text
    user = text.removeprefix("User: ").partition("\nBlob: ")[0]
    normalize = lambda value: " ".join(value.casefold().rstrip(".!? ").split())
    sentences = re.split(r"(?<=[.!?])\s+|\n+|,\s+(?=I\s+(?:have|am|will|need|want)\b)", user)
    kept = [sentence for sentence in sentences if topic_key(sentence) not in current or
            normalize(sentence) == normalize(current[topic_key(sentence)])]
    if len(kept) == len(sentences):
        return text
    if not any(sentence.strip() for sentence in kept):
        return ""
    # An old reply may also repeat the superseded name. Keep only surviving
    # user evidence when a declaration was removed from this episode.
    return "User: " + "\n".join(kept)


def _excerpt(text: str, limit: int, query: str) -> str:
    if limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    if limit == 1:
        return text[:limit]
    terms = [term for term in re.findall(r"\w+", query.casefold()) if len(term) >= 4 and term not in STOPWORDS]
    lowered = text.casefold()
    positions = [lowered.find(term) for term in terms if term in lowered]
    start = max(0, min(positions) - limit // 3) if positions else 0
    start = min(start, len(text) - limit)
    # Reserve room for ellipses so the resulting view never exceeds the limit.
    prefix = "…" if start else ""
    suffix = "…" if start + limit < len(text) else ""
    return prefix + text[start:start + limit - len(prefix) - len(suffix)] + suffix


def _episode_view(text: str, limit: int, query: str, user_only: bool) -> str:
    if limit <= 6:
        return _excerpt(text, limit, query)
    user, separator, reply = text.partition("\nBlob: ")
    if not separator or user_only:
        if user.startswith("User: "):
            return "User: " + _excerpt(user.removeprefix("User: "), max(0, limit - 6), query)
        return _excerpt(user, limit, query)
    user_limit = min(len(user), max(limit * 3 // 4, limit - len(reply) - len(separator)))
    if user.startswith("User: "):
        user_view = "User: " + _excerpt(user.removeprefix("User: "), max(0, user_limit - 6), query)
    else:
        user_view = _excerpt(user, user_limit, query)
    reply_limit = limit - len(user_view) - len(separator)
    if reply_limit <= 0:
        return user_view
    return user_view + separator + _excerpt(reply, reply_limit, query)


def build_memory_view(facts: list[str], episodes: list[str], query: str, user_only: bool = False,
                      recall_mode: bool | None = None) -> tuple[str, str]:
    """Keep the most relevant records within a bounded prompt budget."""
    if recall_mode is None:
        recall_mode = user_only
    budget = RECALL_CONTEXT_CHARS if recall_mode else MEMORY_CONTEXT_CHARS
    seen = set()
    fact_views = []
    fact_budget = min(2000, budget)
    fact_used = 0
    for fact in facts:
        key = " ".join(fact.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        room = fact_budget - fact_used - len(fact_views)
        if room <= 0:
            break
        view = _excerpt(fact, min(FACT_CHARS, room), query)
        fact_views.append(view)
        fact_used += len(view)
    fact_text = "\n".join(fact_views)

    seen.clear()
    episode_views = []
    episode_budget = budget - len(fact_text)
    per_episode = RECALL_EPISODE_CHARS if recall_mode else EPISODE_CHARS
    episode_used = 0
    for episode in episodes:
        key = " ".join(episode.casefold().split())
        if key in seen:
            continue
        seen.add(key)
        room = episode_budget - episode_used - len(episode_views)
        if room <= 0:
            break
        view = _episode_view(episode, min(per_episode, room), query, user_only)
        episode_views.append(view)
        episode_used += len(view)
    return fact_text or "None", "\n".join(episode_views) or "None"
