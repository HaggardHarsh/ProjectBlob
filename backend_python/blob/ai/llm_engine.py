from typing import AsyncIterator
import logging
import os
import re
from openai import AsyncOpenAI
import abc
import asyncio
from contextlib import nullcontext

logger = logging.getLogger(__name__)

class LLMEngine(abc.ABC):
    @abc.abstractmethod
    async def generate(self, prompt: str, context: str, system_prompt: str, tools: list = None) -> str:
        pass

    @abc.abstractmethod
    async def generate_from_messages(self, messages: list[dict], system_prompt: str) -> any:
        """Generate from a full message list (for multi-turn ReAct loop)."""
        pass

    @abc.abstractmethod
    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        pass

class NebiusEngine(LLMEngine):
    def __init__(self, api_key: str, base_url: str, model_name: str, *, controls=None):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name
        self._vision_model = None
        self._vision_checked = False
        self.controls = controls
        self.chat_thinking_enabled = os.environ.get("BLOB_CHAT_THINKING", "").lower() in {"1", "true", "yes", "on"}

    async def _create(self, **kwargs):
        controls = getattr(self, "controls", None)
        async def request():
            with controls.operation(cloud=True) if controls else nullcontext():
                return await self.client.chat.completions.create(**kwargs)
        return await asyncio.create_task(request())

    def _chat_kwargs(self) -> dict:
        """Skip hidden reasoning for casual chat on Nemotron Lightning.

        Memory consolidation uses generate() and keeps the model's normal mode.
        Other model families do not necessarily accept this option.
        """
        if (self.model_name == "nvidia/Nemotron-3_5-Lightning"
                and not getattr(self, "chat_thinking_enabled", False)):
            return {"extra_body": {"chat_template_kwargs": {"enable_thinking": False}}}
        return {}

    async def vision_engine(self, configured_model: str = "auto"):
        """Use the same provider/key for vision, without changing ordinary chat."""
        if configured_model.lower() == "off":
            return None
        if configured_model.lower() != "auto":
            model = configured_model
        else:
            if not self._vision_checked:
                try:
                    controls = getattr(self, "controls", None)
                    with controls.operation(cloud=True) if controls else nullcontext():
                        catalog = await self.client.models.list(extra_query={"verbose": "true"})
                    candidates = []
                    for item in catalog.data:
                        extra = item.model_extra or {}
                        modality = str((extra.get("architecture") or {}).get("modality", "")).lower()
                        if "image" in modality or "-vl-" in item.id.lower():
                            candidates.append(item.id)
                    # Keep the selected chat model for files when it accepts images.
                    # Switching to an unrelated smaller model can undo a quality upgrade.
                    self._vision_model = (self.model_name if self.model_name in candidates else
                        min(candidates, key=lambda name: (
                            int(size.group(1)) if (size := re.search(r"(\d+)[Bb]", name)) else 1000,
                            name), default=None))
                    self._vision_checked = True
                except Exception:
                    logger.warning("Could not discover a vision model; using local OCR")
                    return None
            model = self._vision_model
        if not model:
            return None
        engine = NebiusEngine.__new__(NebiusEngine)
        engine.client = self.client
        engine.model_name = model
        engine.chat_thinking_enabled = self.chat_thinking_enabled
        engine.controls = getattr(self, "controls", None)
        return engine

    async def generate(self, prompt: str, context: str, system_prompt: str, tools: list = None) -> any:
        # returns full message object so we can read tool_calls
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context}\n\nPrompt:\n{prompt}"}
        ]
        
        kwargs = {
            "model": self.model_name,
            "messages": messages
        }
        if tools:
            kwargs["tools"] = tools

        resp = await self._create(**kwargs)
        return resp.choices[0].message

    async def generate_from_messages_stream(self, messages: list[dict], system_prompt: str) -> AsyncIterator[str]:
        """Stream text from the same chat request used by the ReAct loop."""
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": system_prompt}] + messages
        stream = await self._create(
            model=self.model_name,
            messages=messages,
            stream=True,
            **self._chat_kwargs(),
        )
        try:
            async for chunk in stream:
                if getattr(self, "controls", None):
                    self.controls.check(cloud=True)
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            close = getattr(stream, "close", None) or stream.aclose
            await close()

    async def generate_from_messages(self, messages: list[dict], system_prompt: str) -> any:
        """Generate a response from a full conversation message list.
        
        The messages list should already include the system prompt as the first
        message. If it doesn't, one will be prepended. This method is used by
        the ReAct loop to maintain multi-turn context with tool observations.
        """
        # Ensure system prompt is first
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": system_prompt}] + messages

        resp = await self._create(
            model=self.model_name,
            messages=messages,
            **self._chat_kwargs(),
        )
        return resp.choices[0].message

    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context}\n\nPrompt:\n{prompt}"}
        ]
        stream = await self._create(
            model=self.model_name,
            messages=messages,
            stream=True,
            **self._chat_kwargs(),
        )
        try:
            async for chunk in stream:
                if getattr(self, "controls", None):
                    self.controls.check(cloud=True)
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        finally:
            close = getattr(stream, "close", None) or stream.aclose
            await close()
