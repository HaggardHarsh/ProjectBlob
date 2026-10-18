from typing import AsyncIterator
import logging
import os
import re
import json
from types import SimpleNamespace
from openai import AsyncOpenAI
import abc
import asyncio
from contextlib import nullcontext

logger = logging.getLogger(__name__)


class ProviderConfigurationError(ValueError):
    """A provider request cannot start until the user configures credentials."""


class LLMEngine(abc.ABC):
    @abc.abstractmethod
    async def generate(self, prompt: str, context: str, system_prompt: str, tools: list = None) -> str:
        pass

    @abc.abstractmethod
    async def generate_from_messages(self, messages: list[dict], system_prompt: str, *, allow_tools=True) -> any:
        """Generate from a full message list (for multi-turn ReAct loop)."""
        pass

    @abc.abstractmethod
    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        pass

class NebiusEngine(LLMEngine):
    def __init__(self, api_key: str, base_url: str, model_name: str, *, controls=None, tool_registry=None):
        self._api_key = api_key
        self._base_url = base_url
        self._client = None
        self.model_name = model_name
        self._vision_model = None
        self._vision_checked = False
        self.controls = controls
        self.tool_registry = tool_registry
        self.chat_thinking_enabled = os.environ.get("BLOB_CHAT_THINKING", "").lower() in {"1", "true", "yes", "on"}

    def validate_configuration(self):
        if not self._api_key.strip() or self._api_key in {"your_nebius_api_key_here", "your_key_here"}:
            raise ProviderConfigurationError(
                "Cloud assistance needs an API key. Set NEBIUS_API_KEY in your private .env file and restart Blob. "
                "Local commands still work; /privacy cloud off disables cloud assistance.")

    @property
    def client(self):
        if self._client is None:
            self.validate_configuration()
            self._client = AsyncOpenAI(api_key=self._api_key, base_url=self._base_url)
        return self._client

    @client.setter
    def client(self, client):
        self._client = client

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
        if self._request_tools()[0]:
            # Tool deltas cannot be presented as ordinary streamed text. Buffer
            # this completion and let the host validate/execute the single call.
            message = await self.generate_from_messages(messages, system_prompt)
            yield message.content or ""
            return
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

    async def generate_from_messages(self, messages: list[dict], system_prompt: str, *, allow_tools=True) -> any:
        """Generate a response from a full conversation message list.
        
        The messages list should already include the system prompt as the first
        message. If it doesn't, one will be prepended. This method is used by
        the ReAct loop to maintain multi-turn context with tool observations.
        """
        # Ensure system prompt is first
        if not messages or messages[0].get("role") != "system":
            messages = [{"role": "system", "content": system_prompt}] + messages

        tools, mapping = self._request_tools() if allow_tools else ([], {})
        options = {}
        if tools or not allow_tools:
            messages = [dict(message) for message in messages]
            messages[0]["content"] = re.sub(
                r"### How to Call a Tool.*?(?=## Emotes)",
                ("Use the supplied native function interface for tool calls, one call at a time. "
                 if allow_tools else "No tool calls are allowed in this completion. Answer from the supplied evidence. ") +
                "Never print tool requests or simulated tool results as answer text.\n\n",
                messages[0]["content"], flags=re.S)
        if tools:
            options = {"tools": tools, "parallel_tool_calls": False}
        resp = await self._create(
            model=self.model_name,
            messages=messages,
            **options,
            **self._chat_kwargs(),
        )
        message = resp.choices[0].message
        calls = getattr(message, "tool_calls", None)
        if tools and calls:
            from blob.ai.response_format import has_tool_protocol
            if has_tool_protocol(message.content):
                return message
            # Never extract calls from ordinary model text. Only the provider's
            # structured channel is adapted to the existing host execution loop.
            if len(calls) == 1 and calls[0].function.name in mapping:
                try:
                    arguments = json.loads(calls[0].function.arguments)
                except (ValueError, TypeError):
                    arguments = None
                if isinstance(arguments, dict):
                    return SimpleNamespace(content=json.dumps({"tool": mapping[calls[0].function.name], "args": arguments}))
            return SimpleNamespace(content=json.dumps({"tool_calls": [call.model_dump() for call in calls]}))
        return message

    def _request_tools(self):
        """Expose only host-authorized tools, never all registered capabilities."""
        from blob.ai.tool_policy import MODEL_POLICY
        policy = MODEL_POLICY.get()
        registry = getattr(self, "tool_registry", None)
        tools, mapping = [], {}
        if policy is None or registry is None:
            return tools, mapping
        for name in sorted(policy.allowed & set(registry.skills)):
            info = registry.describe(name)
            if not info["model_callable"] or name == "camera" or (
                    self.controls and name in self.controls.state["disabled_skills"]):
                continue
            wire_name = "blob_" + name.replace(".", "__")
            mapping[wire_name] = name
            tools.append({"type": "function", "function": {"name": wire_name,
                          "description": info["description"], "parameters": info["arguments"]}})
        return tools, mapping

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
