# Privacy model

Blob stores conversation memory in a local ChromaDB database. New installations use
`~/.blob/memory/chromadb/`; installations with an existing
`backend_python/data/chroma_db/` continue using that database. Set
`BLOB_MEMORY_DB_PATH` to select a different directory. The LLM runs through the
Nebius API: normal chat sends the user's message, recalled memories, and the
current context to that service. Blob does not currently offer a local LLM mode.

## Screen capture

The `screen_capture` skill runs only when called. It checks the active window
against `backend_python/data/blacklist.yaml` before capture and again before
OCR. The privacy shield also suppresses screen context and new episodic memory
while a blacklisted window is active. `gnome-screenshot` and `grim` can write a
temporary PNG during capture; Blob loads and removes that file immediately.
XDG portal screenshot support is not implemented yet; Blob uses the listed
backends without issuing an unused portal request.
Window detection depends on platform support; the Linux implementation uses
`xdotool`, so blacklist detection may be unavailable on some Wayland desktops.

The OCR text can be sent to Nebius as part of a tool observation. Screen
captures are not saved to ChromaDB directly, but user and assistant messages
about a screen capture can enter episodic memory after the shield is inactive.

## Camera and face enrollment

The camera is available by default and opens only for an explicit request to
open or scan it, or an explicit `/camera` command. Set `BLOB_CAMERA_ENABLED=0`
and restart the backend to disable camera access. `/camera scan`
returns counts of faces and full-body detections and any matching enrolled
names; it does not send pixels to Nebius or write frames to chat memory.

`/camera enroll <name>` requires the person's consent and writes normalized
grayscale face crops under `~/.blob/faces/` (or `BLOB_FACE_DB_PATH`). Blob sets
directory permissions to `0700` and sample and index permissions to `0600`.
`/camera forget <name>` removes that person's samples. `/camera list` shows
enrolled names. The matching method is OpenCV LBPH with a conservative distance
threshold; false matches and missed matches remain possible. Do not use it to
grant access or make consequential decisions.

## Data removal

Stop Blob before manually removing its local data directories. Deleting the
ChromaDB directory erases local conversation memory. Use `/camera forget <name>`
to delete one enrollment, or remove the face directory to delete all enrolled
samples. Backups and copies made outside Blob must be removed separately.

## Installed skills

Dropped skill files are validated and copied to `~/.blob/skills/` by default.
Their commands run without a shell, with an executable allowlist, a 10 second
timeout, and a 4,000 character output cap. This is a command policy rather
than an operating system sandbox. A skill with read or network permissions can
still access data allowed to the Blob process, so install only trusted files.
When the LLM calls a skill, its text output is sent to Nebius as a tool
observation and may also be summarized into local conversation memory.
