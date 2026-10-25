"""Deterministic relevance matching using only the current user's request.

Discovery supplies candidates; the registry still enforces argument contracts,
request authority, disabled tools, command policy and privacy at execution.
"""

import re

ACTION = re.compile(r"\b(?:run|execute|show|check|list|find|search|locate|get|display|inspect|read)\b", re.I)
EXPLANATION = re.compile(r"^\s*(?:please\s+)?(?:explain|describe|teach|what\s+(?:is|are)|how\s+(?:does|do))\b", re.I)
NEGATED = re.compile(r"\b(?:don't|do not|never|without|avoid)\s+(?:\w+\s+){0,2}(?:run|execute|use|check|search|read)\b", re.I)
STOP_WORDS = frozenset("a an and are as at by can check current display execute file files find for from get how i in is it list local me my of on or please read run search show the this to tool tools use what with you your".split())


def normalized(value):
    return " ".join(re.findall(r"[^\W_]+", value.casefold()))


def contains(request, phrase):
    phrase = normalized(phrase)
    return bool(phrase and f" {phrase} " in f" {request} ")


def keywords(value):
    return {word[:-1] if len(word) > 4 and word.endswith("s") else word
            for word in normalized(value).split() if word not in STOP_WORDS}


def discover(skills, request, *, disabled=()):
    """Return ordered installed-tool candidates with inspectable match reasons."""
    from blob.skills.command_skill import CommandSkill

    if EXPLANATION.search(request) or NEGATED.search(request):
        return []
    text = normalized(request)
    matches = []
    for name, skill in sorted(skills.items()):
        if not isinstance(skill, CommandSkill) or name in disabled or not skill.model_callable:
            continue
        definition, tool = skill.definition, skill.tool
        reason, score = None, 0
        if contains(text, name) or contains(text, definition.slug):
            reason, score = "name", 100
        else:
            for kind, phrases, weight in (
                ("example", (*tool.examples, *definition.examples), 90),
                ("trigger", (*tool.triggers, *definition.triggers), 80),
            ):
                for phrase in phrases:
                    # Generic phrases such as 'search for' must have a topic.
                    if (contains(text, phrase) and keywords(phrase) and
                            (len(normalized(phrase).split()) > 1 or ACTION.search(request))):
                        reason, score = kind, weight
                        break
                if reason:
                    break
            if not reason and ACTION.search(request):
                overlap = keywords(request) & keywords(tool.description + " " + definition.description)
                if len(overlap) >= 2:
                    reason, score = "description", 50 + min(len(overlap), 10)
        if reason:
            matches.append({"name": name, "reason": reason, "score": score})
    return sorted(matches, key=lambda item: (-item["score"], item["name"]))
