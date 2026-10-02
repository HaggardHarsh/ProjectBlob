# 🏗️ System Architecture

> Technical architecture documentation for Project Blob

The C++ overlay renders a small expressive slime and receives emotes over gRPC.
Conversation uses the desktop chat panel or Python backend terminal. The backend loads
declarative skill pills; an OS-level agent sandbox remains planned.

---

## High-Level Architecture

Project Blob is a two-process desktop application:

```
┌─────────────────────────────────────────────────────────────────────────┐
│                           User's Desktop                                │
│                                                                         │
│  ┌──────────────────────────┐     gRPC      ┌──────────────────────────┐│
│  │  C++ Frontend Overlay    │◄─────────────►│  Python AI Backend       ││
│  │  (Process 1)             │  TCP / socket  │  (Process 2)             ││
│  │                          │  Bidirectional │                          ││
│  │  • SDL2 Window Manager   │  Streaming     │  • Nebius-hosted LLM     ││
│  │  • SDL2 Renderer         │               │  • Input Guardrails      ││
│  │  • Blob State Machine    │  ◄─ Emotes    │  • Hermes Agent Tasks    ││
│  │  • Spring-Mass Physics   │  ◄─ States    │  • ChromaDB Memory       ││
│  │  • Drag-Drop Handler     │  Events ──►   │  • Privacy Shield        ││
│  │  • System Tray           │               │  • Screen OCR Sampler    ││
│  │  • Facial Expressions    │               │  • Restricted Skills     ││
│  └──────────────────────────┘               │  • Skill Registry        ││
│                                              │  • Nebius Burst (opt-in) ││
│                                              └──────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Process Architecture

### Why Two Processes?

1. **Crash Isolation**: If the Python AI backend OOMs or crashes, the C++ overlay stays alive and shows Blob in a sleeping state. The user never sees a crash — just a sleepy blob that wakes up when the backend reconnects.

2. **Performance Isolation**: The C++ frontend targets 60 FPS. The Python backend can wait on cloud inference without blocking the overlay's event loop.

3. **Security Boundary**: The frontend never touches the LLM, memory store, or screen captures directly. All sensitive operations are contained in the backend process.

4. **Independent Development**: Frontend and backend can be developed, tested, and deployed independently.

### IPC Protocol

Communication uses **gRPC bidirectional streaming** over `localhost:50051` by
default. The address is configurable and can also be a Unix domain socket.

- **Frontend → Backend**: User messages with selected local attachment paths and request IDs, user interactions, skill pill drops, heartbeats
- **Backend → Frontend**: Correlated chat replies, emote commands, skill acknowledgments, privacy shield events

See [`proto/blob_service.proto`](../proto/blob_service.proto) for the full protocol definition.

---

## C++ Frontend Architecture

```
┌─────────────────────────────────────────────┐
│              main.cpp (Entry Point)          │
│  • Parse args  • Init SDL2  • Run loop      │
├─────────────┬───────────────┬───────────────┤
│   overlay/  │     blob/     │     ipc/      │
├─────────────┼───────────────┼───────────────┤
│ Window      │ StateMachine  │ GrpcClient    │
│ • Transparent│ • FSM states │ • Bidir stream│
│ • Always-top│ • Transitions│ • Reconnect   │
│ • Shape mask│ • Timers     │ • Reconnect   │
│             │               │               │
│ Renderer    │ Physics       │ EventQueue    │
│ • SDL2      │ • Spring-mass│ • Thread-safe │
│ • Gradient  │ • Verlet     │ • Queue       │
│ • Faces     │ • Collision  │               │
│             │               │               │
│ Input       │ Animation     │               │
│ • Mouse     │ • Interpolate│               │
│ • Drag-drop │ • Eye moods  │               │
│ • Gestures  │ • Timers     │               │
│             │               │               │
│             │ Expressions   │               │
│             │ • Face       │               │
│             │ • Blink      │               │
├─────────────┴───────────────┴───────────────┤
│                    ui/                       │
│               SystemTray                    │
│             • Optional X11 icon            │
└─────────────────────────────────────────────┘
```

### Render Loop

```
while (running) {
    1. Poll SDL events → InputHandler
    2. Process IPC events from EventQueue (non-blocking)
    3. Update StateMachine (dt)
    4. Update Physics (dt)
    5. Update Animations (dt)
    6. Clear framebuffer (transparent)
    7. Render blob mesh (Physics → Renderer)
    8. Render the current facial expression
    9. Present frame and update the shape mask
    10. Cap to 60 FPS (sleep remaining time)
}
```

---

## Python Backend Architecture

```
┌─────────────────────────────────────────────┐
│              main.py (Entry Point)           │
│  • Load config  • Start services  • Asyncio │
├──────────────────────────────────────────────┤
│                  ipc/                        │
│  Server (gRPC)  │  EventDispatcher           │
│  • Bidirectional│  • Route events            │
│  • Multi-client │  • Broadcast to frontends  │
├──────────────────────────────────────────────┤
│                   ai/                        │
│  LLMEngine      │  Orchestrator  │ Guardrails│
│  • Local vLLM   │  • Reasoning   │ • NemoClaw│
│  • Nebius API   │  • Memory RAG  │ • Input   │
│  • Streaming    │  • Emote pick  │ • Output  │
│                 │  • Proactive   │ • Privacy │
├──────────────────────────────────────────────┤
│                 memory/                      │
│  VectorStore    │  Episodic  │ Middle / Long │
│  • ChromaDB     │  • Archive │ • Exact quotes│
│  • Collections  │  • 7d chat │ • Expiry      │
│                 │            │              │
│                 Decay Algorithm              │
│  • Relevance gate and age decay             │
│  • Long-term facts are pinned               │
├──────────────────────────────────────────────┤
│  privacy/       │  screen/     │  skills/    │
│  Shield         │  Sampler     │  Registry   │
│  • Monitor      │  • Capture   │  • Load     │
│  • Blacklist    │  • OCR       │  • Validate │
│  • Debounce     │  • Analyze   │  • Execute  │
│                 │  • Delete    │  • Hot-reload│
├──────────────────────────────────────────────┤
│                 agents/                      │
│  HermesAgent    │  OpenShell                 │
│  • Plan-Act     │  • Sandbox                 │
│  • Observe      │  • Restrict                │
│  • Reflect      │  • Audit                   │
└──────────────────────────────────────────────┘
```

### Async Task Model

The backend runs on a single `asyncio` event loop with concurrent tasks:

```python
async def main():
    # Core services (always running)
    grpc_server = start_grpc_server()
    privacy_monitor = start_privacy_shield()      # polls every 500ms
    screen_sampler = start_screen_sampler()        # runs every 30-60s
    memory_consolidator = start_memory_timer()     # runs every 10 min
    heartbeat = start_heartbeat()                  # sends pong every 5s
    
    # Wait for shutdown
    await asyncio.gather(
        grpc_server, privacy_monitor, screen_sampler,
        memory_consolidator, heartbeat
    )
```

---

## Model serving

The current backend calls the Nebius chat API with `Qwen/Qwen3-30B-A3B-Instruct-2507` by default. `BLOB_MODEL_NAME` can select another available model. Memory search and tool execution remain local to the backend.

### Proposed NVIDIA integration

The diagram below describes a possible local GPU and cloud routing design. It is not the current chat path.

```
┌─────────────────────────────────────────────┐
│              NVIDIA Stack                    │
│                                              │
│  ┌─────────────┐    ┌──────────────────┐    │
│  │ Nemotron-3   │    │ Nebius Serverless │    │
│  │ Nano (4B)    │    │ (Cloud Burst)    │    │
│  │              │    │                  │    │
│  │ Local GPU    │    │ Ultra/Super/70B  │    │
│  │ vLLM/llama   │    │ OpenAI API       │    │
│  └──────┬───────┘    └────────┬─────────┘    │
│         │                     │              │
│         └─────────┬───────────┘              │
│                   ▼                          │
│         ┌──────────────────┐                 │
│         │    NemoClaw       │                 │
│         │ • Input guards   │                 │
│         │ • Output guards  │                 │
│         │ • Privacy router │                 │
│         └────────┬─────────┘                 │
│                  ▼                           │
│         ┌──────────────────┐                 │
│         │  Hermes Agent     │                 │
│         │ • Plan-Act loop  │                 │
│         │ • Skill registry │                 │
│         │ • Sub-agents     │                 │
│         └────────┬─────────┘                 │
│                  ▼                           │
│         ┌──────────────────┐                 │
│         │   OpenShell       │                 │
│         │ • Landlock LSM   │                 │
│         │ • seccomp-BPF    │                 │
│         │ • Network NS     │                 │
│         └──────────────────┘                 │
└─────────────────────────────────────────────┘
```

---

## Data Flow Diagrams

### User Message Flow

```
User types message
    ↓
Desktop chat panel or Python backend terminal → BlobOrchestrator
    ↓
GuardrailsEngine.sanitize_input()
    ↓
SemanticMemory.recall(query)  →  relevant memories
    ↓
PromptTemplates + skills + context + memory + message
    ↓
NebiusEngine.generate_from_messages()
    ↓
GuardrailsEngine.sanitize_output()
    ↓
EpisodicMemory.capture(interaction)
    ↓
Orchestrator extracts the emote tag
    ↓
Response prints in the terminal; emotes and a correlated ChatReply are broadcast
    ↓
gRPC EventStream → Frontend
    ↓
Renderer draws Blob's facial expression; the chat panel displays the reply
```

### Attachment flow

The SDL chat panel sends `UserMessage.attachments` as local file paths over the
existing gRPC stream. `request_id` pairs each submission with a `ChatReply`, so
unrelated notifications cannot finish an outstanding question. Completed replies
are retained in a bounded backend session cache and replayed when a frontend
reconnects. Desktop and terminal requests are processed in order.

`AttachmentReader` validates file counts, types, sizes, page counts, and decoded
image dimensions. PDFium text extraction and rendering run in a worker thread,
under a shared lock because PDFium cannot run concurrently across threads. Text
excerpts keep page numbers. Page and image payloads are resized and encoded in
memory without original image metadata. The prompt budget counts image context
separately from base64 transport bytes. The model receives documents as source
material and cannot execute tools through the attachment analysis path.

Nebius model discovery checks the provider's input modality and selects an
available vision model for attachment requests; `BLOB_VISION_MODEL` can override
or disable discovery. With no vision model, local OCR supplies text only.
Attachment analysis stays outside episodic storage and memory consolidation.

### Screen Context Flow

```
Timer fires (every 30-60 seconds)
    ↓
PrivacyShield.is_active()?  ──YES──►  SKIP
    ↓ NO
ScreenSampler.capture()  →  PIL Image (480p, in-memory)
    ↓
OCRProcessor.extract(image)  →  text + confidence
    ↓
DELETE image from memory
    ↓
ContextAnalyzer.analyze(text)  →  WorkflowContext
    ↓
┌─ "Build Successful"  →  CELEBRATE emote
├─ "Error/Exception"   →  WORRIED emote (offer help)
├─ Coding > 2 hours    →  OFFER_COFFEE emote
└─ No activity > 30min →  SLEEPING state
    ↓
BackendEvent → Frontend → Animation
```

### Skill Pill Ingestion Flow

```
User drags .skill.yaml onto Blob
    ↓
SDL_DROPFILE event → InputHandler
    ↓
FrontendEvent.SkillPillDrop { file_path, hash }
    ↓
gRPC → Backend
    ↓
SkillValidator.validate(file)
    ↓
┌─ Invalid  →  SkillAcknowledgment { success: false, error }
│                 →  CONFUSED emote
│
└─ Valid    →  SkillRegistry.register(skill)
                  →  HermesAgent.register_tool(skill.tools)
                  →  SkillAcknowledgment { success: true }
                  →  EATING emote + ColorShift(skill.color)
    ↓
Frontend plays eating animation
Frontend tints Blob with skill color (2 seconds)
```

---

## Performance Budget

| Component | CPU Target | RAM Target | GPU Target |
|-----------|-----------|-----------|-----------|
| C++ Overlay (idle) | < 0.5% | < 30 MB | < 0.5% |
| C++ Overlay (animating) | < 2% | < 50 MB | < 1% |
| Python Backend (idle) | < 1% | < 200 MB | 0% |
| Python Backend (inference) | < 5% | < 500 MB | 80-100% (GPU) |
| Screen Sampler (per capture) | < 3% spike | < 50 MB spike | 0% |
| ChromaDB (query) | < 1% spike | < 100 MB | 0% |

### Optimization Strategies

1. **60 FPS Cap**: Frontend sleeps between frames to minimize CPU
2. **Lazy Loading**: OCR models loaded only on first screen capture
3. **Batched IPC**: Events are batched per frame, not sent individually
4. **Memory Pooling**: Physics vertices reuse pre-allocated buffers
5. **Async Everything**: Backend uses asyncio to avoid blocking
6. **Model Caching**: LLM stays resident in GPU memory between queries
