import subprocess
from blob.skills.base import SkillInterface, SkillResult
from blob.skills.command_policy import command_argv
from blob.skills.process import run_command

class GitStatusSkill(SkillInterface):
    permissions = ("filesystem.read", "shell.execute")
    @property
    def name(self): return "git_status"
    
    @property
    def description(self): return "Check git status in current directory"
    
    @property
    def triggers(self): return ["git status", "repo status"]
    
    def execute(self, args):
        try:
            result = run_command(command_argv(["git", "status"]), controls=getattr(self, "controls", None))
            return SkillResult(output=result.stdout, success=result.returncode == 0,
                               emote_suggestion="THINKING" if result.returncode == 0 else "CONFUSED")
        except (OSError, subprocess.TimeoutExpired) as exc:
            return SkillResult(output=f"Git status failed: {exc}", success=False, emote_suggestion="WORRIED")
