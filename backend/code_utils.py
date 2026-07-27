"""Helpers for cleaning and validating Manim Community Edition code."""

from __future__ import annotations

import ast
import re

# =============================================================================
# TEXT SAFETY (HARD RULE)
# =============================================================================
# NEVER render Text at a larger font_size and scale down. On Linux/Pango that
# zeroes trailing glyph widths ("dimension" → "dime…"). Job: b9e3b6764bd4.
# NEVER pad with NBSP / hide glyphs ("Network" → "Networ").
# NEVER auto scale_to_fit_width / soft-wrap host-side in a way that chops words.
# =============================================================================

_TEXT_KERNING_MARKER = "# _NOWIGETIT_TEXT_KERNING_SHIM"
_TEXT_KERNING_END_MARKER = "# _NOWIGETIT_TEXT_KERNING_END"
# Survives older Railway workers that strip/re-inject only the kerning shim.
_TEXT_LAYOUT_MARKER = "# _NOWIGETIT_TEXT_LAYOUT_FIX_V6"
_TEXT_LAYOUT_END_MARKER = "# _NOWIGETIT_TEXT_LAYOUT_FIX_V6_END"
_TEXT_LAYOUT_LEGACY_MARKERS = (
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V2", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V2_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V3", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V3_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V4", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V4_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V5", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V5_END"),
)
_TEXT_DEFAULT_FONT = "DejaVu Sans"

# Patterns that must NEVER appear in cleaned scene code (old scale-up hack).
_FORBIDDEN_TEXT_SHIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"_TEXT_KERNING_MIN\s*=",
        "scale-up kerning constant _TEXT_KERNING_MIN",
    ),
    (
        r"internal\s*=\s*max\s*\(\s*size\s*,",
        "font_size scale-up via max(size, …)",
    ),
    (
        r"max\s*\(\s*size\s*,\s*_TEXT_KERNING_MIN",
        "font_size scale-up via max(size, _TEXT_KERNING_MIN)",
    ),
    (
        r"mob\.scale\s*\(\s*size\s*/\s*internal",
        "scale(size/internal) after larger font render",
    ),
)

_TEXT_KERNING_SHIM = f"""{_TEXT_KERNING_MARKER}
# FORBIDDEN: render at larger font_size then scale down (truncates glyphs on Linux).
_ManimText = Text
_ManimMarkupText = MarkupText
_ManimParagraph = Paragraph
_Manim_to_edge = Mobject.to_edge
_TEXT_DEFAULT_FONT = {_TEXT_DEFAULT_FONT!r}

def _recenter_text_origin(mob):
    try:
        c = mob.get_center()
        if abs(float(c[0])) > 1e-6 or abs(float(c[1])) > 1e-6:
            mob.shift(-c)
    except Exception:
        pass
    return mob

def _prepare_text_kwargs(kwargs):
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("font", _TEXT_DEFAULT_FONT)
    return kwargs

def _assert_text_glyphs_intact(mob, text):
    # Tripwire: trailing letters must keep positive width (catches scale-up regressions).
    if not isinstance(text, str):
        return mob
    letters = sum(1 for ch in text if not ch.isspace())
    if letters <= 0:
        return mob
    try:
        positive = sum(1 for m in mob if float(getattr(m, "width", 0.0) or 0.0) > 1e-4)
    except Exception:
        return mob
    if positive < max(1, letters - 2):
        raise RuntimeError(
            "NowIGetIt text safety: Text glyphs missing/zero-width "
            f"(visible={{positive}}, letters={{letters}}, text={{text!r}}). "
            "Do not render Text at a larger font_size and scale down."
        )
    return mob

def Text(text, *args, **kwargs):
    mob = _ManimText(text, *args, **_prepare_text_kwargs(dict(kwargs)))
    return _assert_text_glyphs_intact(_recenter_text_origin(mob), text)

def MarkupText(text, *args, **kwargs):
    mob = _ManimMarkupText(text, *args, **_prepare_text_kwargs(dict(kwargs)))
    return _assert_text_glyphs_intact(_recenter_text_origin(mob), text)

def Paragraph(*text, **kwargs):
    mob = _ManimParagraph(*text, **_prepare_text_kwargs(dict(kwargs)))
    joined = " ".join(str(t) for t in text)
    return _assert_text_glyphs_intact(_recenter_text_origin(mob), joined)

def _safe_to_edge(self, edge=LEFT, buff=DEFAULT_MOBJECT_TO_EDGE_BUFFER, *args, **kwargs):
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

# Runs AFTER any stale worker re-injects an old scale-up kerning shim.
# Always calls raw _ManimText so a stale wrapper cannot win.
_TEXT_LAYOUT_FIX = f"""{_TEXT_LAYOUT_MARKER}
# FORBIDDEN: font_size upscale + scale(); this block bypasses stale wrappers.
def _nig_recenter(mob):
    try:
        c = mob.get_center()
        if abs(float(c[0])) > 1e-6 or abs(float(c[1])) > 1e-6:
            mob.shift(-c)
    except Exception:
        pass
    return mob

def _nig_assert_glyphs(mob, text):
    if not isinstance(text, str):
        return mob
    letters = sum(1 for ch in text if not ch.isspace())
    if letters <= 0:
        return mob
    try:
        positive = sum(1 for m in mob if float(getattr(m, "width", 0.0) or 0.0) > 1e-4)
    except Exception:
        return mob
    if positive < max(1, letters - 2):
        raise RuntimeError(
            "NowIGetIt text safety: Text glyphs missing/zero-width "
            f"(visible={{positive}}, letters={{letters}}, text={{text!r}}). "
            "Do not render Text at a larger font_size and scale down."
        )
    return mob

def _nig_text_factory():
    return globals().get("_ManimText") or Text

def _nig_markup_factory():
    return globals().get("_ManimMarkupText") or MarkupText

def _nig_paragraph_factory():
    return globals().get("_ManimParagraph") or Paragraph

def Text(text, *args, **kwargs):
    kwargs = dict(kwargs)
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("font", {_TEXT_DEFAULT_FONT!r})
    # Pass font_size through unchanged — never bump then scale.
    mob = _nig_text_factory()(text, *args, **kwargs)
    return _nig_assert_glyphs(_nig_recenter(mob), text)

def MarkupText(text, *args, **kwargs):
    kwargs = dict(kwargs)
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("font", {_TEXT_DEFAULT_FONT!r})
    mob = _nig_markup_factory()(text, *args, **kwargs)
    return _nig_assert_glyphs(_nig_recenter(mob), text)

def Paragraph(*text, **kwargs):
    kwargs = dict(kwargs)
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    kwargs.setdefault("font", {_TEXT_DEFAULT_FONT!r})
    mob = _nig_paragraph_factory()(*text, **kwargs)
    return _nig_assert_glyphs(_nig_recenter(mob), " ".join(str(t) for t in text))

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


class UnsafeTextShimError(RuntimeError):
    """Raised when cleaned Manim code still contains the glyph-truncating Text hack."""


def assert_safe_text_shim(code: str, *, allow_legacy_prefix: bool = True) -> None:
    """Fail hard unless the durable no-scale Text bypass is present and active.

    Outdated Railway workers may re-inject a legacy scale-up kerning block *before*
    the durable layout fix. That is allowed only when V6 remains after it and the
    V6 region itself contains no scale-up logic (V6 calls raw ``_ManimText``).
    """
    if _TEXT_LAYOUT_MARKER not in code or _TEXT_LAYOUT_END_MARKER not in code:
        raise UnsafeTextShimError(
            "Refusing to render: missing durable text layout fix "
            f"({_TEXT_LAYOUT_MARKER})."
        )
    v6_start = code.find(_TEXT_LAYOUT_MARKER)
    v6_region = code[v6_start:]
    for pattern, label in _FORBIDDEN_TEXT_SHIM_PATTERNS:
        if re.search(pattern, v6_region):
            raise UnsafeTextShimError(
                f"Refusing to render: forbidden Text shim in durable fix ({label}). "
                "Rendering Text larger then scaling down truncates glyphs on Linux."
            )
    if not allow_legacy_prefix:
        for pattern, label in _FORBIDDEN_TEXT_SHIM_PATTERNS:
            if re.search(pattern, code):
                raise UnsafeTextShimError(
                    f"Refusing to render: forbidden Text shim ({label}). "
                    "Rendering Text larger then scaling down truncates glyphs on Linux."
                )
    # Last Text() definition must live inside the durable fix.
    defs = list(re.finditer(r"^def Text\s*\(", code, flags=re.M))
    if not defs or defs[-1].start() < v6_start:
        raise UnsafeTextShimError(
            "Refusing to render: final Text() definition is not the durable "
            "no-scale layout fix (stale scale-up wrapper would win)."
        )


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
    try:
        assert_safe_text_shim(code)
    except UnsafeTextShimError as exc:
        return False, str(exc)
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
    """Inject safe Text wrappers + durable layout bypass.

    The layout fix is intentionally AFTER the kerning block so outdated Railway
    workers that only replace the kerning markers still leave V6 intact, and V6
    calls raw `_ManimText` so a stale scale-up wrapper cannot win.
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
    # Scene body must use Text(); keep _ManimText only inside the shim.
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

    code = code.replace("from manimlib import *", "from manim import *")
    code = code.replace("from manimlib import", "from manim import")

    code = code.replace("ShowCreation", "Create")
    code = re.sub(r"\bAlwaysRedraw\b", "always_redraw", code)
    code = re.sub(r"\bTOP_RIGHT\b", "UR", code)
    code = re.sub(r"\bTOP_LEFT\b", "UL", code)
    code = re.sub(r"\bBOTTOM_RIGHT\b", "DR", code)
    code = re.sub(r"\bBOTTOM_LEFT\b", "DL", code)
    code = re.sub(
        r"self\.add_fixed_in_frame_mobjects\(([^)]+)\)",
        r"self.add(\1)",
        code,
    )
    code = re.sub(
        r"class\s+(\w+)\s*\(\s*MovingCameraScene\s*\)",
        r"class \1(Scene)",
        code,
    )
    code = re.sub(r"\.get_graph\(", ".plot(", code)
    code = re.sub(r"(\bAxes\s*\([^)]*?)\bwidth\s*=", r"\1x_length=", code)
    code = re.sub(r"(\bAxes\s*\([^)]*?)\bheight\s*=", r"\1y_length=", code)
    code = re.sub(r"(\bNumberPlane\s*\([^)]*?)\bwidth\s*=", r"\1x_length=", code)
    code = re.sub(r"(\bNumberPlane\s*\([^)]*?)\bheight\s*=", r"\1y_length=", code)
    code = re.sub(r"\bMathTex\s*\(", "Text(", code)
    code = re.sub(r"\bTex\s*\(", "Text(", code)
    code = re.sub(r"\bTexText\s*\(", "Text(", code)
    code = re.sub(r"\.stretch_to_fit_width\s*\([^)]*\)", "", code)
    code = re.sub(r"\.stretch_to_fit_height\s*\([^)]*\)", "", code)
    code = re.sub(r"\.scale_to_fit_width\s*\([^)]*\)", "", code)
    code = re.sub(
        r"\bWrite\(\s*(title|subtitle|caption|heading|label|summary|formula|note|text)\s*\)",
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
    code = code.strip()
    # Our own clean path must never emit the scale-up hack anywhere.
    assert_safe_text_shim(code, allow_legacy_prefix=False)
    return code


def extract_scene_name(code: str) -> str:
    match = re.search(r"class\s+(\w+)\s*\([^)]*Scene[^)]*\)", code)
    return match.group(1) if match else "GeneratedScene"
