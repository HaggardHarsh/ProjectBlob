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
        self.validator = SkillValidator()
        self.history = deque(maxlen=30)
        self.controls = controls

    def register(self, skill):
        if skill.name in self.skills:
            raise ValueError(f"Skill tool already registered: {skill.name}")
        self.skills[skill.name] = skill
        if self.controls is not None:
            skill.controls = self.controls

    def get_skill(self, name):
        return self.skills.get(name)

    def describe(self, name):
        skill = self.get_skill(name)
        if skill is None:
            raise ValueError(f"Unknown skill: {name}. Use /skills to list tools.")
        return {"name": name, "description": getattr(skill, "description", ""),
                "arguments": getattr(skill, "argument_schema", None),
                "permissions": sorted(getattr(skill, "permissions", ())),
                "timeout_seconds": getattr(skill, "timeout_seconds", 15),
                "model_callable": getattr(skill, "model_callable", True)}

    def prompt_text(self):
        lines = []
        for name in sorted(self.skills):
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

    def install_file(self, file_path: str | Path, expected_hash: bytes | None = None, persist: bool = True) -> str:
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
        new_tools = {f"{definition.slug}.{tool.name}": CommandSkill(definition, tool) for tool in definition.tools}
        for tool in new_tools.values():
            tool.controls = self.controls
        for name in new_tools:
            if name in self.skills and name not in self._installed.get(definition.slug, set()):
                raise ValueError(f"Skill tool conflicts with an existing tool: {name}")
        if persist:
            self.install_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
            os.chmod(self.install_dir, 0o700)
            destination = self.install_dir / f"{definition.slug}.skill.yaml"
            if source.resolve() != destination.resolve():
                with tempfile.NamedTemporaryFile(mode="wb", dir=self.install_dir, prefix=".skill-", delete=False) as temporary:
                    temporary.write(content)
                    temp_path = Path(temporary.name)
                try:
                    os.chmod(temp_path, 0o600)
                    temp_path.replace(destination)
                finally:
                    temp_path.unlink(missing_ok=True)
        for name in self._installed.get(definition.slug, set()):
            self.skills.pop(name, None)
        self.skills.update(new_tools)
        self._installed[definition.slug] = set(new_tools)
        logger.info("Installed skill %s with %d tools", definition.name, len(new_tools))
        return definition.slug

    def load_directory(self, directory: str | Path) -> list[str]:
        path = Path(directory).expanduser()
        if not path.is_dir():
            return []
        errors = []
        for file_path in sorted(path.glob("*.skill.yaml")):
            try:
                self.install_file(file_path, persist=False)
            except (OSError, ValueError) as exc:
                errors.append(f"{file_path.name}: {exc}")
                logger.warning("Could not load skill %s: %s", file_path, exc)
        return errors
