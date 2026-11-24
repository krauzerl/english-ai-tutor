"""STT: faster-whisper (CPU int8). Wymienny: wystarczy obiekt z `transcribe(audio) -> str`."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Protocol

import numpy as np

# Typowe halucynacje Whispera na ciszy/szumie
_PHANTOM = {"you", "thank you", "thanks for watching", "bye", "thank you for watching", "so", "the", "uh", "um"}


LOW_PROB = 0.5   # słowo Whispera o `probability` < 0,5 = niska pewność rozpoznania (turn_meta.low_prob_words)


@dataclass(frozen=True)
class Transcript:
    """`low_probs`: [] = Whisper podał pewność i żadne słowo nie jest niepewne; None = brak danych o pewności.
    To NIE jest ocena wymowy: niska pewność może wynikać z szumu, akcentu lub błędu uczącego się."""
    text: str
    low_probs: list[str] | None


class STT(Protocol):
    def transcribe(self, audio: np.ndarray) -> str: ...
    # opcjonalnie: transcribe_detailed(audio) -> Transcript


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

    def _run(self, audio: np.ndarray, **kw):
        segs, _ = self.m.transcribe(
            audio.astype(np.float32), language=self.language, beam_size=self.beam, vad_filter=True,
            vad_parameters={"min_silence_duration_ms": 400}, condition_on_previous_text=False,
            temperature=0.0, no_speech_threshold=0.6, **kw)
        return [s for s in segs if not (s.no_speech_prob > 0.6 and s.avg_logprob < -0.8)]

    @staticmethod
    def _text(kept) -> str:
        text = " ".join(p for p in (s.text.strip() for s in kept) if p).strip()
        return "" if is_phantom(text) else text

    def transcribe(self, audio: np.ndarray) -> str:
        if len(audio) < 1600 * 2:  # < 0,2 s
            return ""
        return self._text(self._run(audio))

    def transcribe_detailed(self, audio: np.ndarray) -> Transcript:
        """faster-whisper 1.2.1: `word_timestamps=True` ⇒ `segment.words[i].probability` (0–1). Brak słów w którymś
        zachowanym segmencie ⇒ `low_probs=None` (nie zmyślamy pewności)."""
        if len(audio) < 1600 * 2:
            return Transcript("", None)
        kept = self._run(audio, word_timestamps=True)
        text = self._text(kept)
        if not text:
            return Transcript("", None)
        if any(not getattr(s, "words", None) for s in kept if s.text.strip()):
            return Transcript(text, None)
        low = {_norm_word(w.word) for s in kept for w in s.words if w.probability < LOW_PROB}
        return Transcript(text, sorted(low - {""}))


def _norm_word(w: str) -> str:
    """Jak `assessment._t`: bez interpunkcji, apostrof prosty, małe litery (porównanie ze spanami oceny)."""
    return re.sub(r"[^\w']", "", w.replace("’", "'")).lower()
