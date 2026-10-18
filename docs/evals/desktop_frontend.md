# Desktop frontend verification

The frontend keeps its procedural slime character and uses terminal chat. No
separate frontend chat or settings window is created.

The renderer, attachment IPC, headless overlay startup and reduced-motion/settings
persistence checks cover the upgraded frontend. Character reference images and
motion clips use the actual renderer. The prior backend regression run passed
578 tests with 46 dependency deprecation warnings; the panel removal changes only
C++ code, tests and documentation.

The existing Linux desktop preview verified the rendering path without reading
user screen content or making provider requests. The current frontend retains
its authenticated IPC, privacy mask, terminal launcher, position restoration,
size options and reduced-motion support. Native Wayland positioning still depends
on compositor support; this installation uses the existing X11/XWayland route.

See [controls and reproduction](../desktop_frontend.md).
