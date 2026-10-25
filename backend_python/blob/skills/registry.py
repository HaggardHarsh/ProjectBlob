"""Runtime skill registry and persistent YAML skill installation."""

import asyncio
from collections import deque
from contextlib import nullcontext
import hashlib
import json
import logging
import os
from pathlib import Path
import tempfile
import time

from blob.skills.base import SkillResult
from blob.skills.contracts import validate_arguments
from blob.skills.command_skill import CommandSkill
from blob.skills.validator import SkillValidator, VALID_EMOTES
from blob.privacy.controls import PrivacyBlocked

logger = logging.getLogger(__name__)
MAX_SKILL_BYTES = 64 * 1024


class SkillRegistry:
    def __init__(self, install_dir: str | Path | None = None, *, controls=None):
        self.skills = {}
        self.install_dir = Path(install_dir or Path.home() / ".blob/skills").expanduser()
        self._installed = {}
        self._contents = {}
        self._sources = {}
        self._bundled = {}
        self._changes = {}
        self.validator = SkillValidator()
        self.history = deque(maxlen=30)
        self.controls = controls
        self.load_errors = {}

    def register(self, skill):
        if skill.name in self.skills:
            raise ValueError(f"Skill tool already registered: {skill.name}")
        self.skills[skill.name] = skill
        if self.controls is not None:
            skill.controls = self.controls

    def get_skill(self, name):
        return self.skills.get(name)

    def discover(self, request):
        from blob.skills.discovery import discover
        disabled = self.controls.state["disabled_skills"] if self.controls else ()
        return discover(self.skills, request, disabled=disabled)

    def health(self, name):
        from blob.skills.health import health
        return health(self, name)

    def doctor(self, name=None):
        from blob.skills.health import doctor
        return doctor(self, name)

    def installation_summary(self, slug):
        from blob.skills.health import format_health
        tools = [self.health(name) for name in sorted(self._installed.get(slug, ()))]
        blocked = [item for item in tools if item["status"] == "blocked"]
        summary = f"Installed skill {slug} ({len(tools)} tools)."
        if slug in self._changes:
            summary += "\n" + self.format_change(self._changes[slug])
        if blocked:
            summary += " Installed but blocked:\n" + "\n".join(format_health(item) for item in blocked)
        return summary

    def package(self, slug):
        if slug not in self._installed:
            raise ValueError("Unknown installed skill. Use /skills packages to list skill IDs.")
        names = sorted(self._installed[slug])
        definition = self.skills[names[0]].definition
        source = self._sources[slug]
        return {"slug": slug, "name": definition.name, "description": definition.description,
                "version": definition.version, "author": definition.author, "color": definition.color,
                "icon": definition.icon, "permissions": sorted(definition.permissions), "tools": names,
                "commands": {tool.name: tool.command for tool in definition.tools},
                "triggers": list(definition.triggers), "examples": list(definition.examples),
                "source": str(source), "bundled": source == self._bundled.get(slug),
                "sha256": hashlib.sha256(self._contents[slug]).hexdigest(),
                "rollback_available": self._rollback_path(slug).is_file()}

    def packages(self):
        return [self.package(slug) for slug in sorted(self._installed)]

    @staticmethod
    def format_change(change):
        lines = [f"Version: {change['previous_version'] or '(new)'} -> {change['version']}"]
        for key, label in (("permissions_added", "Permissions added"), ("permissions_removed", "Permissions removed"),
                           ("tools_added", "Tools added"), ("tools_removed", "Tools removed"),
                           ("tools_changed", "Tools changed")):
            lines.append(f"{label}: {', '.join(change[key]) or 'none'}")
        return "\n".join(lines)

    def describe(self, name):
        skill = self.get_skill(name)
        if skill is None:
            raise ValueError(f"Unknown skill: {name}. Use /skills to list tools.")
        return {"name": name, "description": getattr(skill, "description", ""),
                "arguments": getattr(skill, "argument_schema", None),
                "permissions": sorted(getattr(skill, "permissions", ())),
                "timeout_seconds": getattr(skill, "timeout_seconds", 15),
                "model_callable": getattr(skill, "model_callable", True),
                "triggers": list(getattr(skill, "triggers", ())),
                "examples": list((*skill.definition.examples, *skill.tool.examples)) if isinstance(skill, CommandSkill) else [],
                "package": self.package(skill.definition.slug) if isinstance(skill, CommandSkill) and skill.definition.slug in self._installed else None}

    def prompt_text(self, *, permitted=None):
        lines = []
        for name in sorted(self.skills):
            if permitted is not None and name not in permitted:
                continue
            if self.controls and name in self.controls.state["disabled_skills"]:
                continue
            info = self.describe(name)
            if not info["model_callable"] or name == "camera":
                continue
            schema = info["arguments"]
            contract = (" Arguments: " + json.dumps(schema, separators=(",", ":"), ensure_ascii=False)) if schema else ""
            lines.append(f"- **{name}**: {info['description']}{contract}")
        return "\n".join(lines) or "No tools available."

    async def execute(self, name, args, *, source="model"):
        """One execution path for chat and direct terminal commands."""
        started = time.monotonic()
        try:
            if source not in {"model", "terminal"}:
                raise ValueError("Unknown skill invocation source.")
            info = self.describe(name)
            if self.controls:
                if name in self.controls.state["disabled_skills"]:
                    raise ValueError("This skill is disabled. Use /privacy enable <skill> to allow it.")
                if (self.controls.paused and name != "reminder" and
                        not (name == "camera" and args.get("action") in {"list", "forget"})):
                    raise ValueError("Privacy pause is active. This skill is blocked.")
            if source == "model" and (not info["model_callable"] or name == "camera"):
                raise ValueError("This skill requires an explicit terminal command.")
            values = validate_arguments(info["arguments"], args)
            from blob.ai.tool_policy import MODEL_POLICY
            policy = MODEL_POLICY.get() if source == "model" else None
            if policy:
                values = policy.arguments(name, values)
            requires_cloud = getattr(self.skills[name], "requires_cloud", False)
            with self.controls.operation(cloud=True) if self.controls and requires_cloud else nullcontext():
                cached = policy.read_results.get(values.get("url")) if policy and name == "web_read" else None
                result = cached or await asyncio.wait_for(self.skills[name].async_execute(values), info["timeout_seconds"])
                if self.controls and requires_cloud:
                    self.controls.check(cloud=True)
            if policy:
                policy.observe(name, result, values)
            if not isinstance(result, SkillResult) or not isinstance(result.output, str) or type(result.success) is not bool:
                raise ValueError("The skill returned an invalid result.")
            if len(result.output.encode("utf-8")) > 8000:
                marker = "\n[Additional skill output omitted.]"
                output = result.output.encode("utf-8")[:8000 - len(marker.encode())].decode("utf-8", errors="ignore") + marker
                result = SkillResult(output, result.success, result.emote_suggestion)
            if result.emote_suggestion not in VALID_EMOTES:
                result = SkillResult(result.output, result.success, "IDLE")
        except asyncio.TimeoutError:
            result = SkillResult(f"{name} timed out. Try a narrower request.", False, "WORRIED")
        except (ValueError, TypeError, PrivacyBlocked) as exc:
            result = SkillResult(str(exc), False, "CONFUSED")
        except Exception:
            logger.exception("Skill %s failed", name)
            result = SkillResult(f"{name} failed. Check the local backend logs.", False, "WORRIED")
        # Keep operational metadata, never raw arguments or file contents.
        self.history.append({"name": name, "success": result.success,
                             "duration_ms": round((time.monotonic() - started) * 1000), "source": source})
        return result

    async def close(self):
        for skill in list(self.skills.values()):
            close = getattr(skill, "close", None)
            if close is not None:
                await close()

    def _read_file(self, file_path, expected_hash=None):
        source = Path(file_path).expanduser()
        if not source.name.endswith(".skill.yaml") or source.is_symlink() or not source.is_file():
            raise ValueError("Choose a regular .skill.yaml file.")
        with source.open("rb") as file:
            content = file.read(MAX_SKILL_BYTES + 1)
        if len(content) > MAX_SKILL_BYTES:
            raise ValueError("Skill file is too large (64 KiB maximum).")
        if expected_hash and hashlib.sha256(content).digest() != expected_hash:
            raise ValueError("Skill file hash does not match the dropped file.")
        try:
            definition = self.validator.validate(content.decode("utf-8"))
        except UnicodeDecodeError as exc:
            raise ValueError("Skill file must be UTF-8 text.") from exc
        return source.resolve(), content, definition

    def _prepare(self, definition):
        new_tools = {f"{definition.slug}.{tool.name}": CommandSkill(definition, tool) for tool in definition.tools}
        for tool in new_tools.values():
            tool.controls = self.controls
        for name in new_tools:
            if name in self.skills and name not in self._installed.get(definition.slug, set()):
                raise ValueError(f"Skill tool conflicts with an existing tool: {name}")
        return new_tools

    def _comparison(self, definition, content):
        slug = definition.slug
        previous = self.package(slug) if slug in self._installed else None
        old_permissions = set(previous["permissions"]) if previous else set()
        old_tools = set(previous["tools"]) if previous else set()
        old_definitions = {name: self.skills[name].tool for name in old_tools}
        names = {f"{slug}.{tool.name}" for tool in definition.tools}
        return {"slug": slug, "version": definition.version,
                "previous_version": previous["version"] if previous else None,
                "changed": content != self._contents.get(slug),
                "permissions_added": sorted(definition.permissions - old_permissions),
                "permissions_removed": sorted(old_permissions - definition.permissions),
                "tools_added": sorted(names - old_tools), "tools_removed": sorted(old_tools - names),
                "tools_changed": sorted(f"{slug}.{tool.name}" for tool in definition.tools
                                        if f"{slug}.{tool.name}" in old_definitions and
                                        old_definitions[f"{slug}.{tool.name}"] != tool)}

    def preview_file(self, file_path):
        _, content, definition = self._read_file(file_path)
        self._prepare(definition)
        return self._comparison(definition, content)

    def _rollback_path(self, slug):
        if self.install_dir.is_symlink() or (self.install_dir / ".rollback").is_symlink():
            raise ValueError("Skill storage directories must not be symbolic links.")
        return self.install_dir / ".rollback" / f"{slug}.skill.yaml"

    @staticmethod
    def _write_file(destination, content):
        destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if destination.parent.is_symlink():
            raise ValueError("Skill storage directories must not be symbolic links.")
        os.chmod(destination.parent, 0o700)
        with tempfile.NamedTemporaryFile(mode="wb", dir=destination.parent, prefix=".skill-", delete=False) as temporary:
            temp_path = Path(temporary.name)
            try:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            except BaseException:
                temp_path.unlink(missing_ok=True)
                raise
        try:
            os.chmod(temp_path, 0o600)
            temp_path.replace(destination)
        finally:
            temp_path.unlink(missing_ok=True)

    def install_file(self, file_path: str | Path, expected_hash: bytes | None = None, persist: bool = True) -> str:
        source, content, definition = self._read_file(file_path, expected_hash)
        new_tools = self._prepare(definition)
        change = self._comparison(definition, content)
        slug = definition.slug
        if persist:
            if self.install_dir.is_symlink():
                raise ValueError("Skill storage directories must not be symbolic links.")
            if self.controls:
                self.controls.check()
            previous = self._contents.get(slug)
            if previous is not None and previous != content:
                self._write_file(self._rollback_path(slug), previous)
            destination = self.install_dir / f"{slug}.skill.yaml"
            self._write_file(destination, content)
            old_source = self._sources.get(slug)
            if old_source and old_source != destination.resolve() and old_source.parent == self.install_dir.resolve():
                old_source.unlink(missing_ok=True)
            source = destination.resolve()
        elif source.parent == (Path(__file__).resolve().parents[1] / "data/skills"):
            self._bundled[slug] = source
        for name in self._installed.get(definition.slug, set()):
            self.skills.pop(name, None)
        self.skills.update(new_tools)
        self._installed[slug] = set(new_tools)
        self._contents[slug] = content
        self._sources[slug] = source
        self._changes[slug] = change
        logger.info("Installed skill %s with %d tools", definition.name, len(new_tools))
        return slug

    def rollback(self, slug):
        self.package(slug)  # Validate the ID before constructing a storage path.
        path = self._rollback_path(slug)
        if not path.is_file():
            raise ValueError("No previous version is available for this skill.")
        _, _, definition = self._read_file(path)
        if definition.slug != slug:
            raise ValueError("Rollback snapshot does not match this skill.")
        return self.install_file(path)

    def uninstall(self, slug):
        package = self.package(slug)
        source = self._sources[slug]
        if package["bundled"] or source.parent != self.install_dir.resolve():
            raise ValueError("Bundled/external skills cannot be uninstalled here. Use /privacy disable <tool>.")
        if self.controls:
            self.controls.check()
        bundled = self._bundled.get(slug)
        if bundled:
            self._prepare(self._read_file(bundled)[2])
        source.unlink(missing_ok=True)
        self._rollback_path(slug).unlink(missing_ok=True)
        for name in self._installed.pop(slug):
            self.skills.pop(name, None)
        self._contents.pop(slug, None)
        self._sources.pop(slug, None)
        self._changes.pop(slug, None)
        self.load_errors.pop(str(source), None)
        if bundled:
            self.install_file(bundled, persist=False)
        return f"Uninstalled {slug}." + (" Restored the bundled skill." if bundled else "")

    def load_directory(self, directory: str | Path) -> list[str]:
        path = Path(directory).expanduser()
        if not path.is_dir():
            return []
        errors = []
        for file_path in sorted(path.glob("*.skill.yaml")):
            key = str(file_path.resolve())
            try:
                self.install_file(file_path, persist=False)
                self.load_errors.pop(key, None)
            except (OSError, ValueError) as exc:
                self.load_errors[key] = str(exc)
                errors.append(f"{file_path.name}: {exc}")
                logger.warning("Could not load skill %s: %s", file_path, exc)
        return errors
