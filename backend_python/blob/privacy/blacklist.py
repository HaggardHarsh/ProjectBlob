import yaml
import re

class BlacklistManager:
    def __init__(self, config_path: str):
        self.patterns = []
        try:
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f) or {}
                self.patterns = [re.compile(p, re.IGNORECASE) for p in data.get('patterns', [])]
        except Exception:
            pass

    def is_blacklisted(self, window_info) -> bool:
        for p in self.patterns:
            if p.search(window_info.title) or p.search(window_info.process_name):
                return True
        return False
