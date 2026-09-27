"""Runtime skill registry and persistent YAML skill installation."""

import hashlib
import logging
import os
from pathlib import Path
import tempfile

from blob.skills.command_skill import CommandSkill
from blob.skills.validator import SkillValidator

logger = logging.getLogger(__name__)
MAX_SKILL_BYTES = 64 * 1024


class SkillRegistry:
    def __init__(self, install_dir: str | Path | None = None):
        self.skills = {}
        self.install_dir = Path(install_dir or Path.home() / ".blob/skills").expanduser()
        self._installed = {}
        self.validator = SkillValidator()

    def register(self, skill):
        if skill.name in self.skills:
            raise ValueError(f"Skill tool already registered: {skill.name}")
        self.skills[skill.name] = skill

    def get_skill(self, name):
        return self.skills.get(name)

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
