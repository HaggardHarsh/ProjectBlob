import os
from blob.skills.base import SkillInterface, SkillResult

class FileSearchSkill(SkillInterface):
    @property
    def name(self): return "file_search"
    
    @property
    def description(self): return "Search for files"
    
    @property
    def triggers(self): return ["find file", "search file"]
    
    def execute(self, args):
        query = args.get('query', '')
        results = []
        for root, dirs, files in os.walk('.'):
            for f in files:
                if query in f:
                    results.append(os.path.join(root, f))
        return SkillResult(output="\n".join(results[:10]), success=True)
