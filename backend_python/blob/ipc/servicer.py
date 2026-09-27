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
        shield = self.orchestrator.screen_sampler.privacy_shield if getattr(self.orchestrator, "screen_sampler", None) else None
        if shield:
            initial = blob_service_pb2.BackendEvent()
            initial.privacy.activated = shield.is_active
            await queue.put(initial)
        
        async def read_requests():
            try:
                async for req in request_iterator:
                    await self.handle_frontend_event(req)
            except Exception:
                logger.exception("Frontend event stream ended with an error")
            finally:
                await queue.put(None)
                
        read_task = asyncio.create_task(read_requests())
        
        try:
            while True:
                resp = await queue.get()
                if resp is None:
                    break
                yield resp
        except asyncio.CancelledError:
            pass
        finally:
            read_task.cancel()
            await asyncio.gather(read_task, return_exceptions=True)
            self.dispatcher.unregister_client(client_id)

    async def handle_frontend_event(self, event):
        if event.HasField('user_message'):
            asyncio.create_task(self._process_user_message(event.user_message))
        elif event.HasField('skill_pill_drop'):
            request = event.skill_pill_drop
            response = blob_service_pb2.BackendEvent()
            try:
                skill_id = self.orchestrator.skill_registry.install_file(
                    request.file_path, expected_hash=request.file_hash or None,
                )
                response.skill_ack.skill_name = skill_id
                response.skill_ack.success = True
                response.skill_ack.description = f"Installed skill {skill_id}."
            except (OSError, ValueError) as exc:
                response.skill_ack.skill_name = request.skill_name or request.file_path
                response.skill_ack.success = False
                response.skill_ack.error_message = str(exc)
            await self.dispatcher.broadcast(response)
        elif event.HasField('heartbeat'):
            response = blob_service_pb2.BackendEvent()
            response.heartbeat.llm_loaded = True
            await self.dispatcher.broadcast(response)

    async def _process_user_message(self, message):
        try:
            await self.orchestrator.handle_user_message(message)
        except Exception:
            logger.exception("Could not process frontend message")
            response = blob_service_pb2.BackendEvent()
            response.notification.text = "Blob could not process that message. Check the backend logs."
            await self.dispatcher.broadcast(response)

    async def RegisterSkill(self, request, context):
        try:
            skill_id = self.orchestrator.skill_registry.install_file(request.module_path)
            return blob_service_pb2.SkillRegistrationResponse(success=True, skill_id=skill_id)
        except (OSError, ValueError) as exc:
            return blob_service_pb2.SkillRegistrationResponse(success=False, error=str(exc))

    async def GetBlobState(self, request, context):
        store = self.orchestrator.vector_store
        shield = self.orchestrator.screen_sampler.privacy_shield if self.orchestrator.screen_sampler else None
        return blob_service_pb2.BlobState(
            loaded_skills=sorted(self.orchestrator.skill_registry.skills),
            privacy_shield_active=bool(shield and shield.is_active),
            memories_stored=store.episodic.count() + store.semantic.count(),
        )

    async def SendUserMessage(self, request, context):
        text = await self.orchestrator.handle_user_message(request)
        return blob_service_pb2.AssistantResponse(text=text or "")

    async def UpdateConfig(self, request, context):
        return blob_service_pb2.ConfigUpdateResponse(success=False, error="Runtime configuration updates are not implemented.")
