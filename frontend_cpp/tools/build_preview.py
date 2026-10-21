"""Export local character reference sheets and motion clips from the SDL renderer.

Build the frontend first, then run: python frontend_cpp/tools/build_preview.py
Pillow is needed only for this review tool; the overlay renders with SDL2.
"""

from pathlib import Path
import argparse
import os
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont


FRONTEND = Path(__file__).resolve().parents[1]
NAMES = [
    "neutral", "cute_smile", "happy", "very_happy", "excited", "laughing",
    "shocked", "extremely_shocked", "confused", "thinking", "deep_thinking",
    "focused", "working", "listening", "speaking", "angry", "playfully_angry",
    "frustrated", "sad", "crying", "embarrassed", "nervous", "sleepy", "tired",
    "melting", "completely_melted", "recovering", "error", "glitch", "success",
    "celebration", "curious", "suspicious", "proud", "surprised_realization",
    "idea", "waiting", "bored", "happy_confused", "tired_thinking",
]


def character(source: Path, name: str) -> Image.Image:
    image = Image.open(source / f"{name}.bmp").convert("RGBA")
    pixels = image.load()
    for y in range(image.height):
        for x in range(image.width):
            if pixels[x, y][:3] == (0, 0, 0):
                pixels[x, y] = (0, 0, 0, 0)
    return image


def reference_sheet(source: Path, names: list[str], output: Path, columns: int,
                    scale: int, font: ImageFont.ImageFont) -> None:
    tile_w, tile_h = 132 * scale + 24, 116 * scale + 48
    rows = (len(names) + columns - 1) // columns
    page = Image.new("RGB", (columns * tile_w, rows * tile_h), (236, 242, 246))
    draw = ImageDraw.Draw(page)
    for index, name in enumerate(names):
        x, y = (index % columns) * tile_w, (index // columns) * tile_h
        light = index % 2 == 0
        background = (248, 251, 253) if light else (36, 51, 65)
        draw.rounded_rectangle((x + 8, y + 8, x + tile_w - 8, y + tile_h - 8),
                               radius=16, fill=background)
        image = character(source, name).resize((132 * scale, 116 * scale), Image.Resampling.LANCZOS)
        page.paste(image, (x + 12, y + 12), image)
        draw.text((x + 14, y + 116 * scale + 17), name.replace("_", " ").title(),
                  fill=(35, 58, 74) if light else (238, 246, 250), font=font)
    page.save(output)


def motion_gif(source: Path, prefix: str, output: Path) -> None:
    frames = []
    for path in sorted(source.glob(prefix + "_*.bmp")):
        image = character(source, path.stem).resize((396, 348), Image.Resampling.LANCZOS)
        frame = Image.new("RGB", (792, 348), (248, 251, 253))
        ImageDraw.Draw(frame).rectangle((396, 0, 792, 348), fill=(36, 51, 65))
        frame.paste(image, (0, 0), image)
        frame.paste(image, (396, 0), image)
        frames.append(frame)
    frames[0].save(output, save_all=True, append_images=frames[1:],
                   duration=67, loop=0, optimize=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=FRONTEND / "preview")
    parser.add_argument("--build-dir", type=Path, default=FRONTEND / "build")
    args = parser.parse_args()
    binary = args.build_dir / "blob_render_smoke"
    if not binary.exists():
        parser.error("Build the frontend first: cmake --build frontend_cpp/build -j4")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/julietaula-montserrat-fonts/Montserrat-Bold.otf", 16)
    except OSError:
        font = ImageFont.load_default()
    with tempfile.TemporaryDirectory(prefix="blob-preview-") as temporary:
        source = Path(temporary)
        env = {**os.environ, "SDL_VIDEODRIVER": "dummy", "BLOB_PREVIEW_DIR": str(source)}
        subprocess.run([str(binary)], check=True, env=env)
        reference_sheet(source, NAMES, output / "character_sheet.png", 5, 2, font)
        reference_sheet(source, [
            "neutral", "happy", "thinking", "deep_thinking", "working", "shocked",
            "angry", "sad", "embarrassed", "melting", "completely_melted", "celebration",
        ], output / "key_poses.png", 4, 3, font)
        reference_sheet(source, [
            "neutral", "happy", "angry", "shocked", "thinking", "sad", "crying", "embarrassed",
        ], output / "desktop_emotions.png", 4, 1, font)
        reference_sheet(source, [
            "shielded_sleep", "shielded_hover_right", "shielded_hover_left", "shielded_poke", "shielded_teased",
        ], output / "interaction_poses.png", 5, 2, font)
        neutral = character(source, "neutral")
        neutral.save(output / "neutral_transparent.png")
        icons = Image.new("RGB", (920, 610), (239, 245, 248))
        draw = ImageDraw.Draw(icons)
        for size, x, y in ((512, 24, 48), (128, 580, 70), (64, 745, 100), (32, 847, 116)):
            scaled = neutral.resize((size, int(size * 116 / 132)), Image.Resampling.LANCZOS)
            icons.paste(scaled, (x, y), scaled)
            draw.text((x, y + scaled.height + 8), f"{size} px", fill=(35, 58, 74), font=font)
        icons.save(output / "icon_sizes.png")
        for prefix in ("thinking_motion", "melting_motion", "celebration_motion"):
            motion_gif(source, prefix, output / f"{prefix}.gif")
    print(f"Preview ready: {output}")


if __name__ == "__main__":
    main()
