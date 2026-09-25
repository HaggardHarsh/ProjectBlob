import logging
from blob.ipc import blob_service_pb2_grpc, blob_service_pb2
import asyncio

logger = logging.getLogger(__name__)

class BlobServiceServicer(blob_service_pb2_grpc.BlobServiceServicer):
    def __init__(self, dispatcher, orchestrator):
        self.dispatcher = dispatcher
        self.orchestrator = orchestrator

    async def EventStream(self, request_iterator, context):
        client_id = id(context)
        queue = asyncio.Queue()
        self.dispatcher.register_client(client_id, queue)
        
        async def read_requests():
            async for req in request_iterator:
                await self.handle_frontend_event(req)
                
        read_task = asyncio.create_task(read_requests())
        
        try:
            while True:
                resp = await queue.get()
                yield resp
        except asyncio.CancelledError:
            pass
        finally:
            read_task.cancel()
            self.dispatcher.unregister_client(client_id)

    async def handle_frontend_event(self, event):
        if event.HasField('user_message'):
            asyncio.create_task(self.orchestrator.handle_user_message(event.user_message))
        elif event.HasField('heartbeat'):
            pass # handle heartbeat

    async def RegisterSkill(self, request, context):
        return blob_service_pb2.SkillRegistrationResponse(success=True)

    async def GetBlobState(self, request, context):
        return blob_service_pb2.BlobState()

    async def SendUserMessage(self, request, context):
        return blob_service_pb2.AssistantResponse()

    async def UpdateConfig(self, request, context):
        return blob_service_pb2.ConfigUpdateResponse(success=True)
