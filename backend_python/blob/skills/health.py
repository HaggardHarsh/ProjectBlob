"""Local capability checks; never execute a skill or make a network request."""

import shlex
import shutil

from blob.skills.command_skill import CommandSkill


def health(registry, name):
    skill = registry.get_skill(name)
    if skill is None:
        raise ValueError(f"Unknown skill: {name}. Use /skills to list tools.")
    controls, issues = registry.controls, []
    if controls:
        if name in controls.state["disabled_skills"]:
            issues.append(f"Disabled. Use /privacy enable {name}.")
        if controls.paused and name != "reminder":
            issues.append("Privacy pause is active. Use /privacy resume.")
        if controls.maintaining():
            issues.append("Blob maintenance is active.")
        if getattr(skill, "requires_cloud", False) and not controls.cloud_enabled:
            issues.append("Cloud assistance is off. Use /privacy explain to review data sharing.")
    command_tool = isinstance(skill, CommandSkill) or name in {"git_status", "shell_command"}
    if command_tool:
        executable = shlex.split(skill.tool.command)[0] if isinstance(skill, CommandSkill) else ("git" if name == "git_status" else None)
        if executable and not shutil.which(executable):
            issues.append(f"Required command is missing: {executable}.")
        if executable == "curl":
            issues.append("Network commands are blocked by command isolation. Use built-in weather or web tools.")
        if not shutil.which("bwrap"):
            issues.append("Bubblewrap is missing. Install it to enable command isolation.")
        if not controls:
            issues.append("Runtime privacy controls are unavailable; isolation cannot be checked.")
        elif not controls.folders:
            issues.append("No approved folders. Use /privacy allow /path/to/project.")
        elif not any(root.is_dir() and root.resolve() == root for root in controls.folders):
            issues.append("Approved folders are unavailable or changed. Review /privacy folders.")
    elif name == "file_search" and controls and not controls.folders:
        issues.append("No approved folders. Use /privacy allow /path/to/project.")
    return {"name": name, "status": "blocked" if issues else "ready", "issues": issues}


def doctor(registry, name=None):
    names = [name] if name else sorted(registry.skills)
    results = [health(registry, item) for item in names]
    command_results = [item for item in results if item["status"] == "ready" and (
        isinstance(registry.get_skill(item["name"]), CommandSkill) or item["name"] in {"git_status", "shell_command"})]
    if command_results:
        # Probe the actual namespace once. The probe reads no project files.
        from blob.skills.process import run_command
        try:
            result = run_command(["echo", "blob-isolation-check"], timeout=2, controls=registry.controls)
            if result.returncode or result.stdout.strip() != "blob-isolation-check":
                raise ValueError("Bubblewrap could not start a command namespace on this system.")
        except Exception as exc:
            for item in command_results:
                item["status"] = "blocked"
                item["issues"].append(f"Isolation check failed: {exc}")
    return {"tools": results, "load_errors": dict(registry.load_errors)}


def format_health(item):
    return f"{item['name']}: {item['status']}" + (" — " + " ".join(item["issues"]) if item["issues"] else "")
