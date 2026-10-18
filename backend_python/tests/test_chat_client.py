"""The terminal must show each answer once regardless of stream/RPC ordering."""

import asyncio
from types import SimpleNamespace

import pytest

from blob import client
from blob.ipc import blob_service_pb2 as pb


@pytest.mark.asyncio
@pytest.mark.parametrize("echo_timing", ["before_response", "after_response", "during_next_request"])
@pytest.mark.parametrize("durable", [False, True])
async def test_chat_reply_echoes_are_consumed_once_and_reminders_still_display(
        monkeypatch, capsys, echo_timing, durable):
    events = asyncio.Queue()
    delivered = asyncio.Event()
    replies = 0
    lines = 0
    acknowledged = []
    output_parts = []

    def notification(text, delivery_id=""):
        event = pb.BackendEvent()
        event.notification.text = text
        event.notification.delivery_id = delivery_id
        return event

    class Channel:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class Stub:
        async def AcknowledgeNotification(self, request, metadata, timeout):
            output_parts.append(capsys.readouterr().out)
            number = request.delivery_id[-1]
            assert f"Reminder {number}: take a break." in "".join(output_parts)
            acknowledged.append(request.delivery_id)
            return pb.NotificationAckResponse(acknowledged=True)

        async def EventStream(self, requests, metadata):
            while True:
                event = await events.get()
                yield event
                delivered.set()

        async def SendUserMessage(self, request, metadata, timeout):
            nonlocal replies
            replies += 1
            if echo_timing == "before_response":
                delivered.clear()
                await events.put(notification("Hello again."))
                await delivered.wait()
            elif echo_timing == "during_next_request" and replies == 2:
                delivered.clear()
                await events.put(notification("Hello again."))
                await delivered.wait()
            # An unrelated reminder can arrive while the response is pending.
            delivered.clear()
            await events.put(notification(f"Reminder {replies}: take a break.", f"delivery-{replies}" if durable else ""))
            await delivered.wait()
            return pb.AssistantResponse(text="Hello again.")

    async def read_line():
        nonlocal lines
        # Returning here means the unary reply and its finally block have completed.
        if lines:
            if durable and lines == 1:
                delivered.clear()
                await events.put(notification("Reminder 1: take a break.", "delivery-1"))
                await delivered.wait()
            if echo_timing == "after_response" or (
                    echo_timing == "during_next_request" and lines == 2):
                delivered.clear()
                await events.put(notification("Hello again."))
                await delivered.wait()
        lines += 1
        if lines <= 2:
            return "Hi Blob"
        # Matching text after all echoes are consumed is a new notification.
        delivered.clear()
        await events.put(notification("Hello again."))
        await delivered.wait()
        return "/quit"

    monkeypatch.setattr(client.BlobConfig, "load", lambda: SimpleNamespace(
        ipc_token_path="unused", ipc_address="unused"))
    monkeypatch.setattr(client, "ipc_token", lambda path: "test-token")
    monkeypatch.setattr(client.grpc.aio, "insecure_channel", lambda address: Channel())
    monkeypatch.setattr(client.rpc, "BlobServiceStub", lambda channel: Stub())
    monkeypatch.setattr(client, "read_cli_line", read_line)

    assert await asyncio.wait_for(client.run_client(), timeout=3) == 0
    output = "".join(output_parts) + capsys.readouterr().out
    assert output.count("Blob: Hello again.") == 3  # Two RPC replies and one new notification.
    assert output.count("Reminder 1: take a break.") == 1
    assert output.count("Reminder 2: take a break.") == 1
    assert acknowledged == (["delivery-1", "delivery-1", "delivery-2"] if durable else [])
