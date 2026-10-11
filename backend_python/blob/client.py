"""Reconnectable terminal client for an independently running Blob backend."""

import argparse
import asyncio
import sys
from collections import deque
from contextlib import suppress
import grpc

from blob.config import BlobConfig
from blob.ipc.auth import ipc_token
from blob.ipc import blob_service_pb2 as pb, blob_service_pb2_grpc as rpc
from blob.main import read_cli_line


async def run_client(*, message=None, status=False):
    config = BlobConfig.load()
    try:
        token = ipc_token(config.ipc_token_path)
    except (OSError, ValueError):
        print("Blob is not ready. Start blob-backend --daemon or the blob-backend user service first.")
        return 1
    metadata = (("x-blob-token", token),)
    async with grpc.aio.insecure_channel(config.ipc_address) as channel:
        stub = rpc.BlobServiceStub(channel)
        if status:
            try:
                state = await stub.GetBlobState(pb.Empty(), metadata=metadata, timeout=3)
                print(f"Backend ready. Privacy shield: {'active' if state.privacy_shield_active else 'inactive'}. "
                      f"Personal memories: {state.memories_stored}.")
                return 0
            except grpc.aio.AioRpcError as exc:
                print(f"Backend unavailable: {exc.code().name}. Check the user service logs.")
                return 1
        if message is not None:
            try:
                response = await stub.SendUserMessage(pb.UserMessage(text=message), metadata=metadata, timeout=180)
                print(response.text)
                return 0
            except grpc.aio.AioRpcError as exc:
                print(f"Request failed: {exc.code().name}. It may have run; check state before retrying an action.")
                return 1

        waiting = deque(maxlen=30)
        reply_echoes = deque(maxlen=30)
        busy = False

        def consume_reply_echo(text):
            # The notification stream and unary response can arrive in either order.
            # Consume one echo per reply, including after the input prompt returns.
            try:
                reply_echoes.remove(text)
            except ValueError:
                return False
            return True

        async def heartbeats():
            while True:
                event = pb.FrontendEvent()
                event.heartbeat.frontend_uptime_ms = 0
                yield event
                await asyncio.sleep(5)

        async def notifications():
            delay = 1
            disconnected = False
            while True:
                try:
                    async for event in stub.EventStream(heartbeats(), metadata=metadata):
                        if disconnected:
                            print("\nBlob backend reconnected.")
                            disconnected = False
                        delay = 1
                        if event.HasField("notification"):
                            if consume_reply_echo(event.notification.text):
                                continue
                            if busy:
                                waiting.append(event.notification.text)
                            else:
                                print("\nBlob: " + event.notification.text + "\nBlob> ", end="", flush=True)
                except grpc.aio.AioRpcError as exc:
                    # Disconnected streams do not replay missed notifications.
                    reply_echoes.clear()
                    if not disconnected:
                        print(f"\nBlob backend disconnected ({exc.code().name}); reconnecting.\nBlob> ", end="", flush=True)
                    disconnected = True
                await asyncio.sleep(delay)
                delay = min(delay * 2, 5)

        watcher = asyncio.create_task(notifications())
        if sys.stdout.isatty():
            print("\033[22;0t\033]0;Blob Chat\007", end="", flush=True)
        print("Connected chat client. Closing this terminal leaves Blob running. /quit disconnects.\n"
              "Messages and selected context use Nebius. /privacy shows local controls; /memory manages stored facts.")
        try:
            while True:
                try:
                    line = await read_cli_line()
                except EOFError:
                    break
                if line.strip().lower() in {"/quit", "/exit"}:
                    break
                if not line.strip():
                    continue
                busy = True
                answer = None
                try:
                    response = await stub.SendUserMessage(pb.UserMessage(text=line), metadata=metadata, timeout=180)
                    answer = response.text
                    print("\nBlob: " + answer + "\n")
                except grpc.aio.AioRpcError as exc:
                    print(f"Backend request failed ({exc.code().name}). It may have run; check before retrying an action.")
                finally:
                    if answer is not None:
                        reply_echoes.append(answer)
                    busy = False
                    while waiting:
                        notification = waiting.popleft()
                        if not consume_reply_echo(notification):
                            print("\nBlob: " + notification)
        finally:
            if sys.stdout.isatty():
                print("\033[23;0t", end="", flush=True)
            watcher.cancel()
            with suppress(asyncio.CancelledError):
                await watcher
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--send", metavar="MESSAGE", help="Send one message or local command")
    parser.add_argument("--status", action="store_true", help="Check the running backend")
    args = parser.parse_args()
    try:
        raise SystemExit(asyncio.run(run_client(message=args.send, status=args.status)))
    except KeyboardInterrupt:
        print("\nChat disconnected. Blob continues running.")


if __name__ == "__main__":
    main()
