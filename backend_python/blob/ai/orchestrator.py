import asyncio
from collections import deque
from datetime import datetime
import logging
import json
import inspect
import os
import re
import time
from blob.ai.llm_engine import NebiusEngine
from blob.ipc import blob_service_pb2
from blob.ai.guardrails import GuardrailsEngine
from blob.ai.prompt_templates import SYSTEM_PROMPT, CONTEXT_TEMPLATE
from blob.memory.episodic import EpisodicMemory
from blob.memory.semantic import SemanticMemory, is_temporary_fact
from blob.memory.context import build_memory_view

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 3
STYLE_CACHE_TTL_SECONDS = 30
STYLE_QUERY = "How does the user want Blob to speak to them: friendly buddy, formal, professional, direct, or quiet?"
EMOTE_NAMES = "IDLE|HAPPY|SAD|ANGRY|CONFUSED|THINKING|WORRIED|CELEBRATE|EXCITED|TIRED|OFFER_COFFEE|SHY|SLEEPING|EATING|PROUD|PLAYFUL"
EMOTE_MARKER = re.compile(rf"<emote>\s*({EMOTE_NAMES})\s*</emote>|\(({EMOTE_NAMES})\)", re.IGNORECASE)
CAMERA_REQUEST = re.compile(
    r"\b(?:open|turn on|switch on|start|use|scan|check|share|access|view|see|look through|look at|see through)\b"
    r".{0,35}\b(?:camera|webcam)\b|\bturn\b.{0,15}\b(?:camera|webcam)\b\s+on\b",
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
    r"|\b(?:screen|desktop|display)\b.{0,30}\b(?:what(?:'s| is) on|look|check|read|describe|capture|see)\b",
    re.IGNORECASE,
)
REMEMBER_ME_REQUEST = re.compile(
    r"^(?:(?:can|will|could|would|do) you |please |i want you to )?remember me"
    r"(?: (?:tomorrow|next time|after (?:a |the )?restart))?[.!?]*$",
    re.IGNORECASE,
)
MEMORY_TOPIC = re.compile(r"\b(?:remember|memory|recall|retain)\b", re.IGNORECASE)
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
    # A stream chunk may stop in the middle of a control tag.
    return re.sub(r"<[^>]*$", "", text).rstrip()


class BlobOrchestrator:
    def __init__(self, config, vector_store, skill_registry, event_dispatcher, screen_sampler=None):
        self.config = config
        self.vector_store = vector_store
        self.skill_registry = skill_registry
        self.event_dispatcher = event_dispatcher
        self.screen_sampler = screen_sampler
        self.guardrails = GuardrailsEngine(config)
        self.llm = NebiusEngine(config.nebius_api_key, config.nebius_base_url, config.model_name)
        
        self.episodic = EpisodicMemory(vector_store)
        self.semantic = SemanticMemory(vector_store, self.llm)
        self._style_facts_cache = None
        self._style_facts_revision = None
        self._style_facts_cached_at = 0.0
        self._profile_latency = os.environ.get("BLOB_PROFILE_LATENCY", "").lower() in {"1", "true", "yes", "on"}
        self._streaming_disabled = False
        self._recent_turns = deque(maxlen=12)
        
        # Holds the latest screen context text (populated by ScreenCaptureSkill or sampler)
        self.last_screen_context = "No screen data captured yet."

    def _build_skills_text(self) -> str:
        """Format registered skills for the system prompt."""
        lines = []
        for name, skill in self.skill_registry.skills.items():
            if name == "camera":
                continue  # Camera commands require explicit user text, never an LLM tool call.
            lines.append(f"- **{name}**: {skill.description}")
        return "\n".join(lines) if lines else "No tools available."

    def _build_system_prompt(self) -> str:
        """Build the full system prompt with skills injected."""
        skills_text = self._build_skills_text()
        now = datetime.now().astimezone()
        clock = now.strftime("%A, %Y-%m-%d %H:%M %Z (%z)")
        return SYSTEM_PROMPT.replace("{skills}", skills_text) + f"\n## Current local date and time\n{clock}\n"

    def _remember_turn(self, user_text: str, reply: str) -> None:
        if self.screen_sampler and self.screen_sampler.privacy_shield.is_capture_blocked():
            return
        self.episodic.add_episode(user_text, reply)
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
            self._style_facts_cache = self.semantic.recall_facts(STYLE_QUERY, top_k=2)
            self._style_facts_revision = revision
            self._style_facts_cached_at = now
        return self._style_facts_cache

    def _build_context(self, clean_text: str) -> str:
        """Build the context block with memories, active window, and screen data."""
        episodes = self.episodic.recall_relevant(clean_text, top_k=5)
        facts = self.semantic.recall_facts(clean_text, top_k=3)
        # Tone preferences must remain in view even when the current question
        # is about an unrelated task.
        style_facts = self._get_style_facts()
        fact_texts = [item["text"] for item in style_facts + facts if not is_temporary_fact(item["text"])]
        episode_texts = [item["text"] for item in episodes]
        # Old assistant replies are not evidence for ordinary questions. Include
        # them only when the user explicitly asks what Blob said before.
        fact_view, episode_view = build_memory_view(
            fact_texts, episode_texts, clean_text,
            user_only=not bool(ASSISTANT_HISTORY_REQUEST.search(clean_text)),
            recall_mode=bool(MEMORY_TOPIC.search(clean_text) or ASSISTANT_HISTORY_REQUEST.search(clean_text)),
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
        """Extract a tool_call JSON block from the LLM response.
        
        Supports:
        - ```tool_call ... ```
        - ```json ... ``` (with "tool")
        - Raw JSON containing "tool" and "args"
        - Automatically unescapes {{ ... }} if present
        
        Returns (tool_name, tool_args) or (None, None) if no valid tool call found.
        """
        patterns = [
            r'```(?:tool_call|json)?\s*(\{.*?\})\s*```',
            r'(\{\s*"tool"\s*:\s*".*?"\s*,\s*"args"\s*:\s*\{.*?\}\s*\})',
            r'(\{\{\s*"tool"\s*:\s*".*?"\s*,\s*"args"\s*:\s*\{.*?\}\s*\}\})'
        ]
        
        for pat in patterns:
            match = re.search(pat, response_text, re.DOTALL)
            if match:
                raw_json = match.group(1).strip()
                if raw_json.startswith("{{") and raw_json.endswith("}}"):
                    raw_json = raw_json[1:-1]
                try:
                    tool_data = json.loads(raw_json)
                    tool_name = tool_data.get('tool')
                    tool_args = tool_data.get('args', {})
                    if tool_name:
                        return tool_name, tool_args
                except (json.JSONDecodeError, AttributeError) as e:
                    logger.debug(f"Failed parsing matched tool JSON: {e}")
                    continue
        
        return None, None

    def _strip_tool_call_block(self, text: str) -> str:
        """Remove tool call blocks and raw tool JSON from text for display."""
        text = re.sub(r'```(?:tool_call|json)?\s*\{.*?\}\s*```', '', text, flags=re.DOTALL)
        text = re.sub(r'\{\{?\s*"tool"\s*:.*?"args"\s*:.*?\}\}?', '', text, flags=re.DOTALL)
        return text.strip()

    def _extract_emote(self, text: str) -> tuple[str, str]:
        """Keep model mood markers for the slime, never for the chat text."""
        matches = list(EMOTE_MARKER.finditer(text))
        emote = (matches[-1].group(1) or matches[-1].group(2)).upper() if matches else "IDLE"
        return emote, EMOTE_MARKER.sub("", text).strip()

    async def _generate_with_preview(self, messages: list[dict], system_prompt: str) -> tuple[str, str]:
        stream = getattr(self.llm, "generate_from_messages_stream", None)
        if getattr(self, "_streaming_disabled", False) or not inspect.isasyncgenfunction(stream):
            msg = await self.llm.generate_from_messages(messages, system_prompt)
            return msg.content or "", ""

        response = ""
        preview = ""
        preview_started = False
        try:
            async for part in stream(messages, system_prompt):
                response += part
                head = _visible_preview(response).lstrip()
                # Tool calls are text blocks in this protocol. Keep them out of the terminal.
                if not head or head.startswith(("```", "{")) or "```".startswith(head):
                    continue
                # Hold the tail so incomplete control tags cannot reach the terminal.
                safe = _visible_preview(response[:-32])
                if len(safe) > len(preview):
                    if not preview_started:
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
            msg = await self.llm.generate_from_messages(messages, system_prompt)
            return msg.content or "", ""
        return response, preview

    async def handle_user_message(self, user_msg):
        """Main entry point: handles a user message with a ReAct loop."""
        started_at = time.perf_counter()
        clean_text = self.guardrails.sanitize_input(user_msg.text)
        stripped = clean_text.strip()
        if stripped and stripped.split(maxsplit=1)[0].lower() == "/camera":
            return await self._handle_camera_command(stripped)
        if re.fullmatch(r"(?:camera|webcam)[.!?]*", stripped, re.IGNORECASE):
            return await self._handle_camera_command("/camera scan")
        if CAMERA_STATUS_REQUEST.search(stripped) and not re.search(r"\b(?:don't|do not|never)\b", stripped, re.IGNORECASE):
            return await self._handle_camera_command("/camera status")
        if CAMERA_REQUEST.search(stripped) and not re.search(r"\b(?:don't|do not|never|how (?:do|can|to))\b", stripped, re.IGNORECASE):
            return await self._handle_camera_command("/camera scan")
        if REMEMBER_ME_REQUEST.fullmatch(stripped):
            return await self._handle_remember_me(clean_text)
        if DAY_ONLY_REQUEST.fullmatch(stripped):
            answer = datetime.now().astimezone().strftime("%A.")
            self._remember_turn(clean_text, answer)
            return await self._send_direct_response(answer, "IDLE")

        screen_result = None
        if (SCREEN_REQUEST.search(stripped) or stripped.lower() in {"/screen", "/screenshot"}) and not re.search(r"\b(?:don't|do not|never)\b", stripped, re.IGNORECASE):
            skill = self.skill_registry.get_skill("screen_capture")
            if skill is None:
                return await self._send_direct_response("Screen capture is unavailable.", "WORRIED")
            try:
                screen_result = await skill.async_execute({})
            except Exception:
                logger.exception("Screen capture failed")
                return await self._send_direct_response("Screen capture failed. Check the backend logs.", "WORRIED")
            if not screen_result.success:
                return await self._send_direct_response(screen_result.output, screen_result.emote_suggestion)
            if self.screen_sampler and self.screen_sampler.privacy_shield.is_capture_blocked():
                return await self._send_direct_response("Screen capture is blocked by the privacy shield.", "WORRIED")
            self.last_screen_context = screen_result.output
        # Show the thinking state before local memory retrieval begins.
        await self.dispatch_emote("THINKING")
        print("\033[90m(Thinking...)\033[0m", end="", flush=True)
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
        if screen_result is not None:
            messages.append({"role": "user", "content":
                f"[Observation] A fresh screen capture succeeded. {screen_result.output}\n"
                "Answer using this result. It contains OCR text and the active window title, not a full visual description. "
                "Do not claim screen access is unavailable."})
        
        final_response = None
        preview_text = ""
        
        # ── ReAct Loop ──────────────────────────────────────────────────
        for iteration in range(MAX_REACT_ITERATIONS):
            logger.info(f"ReAct iteration {iteration + 1}/{MAX_REACT_ITERATIONS}")
            
            # Generate LLM response
            model_started_at = time.perf_counter()
            response_text, preview_text = await self._generate_with_preview(messages, sys_prompt)
            model_seconds += time.perf_counter() - model_started_at
            
            # Check for tool call
            tool_name, tool_args = self._parse_tool_call(response_text)
            
            if tool_name is None:
                # No tool call → this is the final answer
                final_response = response_text
                break

            # Clear any streamed preview before executing a tool.
            print("\r\033[K\033[90m(Thinking...)\033[0m", end="", flush=True)

            if tool_name == "camera":
                return await self._send_direct_response(
                    "To use the camera, say 'scan my camera' or enter /camera scan.", "CONFUSED"
                )
            
            # ── Tool Execution ──────────────────────────────────────────
            skill = self.skill_registry.get_skill(tool_name)
            if not skill:
                logger.warning(f"Tool '{tool_name}' not found in registry")
                # Tell the LLM the tool wasn't found
                messages.append({"role": "assistant", "content": response_text})
                available = ", ".join(name for name in self.skill_registry.skills if name != "camera")
                messages.append({"role": "user", "content": f"[Observation] Tool '{tool_name}' not found. Available tools: {available}. Please try again or respond without a tool."})
                continue
            
            logger.info(f"Executing skill: {tool_name} with args: {tool_args}")
            
            try:
                result = await skill.async_execute(tool_args)
                outcome = "executed successfully" if result.success else "failed"
                observation = f"[Observation] Tool '{tool_name}' {outcome}.\nResult: {result.output}"
                logger.info(f"Skill result: {result.output[:200]}")
                
                # If it's a screen capture, update the stored context
                if tool_name == "screen_capture" and result.success:
                    self.last_screen_context = result.output
                
                # Dispatch skill emote if non-idle
                if result.emote_suggestion != "IDLE":
                    await self.dispatch_emote(result.emote_suggestion)
                    
            except Exception as e:
                logger.error(f"Skill execution failed: {e}", exc_info=True)
                observation = f"[Observation] Tool '{tool_name}' failed with error: {str(e)}"
            
            # Append the assistant's tool-call message and the observation
            messages.append({"role": "assistant", "content": response_text})
            messages.append({"role": "user", "content": observation})
            # Loop back for the LLM to process the result
        
        else:
            # Exhausted all iterations without a final answer — use last response
            if messages and messages[-1]["role"] == "user":
                # Force one more generate to get a final answer
                messages.append({"role": "user", "content": "[System] You have used all available tool calls. Please provide your final response to the user now."})
                model_started_at = time.perf_counter()
                final_response, preview_text = await self._generate_with_preview(messages, sys_prompt)
                model_seconds += time.perf_counter() - model_started_at
                final_response = final_response or "Sorry, I got a bit lost there! 😅"
            else:
                final_response = "I tried my best but something went wrong! 😅"
        
        # ── Post-process and dispatch ────────────────────────────────
        # Strip any leftover tool_call blocks
        final_response = self._strip_tool_call_block(_strip_reasoning(final_response))
        
        # Extract emote
        emote_str, final_response = self._extract_emote(final_response)
        
        # Apply output guardrails
        final_response = self.guardrails.filter_output(final_response)
        if MEMORY_TOPIC.search(clean_text) and FALSE_MEMORY_DENIAL.search(final_response):
            logger.warning("Corrected false model claim that Blob has no persistent memory")
            final_response = MEMORY_CAPABILITY_RESPONSE
        
        # Save episodic memory
        self._remember_turn(clean_text, final_response)
        
        # Dispatch emote to frontend
        await self.dispatch_emote(emote_str)
        
        # Dispatch text response to frontend
        resp_event = blob_service_pb2.BackendEvent()
        resp_event.notification.text = final_response
        await self.event_dispatcher.broadcast(resp_event)
        
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

    async def _handle_camera_command(self, command: str):
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
                result = await skill.async_execute({"action": action, "name": name})
                result_text, success = result.output, result.success
            except Exception:
                logger.exception("Camera command failed")
                result_text, success = "Camera command failed. Check the local logs.", False
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
        }
        emote_val = emote_map.get(emote_str, blob_service_pb2.EmoteCommand.IDLE)
        
        evt = blob_service_pb2.BackendEvent()
        evt.emote.emote = emote_val
        await self.event_dispatcher.broadcast(evt)
