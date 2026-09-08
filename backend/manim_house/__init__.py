"""House Manim style: serif type scale + shared palette/layout/formula helpers.

Copied next to each ``scene.py`` at render time so generated code can
``from manim_fonts import …`` / ``from manim_visuals import …``.
"""

from __future__ import annotations

import shutil
from pathlib import Path

_HOUSE_DIR = Path(__file__).resolve().parent
_HOUSE_FILES = ("manim_fonts.py", "manim_visuals.py")


def house_module_paths() -> list[Path]:
    return [_HOUSE_DIR / name for name in _HOUSE_FILES]


def stage_house_modules(dest_dir: Path) -> list[Path]:
    """Copy house helpers into ``dest_dir`` (usually the scene work directory)."""
    dest = Path(dest_dir)
    dest.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for src in house_module_paths():
        if not src.is_file():
            continue
        target = dest / src.name
        shutil.copy2(src, target)
        written.append(target)
    return written
