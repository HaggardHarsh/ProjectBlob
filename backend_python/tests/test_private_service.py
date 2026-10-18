import asyncio
from collections import deque
import os
from pathlib import Path
import shlex
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock

import grpc
import pytest

from blob.ai.llm_engine import NebiusEngine
from blob.ai.orchestrator import BlobOrchestrator
from blob.ipc.auth import ipc_token
from blob.ipc.event_dispatcher import EventDispatcher
from blob.ipc.servicer import BlobServiceServicer
from blob.ipc import blob_service_pb2 as pb, blob_service_pb2_grpc as rpc
from blob.memory.semantic import SemanticMemory
from blob.memory.vector_store import VectorStore
from blob.privacy.controls import PrivacyControls, PrivacyBlocked
from blob.privacy.sandbox import sandbox_command
from blob.skills.builtin.file_search import FileSearchSkill
from blob.skills.process import run_command
from blob.skills.registry import SkillRegistry


class FixedEmbedding:
    def __call__(self, input):
        return [[1.0, float(len(text) % 3), 0.5] for text in input]

    def embed_query(self, input):
        return self(input)

    def name(self):
        return "privacy-test"

    def is_legacy(self):
        return False

    def default_space(self):
        return "l2"

    def supported_spaces(self):
        return ["l2"]


def store_at(path, controls=None):
    return VectorStore(str(path), embedding_function=FixedEmbedding(), controls=controls)


def orchestrator(controls):
    instance = BlobOrchestrator.__new__(BlobOrchestrator)
    instance.controls = controls
    instance._recent_turns = deque()
    instance._send_direct_response = AsyncMock(side_effect=lambda text, emote: text)
    instance._clear_thinking = lambda: None
    instance.screen_sampler = SimpleNamespace(privacy_shield=SimpleNamespace(
        is_active=False, is_capture_blocked=lambda: controls.paused, _broadcast_state=AsyncMock()))
    return instance


def test_privacy_settings_persist_and_are_private(tmp_path):
    settings = tmp_path / "private/privacy.json"
    controls = PrivacyControls(settings)
    assert controls.folders == ()
    folder = tmp_path / "project"
    folder.mkdir()
    controls.approve(folder)
    controls.update(paused=True, cloud_enabled=False, disabled_skills=["weather"])
    restarted = PrivacyControls(settings)
    assert restarted.paused and not restarted.cloud_enabled
    assert restarted.folders == (folder,)
    assert settings.stat().st_mode & 0o777 == 0o600
    assert settings.parent.stat().st_mode & 0o777 == 0o700
    with pytest.raises(PrivacyBlocked):
        restarted.write(lambda: pytest.fail("paused write ran"))
    settings.write_text('{"paused": "false"}')
    with pytest.raises(ValueError, match="Invalid privacy"):
        PrivacyControls(settings)


def test_folder_approval_resolves_paths_and_does_not_allow_symlink_escape(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    other = tmp_path / "other"
    other.mkdir()
    (allowed / "escape").symlink_to(other, target_is_directory=True)
    controls.approve(allowed)
    assert controls.allows(allowed / "normal.txt")
    assert not controls.allows(allowed / "escape/secret")
    for forbidden in ("/", str(Path.home()), "/tmp"):
        with pytest.raises(ValueError):
            controls.approve(forbidden)


def test_search_stays_in_approved_folders(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    allowed, other = tmp_path / "allowed", tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    (allowed / "lesson.txt").write_text("public")
    (other / "lesson-secret.txt").write_text("private")
    (allowed / "lesson-link.txt").symlink_to(other / "lesson-secret.txt")
    controls.approve(allowed)
    skill = FileSearchSkill()
    skill.controls = controls
    result = skill.execute({"query": "lesson"})
    assert result.success
    assert result.output == str(allowed / "lesson.txt")


def test_missing_sandbox_never_falls_back_to_host_commands(tmp_path, monkeypatch):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.approve(tmp_path)
    monkeypatch.setattr(shutil, "which", lambda name: None)
    with pytest.raises(PrivacyBlocked, match="unavailable"):
        run_command(["cat", "/etc/passwd"], controls=controls)


def test_command_namespace_blocks_unapproved_files_and_masks_secrets(tmp_path):
    if not shutil.which("bwrap"):
        pytest.skip("Bubblewrap not installed")
    controls = PrivacyControls(tmp_path / "privacy.json")
    allowed, other = tmp_path / "allowed", tmp_path / "other"
    allowed.mkdir()
    other.mkdir()
    (allowed / "read.txt").write_text("approved content")
    (allowed / ".env").write_text("SECRET_VALUE")
    (other / "secret.txt").write_text("unapproved content")
    (allowed / "escape.txt").symlink_to(other / "secret.txt")
    controls.approve(allowed)
    probe = run_command(["cat", str(allowed / "read.txt")], controls=controls)
    if probe.returncode and ("Operation not permitted" in probe.stdout or "Creating new namespace failed" in probe.stdout):
        pytest.skip("Host disallows unprivileged namespaces; tools fail closed")
    assert probe.returncode == 0 and probe.stdout == "approved content"
    assert run_command(["cat", str(other / "secret.txt")], controls=controls).returncode != 0
    assert run_command(["cat", str(allowed / "escape.txt")], controls=controls).returncode != 0
    assert run_command(["cat", str(allowed / ".env")], controls=controls).stdout == ""
    write = run_command(["/usr/bin/python3", "-c", "from pathlib import Path; Path('read.txt').write_text('changed')"], controls=controls)
    assert write.returncode != 0 and (allowed / "read.txt").read_text() == "approved content"
    import socket
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        port = listener.getsockname()[1]
        network = run_command(["/usr/bin/python3", "-c", f"import socket; s=socket.socket(); s.settimeout(0.2); s.connect(('127.0.0.1', {port}))"], controls=controls)
        assert network.returncode != 0
    wrapped = sandbox_command(["echo", "test"], controls)
    assert "--unshare-all" in wrapped and "--share-net" not in wrapped and "--clearenv" in wrapped


@pytest.mark.asyncio
async def test_pause_cancels_active_and_queued_chat_without_waiting_for_conversation(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=True)
    instance = orchestrator(controls)
    started = asyncio.Event()

    async def slow(message):
        started.set()
        await asyncio.Event().wait()

    instance._handle_user_message = slow
    active = asyncio.create_task(instance.handle_user_message(pb.UserMessage(text="hello")))
    await started.wait()
    reply = await asyncio.wait_for(instance.handle_user_message(pb.UserMessage(text="/privacy pause")), 1)
    assert "paused" in reply
    assert "stopped" in await asyncio.wait_for(active, 1)
    assert controls.paused and not controls.tasks
    assert "pause" in await instance.handle_user_message(pb.UserMessage(text="hello again"))


@pytest.mark.asyncio
async def test_cloud_off_blocks_model_requests_but_local_reminders_can_run(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=False)
    instance = orchestrator(controls)
    instance._handle_user_message = AsyncMock(return_value="local result")
    assert "Cloud assistance is off" in await instance.handle_user_message(pb.UserMessage(text="hello"))
    instance._handle_user_message.assert_not_called()
    assert await instance.handle_user_message(pb.UserMessage(text="/reminders")) == "local result"
    engine = NebiusEngine.__new__(NebiusEngine)
    engine.controls = controls
    create = AsyncMock()
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    with pytest.raises(PrivacyBlocked):
        await engine._create(model="test", messages=[])
    create.assert_not_called()


@pytest.mark.asyncio
async def test_disabled_skills_and_pause_are_enforced_at_execution(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    registry = SkillRegistry(controls=controls)
    run = AsyncMock()
    registry.register(SimpleNamespace(name="weather", description="test", async_execute=run))
    controls.update(disabled_skills=["weather"])
    assert not (await registry.execute("weather", {})).success
    assert "weather" not in registry.prompt_text()
    controls.update(disabled_skills=[], paused=True)
    assert not (await registry.execute("weather", {})).success
    run.assert_not_called()


def test_forgetting_a_fact_removes_repeated_sources_and_survives_restart(tmp_path):
    store = store_at(tmp_path / "db")
    quote = "My subjects are HDL and Physics."
    first = store.store("User: " + quote, {})
    second = store.store("User: " + quote + "\nBlob: Okay.", {})
    memory = SemanticMemory(store, SimpleNamespace(controls=None))
    memory.remember_explicit_statements(quote, second)
    fact_id = store.middle.get(include=[])["ids"][0]
    unrelated = store.store("User: I like cats.", {})
    assert store.forget_personal_memory("middle", fact_id) == 3
    assert store.episodic.get(ids=[first, second], include=[])["ids"] == []
    reopened = store_at(tmp_path / "db")
    SemanticMemory(reopened, SimpleNamespace(controls=None)).backfill_explicit_statements()
    assert reopened.middle.count() == 0
    assert reopened.episodic.get(include=[])["ids"] == [unrelated]
    assert reopened.episodic_user.count() == 1


def test_pause_blocks_memory_writes_and_all_deletion_clears_search_index(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    store = store_at(tmp_path / "db", controls)
    store.store("User: Private fact", {})
    controls.update(paused=True)
    with pytest.raises(PrivacyBlocked):
        store.store("User: Should not be saved", {})
    assert store.forget_personal_memory() == 1
    assert store.episodic_user.count() == 0


def test_queued_thread_writes_are_discarded_after_privacy_changes(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    store = store_at(tmp_path / "db", controls)
    queued = controls.deferred_write(store.store)
    with controls.lock:
        controls.generation += 1
        store.forget_personal_memory()
    with pytest.raises(PrivacyBlocked, match="Storage cancelled"):
        queued("User: Stale queued statement.", {})
    assert store.episodic.count() == 0


@pytest.mark.asyncio
async def test_inflight_consolidation_cannot_restore_deleted_memories(tmp_path):
    store = store_at(tmp_path / "db")
    store.store("User: I prefer Python.", {"consolidated": False})
    started, finish = asyncio.Event(), asyncio.Event()

    async def generate(*args):
        started.set()
        await finish.wait()
        return SimpleNamespace(content="L1")

    memory = SemanticMemory(store, SimpleNamespace(generate=generate, controls=None))
    pending = asyncio.create_task(memory.consolidate_once())
    await started.wait()
    store.forget_personal_memory()
    finish.set()
    assert await pending == 0
    assert store.semantic.count() == store.episodic.count() == 0


@pytest.mark.asyncio
async def test_cancelled_cloud_consolidation_leaves_worker_available(tmp_path):
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=True)
    store = store_at(tmp_path / "db", controls)
    store.store("User: I prefer Python.", {"consolidated": False})
    started = asyncio.Event()

    async def create(**kwargs):
        started.set()
        await asyncio.Event().wait()

    engine = NebiusEngine.__new__(NebiusEngine)
    engine.controls = controls
    engine.model_name = "test"
    engine.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    memory = SemanticMemory(store, engine)
    work = asyncio.create_task(memory.consolidate_once())
    await started.wait()
    controls.update(paused=True)
    controls.cancel_requests()
    assert await asyncio.wait_for(work, 1) == 0
    assert not work.cancelled()
    controls.update(paused=False)
    engine.client.chat.completions.create = AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="L1"))]))
    assert await memory.consolidate_once() == 1


def test_ipc_token_is_private_and_refuses_insecure_files(tmp_path):
    path = tmp_path / "private/token"
    token = ipc_token(path, create=True)
    assert ipc_token(path) == token
    assert path.stat().st_mode & 0o777 == 0o600
    path.chmod(0o644)
    with pytest.raises(ValueError, match="private"):
        ipc_token(path)


@pytest.mark.asyncio
async def test_all_rpc_access_requires_a_valid_token_and_clients_can_reconnect():
    calls = []

    async def respond(message):
        calls.append(message.text)
        return "Reply: " + message.text

    servicer = BlobServiceServicer(EventDispatcher(), SimpleNamespace(handle_user_message=respond, screen_sampler=None), token="secret")
    server = grpc.aio.server()
    rpc.add_BlobServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    try:
        for _ in range(2):
            async with grpc.aio.insecure_channel(f"127.0.0.1:{port}") as channel:
                stub = rpc.BlobServiceStub(channel)
                with pytest.raises(grpc.aio.AioRpcError) as error:
                    await stub.SendUserMessage(pb.UserMessage(text="unauthorized"))
                assert error.value.code() == grpc.StatusCode.UNAUTHENTICATED
                for call in (stub.GetBlobState(pb.Empty()), stub.RegisterSkill(pb.SkillRegistration()),
                             stub.UpdateConfig(pb.ConfigUpdate())):
                    with pytest.raises(grpc.aio.AioRpcError) as denied:
                        await call
                    assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
                async def events():
                    yield pb.FrontendEvent(heartbeat=pb.HeartbeatPing())
                with pytest.raises(grpc.aio.AioRpcError) as denied:
                    await stub.EventStream(events()).read()
                assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
                reply = await stub.SendUserMessage(pb.UserMessage(text="hello"), metadata=(("x-blob-token", "secret"),))
                assert reply.text == "Reply: hello"
        assert calls == ["hello", "hello"]
    finally:
        await server.stop(grace=0)


def test_startup_files_quote_paths_and_preserve_backend_without_a_terminal(tmp_path):
    import importlib.util
    script = Path(__file__).resolve().parents[2] / "tools/install_desktop.py"
    spec = importlib.util.spec_from_file_location("blob_install", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    files = module.render(tmp_path / "Project with % space", tmp_path / "venv/bin/python")
    backend = files["systemd/user/blob-backend.service"]
    assert "--daemon" in backend and "Restart=on-failure" in backend and "StandardInput=null" in backend
    assert "StandardOutput=null" in backend and "%% space" in backend
    assert "Terminal=true" in files["applications/blob-chat.desktop"]
    assert "--startup" in files["autostart/blob.desktop"]


@pytest.mark.asyncio
async def test_daemon_survives_closed_stdin_and_reconnects_after_process_restart(tmp_path):
    import subprocess
    import sys
    env = {**os.environ,
           "NEBIUS_API_KEY": "synthetic-test-key", "BLOB_MODEL_NAME": "synthetic-test-model",
           "BLOB_IPC_ADDRESS": "unix:" + str(tmp_path / "blob.sock"),
           "BLOB_IPC_TOKEN_PATH": str(tmp_path / "token"),
           "BLOB_PRIVACY_SETTINGS_PATH": str(tmp_path / "privacy.json"),
           "BLOB_MEMORY_DB_PATH": str(tmp_path / "memory"),
           "BLOB_REMINDERS_DB_PATH": str(tmp_path / "reminders.sqlite3"),
           "BLOB_DOCUMENTS_DIR_PATH": str(tmp_path / "documents"),
           "BLOB_SKILLS_DIR_PATH": str(tmp_path / "skills"),
           "BLOB_CAMERA_ENABLED": "0", "ANONYMIZED_TELEMETRY": "False"}
    # Test with a persistent local-only setting: no provider requests or personal data.
    controls = PrivacyControls(tmp_path / "privacy.json")
    controls.update(cloud_enabled=False)
    process = None
    logs = tmp_path / "daemon.log"
    with logs.open("w") as log:
        try:
            async with grpc.aio.insecure_channel(env["BLOB_IPC_ADDRESS"]) as channel:
                stub = rpc.BlobServiceStub(channel)
                for attempt in range(2):
                    process = subprocess.Popen([sys.executable, "-m", "blob.main", "--daemon"],
                                               cwd=tmp_path, env=env, stdin=subprocess.DEVNULL,
                                               stdout=subprocess.DEVNULL, stderr=log)
                    for _ in range(150):
                        if (tmp_path / "token").exists():
                            break
                        if process.poll() is not None:
                            pytest.fail("Daemon exited: " + logs.read_text())
                        await asyncio.sleep(0.1)
                    metadata = (("x-blob-token", ipc_token(tmp_path / "token")),)
                    state = await stub.GetBlobState(pb.Empty(), metadata=metadata, timeout=15, wait_for_ready=True)
                    assert state.memories_stored == 0 and process.poll() is None
                    response = await stub.SendUserMessage(pb.UserMessage(text="/privacy status"), metadata=metadata, timeout=3)
                    assert '"cloud_enabled": false' in response.text
                    if attempt == 0:
                        paused = await stub.SendUserMessage(pb.UserMessage(text="/privacy pause"), metadata=metadata, timeout=3)
                        assert "paused" in paused.text
                    else:
                        assert state.privacy_shield_active
                    process.terminate()
                    await asyncio.to_thread(process.wait, 10)
                    process = None
        finally:
            if process is not None:
                process.terminate()
                await asyncio.to_thread(process.wait, 10)
