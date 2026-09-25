import abc
from dataclasses import dataclass

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
    def execute(self, args: dict) -> SkillResult: pass
