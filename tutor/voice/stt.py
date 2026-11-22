"""STT: faster-whisper (CPU int8). Wymienny: wystarczy obiekt z `transcribe(audio) -> str`."""
from __future__ import annotations

import re
from typing import Protocol

import numpy as np

# Typowe halucynacje Whispera na ciszy/szumie
_PHANTOM = {"you", "thank you", "thanks for watching", "bye", "thank you for watching", "so", "the", "uh", "um"}


class STT(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...


def is_phantom(text: str) -> bool:
    return re.sub(r"[^\w ]", "", text).strip().lower() in _PHANTOM


class WhisperSTT:
    """`model`: small.en (tylko angielski) lub small/medium (wiele języków; `language` = kod lub None = auto)."""

    def __init__(self, model="small.en", language="en", device="cpu", compute_type="int8", cpu_threads=8,
                 beam_size=1):
        from faster_whisper import WhisperModel
        self.m = WhisperModel(model, device=device, compute_type=compute_type, cpu_threads=cpu_threads)
        self.language, self.beam = (None if model.endswith(".en") and language == "en" else language), beam_size
        if model.endswith(".en"):
            self.language = "en"

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) < 1600 * 2:  # < 0,2 s
            return ""
        segs, _ = self.m.transcribe(
            audio.astype(np.float32), language=self.language, beam_size=self.beam, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400}, condition_on_previous_text=False,
            temperature=0.0, no_speech_threshold=0.6)
        parts = [s.text.strip() for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]
        text = " ".join(p for p in parts if p).strip()
        return "" if is_phantom(text) else text
