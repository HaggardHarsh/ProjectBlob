import asyncio
import logging

logger = logging.getLogger(__name__)

class EventDispatcher:
    def __init__(self):
        self.clients = {}

    def register_client(self, client_id, queue: asyncio.Queue):
        self.clients[client_id] = queue

    def unregister_client(self, client_id):
        if client_id in self.clients:
            del self.clients[client_id]

    async def broadcast(self, event):
        for queue in tuple(self.clients.values()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(event)

    async def send_to(self, client_id, event):
        """Low-priority invitations never evict a queued reply or reminder."""
        queue = self.clients.get(client_id)
        if queue is None or queue.full():
            return False
        queue.put_nowait(event)
        return True
