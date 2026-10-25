"""Metadata, non-mutating previews, durable rollback and uninstall behavior."""

from pathlib import Path

import pytest

from blob.privacy.controls import PrivacyControls
from blob.skills.commands import handle_skill_command
from blob.skills.registry import SkillRegistry
from test_skill_registry import SKILL_YAML


def definition(version="1.0.0", *, extra_permission=False, tool="echo_text"):
    content = SKILL_YAML.replace("name: Echo Example", f'name: Echo Example\n  version: "{version}"\n  author: Sample Author\n  color: "#AABBCC"\n  icon: terminal')
    content = content.replace("name: echo_text", f"name: {tool}")
    return content.replace("[shell.execute]", "[shell.execute, filesystem.read]") if extra_permission else content


def install(tmp_path):
    source = tmp_path / "sample.skill.yaml"
    source.write_text(definition())
    registry = SkillRegistry(tmp_path / "installed")
    registry.install_file(source)
    return registry, source


def test_metadata_persists_and_preview_has_no_side_effects(tmp_path):
    registry, source = install(tmp_path)
    info = registry.package("echo_example")
    assert (info["version"], info["author"], info["color"], info["icon"]) == ("1.0.0", "Sample Author", "#AABBCC", "terminal")
    assert registry.describe("echo_example.echo_text")["package"] == info
    installed = Path(info["source"])
    previous = installed.read_bytes()
    source.write_text(definition("2.0.0", extra_permission=True, tool="say"))
    change = registry.preview_file(source)
    assert change["previous_version"] == "1.0.0" and change["version"] == "2.0.0"
    assert change["permissions_added"] == ["filesystem.read"]
    assert change["tools_added"] == ["echo_example.say"]
    assert change["tools_removed"] == ["echo_example.echo_text"]
    assert installed.read_bytes() == previous
    assert not registry.package("echo_example")["rollback_available"]
    assert registry.package("echo_example")["version"] == "1.0.0"


def test_upgrade_and_rollback_survive_restart(tmp_path):
    registry, source = install(tmp_path)
    source.write_text(definition("2.0.0", extra_permission=True, tool="say"))
    registry.install_file(source)
    assert "Permissions added: filesystem.read" in registry.installation_summary("echo_example")
    snapshot = registry.install_dir / ".rollback/echo_example.skill.yaml"
    assert snapshot.stat().st_mode & 0o777 == 0o600
    assert snapshot.parent.stat().st_mode & 0o777 == 0o700
    restarted = SkillRegistry(registry.install_dir)
    assert restarted.load_directory(registry.install_dir) == []
    assert len(restarted.packages()) == 1
    assert restarted.package("echo_example")["rollback_available"]
    restarted.rollback("echo_example")
    assert restarted.package("echo_example")["version"] == "1.0.0"
    assert restarted.get_skill("echo_example.say") is None
    assert restarted.get_skill("echo_example.echo_text").execute({"text": "works"}).success
    again = SkillRegistry(registry.install_dir)
    assert again.load_directory(registry.install_dir) == []
    assert again.package("echo_example")["version"] == "1.0.0"
    again.rollback("echo_example")
    assert again.package("echo_example")["version"] == "2.0.0"
    assert again.uninstall("echo_example") == "Uninstalled echo_example."
    assert not again.packages() and not list(registry.install_dir.glob("*.skill.yaml"))
    assert not snapshot.exists()
    assert not SkillRegistry(registry.install_dir).load_directory(registry.install_dir)


def test_identical_reinstall_does_not_destroy_previous_snapshot(tmp_path):
    registry, source = install(tmp_path)
    source.write_text(definition("2.0.0"))
    registry.install_file(source)
    registry.install_file(source)
    registry.rollback("echo_example")
    assert registry.package("echo_example")["version"] == "1.0.0"


def test_rejects_corrupt_snapshots_and_failed_updates_preserve_active_skill(tmp_path, monkeypatch):
    registry, source = install(tmp_path)
    source.write_text(definition("2.0.0"))
    original_write = registry._write_file
    def fail_destination(destination, content):
        if destination.parent == registry.install_dir:
            raise OSError("disk full")
        original_write(destination, content)
    monkeypatch.setattr(registry, "_write_file", fail_destination)
    with pytest.raises(OSError, match="disk full"):
        registry.install_file(source)
    assert registry.package("echo_example")["version"] == "1.0.0"
    assert 'version: "1.0.0"' in (registry.install_dir / "echo_example.skill.yaml").read_text()
    snapshot = registry.install_dir / ".rollback/echo_example.skill.yaml"
    snapshot.write_text(definition().replace("Echo Example", "Different Skill"))
    with pytest.raises(ValueError, match="does not match"):
        registry.rollback("echo_example")
    with pytest.raises(ValueError, match="Unknown installed skill"):
        registry.rollback("../../outside")


def test_uninstall_override_restores_bundled_skill(tmp_path):
    registry = SkillRegistry(tmp_path / "installed")
    bundled = Path(__file__).resolve().parents[1] / "blob/data/skills"
    registry.load_directory(bundled)
    slug = "git_status_checker"
    assert registry.package(slug)["bundled"]
    with pytest.raises(ValueError, match="cannot be uninstalled"):
        registry.uninstall(slug)
    source = tmp_path / "override.skill.yaml"
    source.write_text((bundled / "git_status.skill.yaml").read_text().replace('"1.0.0"', '"2.0.0"'))
    registry.install_file(source)
    assert not registry.package(slug)["bundled"]
    assert "Restored the bundled skill" in registry.uninstall(slug)
    assert registry.package(slug)["bundled"] and registry.package(slug)["version"] == "1.0.0"
    assert not (registry.install_dir / f"{slug}.skill.yaml").exists()


@pytest.mark.parametrize("field, value", [("version", "latest"), ("version", 1), ("author", []), ("icon", 42), ("color", "red")])
def test_invalid_metadata_is_rejected_before_replacement(tmp_path, field, value):
    import yaml
    registry, source = install(tmp_path)
    data = yaml.safe_load(definition("2.0.0"))
    data["skill"][field] = value
    source.write_text(yaml.safe_dump(data))
    with pytest.raises(ValueError, match=field):
        registry.install_file(source)
    assert registry.package("echo_example")["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_management_commands_and_privacy_pause(tmp_path):
    registry, source = install(tmp_path)
    assert "Sample Author" in (await handle_skill_command(registry, "/skills packages")).output
    assert '"version": "1.0.0"' in (await handle_skill_command(registry, "/skills info echo_example")).output
    source.write_text(definition("2.0.0", extra_permission=True))
    assert "Permissions added: filesystem.read" in (await handle_skill_command(registry, f'/skills preview "{source}"')).output
    assert registry.package("echo_example")["version"] == "1.0.0"
    assert (await handle_skill_command(registry, f'/skills install "{source}"')).success
    assert (await handle_skill_command(registry, "/skills rollback echo_example")).success
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    controls.update(paused=True)
    registry.controls = controls
    assert not (await handle_skill_command(registry, "/skills uninstall echo_example")).success
    controls.update(paused=False)
    assert (await handle_skill_command(registry, "/skills uninstall echo_example")).success
    assert not (await handle_skill_command(registry, "/skills rollback echo_example")).success


def test_symlinked_rollback_storage_cannot_modify_other_files(tmp_path):
    registry, source = install(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (registry.install_dir / ".rollback").symlink_to(outside, target_is_directory=True)
    source.write_text(definition("2.0.0"))
    with pytest.raises(ValueError, match="symbolic links"):
        registry.install_file(source)
    assert not list(outside.iterdir())


def test_same_version_command_changes_are_visible_in_preview(tmp_path):
    registry, source = install(tmp_path)
    source.write_text(definition().replace("echo {text}", "echo updated-{text}"))
    change = registry.preview_file(source)
    assert change["changed"] and change["tools_changed"] == ["echo_example.echo_text"]
    assert registry.package("echo_example")["commands"] == {"echo_text": "echo {text}"}


def test_cli_upgrade_loads_current_version_and_keeps_a_snapshot(tmp_path, monkeypatch, capsys):
    from types import SimpleNamespace
    from blob.main import main
    registry, source = install(tmp_path)
    source.write_text(definition("2.0.0", extra_permission=True))
    monkeypatch.setattr("blob.main.BlobConfig.load", lambda: SimpleNamespace(
        skills_dir_path=registry.install_dir, privacy_settings_path=tmp_path / "private/privacy.json"))
    monkeypatch.setattr("sys.argv", ["blob-backend", "--install-skill", str(source)])
    main()
    output = capsys.readouterr().out
    assert "Version: 1.0.0 -> 2.0.0" in output
    assert "Permissions added: filesystem.read" in output
    restarted = SkillRegistry(registry.install_dir)
    restarted.load_directory(registry.install_dir)
    restarted.rollback("echo_example")
    assert restarted.package("echo_example")["version"] == "1.0.0"


@pytest.mark.asyncio
async def test_management_commands_keep_their_request_alive_and_cancel_other_work(tmp_path):
    import asyncio
    from blob.ipc import blob_service_pb2 as pb
    from test_reply_presentation import normal_chat

    registry, source = install(tmp_path)
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    project = tmp_path / "project"
    project.mkdir()
    controls.approve(project)
    registry.controls = controls
    blob = normal_chat()
    blob.controls = controls
    blob.skill_registry = registry
    pending = asyncio.create_task(asyncio.sleep(3600))
    controls.tasks.add(pending)
    try:
        selection = await blob.handle_user_message(pb.UserMessage(text=f"/skills project {project}"))
        assert f"Active project: {project}" in selection
        await asyncio.sleep(0)
        assert pending.cancelled()
        source.write_text(definition("2.0.0"))
        for text, expected in (
            (f"/skills install {source}", "Version: 1.0.0 -> 2.0.0"),
            ("/skills rollback echo_example", "Version: 2.0.0 -> 1.0.0"),
            ("/skills uninstall echo_example", "Uninstalled echo_example"),
        ):
            assert expected in await blob.handle_user_message(pb.UserMessage(text=text))
    finally:
        pending.cancel()
        await asyncio.gather(pending, return_exceptions=True)
        controls.tasks.discard(pending)
