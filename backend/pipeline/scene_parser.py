"""Parse Manim scene code into a structured JSON scene graph with animation timestamps.

Extracts element definitions (Rectangle, Text, MathTex, Tex, Line, Circle, Dot,
Arrow, CurvedArrow, Polygon, Arc) from Manim Python source code.

Tracks animation timelines (self.play, Write, Create, FadeIn, FadeOut, Wait) to
assign appear_time and disappear_time to each element, allowing the canvas
editor to show ONLY elements visible at the paused video timestamp.
"""

from __future__ import annotations

import ast
import re
from typing import Any, Optional

# Manim coordinate system: x ∈ [-7.1, 7.1], y ∈ [-4, 4]
_MANIM_COLORS: dict[str, str] = {
    "WHITE": "#FFFFFF",
    "BLACK": "#000000",
    "RED": "#FC6255",
    "RED_A": "#F7A1A3",
    "RED_B": "#FF8080",
    "RED_C": "#FC6255",
    "GREEN": "#83C167",
    "GREEN_A": "#C5E1A5",
    "GREEN_B": "#A6CF8C",
    "BLUE": "#58C4DD",
    "BLUE_A": "#C7E9F1",
    "BLUE_B": "#9CDCEB",
    "YELLOW": "#FFFF00",
    "YELLOW_A": "#FFF1B6",
    "YELLOW_B": "#FFEA94",
    "YELLOW_E": "#C7A317",
    "ORANGE": "#FF862F",
    "GOLD": "#FFD700",
    "GREY": "#888888",
    "GREY_A": "#DDDDDD",
    "GREY_B": "#BBBBBB",
    "GREY_C": "#999999",
    "GRAY": "#888888",
    "LIGHT_GREY": "#BBBBBB",
    "PURPLE": "#9A72AC",
    "PINK": "#D147BD",
    "TEAL": "#5CD0B3",
    "MAROON": "#C55F73",
    "BOLD": "BOLD",
}

_MANIM_DIRECTIONS: dict[str, tuple[float, float]] = {
    "UP": (0.0, 1.0),
    "DOWN": (0.0, -1.0),
    "LEFT": (-1.0, 0.0),
    "RIGHT": (1.0, 0.0),
    "UL": (-1.0, 1.0),
    "UR": (1.0, 1.0),
    "DL": (-1.0, -1.0),
    "DR": (1.0, -1.0),
    "ORIGIN": (0.0, 0.0),
}


class SceneElement:
    """One visual element parsed from Manim code with timeline awareness."""

    def __init__(
        self,
        *,
        element_id: str,
        element_type: str,
        variable_name: str,
        line_number: int,
        x: float = 0.0,
        y: float = 0.0,
        width: float = 1.0,
        height: float = 1.0,
        radius: float = 0.0,
        fill_color: str | None = None,
        fill_opacity: float = 0.0,
        stroke_color: str | None = None,
        stroke_width: float = 2.0,
        text: str | None = None,
        font_size: float | None = None,
        rotation: float = 0.0,
        scale: float = 1.0,
        appear_time: float = 0.0,
        disappear_time: float = 999.0,
        points: list[tuple[float, float]] | None = None,
        start_point: tuple[float, float] | None = None,
        end_point: tuple[float, float] | None = None,
    ):
        self.element_id = element_id
        self.element_type = element_type
        self.variable_name = variable_name
        self.line_number = line_number
        self.x = x
        self.y = y
        self.width = width
        self.height = height
        self.radius = radius
        self.fill_color = fill_color
        self.fill_opacity = fill_opacity
        self.stroke_color = stroke_color
        self.stroke_width = stroke_width
        self.text = text
        self.font_size = font_size
        self.rotation = rotation
        self.scale = scale
        self.appear_time = appear_time
        self.disappear_time = disappear_time
        self.points = points or []
        self.start_point = start_point
        self.end_point = end_point

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self.element_id,
            "type": self.element_type,
            "variable_name": self.variable_name,
            "line_number": self.line_number,
            "x": round(self.x, 4),
            "y": round(self.y, 4),
            "width": round(self.width, 4),
            "height": round(self.height, 4),
            "fill_color": self.fill_color,
            "fill_opacity": round(self.fill_opacity, 3),
            "stroke_color": self.stroke_color,
            "stroke_width": round(self.stroke_width, 2),
            "rotation": round(self.rotation, 4),
            "scale": round(self.scale, 4),
            "appear_time": round(self.appear_time, 2),
            "disappear_time": round(self.disappear_time, 2),
        }
        if self.radius > 0:
            d["radius"] = round(self.radius, 4)
        if self.text is not None:
            d["text"] = self.text
        if self.font_size is not None:
            d["font_size"] = self.font_size
        if self.points:
            d["points"] = [
                {"x": round(p[0], 4), "y": round(p[1], 4)} for p in self.points
            ]
        if self.start_point:
            d["start_point"] = {
                "x": round(self.start_point[0], 4),
                "y": round(self.start_point[1], 4),
            }
        if self.end_point:
            d["end_point"] = {
                "x": round(self.end_point[0], 4),
                "y": round(self.end_point[1], 4),
            }
        return d


def _resolve_color(value: str, local_colors: dict[str, str]) -> str | None:
    value = value.strip().strip('"').strip("'")
    if value.startswith("#"):
        return value
    if value in local_colors:
        return local_colors[value]
    if value in _MANIM_COLORS:
        return _MANIM_COLORS[value]
    return value if value.startswith("#") else None


def _parse_point_expr(expr: str) -> tuple[float, float]:
    x, y = 0.0, 0.0
    expr = expr.strip()

    array_match = re.search(r"\[([^]]+)\]", expr)
    if array_match:
        parts = array_match.group(1).split(",")
        if len(parts) >= 2:
            try:
                x = float(parts[0].strip())
                y = float(parts[1].strip())
            except ValueError:
                pass
            return (x, y)

    for direction, (dx, dy) in _MANIM_DIRECTIONS.items():
        pattern = rf"{direction}\s*\*\s*([0-9.-]+)"
        for m in re.finditer(pattern, expr):
            scalar = float(m.group(1))
            x += dx * scalar
            y += dy * scalar

        pattern2 = rf"([0-9.-]+)\s*\*\s*{direction}"
        for m in re.finditer(pattern2, expr):
            scalar = float(m.group(1))
            x += dx * scalar
            y += dy * scalar

        if re.search(rf"\b{direction}\b", expr) and not re.search(
            rf"[0-9.-]+\s*\*\s*{direction}|{direction}\s*\*\s*[0-9.-]+", expr
        ):
            x += dx
            y += dy

    return (x, y)


_ELEMENT_TYPES = {
    "Rectangle",
    "Square",
    "Circle",
    "Dot",
    "Line",
    "Arrow",
    "CurvedArrow",
    "DashedLine",
    "Text",
    "MathTex",
    "Tex",
    "Polygon",
    "Arc",
}


def parse_scene_code(code: str) -> list[dict[str, Any]]:
    """Parse Manim code, extracting elements with timeline (appear/disappear) tracking."""
    lines = code.splitlines()
    elements: list[SceneElement] = []
    counters: dict[str, int] = {}

    local_colors: dict[str, str] = {}
    for line in lines:
        m = re.match(r'\s*(\w+)\s*=\s*["\']?(#[0-9A-Fa-f]{6})["\']?', line)
        if m:
            local_colors[m.group(1)] = m.group(2)
        m2 = re.match(r"\s*(\w+)\s*=\s*([A-Z_]+)\s*$", line)
        if m2 and m2.group(2) in _MANIM_COLORS:
            local_colors[m2.group(1)] = _MANIM_COLORS[m2.group(2)]

    var_to_element: dict[str, SceneElement] = {}

    # ── Phase 1: Parse element definitions ──
    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        for etype in _ELEMENT_TYPES:
            pattern = rf"(\w+)\s*=\s*{etype}\s*\("
            match = re.match(pattern, stripped)
            if not match:
                continue

            var_name = match.group(1)
            count = counters.get(etype, 0)
            counters[etype] = count + 1
            eid = f"{etype.lower()}_{count}"

            elem = SceneElement(
                element_id=eid,
                element_type=etype,
                variable_name=var_name,
                line_number=line_idx,
            )

            constructor_text = _extract_call(lines, line_idx - 1)
            _parse_constructor_args(elem, etype, constructor_text, local_colors)
            _apply_position_chain(elem, constructor_text, lines, line_idx - 1)

            elements.append(elem)
            var_to_element[var_name] = elem
            break

    # ── Phase 2: Standalone position updates ──
    for line_idx, line in enumerate(lines, start=1):
        stripped = line.strip()
        for var_name, elem in var_to_element.items():
            mt = re.match(rf"{re.escape(var_name)}\.move_to\((.+?)\)", stripped)
            if mt:
                px, py = _parse_point_expr(mt.group(1))
                elem.x = px
                elem.y = py
                continue

            sh = re.match(rf"{re.escape(var_name)}\.shift\((.+?)\)", stripped)
            if sh:
                dx, dy = _parse_point_expr(sh.group(1))
                elem.x += dx
                elem.y += dy
                continue

    # ── Phase 3: Timeline & Visibility tracking (self.play, self.wait, self.add) ──
    current_time = 0.0
    added_to_scene: set[str] = set()

    for line in lines:
        stripped = line.strip()

        # self.add(var1, var2, ...) -> appear immediately at current_time
        add_match = re.search(r"self\.add\(([^)]+)\)", stripped)
        if add_match:
            args = [a.strip() for a in add_match.group(1).split(",")]
            for arg in args:
                if arg in var_to_element:
                    var_to_element[arg].appear_time = min(
                        var_to_element[arg].appear_time, current_time
                    )
                    added_to_scene.add(arg)

        # self.wait(seconds)
        wait_match = re.search(r"self\.wait\(([0-9.]+)?\)", stripped)
        if wait_match:
            dur = float(wait_match.group(1)) if wait_match.group(1) else 1.0
            current_time += dur
            continue

        # self.play(..., run_time=X)
        if "self.play(" in stripped:
            run_time = 1.0
            rt_match = re.search(r"run_time\s*=\s*([0-9.]+)", stripped)
            if rt_match:
                run_time = float(rt_match.group(1))

            # Appear animations: Create, FadeIn, Write, GrowFromCenter
            for var_name, elem in var_to_element.items():
                if re.search(
                    rf"\b(Create|FadeIn|Write|GrowFromCenter)\s*\(\s*{re.escape(var_name)}\b",
                    stripped,
                ):
                    if var_name not in added_to_scene:
                        elem.appear_time = current_time
                        added_to_scene.add(var_name)

                # Disappear animations: FadeOut, Uncreate
                if re.search(
                    rf"\b(FadeOut|Uncreate)\s*\(\s*{re.escape(var_name)}\b",
                    stripped,
                ):
                    elem.disappear_time = current_time + run_time

            current_time += run_time

    # Filter out variables that were created in Python code but NEVER added to the scene
    visible_elements = [
        e.to_dict()
        for e in elements
        if e.variable_name in added_to_scene or e.appear_time == 0.0
    ]

    return visible_elements


def _extract_call(lines: list[str], start_idx: int) -> str:
    result = []
    paren_depth = 0
    for i in range(start_idx, min(start_idx + 25, len(lines))):
        line = lines[i]
        result.append(line)
        paren_depth += line.count("(") - line.count(")")
        if paren_depth <= 0 and i > start_idx:
            break
    return "\n".join(result)


def _parse_constructor_args(
    elem: SceneElement,
    etype: str,
    constructor_text: str,
    local_colors: dict[str, str],
) -> None:
    # width=...
    m = re.search(r"width\s*=\s*([0-9.]+)", constructor_text)
    if m:
        elem.width = float(m.group(1))

    # height=...
    m = re.search(r"height\s*=\s*([0-9.]+)", constructor_text)
    if m:
        elem.height = float(m.group(1))

    # radius=...
    m = re.search(r"radius\s*=\s*([0-9.]+)", constructor_text)
    if m:
        elem.radius = float(m.group(1))
        elem.width = elem.radius * 2
        elem.height = elem.radius * 2

    # color=...
    m = re.search(r'\bcolor\s*=\s*(["\']?[#\w]+["\']?)', constructor_text)
    if m:
        resolved = _resolve_color(m.group(1), local_colors)
        if resolved:
            elem.stroke_color = resolved

    # fill_color=...
    m = re.search(r'fill_color\s*=\s*(["\']?[#\w]+["\']?)', constructor_text)
    if m:
        resolved = _resolve_color(m.group(1), local_colors)
        if resolved:
            elem.fill_color = resolved

    # fill_opacity=...
    m = re.search(r"fill_opacity\s*=\s*([0-9.]+)", constructor_text)
    if m:
        elem.fill_opacity = float(m.group(1))

    # stroke_width=...
    m = re.search(r"stroke_width\s*=\s*([0-9.]+)", constructor_text)
    if m:
        elem.stroke_width = float(m.group(1))

    # font_size=...
    m = re.search(r"font_size\s*=\s*([0-9.]+)", constructor_text)
    if m:
        elem.font_size = float(m.group(1))

    # Clean text extraction for Text, MathTex, Tex
    if etype in ("Text", "MathTex", "Tex"):
        m = re.search(r'(?:Text|MathTex|Tex)\s*\(\s*["\']([^"\'\n]+)["\']', constructor_text)
        if not m:
            m = re.search(r'Text\s*\(\s*"""(.*?)"""', constructor_text, re.DOTALL)
        if m:
            elem.text = m.group(1).strip()
        else:
            elem.text = "Text"

        if elem.font_size is None:
            elem.font_size = 24.0

        char_count = max(1, len(elem.text or ""))
        elem.width = max(0.6, char_count * 0.16 * (elem.font_size / 24.0))
        elem.height = max(0.4, 0.4 * (elem.font_size / 24.0))


def _apply_position_chain(
    elem: SceneElement,
    constructor_text: str,
    lines: list[str],
    start_idx: int,
) -> None:
    full_text = constructor_text
    for i in range(start_idx + 1, min(start_idx + 5, len(lines))):
        next_line = lines[i].strip()
        if next_line.startswith(".") or next_line.startswith(")"):
            full_text += "\n" + next_line
        else:
            break

    for m in re.finditer(r"\.move_to\((.+?)\)", full_text):
        px, py = _parse_point_expr(m.group(1))
        elem.x = px
        elem.y = py

    for m in re.finditer(r"\.shift\((.+?)\)", full_text):
        dx, dy = _parse_point_expr(m.group(1))
        elem.x += dx
        elem.y += dy
