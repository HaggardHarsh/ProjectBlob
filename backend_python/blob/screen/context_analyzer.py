from dataclasses import dataclass

@dataclass
class WorkflowContext:
    state: str
    confidence: float

class ContextAnalyzer:
    def analyze(self, text: str) -> WorkflowContext:
        text_lower = text.lower()
        if "build successful" in text_lower or "all tests passed" in text_lower:
            return WorkflowContext("CELEBRATE", 0.9)
        elif "error" in text_lower or "exception" in text_lower:
            return WorkflowContext("WORRIED", 0.8)
        return WorkflowContext("NORMAL", 0.5)
