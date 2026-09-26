# 🫧 Project Blob

> A privacy-focused, emotionally intelligent desktop AI companion  
> Built for the **NVIDIA × Nebius Global AI Hackathon** — Personal AI Track

<p align="center">
  <em>Your screen has a new friend. It remembers. It cares. It respects your privacy.</em>
</p>

---

## What is Blob?

Blob is a living desktop companion — a soft, translucent slime creature (styled like Rimuru Tempest) that resides on your screen. It observes your workflow, builds long-term memory about your projects and habits, offers empathetic check-ins, and executes real tasks via a ReAct skill loop.

**Key principles:**
- **Zero-Trust Privacy** — 100% local data. No telemetry. Hardcoded visual blind spots for sensitive apps.
- **Persistent Memory** — Blob remembers your projects, struggles, and wins across sessions via ChromaDB.
- **Living Personality** — Fluid spring-mass physics, state-machine emotions, and contextual reactions.
- **Expandable Skills** — Teach Blob new tricks with `.skill.yaml` files.
- **Lightweight** — Sub-2% CPU overhead. No local GPU required.

---

## Architecture

```
┌─────────────────────────────┐     gRPC (localhost:50051)     ┌─────────────────────────────┐
│   C++ Frontend Overlay      │◄──────────────────────────────►│   Python AI Backend          │
│                             │                                 │                             │
│  • SDL2/OpenGL transparent  │  Bidirectional Streaming        │  • Nebius API (cloud LLM)    │
│    always-on-top window     │                                 │  • ReAct Skill Loop          │
│  • Spring-mass blob physics │  EmoteCommand ──────────►       │  • ChromaDB Memory           │
│  • State machine animations │  NotificationBubble ────►       │  • Privacy Shield            │
│  • Rimuru-style renderer    │  ◄──────── FrontendEvent        │  • Screen Capture (Wayland)  │
│                             │                                 │  • Skill Registry            │
└─────────────────────────────┘                                 └─────────────────────────────┘
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **LLM** | [Nebius AI](https://studio.nebius.ai) — cloud API, no local GPU needed |
| **Model** | `nvidia/Nemotron-3_5-Lightning` via Nebius |
| **Memory** | ChromaDB (local vector store) + Ebbinghaus decay |
| **Frontend** | C++ · SDL2 · OpenGL 3.3 |
| **Backend** | Python 3.11+ · asyncio · gRPC |
| **Skills** | ReAct loop (Reason → Act → Observe) with built-in: `reminder`, `weather`, `shell_command`, `file_search`, `git_status`, `screen_capture` |

---

## Prerequisites

- **OS**: Linux (X11 or Wayland), Windows 10+, or macOS 12+
- **GPU**: ❌ **Not required** — inference runs on Nebius cloud API
- **Python**: 3.11+
- **C++ Compiler**: GCC 12+ or Clang 15+
- **System packages**: `SDL2`, `OpenGL 3.3+`, `gRPC`, `Protobuf`
- **Optional (screen capture)**: `gnome-screenshot` or `grim` (Wayland), or `xdotool` (X11)
- **Nebius API Key**: Free at [studio.nebius.ai](https://studio.nebius.ai)

---

## Quick Start

### 1. Clone & Set Up

```bash
git clone <repo-url> ProjectBlob && cd ProjectBlob
```

### 2. Set your Nebius API key

```bash
export NEBIUS_API_KEY=your_key_here
# Or add it to a .env file:
cp .env.example .env
# then edit .env with your key and: export $(cat .env | xargs)
```

### 3. Create a virtual environment & install

```bash
python3 -m venv venv
source venv/bin/activate
pip install -e backend_python/
```

### 4. Build the C++ frontend

```bash
make frontend
```

### 5. Run

```bash
# Backend + Frontend together:
make run

# Or separately (two terminals):
make run-backend-only   # Terminal 1: Python AI backend + CLI chat
make run-frontend       # Terminal 2: C++ Rimuru overlay
```

The backend also exposes a **CLI debug prompt** (`Blob>`) so you can chat directly from the terminal while the C++ frontend is optional.

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

Blob will play an **eating animation**, register the skill, and tint its color briefly.

---

## Privacy Model

Blob enforces a **zero-trust privacy shield**:

1. **No data leaves your machine** (except LLM inference calls to Nebius — opt-in cloud burst)
2. **Sensitive app detection**: Banking sites, password managers, and incognito windows trigger an automatic blindfold
3. **Screen captures are ephemeral**: Processed in memory, temp files cleaned up immediately after OCR
4. **Memory is local**: ChromaDB stores everything in `backend_python/data/chroma_db/`
5. **Configurable blacklist**: Edit `data/blacklist.yaml` to add your own patterns

---

## Project Structure

```
ProjectBlob/
├── .env.example              # Copy to .env and add your NEBIUS_API_KEY
├── proto/                    # gRPC/Protobuf IPC definitions
├── frontend_cpp/             # C++ transparent overlay engine
│   ├── src/
│   │   ├── blob/             # State machine, physics, Rimuru renderer
│   │   └── ipc/              # gRPC client
│   └── build/                # Built binary: blob_overlay
├── backend_python/           # Python AI engine
│   ├── blob/
│   │   ├── ai/               # LLM engine, ReAct orchestrator, guardrails, prompts
│   │   ├── memory/           # ChromaDB, episodic, semantic, Ebbinghaus decay
│   │   ├── privacy/          # Shield, window monitor, blacklist
│   │   ├── screen/           # Multi-backend screen capture, OCR
│   │   └── skills/           # Registry, base class, builtins
│   └── data/                 # Personality config, blacklist
├── skills/                   # User-facing .skill.yaml pill files
└── docs/                     # Architecture & guides
```

---

## License

MIT License — Built with 💚 for the NVIDIA × Nebius Global AI Hackathon
