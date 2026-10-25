"""Terminal controls for the skill hub; these do not call the cloud model."""

import asyncio
import json
import shlex

from blob.skills.base import SkillResult
from blob.privacy.controls import PrivacyBlocked

SKILL_HELP = """/skills — list available tools
/skills <tool> — inspect arguments and permissions
/skills run <tool> <JSON arguments> — run a tool directly
/skills history — show recent execution status
/skills doctor [tool] — check dependencies, privacy and command isolation
/skills project [path|clear] — inspect or select the active approved project
/skills packages | info <skill_id> — inspect installed skill metadata
/skills preview <file> — validate and compare an update without installing
/skills install <file> — install/update and report permission changes
/skills rollback <skill_id> — restore the previous installed version
/skills uninstall <skill_id> — remove an installed skill or custom override
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
                    lines.append(f"{name} [{registry.health(name)['status']}]: {info['description']}")
                if registry.load_errors:
                    lines.append(f"{len(registry.load_errors)} skill file(s) failed to load. Use /skills doctor.")
                return SkillResult("Available tools:\n" + "\n".join(lines) + "\n\n" + SKILL_HELP, True)
            if parts[1] == "doctor":
                if len(parts) > 3:
                    raise ValueError("Usage: /skills doctor [tool]")
                from blob.skills.health import format_health
                report = await asyncio.to_thread(registry.doctor, parts[2] if len(parts) == 3 else None)
                lines = [format_health(item) for item in report["tools"]]
                lines.extend(f"Load failed: {path}: {error}" for path, error in report["load_errors"].items())
                return SkillResult("Skill health:\n" + ("\n".join(lines) or "No tools installed."),
                                   not report["load_errors"] and all(item["status"] == "ready" for item in report["tools"]))
            if parts[1] == "help":
                return SkillResult(SKILL_HELP, True)
            if parts[1] == "packages":
                if len(parts) != 2:
                    raise ValueError("Usage: /skills packages")
                lines = [f"{item['slug']} · {item['version']} · {item['author'] or 'unknown author'} · "
                         f"{'bundled' if item['bundled'] else 'installed'} · {len(item['tools'])} tools"
                         for item in registry.packages()]
                return SkillResult("Skill packages:\n" + ("\n".join(lines) or "No YAML skills loaded."), True)
            if parts[1] in {"info", "preview", "install", "rollback", "uninstall"}:
                tokens = shlex.split(text)
                action = parts[1]
                if len(tokens) != 3:
                    raise ValueError(f"Usage: /skills {action} <{'file' if action in {'preview', 'install'} else 'skill_id'}>")
                value = tokens[2]
                if action == "info":
                    return SkillResult(json.dumps(registry.package(value), indent=2, ensure_ascii=False), True)
                if action == "preview":
                    change = registry.preview_file(value)
                    return SkillResult(f"Preview: {change['slug']}\n" + registry.format_change(change), True)
                if action == "uninstall":
                    output = registry.uninstall(value)
                else:
                    slug = registry.rollback(value) if action == "rollback" else registry.install_file(value)
                    output = registry.installation_summary(slug)
                if registry.controls:
                    registry.controls.cancel_requests()
                return SkillResult(output, True)
            if parts[1] == "project":
                tokens = shlex.split(text)
                controls = registry.controls
                if not controls:
                    raise ValueError("Runtime privacy controls are unavailable.")
                if len(tokens) == 2:
                    selected = controls.state["active_project"]
                    if selected:
                        return SkillResult(f"Active project: {selected}", True)
                    if len(controls.folders) == 1:
                        return SkillResult(f"Default project (only approved folder): {controls.folders[0]}", True)
                    return SkillResult("No active project. Use /skills project /approved/path.\nApproved folders:\n" +
                                       "\n".join(map(str, controls.folders)), True)
                if len(tokens) != 3:
                    raise ValueError("Usage: /skills project [path|clear] (quote paths containing spaces)")
                selected = controls.select_project(None if tokens[2] == "clear" else tokens[2])
                controls.cancel_requests()
                return SkillResult(f"Active project: {selected}" if selected else "Active project cleared.", True)
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
            from blob.skills.health import format_health
            package = info["package"]
            metadata = (f"Skill: {package['slug']} · version {package['version']} · "
                        f"author {package['author'] or 'unknown'}\n") if package else ""
            return SkillResult(f"{info['name']}: {info['description']}\n"
                               f"Health: {format_health(registry.health(parts[1]))}\n"
                               f"{metadata}"
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
    except (ValueError, TypeError, OSError, PrivacyBlocked) as exc:
        return SkillResult(str(exc), False, "CONFUSED")
