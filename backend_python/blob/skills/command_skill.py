"""Safe execution of validated YAML command tools without a shell."""

import os
import shlex
import subprocess

from blob.skills.base import SkillInterface, SkillResult
from blob.skills.validator import SkillDefinition, ToolDefinition
from blob.skills.contracts import object_schema, validate_arguments
from blob.skills.command_policy import allowed_command as _allowed, command_argv
from blob.skills.process import run_command


class CommandSkill(SkillInterface):
    def __init__(self, definition: SkillDefinition, tool: ToolDefinition):
        self.definition = definition
        self.tool = tool

    @property
    def permissions(self):
        return self.definition.permissions

    @property
    def argument_schema(self):
        properties = {}
        for argument in self.tool.arguments:
            rule = {"type": argument.type, "description": argument.description}
            if not argument.required:
                rule["default"] = argument.default
            for key, value in (("enum", argument.enum), ("minimum", argument.minimum),
                               ("maximum", argument.maximum)):
                if value is not None:
                    rule[key] = list(value) if key == "enum" else value
            properties[argument.name] = rule
        return object_schema(properties, [a.name for a in self.tool.arguments if a.required])

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
        try:
            args = validate_arguments(self.argument_schema, args)
        except ValueError as exc:
            return SkillResult(str(exc), False, self.definition.emote_on_failure)
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
            result = run_command(command_argv(argv))
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            return SkillResult(f"Command failed: {exc}", False, self.definition.emote_on_failure)
        output = result.stdout
        if result.returncode != 0:
            return SkillResult(output or f"Command exited with status {result.returncode}.", False, self.definition.emote_on_failure)
        output = self.definition.response_template.format_map({**values, "result": output or "(no output)"})
        return SkillResult(output, True, self.definition.emote_on_success)
