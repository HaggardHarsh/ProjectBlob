"""Project selection persists and cannot escape approved read-only folders."""

from pathlib import Path
import shutil
import subprocess

import pytest

from blob.ai.tool_policy import ModelToolPolicy
from blob.privacy.controls import PrivacyBlocked, PrivacyControls
from blob.privacy.sandbox import sandbox_command
from blob.skills.builtin.git_status import GitStatusSkill
from blob.skills.commands import handle_skill_command
from blob.skills.process import run_command
from blob.skills.registry import SkillRegistry


def projects(tmp_path):
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    first, second = tmp_path / "first", tmp_path / "second project"
    first.mkdir()
    second.mkdir()
    controls.approve(first)
    controls.approve(second)
    return controls, first, second


def test_project_is_explicit_with_multiple_folders_and_persists(tmp_path):
    controls, first, second = projects(tmp_path)
    with pytest.raises(PrivacyBlocked, match="Select a project"):
        controls.project_directory()
    controls.select_project(second)
    assert controls.project_directory() == second
    restarted = PrivacyControls(controls.path)
    assert restarted.project_directory() == second
    assert restarted.project_directory(first) == first
    assert restarted.state["active_project"] == str(second)
    restarted.update(approved_folders=[str(first)])
    assert restarted.state["active_project"] is None
    assert restarted.project_directory() == first


def test_project_validation_rejects_unapproved_files_and_symlink_escape(tmp_path):
    controls, first, second = projects(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (first / "escape").symlink_to(outside, target_is_directory=True)
    (first / "file").write_text("content")
    for path in (outside, first / "escape", first / "file", tmp_path / "missing"):
        with pytest.raises(PrivacyBlocked):
            controls.select_project(path)
    controls.select_project(second)
    second.rmdir()
    with pytest.raises(PrivacyBlocked, match="unavailable"):
        controls.project_directory()


def test_namespace_uses_selected_project_and_retains_readonly_isolation(tmp_path, monkeypatch):
    controls, first, second = projects(tmp_path)
    controls.select_project(second)
    monkeypatch.setattr("blob.privacy.sandbox.shutil.which", lambda name: "/usr/bin/bwrap")
    command = sandbox_command(["git", "status"], controls)
    assert command[command.index("--chdir") + 1] == str(second)
    assert "--unshare-all" in command
    assert command[command.index(str(first)) - 1] == "--ro-bind"
    command = sandbox_command(["git", "status"], controls, cwd=first)
    assert command[command.index("--chdir") + 1] == str(first)


@pytest.mark.asyncio
async def test_project_commands_and_model_path_authority(tmp_path):
    controls, first, second = projects(tmp_path)
    registry = SkillRegistry(tmp_path / "skills", controls=controls)
    assert "No active project" in (await handle_skill_command(registry, "/skills project")).output
    result = await handle_skill_command(registry, f'/skills project "{second}"')
    assert result.success and str(second) in result.output
    assert "Active project" in (await handle_skill_command(registry, "/skills project")).output
    assert not (await handle_skill_command(registry, f"/skills project {tmp_path}")).success
    policy = ModelToolPolicy.for_request("Check git status", registry)
    assert policy.arguments("git_status", {"project": str(second)})["project"] == str(second)
    with pytest.raises(ValueError, match="active project"):
        policy.arguments("git_status", {"project": str(first)})
    policy = ModelToolPolicy.for_request(f"Check git status in {first}", registry)
    assert policy.arguments("git_status", {"project": str(first)})["project"] == str(first)
    assert (await handle_skill_command(registry, "/skills project clear")).success
    assert controls.state["active_project"] is None


@pytest.mark.asyncio
async def test_git_and_yaml_tools_use_the_selected_real_repository(tmp_path):
    if not shutil.which("bwrap"):
        pytest.skip("Bubblewrap not installed")
    controls, first, second = projects(tmp_path)
    for path in (first, second):
        subprocess.run(["git", "init", "-q", str(path)], check=True)
    (first / "first-only.txt").write_text("first")
    (second / "second-only.txt").write_text("second")
    controls.select_project(second)
    probe = run_command(["echo", "probe"], controls=controls)
    if probe.returncode and any(text in probe.stdout for text in ("Operation not permitted", "Creating new namespace failed", "Permission denied")):
        pytest.skip("Host disallows unprivileged namespaces")
    assert probe.returncode == 0, probe.stdout
    registry = SkillRegistry(tmp_path / "skills", controls=controls)
    registry.register(GitStatusSkill())
    result = await registry.execute("git_status", {}, source="terminal")
    assert result.success and "second-only.txt" in result.output and "first-only.txt" not in result.output
    directory = Path(__file__).resolve().parents[1] / "blob/data/skills"
    registry.load_directory(directory)
    result = await registry.execute("git_status_checker.git_status", {"project": str(first)}, source="terminal")
    assert result.success and "first-only.txt" in result.output and "second-only.txt" not in result.output
    result = await registry.execute("local_file_search.find_by_name", {"pattern": "second-only"}, source="terminal")
    assert result.success and "second-only.txt" in result.output
