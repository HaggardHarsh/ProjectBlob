# 🫧 Project Blob

> A privacy-focused, emotionally intelligent desktop AI companion  
> Built for the **NVIDIA × Nebius Global AI Hackathon** — Personal AI Track

<p align="center">
  <em>Your screen has a new friend. It remembers. It cares. It respects your privacy.</em>
</p>

---

## What is Blob?

Blob is a living desktop companion — a soft, translucent slime creature that resides on your screen. It passively observes your workflow, builds long-term memory about your projects and habits, offers empathetic check-ins when you've been coding too long, and can learn new skills when you feed it "Skill Pills."

**Key principles:**
- **Zero-Trust Privacy** — 100% local data. No telemetry. Hardcoded visual blind spots for sensitive apps.
- **Persistent Memory** — Blob remembers your projects, struggles, and wins across sessions.
- **Living Personality** — Fluid animations, state-machine emotions, and contextual reactions.
- **Expandable Skills** — Drag-and-drop `.skill.yaml` files to teach Blob new tricks.
- **Lightweight** — Sub-2% CPU overhead. Lives alongside your heaviest workloads.

---

## Architecture

```
┌─────────────────────────────┐     gRPC (Unix Socket)     ┌─────────────────────────────┐
│   C++ Frontend Overlay      │◄──────────────────────────►│   Python AI Backend          │
│                             │                             │                             │
│  • SDL2/OpenGL transparent  │  Bidirectional Streaming    │  • NVIDIA Nemotron (Local)   │
│    always-on-top window     │                             │  • NemoClaw Guardrails       │
│  • Spring-mass blob physics │  EmoteCommand ──────────►   │  • Hermes Agent Tasks        │
│  • State machine animations │  StateCommand ──────────►   │  • ChromaDB Memory           │
│  • Drag-drop skill pills    │  ◄────────── FrontendEvent  │  • Privacy Shield            │
│  • Speech bubble UI         │                             │  • Screen OCR Sampler        │
│  • System tray              │                             │  • OpenShell Sandbox         │
└─────────────────────────────┘                             └─────────────────────────────┘
```

---

## NVIDIA Toolchain

| Tool | Role | Integration |
|------|------|-------------|
| **Nemotron-3-Nano (4B)** | Local LLM brain | vLLM / llama.cpp on RTX GPU |
| **NemoClaw** | Security & guardrails | Input/output policy enforcement |
| **Hermes Agent** | Task execution | Plan-Act-Observe-Reflect loops |
| **OpenShell** | Sandboxed execution | Kernel-level isolation for tools |
| **Nebius Serverless** | Cloud burst (opt-in) | Heavy reasoning via Token Factory |

---

## Quick Start

### Prerequisites

- **OS**: Linux (X11/Wayland), Windows 10+, or macOS 12+
- **GPU**: NVIDIA RTX with ≥8 GB VRAM (for local inference)
- **Python**: 3.11+
- **C++ Compiler**: GCC 12+ or Clang 15+
- **SDL2**, **OpenGL 3.3+**, **gRPC**, **Protobuf**

### Build & Run

```bash
# 1. Clone
git clone <repo-url> ProjectBlob && cd ProjectBlob

# 2. Generate Proto stubs
make proto

# 3. Build C++ frontend
make frontend

# 4. Install Python backend
make backend-install

# 5. Start both (backend first, then frontend)
make run
```

### Individual Components

```bash
# Backend only
cd backend_python && pip install -e . && blob-backend --config data/blob_personality.yaml

# Frontend only
cd frontend_cpp && mkdir build && cd build && cmake .. && make && ./blob_overlay
```

---

## Feeding Blob Skills

Drop a `.skill.yaml` file onto Blob to teach it new abilities:

```yaml
skill:
  name: "Git Status Checker"
  description: "Check repository status and recent commits"
  color: "#F05032"
  permissions:
    - shell.execute
  tools:
    - name: "git_status"
      command: "git status --porcelain"
```

Blob will play an **eating animation**, register the skill, and tint its color briefly. See [Skill Authoring Guide](docs/skill_authoring_guide.md) for details.

---

## Privacy Model

Blob enforces a **zero-trust privacy shield**:

1. **No data leaves your machine** (unless you explicitly enable Nebius burst mode)
2. **Sensitive app detection**: Banking sites, password managers, and incognito windows trigger an automatic blindfold
3. **Screen captures are ephemeral**: Processed in memory, never written to disk
4. **Memory is local**: ChromaDB stores everything in `~/.blob/memory/`
5. **Configurable blacklist**: Edit `data/blacklist.yaml` to add your own patterns

---

## Project Structure

```
ProjectBlob/
├── proto/                    # gRPC/Protobuf IPC definitions
├── frontend_cpp/             # C++ transparent overlay engine
│   ├── src/
│   │   ├── overlay/          # Window, renderer, input
│   │   ├── blob/             # State machine, physics, animations
│   │   ├── ipc/              # gRPC client
│   │   └── ui/               # Notifications, tray, chat
│   └── assets/               # Sprites, shaders, sounds
├── backend_python/           # Python AI engine
│   ├── blob/
│   │   ├── ai/               # LLM engine, orchestrator, guardrails
│   │   ├── memory/           # ChromaDB, episodic, decay
│   │   ├── privacy/          # Shield, window monitor, blacklist
│   │   ├── screen/           # Sampler, OCR, context analyzer
│   │   ├── skills/           # Registry, validator, builtins
│   │   └── agents/           # Hermes, OpenShell wrappers
│   └── data/                 # Config files
├── skills/                   # User-facing skill pill files
└── docs/                     # Architecture & guides
```

---

## License

MIT License — Built with 💚 for the NVIDIA × Nebius Global AI Hackathon
