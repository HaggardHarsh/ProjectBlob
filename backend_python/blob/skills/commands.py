"""Terminal controls for the skill hub; these do not call the cloud model."""

import json
import shlex

from blob.skills.base import SkillResult

SKILL_HELP = """/skills — list available tools
/skills <tool> — inspect arguments and permissions
/skills run <tool> <JSON arguments> — run a tool directly
/skills history — show recent execution status
Example: /skills run git_status {}
Example: /skills run weather {"location":"Delhi"}"""
REMINDER_HELP = """/reminders — list scheduled reminders and IDs
/reminders add <minutes> <message> — set a timer
/reminders at <ISO date/time> <message> — schedule a reminder
/reminders every <minutes> <message> — repeat at this interval
/reminders cancel <id> — cancel a reminder
/reminders snooze <id> <minutes> — postpone a reminder
Example: /reminders add 25 Take a study break
Example: /reminders at 2026-10-05T09:00:00+05:30 Get ready for HDL"""


async def handle_skill_command(registry, text):
    try:
        parts = text.split(maxsplit=3)
        command = parts[0].lower()
        if command == "/skills":
            if len(parts) == 1:
                lines = []
                for name in sorted(registry.skills):
                    info = registry.describe(name)
                    lines.append(f"{name}: {info['description']}")
                return SkillResult("Available tools:\n" + "\n".join(lines) + "\n\n" + SKILL_HELP, True)
            if parts[1] == "help":
                return SkillResult(SKILL_HELP, True)
            if parts[1] == "history":
                lines = [f"{'OK' if item['success'] else 'FAILED'} · {item['name']} · {item['duration_ms']} ms · {item['source']}"
                         for item in registry.history]
                return SkillResult("Recent skill runs:\n" + "\n".join(lines) if lines else "No skills have run this session.", True)
            if parts[1] == "run":
                if len(parts) != 4:
                    raise ValueError("Usage: /skills run <tool> <JSON arguments>")
                return await registry.execute(parts[2], json.loads(parts[3]), source="terminal")
            if len(parts) != 2:
                raise ValueError(SKILL_HELP)
            info = registry.describe(parts[1])
            return SkillResult(f"{info['name']}: {info['description']}\n"
                               f"Permissions: {', '.join(info['permissions']) or 'none'}\n"
                               f"Timeout: {info['timeout_seconds']} seconds\n"
                               "Arguments:\n" + json.dumps(info["arguments"], indent=2, ensure_ascii=False), True)
        tokens = shlex.split(text)
        action = tokens[1].lower() if len(tokens) > 1 else "list"
        if action == "help":
            return SkillResult(REMINDER_HELP, True)
        if action == "list" and len(tokens) <= 2:
            args = {"action": "list"}
        elif action in {"add", "at", "every"} and len(tokens) >= 4:
            args = {"message": " ".join(tokens[3:])}
            if action == "at":
                args["at"] = tokens[2]
            else:
                args["minutes"] = float(tokens[2])
                if action == "every":
                    args["repeat_minutes"] = args["minutes"]
        elif action == "cancel" and len(tokens) == 3:
            args = {"action": "cancel", "id": tokens[2]}
        elif action == "snooze" and len(tokens) == 4:
            args = {"action": "snooze", "id": tokens[2], "minutes": float(tokens[3])}
        else:
            raise ValueError(REMINDER_HELP)
        return await registry.execute("reminder", args, source="terminal")
    except (ValueError, TypeError) as exc:
        return SkillResult(str(exc), False, "CONFUSED")
