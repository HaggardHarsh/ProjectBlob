import os
from pathlib import Path

BASE_DIR = Path("/home/cloud/ProjectBlob/backend_python")

FILES = {
    "pyproject.toml": """\
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.build_meta"

[project]
name = "blob-backend"
version = "0.1.0"
description = "Project Blob AI Backend"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "grpcio>=1.59.0",
    "grpcio-tools>=1.59.0",
    "chromadb>=0.4.15",
    "openai>=1.3.0",
    "pyyaml>=6.0.1",
    "pillow>=10.0.1",
    "easyocr>=1.7.1",
    "psutil>=5.9.6",
    "pydantic>=2.4.2",
    "watchdog>=3.0.0"
]

[project.optional-dependencies]
vllm = ["vllm"]
llama-cpp = ["llama-cpp-python"]
openshell = ["openshell"]

[project.scripts]
blob-backend = "blob.main:main"
""",
    "blob/__init__.py": """\
__version__ = "0.1.0"
""",
    "blob/config.py": """\
import os
import yaml
from pydantic import BaseModel, Field

class BlobConfig(BaseModel):
    ipc_address: str = Field(default="localhost:50051")
    llm_backend: str = Field(default="nebius") # local or nebius
    model_name: str = Field(default="meta-llama/Meta-Llama-3.1-70B-Instruct")
    nebius_api_key: str = Field(default=os.environ.get("NEBIUS_API_KEY", ""))
    nebius_base_url: str = Field(default="https://api.studio.nebius.ai/v1")
    memory_db_path: str = Field(default="./data/chroma_db")
    blacklist_path: str = Field(default="./data/blacklist.yaml")
    personality_path: str = Field(default="./data/blob_personality.yaml")
    screen_sample_interval_sec: int = Field(default=30)
    privacy_poll_interval_ms: int = Field(default=500)
    energy_decay_rate: float = Field(default=0.01)

    @classmethod
    def load(cls, config_path: str = "config.yaml") -> "BlobConfig":
        if os.path.exists(config_path):
            with open(config_path, "r") as f:
                data = yaml.safe_load(f) or {}
            return cls(**data)
        return cls()
""",
    "blob/main.py": """\
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
""",
    "blob/ipc/__init__.py": "",
    "blob/ipc/server.py": """\
import asyncio
import logging
import grpc
from grpc import aio
from blob.proto import blob_service_pb2_grpc
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
""",
    "blob/ipc/servicer.py": """\
import logging
from blob.proto import blob_service_pb2_grpc, blob_service_pb2
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
""",
    "blob/ipc/event_dispatcher.py": """\
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
""",
    "blob/ai/__init__.py": "",
    "blob/ai/llm_engine.py": """\
from typing import AsyncIterator
import logging
from openai import AsyncOpenAI
import abc

logger = logging.getLogger(__name__)

class LLMEngine(abc.ABC):
    @abc.abstractmethod
    async def generate(self, prompt: str, context: str, system_prompt: str) -> str:
        pass

    @abc.abstractmethod
    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        pass

class NebiusEngine(LLMEngine):
    def __init__(self, api_key: str, base_url: str, model_name: str):
        self.client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self.model_name = model_name

    async def generate(self, prompt: str, context: str, system_prompt: str) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\\n{context}\\n\\nPrompt:\\n{prompt}"}
        ]
        resp = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages
        )
        return resp.choices[0].message.content

    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Context:\\n{context}\\n\\nPrompt:\\n{prompt}"}
        ]
        stream = await self.client.chat.completions.create(
            model=self.model_name,
            messages=messages,
            stream=True
        )
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

class LocalEngine(LLMEngine):
    async def generate(self, prompt: str, context: str, system_prompt: str) -> str:
        return "Local LLM response placeholder"

    async def generate_streaming(self, prompt: str, context: str, system_prompt: str) -> AsyncIterator[str]:
        yield "Local "
        yield "LLM "
        yield "response"
""",
    "blob/ai/orchestrator.py": """\
import asyncio
import logging
from blob.ai.llm_engine import NebiusEngine, LocalEngine
from blob.proto import blob_service_pb2
from blob.ai.guardrails import GuardrailsEngine

logger = logging.getLogger(__name__)

class BlobOrchestrator:
    def __init__(self, config, vector_store):
        self.config = config
        self.vector_store = vector_store
        self.guardrails = GuardrailsEngine(config)
        if config.llm_backend == "nebius":
            self.llm = NebiusEngine(config.nebius_api_key, config.nebius_base_url, config.model_name)
        else:
            self.llm = LocalEngine()
            
    async def handle_user_message(self, user_msg):
        # sanitize input
        clean_text = self.guardrails.sanitize_input(user_msg.text)
        
        # retrieve memories
        memories = self.vector_store.recall(clean_text, top_k=3)
        context = "\\n".join([m['text'] for m in memories])
        
        # generate response
        sys_prompt = "You are Blob, a friendly AI desktop companion."
        response = await self.llm.generate(clean_text, context, sys_prompt)
        
        # apply output filter
        response = self.guardrails.filter_output(response)
        
        # save episodic memory
        self.vector_store.store(f"User: {clean_text}\\nBlob: {response}", {"type": "episodic"})
        
        # ... logic to determine emote and dispatch ...
""",
    "blob/ai/guardrails.py": """\
import re
import logging

logger = logging.getLogger(__name__)

class GuardrailsEngine:
    def __init__(self, config):
        self.config = config
        
    def sanitize_input(self, text: str) -> str:
        # PII stripping regex or NemoClaw integration
        return text
        
    def filter_output(self, text: str) -> str:
        # Check against harmful content
        return text
""",
    "blob/ai/prompt_templates.py": """\
SYSTEM_PROMPT = "You are Blob, a desktop AI companion. You are helpful, empathetic, and concise."
CONTEXT_TEMPLATE = \"\"\"
Memories:
{memories}

Screen Context:
{screen_context}

Skills Available:
{skills}
\"\"\"
""",
    "blob/memory/__init__.py": "",
    "blob/memory/vector_store.py": """\
import chromadb
import asyncio
import logging
from blob.memory.decay import DecayAlgorithm

logger = logging.getLogger(__name__)

class VectorStore:
    def __init__(self, db_path: str):
        self.client = chromadb.PersistentClient(path=db_path)
        self.episodic = self.client.get_or_create_collection("episodic")
        self.semantic = self.client.get_or_create_collection("semantic")
        self.decay_algo = DecayAlgorithm()
        self.memory_id_counter = 0

    def store(self, text: str, metadata: dict):
        self.memory_id_counter += 1
        doc_id = str(self.memory_id_counter)
        self.episodic.add(documents=[text], metadatas=[metadata], ids=[doc_id])
        
    def recall(self, query: str, top_k: int = 5) -> list:
        results = self.episodic.query(query_texts=[query], n_results=top_k)
        if not results['documents']:
            return []
        
        recalled = []
        for doc, meta, id_ in zip(results['documents'][0], results['metadatas'][0], results['ids'][0]):
            recalled.append({"id": id_, "text": doc, "metadata": meta})
        return recalled

    def delete(self, memory_id: str):
        self.episodic.delete(ids=[memory_id])

    async def consolidation_loop(self):
        while True:
            await asyncio.sleep(3600)  # every hour
            logger.info("Consolidating memories...")
""",
    "blob/memory/episodic.py": """\
class EpisodicMemory:
    def __init__(self):
        self.buffer = []
        
    def add_episode(self, user_msg, blob_msg, timestamp, context):
        self.buffer.append({
            "user": user_msg,
            "blob": blob_msg,
            "ts": timestamp,
            "context": context
        })
""",
    "blob/memory/semantic.py": """\
class SemanticMemory:
    def __init__(self, vector_store):
        self.vector_store = vector_store
        
    def summarize_and_store(self, episodes):
        # ... logic to summarize episodes into a semantic fact ...
        pass
""",
    "blob/memory/decay.py": """\
import math
import time

class DecayAlgorithm:
    def __init__(self, lambda_val: float = 0.05):
        self.lambda_val = lambda_val
        
    def calculate_score(self, base_similarity: float, days_since_access: float, access_count: int) -> float:
        return base_similarity * math.exp(-self.lambda_val * days_since_access) * (1 + access_count * 0.1)
""",
    "blob/privacy/__init__.py": "",
    "blob/privacy/shield.py": """\
import asyncio
import logging
from blob.privacy.window_monitor import WindowMonitor
from blob.privacy.blacklist import BlacklistManager

logger = logging.getLogger(__name__)

class PrivacyShield:
    def __init__(self, config):
        self.config = config
        self.monitor = WindowMonitor()
        self.blacklist = BlacklistManager(config.blacklist_path)
        self.is_active = False

    async def run(self):
        while True:
            try:
                window_info = self.monitor.get_active_window()
                if window_info and self.blacklist.is_blacklisted(window_info):
                    if not self.is_active:
                        self.is_active = True
                        logger.info(f"Privacy Shield ACTIVE: {window_info.title}")
                else:
                    if self.is_active:
                        self.is_active = False
                        logger.info("Privacy Shield INACTIVE")
            except Exception as e:
                logger.error(f"Error in privacy shield: {e}")
            await asyncio.sleep(self.config.privacy_poll_interval_ms / 1000.0)
""",
    "blob/privacy/window_monitor.py": """\
import sys
import subprocess
from dataclasses import dataclass

@dataclass
class WindowInfo:
    title: str
    process_name: str
    pid: int

class WindowMonitor:
    def get_active_window(self) -> WindowInfo:
        if sys.platform == "linux":
            try:
                title = subprocess.check_output(["xdotool", "getactivewindow", "getwindowname"]).decode().strip()
                return WindowInfo(title=title, process_name="", pid=0)
            except Exception:
                return None
        return None
""",
    "blob/privacy/blacklist.py": """\
import yaml
import re

class BlacklistManager:
    def __init__(self, config_path: str):
        self.patterns = []
        try:
            with open(config_path, 'r') as f:
                data = yaml.safe_load(f) or {}
                self.patterns = [re.compile(p, re.IGNORECASE) for p in data.get('patterns', [])]
        except Exception:
            pass

    def is_blacklisted(self, window_info) -> bool:
        for p in self.patterns:
            if p.search(window_info.title) or p.search(window_info.process_name):
                return True
        return False
""",
    "blob/screen/__init__.py": "",
    "blob/screen/sampler.py": """\
import asyncio
import logging
from PIL import ImageGrab

logger = logging.getLogger(__name__)

class ScreenSampler:
    def __init__(self, config, privacy_shield, orchestrator):
        self.config = config
        self.privacy_shield = privacy_shield
        self.orchestrator = orchestrator

    async def run(self):
        while True:
            if not self.privacy_shield.is_active:
                try:
                    img = ImageGrab.grab()
                    # process img...
                except Exception as e:
                    logger.error(f"Failed to grab screen: {e}")
            await asyncio.sleep(self.config.screen_sample_interval_sec)
""",
    "blob/screen/ocr.py": """\
import easyocr

class OCRProcessor:
    def __init__(self):
        self.reader = None
        
    def get_reader(self):
        if self.reader is None:
            self.reader = easyocr.Reader(['en'])
        return self.reader
        
    def extract_text(self, image_path: str) -> str:
        reader = self.get_reader()
        result = reader.readtext(image_path)
        return " ".join([text for _, text, _ in result])
""",
    "blob/screen/context_analyzer.py": """\
from dataclasses import dataclass

@dataclass
class WorkflowContext:
    state: str
    confidence: float

class ContextAnalyzer:
    def analyze(self, text: str) -> WorkflowContext:
        text_lower = text.lower()
        if "build successful" in text_lower or "all tests passed" in text_lower:
            return WorkflowContext("CELEBRATE", 0.9)
        elif "error" in text_lower or "exception" in text_lower:
            return WorkflowContext("WORRIED", 0.8)
        return WorkflowContext("NORMAL", 0.5)
""",
    "blob/skills/__init__.py": "",
    "blob/skills/base.py": """\
import abc
from dataclasses import dataclass

@dataclass
class SkillResult:
    output: str
    success: bool
    emote_suggestion: str = "IDLE"

class SkillInterface(abc.ABC):
    @property
    @abc.abstractmethod
    def name(self) -> str: pass
    
    @property
    @abc.abstractmethod
    def description(self) -> str: pass
    
    @property
    @abc.abstractmethod
    def triggers(self) -> list[str]: pass
    
    @abc.abstractmethod
    def execute(self, args: dict) -> SkillResult: pass
""",
    "blob/skills/registry.py": """\
class SkillRegistry:
    def __init__(self):
        self.skills = {}
        
    def register(self, skill):
        self.skills[skill.name] = skill
        
    def get_skill(self, name):
        return self.skills.get(name)
""",
    "blob/skills/validator.py": """\
import yaml
from dataclasses import dataclass

@dataclass
class SkillDefinition:
    name: str
    description: str

class SkillValidator:
    def validate(self, yaml_content: str) -> SkillDefinition:
        data = yaml.safe_load(yaml_content)
        if 'name' not in data or 'description' not in data:
            raise ValueError("Invalid skill definition")
        return SkillDefinition(name=data['name'], description=data['description'])
""",
    "blob/skills/builtin/__init__.py": "",
    "blob/skills/builtin/weather.py": """\
import urllib.request
from blob.skills.base import SkillInterface, SkillResult

class WeatherSkill(SkillInterface):
    @property
    def name(self): return "weather"
    
    @property
    def description(self): return "Get the current weather"
    
    @property
    def triggers(self): return ["weather", "forecast"]
    
    def execute(self, args):
        try:
            req = urllib.request.Request("https://wttr.in/?format=3", headers={'User-Agent': 'curl/7.0.0'})
            res = urllib.request.urlopen(req).read().decode('utf-8')
            return SkillResult(output=res, success=True, emote_suggestion="HAPPY")
        except Exception as e:
            return SkillResult(output=str(e), success=False, emote_suggestion="WORRIED")
""",
    "blob/skills/builtin/git_status.py": """\
import subprocess
from blob.skills.base import SkillInterface, SkillResult

class GitStatusSkill(SkillInterface):
    @property
    def name(self): return "git_status"
    
    @property
    def description(self): return "Check git status in current directory"
    
    @property
    def triggers(self): return ["git status", "repo status"]
    
    def execute(self, args):
        try:
            out = subprocess.check_output(["git", "status"], stderr=subprocess.STDOUT).decode()
            return SkillResult(output=out, success=True, emote_suggestion="THINKING")
        except subprocess.CalledProcessError as e:
            return SkillResult(output=e.output.decode(), success=False, emote_suggestion="CONFUSED")
""",
    "blob/skills/builtin/file_search.py": """\
import os
from blob.skills.base import SkillInterface, SkillResult

class FileSearchSkill(SkillInterface):
    @property
    def name(self): return "file_search"
    
    @property
    def description(self): return "Search for files"
    
    @property
    def triggers(self): return ["find file", "search file"]
    
    def execute(self, args):
        query = args.get('query', '')
        results = []
        for root, dirs, files in os.walk('.'):
            for f in files:
                if query in f:
                    results.append(os.path.join(root, f))
        return SkillResult(output="\\n".join(results[:10]), success=True)
""",
    "blob/agents/__init__.py": "",
    "blob/agents/hermes.py": """\
class HermesAgentWrapper:
    def __init__(self, registry):
        self.registry = registry
        
    def execute_task(self, task_description):
        pass
""",
    "blob/agents/openshell.py": """\
import subprocess

class OpenShellSandbox:
    def execute(self, command):
        try:
            return subprocess.check_output(command, shell=True).decode()
        except subprocess.CalledProcessError as e:
            return str(e)
""",
    "data/blacklist.yaml": """\
patterns:
  - "1Password"
  - "Bank"
  - "Incognito"
""",
    "data/blob_personality.yaml": """\
name: "Blob"
traits: ["friendly", "empathetic", "concise"]
""",
    "tests/conftest.py": """\
import pytest
""",
    "tests/test_privacy_shield.py": """\
def test_privacy_shield(): pass
""",
    "tests/test_memory.py": """\
def test_memory(): pass
""",
    "tests/test_skill_registry.py": """\
def test_skill_registry(): pass
""",
    "tests/test_screen_sampler.py": """\
def test_screen_sampler(): pass
"""
}

def generate_proto():
    os.makedirs(BASE_DIR / "blob/proto", exist_ok=True)
    open(BASE_DIR / "blob/proto/__init__.py", "w").close()
    
    import grpc_tools.protoc
    grpc_tools.protoc.main((
        '',
        '-I/home/cloud/ProjectBlob/proto',
        '--python_out=' + str(BASE_DIR / "blob/proto"),
        '--grpc_python_out=' + str(BASE_DIR / "blob/proto"),
        '/home/cloud/ProjectBlob/proto/blob_service.proto',
    ))

    # fix import in pb2_grpc
    pb2_grpc = BASE_DIR / "blob/proto/blob_service_pb2_grpc.py"
    if pb2_grpc.exists():
        with open(pb2_grpc, 'r') as f:
            content = f.read()
        content = content.replace("import blob_service_pb2 as blob__service__pb2", "from . import blob_service_pb2 as blob__service__pb2")
        with open(pb2_grpc, 'w') as f:
            f.write(content)

for rel_path, content in FILES.items():
    p = BASE_DIR / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w") as f:
        f.write(content)

# We might not have grpc_tools installed globally here, so just write the files and let the user compile them or run grpc_tools in a subprocess if possible.
