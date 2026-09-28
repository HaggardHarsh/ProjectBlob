import asyncio
import logging
import json
import re
from blob.ai.llm_engine import NebiusEngine
from blob.ipc import blob_service_pb2
from blob.ai.guardrails import GuardrailsEngine
from blob.ai.prompt_templates import SYSTEM_PROMPT, CONTEXT_TEMPLATE
from blob.memory.episodic import EpisodicMemory
from blob.memory.semantic import SemanticMemory

logger = logging.getLogger(__name__)

MAX_REACT_ITERATIONS = 3
EMOTE_NAMES = "IDLE|HAPPY|SAD|ANGRY|CONFUSED|THINKING|WORRIED|CELEBRATE|EXCITED|TIRED|OFFER_COFFEE|SHY|SLEEPING|EATING|PROUD|PLAYFUL"
EMOTE_MARKER = re.compile(rf"<emote>\s*({EMOTE_NAMES})\s*</emote>|\(({EMOTE_NAMES})\)", re.IGNORECASE)
CAMERA_REQUEST = re.compile(
    r"\b(?:open|turn on|switch on|start|use|scan|check|look through|look at|see through)\b"
    r".{0,35}\b(?:camera|webcam)\b|\bturn\b.{0,15}\b(?:camera|webcam)\b\s+on\b",
    re.IGNORECASE,
)
SCREEN_REQUEST = re.compile(
    r"\b(?:what(?:'s| is) (?:happening|going on|on|visible)|show me|look at|check|read|describe|capture|see)\b"
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
        return SYSTEM_PROMPT.replace("{skills}", skills_text)

    def _build_context(self, clean_text: str) -> str:
        """Build the context block with memories, active window, and screen data."""
        episodes = self.episodic.recall_relevant(clean_text, top_k=5)
        facts = self.semantic.recall_facts(clean_text, top_k=3)
        # Tone preferences must remain in view even when the current question
        # is about an unrelated task.
        style_facts = self.semantic.recall_facts(
            "How does the user want Blob to speak to them: friendly buddy, formal, professional, direct, or quiet?",
            top_k=2,
        )
        fact_texts = list(dict.fromkeys(item["text"] for item in style_facts + facts))
        episode_texts = [item["text"] for item in episodes]
        if MEMORY_TOPIC.search(clean_text):
            # Old assistant replies may contain the exact false memory claim.
            episode_texts = [text.split("\nBlob: ", 1)[0] for text in episode_texts]
        
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
            semantic_memories="\n".join(fact_texts) or "None",
            episodic_memories="\n".join(episode_texts) or "None"
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

    async def handle_user_message(self, user_msg):
        """Main entry point: handles a user message with a ReAct loop."""
        clean_text = self.guardrails.sanitize_input(user_msg.text)
        stripped = clean_text.strip()
        if stripped and stripped.split(maxsplit=1)[0].lower() == "/camera":
            return await self._handle_camera_command(stripped)
        if CAMERA_REQUEST.search(stripped) and not re.search(r"\b(?:don't|do not|never|how (?:do|can|to))\b", stripped, re.IGNORECASE):
            return await self._handle_camera_command("/camera scan")
        if REMEMBER_ME_REQUEST.fullmatch(stripped):
            return await self._handle_remember_me(clean_text)

        screen_result = None
        if SCREEN_REQUEST.search(stripped) and not re.search(r"\b(?:don't|do not|never)\b", stripped, re.IGNORECASE):
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
        context = self._build_context(clean_text)
        sys_prompt = self._build_system_prompt()
        
        # Immediately set thinking emote on frontend & print indicator in CLI
        await self.dispatch_emote("THINKING")
        print("\033[90m(Thinking...)\033[0m", end="", flush=True)

        # Build conversation messages for multi-turn reasoning
        messages = [
            {"role": "system", "content": sys_prompt},
            {"role": "user", "content": f"Context:\n{context}\n\nUser message:\n{clean_text}"}
        ]
        if screen_result is not None:
            messages.append({"role": "user", "content":
                f"[Observation] A fresh screen capture succeeded. {screen_result.output}\n"
                "Answer using this result. It contains OCR text and the active window title, not a full visual description. "
                "Do not claim screen access is unavailable."})
        
        final_response = None
        
        # ── ReAct Loop ──────────────────────────────────────────────────
        for iteration in range(MAX_REACT_ITERATIONS):
            logger.info(f"ReAct iteration {iteration + 1}/{MAX_REACT_ITERATIONS}")
            
            # Generate LLM response
            msg = await self.llm.generate_from_messages(messages, sys_prompt)
            response_text = msg.content or ""
            
            # Check for tool call
            tool_name, tool_args = self._parse_tool_call(response_text)
            
            if tool_name is None:
                # No tool call → this is the final answer
                final_response = response_text
                break
            
            # ── Tool Execution ──────────────────────────────────────────
            skill = self.skill_registry.get_skill(tool_name)
            if tool_name == "camera":
                skill = None
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
                msg = await self.llm.generate_from_messages(messages, sys_prompt)
                final_response = msg.content or "Sorry, I got a bit lost there! 😅"
            else:
                final_response = "I tried my best but something went wrong! 😅"
        
        # ── Post-process and dispatch ────────────────────────────────
        # Strip any leftover tool_call blocks
        final_response = self._strip_tool_call_block(final_response)
        
        # Extract emote
        emote_str, final_response = self._extract_emote(final_response)
        
        # Apply output guardrails
        final_response = self.guardrails.filter_output(final_response)
        if MEMORY_TOPIC.search(clean_text) and FALSE_MEMORY_DENIAL.search(final_response):
            logger.warning("Corrected false model claim that Blob has no persistent memory")
            final_response = MEMORY_CAPABILITY_RESPONSE
        
        # Save episodic memory
        if not (self.screen_sampler and self.screen_sampler.privacy_shield.is_capture_blocked()):
            self.episodic.add_episode(clean_text, final_response)
        
        # Dispatch emote to frontend
        await self.dispatch_emote(emote_str)
        
        # Dispatch text response to frontend
        resp_event = blob_service_pb2.BackendEvent()
        resp_event.notification.text = final_response
        await self.event_dispatcher.broadcast(resp_event)
        
        # Clean CLI output (clears the thinking indicator line)
        print(f"\r\033[K\033[96mBlob:\033[0m {final_response}\n")
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
            self.episodic.add_episode(user_text, MEMORY_CAPABILITY_RESPONSE)
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
