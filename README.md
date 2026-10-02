# 🫧 Project Blob

> A privacy-focused, emotionally intelligent desktop AI companion  
> Built for the **NVIDIA × Nebius Global AI Hackathon** — Personal AI Track

<p align="center">
  <em>Your screen has a new friend. It remembers. It cares. It respects your privacy.</em>
</p>

---

## What is Blob?

Blob is a living desktop companion — a small blue slime with expressive eyes that resides on your screen. It observes your workflow, builds long-term memory about your projects and habits, offers empathetic check-ins, and executes real tasks via a ReAct skill loop.

**Key principles:**
- **Privacy Controls** — Local memory and optional camera processing, with a window blacklist for screen capture.
- **Persistent Memory** — Blob recalls conversations and consolidates durable user facts across sessions via ChromaDB.
- **Living Personality** — A warm buddy by default, shown as a small, softly moving slime whose tiny eyes show its mood; Blob follows requests for a different tone.
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
│  • Calm slime animation     │  EmoteCommand ──────────►       │  • ChromaDB Memory           │
│  • Facial expressions       │  EmoteCommand ──────────►       │  • Privacy Shield            │
│  • Tiny eye expressions     │  ◄──────── FrontendEvent        │  • Screen Capture (Wayland)  │
│                             │                                 │  • Skill Registry            │
└─────────────────────────────┘                                 └─────────────────────────────┘
```

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| **LLM** | [Nebius AI](https://studio.nebius.ai) — cloud API, no local GPU needed |
| **Model** | `Qwen/Qwen3-30B-A3B-Instruct-2507` via Nebius |
| **Memory** | ChromaDB (local vector store) + relevance-gated recall |
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
- **Screen capture**: A desktop screenshot portal on Wayland; `gnome-screenshot` or `grim` can serve as fallbacks. Install `backend_python[ocr]` separately if you want Blob to read text in captures.
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
make run-frontend       # Terminal 2: C++ slime overlay
```

Chat at the backend's `Blob>` terminal prompt. The small desktop slime shows emotions and accepts dropped files. Drag it to move it; click, right-click, double-click, or click its optional X11 tray icon for a little jiggle. Drop a `.skill.yaml` file onto Blob to install it; the result appears in the terminal.

### PDF and image attachments

Drag PDFs or images onto the desktop Blob. It prints a brief analysis in the backend terminal, then keeps those files available for follow-up questions at `Blob>`. Ask "Explain page 12" or "Summarize pages 3-5" directly in the terminal. Dropping additional files adds them to the current session. Supported formats are PDF, PNG, JPEG, and WebP, with up to four attached files, at most 20 MB each and 50 MB combined. PDFs can contain up to 100 pages.

Use `/files` to list attached files, `/files remove <number>` to detach one, or `/files clear` to detach all files and return to ordinary conversation. Explicit requests such as reminders, camera commands, and screen capture continue to work while files are attached. File selections last until detached or the backend restarts.

The backend extracts PDF text locally and includes filenames and page numbers as source references. File analysis budgets excerpts, page labels, and images together within `BLOB_MAX_PROMPT_BYTES` (32,000 by default). Long documents and wide page ranges use relevant page excerpts; the supplied context identifies omitted pages and text. Image analysis discovers an available image-input model from your Nebius account. You can set `BLOB_VISION_MODEL` to an exact model ID or `off` to use local OCR only. Ordinary chat continues using `BLOB_MODEL_NAME`.

Visual requests send resized images, including up to three selected PDF page images per document and four images total. When no vision model is available, Blob can read text in images and scanned PDFs using the optional `backend_python[ocr]` installation. OCR alone cannot describe objects, colors, or diagrams. Unreadable, damaged, password protected, and oversized files produce an error instead of an invented explanation.

Dropping files and asking follow-up questions shares selected file content with your cloud AI provider. The backend prints this when a drop arrives. PDF parsing and OCR happen locally; original files are left in place. Document contents and attachment answers are not automatically saved as personal memories.

To run the backend test suite, install `backend_python[dev]` and run `python -m pytest backend_python/tests -q` from the repository root.

### Camera and named recognition

Install the optional local vision dependency to use the camera. Camera access is enabled by default but opens only when requested; set `BLOB_CAMERA_ENABLED=0` in `.env` to disable it:

```bash
pip install -e 'backend_python[vision]'
```

Restart the backend, then say "Camera", ask Blob to open or scan your camera, or use these commands at the `Blob>` prompt:

```text
/camera scan
/camera status
/camera enroll Asha
/camera list
/camera forget Asha
```

Enrollment requires the person's consent and captures at least eight clear frames with one face visible. A scan reports face and full-body detections and matches enrolled faces by name. Recognition uses OpenCV's LBPH model; it can make mistakes, especially with poor light or a changed appearance, so it should not be used for authentication. The camera opens only for a request and is released afterward. Frames are not sent to the LLM or stored in chat memory. Enrollment stores cropped grayscale face samples under `~/.blob/faces/` (or `BLOB_FACE_DB_PATH`); `/camera forget <name>` deletes that person's samples.

`/camera status` opens the webcam long enough to verify that a frame can be read. Webcam access is separate from Wayland screen sharing. A scan reports detections, not a general visual description of the camera scene.

### Screen sharing

Say "show me my screen" or use `/screen`. On Wayland, Blob asks the desktop screenshot portal for one capture. Accept the desktop's permission dialog if it appears. Blob extracts text from the screenshot when the optional OCR dependency is installed:

```bash
pip install -e 'backend_python[ocr]'
```

Restart Blob after installing OCR. Screen capture is on request only, including requests for help with material on the screen. Blob uses the active window title and extracted text to answer, rather than sending the full image to the cloud model. If capture or OCR fails, Blob reports that directly. File search runs only for an explicit request to find a file; it does not search the visible screen.
Blob also uses RapidOCR when it is installed locally; this can provide OCR without loading PyTorch.

### Persistent memory

New installations store ChromaDB data under `~/.blob/memory/chromadb/`, independent of the launch directory. Existing `backend_python/data/chroma_db/` data remains in use automatically when present. Set `BLOB_MEMORY_DB_PATH` to choose another location. Blob has three active memory tiers: the most recent 12 conversation messages in the current session; middle-term quotes about ongoing projects and future events; and long-term quotes about stable preferences, hobbies, and identity. Consolidation selects numbered sentences from the user's original wording. Middle-term memories expire after 30 days by default, or after the day of a recognized dated event. Expired middle-term records are deleted; the original conversation episodes remain in the local archive. Long-term facts remain until corrected or deleted. When consolidation selects a new statement about a recognized topic, including favorites, names, hobbies, and likes, it supersedes older active facts. Other corrections still rely on the newer conversation context and may need manual review. Older model-written summaries are marked unverified in prompts until they are removed. When the privacy shield is active, Blob omits screen context and pauses episode storage. The Nebius chat API still receives the current user message and recalled memory context during normal chat; avoid sharing sensitive information with the cloud model.

To replace old semantic summaries, stop Blob and create a JSON file containing a list of exact sentences from the user's side of saved conversations. Run `PYTHONPATH=backend_python python -m blob.memory.migrate_legacy --facts-file /path/to/reviewed-facts.json` from the repository root. The command checks every sentence against the original episodes, backs up the complete ChromaDB directory under `memory_backups/` beside the database, removes only ungrounded semantic entries, and keeps the episodes. An empty list removes all old semantic summaries while preserving newer grounded facts. Restart Blob after migration.

Memory search runs locally and sends only a bounded view of relevant matches to Nebius. The default embedding distance cutoff rejects weak matches; recent access does not make an old memory more relevant. Ordinary chat recalls conversation episodes from the last seven days. Explicit history questions can search the full episode archive. Long records are excerpted around terms in the current question; the full records remain in ChromaDB. Ordinary replies use the user's side of retrieved episodes; Blob's old replies appear only when asked what Blob said. Recent turns are also sent in their original user and assistant roles during the current backend session. Blob uses the computer's local clock for current day and date questions.

Set `BLOB_PROFILE_LATENCY=1` when launching the backend to log how long local preparation and the model call take for each reply. Blob caches the fixed tone preference search between memory changes, so repeat messages avoid that extra lookup.

Blob defaults to Qwen3-30B-A3B-Instruct-2507. Set `BLOB_MODEL_NAME` in `.env` to select another Nebius model. If you select `nvidia/Nemotron-3_5-Lightning`, Blob uses its faster non-reasoning chat mode unless `BLOB_CHAT_THINKING=1` is set.

Normal replies begin appearing in the `Blob>` terminal as Nebius streams them. Tool calls, reasoning tags, and emote tags stay hidden. Reminder and current-weather requests wait for a confirmed tool result; Blob shows that result directly and never reports an unexecuted reminder as set. If the provider does not support streaming, Blob falls back to a complete response.

Current weather comes from wttr.in. Name a city to query that city; without one, wttr.in estimates the location from the backend's IP address. Blob reports that forecasts are unavailable rather than showing current conditions for a future date.

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
│   │   ├── blob/             # State machine and slime motion
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
