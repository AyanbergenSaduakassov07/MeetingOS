"""Original audio for the launch film, synthesized from scratch with numpy.

Writes into marketing-video/public/audio/:
  score.wav  60 s ambient score: a slow pad, low hits on the scene cuts,
             soft UI ticks, and a resolving chord on the logo.
  voice.wav  6.5 s of the AMI meeting (CC BY 4.0) where the team states the
             price, played under the transcript shot.  Needs FILM_AMI_WAV.
And src/peaks.json: 96 loudness bars from that same meeting audio, drawn in
the opening scene (a real meeting's waveform, not decoration).

Usage: .venv/bin/python marketing-video/scripts/make_audio.py
"""

from __future__ import annotations

import json
import logging
import os
import wave
from pathlib import Path

import numpy as np

RATE = 48_000
LENGTH_S = 60.0
ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "public" / "audio"

CUTS_S = (7.0, 14.0, 28.0, 43.0, 53.0)  # scene boundaries, must match src/timing.ts
# UI ticks: consent checkbox, upload click, copilot send, answer lands.
TICKS_S = (16.2, 17.6, 45.0, 47.57)
VOICE_FROM_S, VOICE_LEN_S = 470.6, 6.5  # "...selling this remote control for 25 euro"

logger = logging.getLogger("make_audio")


def hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def envelope(t: np.ndarray, start: float, end: float, fade: float) -> np.ndarray:
    rise = np.clip((t - start) / fade, 0, 1)
    fall = np.clip((end - t) / fade, 0, 1)
    return np.sin(rise * np.pi / 2) ** 2 * np.sin(fall * np.pi / 2) ** 2


def pad(t: np.ndarray, chords: list[tuple[float, float, list[int]]]) -> np.ndarray:
    """Detuned sine voices per chord, cross-faded; soft and wide."""
    left = np.zeros_like(t)
    right = np.zeros_like(t)
    for start, end, notes in chords:
        env = envelope(t, start, end, 2.5)
        for index, note in enumerate(notes):
            f = hz(note)
            wobble = 0.0015 * np.sin(2 * np.pi * 0.11 * t + index)
            voice_l = np.sin(2 * np.pi * f * (1 - 0.0012 + wobble) * t)
            voice_r = np.sin(2 * np.pi * f * (1 + 0.0012 - wobble) * t + 0.7)
            gain = 0.11 / (1 + index * 0.35)
            left += env * gain * (voice_l + 0.18 * np.sin(4 * np.pi * f * t))
            right += env * gain * (voice_r + 0.18 * np.sin(4 * np.pi * f * t + 0.3))
    return np.stack([left, right])


def hit(t: np.ndarray, at: float, strength: float) -> np.ndarray:
    """A low, felt impact: pitch-dropping sine plus a short air puff."""
    local = t - at
    on = local >= 0
    local = np.where(on, local, 0)
    pitch = 52 + 40 * np.exp(-local * 18)
    body = np.sin(2 * np.pi * np.cumsum(pitch) / RATE) * np.exp(-local * 3.2)
    rng = np.random.default_rng(int(at * 100))
    air = rng.standard_normal(t.size) * np.exp(-local * 30) * 0.05
    return on * strength * (body + air)


def tick(t: np.ndarray, at: float) -> np.ndarray:
    local = t - at
    on = (local >= 0) & (local < 0.06)
    return (
        on
        * 0.09
        * np.sin(2 * np.pi * 2400 * local)
        * np.exp(-np.clip(local, 0, None) * 90)
    )


def riser(t: np.ndarray, start: float, end: float) -> np.ndarray:
    span = np.clip((t - start) / (end - start), 0, 1)
    rng = np.random.default_rng(7)
    noise = np.convolve(rng.standard_normal(t.size), np.ones(24) / 24, mode="same")
    return (t < end) * noise * span**3 * 0.22


def build_score() -> np.ndarray:
    t = np.arange(int(RATE * LENGTH_S)) / RATE
    # D minor colour that opens up, then resolves to D major on the logo.
    chords = [
        (0.0, 15.0, [38, 50, 57, 62, 65]),  # Dm add9 feel
        (13.0, 29.0, [34, 46, 53, 58, 62, 69]),  # Bb maj7
        (27.0, 44.0, [41, 53, 60, 65, 69, 72]),  # F add9
        (42.0, 54.5, [36, 48, 55, 60, 64, 67]),  # C
        (53.0, 62.0, [38, 50, 57, 62, 66, 69, 74]),  # D major: resolve
    ]
    music = pad(t, chords)
    mono = sum(hit(t, cut, 0.55 if cut != 53.0 else 0.8) for cut in CUTS_S)
    mono = mono + sum(tick(t, at) for at in TICKS_S) + riser(t, 49.5, 53.0)
    music = music + np.stack([mono, mono])
    master = envelope(t, 0.0, LENGTH_S, 1.2) * np.clip(1 - (t - 57.5) / 2.5, 0, 1)
    music *= master
    return music / np.max(np.abs(music)) * 0.84


def write_wav(path: Path, stereo: np.ndarray, rate: int = RATE) -> None:
    pcm = (np.clip(stereo.T, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as out:
        out.setnchannels(stereo.shape[0])
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm.tobytes())
    logger.info("wrote %s", path)


def read_mono(path: Path, start_s: float, length_s: float) -> tuple[np.ndarray, int]:
    with wave.open(str(path)) as source:
        rate, channels, width = (
            source.getframerate(),
            source.getnchannels(),
            source.getsampwidth(),
        )
        if width != 2:
            raise ValueError(f"{path}: expected 16-bit PCM, got {width * 8}-bit")
        source.setpos(int(start_s * rate))
        raw = source.readframes(int(length_s * rate))
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float64) / 32768
    return samples.reshape(-1, channels).mean(axis=1), rate


def voice_and_peaks(ami: Path) -> None:
    voice, rate = read_mono(ami, VOICE_FROM_S, VOICE_LEN_S)
    fade = np.minimum(
        1,
        np.minimum(np.arange(voice.size), np.arange(voice.size)[::-1]) / (0.08 * rate),
    )
    voice = voice * fade / max(np.max(np.abs(voice)), 1e-9) * 0.9
    write_wav(AUDIO / "voice.wav", np.stack([voice, voice]), rate)

    meeting, _ = read_mono(ami, 440.0, 96.0)
    rms = np.sqrt(
        np.mean(meeting[: meeting.size // 96 * 96].reshape(96, -1) ** 2, axis=1)
    )
    peaks = np.round(rms / rms.max(), 3).tolist()
    (ROOT / "src" / "peaks.json").write_text(json.dumps(peaks))
    logger.info("wrote peaks.json (%d bars)", len(peaks))


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    AUDIO.mkdir(parents=True, exist_ok=True)
    score = build_score()
    assert score.shape == (2, int(RATE * LENGTH_S)) and np.max(np.abs(score)) <= 0.85
    write_wav(AUDIO / "score.wav", score)
    ami = Path(os.environ.get("FILM_AMI_WAV", ""))
    if ami.is_file():
        voice_and_peaks(ami)
    else:
        logger.warning(
            "FILM_AMI_WAV not set: kept the existing voice.wav and peaks.json"
        )


if __name__ == "__main__":
    main()
