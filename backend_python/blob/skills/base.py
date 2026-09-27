import abc
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass


_skill_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="blob-skill")


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
        return await asyncio.wrap_future(_skill_executor.submit(self.execute, args))
