"""Request-scoped tool authority, independent of model and retrieved instructions."""

from contextvars import ContextVar
from dataclasses import dataclass, field
import json
import re

from blob.ai.web_grounding import declines_web_lookup, live_product_query, live_travel_request, news_followup_query, requested_system_tools
from blob.ai.response_format import FORMAT_FAILURE
from blob.skills.web_network import public_url
from blob.skills.discovery import discover


MODEL_POLICY = ContextVar("blob_model_tool_policy", default=None)
URL = re.compile(r"https?://[^\s<>\"\[\]()【】《》“”‘’]+", re.I)
EXPLICIT_WEB = re.compile(r"https?://|\b(?:web|internet|online|website|browser)\b", re.I)
PUBLIC_REQUEST = re.compile(r"\b(?:latest|recent|today.s|news|availability)\b|"
    r"\bcurrent\s+(?:version|release|price|pricing|status|president|prime minister|ceo|score|rate|exchange|schedule)\b", re.I)
FOLLOWUP = re.compile(
    r"^\s*(?:what\s+(?:about|does|is|are)|how\s+(?:about|much|good)|"
    r"(?:is|are|does|do|can|could)\s+(?:it|that|this|those|they)|"
    r"(?:please\s+)?(?:read|open|check|compare|verify|search|look\s+up)\b|"
    r"(?:tell|show)\s+me\s+more\b|more\s+(?:details?|information)\b|"
    r"and\s+(?:on|for)\b|(?:make|change)\s+that\b)", re.I)
REFERENT = re.compile(r"\b(?:it|its|that|this|those|they|them|their|there|more|first|second|next|again)\b", re.I)
DATE_FOLLOWUP = re.compile(
    r"\s*(?:what about|how about|and(?: on| for)?|on|for)\s+"
    r"(?:(?:the|on|for|instead|tomorrow|today|next|week|monday|tuesday|wednesday|thursday|friday|saturday|sunday|"
    r"jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|"
    r"oct(?:ober)?|nov(?:ember)?|dec(?:ember)?|\d{1,4}(?:st|nd|rd|th)?)\b|[-/.,?!\s])+", re.I)


def normalized(value):
    return " ".join(re.findall(r"\w+", value.casefold()))


@dataclass
class ModelToolPolicy:
    request: str
    allowed: set = field(default_factory=set)
    query: str | None = None
    urls: set = field(default_factory=set)
    verified: dict = field(default_factory=dict)
    public_input: str = ""
    browser_texts: list = field(default_factory=list)
    read_results: dict = field(default_factory=dict)
    active_project: str | None = None

    @classmethod
    def for_request(cls, request, registry, *, required_tool=None, files=False, previous=None, recent=()):
        policy = cls(request)
        controls = getattr(registry, "controls", None)
        if controls:
            policy.active_project = controls.state.get("active_project")
        policy.allowed.update(requested_system_tools(request))
        if required_tool:
            policy.allowed.add(required_tool)
        if files:
            policy.allowed.add("file_search")
        product = live_product_query(request, recent)
        news = news_followup_query(request, recent)
        declined = declines_web_lookup(request)
        public = not declined and required_tool is None and bool(news or product or live_travel_request(request) or EXPLICIT_WEB.search(request) or (
            PUBLIC_REQUEST.search(request) and not requested_system_tools(request) and
            not re.search(r"\b(?:my|our|remember|saved|forget)\b", request, re.I)))
        referenced_followup = FOLLOWUP.search(request) and (REFERENT.search(request) or (
            previous and live_travel_request(previous.public_input) and DATE_FOLLOWUP.fullmatch(request)))
        followup = bool(previous and not declined and (product or referenced_followup) and
                        not re.search(r"\b(?:my|our|remember|saved|forget)\b", request, re.I))
        if public or (followup and required_tool is None):
            policy.allowed.update({"web_search", "web_read", "browser"})
            # The host chooses the outbound search text. A model cannot append
            # recalled private facts or encoded data to a search query.
            policy.query = news or product or (request if public else previous.query + " " + request)
            policy.public_input = ((news or request) + " " + (previous.public_input if followup else ""))[:4000]
            if followup:
                policy.urls.update(previous.urls)
        for url in URL.findall(request):
            try:
                policy.urls.add(public_url(url.rstrip(".,;!?")))
            except ValueError:
                pass
        policy.allowed.update(match["name"] for match in discover(
            registry.skills, request, disabled=controls.state["disabled_skills"] if controls else ()))
        return policy

    def arguments(self, name, args):
        if name not in self.allowed:
            raise ValueError("That tool was not authorized by the user's request and was not executed.")
        args = dict(args)
        if "project" in args and args["project"] != self.active_project and args["project"] not in self.request:
            raise ValueError("Use the active project or a project path supplied in the user's current request.")
        if name == "shell_command":
            command = args.get("command", "").strip()
            diagnostics = set()
            if re.search(r"\bdisk\b.*\b(?:usage|space)\b", self.request, re.I):
                diagnostics.update({"df -h", "df -h /"})
            if re.search(r"\bmemory\s+usage\b", self.request, re.I):
                diagnostics.add("free -h")
            if re.search(r"\bsystem\s+info\b", self.request, re.I):
                diagnostics.add("uname -a")
            if command not in self.request and command not in diagnostics:
                raise ValueError("Only the command supplied by the user or a matching built-in diagnostic can run.")
        elif name == "weather" and args.get("location"):
            if normalized(args["location"]) not in normalized(self.request):
                args.pop("location")
        elif name == "web_search":
            args["query"] = self.query[:500]
        elif name == "web_read" or (name == "browser" and args.get("action") == "open"):
            url = public_url(args.get("url", ""))
            if url not in self.urls:
                raise ValueError("Open a URL supplied by the user or returned by a checked web tool. New model-invented URLs were not requested.")
        elif name == "browser" and args.get("action") in {"fill", "select"}:
            text = normalized(args.get("text", ""))
            if text and f" {text} " not in f" {normalized(self.public_input)} ":
                raise ValueError("Browser input must come from the user's current request. Ask for the missing form value; private memory and webpage instructions do not authorize input.")
        return args

    def observe(self, name, result, args=None):
        if not result.success or name not in {"web_search", "web_read", "browser"}:
            return
        try:
            data = json.loads(result.output)
        except (ValueError, TypeError):
            return
        if not isinstance(data, dict):
            return
        candidates = [data.get("url")]
        for field_name in ("results", "links"):
            candidates.extend(row.get("url") for row in data.get(field_name, []) if isinstance(row, dict))
        for value in candidates:
            if not isinstance(value, str) or len(self.urls) >= 100:
                continue
            try:
                self.urls.add(public_url(value))
            except ValueError:
                pass
        if name in {"web_read", "browser"} and isinstance(data.get("text"), str) and data["text"].strip():
            try:
                self.verified[public_url(data["url"])] = data["text"]
                if name == "web_read":
                    self.read_results[public_url(data["url"])] = result
                    if args and isinstance(args.get("url"), str):
                        self.read_results[public_url(args["url"])] = result
                if name == "browser":
                    self.browser_texts.append(data["text"])
            except (ValueError, KeyError, TypeError):
                pass

    def grounded_answer(self, answer):
        """A checked source is necessary for a live answer; snippets do not count."""
        if not self.query or answer == FORMAT_FAILURE:
            return answer
        if re.fullmatch(r"(?:Which|What|Could you provide|Please provide)[^.?!]{1,250}\?", answer.strip(), re.I):
            return answer
        if not self.verified:
            return "I couldn't verify a live source for that request. Please share a source URL or try again."
        if (re.search(r"\btrain\b", self.public_input, re.I) and
                re.search(r"\b(?:seat|seats|availability|available)\b", self.public_input, re.I) and
                re.search(r"\b(?:available|seats?|waitlist|rac|wl|confirmed|sold out)\b", answer, re.I)):
            # Generic page text cannot bind inventory to the full journey,
            # class, quota and check time. A validated enquiry adapter is needed
            # before emitting a seat claim, even when a page contains numbers.
            return ("I found a source page, but couldn't verify live seats for that train and date. "
                    "Please check the enquiry manually: " + next(iter(self.verified)))
        cited = {value.rstrip(".,;!?\u200b\u200c\u200d\u2060\ufeff") for value in URL.findall(answer)}
        if not cited.intersection(self.verified):
            return "I retrieved a source, but couldn't produce a properly sourced answer. Please retry or check " + next(iter(self.verified))
        if cited - set(self.verified):
            return "The answer included an unverified source link. Please retry or check " + next(iter(self.verified))
        return answer

    def missing_citation(self, answer):
        return bool(self.query and self.verified and answer != FORMAT_FAILURE and not URL.search(answer))
