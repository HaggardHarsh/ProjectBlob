"""Health diagnostics report installed-but-blocked tools without running them."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from blob.ipc import blob_service_pb2 as pb
from blob.ipc.servicer import BlobServiceServicer
from blob.privacy.controls import PrivacyControls
from blob.skills.commands import handle_skill_command
from blob.skills.registry import SkillRegistry
from test_skill_registry import SKILL_YAML


def installed(tmp_path):
    source = tmp_path / "echo.skill.yaml"
    source.write_text(SKILL_YAML)
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    registry = SkillRegistry(tmp_path / "installed", controls=controls)
    registry.install_file(source)
    return registry, controls, source


def test_dependencies_privacy_and_installation_feedback(tmp_path, monkeypatch):
    registry, controls, _ = installed(tmp_path)
    monkeypatch.setattr("blob.skills.health.shutil.which", lambda name: None)
    report = registry.health("echo_example.echo_text")
    assert report["status"] == "blocked"
    assert "Required command is missing: echo" in " ".join(report["issues"])
    assert "Bubblewrap is missing" in " ".join(report["issues"])
    assert "No approved folders" in " ".join(report["issues"])
    assert "Installed but blocked" in registry.installation_summary("echo_example")
    controls.approve(tmp_path)
    controls.update(disabled_skills=["echo_example.echo_text"], paused=True)
    assert "Disabled" in " ".join(registry.health("echo_example.echo_text")["issues"])
    assert "Privacy pause" in " ".join(registry.health("echo_example.echo_text")["issues"])


def test_network_command_is_installed_but_explicitly_blocked(tmp_path, monkeypatch):
    registry, controls, source = installed(tmp_path)
    source.write_text(SKILL_YAML.replace("shell.execute", "network.http").replace("echo {text}", "curl -s https://example.com/{text}"))
    registry.install_file(source)
    controls.approve(tmp_path)
    monkeypatch.setattr("blob.skills.health.shutil.which", lambda name: "/usr/bin/" + name)
    assert "Network commands are blocked" in registry.installation_summary("echo_example")


def test_doctor_probes_isolation_once_and_never_runs_a_skill(tmp_path, monkeypatch):
    registry, controls, _ = installed(tmp_path)
    controls.approve(tmp_path)
    monkeypatch.setattr("blob.skills.health.shutil.which", lambda name: "/usr/bin/" + name)
    calls = []
    def probe(argv, **kwargs):
        calls.append(argv)
        return SimpleNamespace(returncode=1, stdout="")
    monkeypatch.setattr("blob.skills.process.run_command", probe)
    report = registry.doctor()
    assert calls == [["echo", "blob-isolation-check"]]
    assert report["tools"][0]["status"] == "blocked"
    assert "Isolation check failed" in report["tools"][0]["issues"][0]
    monkeypatch.setattr("blob.skills.process.run_command", lambda *a, **kw: SimpleNamespace(returncode=0, stdout="blob-isolation-check\n"))
    assert registry.doctor()["tools"][0]["status"] == "ready"


@pytest.mark.asyncio
async def test_load_errors_are_visible_and_clear_after_repair(tmp_path):
    registry, _, source = installed(tmp_path)
    source.write_text("skill: broken")
    assert registry.load_directory(tmp_path)
    result = await handle_skill_command(registry, "/skills")
    assert "failed to load" in result.output
    report = await handle_skill_command(registry, "/skills doctor")
    assert "Load failed" in report.output and not report.success
    source.write_text(SKILL_YAML)
    assert registry.load_directory(tmp_path) == []
    assert registry.load_errors == {}
    assert not (await handle_skill_command(registry, "/skills doctor unknown")).success


@pytest.mark.asyncio
async def test_drop_acknowledgment_includes_blocked_reason(tmp_path):
    registry, controls, source = installed(tmp_path)
    dispatcher = SimpleNamespace(broadcast=AsyncMock())
    servicer = BlobServiceServicer(dispatcher, SimpleNamespace(skill_registry=registry, controls=controls))
    event = pb.FrontendEvent()
    event.skill_pill_drop.file_path = str(source)
    await servicer.handle_frontend_event(event)
    ack = dispatcher.broadcast.call_args.args[0].skill_ack
    assert ack.success
    assert "Installed but blocked" in ack.description
    assert "No approved folders" in ack.description
