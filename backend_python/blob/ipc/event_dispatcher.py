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
        for queue in self.clients.values():
            await queue.put(event)
