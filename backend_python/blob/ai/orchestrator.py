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

class BlobOrchestrator:
    def __init__(self, config, vector_store, skill_registry, event_dispatcher):
        self.config = config
        self.vector_store = vector_store
        self.skill_registry = skill_registry
        self.event_dispatcher = event_dispatcher
        self.guardrails = GuardrailsEngine(config)
        self.llm = NebiusEngine(config.nebius_api_key, config.nebius_base_url, config.model_name)
        
        self.episodic = EpisodicMemory(vector_store)
        self.semantic = SemanticMemory(vector_store, self.llm)
        
    async def handle_user_message(self, user_msg):
        # sanitize input
        clean_text = self.guardrails.sanitize_input(user_msg.text)
        
        # retrieve memories
        episodes = self.episodic.recall_relevant(clean_text, top_k=5)
        facts = self.semantic.recall_facts(clean_text, top_k=3)
        
        context = CONTEXT_TEMPLATE.format(
            active_window="None",  # Placeholder until screen pipeline is wired
            semantic_memories="\n".join([f['text'] for f in facts]),
            episodic_memories="\n".join([m['text'] for m in episodes])
        )
        
        # Format skills for prompt
        skills_text = ""
        for name, skill in self.skill_registry.skills.items():
            skills_text += f"- {name}: {skill.description}\n"
            
        sys_prompt = SYSTEM_PROMPT.replace("{skills}", skills_text)
        
        # generate response
        msg = await self.llm.generate(clean_text, context, sys_prompt)
        response_text = msg.content
        
        # Look for tool call
        tool_call_match = re.search(r'```tool_call\s*(.*?)\s*```', response_text, re.DOTALL)
        if tool_call_match:
            try:
                tool_data = json.loads(tool_call_match.group(1))
                tool_name = tool_data.get('tool')
                tool_args = tool_data.get('args', {})
                skill = self.skill_registry.get_skill(tool_name)
                
                if skill:
                    logger.info(f"Executing skill: {tool_name} with {tool_args}")
                    result = skill.execute(tool_args)
                    
                    # Feed result back to LLM for final answer
                    followup_prompt = f"Tool '{tool_name}' executed. Result:\n{result.output}\n\nFormulate your final response to the user."
                    msg2 = await self.llm.generate(followup_prompt, context, sys_prompt)
                    response_text = msg2.content
                    
                    # Use emote from tool if applicable
                    if result.emote_suggestion != "IDLE":
                        await self.dispatch_emote(result.emote_suggestion)
                else:
                    logger.warning(f"Tool {tool_name} not found")
            except Exception as e:
                logger.error(f"Failed to parse or execute tool call: {e}")
        
        # Extract emote tag if present
        emote_match = re.search(r'<emote>(.*?)</emote>', response_text, re.IGNORECASE)
        emote_str = "IDLE"
        if emote_match:
            emote_str = emote_match.group(1).upper()
            response_text = response_text.replace(emote_match.group(0), "").strip()
        
        # apply output filter
        response_text = self.guardrails.filter_output(response_text)
        
        # save episodic memory
        self.episodic.add_episode(clean_text, response_text)

        
        # Dispatch back to frontend
        await self.dispatch_emote(emote_str)
        
        resp_event = blob_service_pb2.BackendEvent()
        resp_event.notification.text = response_text
        await self.event_dispatcher.broadcast(resp_event)
        
        # Clean CLI output
        print(f"\n\033[96mBlob ({emote_str}):\033[0m {response_text}\n")

    async def dispatch_emote(self, emote_str: str):
        # Map string to enum
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
