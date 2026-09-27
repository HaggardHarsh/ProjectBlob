import subprocess
import shlex
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
            
        try:
            argv = shlex.split(cmd)
        except ValueError:
            return SkillResult("Invalid command quoting.", False, "CONFUSED")
        if not argv:
            return SkillResult("No command provided", False, "CONFUSED")
        allowed = {"ls", "cat", "grep", "echo"}
        git_safe = argv[0] == "git" and len(argv) >= 2 and argv[1] in {"status", "log"} and not any(arg.startswith("--exec") or arg.startswith("--ext-diff") or arg == "-c" for arg in argv[2:])
        python_safe = argv in (["python", "--version"], ["python3", "--version"])
        find_safe = argv[0] == "find" and not any(arg in {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf"} for arg in argv[1:])
        if not (argv[0] in allowed or git_safe or python_safe or find_safe):
            return SkillResult(f"Command '{cmd}' not allowed for safety.", False, "WORRIED")
            
        try:
            output = subprocess.check_output(argv, shell=False, stderr=subprocess.STDOUT, timeout=10).decode('utf-8')
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
