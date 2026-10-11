import subprocess
import shlex
from blob.skills.base import SkillInterface, SkillResult
from blob.skills.contracts import object_schema
from blob.skills.command_policy import allowed_command, command_argv
from blob.skills.process import run_command

class ShellCommandSkill(SkillInterface):
    argument_schema = object_schema({"command": {"type": "string", "minLength": 1, "maxLength": 2048}}, ("command",))
    permissions = ("filesystem.read", "shell.execute")
    @property
    def name(self): return "shell_command"
    
    @property
    def description(self): return "Run an allowed read-only command without a shell: ls, cat, grep, find, git status/log/diff/branch listing, echo, date, df, free, uname, python --version."
    
    @property
    def triggers(self): return ["run", "command", "shell", "execute"]
    
    def execute(self, args):
        cmd = args.get('command')
        if not cmd:
            return SkillResult("No command provided", False, "CONFUSED")
            
        try:
            argv = shlex.split(cmd)
        except ValueError:
            return SkillResult("Invalid command quoting.", False, "CONFUSED")
        if not argv:
            return SkillResult("No command provided", False, "CONFUSED")
        if not allowed_command(argv, self.permissions):
            return SkillResult(f"Command '{cmd}' not allowed for safety.", False, "WORRIED")
            
        try:
            result = run_command(command_argv(argv), controls=getattr(self, "controls", None))
            return SkillResult(result.stdout, result.returncode == 0, "THINKING" if result.returncode == 0 else "WORRIED")
        except subprocess.TimeoutExpired:
            return SkillResult("Command timed out.", False, "WORRIED")
        except subprocess.CalledProcessError as e:
            err = e.output.decode('utf-8') if e.output else str(e)
            return SkillResult(f"Command failed: {err}", False, "WORRIED")
        except Exception as e:
            return SkillResult(str(e), False, "CONFUSED")
