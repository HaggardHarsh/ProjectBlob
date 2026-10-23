import asyncio
import logging
import grpc
from grpc import aio
from blob.ipc import blob_service_pb2_grpc
from blob.ipc.event_dispatcher import EventDispatcher
from blob.ipc.servicer import BlobServiceServicer
from blob.ipc.auth import ipc_token
import ipaddress

logger = logging.getLogger(__name__)

async def start_grpc_server(config, orchestrator, dispatcher):
    address = config.ipc_address
    if not address.startswith("unix:"):
        host = address.rsplit(":", 1)[0].strip("[]")
        if host != "localhost" and not ipaddress.ip_address(host).is_loopback:
            raise ValueError("Blob IPC must use a loopback address or a private Unix socket.")
    # gRPC enables SO_REUSEPORT by default, allowing separate backends with
    # independent privacy/conversation state to accept the same connections.
    server = aio.server(options=(("grpc.so_reuseport", 0),))
    servicer = BlobServiceServicer(dispatcher, orchestrator, token=ipc_token(config.ipc_token_path, create=True))
    blob_service_pb2_grpc.add_BlobServiceServicer_to_server(servicer, server)
    try:
        if not server.add_insecure_port(config.ipc_address):
            raise RuntimeError("Blob IPC address is already in use or unavailable.")
        logger.info(f"Starting gRPC server on {config.ipc_address}")
        await server.start()
    except BaseException:
        await server.stop(0)
        raise
    return server, servicer
