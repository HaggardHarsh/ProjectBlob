# Desktop lifecycle and privacy controls

## Run at desktop login

Install the backend (`make backend-install`), build the overlay (`make frontend`),
then run `make desktop-install` in this checkout. Linux with a systemd user manager
is required. The installer writes:

- `~/.config/systemd/user/blob-backend.service`
- `~/.config/systemd/user/blob-overlay.service`
- `~/.config/autostart/blob.desktop`
- `~/.local/share/applications/blob-chat.desktop`

XDG config/data directory overrides are respected. The services reference this
checkout and its current Python interpreter; rerun installation after moving it.
The desktop startup launcher imports display/session variables before restarting
the services. Both services restart on failure with a three-second delay and a
limit of ten starts per minute. They belong to the graphical session: availability
at login, not execution after logout or while powered off. Sleep suspends execution;
overdue reminders run after wake according to the existing reminder worker.
API/network outages are reported by chat; local commands still work.

`make chat` or **Blob Chat** opens an independent client. Closing it or using `/quit`
disconnects chat without shutting down the backend. The client reconnects its event
stream after backend restart; a failed action is never automatically resent because
it could already have executed. Session conversation context lasts for the backend
process; personal memory survives its restart. Streamed previews remain available in
foreground backend mode; the reconnecting client displays completed replies.
Notifications are delivered to connected clients; this version does not replay
notifications that arrived while all chat clients were closed.

The overlay sleeps when disconnected and shows its existing blindfold while privacy
is active. Right-click toggles manual pause; double-click opens chat. On desktops with
an X11 tray, left-click opens chat and right-click toggles pause. Opening a terminal
from the overlay requires a supported terminal launcher. The desktop application
launcher and `make chat` work independently of the tray.

Useful local commands:

```bash
venv/bin/python -m blob.client --status
venv/bin/python -m blob.client --send '/privacy status'
systemctl --user status blob-backend blob-overlay
systemctl --user restart blob-backend blob-overlay
journalctl --user -u blob-backend -u blob-overlay
systemctl --user stop blob-overlay blob-backend
```

To disable login startup, disable both user units and remove the `blob.desktop`
autostart entry (or turn it off in your desktop's startup settings). The installer
supports `--stage-dir /tmp/blob-desktop-review` to render files without installing
or starting anything. Backend standard output is discarded in service mode so chat
transcripts do not enter the journal. Operational errors use standard error.

## Privacy controls

Settings are saved atomically under `~/.blob/privacy.json` with mode 0600 in a
private directory. `BLOB_PRIVACY_SETTINGS_PATH` selects another private location.
All changes are explicit local commands; models cannot change these settings.

`/privacy pause` persists manual pause, cancels active/queued conversation work,
and clears recent conversation and recalled context. Capture, camera operations,
cloud requests and new personal/document/result writes are blocked. Local reminders
continue. Listing and deletion commands remain usable; screen/camera operations and
skill installation remain blocked. Resume with `/privacy resume`; a blacklisted
active window can still keep the automatic screen shield active.

`/awareness on|off|status|clear` controls automatic local screen observation. It is
off until enabled explicitly. Activity briefs expire and do not become personal
facts. Unknown or sensitive windows block capture; arbitrary titles and raw OCR
are excluded from automatic cloud context. Native Wayland windows require the
local GNOME bridge and a desktop login after installation. See
[screen awareness](screen_awareness.md) for setup, content filtering, and limitations.

The automatic window shield retains its narrower meaning: block screen capture
and personal/result storage. Manual pause applies to the whole assistant. Existing
data remains stored until explicitly deleted. An HTTP request already transmitted
cannot be recalled; cancellation closes pending model requests, but a synchronous
local operation may take time to finish/release hardware. Its output is discarded,
and queued storage writes check the current privacy generation before committing.
This is not provider-side deletion, disk encryption, or secure erasure of backups.

`/privacy cloud off` blocks model requests and model discovery, including background
consolidation, and blocks the web search, page reader and browser tools. An idle
browser also closes on pause, cloud-off, or browser-skill revocation. Use direct
`/skills`, `/reminders`, `/camera`, `/files`, `/results` and
`/memory` commands locally. The weather skill contacts wttr.in separately; disable it
with `/privacy disable weather` to block that skill as well. `/privacy cloud on`
enables cloud inference but does not resume a manual pause. When enabled, normal
messages, recalled memories, tool observations and selected document content can
be shared with Nebius. Fully local conversational inference is not implemented.

## Approved folders and command isolation

`/privacy allow "/path/with spaces"` approves an existing, specific folder.
`/privacy folders` shows approvals. `/privacy revoke "/path/with spaces"` removes
one. Approvals start empty; approving a home root, system root, or credential
directory is rejected. File search resolves paths, skips credential folders and
does not return symlinks that escape approved roots.

Built-in Git/shell tools and installed YAML command tools use Bubblewrap. The
namespace contains system executables/libraries, minimal `/proc` and `/dev`, temporary
scratch space, and approved folders mounted read-only. Host network access is
unshared, environment variables (including API keys) are cleared, and common secret
files/directories and Git repository config are masked. Curl command skills are
blocked; trusted built-in weather has its own bounded HTTP path. The existing
command allowlist and output/time limits remain in force. Bubblewrap setup errors
never trigger unrestricted fallback. Systems that disallow user namespaces must
enable a supported isolation runtime before these command tools can operate.

Folder approval grants access to other files inside that folder; it is not a
content-based secret detector. Symlink targets outside the mounted folders are
unavailable. Applications should keep secrets outside approved data folders.
Dropped attachments and installed skill definition files are explicitly selected
inputs; Blob's own storage remains managed by trusted backend code.

`/privacy disable <tool-name>` and `/privacy enable <tool-name>` persist revocations.
Disabled tools disappear from model tool listings and are rejected at execution.

## Personal memory

`/memory` lists up to 50 records per tier, with IDs and bounded excerpts.
`/memory episodic`, `/memory middle`, and `/memory semantic` select one tier.
`/memory show <tier> <id>` reads an exact stored record locally.

`/memory forget <tier> <id>` removes that record. For grounded facts it also removes
source episodes containing the exact quoted statement and facts derived from those
episodes. This prevents startup backfill or delayed consolidation from recreating
the forgotten fact. It can remove unrelated statements from the same episode.
`/memory forget all` deletes all three personal tiers and the user search index.
Either deletion clears the current conversation's recalled context and cancels
in-flight work that might store or reuse stale memory.

Saved documents (`/files forget`), generated answers (`/results forget`), reminder
messages (`/reminders cancel`) and enrolled faces (`/camera forget`) are separate
stores. Generated answers may retain earlier user-context snapshots; deleting
personal memory does not delete those results. Existing backups are not erased.

## Local API credentials

Every RPC requires the per-user token from `~/.blob/ipc.token` (0600).
`BLOB_IPC_TOKEN_PATH` overrides it; the parent directory must be private (0700).
The Python chat client and C++ overlay read it locally and send it as gRPC metadata.
The token never enters model prompts. TCP binding is restricted to loopback; private
Unix sockets are also supported through `BLOB_IPC_ADDRESS`. Both clients must use
the same address/token settings. This protects access by other users, not malware
already running as your user. The loopback interface is not intended for LAN use.
