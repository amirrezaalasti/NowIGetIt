"""Per-beat narration audio is what makes the animation timing measured, not guessed.

The concatenated file has to line up with the durations reported alongside it,
and every fallback has to degrade to a plain whole-scene render rather than to
silence or noise.
"""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import pytest

from backend.pipeline.tts import concat_wav_files, wav_duration_seconds

RATE = 24000


def _tone(path: Path, seconds: float, *, rate: int = RATE, channels: int = 1) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        frames = int(rate * seconds)
        wf.writeframes(
            b"".join(
                struct.pack("<h", int(3000 * math.sin(i / 20))) * channels
                for i in range(frames)
            )
        )
    return path


def test_reported_durations_tile_the_joined_file(tmp_path: Path) -> None:
    parts = [_tone(tmp_path / f"{i}.wav", d) for i, d in enumerate((1.0, 2.0, 0.5))]
    out = tmp_path / "scene.wav"
    durations = concat_wav_files(parts, out, gap_seconds=0.18)

    assert len(durations) == 3
    # Whatever the gaps, the parts must still add up to the real file length —
    # the beat timeline slices the animation against exactly these numbers.
    assert sum(durations) == pytest.approx(wav_duration_seconds(out), abs=1e-6)


def test_gap_is_inserted_between_beats_but_not_after_the_last(tmp_path: Path) -> None:
    parts = [_tone(tmp_path / f"{i}.wav", 1.0) for i in range(3)]
    out = tmp_path / "scene.wav"
    durations = concat_wav_files(parts, out, gap_seconds=0.2)

    assert durations[0] == pytest.approx(1.2)
    assert durations[1] == pytest.approx(1.2)
    assert durations[-1] == pytest.approx(1.0)


def test_no_gap_reproduces_the_source_durations(tmp_path: Path) -> None:
    parts = [_tone(tmp_path / f"{i}.wav", d) for i, d in enumerate((0.75, 1.25))]
    durations = concat_wav_files(parts, tmp_path / "out.wav")
    assert durations == pytest.approx([0.75, 1.25])


def test_mismatched_format_bails_out_instead_of_emitting_noise(tmp_path: Path) -> None:
    parts = [
        _tone(tmp_path / "a.wav", 1.0),
        _tone(tmp_path / "b.wav", 1.0, rate=16000),
    ]
    assert concat_wav_files(parts, tmp_path / "out.wav") == []


def test_missing_and_empty_inputs_are_survivable(tmp_path: Path) -> None:
    assert concat_wav_files([], tmp_path / "out.wav") == []
    good = _tone(tmp_path / "a.wav", 1.0)
    # A part that never got written is skipped, not fatal.
    durations = concat_wav_files([good, tmp_path / "missing.wav"], tmp_path / "o.wav")
    assert durations == pytest.approx([1.0])
