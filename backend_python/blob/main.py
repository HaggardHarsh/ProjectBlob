import asyncio
import logging
import signal
from blob.config import BlobConfig
from blob.ipc.server import start_grpc_server
from blob.privacy.shield import PrivacyShield
from blob.screen.sampler import ScreenSampler
from blob.screen.ocr import OCRProcessor
from blob.memory.vector_store import VectorStore
from blob.ai.orchestrator import BlobOrchestrator

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Suppress httpx HTTP request spam
logging.getLogger("httpx").setLevel(logging.WARNING)

async def main_async():
    config = BlobConfig.load()
    
    vector_store = VectorStore(config.memory_db_path)
    
    from blob.skills.registry import SkillRegistry
    from blob.skills.builtin.weather import WeatherSkill
    from blob.skills.builtin.file_search import FileSearchSkill
    from blob.skills.builtin.git_status import GitStatusSkill
    from blob.skills.builtin.shell_command import ShellCommandSkill
    from blob.skills.builtin.reminder import ReminderSkill
    from blob.skills.builtin.screen_capture import ScreenCaptureSkill
    
    from blob.ipc.event_dispatcher import EventDispatcher
    event_dispatcher = EventDispatcher()
    
    # ── Build skill registry ─────────────────────────────────────────
    skill_registry = SkillRegistry()
    skill_registry.register(WeatherSkill())
    skill_registry.register(FileSearchSkill())
    skill_registry.register(GitStatusSkill())
    skill_registry.register(ShellCommandSkill())
    
    # Reminder skill (needs dispatcher for async notifications)
    reminder_skill = ReminderSkill()
    reminder_skill.set_dispatcher(event_dispatcher)
    skill_registry.register(reminder_skill)
    
    # ── Screen capture setup ─────────────────────────────────────────
    privacy_shield = PrivacyShield(config)
    screen_sampler = ScreenSampler(config, privacy_shield)
    ocr_processor = OCRProcessor()
    
    screen_capture_skill = ScreenCaptureSkill()
    screen_capture_skill.set_sampler(screen_sampler)
    screen_capture_skill.set_ocr(ocr_processor)
    skill_registry.register(screen_capture_skill)
    
    # ── Orchestrator (with screen sampler) ───────────────────────────
    orchestrator = BlobOrchestrator(
        config, vector_store, skill_registry, event_dispatcher,
        screen_sampler=screen_sampler
    )
    
    server = await start_grpc_server(config, orchestrator, event_dispatcher)
    
    # Simple CLI debug input loop
    async def cli_input_loop():
        loop = asyncio.get_running_loop()
        print("\n\033[92m╔══════════════════════════════════════════════╗\033[0m")
        print("\033[92m║   🟦 Project Blob — Rimuru AI Companion 🟦   ║\033[0m")
        print("\033[92m╚══════════════════════════════════════════════╝\033[0m")
        print("\033[90mType a message to chat. Ctrl+C to quit.\033[0m\n")
        while True:
            try:
                line = await loop.run_in_executor(None, input, "Blob> ")
                if line.strip():
                    from blob.ipc.blob_service_pb2 import UserMessage
                    msg = UserMessage(text=line.strip())
                    await orchestrator.handle_user_message(msg)
            except EOFError:
                break
            except Exception as e:
                logger.error(f"CLI input error: {e}")
                await asyncio.sleep(1)

    # Start tasks
    tasks = [
        asyncio.create_task(privacy_shield.run()),
        asyncio.create_task(orchestrator.semantic.consolidation_loop()),
        asyncio.create_task(cli_input_loop())
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
