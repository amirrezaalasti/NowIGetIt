"""Turn a teaching blueprint into a spoken podcast, then TTS it."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Optional

from backend.languages import language_display_name, normalize_language
from backend.learn.schemas import PodcastChapter, PodcastScript
from backend.llm import OpenRouterClient
from backend.pipeline.pedagogy import format_blueprint_for_planner
from backend.pipeline.tts import (
    concat_wav_files,
    synthesize_narration,
    wav_duration_seconds,
)
from backend.schemas import TeachingBlueprint

Progress = Callable[[str, dict[str, Any]], None]

PODCAST_SYSTEM = """You write educational podcast scripts that make a concept click.

You are NOT writing a lecture. You are writing a conversation (or a solo
narration) a curious learner would actually finish.

STYLE:
- Dialogue: two people. HOST is the learner — asks the questions a real person
  would, admits confusion, guesses, reacts. GUIDE is the teacher — answers with
  pictures in words, works the running example with real numbers, never dumps
  a definition and walks away.
- Solo: one warm narrator who still uses "you" and works the example out loud.
- Short spoken sentences. No bullet lists. No "in this episode we will".
- Every abstract claim is demonstrated on the running example with real numbers.
- When a formula appears, SPEAK it as a sentence about the world first
  ("the next step is the current x minus a slice of the slope") and only then
  name the symbols.

STRUCTURE:
- One chapter per teaching step, in that order. Chapter id matches the step id.
- 2–6 lines per chapter for short; 4–8 for standard; 6–10 for deep.
- Host speaks first in dialogue (a question or a wrong guess). Guide answers.
- Last chapter lands the payoff: what the listener can now do.

Return ONLY JSON:
{
  "title": string,
  "tagline": string (one sentence),
  "style": "dialogue" | "solo",
  "host_name": string,
  "guide_name": string,
  "chapters": [
    {
      "id": "step_1",
      "title": string,
      "covers_step": "step_1",
      "summary": string,
      "lines": [{"speaker": "host"|"guide", "text": string}]
    }
  ],
  "takeaways": [string, string, string]
}
"""


def generate_podcast_script(
    client: OpenRouterClient,
    prompt: str,
    blueprint: TeachingBlueprint,
    *,
    audience: str = "general",
    language: str = "en",
    length_preset: str = "standard",
    style: str = "dialogue",
    on_progress: Optional[Progress] = None,
) -> PodcastScript:
    lang = normalize_language(language)
    lang_name = language_display_name(lang)
    density = {
        "short": "4–6 chapters, 2–5 spoken lines each, about 4 minutes",
        "standard": "5–8 chapters, 4–7 spoken lines each, about 8 minutes",
        "deep": "6–10 chapters, 6–10 spoken lines each, about 15 minutes",
    }.get(length_preset, "5–8 chapters, about 8 minutes")

    user = f"""Learner prompt:
{prompt}

Audience: {audience}
Output language: write ALL spoken text in {lang_name}.
Requested style: {style}
Length: {density}

Teaching plan (follow this order; one chapter per step):
{format_blueprint_for_planner(blueprint)}
"""
    last_err: Optional[Exception] = None
    for attempt in range(3):
        if on_progress:
            on_progress(
                f"Writing the episode (attempt {attempt + 1}/3)…",
                {"step": "podcast.script", "attempt": attempt + 1},
            )
        try:
            data = client.chat_json(
                system=PODCAST_SYSTEM,
                user=user,
                temperature=0.45 + attempt * 0.1,
                max_tokens=8192,
            )
            script = PodcastScript.model_validate(data)
            _validate_script(script, blueprint, style=style)
            return script
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            user += f"\n\nERROR on last attempt: {exc}\nReturn valid JSON matching the schema."
    raise ValueError(f"Failed to write podcast script: {last_err}") from last_err


def _validate_script(
    script: PodcastScript, blueprint: TeachingBlueprint, *, style: str
) -> None:
    if len(script.chapters) < 2:
        raise ValueError("podcast needs at least 2 chapters")
    empty = [c.id for c in script.chapters if not c.lines]
    if empty:
        raise ValueError(f"chapters with no lines: {', '.join(empty[:5])}")
    if style == "dialogue":
        speakers = {line.speaker for ch in script.chapters for line in ch.lines}
        if speakers == {"guide"} or speakers == {"host"}:
            raise ValueError("dialogue podcasts need both host and guide speaking")
    # Keep chapter ids stable even if the model used titles.
    step_ids = [s.id for s in blueprint.steps]
    for index, chapter in enumerate(script.chapters):
        if not chapter.covers_step and index < len(step_ids):
            chapter.covers_step = step_ids[index]
        if not chapter.id:
            chapter.id = chapter.covers_step or f"ch_{index + 1}"


def synthesize_podcast_audio(
    script: PodcastScript,
    output_path: Path,
    *,
    host_voice: str,
    guide_voice: str,
    on_progress: Optional[Progress] = None,
) -> tuple[Optional[str], bool, list[PodcastChapter]]:
    """TTS every line, concat, stamp chapter start times. WAV on disk."""
    output_path = Path(output_path)
    parts_dir = output_path.parent / "audio_parts"
    parts_dir.mkdir(parents=True, exist_ok=True)
    parts: list[Path] = []
    chapter_part_counts: list[int] = []
    total_lines = sum(len(ch.lines) for ch in script.chapters)
    done = 0

    for ci, chapter in enumerate(script.chapters):
        count = 0
        for li, line in enumerate(chapter.lines):
            text = (line.text or "").strip()
            if not text:
                continue
            voice = host_voice if line.speaker == "host" else guide_voice
            dest = parts_dir / f"{ci:02d}_{li:02d}.wav"
            if on_progress:
                on_progress(
                    f"Recording {chapter.title} ({done + 1}/{max(total_lines, 1)})…",
                    {
                        "step": "podcast.tts",
                        "chapter": chapter.id,
                        "line": li,
                        "done": done,
                        "total": total_lines,
                    },
                )
            path, skipped = synthesize_narration(text, dest, voice=voice)
            if skipped or not path:
                return None, True, script.chapters
            parts.append(Path(path))
            count += 1
            done += 1
        chapter_part_counts.append(count)

    if not parts:
        return None, True, script.chapters

    wav_path = output_path.with_suffix(".wav")
    durations = concat_wav_files(parts, wav_path, gap_seconds=0.28)
    if not durations:
        # Fallback: one file for the whole script.
        joined = " ".join(line.text for ch in script.chapters for line in ch.lines)
        path, skipped = synthesize_narration(joined, wav_path, voice=guide_voice)
        if skipped or not path:
            return None, True, script.chapters
        total = wav_duration_seconds(Path(path))
        stamped = []
        start = 0.0
        share = total / max(len(script.chapters), 1)
        for chapter in script.chapters:
            stamped.append(
                chapter.model_copy(
                    update={"start_seconds": start, "duration_seconds": share}
                )
            )
            start += share
        return str(Path(path)), False, stamped

    stamped: list[PodcastChapter] = []
    cursor = 0
    t = 0.0
    for chapter, n in zip(script.chapters, chapter_part_counts):
        chunk = durations[cursor : cursor + n]
        cursor += n
        dur = float(sum(chunk))
        stamped.append(
            chapter.model_copy(update={"start_seconds": t, "duration_seconds": dur})
        )
        t += dur
    return str(wav_path), False, stamped
