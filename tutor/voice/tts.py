"""TTS: wymienny interfejs. KokoroTTS (Apache-2.0), PiperTTS. Oba CPU. `synth(text) -> float32 mono`."""
from __future__ import annotations

from pathlib import Path
from typing import Protocol

import numpy as np

from tutor import config

MODELS = config.data_dir() / "models"
DEFAULT_VOICE = {"kokoro": "bf_emma", "piper": "en_GB-alba-medium"}


class TTS(Protocol):
    name: str
    voice: str
    sample_rate: int

    def synth(self, text: str) -> np.ndarray: ...


class KokoroTTS:
    name = "kokoro"
    sample_rate = 24000

    def __init__(self, voice="bf_emma", speed=1.0, models: Path = MODELS, threads=4):
        import onnxruntime as ort
        from kokoro_onnx import Kokoro
        o = ort.SessionOptions()
        o.intra_op_num_threads = threads
        sess = ort.InferenceSession(str(models / "kokoro/kokoro-v1.0.int8.onnx"), o,
                                    providers=["CPUExecutionProvider"])
        self.k = Kokoro.from_session(sess, str(models / "kokoro/voices-v1.0.bin"))
        self.voice, self.speed = voice, speed
        self.lang = "en-gb" if voice.startswith("b") else "en-us"

    def synth(self, text: str) -> np.ndarray:
        a, sr = self.k.create(text, voice=self.voice, speed=self.speed, lang=self.lang)
        self.sample_rate = sr
        return a.astype(np.float32)


class PiperTTS:
    name = "piper"

    def __init__(self, voice="en_GB-alba-medium", speed=1.0, models: Path = MODELS):
        from piper import PiperVoice, SynthesisConfig
        self.v = PiperVoice.load(models / f"piper/{voice}.onnx")
        self.voice, self.sample_rate = voice, self.v.config.sample_rate
        self.cfg = SynthesisConfig(length_scale=1.0 / speed)

    def synth(self, text: str) -> np.ndarray:
        parts = [c.audio_int16_array for c in self.v.synthesize(text, self.cfg)]
        return (np.concatenate(parts) if parts else np.zeros(0, np.int16)).astype(np.float32) / 32768.0


class SilentTTS:
    """Tryb tekstowy (`--no-audio`): bez modelu, bez PortAudio, bez pobierania czegokolwiek."""
    name, voice, sample_rate = "none", "-", 24000

    def synth(self, text: str) -> np.ndarray:
        return np.zeros(0, np.float32)


def build_tts(name: str, voice: str | None = None, speed: float = 1.0) -> TTS:
    voice = voice or DEFAULT_VOICE[name]
    if name == "kokoro":
        return KokoroTTS(voice, speed)
    if name == "piper":
        return PiperTTS(voice, speed)
    raise ValueError(f"Nieznany silnik TTS: {name}")
