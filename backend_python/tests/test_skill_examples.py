"""Run reviewed examples through the real registry and Bubblewrap runner."""

from pathlib import Path
import re
import shutil
import subprocess

import pytest

from blob.privacy.controls import PrivacyControls
from blob.skills.commands import handle_skill_command
from blob.skills.process import run_command
from blob.skills.registry import SkillRegistry


ROOT = Path(__file__).resolve().parents[2]
BUNDLED = ROOT / "backend_python/blob/data/skills"


def runtime(tmp_path):
    if not shutil.which("bwrap"):
        pytest.skip("Bubblewrap not installed")
    project = tmp_path / "project"
    project.mkdir()
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    controls.approve(project)
    probe = run_command(["echo", "probe"], controls=controls)
    if probe.returncode and any(text in probe.stdout for text in (
            "Operation not permitted", "Creating new namespace failed", "Permission denied")):
        pytest.skip("Host disallows unprivileged namespaces")
    assert probe.returncode == 0, probe.stdout
    return project, SkillRegistry(tmp_path / "skills", controls=controls)


def test_packaged_examples_match_reviewed_sources():
    assert {path.name for path in BUNDLED.glob("*.skill.yaml")} == {path.name for path in (ROOT / "skills").glob("*.skill.yaml")}
    for path in BUNDLED.glob("*.skill.yaml"):
        assert path.read_bytes() == (ROOT / "skills" / path.name).read_bytes()


@pytest.mark.asyncio
async def test_documented_authoring_example_install_discover_execute_and_uninstall(tmp_path):
    _, registry = runtime(tmp_path)
    guide = (ROOT / "docs/skill_authoring_guide.md").read_text()
    examples = [block for block in re.findall(r"```yaml\n(.*?)```", guide, flags=re.S) if block.startswith("skill:")]
    assert examples
    for index, example in enumerate(examples):
        source = tmp_path / f"documented-{index}.skill.yaml"
        source.write_text(example)
        preview = await handle_skill_command(registry, f"/skills preview {source}")
        assert preview.success
        assert not registry.packages()
        installed = await handle_skill_command(registry, f"/skills install {source}")
        assert installed.success and "Permissions added: shell.execute" in installed.output
        assert registry.discover("Show remaining storage")[0]["name"] == "system_monitor.disk_usage"
        assert (await handle_skill_command(registry, "/skills doctor system_monitor.disk_usage")).success
        result = await handle_skill_command(registry, '/skills run system_monitor.disk_usage {"path":"."}')
        assert result.success and "Disk usage:" in result.output and "Filesystem" in result.output
        assert (await handle_skill_command(registry, "/skills uninstall system_monitor")).success


@pytest.mark.asyncio
async def test_every_bundled_command_executes_or_reports_its_network_block(tmp_path):
    project, registry = runtime(tmp_path)
    subprocess.run(["git", "init", "-q", "--initial-branch=main", str(project)], check=True)
    fixture = project / "lesson.txt"
    fixture.write_text("searchable fixture content\n")
    subprocess.run(["git", "-C", str(project), "add", "lesson.txt"], check=True)
    subprocess.run(["git", "-C", str(project), "-c", "user.name=Blob Test", "-c", "user.email=blob@example.invalid",
                    "commit", "-q", "--no-gpg-sign", "-m", "Fixture commit"], check=True)
    fixture.write_text("searchable fixture content\nmodified fixture\n")
    assert registry.load_directory(BUNDLED) == []
    args = {
        "local_file_search.find_by_name": {"pattern": "lesson"},
        "local_file_search.find_by_extension": {"ext": "txt"},
        "local_file_search.find_by_content": {"text": "searchable", "ext": "txt"},
        "local_file_search.recent_files": {"minutes": 60},
    }
    assert len(registry.skills) == 12
    for name in sorted(registry.skills):
        if name.startswith("weather_fetcher."):
            assert registry.health(name)["status"] == "blocked"
            result = await registry.execute(name, {"location": "Delhi"}, source="terminal")
            assert not result.success and "Network commands are disabled" in result.output
        else:
            assert registry.health(name)["status"] == "ready"
            result = await registry.execute(name, args.get(name, {}), source="terminal")
            assert result.success, f"{name}: {result.output}"
            assert len(result.output.encode("utf-8")) <= 8000
            if name.startswith("local_file_search."):
                assert "lesson.txt" in result.output
    assert len(registry.history) == 12
