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
            episodic_memories="\n".join([m['text'] for m in episodes]) or "None"
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
        """Extract <emote>...</emote> tag from text. Returns (emote_str, clean_text)."""
        match = re.search(r'<emote>(.*?)</emote>', text, re.IGNORECASE)
        if match:
            emote_str = match.group(1).upper()
            clean = text.replace(match.group(0), "").strip()
            return emote_str, clean
        return "IDLE", text

    async def handle_user_message(self, user_msg):
        """Main entry point: handles a user message with a ReAct loop."""
        clean_text = self.guardrails.sanitize_input(user_msg.text)
        stripped = clean_text.strip()
        if stripped and stripped.split(maxsplit=1)[0].lower() == "/camera":
            return await self._handle_camera_command(stripped)
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
        print(f"\r\033[K\033[96mBlob ({emote_str}):\033[0m {final_response}\n")
        return final_response

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
        await self.dispatch_emote("HAPPY" if success else "WORRIED")
        event = blob_service_pb2.BackendEvent()
        event.notification.text = result_text
        await self.event_dispatcher.broadcast(event)
        print(f"\nBlob: {result_text}\n")
        return result_text

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
