import subprocess
from blob.skills.base import SkillInterface, SkillResult

class ShellCommandSkill(SkillInterface):
    @property
    def name(self): return "shell_command"
    
    @property
    def description(self): return "Execute a safe shell command on the host. Allowed commands: ls, cat, grep, find, echo, python --version. Example args: {'command': 'ls -la'}"
    
    @property
    def triggers(self): return ["run", "command", "shell", "execute"]
    
    def execute(self, args):
        cmd = args.get('command')
        if not cmd:
            return SkillResult("No command provided", False, "CONFUSED")
            
        allowed = ["ls", "cat", "grep", "find", "echo", "python --version", "git"]
        if not any(cmd.startswith(a) for a in allowed):
            return SkillResult(f"Command '{cmd}' not allowed for safety.", False, "WORRIED")
            
        try:
            output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT, timeout=10).decode('utf-8')
            # truncate output if too long
            if len(output) > 2000:
                output = output[:2000] + "\n...[truncated]"
            return SkillResult(output, True, "THINKING")
        except subprocess.TimeoutExpired:
            return SkillResult("Command timed out.", False, "WORRIED")
        except subprocess.CalledProcessError as e:
            err = e.output.decode('utf-8') if e.output else str(e)
            return SkillResult(f"Command failed: {err}", False, "WORRIED")
        except Exception as e:
            return SkillResult(str(e), False, "CONFUSED")
