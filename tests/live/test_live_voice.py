"""Testy live głosu (`pytest -m live`): prawdziwe modele CPU i (jeśli jest) mikrofon. Bez rozmowy z człowiekiem."""
import time

import numpy as np
import pytest

from tutor.voice import audio as A
from tutor.voice.tts import MODELS, build_tts

pytestmark = pytest.mark.live
TEXT = "I went to London last weekend and visited a museum."


def need(path):
    if not (MODELS / path).exists():
        pytest.skip(f"brak modelu {path} (patrz docs/ai-work/03_VOICE_REPORT.md)")


def to16k(a, sr):
    return np.interp(np.arange(0, len(a), sr / 16000), np.arange(len(a)), a).astype(np.float32)


@pytest.mark.parametrize("eng,voice,probe", [("kokoro", "bf_emma", "kokoro/voices-v1.0.bin"),
                                             ("piper", "en_GB-alba-medium", "piper/en_GB-alba-medium.onnx")])
def test_tts_engine_makes_speech(eng, voice, probe):
    need(probe)
    t = build_tts(eng, voice)
    a = t.synth(TEXT)
    assert a.dtype == np.float32 and 2 < len(a) / t.sample_rate < 8 and np.abs(a).max() > 0.1


def test_stt_roundtrip_on_synthetic_speech():
    need("piper/en_US-lessac-medium.onnx")
    from tutor.voice.stt import WhisperSTT
    t = build_tts("piper", "en_US-lessac-medium")
    audio = to16k(t.synth(TEXT), t.sample_rate)
    stt = WhisperSTT("small.en")
    t0 = time.monotonic()
    text = stt.transcribe(audio)
    assert time.monotonic() - t0 < 6
    assert "london" in text.lower() and "museum" in text.lower()


def test_stt_silence_and_noise_give_empty_text():
    from tutor.voice.stt import WhisperSTT
    stt = WhisperSTT("small.en")
    rng = np.random.default_rng(1)
    assert stt.transcribe(np.zeros(16000 * 3, np.float32)) == ""
    assert stt.transcribe((0.01 * rng.standard_normal(16000 * 3)).astype(np.float32)) == ""
    assert stt.transcribe(np.zeros(100, np.float32)) == ""


def test_mic_captures_frames_if_present():
    mic = A.Mic()
    try:
        mic.open()
    except A.AudioUnavailable as e:
        pytest.skip(str(e))
    try:
        time.sleep(1.0)
        n = mic.q.qsize()
    finally:
        mic.close()
    assert n >= 20  # ~33 bloków/s


def test_speaker_opens_and_stops():
    sp = A.Speaker()
    try:
        sp.start(24000)
    except A.AudioUnavailable as e:
        pytest.skip(str(e))
    sp.write(np.zeros(2400, np.float32))
    sp.seal()
    sp.drain(timeout=2)
    sp.write(np.zeros(240000, np.float32))
    sp.stop()
    assert not sp.playing
    sp.close()
