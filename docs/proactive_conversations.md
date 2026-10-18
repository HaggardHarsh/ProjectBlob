# Occasional conversations

Blob can offer one short question in a small, temporary speech bubble above the
slime. There is no chat panel, sound, automatic terminal opening, camera access
or microphone listening. Fresh installs and upgrades start with invitations off.

```text
/proactive on
/proactive status
/proactive quiet
/proactive off
```

`quiet` pauses until the next local day. `off` stays off across restarts. Bubble
buttons offer **Reply**, **Quiet today**, and **Mute**; clicking its body dismisses
it. Quiet/mute use authenticated, confirmed setting requests and retry after
reconnection. Reply opens the existing terminal with the invitation visible.
Your answer then continues a normal conversation. Ignoring it produces no nudge.

Cloud assistance must also be enabled independently. Enabling invitations keeps
existing cloud, screen-awareness and privacy choices. Cloud-off, manual privacy
pause and maintenance stop invitations. Local controls work while cloud is off
or privacy is paused. An invalid history disables only this feature, preserving
ordinary chat and historical rate limits.

## Quiet defaults

- At most three attempts in a rolling seven days, never two within 24 hours.
  Normal spacing is randomly chosen between 48 and 84 hours.
- The first hour after startup or chatting is quiet, as are local hours
  22:00–10:00. Toggling off/on never resets historical limits.
- An ignored/dismissed approach waits at least three days; two consecutive
  ignored/dismissed approaches wait at least a week.
- A compatible, visible overlay must be connected. A settled, non-private window
  and a brief input pause are required. Unknown presence, active typing, long
  absence, fullscreen-sized windows, media players, terminals and recognizable
  calls/presentations suppress invitations. Metadata heuristics cannot identify
  every meeting or fullscreen configuration.
- Nothing accumulates during sleep, shutdown or absence. Crashes, provider errors,
  rejected wording and failed display do not cause rapid retries: each attempt is
  reserved durably before inference and counts toward the limits.

These are ceilings. Days without an invitation are normal.

## Topics and privacy

Local rules choose a suitable moment before making any model request. The model
composes one question, at most 160 characters, from a light check-in topic, an
active grounded interest label such as photography, or a recognized topic from
the existing fresh screen-awareness brief with `/awareness on`.

The memory path uses fixed-vocabulary interests, not raw memories, personal names,
old requests, declined tasks, arbitrary project names or sensitive details. The
screen path captures no additional frames and sends no raw OCR, titles or pixels.
Topic cooldowns and hashed word fingerprints reduce repetition across rephrased
openings. Unsafe, tool-shaped, long, repetitive or attention-demanding output is
silently discarded without a generation retry. Generation has no tools. Prompts
and local filters cannot prove that every model output will feel appropriate.

Opting in permits occasional background inference at normal provider rates,
bounded by three attempts a week including failures. Manual chat and existing
memory consolidation are separate operations. Invitations are never stored as
user facts or replayed on reconnect. Only a displayed invitation can enter the
recent session as an actual assistant message when you reply; no fictitious user
request is created. Normal user replies follow existing memory rules.

Operational history is the private `proactive.json` in the configured memory
directory. It contains times, topic identifiers, outcomes and hashed word
fingerprints, not opening text or raw context. Managed snapshots include it.
Disabling invitations retains rate history to prevent re-enable/restart bursts.

## Desktop and verification

Current [verification evidence](evals/proactive_conversations.json) records the
backend suite, final focused regressions, real model, native focus/rendering,
compiled-overlay delivery/mute and installed-wheel smoke checks.

The first target is Ubuntu/Linux. Idle time comes from GNOME Mutter's IdleMonitor
service; other X11 desktops need `xprintidle`. The existing window monitor/bridge
must provide trustworthy focus metadata. Missing metadata leaves Blob quiet and
appears in `/proactive status`; there is no timer-only interruption fallback.

The native bubble uses Pillow's bundled font and a bounded local bitmap, avoiding
additional SDL font libraries or downloads. SDL's [no-activation hint](https://wiki.libsdl.org/SDL2/SDL_HINT_WINDOW_NO_ACTIVATION_WHEN_SHOWN)
and [X11 window type hint](https://wiki.libsdl.org/SDL2/SDL_HINT_X11_WINDOW_TYPE)
keep it passive on SDL2 and SDL2-compat. Older overlays do not advertise support
and receive no invitations.

```bash
venv/bin/python -m pytest backend_python/tests/test_proactive.py -q
ctest --test-dir frontend_cpp/build --output-on-failure
venv/bin/python tools/validate_proactive.py --binary frontend_cpp/build/blob_overlay --report .runtime/validation/proactive-overlay.json
```

Tests simulate weeks, ignored approaches, concurrent chat, privacy changes during
generation, hidden/disconnected clients, restarts, repetition, short replies,
memory attribution and authenticated controls. The compiled-overlay validator
checks actual image decoding/display receipts and confirmed mute using temporary
stores and no real provider calls. Native smoke checks cover hit areas, expiry,
invalid images and keyboard focus.
The Ubuntu installer CI job also runs the compiled-overlay validator and exports
its report, so delivery and confirmed mute are checked on future builds.

For five real-model openings with synthetic interests/activity, a six-call ceiling
and normal inference charges (no actual desktop observations):

```bash
venv/bin/python -m blob.evals.proactive --report .runtime/validation/proactive-model.json
```

The live evaluation also checks private fixture exclusion and mute. Long-term
timing and conversational quality still need beta observation in real use.
