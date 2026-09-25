import subprocess
from blob.skills.base import SkillInterface, SkillResult

class GitStatusSkill(SkillInterface):
    @property
    def name(self): return "git_status"
    
    @property
    def description(self): return "Check git status in current directory"
    
    @property
    def triggers(self): return ["git status", "repo status"]
    
    def execute(self, args):
        try:
            out = subprocess.check_output(["git", "status"], stderr=subprocess.STDOUT).decode()
            return SkillResult(output=out, success=True, emote_suggestion="THINKING")
        except subprocess.CalledProcessError as e:
            return SkillResult(output=e.output.decode(), success=False, emote_suggestion="CONFUSED")
