"""Helpers for cleaning and validating Manim Community Edition code."""

from __future__ import annotations

import ast
import json
import re
from typing import Optional

# =============================================================================
# TEXT SAFETY (HARD RULE)
# =============================================================================
# Pango lays out Text() in *pixel* space: small font_size (~≤24) gets uneven
# letter advances (ManimCommunity/manim#2844). Fix: render at ≥48px, then
# .scale() back to the requested on-screen size. Keep glyph-width asserts so
# we never silently drop trailing letters.
# NEVER pad with NBSP / hide glyphs ("Network" → "Networ").
# NEVER auto scale_to_fit_width / soft-wrap host-side in a way that chops words.
# =============================================================================

_TEXT_KERNING_MARKER = "# _NOWIGETIT_TEXT_KERNING_SHIM"
_TEXT_KERNING_END_MARKER = "# _NOWIGETIT_TEXT_KERNING_END"
# Survives older Railway workers that strip/re-inject only the kerning shim.
_TEXT_LAYOUT_MARKER = "# _NOWIGETIT_TEXT_LAYOUT_FIX_V7"
_TEXT_LAYOUT_END_MARKER = "# _NOWIGETIT_TEXT_LAYOUT_FIX_V7_END"
_TEXT_LAYOUT_LEGACY_MARKERS = (
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V2", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V2_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V3", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V3_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V4", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V4_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V5", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V5_END"),
    ("# _NOWIGETIT_TEXT_LAYOUT_FIX_V6", "# _NOWIGETIT_TEXT_LAYOUT_FIX_V6_END"),
)
# Prefer a modern proportional face; DejaVu is the Linux fallback already in the image.
_TEXT_DEFAULT_FONT = "Noto Sans"
_TEXT_FONT_FALLBACKS = (
    "Noto Sans",
    "Liberation Sans",
    "DejaVu Sans",
    "Arial",
    "Helvetica",
)
_TEXT_KERNING_MIN = 48.0

# Patterns that must NEVER appear (glyph-hiding / pad hacks — not the kerning scale).
_FORBIDDEN_TEXT_SHIM_PATTERNS: tuple[tuple[str, str], ...] = (
    (
        r"_TEXT_CLIP_PAD\s*=",
        "NBSP clip-pad constant",
    ),
    (
        r"_hide_pad_glyphs\s*\(",
        "hide trailing pad glyphs",
    ),
    (
        r"set_opacity\s*\(\s*0\s*\).*\\\\u00a0|\\\\u00a0.*set_opacity\s*\(\s*0",
        "NBSP pad + hide opacity",
    ),
)

_TEXT_HELPERS = f"""
_TEXT_KERNING_MIN = {_TEXT_KERNING_MIN!r}
_TEXT_FONT_FALLBACKS = {_TEXT_FONT_FALLBACKS!r}

def _nig_pick_font():
    try:
        import manimpango
        available = set(manimpango.list_fonts())
    except Exception:
        available = set()
    for name in _TEXT_FONT_FALLBACKS:
        if not available or name in available:
            return name
    return _TEXT_FONT_FALLBACKS[-1]

_TEXT_RESOLVED_FONT = _nig_pick_font()

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
            f"(visible={{positive}}, letters={{letters}}, text={{text!r}})."
        )
    return mob

def _nig_prepare_text_kwargs(kwargs):
    kwargs = dict(kwargs)
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    # Host owns the typeface — ignore LLM font= / disable_ligatures=.
    kwargs["font"] = _TEXT_RESOLVED_FONT
    kwargs["disable_ligatures"] = False
    return kwargs

def _nig_make_text(factory, text, args, kwargs):
    kwargs = _nig_prepare_text_kwargs(kwargs)
    size = float(kwargs.get("font_size", 48) or 48)
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = factory(text, *args, **kwargs)
    if abs(internal - size) > 1e-9:
        mob.scale(size / internal)
    return _nig_assert_glyphs(_nig_recenter(mob), text)
"""

_TEXT_KERNING_SHIM = f"""{_TEXT_KERNING_MARKER}
# Capture raw Manim constructors; V7 redefines Text after this block.
_ManimText = Text
_ManimMarkupText = MarkupText
_ManimParagraph = Paragraph
_Manim_to_edge = Mobject.to_edge
{_TEXT_HELPERS}
def Text(text, *args, **kwargs):
    return _nig_make_text(_ManimText, text, args, kwargs)

def MarkupText(text, *args, **kwargs):
    return _nig_make_text(_ManimMarkupText, text, args, kwargs)

def Paragraph(*text, **kwargs):
    joined = " ".join(str(t) for t in text)
    kwargs = _nig_prepare_text_kwargs(kwargs)
    size = float(kwargs.get("font_size", 48) or 48)
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = _ManimParagraph(*text, **kwargs)
    if abs(internal - size) > 1e-9:
        mob.scale(size / internal)
    return _nig_assert_glyphs(_nig_recenter(mob), joined)

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

# Runs AFTER any stale worker re-injects an older kerning shim.
# Always calls raw _ManimText so a stale wrapper cannot win.
_TEXT_LAYOUT_FIX = f"""{_TEXT_LAYOUT_MARKER}
# Durable Text path: Noto Sans + Pango kerning scale (≥{_TEXT_KERNING_MIN:.0f}px then .scale).
{_TEXT_HELPERS}
def _nig_text_factory():
    return globals().get("_ManimText") or Text

def _nig_markup_factory():
    return globals().get("_ManimMarkupText") or MarkupText

def _nig_paragraph_factory():
    return globals().get("_ManimParagraph") or Paragraph

def Text(text, *args, **kwargs):
    return _nig_make_text(_nig_text_factory(), text, args, kwargs)

def MarkupText(text, *args, **kwargs):
    return _nig_make_text(_nig_markup_factory(), text, args, kwargs)

def Paragraph(*text, **kwargs):
    joined = " ".join(str(t) for t in text)
    kwargs = _nig_prepare_text_kwargs(kwargs)
    size = float(kwargs.get("font_size", 48) or 48)
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = _nig_paragraph_factory()(*text, **kwargs)
    if abs(internal - size) > 1e-9:
        mob.scale(size / internal)
    return _nig_assert_glyphs(_nig_recenter(mob), joined)

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


# =============================================================================
# LAYOUT GUARD
# =============================================================================
# The VLM is unreliable at spotting a panel that runs off the bottom of the
# frame or two labels sitting on top of each other, and it costs an image call
# to ask. Manim already knows the exact geometry, so we sample it during the
# render and report it back through the log the orchestrator already collects.
# Reporting only — never mutate the scene or fail the render.

_TEXT_MOTION_MARKER = "# _NOWIGETIT_TEXT_MOTION_FIX"
_TEXT_MOTION_END_MARKER = "# _NOWIGETIT_TEXT_MOTION_FIX_END"

# Transform between two Text mobjects interpolates glyph OUTLINES: the letters
# visibly melt into other letters, and Text→shape turns words into blobs. It
# reads as a rendering artefact rather than an explanation. Manim cannot know
# the intent statically, but at runtime the operand types are right there, so
# swap in a crossfade whenever text is involved.
_TEXT_MOTION_FIX = f'''{_TEXT_MOTION_MARKER}
_NIG_Transform = Transform
_NIG_ReplacementTransform = ReplacementTransform
_NIG_TransformMatchingShapes = TransformMatchingShapes


def _nig_texty(mob):
    try:
        name = type(mob).__name__
    except Exception:
        return False
    if name in ("Text", "MarkupText", "Paragraph"):
        return True
    subs = [s for s in getattr(mob, "submobjects", []) or [] if s is not None]
    if name in ("VGroup", "Group") and subs:
        return all(_nig_texty(s) for s in subs)
    return False


def _nig_crossfade(original, mobject, target, args, kwargs):
    """Crossfade when either side is text; otherwise keep the real morph."""
    try:
        if target is not None and (_nig_texty(mobject) or _nig_texty(target)):
            return FadeTransform(mobject, target, **kwargs)
    except Exception:
        pass
    if target is None:
        return original(mobject, *args, **kwargs)
    return original(mobject, target, *args, **kwargs)


def Transform(mobject, target_mobject=None, *args, **kwargs):
    return _nig_crossfade(_NIG_Transform, mobject, target_mobject, args, kwargs)


def ReplacementTransform(mobject, target_mobject=None, *args, **kwargs):
    return _nig_crossfade(
        _NIG_ReplacementTransform, mobject, target_mobject, args, kwargs
    )


def TransformMatchingShapes(mobject, target_mobject=None, *args, **kwargs):
    return _nig_crossfade(
        _NIG_TransformMatchingShapes, mobject, target_mobject, args, kwargs
    )
{_TEXT_MOTION_END_MARKER}
'''

_LAYOUT_GUARD_MARKER = "# _NOWIGETIT_LAYOUT_GUARD"
_LAYOUT_GUARD_END_MARKER = "# _NOWIGETIT_LAYOUT_GUARD_END"
_LAYOUT_REPORT_PREFIX = "_NOWIGETIT_LAYOUT_REPORT "
# Content may kiss the frame edge; only flag a real bleed past it.
_FRAME_TOLERANCE = 0.12
# Text boxes overlapping by less than this read as tight spacing, not collision.
_OVERLAP_TOLERANCE = 0.06

_LAYOUT_GUARD = f'''{_LAYOUT_GUARD_MARKER}
# Samples on-screen geometry after each play and reports violations via stdout.
_NIG_REPORT_PREFIX = {_LAYOUT_REPORT_PREFIX!r}
_NIG_FRAME_TOL = {_FRAME_TOLERANCE!r}
_NIG_OVERLAP_TOL = {_OVERLAP_TOLERANCE!r}
_nig_violations = {{}}


# ValueTracker & friends store their value AS a coordinate, so they sit far off
# stage by design and must never be read as layout.
_NIG_NON_VISUAL = ("ValueTracker", "ComplexValueTracker", "DecimalMatrix_dummy")


def _nig_box(mob):
    try:
        if type(mob).__name__ in _NIG_NON_VISUAL:
            return None
        if not mob.get_all_points().size:
            return None
        box = (
            float(mob.get_left()[0]), float(mob.get_right()[0]),
            float(mob.get_bottom()[1]), float(mob.get_top()[1]),
        )
    except Exception:
        return None
    # Updaters can transiently produce inf/NaN or astronomically large values
    # (e.g. an Angle between momentarily parallel lines) — not a layout fault.
    for v in box:
        if v != v or v in (float("inf"), float("-inf")) or abs(v) > 1e4:
            return None
    return box


def _nig_label(mob):
    text = getattr(mob, "text", None) or getattr(mob, "original_text", None)
    name = type(mob).__name__
    if isinstance(text, str) and text.strip():
        return name + " " + repr(text.strip()[:34])
    return name


def _nig_walk(mob):
    """Leaf-ish mobjects: a VGroup's own box hides which child is off-frame."""
    subs = [s for s in getattr(mob, "submobjects", []) if s is not None]
    if subs and type(mob).__name__ in ("VGroup", "Group", "VDict"):
        for sub in subs:
            for leaf in _nig_walk(sub):
                yield leaf
    else:
        yield mob


def _nig_check(scene):
    try:
        half_w = float(config.frame_width) / 2.0
        half_h = float(config.frame_height) / 2.0
    except Exception:
        return
    texts, seen = [], []
    for top in list(getattr(scene, "mobjects", [])):
        for mob in _nig_walk(top):
            box = _nig_box(mob)
            if box is None:
                continue
            left, right, bottom, top_y = box
            # Objects larger than the frame are deliberate backdrops.
            if (right - left) > 2 * half_w or (top_y - bottom) > 2 * half_h:
                continue
            # Only *partially* visible content is a layout fault. Something
            # entirely off stage is either parked there deliberately or is a
            # transient updater state — the learner never sees it clipped.
            visible = (
                left < half_w and right > -half_w
                and bottom < half_h and top_y > -half_h
            )
            if not visible:
                continue
            over = max(
                -half_w - left, right - half_w, -half_h - bottom, top_y - half_h
            )
            if over > _NIG_FRAME_TOL:
                key = "offframe:" + _nig_label(mob)
                if key not in _nig_violations:
                    _nig_violations[key] = (
                        _nig_label(mob) + " runs " + format(over, ".2f")
                        + " units past the frame edge"
                    )
            if type(mob).__name__ in ("Text", "MarkupText", "Paragraph"):
                texts.append((mob, box))
    for i in range(len(texts)):
        mob_a, a = texts[i]
        for j in range(i + 1, len(texts)):
            mob_b, b = texts[j]
            dx = min(a[1], b[1]) - max(a[0], b[0])
            dy = min(a[3], b[3]) - max(a[2], b[2])
            if dx > _NIG_OVERLAP_TOL and dy > _NIG_OVERLAP_TOL:
                pair = tuple(sorted([_nig_label(mob_a), _nig_label(mob_b)]))
                key = "overlap:" + "|".join(pair)
                if key not in _nig_violations and pair not in seen:
                    seen.append(pair)
                    _nig_violations[key] = pair[0] + " overlaps " + pair[1]


_NIG_scene_play = Scene.play


def _nig_play(self, *args, **kwargs):
    result = _NIG_scene_play(self, *args, **kwargs)
    try:
        _nig_check(self)
    except Exception:
        pass
    return result


Scene.play = _nig_play

_NIG_scene_render = Scene.render


def _nig_render(self, *args, **kwargs):
    result = _NIG_scene_render(self, *args, **kwargs)
    try:
        if _nig_violations:
            import json as _nig_json
            print(_NIG_REPORT_PREFIX + _nig_json.dumps(
                sorted(_nig_violations.values())[:8]
            ))
    except Exception:
        pass
    return result


Scene.render = _nig_render
{_LAYOUT_GUARD_END_MARKER}
'''


def parse_layout_report(log: str) -> list[str]:
    """Pull layout violations the guard reported during a render."""
    if not log or _LAYOUT_REPORT_PREFIX not in log:
        return []
    issues: list[str] = []
    for line in log.splitlines():
        idx = line.find(_LAYOUT_REPORT_PREFIX)
        if idx < 0:
            continue
        payload = line[idx + len(_LAYOUT_REPORT_PREFIX) :].strip()
        try:
            parsed = json.loads(payload)
        except ValueError:
            continue
        if isinstance(parsed, list):
            issues.extend(str(x) for x in parsed if str(x).strip())
    return list(dict.fromkeys(issues))


def layout_revision_instructions(issues: list[str]) -> str:
    """Turn guard findings into a concrete, actionable revision request."""
    if not issues:
        return ""
    offframe = [i for i in issues if "past the frame edge" in i]
    overlaps = [i for i in issues if "overlaps" in i]
    parts = [
        "The render measured real layout faults (exact geometry, not opinion) — "
        "fix these without changing the teaching content or the beat timing:"
    ]
    if offframe:
        parts.append(
            "- Off-frame content (the visible frame is 14.2 x 8.0 units, so x must "
            "stay within ±7.1 and y within ±4.0). Pull these back by grouping with "
            "arrange()/next_to() and move_to(ORIGIN), or use a smaller font_size / "
            "shorter diagram — never by truncating words:\n  "
            + "\n  ".join(offframe)
        )
    if overlaps:
        parts.append(
            "- Overlapping text. Give each label its own zone (next_to with buff "
            "~0.3), or FadeOut the earlier label before the later one appears:\n  "
            + "\n  ".join(overlaps)
        )
    return "\n".join(parts)


class UnsafeTextShimError(RuntimeError):
    """Raised when cleaned Manim code is missing the durable Text fix or has pad/hide hacks."""


def assert_safe_text_shim(code: str, *, allow_legacy_prefix: bool = True) -> None:
    """Fail hard unless the durable V7 Text path is present and active.

    V7 must own the final ``Text()`` and include the kerning scale (≥48px then
    ``.scale``). Pad/hide glyph hacks are always rejected.
    """
    if _TEXT_LAYOUT_MARKER not in code or _TEXT_LAYOUT_END_MARKER not in code:
        raise UnsafeTextShimError(
            "Refusing to render: missing durable text layout fix "
            f"({_TEXT_LAYOUT_MARKER})."
        )
    v7_start = code.find(_TEXT_LAYOUT_MARKER)
    v7_region = code[v7_start:]
    if "_TEXT_KERNING_MIN" not in v7_region or "_nig_make_text" not in v7_region:
        raise UnsafeTextShimError(
            "Refusing to render: durable fix missing kerning scale helpers."
        )
    for pattern, label in _FORBIDDEN_TEXT_SHIM_PATTERNS:
        if re.search(pattern, code, flags=re.S):
            raise UnsafeTextShimError(
                f"Refusing to render: forbidden Text shim ({label})."
            )
    # Last Text() definition must live inside the durable fix.
    defs = list(re.finditer(r"^def Text\s*\(", code, flags=re.M))
    if not defs or defs[-1].start() < v7_start:
        raise UnsafeTextShimError(
            "Refusing to render: final Text() definition is not the durable "
            "V7 layout fix."
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
        # Also swallow blank lines left at the seam, so strip→inject cycles
        # (every revision re-cleans the code) stay byte-for-byte idempotent
        # instead of growing a blank line per pass.
        while end < len(code) and code[end] == "\n":
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
    code = _strip_marked_block(code, _LAYOUT_GUARD_MARKER, _LAYOUT_GUARD_END_MARKER)
    code = _strip_marked_block(code, _TEXT_MOTION_MARKER, _TEXT_MOTION_END_MARKER)
    code = _strip_marked_block(code, _TEXT_LAYOUT_MARKER, _TEXT_LAYOUT_END_MARKER)
    return _strip_marked_block(code, _TEXT_KERNING_MARKER, _TEXT_KERNING_END_MARKER)


def _inject_text_kerning_shim(code: str) -> str:
    """Inject safe Text wrappers + durable V7 layout bypass.

    The layout fix is intentionally AFTER the kerning block so outdated Railway
    workers that only replace the kerning markers still leave V7 intact, and V7
    calls raw `_ManimText` so a stale wrapper cannot win.
    """
    code = _strip_text_kerning_shim(code)
    shim = (
        _TEXT_KERNING_SHIM.strip()
        + "\n"
        + _TEXT_LAYOUT_FIX.strip()
        + "\n"
        + _TEXT_MOTION_FIX.strip()
        + "\n"
        + _LAYOUT_GUARD.strip()
        + "\n"
    )
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
    # Our own clean path must emit the durable V7 Text path.
    assert_safe_text_shim(code, allow_legacy_prefix=False)
    return code


def extract_scene_name(code: str) -> str:
    match = re.search(r"class\s+(\w+)\s*\([^)]*Scene[^)]*\)", code)
    return match.group(1) if match else "GeneratedScene"


# =============================================================================
# SCENE QUALITY LINT
# =============================================================================
# Catches "40 seconds of nothing": a scene that renders and matches the
# narration length but spends it on motion that carries no information —
# scale/opacity breathing loops, no-op scale(1.0) "reverts", unlabeled shapes
# flying in and out, and trailing waits added to pad up to the target time.

_ANIMATE_CHAIN_RE = re.compile(r"(\w+)\.animate((?:\.\w+\([^()]*\))+)")
_SCALE_ARG_RE = re.compile(r"\.scale\(\s*([0-9]*\.?[0-9]+)\s*\)")
_OPACITY_ARG_RE = re.compile(r"\.set_(?:fill_)?opacity\(\s*([0-9]*\.?[0-9]+)\s*\)")
_NOOP_SCALE_RE = re.compile(r"\.scale\(\s*1(?:\.0+)?\s*\)")
_WAIT_RE = re.compile(r"self\.wait\(\s*([0-9]*\.?[0-9]+)?\s*\)")
_TIMING_COMMENT_RE = re.compile(
    r"#[^\n]*\b(?:total|totals|runtime|adjust to reach|sum|budget)\b[^\n]*\d",
    re.IGNORECASE,
)


def scene_body(code: str) -> str:
    """Scene source with the injected Text/layout shims stripped off.

    Ordered outermost-last: the guard is injected after the Text shims, so its
    end marker has to be tried first or the guard's own source leaks into the
    body and gets linted and fingerprinted as if the model had written it.
    """
    for marker in (
        _LAYOUT_GUARD_END_MARKER,
        _TEXT_LAYOUT_END_MARKER,
        _TEXT_KERNING_END_MARKER,
    ):
        idx = code.find(marker)
        if idx >= 0:
            return code[idx + len(marker) :]
    return code


def _direction_reversals(values: list[float]) -> int:
    """How many times a sequence of values changes direction (up→down→up)."""
    reversals = 0
    last_sign = 0
    for prev, curr in zip(values, values[1:]):
        delta = curr - prev
        if abs(delta) < 1e-6:
            continue
        sign = 1 if delta > 0 else -1
        if last_sign and sign != last_sign:
            reversals += 1
        last_sign = sign
    return reversals


def _grow_then_return_pairs(values: list[float]) -> int:
    """Count `scale(>1)` immediately followed by a scale back down to ~1 or less.

    That pair is the classic pointless pulse: the object ends where it started,
    so the seconds spent on it carry no information.
    """
    return sum(
        1
        for prev, curr in zip(values, values[1:])
        if prev > 1.02 and curr <= 1.02
    )


def _animated_property_series(body: str) -> tuple[dict[str, list[float]], dict[str, list[float]]]:
    """Per-object ordered scale / opacity values from `.animate` chains."""
    scales: dict[str, list[float]] = {}
    opacities: dict[str, list[float]] = {}
    for match in _ANIMATE_CHAIN_RE.finditer(body):
        name, chain = match.group(1), match.group(2)
        for raw in _SCALE_ARG_RE.findall(chain):
            scales.setdefault(name, []).append(float(raw))
        for raw in _OPACITY_ARG_RE.findall(chain):
            opacities.setdefault(name, []).append(float(raw))
    return scales, opacities


def lint_scene_code(code: str, *, target_duration: Optional[float] = None) -> list[str]:
    """Return actionable complaints about time-filling, information-free scenes.

    Empty list means the scene spends its runtime on something. Each message is
    written as an instruction so it can be fed straight into a revision prompt.
    """
    body = scene_body(code)
    issues: list[str] = []
    duration = float(target_duration or 0.0)

    noop_scales = len(_NOOP_SCALE_RE.findall(body))
    if noop_scales:
        issues.append(
            f"Remove {noop_scales} `.scale(1.0)` call(s): scaling by 1.0 is a no-op that "
            "does NOT undo an earlier scale, so the animation shows nothing. Delete the "
            "fake 'revert' plays entirely rather than replacing them."
        )

    scales, opacities = _animated_property_series(body)
    scale_pulses = sum(_grow_then_return_pairs(v) for v in scales.values())
    scale_churn = max((len(v) for v in scales.values()), default=0)
    if scale_pulses >= 2 or scale_churn >= 3:
        issues.append(
            f"Remove the decorative scale 'breathing' loops ({scale_pulses} grow-then-"
            "shrink pairs): scaling an object up and back down leaves it exactly where "
            "it started, so those seconds teach nothing. Replace that time with a new "
            "labeled element or a state change the narration actually mentions."
        )
    opacity_reversals = sum(_direction_reversals(v) for v in opacities.values())
    opacity_churn = max((len(v) for v in opacities.values()), default=0)
    if opacity_reversals >= 2 or opacity_churn >= 3:
        issues.append(
            "Remove the opacity oscillation filler (fading the same object up and down, "
            "e.g. 0.4 → 0.6 → 0.4). Fade an element in ONCE when the narration "
            "introduces it and leave it; use the freed time for real content."
        )

    label_count = len(re.findall(r"\bText\(", body))
    if duration >= 20.0 and label_count < 3:
        issues.append(
            f"Only {label_count} on-screen Text label(s) for a {duration:.0f}s scene. "
            "Label every element the narration names (short, ≤3 words each) and reveal "
            "the labels progressively — aim for 3-4 labels/captions besides the title."
        )
    elif duration >= 12.0 and label_count < 2:
        issues.append(
            f"Only {label_count} on-screen Text label(s) for a {duration:.0f}s scene. "
            "Add 1-2 short labels (≤3 words) naming the key elements as the narration "
            "introduces them; a long scene with just a title teaches nothing."
        )

    # With updaters / always_redraw, self.wait() IS the animation (that is how
    # continuous motion is driven in Manim), so wait time is not dead time.
    driven_by_updaters = bool(re.search(r"add_updater\(|always_redraw\(", body))
    if not driven_by_updaters:
        waits = [float(v) if v else 1.0 for v in _WAIT_RE.findall(body)]
        wait_total = sum(waits)
        last_play = body.rfind("self.play(")
        if last_play >= 0:
            trailing = [
                float(v) if v else 1.0 for v in _WAIT_RE.findall(body[last_play:])
            ]
            padded = (len(trailing) >= 2 and sum(trailing) > 1.0) or sum(trailing) > 2.5
            if padded:
                issues.append(
                    f"Trailing self.wait() total is {sum(trailing):.1f}s across "
                    f"{len(trailing)} call(s) after the last animation. End with exactly "
                    "one self.wait(0.5) hold; move the remaining time into animations "
                    "that advance the explanation instead of padding."
                )
        if duration > 0 and wait_total > max(2.5, 0.22 * duration):
            issues.append(
                f"Dead wait time is {wait_total:.1f}s of a {duration:.0f}s scene. Cut the "
                "static waits and give that time to meaningful self.play animations "
                "(reveals, labels, tracker motion) so the frame keeps developing."
            )

    if _TIMING_COMMENT_RE.search(body):
        issues.append(
            "Delete the runtime-arithmetic comments (e.g. '# total 6.78s', "
            "'# adjust to reach 40.7s'). Never write timing math in comments — just "
            "set correct run_time values."
        )

    return issues
