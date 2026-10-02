import os
import time
from blob.skills.base import SkillInterface, SkillResult
from blob.skills.contracts import object_schema

class FileSearchSkill(SkillInterface):
    argument_schema = object_schema({"query": {"type": "string", "minLength": 1, "maxLength": 256}}, ("query",))
    permissions = ("filesystem.read",)
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
        deadline = time.monotonic() + 8
        for root, dirs, files in os.walk('.'):
            if time.monotonic() >= deadline:
                return SkillResult(output="\n".join(results) + "\nSearch stopped after eight seconds; try a more specific directory or filename.",
                                   success=bool(results), emote_suggestion="CONFUSED")
            dirs[:] = sorted(d for d in dirs if d not in {".git", ".venv", "venv", "node_modules", "__pycache__"})
            for f in sorted(files):
                if query.casefold() in f.casefold():
                    results.append(os.path.join(root, f))
                    if len(results) == 10:
                        return SkillResult(output="\n".join(results), success=True)
        if not results:
            return SkillResult(output=f"No files matching {query!r} were found in the current directory.", success=False)
        return SkillResult(output="\n".join(results[:10]), success=True)
