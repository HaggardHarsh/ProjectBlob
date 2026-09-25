import asyncio
import logging
import signal
from blob.config import BlobConfig
from blob.ipc.server import start_grpc_server
from blob.privacy.shield import PrivacyShield
from blob.screen.sampler import ScreenSampler
from blob.memory.vector_store import VectorStore
from blob.ai.orchestrator import BlobOrchestrator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main_async():
    config = BlobConfig.load()
    
    vector_store = VectorStore(config.memory_db_path)
    privacy_shield = PrivacyShield(config)
    orchestrator = BlobOrchestrator(config, vector_store)
    screen_sampler = ScreenSampler(config, privacy_shield, orchestrator)
    
    server, event_dispatcher = await start_grpc_server(config, orchestrator)
    
    # Start tasks
    tasks = [
        asyncio.create_task(privacy_shield.run()),
        asyncio.create_task(screen_sampler.run()),
        asyncio.create_task(vector_store.consolidation_loop())
    ]
    
    stop_event = asyncio.Event()
    
    def handle_sigint():
        logger.info("Received SIGINT, shutting down...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGINT, handle_sigint)
    loop.add_signal_handler(signal.SIGTERM, handle_sigint)
    
    await stop_event.wait()
    
    # Cancel tasks
    for task in tasks:
        task.cancel()
    
    await server.stop(grace=5)
    logger.info("Shutdown complete")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
