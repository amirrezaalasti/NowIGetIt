---
name: generate-manim-scene
description: >-
  Generate NowIGetIt Manim Community Edition scene code using the house
  template (manim_fonts / manim_visuals). Use when writing or revising Manim
  scenes, animation beats, formula panels, or educational explainer visuals
  in this repo.
---

# Generate Manim Scene (NowIGetIt)

Follow the same five template rules as the tutorial skill, adapted for this
pipeline (TTS-first + burned subtitles).

**Canonical helpers** (copied beside `scene.py` at render):

- `backend/manim_house/manim_fonts.py`
- `backend/manim_house/manim_visuals.py`

**Prompt source of truth:** `backend/pipeline/scene_generator.py` (`MANIM_SYSTEM`).

## Five rules (NowIGetIt)

1. **Consistent styling.** First line of `construct()`: `apply_scene_style(self)`.
   All `font_size=` from `TITLE_FONT_SIZE` / `SUBTITLE_FONT_SIZE` / `BODY_FONT_SIZE` /
   `LABEL_FONT_SIZE` / `FORMULA_FONT_SIZE`. Palette: import `P_*` from
   `manim_visuals` (or plan hexes) — never paste a one-off palette.
2. **Clear heading.** `scene_title` + `play_scene_title` — top-center. Never raw
   `Text(...).to_edge(UP)` / `to_corner`.
3. **Dedicated formula section.** `equation_row` → `formula_panel`; ring params
   with `highlight_param`. Text-only — never MathTex/Tex.
4. **Timing from beat timeline.** Match `self.play(run_time=...)` to the
   provided TTS beat windows. Do **not** use `NARRATION` / `hold_for` (host muxes
   audio after render).
5. **Subtitles via compose.** Do **not** use `caption_bar` / `swap_caption`
   (would double with burned VO). On-screen language = job language.

**Write()** only via `play_scene_title`. All other text: **FadeIn**.

## Skeleton

```python
from manim import *
from manim_fonts import (
    apply_scene_style, scene_title, play_scene_title,
    body_text, BODY_FONT_SIZE, LABEL_FONT_SIZE,
)
from manim_visuals import (
    P_WHITE, P_TEAL, P_ORANGE, fit_band,
    equation_row, formula_panel, highlight_param,
)

class SceneName(Scene):
    def construct(self):
        apply_scene_style(self)
        title = scene_title("…")
        play_scene_title(self, title)
        # … diagram near ORIGIN, then fit_band(group)
        # … formulas: equation_row → formula_panel
        self.wait(0.5)
```

## Checklist

- [ ] `apply_scene_style(self)` first
- [ ] `scene_title` / `play_scene_title`
- [ ] Type-scale constants only
- [ ] Formulas through `formula_panel` when present
- [ ] No `caption_bar` / `hold_for` / TeX
- [ ] Beat timeline run_times; final `self.wait(0.5)`
