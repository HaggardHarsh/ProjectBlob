# Desktop frontend

Blob renders only its animated slime overlay. Chat opens in the existing terminal
client; there is no separate chat or settings window.

The pale blue jelly body has a shaded inner core and broad glossy highlights.
Happy eyes arch, annoyed eyes scrunch into wide tapered lines, surprise stretches
the body and eyes, and sadness slumps with distinct tears for crying. Facial
features remain readable while following the cursor. Incoming expressions lift
the privacy mask onto the forehead while screen protection stays active.

## Controls

- Double-click Blob, press Enter while the overlay is focused, or left-click its
  tray icon to open terminal chat. `make chat` and `blob-chat` also work.
- Drag the body to move it; pokes produce a damped spring wobble and dragging adds
  a small lean. Position survives restarting, with off-screen positions restored
  to a visible display.
- Hover to wake Blob and have him follow the pointer. Wiggle the cursor back and
  forth to tease him; pokes bring a surprised, playful face, with a mock grumpy
  reaction to repeated pokes. He settles again after you leave. These animations
  run locally even while disconnected or paused. During play, the privacy mask
  lifts onto his forehead; screen protection stays active.
- Right-click Blob or its tray icon to toggle manual privacy pause. The visible
  mask reflects backend screen shielding. Use `/privacy status`, `/privacy explain`,
  `/privacy pause`, `/privacy resume`, and `/privacy cloud on|off` in terminal chat.
- `/stop` requests cancellation of active work without undoing completed actions.
- Drop PDFs, images and skill files onto the slime to use their existing backend
  routes. Continue document questions in terminal chat.
- Escape on the overlay closes it, leaving the backend available.

Desktop preferences remain in `$XDG_CONFIG_HOME/projectblob/frontend.conf` or
`~/.config/projectblob/frontend.conf`. Launch with `--scale 0.75..2` or
`--reduced-motion` to adjust appearance without opening another window.
Reduced motion removes body oscillation, shaking, gaze drift, animated particles
and poke/drag wobble while retaining expressions and smooth transitions.

## Build and review

Requires SDL 2.0.18+, Protobuf and gRPC C++ development libraries, with optional
X11 tray support. No font library or font assets are required.

```bash
cmake -S frontend_cpp -B frontend_cpp/build -DCMAKE_BUILD_TYPE=Release
cmake --build frontend_cpp/build --parallel 2
ctest --test-dir frontend_cpp/build --output-on-failure
frontend_cpp/build/blob_overlay --help
frontend_cpp/build/blob_overlay --demo --frames 180
venv/bin/python frontend_cpp/tools/build_preview.py
```

`--demo` cycles expressions without a backend connection or preference writes.
`--frames` bounds a preview run; `--snapshot FILE.bmp` saves the slime window.
Headless checks use `SDL_VIDEODRIVER=dummy`. Pass `--build-dir /path/to/build` to
the preview tool to review a separate build. Character reference images and motion
clips are in `frontend_cpp/preview`.

The renderer uses a double-resolution target, smooth geometry and downsampling.
The overlay input mask scales with its size. High-resolution timing and one frame
limiter replace the previous clock/vsync combination. SDL resources are destroyed
before shutdown. Linux prefers X11/XWayland for overlay positioning; native Wayland
compositor restrictions and the existing non-shaped fallback remain limitations.
IPC remains authenticated. Disconnected actions are rejected; failed writes and
disconnected queues are never automatically replayed.
