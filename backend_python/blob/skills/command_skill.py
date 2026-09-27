"""Safe execution of validated YAML command tools without a shell."""

import os
import shlex
import subprocess

from blob.skills.base import SkillInterface, SkillResult
from blob.skills.validator import SkillDefinition, ToolDefinition


def _allowed(argv: list[str], permissions: frozenset[str]) -> bool:
    executable = argv[0]
    if executable in {"find", "grep", "ls", "cat", "head", "tail"}:
        if "filesystem.read" not in permissions:
            return False
        if executable == "find" and any(arg in {"-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"} for arg in argv[1:]):
            return False
        return True
    if executable == "git":
        if "shell.execute" not in permissions or len(argv) < 2:
            return False
        if any(arg in {"-c", "--ext-diff", "--output"} or arg.startswith(("--ext-diff=", "--output=")) for arg in argv[2:]):
            return False
        return argv[1] in {"status", "log", "branch", "diff"} or (argv[1:3] == ["stash", "list"])
    if executable == "curl":
        return ("network.http" in permissions and len(argv) in {2, 3}
                and argv[-1].startswith("https://") and all(arg in {"-s", "--silent"} for arg in argv[1:-1]))
    if executable in {"echo", "date", "df", "free", "uname"}:
        return "shell.execute" in permissions
    return False


class CommandSkill(SkillInterface):
    def __init__(self, definition: SkillDefinition, tool: ToolDefinition):
        self.definition = definition
        self.tool = tool

    @property
    def name(self) -> str:
        return f"{self.definition.slug}.{self.tool.name}"

    @property
    def description(self) -> str:
        names = ", ".join(arg.name for arg in self.tool.arguments)
        return f"{self.tool.description}. {self.definition.description}. args: {names or '{}'}"

    @property
    def triggers(self) -> list[str]:
        return list(self.definition.triggers)

    def execute(self, args: dict) -> SkillResult:
        if not isinstance(args, dict):
            return SkillResult("Tool arguments must be an object.", False, self.definition.emote_on_failure)
        declared = {argument.name for argument in self.tool.arguments}
        if set(args) - declared:
            return SkillResult("Unknown tool arguments.", False, self.definition.emote_on_failure)
        values = {}
        for argument in self.tool.arguments:
            value = args.get(argument.name, argument.default)
            if argument.required and (value is None or str(value) == ""):
                return SkillResult(f"Missing required argument: {argument.name}.", False, self.definition.emote_on_failure)
            values[argument.name] = str(value)
        try:
            argv = [os.path.expanduser(token.format_map(values)) for token in shlex.split(self.tool.command)]
        except (ValueError, KeyError) as exc:
            return SkillResult(f"Invalid tool arguments: {exc}", False, self.definition.emote_on_failure)
        if not _allowed(argv, self.definition.permissions):
            return SkillResult("This command is not allowed by the skill permissions or command policy.", False, self.definition.emote_on_failure)
        try:
            result = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, timeout=10, check=False)
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return SkillResult(f"Command failed: {exc}", False, self.definition.emote_on_failure)
        output = result.stdout[:4000]
        if len(result.stdout) > 4000:
            output += "\n...[truncated]"
        if result.returncode != 0:
            return SkillResult(output or f"Command exited with status {result.returncode}.", False, self.definition.emote_on_failure)
        output = self.definition.response_template.format_map({**values, "result": output or "(no output)"})
        return SkillResult(output, True, self.definition.emote_on_success)
