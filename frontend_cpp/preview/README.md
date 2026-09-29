# Blob character review

These files are local previews from the SDL renderer. The running overlay draws the
character from code; it does not load these images.

- `key_poses.png`: twelve main expressions on light and dark backgrounds.
- `character_sheet.png`: all reference poses and two mixed expressions.
- `thinking_motion.gif`, `melting_motion.gif`, `celebration_motion.gif`: motion clips.
- `icon_sizes.png`: neutral pose at 512, 128, 64, and 32 pixels.
- `neutral_transparent.png`: isolated neutral pose with transparency.

To regenerate after a frontend build:

```sh
venv/bin/python frontend_cpp/tools/build_preview.py
```
