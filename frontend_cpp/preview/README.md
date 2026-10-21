# Blob character review

These files are local previews from the SDL renderer. The running overlay draws the
character from code; it does not load these images.

The pale jelly shell, asymmetric blue core, glossy highlights, and broad pinched
eyes follow the supplied slime reference. Emotions use distinct eye curves,
postures, and mouth shapes, with smooth transitions and reduced-motion support.

- `key_poses.png`: twelve main expressions on light and dark backgrounds.
- `character_sheet.png`: all reference poses and two mixed expressions.
- `desktop_emotions.png`: eight emotions at the actual 132 × 116 drawing size.
- `interaction_poses.png`: resting, cursor-following, and teasing with the privacy mask visible.
- `thinking_motion.gif`, `melting_motion.gif`, `celebration_motion.gif`: motion clips.
- `icon_sizes.png`: neutral pose at 512, 128, 64, and 32 pixels.
- `neutral_transparent.png`: isolated neutral pose with transparency.

To regenerate after a frontend build:

```sh
venv/bin/python frontend_cpp/tools/build_preview.py
```
