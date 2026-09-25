import asyncio
import logging
import grpc
from grpc import aio
from blob.ipc import blob_service_pb2_grpc
from blob.ipc.event_dispatcher import EventDispatcher
from blob.ipc.servicer import BlobServiceServicer

logger = logging.getLogger(__name__)

async def start_grpc_server(config, orchestrator):
    server = aio.server()
    dispatcher = EventDispatcher()
    servicer = BlobServiceServicer(dispatcher, orchestrator)
    blob_service_pb2_grpc.add_BlobServiceServicer_to_server(servicer, server)
    server.add_insecure_port(config.ipc_address)
    logger.info(f"Starting gRPC server on {config.ipc_address}")
    await server.start()
    return server, dispatcher
