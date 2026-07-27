"""Hard guarantees: Text must never use the font_size-upscale→scale hack."""

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


def _old_scaleup_kerning_shim() -> str:
    return """# _NOWIGETIT_TEXT_KERNING_SHIM
_ManimText = Text
_ManimMarkupText = MarkupText
_ManimParagraph = Paragraph
_TEXT_KERNING_MIN = 48.0

def _kerning_safe_text(factory, text, args, kwargs):
    kwargs.pop("width", None)
    kwargs.pop("height", None)
    font_size = kwargs.get("font_size", 48)
    size = float(font_size)
    internal = max(size, _TEXT_KERNING_MIN)
    kwargs["font_size"] = internal
    mob = factory(text, *args, **kwargs)
    if internal != size:
        mob.scale(size / internal)
    return mob

def Text(text, *args, **kwargs):
    return _kerning_safe_text(_ManimText, text, args, kwargs)
# _NOWIGETIT_TEXT_KERNING_END
"""


def test_clean_code_rejects_scaleup_patterns():
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
    assert "_TEXT_KERNING_MIN" not in code
    assert "max(size," not in code
    assert "size / internal" not in code


def test_assert_safe_text_shim_blocks_old_hack_without_v6():
    poisoned = (
        "from manim import *\n"
        + _old_scaleup_kerning_shim()
        + "\nclass Demo(Scene):\n    def construct(self):\n        pass\n"
    )
    with pytest.raises(UnsafeTextShimError):
        assert_safe_text_shim(poisoned)


def test_assert_allows_legacy_prefix_when_v6_wins():
    cleaned = clean_manim_code(
        "from manim import *\nclass Demo(Scene):\n    def construct(self):\n        pass\n"
    )
    start = cleaned.find("# _NOWIGETIT_TEXT_KERNING_SHIM")
    end = cleaned.find("# _NOWIGETIT_TEXT_KERNING_END") + len("# _NOWIGETIT_TEXT_KERNING_END")
    if cleaned[end : end + 1] == "\n":
        end += 1
    stale = cleaned[:start] + _old_scaleup_kerning_shim() + cleaned[end:]
    # Stale worker payload is acceptable only because V6 still owns Text().
    assert_safe_text_shim(stale, allow_legacy_prefix=True)
    with pytest.raises(UnsafeTextShimError):
        assert_safe_text_shim(stale, allow_legacy_prefix=False)


def test_clean_strips_old_hack_and_is_safe():
    poisoned = (
        "from manim import *\n"
        + _old_scaleup_kerning_shim()
        + """
class Demo(Scene):
    def construct(self):
        t = Text("Determinant measures scaling in any dimension", font_size=28)
        self.add(t)
"""
    )
    cleaned = clean_manim_code(poisoned)
    assert_safe_text_shim(cleaned)
    assert "_TEXT_KERNING_MIN" not in cleaned
    # Durable V6 must outrank any residual wrapper.
    assert cleaned.rfind("def Text(") > cleaned.find(_TEXT_LAYOUT_MARKER)


def test_stale_worker_kerning_cannot_win_over_layout_fix():
    """Old Railway workers re-inject scale-up kerning but leave V6 after it."""
    cleaned = clean_manim_code(
        """
from manim import *
class Demo(Scene):
    def construct(self):
        self.add(Text("Volume in 3D", font_size=40))
"""
    )
    # Simulate outdated worker: replace only kerning markers with old hack.
    start = cleaned.find("# _NOWIGETIT_TEXT_KERNING_SHIM")
    end = cleaned.find("# _NOWIGETIT_TEXT_KERNING_END")
    assert start >= 0 and end >= 0
    end = end + len("# _NOWIGETIT_TEXT_KERNING_END")
    if end < len(cleaned) and cleaned[end] == "\n":
        end += 1
    stale = cleaned[:start] + _old_scaleup_kerning_shim() + cleaned[end:]
    assert "_TEXT_KERNING_MIN" in stale
    assert _TEXT_LAYOUT_MARKER in stale
    assert stale.find("_TEXT_KERNING_MIN") < stale.find(_TEXT_LAYOUT_MARKER)
    # V6 Text() must be the last definition and call _ManimText / factory.
    last_text_def = list(re.finditer(r"^def Text\(", stale, flags=re.M))[-1]
    assert last_text_def.start() > stale.find(_TEXT_LAYOUT_MARKER)
    v6_region = stale[stale.find(_TEXT_LAYOUT_MARKER) :]
    assert "_nig_text_factory" in v6_region or "_ManimText" in v6_region
    assert "max(size," not in v6_region


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
    # Explicit trailing letters of "dimension"
    trailing = [float(m.width) for m in mob[-4:]]
    assert all(w > 1e-4 for w in trailing), trailing
