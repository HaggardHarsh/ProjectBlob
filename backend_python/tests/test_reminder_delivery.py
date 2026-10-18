"""Durable reminder handoff: crashes, disconnection, acknowledgement and rollback."""

import asyncio
import sqlite3
from types import SimpleNamespace
from unittest.mock import AsyncMock

import grpc
import pytest

from blob.ipc import blob_service_pb2 as pb, blob_service_pb2_grpc as rpc
from blob.ipc.auth import ipc_token
from blob.ipc.event_dispatcher import EventDispatcher
from blob.ipc.server import start_grpc_server
from blob.privacy.controls import PrivacyControls
from blob.skills.builtin.reminder import ReminderSkill
from blob.skills.registry import SkillRegistry
from blob.skills.reminder_store import ReminderStore
from test_private_service import orchestrator


def test_old_database_migrates_and_committed_delivery_survives_crash_gap(tmp_path):
    path = tmp_path / "old.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE reminders (id TEXT PRIMARY KEY, message TEXT NOT NULL, due_at REAL NOT NULL, repeat_minutes REAL, created_at REAL NOT NULL)")
        db.execute("INSERT INTO reminders VALUES ('legacy', 'Persist me', 10, NULL, 0)")
    store = ReminderStore(path)
    due = store.take_due(20)[0]
    assert store.pending() == []
    store.close()  # Simulate exit after commit and before any event is published.
    reopened = ReminderStore(path)
    try:
        assert reopened.pending_deliveries()[0]["delivery_id"] == due["delivery_id"]
        assert reopened.acknowledge(due["delivery_id"])
        assert not reopened.acknowledge(due["delivery_id"])
        assert reopened.pending_deliveries() == []
    finally:
        reopened.close()


def test_unread_repeats_coalesce_and_old_ack_cannot_remove_new_occurrence(tmp_path):
    store = ReminderStore(tmp_path / "reminders.sqlite3")
    try:
        identifier = store.add("Stretch", 10, 1, 0)
        first = store.take_due(10)[0]
        second = store.take_due(190)[0]
        pending = store.pending_deliveries()
        assert len(pending) == 1 and pending[0]["id"] == identifier
        assert pending[0]["occurrences"] == 4
        assert not store.acknowledge(first["delivery_id"])
        assert store.pending_deliveries()
        assert store.acknowledge(second["delivery_id"])
        assert store.pending()[0]["due_at"] == 250
    finally:
        store.close()


@pytest.mark.parametrize("action", ["cancel", "snooze"])
def test_delivered_one_shot_can_be_cancelled_or_snoozed_without_stale_replay(tmp_path, action):
    store = ReminderStore(tmp_path / "reminders.sqlite3")
    try:
        identifier = store.add("A task", 10, None, 0)
        stale = store.take_due(10)[0]
        assert (store.cancel(identifier) if action == "cancel" else store.snooze(identifier, 200))
        assert not store.acknowledge(stale["delivery_id"])
        assert store.pending_deliveries() == []
        assert bool(store.pending()) == (action == "snooze")
    finally:
        store.close()


def test_sqlite_disk_full_rolls_back_delivery_and_keeps_schedule(tmp_path):
    store = ReminderStore(tmp_path / "full.sqlite3")
    try:
        store.db.execute("PRAGMA page_size=512")
        store.db.execute("VACUUM")
        identifier = store.add("x" * 1000, 10, None, 0)
        pages = store.db.execute("PRAGMA page_count").fetchone()[0]
        store.db.execute(f"PRAGMA max_page_count={pages}")
        with pytest.raises(sqlite3.OperationalError, match="full"):
            store.take_due(20)
        assert store.pending()[0]["id"] == identifier
        assert store.pending_deliveries() == []
        store.db.execute("PRAGMA max_page_count=10000")
        assert store.take_due(20)[0]["id"] == identifier
    finally:
        store.close()


@pytest.mark.asyncio
async def test_pending_delivery_replays_after_disconnect_until_authenticated_ack(tmp_path):
    path = tmp_path / "reminders.sqlite3"
    initial = ReminderStore(path)
    identifier = initial.add("Reconnect reminder", 10, None, 0)
    delivery_id = initial.take_due(20)[0]["delivery_id"]
    initial.close()
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    instance = orchestrator(controls)
    dispatcher = EventDispatcher()
    instance.skill_registry = SkillRegistry(tmp_path / "skills", controls=controls)
    reminder = ReminderSkill(path)
    instance.skill_registry.register(reminder)
    config = SimpleNamespace(ipc_address="unix:" + str(tmp_path / "ipc.sock"), ipc_token_path=str(tmp_path / "private/token"))
    server, service = await start_grpc_server(config, instance, dispatcher)
    try:
        async with grpc.aio.insecure_channel(config.ipc_address) as channel:
            stub = rpc.BlobServiceStub(channel)
            metadata = (("x-blob-token", ipc_token(config.ipc_token_path)),)
            for attempt in range(2):
                stream = stub.EventStream(metadata=metadata)
                await stream.write(pb.FrontendEvent(heartbeat=pb.HeartbeatPing()))
                while True:
                    event = await asyncio.wait_for(stream.read(), 2)
                    if event.HasField("notification"):
                        break
                assert event.notification.delivery_id == delivery_id and identifier in event.notification.text
                stream.cancel()  # A disconnected client has not acknowledged display.
            with pytest.raises(grpc.aio.AioRpcError) as denied:
                await stub.AcknowledgeNotification(pb.NotificationAck(delivery_id=delivery_id))
            assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
            assert reminder.store.pending_deliveries()
            ack = await stub.AcknowledgeNotification(pb.NotificationAck(delivery_id=delivery_id), metadata=metadata)
            assert ack.acknowledged and reminder.store.pending_deliveries() == []
    finally:
        await service.close_streams()
        await server.stop(0)
        await reminder.close()


@pytest.mark.asyncio
async def test_slow_client_does_not_block_broadcast_or_shutdown():
    from blob.ipc.servicer import BlobServiceServicer
    dispatcher = EventDispatcher()
    queue = asyncio.Queue(maxsize=1)
    dispatcher.register_client("slow", queue)
    queue.put_nowait(pb.BackendEvent())
    event = pb.BackendEvent(notification=pb.NotificationBubble(text="Latest event"))
    await asyncio.wait_for(dispatcher.broadcast(event), 0.2)
    assert queue.qsize() == 1 and queue.get_nowait().notification.text == "Latest event"
    queue.put_nowait(event)
    BlobServiceServicer._finish_queue(queue)
    assert queue.get_nowait() is None


@pytest.mark.asyncio
async def test_maintenance_blocks_rpc_writes_but_keeps_health_available(tmp_path, monkeypatch):
    marker = tmp_path / "maintenance"
    monkeypatch.setenv("BLOB_MAINTENANCE_PATH", str(marker))
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    instance = orchestrator(controls)
    instance.handle_user_message = AsyncMock()
    collection = SimpleNamespace(count=lambda: 0)
    instance.vector_store = SimpleNamespace(episodic=collection, semantic=collection, middle=collection)
    instance.skill_registry = SkillRegistry(tmp_path / "skills", controls=controls)
    reminder = ReminderSkill(tmp_path / "reminders.sqlite3")
    instance.skill_registry.register(reminder)
    reminder.store.add("Keep me", 10, None, 0)
    delivery = reminder.store.take_due(20)[0]["delivery_id"]
    config = SimpleNamespace(ipc_address="unix:" + str(tmp_path / "ipc.sock"), ipc_token_path=str(tmp_path / "private/token"))
    server, service = await start_grpc_server(config, instance, EventDispatcher())
    try:
        async with grpc.aio.insecure_channel(config.ipc_address) as channel:
            stub = rpc.BlobServiceStub(channel)
            metadata = (("x-blob-token", ipc_token(config.ipc_token_path)),)
            marker.touch()
            assert "updating" in (await stub.SendUserMessage(pb.UserMessage(text="/reminders clear"), metadata=metadata)).text
            assert not (await stub.UpdateConfig(pb.ConfigUpdate(settings={"cloud_enabled": "true"}), metadata=metadata)).success
            assert not (await stub.AcknowledgeNotification(pb.NotificationAck(delivery_id=delivery), metadata=metadata)).acknowledged
            assert reminder.store.pending_deliveries()
            assert (await stub.GetBlobState(pb.Empty(), metadata=metadata)).memories_stored == 0
            instance.handle_user_message.assert_not_awaited()
            marker.unlink()
            assert (await stub.AcknowledgeNotification(pb.NotificationAck(delivery_id=delivery), metadata=metadata)).acknowledged
    finally:
        await service.close_streams()
        await server.stop(0)
        await reminder.close()
