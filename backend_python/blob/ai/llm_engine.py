from typing import AsyncIterator
import logging
from openai import AsyncOpenAI
import abc

logger = logging.getLogger(__name__)

class LLMEngine(abc.ABC):
    @abc.abstractmethod
    async def generate(self, prompt: str, context: str, system_prompt: str, tools: list = None) -> str:
        pass

    @abc.abstractmethod
    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        pass

class NebiusEngine(LLMEngine):
    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

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

        resp = await self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message

    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\n{context}\n\nPrompt:\n{prompt}"}
        ]
        stream = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content


