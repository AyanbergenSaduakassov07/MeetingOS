"""faster_whisper runs locally; the real model is replaced by a fake here."""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace

import pytest

from backend.transcription import get_transcription_provider, reset_providers
from backend.transcription.base import TranscriptionError
from backend.transcription.providers.faster_whisper_provider import FasterWhisperProvider


class FakeWhisperModel:
    def __init__(self, model, device, compute_type):
        self.model = model

    def transcribe(self, path, language=None, initial_prompt=None):
        segments = iter(
            [
                SimpleNamespace(start=0.0, end=2.5, text=" Book the hall. "),
                SimpleNamespace(start=2.5, end=3.0, text="  "),
                SimpleNamespace(start=3.0, end=4.25, text="Agreed."),
            ]
        )
        return segments, SimpleNamespace(language="en", duration=4.25)


@pytest.fixture
def fake_faster_whisper(monkeypatch):
    module = types.ModuleType("faster_whisper")
    module.WhisperModel = FakeWhisperModel
    monkeypatch.setitem(sys.modules, "faster_whisper", module)


async def test_maps_segments_to_ms_and_drops_blank_ones(fake_faster_whisper, tmp_path):
    result = await FasterWhisperProvider().transcribe(tmp_path / "a.wav")

    assert [(s.start_ms, s.end_ms, s.text) for s in result.segments] == [
        (0, 2500, "Book the hall."),
        (3000, 4250, "Agreed."),
    ]
    assert result.language == "en"
    assert result.duration_seconds == 4.25


async def test_missing_package_gives_install_hint(monkeypatch, tmp_path):
    monkeypatch.setitem(sys.modules, "faster_whisper", None)  # import raises ImportError
    with pytest.raises(TranscriptionError, match="uv pip install faster-whisper"):
        await FasterWhisperProvider().transcribe(tmp_path / "a.wav")


def test_selectable_by_env_and_local(monkeypatch):
    monkeypatch.setenv("TRANSCRIPTION_PROVIDER", "faster_whisper")
    reset_providers()
    try:
        provider = get_transcription_provider()
        assert provider.config.name == "faster_whisper"
        assert provider.config.base_url is None and provider.config.api_key_env is None
    finally:
        reset_providers()
