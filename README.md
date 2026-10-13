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
- **Automatic Screen Awareness** — Opt-in local active-window OCR, with a short-lived activity brief and sensitive-screen filtering. No background model calls or screenshot history.
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
| **Chat / text document model** | NVIDIA `nvidia/nemotron-3-super-120b-a12b` via Nebius |
| **Memory model** | NVIDIA `nvidia/Nemotron-3_5-Lightning` via Nebius |
| **Vision model** | `zai-org/GLM-5.3-Flash` via Nebius |
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

Chat at the backend's `Blob>` terminal prompt. The small desktop slime shows emotions and accepts dropped files. Drag it to move it; click for a little jiggle. Right-click Blob or its optional X11 tray icon to toggle privacy pause. Double-click Blob or left-click its tray icon to open a reconnecting chat terminal. Drop a `.skill.yaml` file onto Blob to install it.

### Always-on desktop mode and privacy controls

After installing the backend and building the frontend, run `make desktop-install`.
This installs per-user Linux services and desktop login startup, starts Blob, and
restarts either component after a crash. Closing a chat terminal leaves the backend,
overlay, and reminders running. Use the **Blob Chat** application launcher or
`make chat` to reconnect. Without installing startup, `make run-daemon` starts an
independent backend and `make chat` connects from another terminal.

The daemon delivers replies and reminder notifications through authenticated local
IPC. It does not archive printed chat in the system journal. A private local token
protects every RPC; the server accepts only loopback or Unix-socket addresses.

```text
/privacy status
/privacy pause
/privacy resume
/privacy cloud off
/privacy cloud on
/privacy allow /home/you/Documents/study
/privacy folders
/privacy revoke /home/you/Documents/study
/privacy disable weather
/privacy enable weather
/memory
/memory show middle <id>
/memory forget middle <id>
/memory forget all
```

Privacy pause persists across restarts and blocks new cloud requests, screen capture,
camera work, and new memory/source/result writes. It cancels active chat requests and
clears recalled conversation context. Local reminders continue; local listing and
deletion commands remain available. Cloud-off mode permits direct local commands
while blocking model inference. Content already sent to a provider cannot be recalled.

File search starts with no approved folders. Command skills require approved folders
and Linux Bubblewrap (`bwrap`); if isolation is unavailable they remain blocked.
Commands receive read-only approved folders, a clean environment, and a private
network namespace. Common credential directories, `.env` files, and repository Git
configuration are masked. Explicitly dropped attachments are separate user selections
and do not require broad folder approval. Cloud assistance still sends messages,
recalled context, and selected file content to Nebius when enabled.

Personal memory commands run locally. Forgetting a fact also removes archived source
episodes containing its exact quote and their derived facts, preventing recreation
on restart; this can remove other facts from those same episodes. `/memory forget all`
clears personal memory and the current conversation context. Documents, generated
results, reminders, and face enrollments retain their separate deletion controls.

See [desktop lifecycle and privacy controls](docs/desktop_privacy.md) for service
management, limits, and troubleshooting.

### PDF and image attachments

Drag PDFs or images onto the desktop Blob. It prints a brief analysis in the backend terminal, then keeps those files available for follow-up questions at `Blob>`. Ask "Explain page 12" or "Summarize pages 3-5" directly in the terminal. Dropping additional files adds them to the current session. Supported formats are PDF, PNG, JPEG, and WebP, with up to four attached files, at most 20 MB each and 50 MB combined. PDFs can contain up to 100 pages.

You can also paste a file path at the beginning of a terminal message:

```text
"/home/you/Pictures/Photo from Tuesday.jpeg" Describe the people in this picture
```

Quoted paths, terminal-escaped spaces, and unquoted spaces before a supported file
extension are accepted. Multiple leading paths select multiple files. The selected
files stay available for follow-ups such as “What about the other person?” and
“What are they wearing?” Ordinary chat and email drafts still use normal chat.
Image descriptions use the configured vision model; a bare filename is not visual
evidence. Blob can describe visible people, but does not guess their identities
from faces or assume a pictured person is you from a remembered nickname.

Use `/files` to list attached files, `/files remove <number>` to detach one, or `/files clear` to detach all files. Explicit requests such as reminders, camera commands, and screen capture continue to work while files are attached. The active selection lasts until detached or the backend restarts.

Keeping files attached does not turn ordinary terminal chat into file analysis.
You can ask what Blob can do or request an email draft without detaching your PDF.
Refer to a file, page, exam timetable, or the immediately preceding document answer
when you want file-based help. To draft from a source, say “Draft an email using the
attached PDF.” Blob can write drafts in chat; sending requires an available sending tool.

Blob also saves private local source copies in `~/.blob/documents/` (override with `BLOB_DOCUMENTS_DIR_PATH`). After a restart, ask about your exam timetable or name a saved document: Blob searches filenames and extracted excerpts, reopens relevant sources, and answers with page references. This also works if the original file moved or was deleted. Search uses bounded extracted text and filenames; text outside previous excerpts and visual details without OCR might require naming the file or opening it explicitly. The library holds up to 20 documents / 200 MB; storage failures are reported in the terminal and leave the current analysis usable. Files dropped before this persistence feature must be dropped again once.

Use `/files saved` to list saved document IDs, `/files open <id>` to reopen one, and `/files forget <id>` or `/files forget all` to delete saved source copies. Original files remain untouched. Forgetting a source removes source-only overviews from the current conversation while preserving completed work and unrelated chat. Detaching a file keeps its saved copy; a later question about it can reopen it.

The backend extracts PDF text locally and includes filenames and page numbers as source references. File analysis budgets excerpts, page labels, and images together within `BLOB_MAX_PROMPT_BYTES` (32,000 by default). Long documents and wide page ranges use relevant page excerpts; the supplied context identifies omitted pages and text. Image inputs and rendered PDF pages use `zai-org/GLM-5.3-Flash` by default because the main Nemotron Super model is text-only. Set `BLOB_VISION_MODEL` to another exact model ID, `auto` for provider discovery, or `off` to use local OCR only. In auto mode, image analysis reuses the chat model when the provider reports image-input support. Ordinary chat and document requests without images use `BLOB_MODEL_NAME`.

Visual requests send resized images, including up to three selected PDF page images per document and four images total. When no vision model is available, Blob can read text in images and scanned PDFs using the optional `backend_python[ocr]` installation. OCR alone cannot describe objects, colors, or diagrams. Unreadable, damaged, password protected, and oversized files produce an error instead of an invented explanation.

If an image request times out after 30 seconds, Blob retries the same bounded image
context once with `openbmb/MiniCPM-V-4_5` through the same provider, with a 60-second
deadline. Text-only requests keep their normal model. Set
`BLOB_VISION_FALLBACK_MODEL=off` to disable this backup or set another exact vision
model ID. Privacy pause and cloud-off stop both routes.

Dropping files, opening saved files, and asking related questions shares selected file content with your cloud AI provider. The backend prints a notice on drops and reopening saved files. PDF parsing and OCR happen locally; original files are left in place. Source copies and extracted excerpts are stored separately from personal memory. Completed answers to your file questions are saved as generated results, with their original request, source names and checksums, and creation time. These are earlier generated work, not user-stated facts or independently verified document evidence. Automatic file-drop overviews are not saved as results.

Timetables, notes, summaries, and other file answers survive `/files forget` and backend restarts. Use `/results` to list them, `/results show <id>` to display an exact saved answer without the AI provider, and `/results forget <id|all>` to delete generated work. After deleting a datesheet PDF, "Show my timetable" can repeat the completed timetable, and "What exam do I have on Monday?" can use its saved rows. The original PDF is needed for details that were never included in a saved answer. A revised source takes priority over work made from an older copy. Fresh screen requests retain their usual priority.

Generated results live in `document_results.sqlite3` inside `BLOB_MEMORY_DB_PATH`. They retain up to 100 answers / 2 MB, with a 128 KB limit per answer; quota and storage failures are reported without silently evicting older work. Follow-up prompts use bounded excerpts, while `/results show` displays the complete stored answer. The privacy shield pauses automatic result writes. Regenerating the same timetable updates its saved result; a countdown question creates a separate answer. Earlier versions did not save completed file answers, so results lost before this upgrade must be made again.

Your own terminal messages about files are saved to personal memory before analysis, unless the privacy shield is active. Explicit subject lists and programs are available immediately after a restart, without waiting for consolidation. File questions include the current saved user statements, and your subjects help select relevant PDF pages. A newer subject list replaces the old list; explicit subjects take priority over program defaults. Blob asks for the missing subjects or program when it cannot identify your exams. `/files forget` removes document copies, not separately saved user statements.

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

“Can you recognize me” also runs a real local camera scan, without a model call.
An immediate “yes it is” or “try again” repeats the last camera check; an unrelated
turn clears that retry context. The same requests work with cloud assistance off,
while manual privacy pause still blocks camera access. Blob reports the camera
tool's actual result rather than narrating an unexecuted attempt.

Enrollment requires the person's consent and captures at least eight clear frames with one face visible. A scan reports face and full-body detections and matches enrolled faces by name. Recognition uses OpenCV's LBPH model; it can make mistakes, especially with poor light or a changed appearance, so it should not be used for authentication. The camera opens only for a request and is released afterward. Frames are not sent to the LLM or stored in chat memory. Enrollment stores cropped grayscale face samples under `~/.blob/faces/` (or `BLOB_FACE_DB_PATH`); `/camera forget <name>` deletes that person's samples.

`/camera status` opens the webcam long enough to verify that a frame can be read. Webcam access is separate from Wayland screen sharing. A scan reports detections, not a general visual description of the camera scene.

### Screen sharing

Say "show me my screen" or use `/screen`. On Wayland, Blob asks the desktop screenshot portal for one capture. Accept the desktop's permission dialog if it appears. Blob extracts text from the screenshot when the optional OCR dependency is installed:

```bash
pip install -e 'backend_python[ocr]'
```

Restart Blob after installing OCR. Explicit screen requests use one capture, including requests for help with material on the screen. Blob filters extracted text locally and supplies a generic app category rather than a document/window title; the full screenshot is not sent to the cloud. Sensitive content may cause the entire request to be excluded. If capture or OCR fails, Blob reports that directly. File search runs only for an explicit request to find a file; it does not search the visible screen.

To let Blob recognize your activity without a capture request, use `/awareness on`.
On GNOME Wayland, first run `make awareness-install` and log out/back in once to
load the local GNOME extension. Automatic observation captures only the active
window, waits two seconds after focus changes, and samples every 30 seconds.
Local OCR and filtering produce a brief such as “Reading or studying in a browser.
Detected topics: voltage divider, resistance.” Only fixed activity/topic labels
enter normal chat; automatic observation never uploads screenshots or OCR excerpts.
Try “What am I working on?” or “Help me with this.”

The brief expires after 90 seconds and is cleared on sensitive/unverified windows,
privacy pause, or awareness-off. Switching to the terminal titled **Blob Chat**
keeps the recent brief until expiry. Use `/awareness status`, `/awareness off`, or
`/awareness clear` to inspect or control it locally, including when cloud assistance
is off. Observation is disabled on new installations until explicitly enabled;
the setting persists across restarts. See [screen awareness](docs/screen_awareness.md)
for supported desktops, privacy boundaries, and validation.

Screen requests take priority over attached and saved documents. You can say "The stuff on my screen is hard; dumb it down for me" while an exam PDF is attached, or correct Blob with "No, the stuff on my screen, not the PDF." Each request captures the current screen again. There is no need to detach files first; an unsuccessful capture reports the actual problem instead of answering from an unrelated PDF.
Blob also uses RapidOCR when it is installed locally; this can provide OCR without loading PyTorch.

### Persistent memory

New installations store ChromaDB data under `~/.blob/memory/chromadb/`, independent of the launch directory. Existing `backend_python/data/chroma_db/` data remains in use automatically when present. Set `BLOB_MEMORY_DB_PATH` to choose another location. Blob has three active memory tiers: the most recent 12 conversation messages in the current session; middle-term quotes about ongoing projects and future events; and long-term quotes about stable preferences, hobbies, and identity. Consolidation selects numbered sentences from the user's original wording. Middle-term memories expire after 30 days by default, or after the day of a recognized dated event. Expired middle-term records are deleted; the original conversation episodes remain in the local archive. Long-term facts remain until corrected or deleted. When consolidation selects a new statement about a recognized topic, including favorites, names, hobbies, and likes, it supersedes older active facts. Other corrections still rely on the newer conversation context and may need manual review. Older model-written summaries are marked unverified in prompts until they are removed. When the privacy shield is active, Blob omits screen context and pauses episode storage. The Nebius chat API still receives the current user message and recalled memory context during normal chat; avoid sharing sensitive information with the cloud model.

To replace old semantic summaries, stop Blob and create a JSON file containing a list of exact sentences from the user's side of saved conversations. Run `PYTHONPATH=backend_python python -m blob.memory.migrate_legacy --facts-file /path/to/reviewed-facts.json` from the repository root. The command checks every sentence against the original episodes, backs up the complete ChromaDB directory under `memory_backups/` beside the database, removes only ungrounded semantic entries, and keeps the episodes. An empty list removes all old semantic summaries while preserving newer grounded facts. Restart Blob after migration.

Memory search runs locally and sends only a bounded view of relevant matches to Nebius. The default embedding distance cutoff rejects weak matches; recent access does not make an old memory more relevant. Ordinary chat recalls conversation episodes from the last seven days. Explicit history questions can search the full episode archive. Long records are excerpted around terms in the current question; the full records remain in ChromaDB. Ordinary replies use the user's side of retrieved episodes; Blob's old replies appear only when asked what Blob said. Recent turns are also sent in their original user and assistant roles during the current backend session. Blob uses the computer's local clock for current day and date questions.

Academic declarations use exact user quotes in middle-term memory with a 30-day lifetime. Their current values are retrieved by topic for file questions, even when words such as "Monday" have little similarity to the subject names. Startup recovers these declarations from older saved user conversations when present, preserving their original dates. Earlier attachment chats did not archive user messages, so those missing statements must be shared once again.

To check document memory with isolated temporary storage and synthetic timetables, run `venv/bin/python -m blob.evals.document_memory`. Add `--live --report /tmp/blob-document-memory.json` to test the configured provider model; this sends only synthetic PDF pages and test user statements and uses normal API billing. The evaluation checks restarts before consolidation, corrections, conflicting program information, no matching Monday subjects, and missing personal information.

Add `--saved-work` to test making a timetable, deleting both PDF copies, restarting, replaying the exact saved work, and answering an exam follow-up without source access. `--saved-work --live` uses the configured model for creation and follow-up; the exact replay is local.

Set `BLOB_PROFILE_LATENCY=1` when launching the backend to log how long local preparation and the model call take for each reply. Blob caches the fixed tone preference search between memory changes, so repeat messages avoid that extra lookup.

Blob uses NVIDIA `nvidia/nemotron-3-super-120b-a12b` for chat, tool planning, text-only document answers, and follow-ups on saved work. `zai-org/GLM-5.3-Flash` handles image inputs and rendered PDF pages. Set `BLOB_MODEL_NAME` and `BLOB_VISION_MODEL` in `.env` to override these roles. If you select `nvidia/Nemotron-3_5-Lightning` for chat, Blob uses its faster non-reasoning chat mode unless `BLOB_CHAT_THINKING=1` is set. Super uses the provider's normal reasoning mode.

Background memory consolidation uses NVIDIA `nvidia/Nemotron-3_5-Lightning` through Nebius, independently of the chat model. It selects numbered user quotes for lasting or expiring memory; the backend stores the original wording and the model's identity locally. Set `BLOB_MEMORY_MODEL_NAME` to override this role. All model routes obey privacy pause and cloud-off controls. Failed memory requests stay pending for a later retry. Model calls use normal provider billing; latency and cost depend on the request.

Run `venv/bin/python -m blob.evals.private_workflow --live --report /tmp/blob-private-workflow.json` for a complete synthetic workflow: NVIDIA memory selection, reopening stores, a personalized PDF study plan, exact replay after source deletion, and a reminder that persists and fires while privacy is paused and cloud access is off. Omit `--live` for the offline version. See [the workflow guide](docs/nvidia_workflow.md) for model roles, report details, and a demo sequence.

Normal replies begin appearing in the `Blob>` terminal as Nebius streams them. Tool calls, reasoning tags, and emote tags stay hidden. Reminder and current-weather requests wait for a confirmed tool result; Blob shows that result directly and never reports an unexecuted reminder as set. If the provider does not support streaming, Blob falls back to a complete response.

Current weather comes from wttr.in. Name a city to query that city; without one, wttr.in estimates the location from the backend's IP address. Blob reports that forecasts are unavailable rather than showing current conditions for a future date.

---

## Skill Pills

### Skill hub and reminders

Blob's skills share typed argument validation, execution deadlines, bounded output,
and a session history of successful and failed runs. Use these terminal commands
to inspect and run them directly, without sending a request to the cloud model:

```text
/skills
/skills reminder
/skills run git_status {}
/skills history
/reminders add 25 Take a study break
/reminders at 2026-10-05T09:00:00+05:30 Get ready for HDL
/reminders every 60 Drink water
/reminders
/reminders snooze <id> 10
/reminders cancel <id>
```

Reminders survive backend restarts in `~/.blob/reminders.sqlite3`; override this
with `BLOB_REMINDERS_DB_PATH`. They support timers, an exact date/time, and repeating
intervals. A date/time without an offset uses the computer's local timezone.
Blob must be running to notify you; overdue reminders appear on the next launch.
Repeating reminders catch up once and resume their cadence. Cancelling a reminder
removes its stored message. Natural requests such as "Remind me to revise HDL
tomorrow at 9 am" and "Cancel my reminder to stretch" use the same runtime.
Chat cannot create or change reminders unless you ask for that action.

Command skills share a read-only command policy. Git branch creation, deletion,
renaming, external diff helpers, and output-file options are rejected. Command
output is bounded as it is read, and screen OCR runs in a worker so the event
loop can keep delivering reminders. Skill execution history contains names,
status, timing, and source, rather than raw arguments or file contents.

### Install a skill

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
