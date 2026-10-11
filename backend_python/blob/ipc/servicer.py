import logging
from blob.ipc import blob_service_pb2_grpc, blob_service_pb2
import asyncio
import secrets
import grpc
from blob.privacy.controls import PrivacyBlocked

logger = logging.getLogger(__name__)

class BlobServiceServicer(blob_service_pb2_grpc.BlobServiceServicer):
    def __init__(self, dispatcher, orchestrator, *, token=None):
        self.dispatcher = dispatcher
        self.orchestrator = orchestrator
        self._stopping = False
        self._stream_queues = {}
        self._streams_closed = asyncio.Event()
        self._streams_closed.set()
        self.token = token
        self._work_tasks = set()

    async def _authorize(self, context):
        if self.token is not None:
            value = dict(context.invocation_metadata()).get("x-blob-token", "")
            if not secrets.compare_digest(value, self.token):
                await context.abort(grpc.StatusCode.UNAUTHENTICATED, "A valid local Blob IPC credential is required.")

    def _start_work(self, coroutine):
        task = asyncio.create_task(coroutine)
        self._work_tasks.add(task)
        task.add_done_callback(self._work_tasks.discard)

    async def close_streams(self):
        """Finish event streams before stopping the gRPC server."""
        self._stopping = True
        for task in tuple(self._work_tasks):
            task.cancel()
        await asyncio.gather(*self._work_tasks, return_exceptions=True)
        for queue in tuple(self._stream_queues.values()):
            queue.put_nowait(None)
        try:
            await asyncio.wait_for(self._streams_closed.wait(), timeout=4)
        except asyncio.TimeoutError:
            logger.warning("Timed out waiting for frontend event streams to close")

    async def EventStream(self, request_iterator, context):
        await self._authorize(context)
        if self._stopping:
            return
        client_id = id(context)
        queue = asyncio.Queue()
        self._stream_queues[client_id] = queue
        self._streams_closed.clear()
        self.dispatcher.register_client(client_id, queue)
        shield = self.orchestrator.screen_sampler.privacy_shield if getattr(self.orchestrator, "screen_sampler", None) else None
        if shield:
            initial = blob_service_pb2.BackendEvent()
            initial.privacy.activated = shield.is_capture_blocked()
            queue.put_nowait(initial)
        
        async def read_requests():
            try:
                async for req in request_iterator:
                    await self.handle_frontend_event(req)
            except Exception:
                logger.exception("Frontend event stream ended with an error")
            finally:
                queue.put_nowait(None)
                
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
            self._stream_queues.pop(client_id, None)
            if not self._stream_queues:
                self._streams_closed.set()

    async def handle_frontend_event(self, event):
        if event.HasField('user_message'):
            self._start_work(self._process_user_message(event.user_message))
        elif event.HasField('attachment_drop'):
            self._start_work(self._process_attachment_drop(list(event.attachment_drop.file_paths)))
        elif event.HasField('skill_pill_drop'):
            request = event.skill_pill_drop
            response = blob_service_pb2.BackendEvent()
            try:
                controls = getattr(self.orchestrator, "controls", None)
                if controls:
                    controls.check()
                skill_id = self.orchestrator.skill_registry.install_file(
                    request.file_path, expected_hash=request.file_hash or None,
                )
                response.skill_ack.skill_name = skill_id
                response.skill_ack.success = True
                response.skill_ack.description = f"Installed skill {skill_id}."
            except (OSError, ValueError, PrivacyBlocked) as exc:
                response.skill_ack.skill_name = request.skill_name or request.file_path
                response.skill_ack.success = False
                response.skill_ack.error_message = str(exc)
            outcome = response.skill_ack.description if response.skill_ack.success else (
                f"Skill install failed: {response.skill_ack.error_message}"
            )
            print(f"\nBlob: {outcome}\n")
            await self.dispatcher.broadcast(response)
        elif event.HasField('heartbeat'):
            response = blob_service_pb2.BackendEvent()
            response.heartbeat.llm_loaded = True
            shield = getattr(getattr(self.orchestrator, "screen_sampler", None), "privacy_shield", None)
            response.heartbeat.privacy_shield_active = bool(shield and shield.is_capture_blocked())
            await self.dispatcher.broadcast(response)

    async def _process_user_message(self, message):
        try:
            await self.orchestrator.handle_user_message(message)
        except Exception:
            logger.exception("Could not process frontend message")
            emote = blob_service_pb2.BackendEvent()
            emote.emote.emote = blob_service_pb2.EmoteCommand.ERROR
            emote.emote.intensity = 0.75
            await self.dispatcher.broadcast(emote)
            response = blob_service_pb2.BackendEvent()
            response.notification.text = "Blob could not process that message. Check the backend logs."
            await self.dispatcher.broadcast(response)

    async def _process_attachment_drop(self, paths):
        try:
            await self.orchestrator.handle_attachment_drop(paths)
        except Exception:
            logger.exception("Could not process dropped files")
            await self.orchestrator._send_direct_response(
                "I couldn't analyze the dropped files. Try again or check the backend logs.", "ERROR")
        finally:
            if getattr(self.orchestrator, "_cli_waiting_for_input", False):
                print("Blob> ", end="", flush=True)

    async def RegisterSkill(self, request, context):
        await self._authorize(context)
        try:
            controls = getattr(self.orchestrator, "controls", None)
            if controls:
                controls.check()
            skill_id = self.orchestrator.skill_registry.install_file(request.module_path)
            return blob_service_pb2.SkillRegistrationResponse(success=True, skill_id=skill_id)
        except (OSError, ValueError, PrivacyBlocked) as exc:
            return blob_service_pb2.SkillRegistrationResponse(success=False, error=str(exc))

    async def GetBlobState(self, request, context):
        await self._authorize(context)
        store = self.orchestrator.vector_store
        shield = self.orchestrator.screen_sampler.privacy_shield if self.orchestrator.screen_sampler else None
        return blob_service_pb2.BlobState(
            loaded_skills=sorted(self.orchestrator.skill_registry.skills),
            privacy_shield_active=bool(shield and shield.is_capture_blocked()),
            memories_stored=store.episodic.count() + store.semantic.count() + store.middle.count(),
        )

    async def SendUserMessage(self, request, context):
        await self._authorize(context)
        text = await self.orchestrator.handle_user_message(request)
        return blob_service_pb2.AssistantResponse(text=text or "")

    async def UpdateConfig(self, request, context):
        await self._authorize(context)
        controls = getattr(self.orchestrator, "controls", None)
        if controls and set(request.settings) == {"privacy_paused"}:
            value = request.settings["privacy_paused"]
            if value == "toggle":
                value = "false" if controls.paused else "true"
            if value in {"true", "false"}:
                command = "/privacy pause" if value == "true" else "/privacy resume"
                text = await self.orchestrator.handle_user_message(blob_service_pb2.UserMessage(text=command))
                return blob_service_pb2.ConfigUpdateResponse(success=True, effective_config={"privacy_paused": str(controls.paused).lower()})
        return blob_service_pb2.ConfigUpdateResponse(success=False, error="Only the local privacy_paused setting can be updated here.")
