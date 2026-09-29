import os
from blob.skills.base import SkillInterface, SkillResult

class FileSearchSkill(SkillInterface):
    @property
    def name(self): return "file_search"
    
    @property
    def description(self): return "Search file names in Blob's current working directory. This does not search the user's screen or open a visible PDF. args: {query: filename text}"
    
    @property
    def triggers(self): return ["find file", "search file"]
    
    def execute(self, args):
        query = str(args.get('query', '')).strip()
        if not query:
            return SkillResult(output="Tell me a file name or part of one to search for.", success=False)
        results = []
        for root, dirs, files in os.walk('.'):
            for f in files:
                if query.casefold() in f.casefold():
                    results.append(os.path.join(root, f))
        if not results:
            return SkillResult(output=f"No files matching {query!r} were found in the current directory.", success=False)
        return SkillResult(output="\n".join(results[:10]), success=True)
