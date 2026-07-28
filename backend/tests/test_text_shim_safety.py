"""Hard guarantees: Text uses Noto + kerning scale, never pad/hide glyphs."""

from __future__ import annotations

import re

import pytest

from backend.code_utils import (
    UnsafeTextShimError,
    _TEXT_LAYOUT_MARKER,
    assert_safe_text_shim,
    clean_manim_code,
)


CANARY = "Determinant measures scaling in any dimension"


def _pad_hide_shim() -> str:
    return """# _NOWIGETIT_TEXT_KERNING_SHIM
_ManimText = Text
_TEXT_CLIP_PAD = "\\u00a0\\u00a0"

def _hide_pad_glyphs(mob):
    for i in range(1, 3):
        mob[-i].set_opacity(0)
    return mob

def Text(text, *args, **kwargs):
    mob = _ManimText(text + _TEXT_CLIP_PAD, *args, **kwargs)
    return _hide_pad_glyphs(mob)
# _NOWIGETIT_TEXT_KERNING_END
"""


def test_clean_code_injects_v7_kerning_scale():
    code = clean_manim_code(
        """
from manim import *
class Demo(Scene):
    def construct(self):
        self.add(Text("hello", font_size=28))
"""
    )
    assert_safe_text_shim(code)
    assert _TEXT_LAYOUT_MARKER in code
    assert "_TEXT_KERNING_MIN" in code
    assert "_nig_make_text" in code
    assert "Noto Sans" in code
    assert "_TEXT_CLIP_PAD" not in code


def test_assert_safe_text_shim_blocks_pad_hide_without_v7():
    poisoned = (
        "from manim import *\n"
        + _pad_hide_shim()
        + "\nclass Demo(Scene):\n    def construct(self):\n        pass\n"
    )
    with pytest.raises(UnsafeTextShimError):
        assert_safe_text_shim(poisoned)


def test_clean_strips_pad_hide_and_is_safe():
    poisoned = (
        "from manim import *\n"
        + _pad_hide_shim()
        + """
class Demo(Scene):
    def construct(self):
        t = Text("Determinant measures scaling in any dimension", font_size=28)
        self.add(t)
"""
    )
    cleaned = clean_manim_code(poisoned)
    assert_safe_text_shim(cleaned)
    assert "_TEXT_CLIP_PAD" not in cleaned
    assert "_hide_pad_glyphs" not in cleaned
    assert cleaned.rfind("def Text(") > cleaned.find(_TEXT_LAYOUT_MARKER)


def test_stale_worker_cannot_outrank_v7():
    """Old Railway workers re-inject a shim before V7; V7 Text() must still win."""
    cleaned = clean_manim_code(
        """
from manim import *
class Demo(Scene):
    def construct(self):
        self.add(Text("Volume in 3D", font_size=40))
"""
    )
    start = cleaned.find("# _NOWIGETIT_TEXT_KERNING_SHIM")
    end = cleaned.find("# _NOWIGETIT_TEXT_KERNING_END")
    assert start >= 0 and end >= 0
    end = end + len("# _NOWIGETIT_TEXT_KERNING_END")
    if end < len(cleaned) and cleaned[end] == "\n":
        end += 1
    stale = cleaned[:start] + _pad_hide_shim() + cleaned[end:]
    # Pad/hide in the prefix is rejected whenever present.
    with pytest.raises(UnsafeTextShimError):
        assert_safe_text_shim(stale)
    # But V7 markers + helpers are still present after the stale block.
    assert _TEXT_LAYOUT_MARKER in stale
    last_text_def = list(re.finditer(r"^def Text\(", stale, flags=re.M))[-1]
    assert last_text_def.start() > stale.find(_TEXT_LAYOUT_MARKER)
    v7_region = stale[stale.find(_TEXT_LAYOUT_MARKER) :]
    assert "_nig_make_text" in v7_region
    assert "_TEXT_KERNING_MIN" in v7_region


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("manim") is None,
    reason="manim not installed",
)
def test_text_trailing_glyphs_have_width():
    from manim import config

    config.verbosity = "ERROR"
    code = clean_manim_code(
        """
from manim import *
class Demo(Scene):
    def construct(self):
        pass
"""
    )
    ns: dict = {}
    exec(code.split("class ")[0], ns)
    mob = ns["Text"](CANARY, font_size=28)
    letters = sum(1 for ch in CANARY if not ch.isspace())
    positive = sum(1 for m in mob if float(m.width) > 1e-4)
    assert positive >= letters - 2, (positive, letters, [float(m.width) for m in mob[-6:]])
    trailing = [float(m.width) for m in mob[-4:]]
    assert all(w > 1e-4 for w in trailing), trailing


@pytest.mark.skipif(
    __import__("importlib").util.find_spec("manim") is None,
    reason="manim not installed",
)
def test_small_labels_use_kerning_scale_and_keep_size():
    from manim import Text as RawText
    from manim import config

    config.verbosity = "ERROR"
    code = clean_manim_code(
        "from manim import *\nclass Demo(Scene):\n    def construct(self):\n        pass\n"
    )
    ns: dict = {}
    exec(code.split("class ")[0], ns)
    label = "Innenraum (warm)"
    wrapped = ns["Text"](label, font_size=20)
    raw = RawText(label, font_size=20, font=ns.get("_TEXT_RESOLVED_FONT", "DejaVu Sans"))
    # On-screen size stays near the requested size (±15%).
    assert abs(wrapped.width - raw.width) / max(raw.width, 1e-6) < 0.15
    # Host forces a resolved font.
    assert ns.get("_TEXT_RESOLVED_FONT")
