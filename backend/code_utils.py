"""Helpers for cleaning and validating Manim Community Edition code."""

from __future__ import annotations

import ast
import re

# Pango lays out Text() at the given font_size in pixels; small sizes get
# uneven letter advances (broken kerning). Render at a safe size, then scale.
# See: https://github.com/ManimCommunity/manim/issues/2844
#
# Do NOT pad with NBSP/spaces and hide trailing glyphs: on many hosts those
# pads add zero width (no anti-clip benefit) and when submobject counts differ
# the hide step erases real letters ("Network" → "Networ").
_TEXT_KERNING_MARKER = "# _NOWIGETIT_TEXT_KERNING_SHIM"
_TEXT_KERNING_END_MARKER = "# _NOWIGETIT_TEXT_KERNING_END"
# Survives older Railway workers that strip/re-inject only the kerning shim.
_TEXT_LAYOUT_MARKER = "# _NOWIGETIT_TEXT_LAYOUT_FIX_V4"
_TEXT_LAYOUT_END_MARKER = "# _NOWIGETIT_TEXT_LAYOUT_FIX_V4_END"
# Strip older layout-fix generations (width caps / soft-wrap / clamp).
_TEXT_LAYOUT_LEGACY_MARKERS = (
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V2", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V2_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V3", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V3_END"),
)
_TEXT_KERNING_MIN_SIZE = 48.0
# Installed on the Railway image (fonts-dejavu-core); avoids Pango fallback drift.
_TEXT_DEFAULT_FONT = "DejaVu Sans"
_TEXT_KERNING_SHIM = f"""{_TEXT_KERNING_MARKER}
_ManimText = Text
_ManimMarkupText = MarkupText
_ManimParagraph = Paragraph
_Manim_to_edge = Mobject.to_edge
_TEXT_KERNING_MIN = {_TEXT_KERNING_MIN_SIZE}
_TEXT_DEFAULT_FONT = {_TEXT_DEFAULT_FONT!r}

def _recenter_text_origin(mob):
    # Linux/Pango can emit Text SVGs whose bbox center is far from ORIGIN.
    try:
        c = mob.get_center()
        if abs(float(c[0])) > 1e-6 or abs(float(c[1])) > 1e-6:
            mob.shift(-c)
    except Exception:
        pass
    return mob

def _prepare_text_kwargs(kwargs):
    # width/height stretch the SVG and ruin letter spacing / clip glyphs
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("font", _TEXT_DEFAULT_FONT)
    kwargs.setdefault("disable_ligatures", True)
    return kwargs

def _kerning_safe_text(factory, text, args, kwargs):
    kwargs = _prepare_text_kwargs(dict(kwargs))
    font_size = kwargs.get("font_size", 48)
    try:
        size = float(font_size)
    except (TypeError, ValueError):
        return _recenter_text_origin(factory(text, *args, **kwargs))
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = factory(text, *args, **kwargs)
    if internal != size:
        mob.scale(size / internal)
    return _recenter_text_origin(mob)

def Text(text, *args, **kwargs):
    return _kerning_safe_text(_ManimText, text, args, kwargs)

def MarkupText(text, *args, **kwargs):
    return _kerning_safe_text(_ManimMarkupText, text, args, kwargs)

def Paragraph(*text, **kwargs):
    kwargs = _prepare_text_kwargs(dict(kwargs))
    font_size = kwargs.get("font_size", 48)
    try:
        size = float(font_size)
    except (TypeError, ValueError):
        return _recenter_text_origin(_ManimParagraph(*text, **kwargs))
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = _ManimParagraph(*text, **kwargs)
    if internal != size:
        mob.scale(size / internal)
    return _recenter_text_origin(mob)

def _safe_to_edge(self, edge=LEFT, buff=DEFAULT_MOBJECT_TO_EDGE_BUFFER, *args, **kwargs):
    # Center titles/captions horizontally; do NOT shrink or clamp width.
    result = _Manim_to_edge(self, edge, buff, *args, **kwargs)
    try:
        e = np.array(edge, dtype=float)
        if abs(float(e[0])) < 1e-6 and abs(float(e[1])) > 0.5:
            self.set_x(0)
    except Exception:
        pass
    return result

Mobject.to_edge = _safe_to_edge
{_TEXT_KERNING_END_MARKER}
"""

# Re-applied after an outdated worker re-injects an old kerning-only shim.
_TEXT_LAYOUT_FIX = f"""{_TEXT_LAYOUT_MARKER}
def _nig_recenter(mob):
    try:
        c = mob.get_center()
        if abs(float(c[0])) > 1e-6 or abs(float(c[1])) > 1e-6:
            mob.shift(-c)
    except Exception:
        pass
    return mob

def _nig_wrap_text(factory):
    def _wrapped(text, *args, **kwargs):
        kwargs = dict(kwargs)
        kwargs.pop("width", None)
        kwargs.pop("height", None)
        kwargs.setdefault("font", {_TEXT_DEFAULT_FONT!r})
        kwargs.setdefault("disable_ligatures", True)
        return _nig_recenter(factory(text, *args, **kwargs))
    return _wrapped

Text = _nig_wrap_text(Text)
MarkupText = _nig_wrap_text(MarkupText)
_NIG_Paragraph = Paragraph
def Paragraph(*text, **kwargs):
    kwargs = dict(kwargs)
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("font", {_TEXT_DEFAULT_FONT!r})
    kwargs.setdefault("disable_ligatures", True)
    return _nig_recenter(_NIG_Paragraph(*text, **kwargs))

_NIG_to_edge = Mobject.to_edge
def _nig_safe_to_edge(self, edge=LEFT, buff=DEFAULT_MOBJECT_TO_EDGE_BUFFER, *args, **kwargs):
    result = _NIG_to_edge(self, edge, buff, *args, **kwargs)
    try:
        e = np.array(edge, dtype=float)
        if abs(float(e[0])) < 1e-6 and abs(float(e[1])) > 0.5:
            self.set_x(0)
    except Exception:
        pass
    return result
Mobject.to_edge = _nig_safe_to_edge
{_TEXT_LAYOUT_END_MARKER}
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


def _strip_marked_block(code: str, start_marker: str, end_marker: str) -> str:
    """Remove a previously injected marked block (old or new format)."""
    start = code.find(start_marker)
    if start < 0:
        return code
    end = code.find(end_marker, start)
    if end >= 0:
        end = end + len(end_marker)
        if end < len(code) and code[end] == "\n":
            end += 1
        return code[:start] + code[end:]
    # Legacy blocks had no end marker — cut until the next top-level class.
    rest = code[start:]
    m = re.search(r"^class\s", rest, flags=re.M)
    if m:
        return code[:start] + rest[m.start() :]
    nl = code.find("\n", start)
    return code[:start] + (code[nl + 1 :] if nl >= 0 else "")


def _strip_text_kerning_shim(code: str) -> str:
    """Remove previously injected text/layout shims."""
    for start, end in _TEXT_LAYOUT_LEGACY_MARKERS:
        code = _strip_marked_block(code, start, end)
    code = _strip_marked_block(code, _TEXT_LAYOUT_MARKER, _TEXT_LAYOUT_END_MARKER)
    return _strip_marked_block(code, _TEXT_KERNING_MARKER, _TEXT_KERNING_END_MARKER)


def _inject_text_kerning_shim(code: str) -> str:
    """Shadow Text/MarkupText/Paragraph with kerning-safe wrappers.

    Always refresh an existing shim so older jobs pick up clip/kerning fixes.
    Also inject a layout fix *after* the kerning shim so outdated Railway
    workers that only replace the kerning block still keep title centering.
    """
    code = _strip_text_kerning_shim(code)
    shim = _TEXT_KERNING_SHIM.strip() + "\n" + _TEXT_LAYOUT_FIX.strip() + "\n"
    match = re.search(r"^from manim import \*[ \t]*$", code, flags=re.M)
    if match:
        insert_at = match.end()
        return code[:insert_at] + "\n" + shim + code[insert_at:]
    return shim + "\n" + code


def _rewrite_text_bypass(code: str) -> str:
    """Force scene code to use wrapped Text, not raw _ManimText bypasses."""
    # Rewrite only scene body after the last injected fix block.
    end = code.find(_TEXT_LAYOUT_END_MARKER)
    if end < 0:
        end = code.find(_TEXT_KERNING_END_MARKER)
        end_marker = _TEXT_KERNING_END_MARKER
    else:
        end_marker = _TEXT_LAYOUT_END_MARKER
    if end < 0:
        return code
    split_at = end + len(end_marker)
    head, tail = code[:split_at], code[split_at:]
    tail = re.sub(r"\b_ManimText\s*\(", "Text(", tail)
    tail = re.sub(r"\b_ManimMarkupText\s*\(", "MarkupText(", tail)
    tail = re.sub(r"\b_ManimParagraph\s*\(", "Paragraph(", tail)
    return head + tail


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
    # Forced width caps from older prompts/models shrink text until words look cut off.
    code = re.sub(r"\.scale_to_fit_width\s*\([^)]*\)", "", code)
    # Write() on titles looks truncated for ~1s; prefer instant FadeIn.
    code = re.sub(
        r"\bWrite\(\s*(title|subtitle|caption|heading|label)\s*\)",
        r"FadeIn(\1)",
        code,
        flags=re.I,
    )

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
    code = _rewrite_text_bypass(code)
    return code.strip()


def extract_scene_name(code: str) -> str:
    match = re.search(r"class\s+(\w+)\s*\([^)]*Scene[^)]*\)", code)
    return match.group(1) if match else "GeneratedScene"
