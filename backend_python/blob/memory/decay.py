import math

class DecayAlgorithm:
    def __init__(self, lambda_val: float = 0.05):
        self.lambda_val = lambda_val
        
    def calculate_score(self, base_similarity: float, days_since_access: float, access_count: int, pinned: bool = False) -> float:
        decay = 1.0 if pinned else math.exp(-self.lambda_val * days_since_access)
        return base_similarity * decay * (1 + math.log1p(access_count) * 0.1)
