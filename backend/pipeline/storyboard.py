"""Create a storyboard frame for VLM when Manim render is unavailable."""

from __future__ import annotations

import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from backend.schemas import SceneSection


def create_storyboard_frame(
    scene: SceneSection,
    *,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
) -> str:
    """
    Render a simple inspection frame the VLM (and humans) can review.

    Used when Manim did not produce a real frame, so we still persist
    'what the VLM saw' and keep the debug trail complete.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)

    img = Image.new("RGB", (width, height), color=(12, 20, 18))
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 42)
        body_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 28)
        small_font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial.ttf", 22)
    except OSError:
        title_font = ImageFont.load_default()
        body_font = title_font
        small_font = title_font

    # Accent bar
    draw.rectangle((0, 0, width, 8), fill=(62, 207, 142))
    draw.rectangle((48, 48, width - 48, height - 48), outline=(40, 70, 60), width=2)

    y = 72
    draw.text(
        (72, y),
        "PLAN CARD — not a Manim render (ENABLE_MANIM_RENDER=false)",
        fill=(240, 199, 94),
        font=small_font,
    )
    y += 40
    draw.text((72, y), scene.title[:80], fill=(232, 240, 236), font=title_font)
    y += 70

    draw.text((72, y), "Visual description", fill=(62, 207, 142), font=small_font)
    y += 36
    for line in textwrap.wrap(scene.visual_description, width=70)[:8]:
        draw.text((72, y), line, fill=(232, 240, 236), font=body_font)
        y += 34

    y += 20
    draw.text((72, y), "Animation beats", fill=(240, 199, 94), font=small_font)
    y += 36
    for beat in scene.animation_beats[:6]:
        for line in textwrap.wrap(f"• {beat}", width=68)[:2]:
            draw.text((72, y), line, fill=(200, 214, 208), font=body_font)
            y += 32
        if y > height - 120:
            break

    y = max(y + 16, height - 110)
    draw.text((72, y), "Narration (excerpt)", fill=(155, 176, 166), font=small_font)
    y += 30
    excerpt = scene.narration[:180] + ("…" if len(scene.narration) > 180 else "")
    for line in textwrap.wrap(excerpt, width=72)[:3]:
        draw.text((72, y), line, fill=(155, 176, 166), font=small_font)
        y += 26

    img.save(output_path, format="PNG")
    return str(output_path)
