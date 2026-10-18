"""Recognize public AI-product lookups without searching personal conversation."""

import re

PRODUCT = re.compile(r"\b(?:gemini|claude|gpt|grok|deepseek|qwen|nemotron|llama|mistral|chatgpt)(?=\b|\d)(?:[- ]*\d[\w.-]*)?", re.I)
QUESTION = re.compile(r"^(?:(?:hey|bro|dude|please)[, ]+)*(?:what|who|when|where|how|is|are|does|do|can|could|tell me|explain|compare|review)\b", re.I)
FOLLOWUP = re.compile(r"\b(?:is it|is that|is this|are they|how good|how much|what about|worth it|better|pricing|benchmarks?|limitations?)\b", re.I)
PERSONAL = re.compile(r"\b(?:remember|remind|my|our|saved|forget|memory)\b", re.I)
STOP = set("a an the is are was were what who how when where why it its that this they their for with on at in to and or vs versus than good better best worth pricing price benchmarks model models release released from my our does do can capabilities about please official limitations evaluation ai llm chatbot latest current new recent version versions".split())
OFFICIAL_DOMAINS = ("ai.google.dev", "deepmind.google", "blog.google", "cloud.google.com", "openai.com",
                    "anthropic.com", "claude.com", "x.ai", "deepseek.com", "qwen.ai", "nvidia.com",
                    "llama.com", "mistral.ai")
TRAVEL_TOPIC = re.compile(r"\b(?:flights?|airfares?|trains?|buses|bus|hotels?|tickets?|seats?)\b", re.I)
TRAVEL_LOOKUP = re.compile(
    r"^\s*(?:(?:hey|please)[, ]+)*(?:(?:can|could|would|will)\s+(?:you|u)\s+)?"
    r"(?:please\s+)?(?:check|find|search|see\s+(?:if|whether)|look\s+(?:up|for)|show\s+me)\b", re.I)
TRAVEL_QUESTION = re.compile(
    r"^\s*(?:(?:are|is)\s+(?:there|any)\b|(?:any|what|which)\s+(?:flights?|trains?|buses|hotels?|tickets?|seats?)\b)", re.I)
DECLINED_WEB = re.compile(
    r"\b(?:don't|dont|do not|not|never|stop|without|no more)\s+"
    r"(?:(?:want|need)\s+(?:you\s+)?to\s+)?"
    r"(?:(?:do|any|more|further|another|the|a|web|internet|online|browser)\s+){0,4}"
    r"(?:search(?:es|ing)?|brows(?:e|ing)|look(?:ing)?\s+up|(?:check|use|using)\s+(?:the\s+)?(?:web|internet|browser|online))\b", re.I)


def declines_web_lookup(text):
    return bool(DECLINED_WEB.search(text.replace("’", "'")))


def live_travel_request(text):
    """A current travel enquiry is public lookup intent without a 'web' keyword."""
    if re.search(r"\b(?:remember|recall|saved|stored|downloaded|files?|folders?|documents?)\b", text, re.I):
        return False
    return bool(TRAVEL_TOPIC.search(text) and (TRAVEL_LOOKUP.search(text) or TRAVEL_QUESTION.search(text)))


def product_names(text):
    names = []
    for match in PRODUCT.finditer(text):
        extra = []
        for word in re.findall(r"[\w.-]+", text[match.end():])[:2]:
            if word.lower() in STOP or PRODUCT.fullmatch(word):
                break
            extra.append(word)
        names.append(" ".join([match.group(), *extra])[:100])
    return names


def mentions_requested_product(query, text):
    normalize = lambda value: re.sub(r"[^a-z0-9]", "", value.lower())
    return any(normalize(name) in normalize(text) for name in product_names(query))


def live_product_query(text, recent=()):
    """Use the user's product name and requested topic, never old assistant claims."""
    if PERSONAL.search(text) or text.strip().startswith("/"):
        return None
    subject_text = text
    if not PRODUCT.search(text):
        if not FOLLOWUP.search(text):
            return None
        for turn in reversed(list(recent)):
            if turn.get("role") != "user":
                continue
            previous = turn.get("content", "")
            if PERSONAL.search(previous):
                return None
            if PRODUCT.search(previous):
                subject_text = previous
                break
            if not FOLLOWUP.search(previous):
                return None
        else:
            return None
    elif not QUESTION.search(text.strip()):
        if (not PRODUCT.match(text.strip()) or len(text.split()) > 5 or
                re.search(r"\b(?:is|are|was|were|feels|seems|helps)\b", text, re.I)):
            return None
    subjects = product_names(subject_text)
    if not subjects:
        return None
    topic = ("official pricing availability" if re.search(r"\b(?:price|pricing|cost|how much|available|availability)\b", text, re.I) else
             "benchmarks capabilities limitations evaluation" if re.search(r"\b(?:good|better|best|worth|benchmarks?|compare|review)\b", text, re.I) else
             "official model release capabilities")
    return (" vs ".join(subjects[:3]) + " " + topic)[:500]


def requested_system_tools(text):
    """Public model questions do not authorize shell commands or reminder checks."""
    tools = set()
    if re.search(r"\b(?:git|repo(?:sitory)?)\b", text, re.I):
        tools.add("git_status")
    if (re.search(r"\b(?:run|execute)\b.{0,45}\b(?:command|shell|terminal|echo|ls|cat|grep|find|git|df|free|uname|python)\b", text, re.I) or
            re.search(r"\b(?:shell|terminal)\s+command\b|\b(?:disk|memory|system)\s+(?:usage|space|info)\b", text, re.I) or
            re.match(r"\s*(?:ls|cat|grep|find|git|df|free|uname|python\s+--version)\b", text, re.I)):
        tools.add("shell_command")
    return tools
