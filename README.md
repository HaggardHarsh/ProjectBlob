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
- **Privacy Controls** — Local memory and optional camera processing, with a window blacklist for screen capture.
- **Persistent Memory** — Blob recalls conversations and consolidates durable user facts across sessions via ChromaDB.
- **Living Personality** — Fluid spring-mass physics, state-machine emotions, and contextual reactions.
- **Expandable Skills** — Built-in tools plus validated `.skill.yaml` files loaded at startup or dropped on Blob.
- **No local GPU required** — Inference runs through the configured Nebius API.

---

## Architecture

```
┌─────────────────────────────┐     gRPC (localhost:50051)     ┌─────────────────────────────┐
│   C++ Frontend Overlay      │◄──────────────────────────────►│   Python AI Backend          │
│                             │                                 │                             │
│  • SDL2 transparent overlay │  Bidirectional Streaming        │  • Nebius API (cloud LLM)    │
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
| **Memory** | ChromaDB (local vector store) + access-aware recall |
| **Camera** | Optional OpenCV face and full-body detection with local face enrollment |
| **Frontend** | C++ · SDL2 renderer · optional X11 system tray |
| **Backend** | Python 3.11+ · asyncio · gRPC |
| **Skills** | ReAct loop with built-in tools and validated YAML command skills |

---

## Prerequisites

- **OS**: Linux (X11 or Wayland), Windows 10+, or macOS 12+
- **GPU**: ❌ **Not required** — inference runs on Nebius cloud API
- **Python**: 3.11+
- **C++ Compiler**: GCC 12+ or Clang 15+
- **System packages**: `SDL2`, `gRPC`, `Protobuf`; X11 development headers for the optional tray icon
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
# then edit .env with your key; the backend loads it automatically
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

Right-click or double-click Blob to open the chat window. Type a message and press Enter. Backend replies also appear in a temporary notification bubble. On X11 desktops with a tray manager, clicking Blob's tray icon opens chat; the right-click gesture works when no tray is available. Drag a `.skill.yaml` file onto Blob to install it. The backend also exposes a CLI prompt (`Blob>`) for terminal chat.

To run the backend test suite, install `backend_python[dev]` and run `python -m pytest backend_python/tests -q` from the repository root.

### Camera and named recognition

Install the optional local vision dependency and enable camera access in `.env`:

```bash
pip install -e 'backend_python[vision]'
BLOB_CAMERA_ENABLED=1
```

Restart the backend, then use these commands in the chat window or CLI:

```text
/camera scan
/camera enroll Asha
/camera list
/camera forget Asha
```

Enrollment requires the person's consent and captures at least eight clear frames with one face visible. A scan reports face and full-body detections and matches enrolled faces by name. Recognition uses OpenCV's LBPH model; it can make mistakes, especially with poor light or a changed appearance, so it should not be used for authentication. The camera opens only for a command and is released afterward. Frames are not sent to the LLM or stored in chat memory. Enrollment stores cropped grayscale face samples under `~/.blob/faces/` (or `BLOB_FACE_DB_PATH`); `/camera forget <name>` deletes that person's samples. Camera access is off by default.

### Persistent memory

New installations store ChromaDB data under `~/.blob/memory/chromadb/`, independent of the launch directory. Existing `backend_python/data/chroma_db/` data remains in use automatically when present. Set `BLOB_MEMORY_DB_PATH` to choose another location. Conversations are saved as episodes; consolidation processes each episode once and stores deduplicated, pinned facts drawn from user messages. When the privacy shield is active, Blob omits screen context and pauses episode storage. The Nebius chat API still receives the current user message and recalled memory context during normal chat; avoid sharing sensitive information with the cloud model.

---

## Skill Pills

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
      description: "Show repository status"
      command: "git status --porcelain"
```

Drop the file on Blob, run `blob-backend --install-skill path/to/file.skill.yaml`, or place it in `~/.blob/skills/` before startup. Installed skills persist across restarts. Tools use names such as `git_status_checker.git_status` in the LLM prompt. The command runner accepts a limited set of commands and does not interpret shell pipelines or redirections; see the [skill authoring guide](docs/skill_authoring_guide.md).

---

## Privacy Model

Blob enforces a **zero-trust privacy shield**:

1. **Local storage**: Memory and enrolled face samples stay on this device. Chat requests and recalled context are sent to Nebius when the backend handles a message.
2. **Sensitive app detection**: Banking sites, password managers, and incognito windows trigger an automatic blindfold
3. **Screen captures are temporary**: Command-line capture backends may briefly write a temporary PNG, which Blob removes after loading it.
4. **Memory is local**: ChromaDB uses `~/.blob/memory/chromadb/` by default for new installations.
5. **Configurable blacklist**: Edit `backend_python/data/blacklist.yaml` to add your own patterns

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
