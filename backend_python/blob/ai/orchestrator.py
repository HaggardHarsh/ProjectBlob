import asyncio
from collections import deque
from datetime import datetime
import logging
import json
import inspect
import os
import re
import sqlite3
import time
from pathlib import Path
from blob.ai.llm_engine import NebiusEngine
from blob.ai.attachments import AttachmentReader, AttachmentError, MAX_IMAGES
from blob.ipc import blob_service_pb2
from blob.ai.guardrails import GuardrailsEngine, PERSONAL_PLAN_TOPIC, unsupported_personal_event_claim
from blob.ai.context_budget import DEFAULT_MAX_PROMPT_BYTES, IMAGE_BUDGET_BYTES, fit_messages, prompt_size_bytes
from blob.ai.prompt_templates import SYSTEM_PROMPT, ATTACHMENT_SYSTEM_PROMPT, CONTEXT_TEMPLATE
from blob.memory.episodic import EpisodicMemory
from blob.memory.documents import DocumentLibrary, DocumentError, DOCUMENT_REFERENCE
from blob.memory.semantic import SemanticMemory, is_temporary_fact
from blob.memory.context import build_memory_view
from blob.memory.lifecycle import SHORT_RECALL_DAYS, academic_selector_known, topic_key
from blob.skills.commands import handle_skill_command

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 3
STYLE_CACHE_TTL_SECONDS = 30
MAX_MEMORY_DISTANCE = 1.35  # Calibrated for Chroma's default normalized MiniLM embeddings.
STYLE_QUERY = "How does the user want Blob to speak to them: friendly buddy, formal, professional, direct, or quiet?"
EMOTE_NAMES = "IDLE|HAPPY|SAD|ANGRY|CONFUSED|THINKING|WORRIED|CELEBRATE|EXCITED|TIRED|OFFER_COFFEE|SHY|SLEEPING|EATING|PROUD|PLAYFUL|WORKING|DEEP_THINKING|LISTENING|SHOCKED|MELTING|ERROR|SUCCESS|WAITING"
EMOTE_ALIASES = {"AMUSED": "PLAYFUL"}
EMOTE_MARKER = re.compile(
    rf"<emote>\s*([^<]*?)\s*</emote>|\(({EMOTE_NAMES}|{'|'.join(EMOTE_ALIASES)})\)",
    re.IGNORECASE | re.DOTALL)
EMOTE_OPEN = re.compile(
    r"<emote>.*$|</?emote\b[^>]*$|</?(?:e|em|emo|emot)\s*$", re.IGNORECASE | re.DOTALL)
FACE_REQUEST = re.compile(
    r"(?:"
    r"(?:(?:can|could|would|will) you\s+)?(?:please\s+)?"
    r"(?:make|do|show|give|put on)\s+(?:me\s+)?(?:(?:a|the|your)\s+)?"
    r"|what about\s+(?:(?:a|the|your)\s+)?"
    r")"
    r"(?P<mood>melting|melted|sad|happy)\s+(?:face|expression)"
    r"(?:\s+for me)?(?:,?\s+please)?[?.!]*",
    re.IGNORECASE,
)
CAMERA_REQUEST = re.compile(
    r"\b(?:open|turn on|switch on|start|use|scan|check|share|access|view|see|look through|look at|see through|"
    r"recognize|recognise|identify|detect)\b"
    r".{0,35}\b(?:camera|webcam)\b|\bturn\b.{0,15}\b(?:camera|webcam)\b\s+on\b"
    r"|\b(?:recognize|recognise|identify|scan|detect)\b.{0,20}\bmy\s+face\b",
    re.IGNORECASE,
)
CAMERA_RETRY_EXPLICIT = re.compile(
    r"\b(?:try|scan|check|use|open)\b.{0,20}\b(?:camera|webcam)\b.{0,15}\bagain\b"
    r"|\b(?:camera|webcam)\b.{0,15}\bagain\b"
    r"|\btry\s+again\s+(?:with\s+)?(?:the\s+|my\s+)?(?:camera|webcam)\b",
    re.IGNORECASE,
)
CAMERA_RETRY_FOLLOWUP = re.compile(
    r"^(?:(?:no|okay|ok)[, ]+|please\s+|can you\s+)?"
    r"(?:try|scan|check)(?:\s+it)?\s+again[?.!]*$",
    re.IGNORECASE,
)
CAMERA_STATUS_REQUEST = re.compile(
    r"\b(?:camera|webcam)\b.{0,40}\b(?:work(?:ing)?|available|availability|access|block(?:ed)?|permission(?:s)?|status)\b"
    r"|\bwhy\b.{0,60}\b(?:access|open|use)\b.{0,20}\b(?:camera|webcam)\b",
    re.IGNORECASE,
)
SCREEN_REQUEST = re.compile(
    r"\b(?:what(?:'s| is) (?:happening|going on|on|visible)|show me|look at|check|read|describe|capture|see|share|view)\b"
    r".{0,45}\b(?:my |the |this )?(?:screen|desktop|display)\b"
    r"|\b(?:screen|desktop|display)\b.{0,30}\b(?:what(?:'s| is) on|look|check|read|describe|capture|see)\b"
    r"|\b(?:help(?: me)?(?: with)?|explain|teach|understand|studying|reading)\b"
    r".{0,100}\b(?:on|from)\s+(?:my|the|this)\s+(?:screen|desktop|display)\b"
    r"|\bwhat does\b.{0,80}\bon\s+(?:my|the|this)\s+(?:screen|desktop|display)\b",
    re.IGNORECASE,
)
SCREEN_REFERENCE = re.compile(
    r"\b(?:my|the|this|current)\s+(?:screen|desktop|display)\b", re.IGNORECASE)
SCREEN_CORRECTION = re.compile(
    r"^\s*(?:no|nope|nah|actually|i (?:mean|meant))\b"
    r"|\b(?:i (?:mean|meant)|not (?:the|that|an?)(?:\s+attached)?\s+(?:pdf|document|file|timetable))\b",
    re.IGNORECASE)
SCREEN_CAPTURE_FOLLOWUP = re.compile(
    r"\b(?:capture(?: it)?|take (?:a )?screenshot|screenshot|go ahead|just do it|do it now)\b",
    re.IGNORECASE,
)
SCREEN_CAPTURE_DENIAL = re.compile(
    r"\b(?:don['’]t|do not|never)\s+(?!(?:need|require)\b)"
    r"(?:(?:please|want|you|to|me|my|the|a)\s+){0,4}"
    r"(?:capture|record|screenshot|look at|see|view|read|share|take (?:a )?screenshot|do (?:it|that))\b"
    r"|\b(?:don['’]t|do not)\s+need\s+(?:(?:you\s+)?to\s+"
    r"(?:capture|record|look at|see|view|read)|(?:a\s+)?(?:screenshot|screen capture))\b"
    r"|\bno\s+(?:more\s+)?(?:screenshots?|screen capture|captur(?:e|ing)(?:\s+of)?|recording)\b"
    r"|\b(?:don['’]t|do not)\s+(?:want|need)\b.{0,35}\b(?:screen|desktop|display)\b"
    r".{0,25}\b(?:captured|recorded|shared|read)\b"
    r"|\bnot\s+(?:my|the|this)\s+(?:screen|desktop|display)\b",
    re.IGNORECASE,
)
SCREEN_PROCEDURE_QUESTION = re.compile(
    r"^\s*(?:how (?:do|can) (?:i|you)|why (?:can't|cannot|won't) you)\b"
    r".{0,80}\b(?:capture|record|take (?:a )?screenshot)\b",
    re.IGNORECASE,
)
FALSE_SCREEN_PERMISSION_DENIAL = re.compile(
    r"\b(?:can['’]t|cannot|unable to|need(?: your)? permission)\b.{0,100}"
    r"\b(?:capture|see|view|read|access|peek|look)\b.{0,60}\b(?:screen|desktop|display)\b"
    r"|\b(?:don['’]t|do not)\s+have\s+access\b.{0,60}\b(?:screen|desktop|display)\b",
    re.IGNORECASE,
)
STUDY_HELP_REQUEST = re.compile(
    r"\b(?:study|studying|learn|learning|understand|explain|teach|help(?: me)?(?: with)?"
    r"|simplify|simpler|hard|difficult|confusing|confused)\b"
    r"|\b(?:dumb|break)\b.{0,40}\bdown\b"
    r"|\bmake\b.{0,40}\b(?:simple|easy|easier)\b",
    re.IGNORECASE,
)
FILE_REQUEST = re.compile(
    r"\b(?:find|search|locate)\b.{0,50}\b(?:file|pdf|document|notes)\b"
    r"|\b(?:file|pdf|document|notes)\b.{0,50}\b(?:find|search|locate)\b",
    re.IGNORECASE,
)
FILE_SEARCH_CLAIM = re.compile(
    r"\b(?:file|document|pdf)\b.{0,100}\b(?:search|find|found|showing|saved)\b"
    r"|\b(?:search|find|found)\b.{0,100}\b(?:file|document|pdf)\b",
    re.IGNORECASE,
)
REMINDER_INTENT = re.compile(
    r"\b(?:remind me|(?:set|create|make|add)\s+(?:me\s+)?(?:a |an |the )?(?:reminder|timer|alarm)"
    r"|start (?:a |the )?timer"
    r"|(?:cancel|remove|delete|snooze|postpone|list|show|check)\s+(?:me\s+)?"
    r"(?:my |the |a |all |that )?(?:scheduled )?(?:reminders?|timers?|alarms?))\b",
    re.IGNORECASE,
)
REMINDER_CONTROL = re.compile(
    r"\b(?P<action>cancel|remove|delete|snooze|postpone|list|show|check)\s+(?:me\s+)?"
    r"(?:my |the |a |all |that )?(?:scheduled )?(?:reminders?|timers?|alarms?)\b", re.I)


def _requested_reminder_action(text):
    match = REMINDER_CONTROL.search(text)
    if not match:
        return "set"
    verb = match.group("action").lower()
    return "cancel" if verb in {"cancel", "remove", "delete"} else "snooze" if verb in {"snooze", "postpone"} else "list"


WEATHER_INTENT = re.compile(
    r"\b(?:what(?:'s| is) the weather|(?:check|show|tell me|give me)\b.{0,40}\bweather"
    r"|weather (?:in|now|today)|"
    r"is it (?:raining|sunny|snowing))\b",
    re.IGNORECASE,
)
WEATHER_LOCATION = re.compile(
    r"\bweather\s+in\s+(.+?)(?:\s+(?:right now|today|now))?[?.!]*$",
    re.IGNORECASE,
)
FUTURE_WEATHER_TIME = re.compile(r"\b(?:tomorrow|next week|this weekend|later today)\b", re.IGNORECASE)
WEATHER_TOPIC = re.compile(r"\b(?:weather|forecast|rain|snow|temperature)\b", re.IGNORECASE)
REMEMBER_ME_REQUEST = re.compile(
    r"^(?:(?:can|will|could|would|do) you |please |i want you to )?remember me"
    r"(?: (?:tomorrow|next time|after (?:a |the )?restart))?[.!?]*$",
    re.IGNORECASE,
)
MEMORY_TOPIC = re.compile(r"\b(?:remember|memory|recall|retain)\b", re.IGNORECASE)
PROFILE_OVERVIEW_REQUEST = re.compile(
    r"\b(?:what do you (?:know|remember) about me|what have you learned about me|"
    r"(?:tell me|summari[sz]e) what you (?:know|remember) about me)\b",
    re.IGNORECASE,
)
HISTORICAL_RECALL = re.compile(
    r"\b(?:yesterday|last (?:week|month|year)|previous (?:chat|conversation)|"
    r"earlier (?:chat|conversation)|what did we (?:talk|discuss))\b", re.IGNORECASE,
)
ASSISTANT_HISTORY_REQUEST = re.compile(
    r"\b(?:what did you (?:say|tell me)|what was your (?:reply|answer)|your (?:earlier|previous|last) (?:reply|answer|message))\b",
    re.IGNORECASE,
)
FALSE_MEMORY_DENIAL = re.compile(
    r"\b(?:i|blob)\s+(?:do(?: not|n't)|will(?: not|n't)|can(?: not|'t))\s+"
    r"(?:have|retain|keep|store|remember).{0,65}\b(?:persistent memory|long.term memory|across sessions|after (?:a |the )?restart|tomorrow)\b"
    r"|\b(?:no persistent memory|no long.term memory|memory (?:does(?: not|n't)|will(?: not|n't)) survive)\b",
    re.IGNORECASE,
)
MEMORY_CAPABILITY_RESPONSE = (
    "I have persistent local memory and can recall relevant details you share across restarts. "
    "What would you like me to remember about you?"
)
DAY_ONLY_REQUEST = re.compile(
    r"^(?:(?:man|hey|please)[, ]+)?(?:just\s+)?(?:tell me\s+)?"
    r"(?:(?:what(?:'s| is)\s+)?(?:the\s+)?day(?: of the week)?(?:\s+(?:is it|today))?"
    r"|what day is it(?: today)?|what day is today)\s*[.!?]*$",
    re.IGNORECASE,
)
REASONING_BLOCK = re.compile(r"<(think|thinking|analysis)>.*?</\1>", re.IGNORECASE | re.DOTALL)
REASONING_OPEN = re.compile(r"<(?:think|thinking|analysis)>.*$", re.IGNORECASE | re.DOTALL)
REASONING_CLOSE = re.compile(r"</(?:think|thinking|analysis)>", re.IGNORECASE)


def _strip_reasoning(text: str) -> str:
    text = REASONING_BLOCK.sub("", text)
    text = REASONING_OPEN.sub("", text)
    return REASONING_CLOSE.sub("", text).strip()


def _visible_preview(text: str) -> str:
    text = _strip_reasoning(text)
    text = EMOTE_MARKER.sub("", text)
    text = EMOTE_OPEN.sub("", text)
    # A stream chunk may stop in the middle of a control tag.
    return re.sub(r"<[^>]*$", "", text).rstrip()


def _requested_face(text: str) -> str | None:
    """Recognize a whole-message request to change Blob's visible expression."""
    match = FACE_REQUEST.fullmatch(text.strip())
    if match is None:
        return None
    mood = match.group("mood").upper()
    return "MELTING" if mood == "MELTED" else mood


def _wants_screen_capture(text: str, recent_turns) -> bool:
    """Treat a screen question or its immediate go-ahead as a capture request."""
    if SCREEN_CAPTURE_DENIAL.search(text) or SCREEN_PROCEDURE_QUESTION.search(text):
        return False
    if (SCREEN_REQUEST.search(text) or text.casefold() in {"/screen", "/screenshot"} or
            (SCREEN_REFERENCE.search(text) and
             (STUDY_HELP_REQUEST.search(text) or SCREEN_CORRECTION.search(text)))):
        return True
    if not SCREEN_CAPTURE_FOLLOWUP.search(text):
        return False
    previous_user = next((item["content"] for item in reversed(recent_turns)
                          if item["role"] == "user"), "")
    return _wants_screen_capture(previous_user.strip(), ())


class BlobOrchestrator:
    def __init__(self, config, vector_store, skill_registry, event_dispatcher, screen_sampler=None):
        self.config = config
        self.vector_store = vector_store
        vector_store.backfill_grounded_provenance()
        self.skill_registry = skill_registry
        self.event_dispatcher = event_dispatcher
        self.screen_sampler = screen_sampler
        self.guardrails = GuardrailsEngine(config)
        self.llm = NebiusEngine(config.nebius_api_key, config.nebius_base_url, config.model_name)
        
        self.episodic = EpisodicMemory(vector_store)
        self.semantic = SemanticMemory(vector_store, self.llm)
        self.semantic.backfill_explicit_statements()
        self._style_facts_cache = None
        self._style_facts_revision = None
        self._style_facts_cached_at = 0.0
        self._profile_latency = os.environ.get("BLOB_PROFILE_LATENCY", "").lower() in {"1", "true", "yes", "on"}
        self._streaming_disabled = False
        self._recent_turns = deque(maxlen=12)
        self._active_attachments = []
        configured_budget = getattr(config, "max_prompt_bytes", DEFAULT_MAX_PROMPT_BYTES)
        self._max_prompt_bytes = (configured_budget if isinstance(configured_budget, int)
                                  else DEFAULT_MAX_PROMPT_BYTES)
        
        # Holds the latest screen context text (populated by ScreenCaptureSkill or sampler)
        self.last_screen_context = "No screen data captured yet."

    def _build_skills_text(self) -> str:
        """Format registered skills for the system prompt."""
        return self.skill_registry.prompt_text()

    @staticmethod
    def _current_clock_context() -> str:
        """Supply a fresh local clock for ordinary chat and file analysis."""
        now = datetime.now().astimezone()
        clock = now.strftime("%A, %Y-%m-%d %H:%M %Z (%z)")
        return f"\n## Current local date and time\n{clock}\n"

    def _build_system_prompt(self) -> str:
        """Build the full system prompt with skills injected."""
        skills_text = self._build_skills_text()
        return SYSTEM_PROMPT.replace("{skills}", skills_text) + self._current_clock_context()

    def _remember_turn(self, user_text: str, reply: str) -> None:
        if self.screen_sampler and self.screen_sampler.privacy_shield.is_capture_blocked():
            return
        episode_id = self.episodic.add_episode(user_text, reply)
        remember = getattr(getattr(self, "semantic", None), "remember_explicit_statements", None)
        if callable(remember):
            remember(user_text, episode_id)
        self._remember_recent_turn(user_text, reply)

    def _save_document_user_message(self, text):
        """Persist authored user words; document analysis is not a user fact."""
        sampler = getattr(self, "screen_sampler", None)
        if sampler and sampler.privacy_shield.is_capture_blocked():
            return
        add_user = getattr(self.episodic, "add_user_message", None)
        if callable(add_user):
            episode_id = add_user(text, {"source": "document_chat"})
            remember = getattr(getattr(self, "semantic", None), "remember_explicit_statements", None)
            if callable(remember):
                remember(text, episode_id)

    def _document_user_context(self, question):
        reader = getattr(getattr(self, "semantic", None), "document_context", None)
        return reader(question) if callable(reader) else ""

    @staticmethod
    def _needs_exam_selector(question, attached, personal_context):
        """A multi-program timetable cannot identify a user's exams on its own."""
        evidence = "\n".join(part.get("text", "") for part in attached.parts)
        exam_words = r"\b(?:exams?|examinations?|mid[ -]?(?:sems?|terms?))\b"
        if not re.search(exam_words, question + "\n" + evidence, re.I):
            return False
        personal_question = (
            re.search(r"\b(?:my|mine|i)\b", question, re.I) and
            (re.search(exam_words + r"|\b(?:papers?|subjects?|courses?|timetable)\b", question, re.I) or
             re.search(r"\bi\s+have\b", question, re.I))) or re.search(
                 r"\b(?:make|create|prepare)\b.{0,25}\bme\b.{0,45}\btimetable\b", question, re.I)
        if not personal_question:
            return False
        current = [line.partition(": ")[2] for line in personal_context.splitlines()
                   if line.startswith("Current user statement: ")]
        subjects = [statement for statement in current if topic_key(statement) == "education:subjects"]
        # An explicit unknown/empty course list supersedes a previous program assumption.
        if subjects:
            return not any(academic_selector_known(statement) for statement in subjects)
        return not any(academic_selector_known(statement) for statement in current)

    def _remember_recent_turn(self, user_text: str, reply: str) -> None:
        """Keep direct tool results in this session without saving them as facts."""
        if not hasattr(self, "_recent_turns"):
            self._recent_turns = deque(maxlen=12)
        self._recent_turns.extend((
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": reply},
        ))

    def _get_style_facts(self) -> list:
        revision = getattr(self.vector_store, "semantic_revision", None)
        now = time.monotonic()
        if (self._style_facts_cache is None or revision != self._style_facts_revision or
                now - self._style_facts_cached_at >= STYLE_CACHE_TTL_SECONDS):
            self._style_facts_cache = self.semantic.recall_facts(
                STYLE_QUERY, top_k=2, max_distance=MAX_MEMORY_DISTANCE)
            self._style_facts_revision = revision
            self._style_facts_cached_at = now
        return self._style_facts_cache

    def _build_context(self, clean_text: str) -> str:
        """Build the context block with memories, active window, and screen data."""
        overview = bool(PROFILE_OVERVIEW_REQUEST.search(clean_text))
        historical = bool(MEMORY_TOPIC.search(clean_text) or
                          HISTORICAL_RECALL.search(clean_text) or
                          ASSISTANT_HISTORY_REQUEST.search(clean_text))
        episodes = [] if overview else self.episodic.recall_relevant(
            clean_text, top_k=5, max_distance=MAX_MEMORY_DISTANCE,
            min_timestamp=None if historical else time.time() - SHORT_RECALL_DAYS * 86400,
            search_full_episode=bool(ASSISTANT_HISTORY_REQUEST.search(clean_text)))
        facts = (self.semantic.list_facts() if overview else
                 self.semantic.recall_facts(clean_text, top_k=3,
                                            max_distance=MAX_MEMORY_DISTANCE))
        middle_facts = (self.semantic.list_middle() if overview else
                        self.semantic.recall_middle(clean_text, top_k=3,
                                                    max_distance=MAX_MEMORY_DISTANCE))
        evidence = []
        for item in facts + middle_facts:
            meta = item.get("metadata") or {}
            if meta.get("grounded") is True:
                evidence.append((meta.get("source_timestamp", meta.get("timestamp", 0)), item["text"]))
        for item in episodes:
            if not item["text"].startswith("User: "):
                continue
            meta = item.get("metadata") or {}
            user_text = item["text"].partition("\nBlob: ")[0].removeprefix("User: ")
            if user_text:
                evidence.append((meta.get("timestamp", 0), user_text))
        self._grounded_user_evidence = [
            (text, timestamp) for timestamp, text in sorted(
                evidence, key=lambda entry: entry[0] if isinstance(entry[0], (int, float)) else 0,
                reverse=True)
        ]
        # Tone preferences must remain in view even when the current question
        # is about an unrelated task.
        style_facts = self._get_style_facts()
        fact_texts = []
        for item in style_facts + facts:
            if is_temporary_fact(item["text"]):
                continue
            meta = item.get("metadata") or {}
            prefix = "Long-term user quote" if meta.get("grounded") else "Older saved summary (unverified)"
            said = meta.get("source_timestamp")
            date = datetime.fromtimestamp(said).astimezone().date().isoformat() if said else "date unknown"
            fact_texts.append(f"{prefix} (said {date}): {item['text']}")
        for item in middle_facts:
            meta = item.get("metadata") or {}
            said = datetime.fromtimestamp(meta.get("source_timestamp", meta.get("timestamp", time.time()))).astimezone().date().isoformat()
            expires = datetime.fromtimestamp(meta["expires_at"]).astimezone().date().isoformat() if meta.get("expires_at") else "unknown"
            fact_texts.append(f"Active middle-term user quote (said {said}, expires {expires}): {item['text']}")
        episode_texts = []
        for item in episodes:
            text = item["text"]
            timestamp = (item.get("metadata") or {}).get("timestamp")
            if isinstance(timestamp, (int, float)) and text.startswith("User: "):
                user_part, separator, reply = text.partition("\nBlob: ")
                said = datetime.fromtimestamp(timestamp).astimezone().date().isoformat()
                text = f"{user_part}\n[User said this on {said}]"
                if separator:
                    text += separator + reply
            episode_texts.append(text)
        # Old assistant replies are not evidence for ordinary questions. Include
        # them only when the user explicitly asks what Blob said before.
        fact_view, episode_view = build_memory_view(
            fact_texts, episode_texts, clean_text,
            user_only=not bool(ASSISTANT_HISTORY_REQUEST.search(clean_text)),
            recall_mode=historical,
        )
        # Try to get active window title (lightweight, no screenshot)
        active_window = "Unknown"
        shielded = bool(self.screen_sampler and self.screen_sampler.privacy_shield.is_capture_blocked())
        if shielded:
            self.last_screen_context = "No screen data captured yet."
        if self.screen_sampler and not shielded:
            try:
                title = self.screen_sampler.get_active_window_title()
                if title:
                    active_window = title
            except Exception:
                pass

        return CONTEXT_TEMPLATE.format(
            active_window=active_window,
            screen_context="Blocked by privacy shield" if shielded else self.last_screen_context,
            semantic_memories=fact_view,
            episodic_memories=episode_view,
        )

    def _parse_tool_call(self, response_text: str):
        """Accept a tool request only when it is the entire model message."""
        visible = EMOTE_MARKER.sub("", _strip_reasoning(response_text)).strip()
        for pattern in (r"```(?:tool_call|json)?\s*(.*?)\s*```",
                        r"<tool_call>\s*(.*?)\s*</tool_call>"):
            match = re.fullmatch(pattern, visible, flags=re.IGNORECASE | re.DOTALL)
            if match:
                visible = match.group(1).strip()
                break
        if visible.startswith("{{") and visible.endswith("}}"):
            visible = visible[1:-1]
        try:
            tool_data = json.loads(visible)
        except json.JSONDecodeError:
            return None, None
        if isinstance(tool_data, dict):
            tool_name = tool_data.get("tool")
            tool_args = tool_data.get("args", {})
            if isinstance(tool_name, str) and tool_name and isinstance(tool_args, dict):
                return tool_name, tool_args
        return None, None

    def _strip_tool_call_block(self, text: str) -> str:
        """Remove tool call blocks and raw tool JSON from text for display."""
        text = re.sub(r'```(?:tool_call|json)?\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)
        text = re.sub(r'<tool_call>.*?</tool_call>', '', text, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r'\{\{?\s*"tool"\s*:.*?"args"\s*:.*?\}\}?', '', text, flags=re.DOTALL)
        return text.strip()

    def _extract_emote(self, text: str) -> tuple[str, str]:
        """Keep model mood markers for the slime, never for the chat text."""
        matches = list(EMOTE_MARKER.finditer(text))
        emote = (matches[-1].group(1) or matches[-1].group(2) or "IDLE").strip().upper() if matches else "IDLE"
        emote = EMOTE_ALIASES.get(emote, emote)
        if emote not in EMOTE_NAMES.split("|"):
            emote = "IDLE"
        return emote, EMOTE_OPEN.sub("", EMOTE_MARKER.sub("", text)).strip()

    def _show_thinking(self):
        """Display the same terminal placeholder for ordinary chat and documents."""
        print("\r\033[K\033[90m(Thinking...)\033[0m", end="", flush=True)
        self._thinking_placeholder_visible = True

    def _clear_thinking(self):
        if getattr(self, "_thinking_placeholder_visible", False):
            print("\r\033[K", end="", flush=True)
            self._thinking_placeholder_visible = False

    async def _generate_with_preview(self, messages: list[dict], system_prompt: str,
                                     allow_preview: bool = True, engine=None) -> tuple[str, str]:
        engine = engine or self.llm
        stream = getattr(engine, "generate_from_messages_stream", None)
        if getattr(self, "_streaming_disabled", False) or not inspect.isasyncgenfunction(stream):
            msg = await engine.generate_from_messages(messages, system_prompt)
            return msg.content or "", ""

        response = ""
        preview = ""
        preview_started = False
        try:
            async for part in stream(messages, system_prompt):
                response += part
                if not allow_preview:
                    continue
                head = _visible_preview(response).lstrip()
                # Tool calls are text blocks in this protocol. Keep them out of the terminal.
                if (not head or head.startswith(("```", "{", "<tool_call>"))
                        or "```".startswith(head) or "<tool_call>".startswith(head)):
                    continue
                # Hold the tail so incomplete control tags cannot reach the terminal.
                safe = _visible_preview(response[:-32])
                if len(safe) > len(preview):
                    if not preview_started:
                        self._clear_thinking()
                        print("\r\033[K\033[96mBlob:\033[0m ", end="", flush=True)
                        preview_started = True
                    print(safe[len(preview):], end="", flush=True)
                    preview = safe
        except Exception:
            if response:
                if preview_started:
                    print("\r\033[K", end="", flush=True)
                raise
            self._streaming_disabled = True
            logger.warning("Streaming unavailable; using normal model responses")
            msg = await engine.generate_from_messages(messages, system_prompt)
            return msg.content or "", ""
        return response, preview

    async def _await_with_progress(self, operation, delay: float, emote: str):
        """Show a calmer state if model or tool work takes longer than expected."""
        task = asyncio.create_task(operation)
        try:
            try:
                return await asyncio.wait_for(asyncio.shield(task), delay)
            except asyncio.TimeoutError:
                await self.dispatch_emote(emote)
                return await task
        finally:
            if not task.done():
                task.cancel()
                self._clear_thinking()
            elif task.cancelled() or task.exception() is not None:
                self._clear_thinking()

    def _conversation_lock(self):
        if not hasattr(self, "_message_lock"):
            self._message_lock = asyncio.Lock()
        return self._message_lock

    def _document_library(self):
        if not hasattr(self, "_documents"):
            self._documents = DocumentLibrary(getattr(getattr(self, "config", None), "documents_dir_path", None))
        return self._documents

    def _uses_attachment_context(self, text):
        """Use dropped files for conversation while preserving explicit controls and tools."""
        stripped = text.strip()
        if (stripped.startswith("/") or DAY_ONLY_REQUEST.fullmatch(stripped) or
                FACE_REQUEST.fullmatch(stripped) or REMEMBER_ME_REQUEST.fullmatch(stripped) or
                PROFILE_OVERVIEW_REQUEST.search(stripped) or REMINDER_INTENT.search(stripped) or
                _wants_screen_capture(stripped, getattr(self, "_recent_turns", ()))):
            return False
        if re.search(r"\b(?:attached|attachment|pdf|document|image|picture|diagram|chapter|pages?)\b", stripped, re.I):
            return True
        return not (
            WEATHER_INTENT.search(stripped) or
            (WEATHER_TOPIC.search(stripped) and FUTURE_WEATHER_TIME.search(stripped)) or
            CAMERA_REQUEST.search(stripped) or CAMERA_STATUS_REQUEST.search(stripped) or
            CAMERA_RETRY_EXPLICIT.search(stripped) or re.fullmatch(r"(?:camera|webcam)[.!?]*", stripped, re.I) or
            (getattr(self, "_last_camera_action", None) and CAMERA_RETRY_FOLLOWUP.fullmatch(stripped)) or
            FILE_REQUEST.search(stripped)
        )

    async def handle_user_message(self, user_msg):
        # File drops and terminal messages share one ordered conversation.
        async with self._conversation_lock():
            stripped = user_msg.text.strip()
            if stripped and stripped.split(maxsplit=1)[0].lower() in {"/skills", "/reminders"}:
                result = await self._await_with_progress(
                    handle_skill_command(self.skill_registry, stripped), 3.0, "WAITING")
                self._remember_recent_turn(stripped, result.output)
                return await self._send_direct_response(result.output, result.emote_suggestion)
            if stripped and stripped.split(maxsplit=1)[0].lower() == "/files":
                return await self._handle_files_command(stripped)
            # An explicit screen request selects fresh screen evidence before
            # attachment selection or saved-document search can claim the message.
            if _wants_screen_capture(stripped, getattr(self, "_recent_turns", ())):
                return await self._handle_text_message(user_msg)
            explicit = list(getattr(user_msg, "attachments", ()))
            paths = explicit or list(getattr(self, "_active_attachments", ()))
            if paths and (explicit or self._uses_attachment_context(stripped)):
                return await self._handle_attachment_message(blob_service_pb2.UserMessage(
                    text=user_msg.text, attachments=paths))
            if not paths and self._uses_attachment_context(stripped):
                library = self._document_library()
                try:
                    saved = await asyncio.to_thread(library.find, stripped)
                    if saved:
                        paths = await asyncio.to_thread(library.reopen, saved)
                        print("\nBlob: Reopening saved files: " + ", ".join(record["name"] for record in saved) +
                              ". Selected content is sent to your AI provider for analysis.\n")
                        return await self._handle_attachment_message(blob_service_pb2.UserMessage(
                            text=user_msg.text, attachments=paths), activate=True)
                    if DOCUMENT_REFERENCE.search(stripped):
                        records = await asyncio.to_thread(library.records)
                        if records:
                            names = ", ".join(record["name"] for record in records)
                            return await self._send_direct_response(
                                f"I have saved documents: {names}. Which one do you mean? Name it or use /files saved and /files open <id>.",
                                "CONFUSED")
                except (DocumentError, OSError, sqlite3.Error) as exc:
                    logger.warning("Document recall failed: %s", exc)
                    return await self._send_direct_response(str(exc), "WORRIED")
            return await self._handle_text_message(user_msg)

    async def handle_attachment_drop(self, paths):
        async with self._conversation_lock():
            incoming = [str(Path(path).expanduser().resolve()) for path in paths if path]
            if not incoming:
                return await self._send_direct_response("No files were dropped.", "CONFUSED")
            library = self._document_library()
            try:
                # A newly dropped original replaces its saved copy in the active selection.
                originals = {await asyncio.to_thread(library.original_path, path) for path in incoming}
                retained = []
                for path in getattr(self, "_active_attachments", ()):
                    if await asyncio.to_thread(library.original_path, path) not in originals:
                        retained.append(path)
            except (DocumentError, OSError, sqlite3.Error):
                retained = list(getattr(self, "_active_attachments", ()))
            combined = list(dict.fromkeys([*retained, *incoming]))
            names = ", ".join(Path(path).name for path in incoming)
            print(f"\nBlob: Reading dropped files: {names}. Selected content is sent to your AI provider for analysis.\n")
            return await self._handle_attachment_message(blob_service_pb2.UserMessage(
                text="Give a brief overview of these attached files so we can discuss them in the terminal.",
                attachments=combined), activate=True, user_authored=False)

    async def _handle_files_command(self, command):
        parts = command.lower().split()
        paths = list(getattr(self, "_active_attachments", ()))
        library = self._document_library()
        try:
            if parts == ["/files", "saved"]:
                records = await asyncio.to_thread(library.records)
                listing = "\n".join(f"{record['id']}  {record['name']}" for record in records)
                return await self._send_direct_response(
                    ("Saved documents:\n" + listing if records else "No saved documents yet. Drop a PDF or image onto Blob.") +
                    "\nUse /files open <id> to analyze one or /files forget <id|all> to delete saved copies.", "IDLE")
            if len(parts) == 3 and parts[:2] == ["/files", "open"]:
                records = await asyncio.to_thread(library.records)
                selected = [record for record in records if record["id"] == parts[2]]
                if not selected:
                    raise DocumentError("No saved document with that ID. Use /files saved to list IDs.")
                reopened = await asyncio.to_thread(library.reopen, selected)
                print("\nBlob: Reopening " + selected[0]["name"] +
                      ". Selected content is sent to your AI provider for analysis.\n")
                return await self._handle_attachment_message(blob_service_pb2.UserMessage(
                    text="Give a brief overview of this saved document.", attachments=reopened), activate=True, user_authored=False)
            if len(parts) == 3 and parts[:2] == ["/files", "forget"]:
                removed = await asyncio.to_thread(library.forget, parts[2])
                deleted_paths = {str(library.path_for(record)) for record in removed} | {
                    record["original_path"] for record in removed}
                self._active_attachments = [path for path in paths if str(Path(path).resolve()) not in deleted_paths]
                # Discard prior document excerpts and answers from the live context too.
                getattr(self, "_recent_turns", []).clear()
                names = ", ".join(record["name"] for record in removed)
                return await self._send_direct_response(f"Deleted saved copies of {names}. Original files are untouched.", "IDLE")
        except (DocumentError, OSError, sqlite3.Error) as exc:
            logger.warning("Saved document command failed: %s", exc)
            return await self._send_direct_response(str(exc), "WORRIED")
        if parts == ["/files", "clear"]:
            self._active_attachments = []
            return await self._send_direct_response(
                "Detached all files. Saved copies remain available; use /files saved to list them.", "IDLE")
        if len(parts) == 3 and parts[:2] == ["/files", "remove"]:
            try:
                index = int(parts[2]) - 1
            except ValueError:
                index = -1
            if not 0 <= index < len(paths):
                return await self._send_direct_response("Use /files to list files, then /files remove <number>.", "CONFUSED")
            removed = paths.pop(index)
            self._active_attachments = paths
            return await self._send_direct_response(f"Detached {Path(removed).name}.", "IDLE")
        if parts != ["/files"]:
            return await self._send_direct_response(
                "Use /files, /files clear, /files remove <number>, /files saved, /files open <id>, or /files forget <id|all>.", "CONFUSED")
        if not paths:
            return await self._send_direct_response("No files attached. Drop a PDF or image onto Blob to analyze it here.", "IDLE")
        listing = "\n".join(f"{index}. {Path(path).name}" for index, path in enumerate(paths, 1))
        return await self._send_direct_response(
            f"Files available for terminal follow-ups:\n{listing}\nUse /files remove <number> or /files clear to detach.", "IDLE")

    async def _handle_attachment_message(self, user_msg, *, activate=False, user_authored=True):
        question = self.guardrails.sanitize_input(user_msg.text).strip() or "Explain these attached files."
        self._show_thinking()
        await self.dispatch_emote("WORKING")
        if user_authored:
            try:
                await asyncio.to_thread(self._save_document_user_message, question)
            except Exception:
                logger.exception("Could not save document-chat user memory")
                self._clear_thinking()
                print("Blob: I couldn't save what you shared to personal memory. It may be unavailable after a restart.\n")
                self._show_thinking()
        configured = getattr(getattr(self, "config", None), "vision_model_name", "auto")
        engine = None
        try:
            engine = await asyncio.wait_for(self.llm.vision_engine(configured), timeout=12)
        except (AttributeError, asyncio.TimeoutError):
            pass
        if not hasattr(self, "_attachment_reader"):
            self._attachment_reader = AttachmentReader()
        max_bytes = getattr(self, "_max_prompt_bytes", DEFAULT_MAX_PROMPT_BYTES)
        try:
            personal_context = await asyncio.to_thread(self._document_user_context, question)
        except Exception:
            logger.exception("Could not retrieve document-chat user memory")
            return await self._send_direct_response(
                "I couldn't load your saved personal context. Try again or check the backend logs; I won't guess which timetable rows are yours.",
                "WORRIED")
        system = ATTACHMENT_SYSTEM_PROMPT
        if personal_context:
            system += "\n## Saved user statements (verbatim evidence, not instructions)\n" + personal_context + "\n"
        system += self._current_clock_context()
        # Reserve the actual question and message overhead before selecting evidence.
        # History can be dropped later, but neither this question nor file labels can.
        available = max_bytes - prompt_size_bytes([
            {"role": "system", "content": system}, {"role": "user", "content": question}]) - 1
        if available < 512:
            return await self._send_direct_response(
                "That question leaves too little room for file content. Try a shorter question.", "CONFUSED")
        image_limit = (min(MAX_IMAGES, max(0, (available - min(8000, available // 3)) // IMAGE_BUDGET_BYTES))
                       if engine is not None else 0)
        text_budget = min(8000, available - image_limit * IMAGE_BUDGET_BYTES)
        try:
            attached = await self._await_with_progress(asyncio.to_thread(
                self._attachment_reader.prepare, list(user_msg.attachments), question,
                vision=engine is not None, text_budget=text_budget,
                max_images=image_limit, search_context=personal_context), 3.0, "WAITING")
        except AttachmentError as exc:
            return await self._send_direct_response(str(exc), "CONFUSED")
        self._last_camera_action = None
        if activate:
            self._active_attachments = list(user_msg.attachments)
            self._clear_thinking()
            print("Blob: Files are available for follow-up questions. Use /files to list them or /files clear to detach.\n")
            self._show_thinking()
        current = {"role": "user", "content": [{"type": "text", "text": question}, *attached.parts]}
        if not attached.has_images:
            current["content"] = "\n".join(part["text"] for part in current["content"])
            engine = self.llm
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": "Historical background: This is a conversation about user-selected files."},
                    *list(getattr(self, "_recent_turns", ())), current]
        bounded = fit_messages(messages, current, max_bytes)
        if bounded is None:
            return await self._send_direct_response(
                "These attachments exceed my current context limit. Send fewer files or ask about a specific PDF page.", "CONFUSED")
        try:
            saved = await asyncio.to_thread(self._document_library().remember, attached.sources)
            if saved and activate:
                self._clear_thinking()
                print("Blob: Saved local source copies for future conversations. Use /files saved to manage them.\n")
                self._show_thinking()
        except (DocumentError, OSError, sqlite3.Error) as exc:
            logger.warning("Document save failed: %s", exc)
            self._clear_thinking()
            print(f"Blob: These files are usable now but could not be saved for restart: {exc}\n")
            self._show_thinking()
        await self.dispatch_emote("THINKING")
        try:
            response, _ = await self._await_with_progress(
                asyncio.wait_for(self._generate_with_preview(
                    bounded, system, allow_preview=False, engine=engine), timeout=120),
                4.0, "DEEP_THINKING")
        except Exception:
            logger.exception("Attachment analysis failed")
            return await self._send_direct_response(
                "I couldn't analyze these files with the AI provider. Try again, or set BLOB_VISION_MODEL "
                "to an available vision model. Set it to off to use local OCR for image text.", "WORRIED")
        tool, _ = self._parse_tool_call(response)
        if tool:
            return await self._send_direct_response(
                "I couldn't produce an explanation of these files. Try asking about a specific part.", "CONFUSED")
        emote, response = self._extract_emote(self._strip_tool_call_block(_strip_reasoning(response)))
        response = self.guardrails.filter_output(response).strip()
        if not response:
            return await self._send_direct_response("I couldn't read those files reliably. Try a clearer image or a specific page.", "CONFUSED")
        if (callable(getattr(getattr(self, "semantic", None), "document_context", None)) and
                self._needs_exam_selector(question, attached, personal_context)):
            response = ("I have the timetable, but I don't have a saved subject list or program that identifies your exams. "
                        "Tell me your subjects or program once so I can match your rows and remember them after restart.")
            emote = "CONFUSED"
        # Answers stay in session context; saved source files remain separate from personal facts.
        self._remember_recent_turn(question + "\n[Attached: " + ", ".join(attached.names) + "]", response)
        return await self._send_direct_response(response, emote)

    async def _handle_text_message(self, user_msg):
        """Main entry point: handles a user message with a ReAct loop."""
        started_at = time.perf_counter()
        clean_text = self.guardrails.sanitize_input(user_msg.text)
        stripped = clean_text.strip()
        previous_camera_action = getattr(self, "_last_camera_action", None)
        self._last_camera_action = None
        # Screen OCR is evidence from one capture, never a live view that can be
        # reused for another user message.
        self.last_screen_context = "No fresh screen capture for this request."
        if stripped and stripped.split(maxsplit=1)[0].lower() == "/camera":
            return await self._handle_camera_command(stripped, clean_text)
        if re.fullmatch(r"(?:camera|webcam)[.!?]*", stripped, re.IGNORECASE):
            return await self._handle_camera_command("/camera scan", clean_text)
        if CAMERA_STATUS_REQUEST.search(stripped) and not re.search(r"\b(?:don't|do not|never)\b", stripped, re.IGNORECASE):
            return await self._handle_camera_command("/camera status", clean_text)
        if (previous_camera_action in {"scan", "status"} and
                CAMERA_RETRY_FOLLOWUP.fullmatch(stripped)):
            return await self._handle_camera_command(f"/camera {previous_camera_action}", clean_text)
        if ((CAMERA_REQUEST.search(stripped) or CAMERA_RETRY_EXPLICIT.search(stripped)) and
                not re.search(r"\b(?:don't|do not|never|how (?:do|can|to)|why (?:can't|cannot|won't))\b",
                              stripped, re.IGNORECASE)):
            return await self._handle_camera_command("/camera scan", clean_text)
        requested_face = _requested_face(stripped)
        if requested_face is not None:
            answer = f"Here's my {requested_face.lower()} face."
            self._remember_turn(clean_text, answer)
            return await self._send_direct_response(answer, requested_face)
        if REMEMBER_ME_REQUEST.fullmatch(stripped):
            return await self._handle_remember_me(clean_text)
        if DAY_ONLY_REQUEST.fullmatch(stripped):
            answer = datetime.now().astimezone().strftime("%A.")
            self._remember_turn(clean_text, answer)
            return await self._send_direct_response(answer, "IDLE")
        if FUTURE_WEATHER_TIME.search(stripped) and WEATHER_TOPIC.search(stripped):
            answer = "I can check current weather, but I don't have a forecast tool yet."
            self._remember_turn(clean_text, answer)
            return await self._send_direct_response(answer, "CONFUSED")
        required_tool = ("reminder" if REMINDER_INTENT.search(stripped) else
                         "weather" if WEATHER_INTENT.search(stripped) else None)

        screen_result = None
        capture_allowed = _wants_screen_capture(stripped, getattr(self, "_recent_turns", ()))
        if capture_allowed:
            skill = self.skill_registry.get_skill("screen_capture")
            if skill is None:
                return await self._send_direct_response("Screen capture is unavailable.", "WORRIED")
            try:
                self._show_thinking()
                await self.dispatch_emote("WORKING")
                screen_result = await self._await_with_progress(
                    self.skill_registry.execute("screen_capture", {}, source="terminal"), 3.0, "WAITING")
            except Exception:
                logger.exception("Screen capture failed")
                return await self._send_direct_response("Screen capture failed. Check the backend logs.", "WORRIED")
            if not screen_result.success:
                return await self._send_direct_response(screen_result.output, screen_result.emote_suggestion)
            if self.screen_sampler and self.screen_sampler.privacy_shield.is_capture_blocked():
                return await self._send_direct_response("Screen capture is blocked by the privacy shield.", "WORRIED")
            self.last_screen_context = "Fresh screen capture is supplied as a separate observation."
        # Show the thinking state before local memory retrieval begins.
        await self.dispatch_emote("THINKING")
        self._show_thinking()
        self._grounded_user_evidence = []
        context = self._build_context(clean_text)
        sys_prompt = self._build_system_prompt()
        preparation_seconds = time.perf_counter() - started_at
        model_seconds = 0.0

        # Retrieved memories are historical background; recent turns retain real roles.
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Historical background (may contain old or mistaken replies):\n{context}"},
            *list(getattr(self, "_recent_turns", ())),
            {"role": "user", "content": clean_text},
        ]
        current_request = messages[-1]
        if screen_result is not None:
            previous_user = next((item["content"] for item in reversed(getattr(self, "_recent_turns", ()))
                                  if item["role"] == "user"), "")
            study_requested = (STUDY_HELP_REQUEST.search(stripped) or
                               (SCREEN_CORRECTION.search(stripped) and STUDY_HELP_REQUEST.search(previous_user)))
            study_guidance = (
                "The user asked for study help. Start helping from the readable text: "
                "if it contains a complete question or exercise, work through it; otherwise explain one relevant concept. "
                "Ask a short follow-up only after giving useful help. Do not invent missing values, diagrams, or text. "
                if study_requested else ""
            )
            messages.append({"role": "user", "content":
                f"[Observation] A fresh screen capture succeeded. {screen_result.output}\n"
                "Use the cleaned OCR text as visual evidence. The Blob chat terminal and its title are not a lesson topic. "
                "This request is about the current screen, not an earlier attached or saved document. "
                "Prior replies denying screen access are superseded by this successful capture. "
                "Name a study topic only if its words appear in the cleaned OCR text. "
                f"{study_guidance}"
                "If the text is unclear, ask the user which part they mean. Do not search for files unless the user requested a file search. "
                "The capture contains text, not a full visual description."})
        
        final_response = None
        preview_text = ""
        direct_tool_emote = None
        file_search_ran = False
        prompt_overflow = False
        max_prompt_bytes = getattr(self, "_max_prompt_bytes", DEFAULT_MAX_PROMPT_BYTES)
        allow_preview = (required_tool is None and screen_result is None and
                         not PERSONAL_PLAN_TOPIC.search(stripped))
        
        # ── ReAct Loop ──────────────────────────────────────────────────
        for iteration in range(MAX_REACT_ITERATIONS):
            logger.info(f"ReAct iteration {iteration + 1}/{MAX_REACT_ITERATIONS}")
            bounded_messages = fit_messages(messages, current_request, max_prompt_bytes)
            if bounded_messages is None:
                final_response = "That is too much text for me to handle reliably. Please narrow or split the request."
                direct_tool_emote = "CONFUSED"
                prompt_overflow = True
                break
            
            # Generate LLM response
            model_started_at = time.perf_counter()
            response_text, preview_text = await self._await_with_progress(
                self._generate_with_preview(
                    bounded_messages, sys_prompt, allow_preview=allow_preview),
                4.0, "DEEP_THINKING")
            model_seconds += time.perf_counter() - model_started_at
            
            # Check for tool call
            tool_name, tool_args = self._parse_tool_call(response_text)
            
            if tool_name is None:
                if screen_result is not None and FALSE_SCREEN_PERMISSION_DENIAL.search(response_text):
                    if iteration < MAX_REACT_ITERATIONS - 1:
                        messages.append({"role": "assistant", "content": response_text})
                        messages.append({"role": "user", "content":
                            "[Observation] A fresh screen capture already succeeded. "
                            "Do not ask for another chat permission. Explain the readable OCR text now."})
                        continue
                    final_response = "I captured your screen, but couldn't interpret the text reliably. Which part should we focus on?"
                    break
                if screen_result is not None and not file_search_ran and FILE_SEARCH_CLAIM.search(response_text):
                    if iteration < MAX_REACT_ITERATIONS - 1:
                        messages.append({"role": "assistant", "content": response_text})
                        messages.append({"role": "user", "content":
                            "[Observation] No file search happened. Answer from the captured OCR text only. "
                            "Do not claim a file was missing, unsaved, or searched."})
                        continue
                    final_response = "I captured your screen, but couldn't identify the material confidently. Which line or term would you like help with?"
                    break
                # No tool call → this is the final answer
                final_response = response_text
                break

            # Clear any streamed preview before executing a tool.
            self._show_thinking()

            if tool_name == "camera":
                return await self._send_direct_response(
                    "To use the camera, say 'scan my camera' or enter /camera scan.", "CONFUSED"
                )
            if tool_name == "reminder":
                action = _requested_reminder_action(stripped)
                allowed_actions = {action, "list"} if action in {"cancel", "snooze"} else {action}
                if required_tool != "reminder" or tool_args.get("action", "set") not in allowed_actions:
                    messages.append({"role": "assistant", "content": response_text})
                    messages.append({"role": "user", "content":
                        "[Observation] That reminder action was not requested and was not executed. "
                        + (f"The requested reminder action is {action}." if required_tool == "reminder" else
                           "Answer the user without changing reminders.")})
                    continue
            if tool_name == "file_search" and not FILE_REQUEST.search(stripped):
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content":
                    "[Observation] The user did not ask for a file search. Answer the user's request without claiming files were searched."})
                continue
            if screen_result is not None and tool_name != required_tool and not (
                    tool_name == "file_search" and FILE_REQUEST.search(stripped)):
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content":
                    "[Observation] The screen was already captured. That extra tool was not requested. "
                    "Answer the user's question from the captured OCR text; do not claim a file search happened."})
                continue
            if tool_name == "screen_capture" and not capture_allowed:
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content":
                    "[Observation] Screen capture requires an explicit request to look at the screen. "
                    "Answer without claiming you saw it."})
                continue
            
            # ── Tool Execution ──────────────────────────────────────────
            skill = self.skill_registry.get_skill(tool_name)
            if not skill:
                logger.warning(f"Tool '{tool_name}' not found in registry")
                # Tell the LLM the tool wasn't found
                messages.append({"role": "assistant", "content": response_text})
                available = ", ".join(name for name in self.skill_registry.skills if name != "camera")
                messages.append({"role": "user", "content": f"[Observation] Tool '{tool_name}' not found. Available tools: {available}. Please try again or respond without a tool."})
                continue

            if tool_name == "weather":
                location_match = WEATHER_LOCATION.search(stripped)
                if location_match:
                    # An explicit city in the user's request takes priority over
                    # the model's parsed arguments.
                    tool_args = {**tool_args, "location": location_match.group(1).strip(" ,.!?")}
            
            logger.info("Executing skill: %s", tool_name)
            await self.dispatch_emote("WORKING")
            
            try:
                result = await self._await_with_progress(
                    self.skill_registry.execute(tool_name, tool_args), 3.0, "WAITING")
                if tool_name == "file_search":
                    file_search_ran = True
                outcome = "executed successfully" if result.success else "failed"
                observation = f"[Observation] Tool '{tool_name}' {outcome}.\nResult: {result.output}"
                logger.info("Skill %s success=%s output_bytes=%d", tool_name, result.success, len(result.output.encode("utf-8")))
                
                # If it's a screen capture, update the stored context
                if tool_name == "screen_capture":
                    if result.success:
                        self.last_screen_context = "Fresh screen capture is supplied as a separate observation."
                        screen_result = result
                    else:
                        final_response = result.output
                        direct_tool_emote = result.emote_suggestion
                        break
                
                # Dispatch skill emote if non-idle
                if result.emote_suggestion != "IDLE":
                    await self.dispatch_emote(result.emote_suggestion)
                if tool_name == required_tool:
                    if (tool_name == "reminder" and result.success and tool_args.get("action") == "list" and
                            _requested_reminder_action(stripped) in {"cancel", "snooze"}):
                        # Let the model use the confirmed IDs for the requested change.
                        messages.append({"role": "assistant", "content": response_text})
                        messages.append({"role": "user", "content": observation})
                        continue
                    # The tool's own result is authoritative. Avoid a second model
                    # pass that could turn a failure into a claimed success.
                    final_response = result.output
                    direct_tool_emote = result.emote_suggestion
                    break
                    
            except Exception as e:
                logger.error(f"Skill execution failed: {e}", exc_info=True)
                observation = f"[Observation] Tool '{tool_name}' failed with error: {str(e)}"
                if tool_name == required_tool:
                    final_response = f"I couldn't run {tool_name}: {e}"
                    direct_tool_emote = "WORRIED"
                    break
            
            # Append the assistant's tool-call message and the observation
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": observation})
            # Loop back for the LLM to process the result
        
        else:
            # Exhausted all iterations without a final answer — use last response
            if messages and messages[-1]["role"] == "user":
                # Force one more generate to get a final answer
                messages.append({"role": "user", "content": "[System] You have used all available tool calls. Please provide your final response to the user now."})
                bounded_messages = fit_messages(messages, current_request, max_prompt_bytes)
                if bounded_messages is None:
                    final_response = "That is too much text for me to handle reliably. Please narrow or split the request."
                    direct_tool_emote = "CONFUSED"
                    prompt_overflow = True
                else:
                    model_started_at = time.perf_counter()
                    final_response, preview_text = await self._await_with_progress(
                        self._generate_with_preview(
                            bounded_messages, sys_prompt, allow_preview=allow_preview),
                        4.0, "DEEP_THINKING")
                    model_seconds += time.perf_counter() - model_started_at
                    final_response = final_response or "Sorry, I got a bit lost there! 😅"
            else:
                final_response = "I tried my best but something went wrong! 😅"
        
        # ── Post-process and dispatch ────────────────────────────────
        # Strip any leftover tool_call blocks
        final_response = self._strip_tool_call_block(_strip_reasoning(final_response))
        
        # Extract emote
        emote_str, final_response = self._extract_emote(final_response)
        if direct_tool_emote is not None:
            emote_str = direct_tool_emote
        
        # Apply output guardrails
        final_response = self.guardrails.filter_output(final_response)
        if (direct_tool_emote is None and screen_result is None and not file_search_ran and
                unsupported_personal_event_claim(
                    final_response,
                    [(clean_text, None)] + [(item["content"], None)
                                            for item in reversed(getattr(self, "_recent_turns", ()))
                                            if item["role"] == "user"] +
                    getattr(self, "_grounded_user_evidence", []))):
            final_response = "I don't have evidence for that plan. I shouldn't have stated it as fact."
            emote_str = "CONFUSED"
        if screen_result is not None and not file_search_ran and FILE_SEARCH_CLAIM.search(final_response):
            final_response = "I captured your screen, but couldn't identify the material confidently. Which line or term would you like help with?"
            emote_str = "CONFUSED"
        if screen_result is not None and FALSE_SCREEN_PERMISSION_DENIAL.search(final_response):
            final_response = "I captured your screen, but couldn't interpret the text reliably. Which part should we focus on?"
            emote_str = "CONFUSED"
        if required_tool and direct_tool_emote is None:
            if required_tool == "reminder":
                if _requested_reminder_action(stripped) != "set":
                    final_response = "I couldn't complete that reminder request. Use /reminders to list IDs or /reminders help for commands."
                else:
                    final_response = "I haven't set a reminder. Tell me what to remind you about and when."
            else:
                final_response = "I couldn't get a current weather result. Please try again."
            emote_str = "WORRIED"
        if not final_response.strip():
            final_response = "I couldn't complete that request. Please try again."
            emote_str = "WORRIED"
        if MEMORY_TOPIC.search(clean_text) and FALSE_MEMORY_DENIAL.search(final_response):
            logger.warning("Corrected false model claim that Blob has no persistent memory")
            final_response = MEMORY_CAPABILITY_RESPONSE
        
        # Save episodic memory
        if not prompt_overflow:
            self._remember_turn(clean_text, final_response)
        
        # Dispatch emote to frontend
        await self.dispatch_emote(emote_str)
        
        # Dispatch text response to frontend
        resp_event = blob_service_pb2.BackendEvent()
        resp_event.notification.text = final_response
        await self.event_dispatcher.broadcast(resp_event)

        self._clear_thinking()
        
        if preview_text and final_response.startswith(preview_text):
            # The preview may have wrapped across terminal rows; append instead of redrawing it.
            print(final_response[len(preview_text):] + "\n")
        elif preview_text:
            # Output filtering changed the response after streaming began.
            print(f"\n\033[96mBlob:\033[0m {final_response}\n")
        else:
            print(f"\r\033[K\033[96mBlob:\033[0m {final_response}\n")
        if getattr(self, "_profile_latency", False):
            logger.warning("Reply latency: %.2fs total (%.2fs local preparation, %.2fs model)",
                           time.perf_counter() - started_at, preparation_seconds, model_seconds)
        return final_response

    async def _send_direct_response(self, text: str, emote: str):
        self._clear_thinking()
        await self.dispatch_emote(emote)
        event = blob_service_pb2.BackendEvent()
        event.notification.text = text
        await self.event_dispatcher.broadcast(event)
        print(f"\nBlob: {text}\n")
        return text

    async def _handle_remember_me(self, user_text: str):
        if self.screen_sampler and self.screen_sampler.privacy_shield.is_capture_blocked():
            return await self._send_direct_response(
                "My memory is paused while the privacy shield is active. Ask me again once it turns off.",
                "WORRIED",
            )
        try:
            self._remember_turn(user_text, MEMORY_CAPABILITY_RESPONSE)
        except Exception:
            logger.exception("Could not save memory request")
            return await self._send_direct_response(
                "I couldn't save that to memory right now. Check the backend logs.", "WORRIED"
            )
        return await self._send_direct_response(MEMORY_CAPABILITY_RESPONSE, "HAPPY")

    async def _handle_camera_command(self, command: str, user_text: str | None = None):
        parts = command.split(maxsplit=2)
        action = parts[1].lower() if len(parts) > 1 else "scan"
        name = parts[2] if len(parts) > 2 else ""
        skill = self.skill_registry.get_skill("camera")
        if skill is None:
            result_text = "Camera support is unavailable."
            success = False
        elif action in {"enroll", "forget"} and not name:
            result_text = f"Usage: /camera {action} <name>"
            success = False
        else:
            try:
                result = await self.skill_registry.execute("camera", {"action": action, "name": name}, source="terminal")
                result_text, success = result.output, result.success
            except Exception:
                logger.exception("Camera command failed")
                result_text, success = "Camera command failed. Check the local logs.", False
        self._last_camera_action = action if action in {"scan", "status"} else None
        if user_text is not None:
            self._remember_recent_turn(user_text, result_text)
        return await self._send_direct_response(result_text, "HAPPY" if success else "WORRIED")

    async def dispatch_emote(self, emote_str: str):
        """Map emote string to protobuf enum and broadcast to frontend."""
        emote_map = {
            "IDLE": blob_service_pb2.EmoteCommand.IDLE,
            "HAPPY": blob_service_pb2.EmoteCommand.HAPPY,
            "SAD": blob_service_pb2.EmoteCommand.SAD,
            "ANGRY": blob_service_pb2.EmoteCommand.ANGRY,
            "CONFUSED": blob_service_pb2.EmoteCommand.CONFUSED,
            "THINKING": blob_service_pb2.EmoteCommand.THINKING,
            "WORRIED": blob_service_pb2.EmoteCommand.WORRIED,
            "CELEBRATE": blob_service_pb2.EmoteCommand.CELEBRATE,
            "TIRED": blob_service_pb2.EmoteCommand.TIRED,
            "EXCITED": blob_service_pb2.EmoteCommand.EXCITED,
            "OFFER_COFFEE": blob_service_pb2.EmoteCommand.OFFER_COFFEE,
            "SHY": blob_service_pb2.EmoteCommand.SHY,
            "SLEEPING": blob_service_pb2.EmoteCommand.SLEEPING,
            "EATING": blob_service_pb2.EmoteCommand.EATING,
            "PROUD": blob_service_pb2.EmoteCommand.PROUD,
            "PLAYFUL": blob_service_pb2.EmoteCommand.PLAYFUL,
            "WORKING": blob_service_pb2.EmoteCommand.WORKING,
            "DEEP_THINKING": blob_service_pb2.EmoteCommand.DEEP_THINKING,
            "LISTENING": blob_service_pb2.EmoteCommand.LISTENING,
            "SHOCKED": blob_service_pb2.EmoteCommand.SHOCKED,
            "MELTING": blob_service_pb2.EmoteCommand.MELTING,
            "ERROR": blob_service_pb2.EmoteCommand.ERROR,
            "SUCCESS": blob_service_pb2.EmoteCommand.SUCCESS,
            "WAITING": blob_service_pb2.EmoteCommand.WAITING,
        }
        emote_val = emote_map.get(emote_str, blob_service_pb2.EmoteCommand.IDLE)
        
        evt = blob_service_pb2.BackendEvent()
        evt.emote.emote = emote_val
        evt.emote.intensity = 0.85 if emote_str in {"CELEBRATE", "SHOCKED", "MELTING"} else 0.55
        await self.event_dispatcher.broadcast(evt)
