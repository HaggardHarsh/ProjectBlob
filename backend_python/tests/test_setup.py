"""Installer ordering, isolation, and recovery without host service or package changes."""

import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest


@pytest.fixture
def setup_module(monkeypatch, tmp_path):
    tools = Path(__file__).resolve().parents[2] / "tools"
    monkeypatch.syspath_prepend(str(tools))
    spec = importlib.util.spec_from_file_location("blob_setup_test", tools / "setup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "PROJECT", tmp_path / "Project with spaces %")
    module.PROJECT.mkdir()
    return module


def test_existing_install_is_rejected_before_system_package_changes(setup_module, monkeypatch):
    module = setup_module
    (module.PROJECT / "venv").mkdir()
    monkeypatch.setattr(module.os, "geteuid", lambda: 1000)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(module, "run", lambda *a, **k: pytest.fail("Existing install reached a mutation"))
    args = argparse.Namespace(check=False, prepare_only=False, install_system_deps=True)
    with pytest.raises(module.SetupError, match="already exists"):
        module.preflight(args)


def test_prepare_failure_never_activates_or_overwrites_settings(setup_module, monkeypatch):
    module = setup_module
    settings = module.PROJECT / ".env"
    settings.write_text("existing settings")
    monkeypatch.setattr(module, "preflight", lambda args: None)
    calls = []

    def fail_install(command, **kwargs):
        calls.append(command)
        if "pip" in command:
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(module, "run", fail_install)
    monkeypatch.setattr(module, "activate", lambda *a: pytest.fail("Failed build activated"))
    assert module.main([]) == 1
    assert settings.read_text() == "existing settings"
    assert not (module.PROJECT / ".runtime/desktop/current").exists()
    assert not any("systemctl" in call for call in calls)


@pytest.mark.parametrize("python_version", [(3, 14, 0), (3, 12, 0)])
def test_prepare_verifies_packages_daemon_browser_and_native_build_before_startup(setup_module, monkeypatch, python_version):
    module = setup_module
    monkeypatch.setattr(sys, "version_info", python_version)
    commands = []
    monkeypatch.setattr(module, "run", lambda command, **kwargs: commands.append([str(v) for v in command]))
    candidate = module.prepare(SimpleNamespace(ocr=False, jobs=2, install_system_deps=False))
    assert candidate.is_relative_to(module.PROJECT / ".runtime/desktop/releases")
    assert (candidate / "installation.json").is_file()
    joined = [" ".join(command) for command in commands]
    smoke = next(i for i, command in enumerate(joined) if "release_smoke.py" in command)
    browser = next(i for i, command in enumerate(joined) if "playwright install chromium" in command)
    native_test = next(i for i, command in enumerate(joined) if command.startswith("ctest "))
    startup = next(i for i, command in enumerate(joined) if "install_desktop.py" in command)
    assert smoke < browser < native_test < startup
    assert "--stage-dir" in commands[startup]
    assert not any("systemctl" in command for command in commands)
    assert not (module.PROJECT / ".runtime/desktop/current").exists()
    assert any("linux-py314.lock" in command for command in joined) == (python_version[:2] == (3, 14))


def test_check_mode_does_not_prepare_or_activate(setup_module, monkeypatch):
    monkeypatch.setattr(setup_module, "preflight", lambda args: None)
    monkeypatch.setattr(setup_module, "prepare", lambda *a: pytest.fail("Check started an install"))
    assert setup_module.main(["--check"]) == 0


def test_prepare_only_does_not_prompt_for_key_or_activate(setup_module, monkeypatch):
    monkeypatch.setattr(setup_module, "preflight", lambda args: None)
    monkeypatch.setattr(setup_module, "prepare", lambda args: setup_module.PROJECT)
    monkeypatch.setattr(setup_module, "activate", lambda *a: pytest.fail("Prepare changed startup"))
    monkeypatch.setattr(setup_module, "configure_key", lambda: pytest.fail("Prepare requested credentials"))
    assert setup_module.main(["--prepare-only"]) == 0


def test_activation_failure_removes_only_its_pointer(setup_module, monkeypatch):
    candidate = setup_module.PROJECT / ".runtime/desktop/releases/candidate"
    candidate.mkdir(parents=True)
    (candidate / "retained-for-diagnosis").touch()
    monkeypatch.setattr(setup_module, "run", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("startup failed")))
    with pytest.raises(RuntimeError, match="startup failed"):
        setup_module.activate(candidate)
    assert not (setup_module.PROJECT / ".runtime/desktop/current").is_symlink()
    assert (candidate / "retained-for-diagnosis").exists()


def test_existing_pointer_is_never_replaced(setup_module, monkeypatch):
    current = setup_module.PROJECT / ".runtime/desktop/current"
    current.parent.mkdir(parents=True)
    current.symlink_to("existing-install")
    monkeypatch.setattr(setup_module, "run", lambda *a, **k: pytest.fail("Existing install activated"))
    with pytest.raises(FileExistsError):
        setup_module.activate(setup_module.PROJECT)
    assert current.readlink() == Path("existing-install")


def test_key_prompt_is_masked_private_and_never_overwrites(setup_module, monkeypatch, capsys):
    module = setup_module
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr(module.getpass, "getpass", lambda prompt: "synthetic-setup-key")
    module.configure_key()
    target = module.PROJECT / ".env"
    assert target.stat().st_mode & 0o777 == 0o600
    assert "synthetic-setup-key" in target.read_text()
    assert "synthetic-setup-key" not in capsys.readouterr().out
    monkeypatch.setattr(module.getpass, "getpass", lambda prompt: pytest.fail("Existing .env prompted"))
    module.configure_key()
    assert "synthetic-setup-key" in target.read_text()


def test_environment_key_is_persisted_for_desktop_startup_without_echo(setup_module, monkeypatch, capsys):
    monkeypatch.setenv("NEBIUS_API_KEY", "synthetic-environment-key")
    monkeypatch.setattr(setup_module.getpass, "getpass", lambda prompt: pytest.fail("Environment key prompted"))
    setup_module.configure_key()
    assert "synthetic-environment-key" in (setup_module.PROJECT / ".env").read_text()
    assert "synthetic-environment-key" not in capsys.readouterr().out


@pytest.fixture
def desktop_module(setup_module, monkeypatch, tmp_path):
    import install_desktop
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    return install_desktop


def test_fresh_guard_rejects_existing_files_before_service_commands(desktop_module, monkeypatch):
    targets = desktop_module.desktop_targets()
    existing = next(iter(targets.values()))
    existing.parent.mkdir(parents=True)
    existing.write_text("keep my unit")
    monkeypatch.setattr(desktop_module.subprocess, "run", lambda *a, **k: pytest.fail("Existing file reached services"))
    with pytest.raises(RuntimeError, match="left unchanged"):
        desktop_module.require_fresh_desktop(targets)
    assert existing.read_text() == "keep my unit"


def test_fresh_guard_rejects_service_from_another_search_location(desktop_module, monkeypatch):
    monkeypatch.setattr(desktop_module.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout="loaded\n"))
    with pytest.raises(RuntimeError, match="Existing service"):
        desktop_module.require_fresh_desktop(desktop_module.desktop_targets())
    assert not any(target.exists() for target in desktop_module.desktop_targets().values())


@pytest.mark.parametrize("failure_stage", ["start", "health"])
def test_fresh_startup_failure_removes_created_files_and_disables_new_units(desktop_module, setup_module, monkeypatch, failure_stage):
    from blob import desktop
    commands = []
    monkeypatch.setattr(desktop_module, "require_fresh_desktop", lambda targets: None)
    monkeypatch.setattr(desktop_module.subprocess, "run", lambda command, **kwargs: commands.append(command))
    def failure(*args):
        raise RuntimeError("startup failed")
    monkeypatch.setattr(desktop, "start_session", failure if failure_stage == "start" else lambda: None)
    monkeypatch.setattr(desktop_module, "wait_ready", failure)
    with pytest.raises(RuntimeError, match="startup failed"):
        desktop_module.install(setup_module.PROJECT, sys.executable, fresh=True, overlay="/tmp/test-overlay")
    assert not any(target.exists() for target in desktop_module.desktop_targets().values())
    assert ["systemctl", "--user", "stop", "blob-backend.service", "blob-overlay.service"] in commands
    assert ["systemctl", "--user", "disable", "blob-backend.service", "blob-overlay.service"] in commands


def test_successful_fresh_install_verifies_startup_and_uses_candidate_overlay(desktop_module, setup_module, monkeypatch):
    from blob import desktop
    monkeypatch.setattr(desktop_module, "require_fresh_desktop", lambda targets: None)
    monkeypatch.setattr(desktop_module.subprocess, "run", lambda *a, **k: None)
    monkeypatch.setattr(desktop, "start_session", lambda: None)
    checked = []
    monkeypatch.setattr(desktop_module, "wait_ready", lambda *args: checked.append(args))
    overlay = setup_module.PROJECT / "candidate build/blob_overlay"
    desktop_module.install(setup_module.PROJECT, sys.executable, fresh=True, overlay=overlay)
    assert checked == [(setup_module.PROJECT, sys.executable)]
    targets = desktop_module.desktop_targets()
    assert str(overlay).replace("%", "%%") in targets["systemd/user/blob-overlay.service"].read_text()
    assert all(target.stat().st_mode & 0o777 == 0o600 for target in targets.values())


def test_exclusive_stage_write_rolls_back_without_deleting_collision(desktop_module, setup_module, tmp_path):
    stage = tmp_path / "stage"
    collision = stage / "autostart/blob.desktop"
    collision.parent.mkdir(parents=True)
    collision.write_text("another install owns this")
    with pytest.raises(FileExistsError):
        desktop_module.install(setup_module.PROJECT, sys.executable, stage_dir=stage, fresh=True)
    assert collision.read_text() == "another install owns this"
    assert not (stage / "systemd/user/blob-backend.service").exists()
    assert not (stage / "systemd/user/blob-overlay.service").exists()


def test_startup_health_requires_both_services(desktop_module, monkeypatch, tmp_path):
    times = iter([0, 1, 46])
    monkeypatch.setattr(desktop_module.time, "monotonic", lambda: next(times))
    monkeypatch.setattr(desktop_module.time, "sleep", lambda seconds: None)
    calls = []

    def only_backend_active(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="active\nfailed\n")

    monkeypatch.setattr(desktop_module.subprocess, "run", only_backend_active)
    with pytest.raises(RuntimeError, match="did not become ready"):
        desktop_module.wait_ready(tmp_path, sys.executable)
    assert len(calls) == 1
