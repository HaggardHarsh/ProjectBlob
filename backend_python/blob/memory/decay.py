import math
import time

class DecayAlgorithm:
    def __init__(self, lambda_val: float = 0.05):
        self.lambda_val = lambda_val
        
    def calculate_score(self, base_similarity: float, days_since_access: float, access_count: int) -> float:
        return base_similarity * math.exp(-self.lambda_val * days_since_access) * (1 + access_count * 0.1)
