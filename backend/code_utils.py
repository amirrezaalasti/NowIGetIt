"""Helpers for cleaning and validating Manim Community Edition code."""

from __future__ import annotations

import ast
import re

# Pango lays out Text() at the given font_size in pixels; small sizes get
# uneven letter advances (broken kerning). Render at a safe size, then scale.
# See: https://github.com/ManimCommunity/manim/issues/2844
#
# Separately, Pango/Cairo often underestimates the right side bearing so the
# LAST letter is clipped ("Network" → "Networ"). Pad with NBSPs to widen the
# SVG viewBox, then hide the pad glyphs when Text is split per-character.
_TEXT_KERNING_MARKER = "# _NOWIGETIT_TEXT_KERNING_SHIM"
_TEXT_KERNING_END_MARKER = "# _NOWIGETIT_TEXT_KERNING_END"
_TEXT_KERNING_MIN_SIZE = 48.0
_TEXT_KERNING_SHIM = f"""{_TEXT_KERNING_MARKER}
_ManimText = Text
_ManimMarkupText = MarkupText
_ManimParagraph = Paragraph
_TEXT_KERNING_MIN = {_TEXT_KERNING_MIN_SIZE}
_TEXT_CLIP_PAD = "\\u00a0\\u00a0"  # non-breaking spaces — expand layout width

def _pad_for_clip(text):
    raw = text if isinstance(text, str) else str(text)
    if not raw:
        return raw, 0
    # Don't double-pad if caller already trailing-spaced.
    if raw.endswith((" ", "\\u00a0")):
        return raw + "\\u00a0", 1
    return raw + _TEXT_CLIP_PAD, len(_TEXT_CLIP_PAD)

def _hide_pad_glyphs(mob, n_pad):
    if n_pad <= 0:
        return mob
    try:
        # disable_ligatures=True → one submobject per character (incl. pads)
        if len(mob) >= n_pad:
            for i in range(n_pad):
                mob[-(i + 1)].set_opacity(0)
    except Exception:
        pass
    return mob

def _kerning_safe_text(factory, text, args, kwargs):
    # width/height stretch the SVG and ruin letter spacing / clip glyphs
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("disable_ligatures", True)
    padded, n_pad = _pad_for_clip(text)
    font_size = kwargs.get("font_size", 48)
    try:
        size = float(font_size)
    except (TypeError, ValueError):
        mob = factory(padded, *args, **kwargs)
        return _hide_pad_glyphs(mob, n_pad)
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = factory(padded, *args, **kwargs)
    if internal != size:
        mob.scale(size / internal)
    return _hide_pad_glyphs(mob, n_pad)

def Text(text, *args, **kwargs):
    return _kerning_safe_text(_ManimText, text, args, kwargs)

def MarkupText(text, *args, **kwargs):
    return _kerning_safe_text(_ManimMarkupText, text, args, kwargs)

def Paragraph(*text, **kwargs):
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("disable_ligatures", True)
    padded_lines = []
    for line in text:
        p, _n = _pad_for_clip(line)
        padded_lines.append(p)
    font_size = kwargs.get("font_size", 48)
    try:
        size = float(font_size)
    except (TypeError, ValueError):
        return _ManimParagraph(*padded_lines, **kwargs)
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = _ManimParagraph(*padded_lines, **kwargs)
    if internal != size:
        mob.scale(size / internal)
    return mob
{_TEXT_KERNING_END_MARKER}
"""


def validate_manim_code(code: str) -> tuple[bool, str]:
    """Return (ok, error). Rejects truncated / commentary-polluted outputs."""
    if not code or len(code.strip()) < 40:
        return False, "Code too short or empty"
    if "class " not in code or "Scene" not in code:
        return False, "Missing Scene class"
    if "def construct" not in code:
        return False, "Missing construct()"
    if not re.search(r"^(from |import |class |#)", code.strip(), re.M):
        return False, "Does not look like Python source"
    if re.search(r"\)`\)|\. No \$|Target duration:", code):
        return False, "Contains commentary mixed into code"
    try:
        ast.parse(code)
    except SyntaxError as exc:
        return False, f"SyntaxError: {exc.msg} (line {exc.lineno})"
    return True, ""


def _strip_text_kerning_shim(code: str) -> str:
    """Remove a previously injected shim block (old or new format)."""
    start = code.find(_TEXT_KERNING_MARKER)
    if start < 0:
        return code
    end_token = _TEXT_KERNING_END_MARKER
    end = code.find(end_token, start)
    if end >= 0:
        end = end + len(end_token)
        # Consume trailing newline
        if end < len(code) and code[end] == "\n":
            end += 1
        return code[:start] + code[end:]
    # Legacy shims had no end marker — cut until the next top-level class.
    rest = code[start:]
    m = re.search(r"^class\s", rest, flags=re.M)
    if m:
        return code[:start] + rest[m.start() :]
    # Last resort: drop the marker line only.
    nl = code.find("\n", start)
    return code[:start] + (code[nl + 1 :] if nl >= 0 else "")


def _inject_text_kerning_shim(code: str) -> str:
    """Shadow Text/MarkupText/Paragraph with kerning-safe wrappers.

    Always refresh an existing shim so older jobs pick up clip/kerning fixes.
    """
    code = _strip_text_kerning_shim(code)
    shim = _TEXT_KERNING_SHIM.strip() + "\n"
    match = re.search(r"^from manim import \*[ \t]*$", code, flags=re.M)
    if match:
        insert_at = match.end()
        return code[:insert_at] + "\n" + shim + code[insert_at:]
    return shim + "\n" + code


def clean_manim_code(code: str) -> str:
    """Normalize LLM-generated Manim Community Edition code."""
    if "```python" in code:
        code = code.split("```python", 1)[1].split("```", 1)[0].strip()
    elif "```" in code:
        parts = code.split("```")
        if len(parts) >= 2:
            code = parts[1].strip()

    # Prefer Community Edition import
    code = code.replace("from manimlib import *", "from manim import *")
    code = code.replace("from manimlib import", "from manim import")

    # ManimGL → Community API shims
    code = code.replace("ShowCreation", "Create")
    code = re.sub(r"\bAlwaysRedraw\b", "always_redraw", code)
    code = re.sub(r"\bTOP_RIGHT\b", "UR", code)
    code = re.sub(r"\bTOP_LEFT\b", "UL", code)
    code = re.sub(r"\bBOTTOM_RIGHT\b", "DR", code)
    code = re.sub(r"\bBOTTOM_LEFT\b", "DL", code)
    # Broken 3D HUD helper on plain / MovingCamera scenes
    code = re.sub(
        r"self\.add_fixed_in_frame_mobjects\(([^)]+)\)",
        r"self.add(\1)",
        code,
    )
    # Prefer plain Scene — MovingCameraScene often breaks generated code
    code = re.sub(
        r"class\s+(\w+)\s*\(\s*MovingCameraScene\s*\)",
        r"class \1(Scene)",
        code,
    )
    code = re.sub(r"\.get_graph\(", ".plot(", code)
    # Axes(width=..., height=...) → x_length / y_length
    code = re.sub(r"(\bAxes\s*\([^)]*?)\bwidth\s*=", r"\1x_length=", code)
    code = re.sub(r"(\bAxes\s*\([^)]*?)\bheight\s*=", r"\1y_length=", code)
    # NumberPlane width/height similarly
    code = re.sub(r"(\bNumberPlane\s*\([^)]*?)\bwidth\s*=", r"\1x_length=", code)
    code = re.sub(r"(\bNumberPlane\s*\([^)]*?)\bheight\s*=", r"\1y_length=", code)
    # Convert MathTex and Tex to Text to prevent dvisvgm / LaTeX system dependencies
    code = re.sub(r"\bMathTex\s*\(", "Text(", code)
    code = re.sub(r"\bTex\s*\(", "Text(", code)
    code = re.sub(r"\bTexText\s*\(", "Text(", code)
    # Horizontal/vertical stretch distorts glyphs and often clips the last letter.
    code = re.sub(r"\.stretch_to_fit_width\s*\([^)]*\)", "", code)
    code = re.sub(r"\.stretch_to_fit_height\s*\([^)]*\)", "", code)

    color_replacements = {
        "LIGHT_BLUE": "BLUE_A",
        "DARK_BLUE": "BLUE_E",
        "LIGHT_RED": "RED_A",
        "DARK_RED": "RED_E",
        "LIGHT_GREEN": "GREEN_A",
        "DARK_GREEN": "GREEN_E",
        "ORANGE_A": "ORANGE",
        "PINK_A": "PINK",
        "GRAY": "GREY",
        "DARK_GRAY": "GREY_D",
        "LIGHT_GRAY": "GREY_A",
        "GREY_A": "GREY_A",
    }

    lines: list[str] = []
    for line in code.split("\n"):
        for invalid, valid in color_replacements.items():
            line = line.replace(invalid, valid)
        # Drop invalid tip_size kwargs that some models invent
        line = re.sub(r",\s*tip_size\s*=\s*[^,\)]+", "", line)
        line = re.sub(r"tip_size\s*=\s*[^,\)]+\s*,\s*", "", line)
        if "self.play(" in line and ".move_to," in line:
            line = re.sub(
                r"self\.play\((\w+)\.move_to,\s*([^)]+)\)",
                r"self.play(\1.animate.move_to(\2))",
                line,
            )
        lines.append(line)

    code = "\n".join(lines)
    if "from manim import *" not in code:
        code = "from manim import *\n" + code
    for imp in ("import numpy as np", "import math"):
        if imp not in code:
            code = imp + "\n" + code
    code = _inject_text_kerning_shim(code)
    return code.strip()


def extract_scene_name(code: str) -> str:
    match = re.search(r"class\s+(\w+)\s*\([^)]*Scene[^)]*\)", code)
    return match.group(1) if match else "GeneratedScene"
