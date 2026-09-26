import abc
import asyncio
from dataclasses import dataclass
from typing import Optional


@dataclass
class SkillResult:
    output: str
    success: bool
    emote_suggestion: str = "IDLE"


class SkillInterface(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: pass
    
    @property
    @abc.abstractmethod
    def description(self) -> str: pass
    
    @property
    @abc.abstractmethod
    def triggers(self) -> list[str]: pass
    
    @abc.abstractmethod
    def execute(self, args: dict) -> SkillResult:
        """Synchronous execution. Override this for simple skills."""
        pass

    async def async_execute(self, args: dict) -> SkillResult:
        """Async execution. Default wraps sync execute() in a thread executor.
        Override this directly for natively async skills (e.g., ReminderSkill).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.execute, args)
