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
    
    from blob.skills.registry import SkillRegistry
    from blob.skills.builtin.weather import WeatherSkill
    from blob.skills.builtin.file_search import FileSearchSkill
    from blob.skills.builtin.git_status import GitStatusSkill
    from blob.skills.builtin.shell_command import ShellCommandSkill
    from blob.skills.builtin.reminder import ReminderSkill
    
    # We need dispatcher before orchestrator and shield
    # But start_grpc_server takes orchestrator...
    # Let's import EventDispatcher manually or instantiate it here
    from blob.ipc.event_dispatcher import EventDispatcher
    event_dispatcher = EventDispatcher()
    
    skill_registry = SkillRegistry()
    skill_registry.register(WeatherSkill())
    skill_registry.register(FileSearchSkill())
    skill_registry.register(GitStatusSkill())
    skill_registry.register(ShellCommandSkill())
    
    reminder_skill = ReminderSkill()
    reminder_skill.set_dispatcher(event_dispatcher)
    skill_registry.register(reminder_skill)
    
    privacy_shield = PrivacyShield(config)
    orchestrator = BlobOrchestrator(config, vector_store, skill_registry, event_dispatcher)
    screen_sampler = ScreenSampler(config, privacy_shield, orchestrator)
    
    server = await start_grpc_server(config, orchestrator, event_dispatcher)
    
    # Start tasks
    tasks = [
        asyncio.create_task(privacy_shield.run()),
        asyncio.create_task(screen_sampler.run()),
        asyncio.create_task(orchestrator.semantic.consolidation_loop())
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
