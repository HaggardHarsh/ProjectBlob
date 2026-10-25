"""Small, shared argument contracts for built-in and installed skills."""

import math

PROJECT_ARGUMENT = {"type": "string", "minLength": 1, "maxLength": 4096,
                    "description": "Working directory inside an approved folder. Defaults to the active project."}


def object_schema(properties=None, required=()):
    return {"type": "object", "properties": properties or {},
            "required": list(required), "additionalProperties": False}


def validate_arguments(schema, args):
    if not isinstance(args, dict) or any(not isinstance(key, str) for key in args):
        raise ValueError("Tool arguments must be an object with string keys.")
    if schema is None:  # Compatibility with externally registered Python tools.
        return dict(args)
    properties = schema.get("properties", {})
    unknown = set(args) - set(properties)
    if unknown:
        raise ValueError("Unknown arguments: " + ", ".join(sorted(unknown)) + ".")
    values = dict(args)
    for name, rule in properties.items():
        if name not in values and "default" in rule:
            values[name] = rule["default"]
        if name not in values:
            if name in schema.get("required", ()):
                raise ValueError(f"Missing required argument: {name}.")
            continue
        value, kind = values[name], rule.get("type", "string")
        valid = (isinstance(value, str) if kind == "string" else
                 type(value) is bool if kind == "boolean" else
                 type(value) is int if kind == "integer" else
                 type(value) in {int, float} if kind == "number" else False)
        if not valid:
            raise ValueError(f"Argument '{name}' must be a {kind}.")
        if kind in {"number", "integer"}:
            try:
                finite = math.isfinite(value)
            except OverflowError:
                finite = False
            if not finite:
                raise ValueError(f"Argument '{name}' must be finite.")
            for field, invalid in (("minimum", lambda n: value < n), ("maximum", lambda n: value > n),
                                   ("exclusiveMinimum", lambda n: value <= n)):
                if field in rule and invalid(rule[field]):
                    raise ValueError(f"Argument '{name}' is outside its allowed range.")
        if kind == "string":
            if len(value) < rule.get("minLength", 0) or len(value) > rule.get("maxLength", 4096):
                raise ValueError(f"Argument '{name}' has an invalid length.")
        if "enum" in rule and value not in rule["enum"]:
            raise ValueError(f"Argument '{name}' must be one of: {', '.join(map(str, rule['enum']))}.")
    return values
