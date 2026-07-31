"""Patch Manim scene code with user-edited element properties.

Takes the original Manim Python source code and a list of element edits
(position, color, size, text changes) and produces updated code by modifying
specific parameters at the correct source lines.

Works with the output of ``scene_parser.parse_scene_code()``.
"""

from __future__ import annotations

import re
from typing import Any


def _hex_to_quoted(color: str) -> str:
    """Ensure a color value is a quoted hex string."""
    if color.startswith("#"):
        return f'"{color}"'
    return color


def apply_element_edits(
    code: str,
    edits: list[dict[str, Any]],
) -> str:
    """Apply a list of element edits to Manim source code.

    Each edit dict must contain:
      - ``variable_name``: str — the Python variable to modify
      - ``line_number``: int — 1-indexed line where the element is defined

    And optionally:
      - ``x``, ``y``: float — new center position (Manim coords)
      - ``width``, ``height``: float — new dimensions
      - ``radius``: float — new radius (for Circle/Dot)
      - ``fill_color``: str — new fill color (hex)
      - ``fill_opacity``: float — new fill opacity
      - ``stroke_color``: str — new stroke/color (hex)
      - ``stroke_width``: float — new stroke width
      - ``text``: str — new text content (for Text elements)
      - ``font_size``: float — new font size
      - ``scale``: float — new scale factor

    Returns the modified source code.
    """
    lines = code.split("\n")

    # Sort edits by line number descending so modifications don't shift indices
    sorted_edits = sorted(edits, key=lambda e: e.get("line_number", 0), reverse=True)

    for edit in sorted_edits:
        var_name = edit.get("variable_name", "")
        line_num = edit.get("line_number", 0)
        if not var_name or line_num < 1:
            continue

        # Find the constructor block (may span multiple lines)
        start_idx = line_num - 1
        end_idx = _find_constructor_end(lines, start_idx)

        # Extract and modify the constructor block
        block = "\n".join(lines[start_idx : end_idx + 1])
        modified_block = _patch_constructor(block, edit)

        # Replace the block
        lines[start_idx : end_idx + 1] = modified_block.split("\n")

        # Apply position changes via .move_to() updates or additions
        if "x" in edit or "y" in edit:
            _patch_position(lines, var_name, edit)

    return "\n".join(lines)


def _find_constructor_end(lines: list[str], start_idx: int) -> int:
    """Find the last line of a constructor call starting at start_idx."""
    depth = 0
    for i in range(start_idx, min(start_idx + 30, len(lines))):
        depth += lines[i].count("(") - lines[i].count(")")
        if depth <= 0 and i > start_idx:
            return i
    return start_idx


def _patch_constructor(block: str, edit: dict[str, Any]) -> str:
    """Patch keyword arguments in a constructor block."""

    # Width
    if "width" in edit:
        block = re.sub(
            r"(width\s*=\s*)[0-9.]+",
            rf"\g<1>{edit['width']:.1f}",
            block,
        )

    # Height
    if "height" in edit:
        block = re.sub(
            r"(height\s*=\s*)[0-9.]+",
            rf"\g<1>{edit['height']:.1f}",
            block,
        )

    # Radius
    if "radius" in edit:
        block = re.sub(
            r"(radius\s*=\s*)[0-9.]+",
            rf"\g<1>{edit['radius']:.2f}",
            block,
        )

    # fill_color
    if "fill_color" in edit and edit["fill_color"]:
        color_val = _hex_to_quoted(edit["fill_color"])
        if re.search(r"fill_color\s*=", block):
            block = re.sub(
                r'(fill_color\s*=\s*)["\']?[#\w]+["\']?',
                rf"\g<1>{color_val}",
                block,
            )
        else:
            # Add fill_color parameter
            block = _insert_kwarg(block, f"fill_color={color_val}")

    # fill_opacity
    if "fill_opacity" in edit:
        if re.search(r"fill_opacity\s*=", block):
            block = re.sub(
                r"(fill_opacity\s*=\s*)[0-9.]+",
                rf"\g<1>{edit['fill_opacity']:.2f}",
                block,
            )

    # stroke color (color=...)
    if "stroke_color" in edit and edit["stroke_color"]:
        color_val = _hex_to_quoted(edit["stroke_color"])
        if re.search(r"\bcolor\s*=", block):
            block = re.sub(
                r'(\bcolor\s*=\s*)["\']?[#\w]+["\']?',
                rf"\g<1>{color_val}",
                block,
            )

    # stroke_width
    if "stroke_width" in edit:
        if re.search(r"stroke_width\s*=", block):
            block = re.sub(
                r"(stroke_width\s*=\s*)[0-9.]+",
                rf"\g<1>{edit['stroke_width']:.1f}",
                block,
            )

    # font_size
    if "font_size" in edit:
        if re.search(r"font_size\s*=", block):
            block = re.sub(
                r"(font_size\s*=\s*)[0-9.]+",
                rf"\g<1>{edit['font_size']:.0f}",
                block,
            )

    # Text content
    if "text" in edit and edit["text"] is not None:
        # Replace the first string literal in Text(...) or MathTex(...)
        block = re.sub(
            r'((?:Text|MathTex|Tex)\s*\(\s*["\'])(.+?)(["\'])',
            rf"\g<1>{_escape_text(edit['text'])}\g<3>",
            block,
        )

    return block


def _escape_text(text: str) -> str:
    """Escape special characters for Python string literal."""
    return text.replace("\\", "\\\\").replace('"', '\\"').replace("'", "\\'")


def _insert_kwarg(block: str, kwarg: str) -> str:
    """Insert a keyword argument before the closing parenthesis."""
    # Find the last )
    last_paren = block.rfind(")")
    if last_paren < 0:
        return block
    # Insert before the closing paren with proper formatting
    indent = "            "  # reasonable default indent
    insertion = f",\n{indent}{kwarg}"
    return block[:last_paren] + insertion + block[last_paren:]


def _patch_position(
    lines: list[str],
    var_name: str,
    edit: dict[str, Any],
) -> None:
    """Update or add .move_to() for a variable."""
    x = edit.get("x", 0.0)
    y = edit.get("y", 0.0)

    new_move_to = f".move_to([{x:.2f}, {y:.2f}, 0])"

    # First, check if there's a chained .move_to() on the constructor line(s)
    for i, line in enumerate(lines):
        # Pattern: var = Constructor(...).move_to(...)
        pattern = rf"({re.escape(var_name)}\s*=\s*.+?)\.move_to\([^)]+\)"
        if re.search(pattern, line):
            lines[i] = re.sub(
                r"\.move_to\([^)]+\)",
                new_move_to,
                line,
            )
            return

    # Check for standalone .move_to()
    for i, line in enumerate(lines):
        if re.match(rf"\s*{re.escape(var_name)}\.move_to\(", line.strip()):
            indent = len(line) - len(line.lstrip())
            lines[i] = " " * indent + f"{var_name}{new_move_to}"
            return

    # No existing move_to — find the constructor line and add one after
    for i, line in enumerate(lines):
        if re.match(rf"\s*{re.escape(var_name)}\s*=\s*\w+\(", line):
            # Find the end of the constructor
            end = _find_constructor_end(lines, i)
            indent = len(line) - len(line.lstrip())

            # Check if there's a chained .move_to() at end of constructor
            if ".move_to(" in lines[end]:
                lines[end] = re.sub(
                    r"\.move_to\([^)]+\)",
                    new_move_to,
                    lines[end],
                )
            else:
                # Append .move_to() to the last line of the constructor
                lines[end] = lines[end].rstrip()
                if lines[end].endswith(")"):
                    lines[end] = lines[end] + new_move_to
                else:
                    # Insert after constructor
                    lines.insert(
                        end + 1,
                        " " * indent + f"{var_name}{new_move_to}",
                    )
            return
