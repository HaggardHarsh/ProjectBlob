# Automatic screen awareness

Blob can maintain limited awareness of the user's current task without an explicit
screen request. `/awareness on` opts in; `/awareness off` stops observation and clears
the brief. The setting lives in the private privacy JSON and survives restarts.
`/awareness status` shows the brief and operational state locally; `/awareness clear`
clears context without turning observation off. These commands work while cloud
assistance is off or privacy is paused. Manual pause blocks observation regardless
of the awareness setting. Disabling the `screen_capture` skill also blocks it.

## Observation and conversation

The background worker polls window metadata once per second, waits two seconds for
a new active window to settle, and captures that window every 30 seconds. Identical
frames skip repeated OCR. OCR runs locally in a bounded worker pool. The last activity
brief exists only in memory and expires after 90 seconds, using a monotonic clock.
`BLOB_SCREEN_SAMPLE_INTERVAL_SEC` (5–300) and `BLOB_SCREEN_CONTEXT_TTL_SEC` (10–300)
override these defaults.

Normal chat receives a tentative activity/category and up to four recognized topics
from a fixed vocabulary. For example, “Reading or studying in a browser. Detected
topics: voltage divider, resistance.” Raw OCR, arbitrary window/document titles,
filenames, personal identifiers, and pixels are absent from this automatic context.
This additional fixed-vocabulary boundary prevents unknown private text from becoming
a cloud summary even when local pattern-based redaction does not recognize it.
It is coarse task awareness, not a full visual interpretation or exact exercise.

“Help me with this” uses the current brief ahead of an old attached PDF. Blob starts
with a general explanation of a recognized concept; it does not invent the unseen
exercise's values or code. Explicit requests to read the screen still capture fresh
evidence through the separate screen skill, applying local redaction before sending
filtered text. They may require the desktop portal's permission dialog.

Switching to the terminal titled **Blob Chat** keeps the prior task's brief until
expiry. Reopen existing chat clients to load the title change. Other focus changes,
sensitive windows, lock/overview screens, unknown window identity, worker shutdown,
privacy pause, or disabling observation clear/invalidate it. Captures are checked
again after OCR; changed focus/settings discard in-flight results. Privacy cancellation
stops a sample without permanently stopping the observer after resume.

## Privacy boundaries

Capture is blocked for sensitive app/window patterns, including password managers,
private browsing, banking/payment screens, inboxes, common messaging apps, credential
files, and the configurable `backend_python/data/blacklist.yaml`. Unknown window
metadata fails closed. OCR containing credential/payment/private-message markers is
discarded. Other text has identifiable email/URL/long-number patterns and labeled
personal-information lines removed. These are conservative heuristics with possible
false positives, not universal detection of every kind of private information.

Automatic observation makes no cloud calls, performs no model-driven summarization,
and writes no screen history, documents, or personal facts. The activity brief may
be included in a normal cloud chat request when cloud assistance is enabled. Normal
chat questions/replies remain subject to the existing conversation-memory behavior;
a reply mentioning a recognized topic may therefore appear in conversation history.
The observer does not promote screen-derived information into personal memory.
Explicitly typed messages and selected attachments use their existing data-sharing
rules; screen filtering does not rewrite those intentional inputs.

## Supported desktops and setup

GNOME Shell 45–50 supports native Wayland windows through the bundled extension:

```bash
make awareness-install
# Log out/back in once so GNOME discovers the new extension.
venv/bin/blob-chat --send '/awareness on'
venv/bin/blob-chat --send '/awareness status'
```

The installer copies the reviewed extension and adds only its UUID to enabled
extensions. It does not restart the desktop. GNOME keeps loaded extension modules
cached; changes may require another desktop login. The extension is absent from lock
screen session mode. It provides local metadata and active-window images via the
user's session bus; it has no network path. Capture requires a per-user runtime token
stored as `0600` in `$XDG_RUNTIME_DIR/blob-awareness/token`, outside model context.
It checks focus/lock state before and after capture and returns a bounded PNG in
memory, without writing screenshot files.

Linux X11 uses the existing window monitor and `gnome-screenshot -w`; that tool
requires a private temporary PNG, deleted after reading. Automatic capture never
falls back to the full desktop or opens repeated portal dialogs. Other Wayland
compositors and Windows ambient capture are currently unavailable; status reports
missing/unverified observation. Install the local OCR backend described in README.

## Validation

The backend tests cover redaction, fixed-vocabulary boundaries, TTL, focus changes,
paused/off/disabled states, mid-OCR privacy changes, cancellation/resume, duplicate
frames, deictic chat routing, and the actual outgoing prompt and memory attribution.

The [native desktop report](evaluations/awareness_desktop_live.json) uses a separate
headless GNOME session, virtual monitor, synthetic GTK windows, real active-window
captures, and real local OCR. No real user screen or cloud model is used:

```bash
dbus-run-session -- venv/bin/python tools/validate_awareness_desktop.py \
  --report /tmp/blob-awareness-desktop.json
```

The [Super chat report](evaluations/awareness_chat_live.json) uses scripted synthetic
screen/OCR inputs and isolated stores with real Nebius chat calls. It checks recognizing
activity without a user declaration, explaining a topic on implicit help, excluding
private strings from provider requests, avoiding tools and personal-fact writes, and
refusing to guess after a sensitive window invalidates the brief:

```bash
venv/bin/python -m blob.evals.screen_awareness --report /tmp/blob-awareness-chat.json
```

Desktop login activation must be checked in the user's session after its next login.
The native bridge/OCR path has been exercised on GNOME 50; other declared GNOME versions
use the same API but have not all been manually tested.
