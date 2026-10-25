"""Validation for installable, declarative skill files."""

from dataclasses import dataclass
import re
import shlex
from string import Formatter

import yaml
from blob.skills.contracts import object_schema, validate_arguments
from blob.skills.command_policy import allowed_command


ALLOWED_PERMISSIONS = frozenset({"filesystem.read", "shell.execute", "network.http"})
SHELL_OPERATORS = frozenset({"|", "||", "&", "&&", ";", ">", ">>", "<", "2>", "2>>"})
VALID_EMOTES = frozenset({"IDLE", "HAPPY", "TIRED", "EXCITED", "THINKING", "OFFER_COFFEE", "CELEBRATE", "SHY", "SLEEPING", "EATING", "CONFUSED", "PROUD", "WORRIED", "PLAYFUL", "SAD", "ANGRY", "WORKING", "DEEP_THINKING", "LISTENING", "SHOCKED", "MELTING", "ERROR", "SUCCESS", "WAITING"})


@dataclass(frozen=True)
class ToolArgument:
    name: str
    required: bool = False
    default: object = ""
    type: str = "string"
    description: str = ""
    enum: tuple | None = None
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    command: str
    arguments: tuple[ToolArgument, ...]
    triggers: tuple[str, ...] = ()
    examples: tuple[str, ...] = ()


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    slug: str
    description: str
    permissions: frozenset[str]
    triggers: tuple[str, ...]
    tools: tuple[ToolDefinition, ...]
    response_template: str = "{result}"
    emote_on_success: str = "HAPPY"
    emote_on_failure: str = "CONFUSED"
    examples: tuple[str, ...] = ()
    version: str = "0.0.0"
    author: str = ""
    color: str = ""
    icon: str = ""


def phrase_list(data, key):
    values = data.get(key, [])
    if (not isinstance(values, list) or len(values) > 32 or
            any(not isinstance(value, str) or not value.strip() or len(value) > 500 for value in values)):
        raise ValueError(f"Skill {key} must be a list of up to 32 nonempty strings (500 characters each).")
    return tuple(value.strip() for value in values)


class SkillValidator:
    def validate(self, yaml_content: str) -> SkillDefinition:
        try:
            document = yaml.safe_load(yaml_content)
        except yaml.YAMLError as exc:
            raise ValueError(f"Invalid YAML: {exc}") from exc
        if not isinstance(document, dict) or not isinstance(document.get("skill"), dict):
            raise ValueError("Expected a top-level 'skill' mapping.")
        data = document["skill"]
        name = data.get("name")
        description = data.get("description")
        if not isinstance(name, str) or not name.strip() or not isinstance(description, str) or not description.strip():
            raise ValueError("Skill name and description are required strings.")
        slug = re.sub(r"[^a-z0-9]+", "_", name.casefold()).strip("_")
        if not slug:
            raise ValueError("Skill name must contain letters or numbers.")
        metadata = {}
        for field, default, limit in (("version", "0.0.0", 100), ("author", "", 200),
                                      ("color", "", 7), ("icon", "", 100)):
            value = data.get(field, default)
            if not isinstance(value, str) or len(value) > limit or any(ord(char) < 32 for char in value):
                raise ValueError(f"Skill {field} must be a string of at most {limit} printable characters.")
            metadata[field] = value.strip()
        if not re.fullmatch(r"(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)(?:-[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?", metadata["version"]):
            raise ValueError("Skill version must use major.minor.patch, optionally with a prerelease/build suffix.")
        if metadata["color"] and not re.fullmatch(r"#[0-9a-fA-F]{6}", metadata["color"]):
            raise ValueError("Skill color must be a six-digit hex color, such as #4FC3F7.")
        raw_permissions = data.get("permissions", [])
        if not isinstance(raw_permissions, list) or any(not isinstance(item, str) for item in raw_permissions):
            raise ValueError("Skill permissions must be a list of strings.")
        permissions = frozenset(raw_permissions)
        unknown = permissions - ALLOWED_PERMISSIONS
        if unknown:
            raise ValueError(f"Unsupported permissions: {', '.join(sorted(unknown))}.")
        raw_tools = data.get("tools")
        if not isinstance(raw_tools, list) or not raw_tools:
            raise ValueError("A skill needs at least one tool.")
        tools = []
        seen_names = set()
        for raw_tool in raw_tools:
            if not isinstance(raw_tool, dict):
                raise ValueError("Each tool must be a mapping.")
            tool_name = raw_tool.get("name")
            tool_description = raw_tool.get("description", "")
            command = raw_tool.get("command")
            if not isinstance(tool_name, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", tool_name):
                raise ValueError("Tool names must use lowercase letters, numbers, and underscores.")
            if tool_name in seen_names:
                raise ValueError(f"Duplicate tool name: {tool_name}.")
            seen_names.add(tool_name)
            if not isinstance(command, str) or not command.strip() or len(command) > 2048:
                raise ValueError(f"Tool {tool_name} needs a command of at most 2048 characters.")
            try:
                tokens = shlex.split(command)
            except ValueError as exc:
                raise ValueError(f"Invalid command quoting in {tool_name}: {exc}") from exc
            if not tokens or any(token in SHELL_OPERATORS or re.fullmatch(r"\d?>.*", token) for token in tokens):
                raise ValueError(f"Shell pipelines, redirections, and separators are not supported in {tool_name}.")
            raw_args = raw_tool.get("args", [])
            if not isinstance(raw_args, list):
                raise ValueError(f"Tool {tool_name} args must be a list.")
            arguments = []
            arg_names = set()
            for raw_arg in raw_args:
                if not isinstance(raw_arg, dict) or not isinstance(raw_arg.get("name"), str):
                    raise ValueError(f"Tool {tool_name} has an invalid argument.")
                arg_name = raw_arg["name"]
                if arg_name == "project":
                    raise ValueError("'project' is reserved for the tool's working directory; use another argument name.")
                if not re.fullmatch(r"[a-z][a-z0-9_]*", arg_name) or arg_name in arg_names:
                    raise ValueError(f"Tool {tool_name} has a duplicate or invalid argument name.")
                arg_names.add(arg_name)
                required = raw_arg.get("required", False)
                kind = raw_arg.get("type", "string")
                if type(required) is not bool or not isinstance(kind, str) or kind not in {"string", "number", "integer", "boolean"}:
                    raise ValueError(f"Tool {tool_name} argument {arg_name} has an invalid type or required flag.")
                enum = raw_arg.get("enum")
                if enum is not None and (not isinstance(enum, list) or not enum):
                    raise ValueError(f"Tool {tool_name} argument {arg_name} enum must be a nonempty list.")
                minimum, maximum = raw_arg.get("minimum"), raw_arg.get("maximum")
                if any(value is not None and type(value) not in {int, float} for value in (minimum, maximum)):
                    raise ValueError(f"Tool {tool_name} argument {arg_name} bounds must be numbers.")
                for value in (minimum, maximum):
                    if value is not None:
                        validate_arguments(object_schema({"bound": {"type": "number"}}), {"bound": value})
                if minimum is not None and maximum is not None and minimum > maximum:
                    raise ValueError(f"Tool {tool_name} argument {arg_name} has reversed bounds.")
                default = raw_arg.get("default", {"string": "", "number": 0, "integer": 0, "boolean": False}[kind])
                argument = ToolArgument(arg_name, required, default, kind, str(raw_arg.get("description", "")),
                                        tuple(enum) if enum is not None else None, minimum, maximum)
                rule = {"type": kind}
                if enum is not None:
                    for choice in enum:
                        validate_arguments(object_schema({arg_name: rule}), {arg_name: choice})
                if enum is not None:
                    rule["enum"] = enum
                if minimum is not None:
                    rule["minimum"] = minimum
                if maximum is not None:
                    rule["maximum"] = maximum
                if not required:
                    validate_arguments(object_schema({arg_name: rule}), {arg_name: default})
                arguments.append(argument)
            fields = set()
            for _, field, spec, conversion in Formatter().parse(command):
                if field is not None:
                    if not re.fullmatch(r"[a-z][a-z0-9_]*", field) or spec or conversion:
                        raise ValueError(f"Tool {tool_name} has an unsafe template field.")
                    fields.add(field)
            if fields - arg_names:
                raise ValueError(f"Tool {tool_name} refers to undeclared arguments: {', '.join(sorted(fields - arg_names))}.")
            if any(field in tokens[0] for field in ("{", "}")):
                raise ValueError(f"Tool {tool_name} must use a fixed executable.")
            preview = [token.format_map({a.name: str(a.default) for a in arguments}) for token in tokens]
            if not allowed_command(preview, permissions):
                raise ValueError(f"Tool {tool_name} command is not allowed by the declared permissions or command policy.")
            tools.append(ToolDefinition(tool_name, str(tool_description or tool_name), command, tuple(arguments),
                                        phrase_list(raw_tool, "triggers"), phrase_list(raw_tool, "examples")))
        triggers = phrase_list(data, "triggers")
        examples = phrase_list(data, "examples")
        response_template = data.get("response_template", "{result}")
        if not isinstance(response_template, str) or len(response_template) > 2048:
            raise ValueError("Response template must be a string of at most 2048 characters.")
        common_args = set.intersection(*(set(argument.name for argument in tool.arguments) for tool in tools))
        allowed_fields = common_args | {"result"}
        for _, field, spec, conversion in Formatter().parse(response_template):
            if field is not None and (field not in allowed_fields or spec or conversion):
                raise ValueError("Response template uses an undeclared or unsafe field.")
        success_emote = str(data.get("emote_on_success", "HAPPY")).upper()
        failure_emote = str(data.get("emote_on_failure", "CONFUSED")).upper()
        if success_emote not in VALID_EMOTES or failure_emote not in VALID_EMOTES:
            raise ValueError("Skill emotes must use a supported emote name.")
        return SkillDefinition(
            name=name.strip(), slug=slug, description=description.strip(),
            permissions=permissions, triggers=triggers, tools=tuple(tools), examples=examples,
            response_template=response_template,
            emote_on_success=success_emote,
            emote_on_failure=failure_emote,
            **metadata,
        )
