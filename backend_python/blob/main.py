import asyncio
import argparse
import logging
import signal
import sys
import os
from pathlib import Path
from blob.config import BlobConfig
from blob.ipc.server import start_grpc_server
from blob.privacy.shield import PrivacyShield
from blob.screen.sampler import ScreenSampler
from blob.screen.ocr import OCRProcessor
from blob.screen.awareness import ScreenAwareness
from blob.memory.vector_store import VectorStore
from blob.ai.orchestrator import BlobOrchestrator
from blob.privacy.controls import PrivacyControls

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# Suppress httpx HTTP request spam
logging.getLogger("httpx").setLevel(logging.WARNING)


async def read_cli_line():
    """Wait for terminal input without keeping a thread blocked in input()."""
    loop = asyncio.get_running_loop()
    future = loop.create_future()
    fd = sys.stdin.fileno()
    print("Blob> ", end="", flush=True)

    def on_ready():
        loop.remove_reader(fd)
        try:
            line = sys.stdin.readline()
            if not line:
                future.set_exception(EOFError())
            else:
                future.set_result(line.rstrip("\r\n"))
        except Exception as exc:
            future.set_exception(exc)

    try:
        loop.add_reader(fd, on_ready)
    except PermissionError:
        # epoll cannot watch regular files; reading a file is non-blocking.
        line = sys.stdin.readline()
        if not line:
            raise EOFError
        return line.rstrip("\r\n")
    try:
        return await future
    finally:
        loop.remove_reader(fd)

async def main_async(*, daemon=False):
    config = BlobConfig.load()
    controls = PrivacyControls(config.privacy_settings_path)
    os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")
    
    vector_store = VectorStore(config.memory_db_path, controls=controls)
    
    from blob.skills.registry import SkillRegistry
    from blob.skills.builtin.weather import WeatherSkill
    from blob.skills.builtin.file_search import FileSearchSkill
    from blob.skills.builtin.git_status import GitStatusSkill
    from blob.skills.builtin.shell_command import ShellCommandSkill
    from blob.skills.builtin.reminder import ReminderSkill
    from blob.skills.builtin.screen_capture import ScreenCaptureSkill
    from blob.skills.builtin.camera import CameraSkill
    from blob.vision.camera import CameraVision
    
    from blob.ipc.event_dispatcher import EventDispatcher
    event_dispatcher = EventDispatcher()
    
    # ── Build skill registry ─────────────────────────────────────────
    skill_registry = SkillRegistry(config.skills_dir_path, controls=controls)
    skill_registry.register(WeatherSkill())
    skill_registry.register(FileSearchSkill())
    skill_registry.register(GitStatusSkill())
    skill_registry.register(ShellCommandSkill())
    
    # Reminder skill (needs dispatcher for async notifications)
    reminder_skill = ReminderSkill(config.reminders_db_path)
    reminder_skill.set_dispatcher(event_dispatcher)
    skill_registry.register(reminder_skill)
    
    # ── Screen capture setup ─────────────────────────────────────────
    privacy_shield = PrivacyShield(config, event_dispatcher, controls=controls)
    screen_sampler = ScreenSampler(config, privacy_shield)
    ocr_processor = OCRProcessor()
    
    screen_capture_skill = ScreenCaptureSkill()
    screen_capture_skill.set_sampler(screen_sampler)
    screen_capture_skill.set_ocr(ocr_processor)
    skill_registry.register(screen_capture_skill)

    camera_vision = CameraVision(config)
    camera_vision.controls = controls
    skill_registry.register(CameraSkill(camera_vision))

    bundled_skills = Path(__file__).resolve().parents[2] / "skills"
    skill_registry.load_directory(bundled_skills)
    skill_registry.load_directory(config.skills_dir_path)
    
    # ── Orchestrator (with screen sampler) ───────────────────────────
    orchestrator = BlobOrchestrator(
        config, vector_store, skill_registry, event_dispatcher,
        screen_sampler=screen_sampler, controls=controls
    )
    async def prepare_agent():
        if orchestrator.agent_runtime is not None:
            try:
                await orchestrator.agent_runtime.start()
            except Exception:
                logger.warning("Hermes preload failed; the next request will try initialization again.")
    awareness = ScreenAwareness(config, screen_sampler, ocr_processor, controls)
    orchestrator.awareness = awareness
    privacy_shield.awareness = awareness
    reminder_skill.prompt_waiting = lambda: getattr(orchestrator, "_cli_waiting_for_input", False)
    reminder_skill.start()
    
    server, servicer = await start_grpc_server(config, orchestrator, event_dispatcher)
    if sys.platform == "linux" and os.environ.get("XDG_RUNTIME_DIR"):
        from blob.screen.gnome_bridge import bridge_token
        try:
            bridge_token(create=True)
        except (OSError, ValueError):
            logger.warning("Screen bridge authentication unavailable; automatic capture remains blocked.")
    
    # Simple CLI debug input loop
    async def cli_input_loop():
        print("\n\033[92m╔══════════════════════════════════════════════╗\033[0m")
        print("\033[92m║   🟦 Project Blob — Rimuru AI Companion 🟦   ║\033[0m")
        print("\033[92m╚══════════════════════════════════════════════╝\033[0m")
        print("\033[90mType a message to chat. Ctrl+C to quit.\033[0m\n")
        print("\033[90mDrop PDFs or images onto Blob to analyze them here. /files lists them; /files clear detaches them.\033[0m\n")
        print("\033[90mSaved files survive restarts. /files saved lists copies; /files forget <id|all> deletes them.\033[0m\n")
        print("\033[90mCompleted file answers survive source deletion. /results lists them; /results show <id> reopens one.\033[0m\n")
        print("\033[90m/skills lists tools. /reminders lists reminders; /reminders help shows scheduling commands.\033[0m\n")
        while True:
            try:
                orchestrator._cli_waiting_for_input = True
                try:
                    line = await read_cli_line()
                finally:
                    orchestrator._cli_waiting_for_input = False
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
        asyncio.create_task(prepare_agent()),
        asyncio.create_task(privacy_shield.run()),
        asyncio.create_task(orchestrator.semantic.consolidation_loop()),
        asyncio.create_task(awareness.run()),
    ]
    if not daemon:
        tasks.append(asyncio.create_task(cli_input_loop()))
    
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
    await asyncio.gather(*tasks, return_exceptions=True)
    await skill_registry.close()
    
    await servicer.close_streams()
    await server.stop(grace=5)
    if orchestrator.agent_runtime is not None:
        await orchestrator.agent_runtime.close()
    logger.info("Shutdown complete")

def main():
    parser = argparse.ArgumentParser(description="Project Blob backend")
    parser.add_argument("--install-skill", metavar="FILE", help="Validate and install a .skill.yaml file")
    parser.add_argument("--daemon", action="store_true", help="Run without terminal input; connect with blob-chat")
    args = parser.parse_args()
    if args.install_skill:
        from blob.skills.registry import SkillRegistry
        config = BlobConfig.load()
        skill_id = SkillRegistry(config.skills_dir_path).install_file(args.install_skill)
        print(f"Installed skill: {skill_id}")
        return
    asyncio.run(main_async(daemon=args.daemon))

if __name__ == "__main__":
    main()
