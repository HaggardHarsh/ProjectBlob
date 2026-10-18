"""Desktop controls share authenticated, local privacy commands and typed state."""

import asyncio
from types import SimpleNamespace

import grpc
import pytest

from blob.ipc import blob_service_pb2 as pb, blob_service_pb2_grpc as rpc
from blob.ipc.auth import ipc_token
from blob.ipc.event_dispatcher import EventDispatcher
from blob.ipc.server import start_grpc_server
from blob.privacy.controls import PrivacyControls
from blob.privacy.shield import PrivacyShield
from test_private_service import orchestrator


@pytest.mark.asyncio
async def test_desktop_controls_report_actual_settings_and_require_explicit_cloud_choice(tmp_path):
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    instance = orchestrator(controls)
    dispatcher = EventDispatcher()
    shield = PrivacyShield.__new__(PrivacyShield)
    shield.controls = controls
    shield.event_dispatcher = dispatcher
    shield.is_active = True
    shield.is_capture_blocked = lambda: True  # Automatic shielding is separate from manual pause.
    instance.screen_sampler = SimpleNamespace(privacy_shield=shield)
    config = SimpleNamespace(ipc_address="unix:" + str(tmp_path / "ipc.sock"),
                             ipc_token_path=str(tmp_path / "private/token"))
    server, service = await start_grpc_server(config, instance, dispatcher)
    try:
        async with grpc.aio.insecure_channel(config.ipc_address) as channel:
            stub = rpc.BlobServiceStub(channel)
            metadata = (("x-blob-token", ipc_token(config.ipc_token_path)),)
            stream = stub.EventStream(metadata=metadata)
            await stream.write(pb.FrontendEvent(heartbeat=pb.HeartbeatPing()))
            first = await asyncio.wait_for(stream.read(), 2)
            assert first.privacy.activated and first.privacy.controls_available
            assert not first.privacy.manual_pause and not first.privacy.cloud_enabled
            with pytest.raises(grpc.aio.AioRpcError) as denied:
                await stub.UpdateConfig(pb.ConfigUpdate(settings={"cloud_enabled": "true"}))
            assert denied.value.code() == grpc.StatusCode.UNAUTHENTICATED
            ambiguous = await stub.UpdateConfig(pb.ConfigUpdate(settings={"cloud_enabled": "toggle"}), metadata=metadata)
            assert not ambiguous.success and not controls.cloud_enabled
            response = await stub.UpdateConfig(pb.ConfigUpdate(settings={"cloud_enabled": "true"}), metadata=metadata)
            assert response.success and controls.cloud_enabled
            response = await stub.UpdateConfig(pb.ConfigUpdate(settings={"privacy_paused": "true"}), metadata=metadata)
            assert response.success and controls.paused
            events = []
            while len(events) < 3:
                item = await asyncio.wait_for(stream.read(), 2)
                if item.HasField("privacy"):
                    events.append(item.privacy)
                    if item.privacy.manual_pause:
                        break
            assert any(event.cloud_enabled and not event.manual_pause for event in events)
            assert events[-1].manual_pause
            stream.cancel()
    finally:
        await service.close_streams()
        await server.stop(0)


@pytest.mark.asyncio
async def test_stop_cancels_pending_work_without_changing_privacy_settings(tmp_path):
    controls = PrivacyControls(tmp_path / "private/privacy.json")
    controls.update(cloud_enabled=True)
    instance = orchestrator(controls)
    started = asyncio.Event()
    async def work(message):
        started.set()
        await asyncio.Event().wait()
    instance._handle_user_message = work
    active = asyncio.create_task(instance.handle_user_message(pb.UserMessage(text="Synthetic slow request")))
    await asyncio.wait_for(started.wait(), 2)
    response = await instance.handle_user_message(pb.UserMessage(text="/stop"))
    assert "Stop requested" in response and "not undone" in response
    with pytest.raises(asyncio.CancelledError):
        await active
    assert controls.cloud_enabled and not controls.paused
