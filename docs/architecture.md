# 🏗️ System Architecture

> Technical architecture documentation for Project Blob

This document includes the intended architecture. The C++ chat, notification,
X11 tray, and gRPC event stream are implemented. The backend loads declarative
skill pills, while the agent sandbox and some advanced animations in the
diagrams remain planned rather than implemented.

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
│  │  • SDL2 Window Manager   │  Streaming     │  • NVIDIA Nemotron LLM   ││
│  │  • OpenGL 3.3 Renderer   │               │  • NemoClaw Guardrails   ││
│  │  • Blob State Machine    │  ◄─ Emotes    │  • Hermes Agent Tasks    ││
│  │  • Spring-Mass Physics   │  ◄─ States    │  • ChromaDB Memory       ││
│  │  • Drag-Drop Handler     │  Events ──►   │  • Privacy Shield        ││
│  │  • System Tray           │               │  • Screen OCR Sampler    ││
│  │  • Chat Window           │               │  • Restricted Skills     ││
│  └──────────────────────────┘               │  • Skill Registry        ││
│                                              │  • Nebius Burst (opt-in) ││
│                                              └──────────────────────────┘│
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Process Architecture

### Why Two Processes?

1. **Crash Isolation**: If the Python AI backend OOMs or crashes, the C++ overlay stays alive and shows Blob in a sleeping state. The user never sees a crash — just a sleepy blob that wakes up when the backend reconnects.

2. **Performance Isolation**: The C++ frontend runs at 30 FPS with < 2% CPU. The Python backend can saturate the GPU with LLM inference without affecting the overlay's responsiveness.

3. **Security Boundary**: The frontend never touches the LLM, memory store, or screen captures directly. All sensitive operations are contained in the backend process.

4. **Independent Development**: Frontend and backend can be developed, tested, and deployed independently.

### IPC Protocol

Communication uses **gRPC bidirectional streaming** over `localhost:50051` by
default. The address is configurable and can also be a Unix domain socket.

- **Frontend → Backend**: User interactions, skill pill drops, heartbeats
- **Backend → Frontend**: Emote commands, state changes, notifications, privacy shield events

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
│ • Click-thru│ • Timers     │ • Fallback    │
│             │               │               │
│ Renderer    │ Physics       │ EventQueue    │
│ • OpenGL    │ • Spring-mass│ • Thread-safe │
│ • Sprites   │ • Verlet     │ • MPSC        │
│ • Shaders   │ • Collision  │               │
│             │               │               │
│ Input       │ Animation     │               │
│ • Mouse     │ • Interpolate│               │
│ • Drag-drop │ • Eyes/mouth │               │
│ • Gestures  │ • Particles  │               │
│             │               │               │
│             │ Emotes        │               │
│             │ • Mapping    │               │
│             │ • Effects    │               │
├─────────────┴───────────────┴───────────────┤
│                    ui/                       │
│  Notification  │  SystemTray  │  ChatWindow  │
│  • Bubbles     │  • Menu      │  • Text input│
│  • Priority    │  • Status    │  • History   │
│  • Animation   │  • Toggle    │  • Send/Recv │
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
    8. Render eyes/mouth (Animation → Renderer)
    9. Render emote effects (Emotes → Renderer)
    10. Render notifications (NotificationManager)
    11. Present frame
    12. Cap to 30 FPS (sleep remaining time)
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
│  VectorStore    │  Episodic  │  Semantic     │
│  • ChromaDB     │  • Buffer  │  • Summarize │
│  • Collections  │  • Capture │  • Merge     │
│                 │            │              │
│                 Decay Algorithm              │
│  • Exponential decay with access refresh    │
│  • λ=0.05 (14-day half-life)               │
│  • Pinned memories (λ=0)                   │
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

## NVIDIA Toolchain Integration

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
ChatWindow (C++) → FrontendEvent.UserMessage
    ↓
gRPC EventStream → Backend
    ↓
GuardrailsEngine.sanitize_input()
    ↓
SemanticMemory.recall(query)  →  relevant memories
    ↓
PromptTemplates.build(personality + context + memory + message)
    ↓
LLMEngine.generate(prompt)
    ↓  (local Nemotron or Nebius burst)
GuardrailsEngine.sanitize_output()
    ↓
EpisodicMemory.capture(interaction)
    ↓
Orchestrator.classify_emote(response)
    ↓
BackendEvent { notification + emote }
    ↓
gRPC EventStream → Frontend
    ↓
NotificationBubble (speech bubble) + EmoteCommand (animation)
```

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

1. **30 FPS Cap**: Frontend sleeps between frames to minimize CPU
2. **Lazy Loading**: OCR models loaded only on first screen capture
3. **Batched IPC**: Events are batched per frame, not sent individually
4. **Memory Pooling**: Physics vertices reuse pre-allocated buffers
5. **Async Everything**: Backend uses asyncio to avoid blocking
6. **Model Caching**: LLM stays resident in GPU memory between queries
