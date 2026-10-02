# Privacy model

Blob stores conversation memory in a local ChromaDB database. New installations use
`~/.blob/memory/chromadb/`; installations with an existing
`backend_python/data/chroma_db/` continue using that database. Set
`BLOB_MEMORY_DB_PATH` to select a different directory. The LLM runs through the
Nebius API: normal chat sends the user's message, recalled memories, and the
current context to that service. Blob does not currently offer a local LLM mode.

## User-selected attachments

The overlay forwards only files you drop onto Blob. Dropping files triggers
analysis in the backend terminal and shares PDF text excerpts and, when a vision
model is available, resized images or selected PDF page images with Nebius.
The backend prints this before analysis. Follow-up questions in the terminal
reuse the attached files and can send new excerpts or images to the provider.
PDF extraction, rendering, and fallback OCR happen locally. Blob saves exact
source copies in `~/.blob/documents/` (or `BLOB_DOCUMENTS_DIR_PATH`) and does not
move or modify originals. Private copies retain their source metadata locally;
image payloads sent to the provider omit original metadata.

Attachment contents and answers are kept outside automatic episodic storage and
personal memory consolidation. Recent questions, filenames, and replies remain
in session context. `/files` lists the current files, `/files remove <number>`
detaches one, and `/files clear` detaches all files. Exiting the backend clears
the active selection and session context, while saved source copies and a local
SQLite index of filenames, original paths, checksums, and bounded source excerpts
survive. Questions matching saved filenames or excerpts can reopen sources and
send selected content to the provider; Blob prints a notice when reopening.
`/files saved` lists IDs, `/files open <id>` explicitly reopens one, and
`/files forget <id|all>` deletes saved copies and indexed excerpts, detaches
those files, and clears recent conversation context. It leaves originals intact.
Detaching keeps the saved copy available for a later relevant question. Stored
sources and the index use mode 0600 inside private directories (0700), with a
20-file / 200 MB limit. These are local plaintext files, not encrypted storage.
The screen privacy shield controls
screen capture and memory storage; explicitly selected attachments can still be
sent and saved to the document library while it is active.

## Screen capture

The `screen_capture` skill runs only when called. It checks the active window
against `backend_python/data/blacklist.yaml` before capture and again before
OCR. The privacy shield also suppresses screen context and new episodic memory
while a blacklisted window is active. `gnome-screenshot` and `grim` can write a
temporary PNG during capture; Blob loads and removes that file immediately.
On Wayland, Blob first asks the XDG screenshot portal for a capture. The desktop
may show a permission dialog. If the portal is unavailable, Blob can try the
listed command-line backends. If the user cancels or the desktop denies the
request, Blob stops without trying another capture path.
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
Expired middle-term memories are deleted automatically; saved conversation
episodes remain in the local archive until the database is removed.

## Installed skills

Dropped skill files are validated and copied to `~/.blob/skills/` by default.
Their commands run without a shell, with an executable allowlist, a 10 second
timeout, and an 8,000 byte output cap applied while reading output. Built-in
command tools use the same policy. Git mutation and external execution options,
unsafe find actions, and clock setting are rejected. This is a command policy rather
than an operating system sandbox. A skill with read or network permissions can
still access data allowed to the Blob process, so install only trusted files.
When the LLM calls a skill, its text output is sent to Nebius as a tool
observation and may also be summarized into local conversation memory.

`/skills` and `/reminders` commands run locally without calling Nebius. Their
results can appear in recent session context for subsequent chat. The last 30
skill runs retain only the tool name, status, duration, and invocation source;
raw arguments and results are not included in this execution history.

## Scheduled reminders

Reminder messages, IDs, due times, and repeat intervals are stored locally in
`~/.blob/reminders.sqlite3` (or `BLOB_REMINDERS_DB_PATH`), separately from ChromaDB.
The database file is private (`0600`); newly created parent directories use
`0700`. Direct `/reminders` commands do not send their contents to the provider.
Natural-language reminder requests use the normal cloud chat path. Reminders
are created or changed only on an explicit request. Cancelling one deletes its
record; completed one-time reminders are removed rather than archived.

Blob cannot notify while its backend is closed. On startup it delivers overdue
reminders once, with their original due time, and advances repeating reminders
past missed intervals. A due record is removed or advanced before notification
to prevent duplicate delivery; a process crash between that commit and printing
can lose that notification. Stop Blob and remove the reminder database to erase
all reminder records.
