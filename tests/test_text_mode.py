"""F7: `--no-audio` nie ładuje Kokoro, nie wymaga PortAudio ani plików modeli TTS (regresja)."""
import sys

import pytest

from tests.llm_fakes import FakeProvider
from tests.voice_fakes import Lines
from tutor.voice import tts as TT
from tutor.voice.cli import run


@pytest.fixture
def no_voice_stack(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("tryb tekstowy nie może budować TTS")
    monkeypatch.setattr(TT, "build_tts", boom)
    monkeypatch.setattr(TT, "KokoroTTS", boom)
    for m in ("sounddevice", "onnxruntime", "kokoro_onnx", "faster_whisper"):
        monkeypatch.setitem(sys.modules, m, None)        # import => ImportError


def test_no_audio_chat_needs_no_tts_or_portaudio(repo, conn, no_voice_stack):
    repo.create_profile("ann")
    out = []
    code = run(["--voice", "--profile", "ann", "--no-audio", "--summary-wait", "0", "--chat", "fd.cooking"],
               llm=FakeProvider(chunks=["Nice. ", "Go on."]), lines=Lines("I like soup", "q"),
               out=out.append, db=conn)
    assert code == 0
    assert any(s.startswith("Tutor: Nice.") for s in out)
    assert any("TTS: none/-" in s for s in out)


def test_no_audio_lesson_needs_no_tts(repo, conn, no_voice_stack):
    repo.create_profile("ann")
    out = []
    code = run(["--voice", "--profile", "ann", "--no-audio", "--summary-wait", "0", "--lesson"],
               llm=FakeProvider(chunks=["Ok."]), lines=Lines("q"), out=out.append, db=conn)
    assert code == 0
    assert any(s.startswith("Cel lekcji:") for s in out)


def test_silent_tts_is_empty():
    assert TT.SilentTTS().synth("Hello").size == 0
