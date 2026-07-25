"""Render a real visual preview frame when Manim isn't available.

Plan cards are useful metadata; this module draws an actual still
(axes, curves, markers) so debug/VLM artifacts look like the scene.
"""

from __future__ import annotations

import re
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from backend.schemas import SceneSection


def create_visual_preview(
    scene: SceneSection,
    *,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
) -> str:
    """Draw a concept still from the scene brief. Returns output path."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    text_blob = " ".join(
        [
            scene.title,
            scene.visual_description,
            " ".join(scene.animation_beats),
            scene.narration,
        ]
    ).lower()

    fig_w, fig_h = width / 100, height / 100
    fig, ax = plt.subplots(figsize=(fig_w, fig_h), dpi=100)
    fig.patch.set_facecolor("#0c1412")
    ax.set_facecolor("#13201c")

    # Default view
    x = np.linspace(-2.5, 2.5, 400)
    drew_curve = False

    if any(k in text_blob for k in ("parabola", "x^2", "x²", "x squared", "loss")):
        y = x**2
        ax.plot(x, y, color="#f0c75e", linewidth=3.2, solid_capstyle="round")
        ax.plot(x, y, color="#f0c75e", linewidth=10, alpha=0.18)
        drew_curve = True
        ax.set_xlim(-2.6, 2.6)
        ax.set_ylim(-0.4, 5.2)
    elif "sine" in text_blob or "sin(" in text_blob:
        y = np.sin(x * 1.2)
        ax.plot(x, y, color="#3ecf8e", linewidth=3)
        drew_curve = True
        ax.set_xlim(-2.6, 2.6)
        ax.set_ylim(-1.6, 1.6)
    else:
        # Gentle placeholder curve so the frame still feels like a graph scene
        y = 0.35 * x**2 + 0.2
        ax.plot(x, y, color="#9bb0a6", linewidth=2.5, alpha=0.85)
        drew_curve = True
        ax.set_xlim(-2.6, 2.6)
        ax.set_ylim(-0.4, 3.5)

    # Axes styling
    ax.axhline(0, color="#5a7268", linewidth=1.2)
    ax.axvline(0, color="#5a7268", linewidth=1.2)
    ax.grid(True, color="#1c2e28", linewidth=0.8)
    ax.tick_params(colors="#9bb0a6", labelsize=11)
    for spine in ax.spines.values():
        spine.set_color("#3a5248")

    # Minimum / target at origin for loss/parabola scenes
    if any(k in text_blob for k in ("minimum", "origin", "(0,0)", "(0, 0)", "lowest")):
        ax.scatter([0], [0], s=180, c="#3ecf8e", zorder=5, edgecolors="#e8f0ec", linewidths=1.2)
        ax.scatter([0], [0], s=700, c="#3ecf8e", alpha=0.22, zorder=4)
        ax.text(
            0.08,
            -0.45,
            "Minimum Loss",
            color="#3ecf8e",
            fontsize=13,
            ha="left",
            va="top",
        )

    # Point like (3, 9) — scale into view if needed
    point_match = re.search(r"\((-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\)", text_blob)
    if point_match and "0,0" not in point_match.group(0).replace(" ", ""):
        px, py = float(point_match.group(1)), float(point_match.group(2))
        # Remap large coords onto the visible parabola domain when needed
        if abs(px) > 2.5 or py > 5.5:
            # Keep x on curve domain; plot on y=x^2 when parabola scene
            if drew_curve and ("parabola" in text_blob or "x^2" in text_blob):
                px = np.clip(px, -2.2, 2.2)
                # Prefer the described x if small enough else use sign*1.8
                if abs(float(point_match.group(1))) > 2.5:
                    px = 1.8 if float(point_match.group(1)) > 0 else -1.8
                py = px**2
        ax.scatter([px], [py], s=140, c="#ff5a5a", zorder=6)
        ax.text(px + 0.1, py + 0.25, f"({px:.1f}, {py:.1f})", color="#ffb4b4", fontsize=11)

    # Tangent hint
    if "tangent" in text_blob or "slope" in text_blob:
        tx = 1.5
        # y = x^2 => slope 2x
        slope = 2 * tx
        yy0 = tx**2
        xs = np.array([tx - 0.7, tx + 0.7])
        ys = yy0 + slope * (xs - tx)
        ax.plot(xs, ys, color="#ff8a3d", linewidth=2.4, solid_capstyle="round")
        ax.annotate(
            "slope",
            xy=(tx + 0.35, yy0 + slope * 0.35),
            xytext=(tx + 0.7, yy0 + 1.1),
            color="#ff8a3d",
            fontsize=11,
            arrowprops=dict(arrowstyle="->", color="#ff8a3d", lw=1.2),
        )

    # Title banner
    ax.set_title(
        scene.title,
        color="#e8f0ec",
        fontsize=20,
        pad=14,
        loc="left",
        fontweight="bold",
    )
    fig.text(
        0.012,
        0.015,
        "visual preview (matplotlib) · Manim render disabled",
        color="#6f857b",
        fontsize=9,
    )

    fig.tight_layout(rect=(0.02, 0.04, 0.98, 0.96))
    fig.savefig(output_path, facecolor=fig.get_facecolor(), edgecolor="none")
    plt.close(fig)
    return str(output_path)
