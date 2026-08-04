"""Line up each animation beat with the narration actually spoken under it.

A scene's plan pairs a `visual_action` with the `narration` said while it runs,
but codegen used to receive those two halves separately — a list of actions and
one undifferentiated blob of narration — plus an equal slice of time per beat.
The model then had to guess which animation belonged to which sentence, and a
three-word beat got exactly as many seconds as a thirty-word one. That is what
produces clips where the picture is talking about something the voice already
left behind.

This module rebuilds the pairing: it splits the measured narration audio across
beats in proportion to how long each beat's own line takes to speak, and renders
it as a timeline the code generator can follow literally.
"""

from __future__ import annotations

from dataclasses import dataclass

from backend.languages import normalize_language
from backend.schemas import SceneSection

# A beat still needs enough time to read as a deliberate move rather than a
# flicker, even when its narration is only a couple of words.
MIN_BEAT_SECONDS = 0.8
# Silent beats (a visual action with no line under it) are pure staging, so they
# get a modest slice rather than an equal share of the scene.
SILENT_BEAT_WEIGHT = 1.2


@dataclass(frozen=True)
class BeatTiming:
    index: int
    visual_action: str
    narration: str
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


def _rebalance_to_total(weights: list[float], total: float) -> list[float]:
    """Scale weights to sum to `total`, honouring MIN_BEAT_SECONDS per beat.

    Beats pinned at the floor stop absorbing scale, so the remaining time is
    redistributed across the beats that still have room.
    """
    n = len(weights)
    if n == 0:
        return []
    floor = min(MIN_BEAT_SECONDS, total / n)
    free = list(range(n))
    out = [0.0] * n

    # Pin beats up to the floor, then rescale the rest, repeating until the
    # scaled values all clear the floor on their own.
    while True:
        pinned_total = sum(out[i] for i in range(n) if i not in free)
        remaining = total - pinned_total
        weight_sum = sum(weights[i] for i in free)
        if not free or remaining <= 0:
            break
        if weight_sum <= 0:
            share = remaining / len(free)
            for i in free:
                out[i] = share
            break
        scale = remaining / weight_sum
        below = [i for i in free if weights[i] * scale < floor]
        if not below:
            for i in free:
                out[i] = weights[i] * scale
            break
        for i in below:
            out[i] = floor
            free.remove(i)

    # Absorb rounding drift into the longest beat so the sum is exact.
    drift = total - sum(out)
    if out and abs(drift) > 1e-9:
        longest = max(range(n), key=lambda i: out[i])
        out[longest] = max(0.0, out[longest] + drift)
    return out


def beat_timeline(
    scene: SceneSection,
    total_seconds: float,
    *,
    language: str = "en",
) -> list[BeatTiming]:
    """Allocate `total_seconds` of narration audio across the scene's beats.

    Time is split by each beat's own spoken length, so the animation budget
    tracks the voiceover instead of dividing the clock evenly.
    """
    # Imported here: planner pulls in the LLM client, and codegen should not
    # depend on that just to measure words.
    from backend.pipeline.planner import estimate_narration_seconds

    beats = list(scene.beats)
    if not beats or total_seconds <= 0:
        return []

    lang = normalize_language(language)
    spoken = [estimate_narration_seconds(b.narration, lang) for b in beats]
    # Prefer a real measurement when TTS already filled it in.
    weights = [
        float(b.audio_duration_seconds) if float(b.audio_duration_seconds or 0) > 0
        else (est if est > 0 else SILENT_BEAT_WEIGHT)
        for b, est in zip(beats, spoken)
    ]

    durations = _rebalance_to_total(weights, float(total_seconds))
    timings: list[BeatTiming] = []
    cursor = 0.0
    for i, (beat, dur) in enumerate(zip(beats, durations)):
        timings.append(
            BeatTiming(
                index=i,
                visual_action=beat.visual_action,
                narration=beat.narration,
                start=cursor,
                duration=dur,
            )
        )
        cursor += dur
    return timings


def format_beat_timeline(timings: list[BeatTiming]) -> str:
    """Render the timeline as prompt text the generator can follow literally."""
    if not timings:
        return "(no beats specified)"
    lines: list[str] = []
    for t in timings:
        lines.append(
            f"[{t.start:5.1f}s – {t.end:5.1f}s]  run_time≈{t.duration:.1f}s  "
            f"ANIMATE: {t.visual_action or '(hold the current frame)'}"
        )
        if t.narration.strip():
            lines.append(f'{"":>18}VOICEOVER SAYS: "{t.narration.strip()}"')
    return "\n".join(lines)


def narration_is_beat_aligned(scene: SceneSection) -> bool:
    """True when narration is genuinely split per beat.

    Plans written before beats existed (and legacy artifacts) carry the whole
    script on the first beat, so the per-beat timeline is only a rough guide
    there and the prompt should say so.
    """
    return sum(1 for b in scene.beats if b.narration.strip()) >= 2
