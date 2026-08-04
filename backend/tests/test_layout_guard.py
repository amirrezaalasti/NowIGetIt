"""The layout guard reports geometry the render actually measured.

It exists because the reviewer only ever sees two sampled frames, and misses a
label that collides or a panel that leaves the frame. Its findings override an
approval, so a false positive costs a wasted revision — the rules below are the
ones that keep it honest.
"""

from __future__ import annotations

import json

from backend.code_utils import (
    _LAYOUT_GUARD_END_MARKER,
    _LAYOUT_GUARD_MARKER,
    _LAYOUT_REPORT_PREFIX,
    clean_manim_code,
    layout_revision_instructions,
    parse_layout_report,
    validate_manim_code,
)

SCENE = """
from manim import *
class S(Scene):
    def construct(self):
        t = Text("hi")
        self.play(FadeIn(t))
        self.wait(0.5)
"""


def _report(*issues: str) -> str:
    return _LAYOUT_REPORT_PREFIX + json.dumps(list(issues))


def test_guard_is_injected_and_keeps_the_code_valid() -> None:
    code = clean_manim_code(SCENE)
    assert _LAYOUT_GUARD_MARKER in code
    ok, err = validate_manim_code(code)
    assert ok, err


def test_cleaning_is_idempotent_so_the_guard_never_stacks() -> None:
    # Code is re-cleaned on every revision and again before render; a guard that
    # accumulated would re-wrap Scene.play once per pass.
    once = clean_manim_code(SCENE)
    assert clean_manim_code(once) == once
    assert once.count(_LAYOUT_GUARD_END_MARKER) == 1


def test_report_is_parsed_out_of_a_noisy_render_log() -> None:
    log = "\n".join(
        [
            "Manim Community v0.20.1",
            "INFO   rendering...",
            _report("Rectangle runs 0.70 units past the frame edge"),
            "INFO   File ready at scene.mp4",
        ]
    )
    assert parse_layout_report(log) == [
        "Rectangle runs 0.70 units past the frame edge"
    ]


def test_repeated_and_empty_reports_are_deduplicated() -> None:
    log = "\n".join([_report("A overlaps B"), _report("A overlaps B", "C off frame")])
    assert parse_layout_report(log) == ["A overlaps B", "C off frame"]


def test_a_log_without_a_report_yields_nothing() -> None:
    assert parse_layout_report("") == []
    assert parse_layout_report("INFO rendering\nDone.") == []
    # A truncated / malformed payload must not raise.
    assert parse_layout_report(_LAYOUT_REPORT_PREFIX + '["unterminated') == []


def test_instructions_separate_the_two_fault_kinds() -> None:
    text = layout_revision_instructions(
        ["Rectangle runs 0.70 units past the frame edge", "Text 'A' overlaps Text 'B'"]
    )
    assert "Off-frame content" in text
    assert "Overlapping text" in text
    # Never resolve a layout fault by dropping characters.
    assert "never by truncating words" in text


def test_no_issues_means_no_instructions() -> None:
    assert layout_revision_instructions([]) == ""
