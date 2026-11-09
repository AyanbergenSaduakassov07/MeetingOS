"""Build a messy multi-speaker meeting WAV for transcription checks.

macOS only (uses `say`). Pauses, sighs, fast speech, fillers, overlap, room hiss
and one Russian aside; writes <out>.truth.json with the spoken lines.

    .venv/bin/python scripts/make_messy_meeting.py /tmp/meeting.wav
"""

import json
import re
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np

SR = 16000
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "meeting.wav")
rng = np.random.default_rng(7)

# (speaker, voice, rate wpm, text) | ("pause", seconds) | ("sigh",) | ("overlap", turnA, turnB)
SCRIPT = [
    (
        "Priya",
        "Samantha",
        175,
        "Okay, um, let's get started. Can everyone hear me? [[slnc 600]] Good.",
    ),
    (
        "Priya",
        "Samantha",
        175,
        "First thing is the demo day venue. We, uh, we still haven't booked anything.",
    ),
    ("pause", 2.5),
    (
        "Daniel",
        "Daniel",
        165,
        "Right. So [[slnc 900]] I called the main hall yesterday, and they said the fourteenth is free.",
    ),
    ("sigh",),
    (
        "Daniel",
        "Daniel",
        160,
        "But it costs four hundred dollars, which is, honestly, more than we hoped.",
    ),
    (
        "Karen",
        "Karen",
        290,
        "Look we've got the sponsor money coming in so four hundred is fine as long as the transfer actually clears this week which it should because they confirmed on Monday.",
    ),
    ("pause", 1.2),
    (
        "Priya",
        "Samantha",
        170,
        "Okay. So are we agreed? We book the main hall for the fourteenth.",
    ),
    (
        "overlap",
        ("Daniel", "Daniel", 180, "Yes, agreed."),
        ("Karen", "Karen", 180, "Yeah, let's do it."),
    ),
    ("Priya", "Samantha", 170, "Great. Daniel, can you book it by Wednesday?"),
    ("Daniel", "Daniel", 170, "Sure, I'll book it by Wednesday."),
    ("pause", 6.0),
    ("sigh",),
    (
        "Rishi",
        "Rishi",
        175,
        "Sorry, I was on mute. Um. [[slnc 700]] One risk. If the sponsor money doesn't arrive, we can't pay the deposit.",
    ),
    (
        "Karen",
        "Karen",
        280,
        "Then I'll email the sponsor tomorrow morning and ask them for a firm date on the transfer, I'll copy everyone.",
    ),
    (
        "Milena",
        "Milena",
        170,
        "Если деньги не придут, можно подать заявку на университетский грант.",
    ),
    (
        "Priya",
        "Samantha",
        165,
        "Good point, a university grant as a backup. Let's not decide that today. [[slnc 800]] Okay, uh, that's everything. Thanks all.",
    ),
]


def say(voice, rate, text, tmp=Path("tmp.wav")):
    subprocess.run(
        [
            "say",
            "-v",
            voice,
            "-r",
            str(rate),
            "--data-format=LEI16@16000",
            "-o",
            str(tmp),
            text,
        ],
        check=True,
    )
    with wave.open(str(tmp)) as w:
        return (
            np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(
                np.float32
            )
            / 32768
        )


def sigh(seconds=1.1):
    n = int(SR * seconds)
    noise = rng.standard_normal(n)
    # crude low-pass: moving average, then a breathy rise-and-fall envelope
    noise = np.convolve(noise, np.ones(12) / 12, mode="same")
    env = np.sin(np.linspace(0, np.pi, n)) ** 2
    return (noise * env * 0.12).astype(np.float32)


chunks, truth, t = [], [], 0.0


def push(audio, label=None):
    global t
    chunks.append(audio)
    if label:
        truth.append(
            {"start": round(t, 2), "end": round(t + len(audio) / SR, 2), **label}
        )
    t += len(audio) / SR


for item in SCRIPT:
    kind = item[0]
    if kind == "pause":
        push(np.zeros(int(SR * item[1]), np.float32))
    elif kind == "sigh":
        push(sigh(), {"speaker": None, "text": "(sigh)"})
    elif kind == "overlap":
        a = say(*item[1][1:])
        b = say(*item[2][1:])
        offset = int(len(a) * 0.4)  # B starts while A is still talking
        mix = np.zeros(max(len(a), offset + len(b)), np.float32)
        mix[: len(a)] += a
        mix[offset : offset + len(b)] += b
        push(
            mix,
            {
                "speaker": f"{item[1][0]}+{item[2][0]}",
                "text": f"{item[1][3]} / {item[2][3]}",
            },
        )
    else:
        spk, voice, rate, text = item
        push(
            say(voice, rate, text),
            {"speaker": spk, "text": re.sub(r"\[\[.*?\]\]\s*", "", text)},
        )
    push(np.zeros(int(SR * rng.uniform(0.15, 0.45)), np.float32))  # natural turn gap

audio = np.concatenate(chunks)
audio += rng.standard_normal(len(audio)).astype(np.float32) * 0.004  # room hiss
audio = np.clip(audio, -1, 1)
with wave.open(str(OUT), "wb") as w:
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((audio * 32767).astype(np.int16).tobytes())
OUT.with_suffix(".truth.json").write_text(
    json.dumps(truth, ensure_ascii=False, indent=1)
)
print(f"{OUT}: {len(audio) / SR:.1f}s, {len(truth)} labelled turns")
