"""Check an installed Blob wheel outside its source checkout, without network calls."""

from importlib.metadata import version
from pathlib import Path
import argparse
import asyncio
import json
import os
import subprocess
import sys
import tempfile


async def check_daemon(root):
    """Exercise the installed daemon with no key, display, camera, or provider calls."""
    import grpc
    from blob.ipc import blob_service_pb2 as pb, blob_service_pb2_grpc as rpc
    from blob.ipc.auth import ipc_token
    from blob.skills.reminder_store import ReminderStore

    store = ReminderStore(root / "reminders.sqlite3")
    store.add("synthetic unread delivery", 1, None, 0)
    delivery_id = store.take_due(2)[0]["delivery_id"]
    store.close()

    env = {key: value for key, value in os.environ.items()
           if not key.startswith(("BLOB_", "NEBIUS_", "OPENAI_")) and key != "PYTHONPATH"}
    env.update({"NEBIUS_API_KEY": "", "BLOB_AGENT_RUNTIME": "classic", "BLOB_CAMERA_ENABLED": "0",
                "ANONYMIZED_TELEMETRY": "False", "BLOB_IPC_ADDRESS": "unix:" + str(root / "blob.sock"),
                "BLOB_IPC_TOKEN_PATH": str(root / "private/token"),
                "BLOB_PRIVACY_SETTINGS_PATH": str(root / "private/privacy.json"),
                "BLOB_MEMORY_DB_PATH": str(root / "memory"), "BLOB_DOCUMENTS_DIR_PATH": str(root / "documents"),
                "BLOB_SKILLS_DIR_PATH": str(root / "skills"),
                "BLOB_REMINDERS_DB_PATH": str(root / "reminders.sqlite3")})
    with (root / "daemon.log").open("w") as log:
        process = subprocess.Popen([sys.executable, "-m", "blob.main", "--daemon"], cwd=root,
                                   env=env, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=log)
        try:
            async with grpc.aio.insecure_channel(env["BLOB_IPC_ADDRESS"]) as channel:
                await asyncio.wait_for(channel.channel_ready(), timeout=20)
                stub = rpc.BlobServiceStub(channel)
                metadata = (("x-blob-token", ipc_token(env["BLOB_IPC_TOKEN_PATH"])),)
                async def send(text):
                    return (await stub.SendUserMessage(pb.UserMessage(text=text), metadata=metadata, timeout=5)).text
                state = json.loads(await send("/privacy status"))
                assert not state["cloud_enabled"] and not state["awareness_enabled"]
                assert "Cloud assistance is off" in await send("Hello")
                assert "synthetic release reminder" in await send("/reminders add 5 synthetic release reminder")
                assert "synthetic release reminder" in await send("/reminders")
                project = root / "project"
                project.mkdir()
                approval = await send(f"/privacy allow {project}")
                assert str(project) in approval, approval
                selection = await send(f"/skills project {project}")
                assert str(project) in selection, selection
                assert str(project) in await send("/skills project")
                skill_file = root / "wheel_probe.skill.yaml"
                definition = ('skill:\n  name: Wheel Probe\n  description: Verify installed wheel skill management\n'
                              '  version: "1.0.0"\n  author: Release Smoke\n  permissions: [shell.execute]\n'
                              '  tools:\n    - name: echo\n      command: echo wheel-skill-v1\n')
                skill_file.write_text(definition)
                assert "Permissions added: shell.execute" in await send(f"/skills preview {skill_file}")
                assert "Installed skill wheel_probe" in await send(f"/skills install {skill_file}")
                assert json.loads(await send("/skills info wheel_probe"))["version"] == "1.0.0"
                skill_file.write_text(definition.replace("1.0.0", "2.0.0").replace("wheel-skill-v1", "wheel-skill-v2"))
                assert "Tools changed: wheel_probe.echo" in await send(f"/skills preview {skill_file}")
                assert "Version: 1.0.0 -> 2.0.0" in await send(f"/skills install {skill_file}")
                assert "Version: 2.0.0 -> 1.0.0" in await send("/skills rollback wheel_probe")
                health = await send("/skills doctor wheel_probe.echo")
                if "wheel_probe.echo: ready" in health:
                    assert "wheel-skill-v1" in await send("/skills run wheel_probe.echo {}")
                else:
                    assert "blocked" in health
                assert "Uninstalled wheel_probe" in await send("/skills uninstall wheel_probe")
                stream = stub.EventStream(metadata=metadata)
                await stream.write(pb.FrontendEvent(heartbeat=pb.HeartbeatPing()))
                try:
                    while True:
                        event = await asyncio.wait_for(stream.read(), timeout=5)
                        if event.HasField("notification") and event.notification.delivery_id == delivery_id:
                            break
                    assert (await stub.AcknowledgeNotification(pb.NotificationAck(delivery_id=delivery_id), metadata=metadata)).acknowledged
                finally:
                    stream.cancel()
                assert "synthetic unread delivery" not in await send("/reminders")
                await send("/privacy cloud on")
                assert "needs an API key" in await send("Hello")
        finally:
            if process.poll() is None:
                process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(process.wait), timeout=10)
            except asyncio.TimeoutError:
                process.kill()
                await asyncio.to_thread(process.wait)
                raise AssertionError("Installed daemon did not shut down cleanly")
        assert process.returncode == 0, "Installed daemon exited with an error"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    args = parser.parse_args()
    import blob
    from blob.config import BlobConfig
    from blob.ipc import blob_service_pb2, blob_service_pb2_grpc
    from blob.privacy.controls import PrivacyBlocked, PrivacyControls
    from blob.privacy.blacklist import BlacklistManager
    import yaml

    source = args.source_root.resolve()
    assert not Path(blob.__file__).resolve().is_relative_to(source / "backend_python"), "Smoke check imported the checkout, not the wheel"
    assert blob.__version__ == version("blob-backend"), "Package version mismatch"
    config = BlobConfig()
    for resource in (config.blacklist_path, config.personality_path, config.openshell_policy_path):
        path = Path(resource)
        assert path.is_file() and path.resolve().is_relative_to(Path(blob.__file__).resolve().parent), "Missing packaged defaults"
        assert yaml.safe_load(path.read_text()), "Empty packaged defaults"
    assert BlacklistManager(config.blacklist_path).patterns, "Packaged privacy blacklist is empty"
    assert Path(config.openshell_policy_path).read_bytes() == (source / "deploy/openshell/policy.yaml").read_bytes(), "Packaged OpenShell policy differs from reviewed deployment policy"
    assert blob_service_pb2.UserMessage(text="synthetic").text == "synthetic"
    assert blob_service_pb2_grpc.BlobServiceStub
    from blob.skills.registry import SkillRegistry
    bundled = Path(blob.__file__).resolve().parent / "data/skills"
    with tempfile.TemporaryDirectory(prefix="blob-bundled-skills-") as directory:
        registry = SkillRegistry(directory)
        assert registry.load_directory(bundled) == []
        assert len(registry.skills) == 12, "Bundled skill definitions missing from installed package"
    for path in bundled.glob("*.skill.yaml"):
        assert path.read_bytes() == (source / "skills" / path.name).read_bytes(), "Bundled skill differs from reviewed definition"
    with tempfile.TemporaryDirectory(prefix="blob-release-smoke-") as directory:
        controls = PrivacyControls(Path(directory) / "private/privacy.json")
        assert not controls.cloud_enabled and not controls.state["awareness_enabled"]
        try:
            controls.check(cloud=True)
        except PrivacyBlocked:
            pass
        else:
            raise AssertionError("Fresh installation allowed cloud requests without opt-in")
        controls.update(cloud_enabled=True)
        assert PrivacyControls(controls.path).cloud_enabled
    with tempfile.TemporaryDirectory(prefix="blob-release-daemon-") as directory:
        asyncio.run(check_daemon(Path(directory)))
    print(json.dumps({"version": blob.__version__, "wheel_import": True, "resources": True,
                      "ipc_import": True, "cloud_opt_in": True, "daemon_without_key": True,
                      "local_reminders": True, "durable_reminder_ack": True,
                      "missing_key_message": True, "openshell_policy": True,
                      "skill_management": True, "project_selection": True}))


if __name__ == "__main__":
    main()
