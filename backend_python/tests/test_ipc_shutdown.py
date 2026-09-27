import asyncio
import errno
import os
import socket
import sys
from types import SimpleNamespace

import grpc
import pytest

from blob.ipc import blob_service_pb2, blob_service_pb2_grpc
from blob.ipc.event_dispatcher import EventDispatcher
from blob.ipc.servicer import BlobServiceServicer
from blob.main import read_cli_line


@pytest.mark.asyncio
async def test_terminal_reader_cancels_without_waiting_for_input(monkeypatch):
    read_fd, write_fd = os.pipe()
    try:
        with os.fdopen(read_fd, "r") as terminal:
            monkeypatch.setattr(sys, "stdin", terminal)
            task = asyncio.create_task(read_cli_line())
            await asyncio.sleep(0)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
    finally:
        os.close(write_fd)


@pytest.mark.asyncio
async def test_event_stream_closes_before_server_shutdown():
    dispatcher = EventDispatcher()
    servicer = BlobServiceServicer(dispatcher, SimpleNamespace(screen_sampler=None))
    request_wait = asyncio.Event()

    async def requests():
        await request_wait.wait()
        yield None

    async def consume():
        async for _ in servicer.EventStream(requests(), object()):
            pass

    consumer = asyncio.create_task(consume())
    await asyncio.sleep(0)
    assert len(dispatcher.clients) == 1

    await servicer.close_streams()
    await asyncio.wait_for(consumer, timeout=1)

    assert dispatcher.clients == {}
    assert not servicer._stream_queues
    async for _ in servicer.EventStream(requests(), object()):
        pytest.fail("A stream opened while the server was stopping")


@pytest.mark.asyncio
async def test_grpc_event_stream_finishes_before_server_stop():
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            pytest.skip("Loopback sockets are blocked by the test sandbox")
        raise
    dispatcher = EventDispatcher()
    servicer = BlobServiceServicer(dispatcher, SimpleNamespace(screen_sampler=None))
    server = grpc.aio.server()
    blob_service_pb2_grpc.add_BlobServiceServicer_to_server(servicer, server)
    port = server.add_insecure_port("127.0.0.1:0")
    await server.start()
    channel = grpc.aio.insecure_channel(f"127.0.0.1:{port}")
    hold_requests = asyncio.Event()

    async def requests():
        event = blob_service_pb2.FrontendEvent()
        event.heartbeat.frontend_uptime_ms = 1
        yield event
        await hold_requests.wait()

    try:
        call = blob_service_pb2_grpc.BlobServiceStub(channel).EventStream(requests())
        event = await asyncio.wait_for(call.read(), timeout=2)
        assert event.HasField("heartbeat")

        await servicer.close_streams()
        assert await asyncio.wait_for(call.read(), timeout=2) is grpc.aio.EOF
        await server.stop(grace=1)
    finally:
        await channel.close()
        await server.stop(grace=0)
