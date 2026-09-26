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
        
        # Try to get active window title (lightweight, no screenshot)
        active_window = "Unknown"
        if self.screen_sampler:
            try:
                title = self.screen_sampler.get_active_window_title()
                if title:
                    active_window = title
            except Exception:
                pass

        return CONTEXT_TEMPLATE.format(
            active_window=active_window,
            screen_context=self.last_screen_context,
            semantic_memories="\n".join([f['text'] for f in facts]) or "None",
            episodic_memories="\n".join([m['text'] for m in episodes]) or "None"
        )

    def _parse_tool_call(self, response_text: str):
        """Extract a ```tool_call JSON block from the LLM response.
        
        Returns (tool_name, tool_args) or (None, None) if no valid tool call found.
        """
        match = re.search(r'```tool_call\s*(.*?)\s*```', response_text, re.DOTALL)
        if not match:
            return None, None
        
        try:
            tool_data = json.loads(match.group(1))
            tool_name = tool_data.get('tool')
            tool_args = tool_data.get('args', {})
            if tool_name:
                return tool_name, tool_args
        except (json.JSONDecodeError, AttributeError) as e:
            logger.error(f"Failed to parse tool_call JSON: {e}")
        
        return None, None

    def _strip_tool_call_block(self, text: str) -> str:
        """Remove ```tool_call blocks from text for display."""
        return re.sub(r'```tool_call\s*.*?\s*```', '', text, flags=re.DOTALL).strip()

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
        context = self._build_context(clean_text)
        sys_prompt = self._build_system_prompt()
        
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
            if not skill:
                logger.warning(f"Tool '{tool_name}' not found in registry")
                # Tell the LLM the tool wasn't found
                messages.append({"role": "assistant", "content": response_text})
                messages.append({"role": "user", "content": f"[Observation] Tool '{tool_name}' not found. Available tools: {', '.join(self.skill_registry.skills.keys())}. Please try again or respond without a tool."})
                continue
            
            logger.info(f"Executing skill: {tool_name} with args: {tool_args}")
            
            try:
                result = await skill.async_execute(tool_args)
                observation = f"[Observation] Tool '{tool_name}' executed successfully.\nResult: {result.output}"
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
        self.episodic.add_episode(clean_text, final_response)
        
        # Dispatch emote to frontend
        await self.dispatch_emote(emote_str)
        
        # Dispatch text response to frontend
        resp_event = blob_service_pb2.BackendEvent()
        resp_event.notification.text = final_response
        await self.event_dispatcher.broadcast(resp_event)
        
        # Clean CLI output
        print(f"\n\033[96mBlob ({emote_str}):\033[0m {final_response}\n")

    async def dispatch_emote(self, emote_str: str):
        """Map emote string to protobuf enum and broadcast to frontend."""
        emote_map = {
            "IDLE": blob_service_pb2.EmoteCommand.IDLE,
            "HAPPY": blob_service_pb2.EmoteCommand.HAPPY,
            "SAD": blob_service_pb2.EmoteCommand.WORRIED,
            "ANGRY": blob_service_pb2.EmoteCommand.CONFUSED,
            "CONFUSED": blob_service_pb2.EmoteCommand.CONFUSED,
            "THINKING": blob_service_pb2.EmoteCommand.THINKING,
            "WORRIED": blob_service_pb2.EmoteCommand.WORRIED,
            "CELEBRATE": blob_service_pb2.EmoteCommand.CELEBRATE,
            "TIRED": blob_service_pb2.EmoteCommand.TIRED,
            "EXCITED": blob_service_pb2.EmoteCommand.EXCITED
        }
        emote_val = emote_map.get(emote_str, blob_service_pb2.EmoteCommand.IDLE)
        
        evt = blob_service_pb2.BackendEvent()
        evt.emote.emote = emote_val
        await self.event_dispatcher.broadcast(evt)
