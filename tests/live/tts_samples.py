"""Próbki TTS z identycznym tekstem + pomiar czasu i zasobów. Wyjście poza repo (licencje głosów).

PYTHONPATH=. .venv/bin/python tests/live/tts_samples.py [katalog]
"""
import json
import resource
import sys
import time
import wave
from pathlib import Path

import numpy as np

from tutor import config
from tutor.voice.tts import build_tts

TEXTS = {
    "1_greeting": "Hi, nice to see you again! How was your weekend? Did you do anything fun?",
    "2_explain": ("Last Wednesday, I read a book about the history of London. It was thorough, but quite "
                  "comfortable to read, and it only cost twelve pounds fifty."),
    "3_correct": ("Good try! We usually say, I went to the cinema yesterday, not I go. "
                  "Now, tell me, what kind of films do you enjoy?"),
    "4_hard": "I'd rather schedule it for February. Is that all right, or would you prefer a different day?",
}
VOICES = [("kokoro", v) for v in ("bf_emma", "bf_isabella", "bm_george", "af_heart", "af_bella", "am_michael")] + \
         [("piper", v) for v in ("en_GB-alba-medium", "en_GB-jenny_dioco-medium", "en_US-lessac-medium",
                                  "en_US-amy-medium", "en_US-ryan-high")]


def save(path: Path, a: np.ndarray, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(sr)
        w.writeframes((np.clip(a, -1, 1) * 32767).astype(np.int16).tobytes())


def main(out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for eng, voice in VOICES:
        r0 = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        t0 = time.monotonic()
        tts = build_tts(eng, voice)
        load = time.monotonic() - t0
        tts.synth("Warm up.")
        for key, text in TEXTS.items():
            t = time.monotonic()
            a = tts.synth(text)
            dt = time.monotonic() - t
            save(out / f"{eng}_{voice}_{key}.wav", a, tts.sample_rate)
            first = tts.synth(text.split("!")[0].split(".")[0].split(",")[0] + ".")
            t1 = time.monotonic() - t - dt
            rows.append({"engine": eng, "voice": voice, "text": key, "audio_s": round(len(a) / tts.sample_rate, 2),
                         "synth_s": round(dt, 3), "rtf": round(dt / (len(a) / tts.sample_rate), 3),
                         "first_phrase_s": round(t1, 3), "first_phrase_audio_s": round(len(first) / tts.sample_rate, 2),
                         "load_s": round(load, 2)})
        rows[-1]["rss_delta_mb"] = (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss - r0) // 1024
        del tts
    (out / "metrics.json").write_text(json.dumps(rows, indent=1))
    return rows


if __name__ == "__main__":
    d = Path(sys.argv[1]) if len(sys.argv) > 1 else config.data_dir() / "voice_samples"
    for r in main(d):
        print(r)
    print("próbki:", d)
