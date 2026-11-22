"""Atrapy STT/TTS/mikrofonu — żadnego prawdziwego audio ani modeli."""
import queue

import numpy as np

from tutor.voice import audio as A


class FakeTTS:
    name, voice, sample_rate = "fake", "v", 16000

    def __init__(self, fail_on=None, delay=0.0, secs=0.5):
        self.calls, self.fail_on, self.delay, self.secs = [], fail_on, delay, secs
        self.times = []

    def synth(self, text):
        import time
        if self.delay:
            time.sleep(self.delay)
        if self.fail_on and self.fail_on in text:
            raise RuntimeError("boom")
        self.calls.append(text)
        self.times.append(time.monotonic())
        return np.zeros(int(self.sample_rate * self.secs), np.float32)


class FakeSTT:
    def __init__(self, *texts):
        self.texts, self.audio_seen = list(texts), []

    def transcribe(self, audio):
        self.audio_seen.append(len(audio))
        return self.texts.pop(0) if self.texts else ""


class FakeMic:
    """Podaje bloki; muted_until jak w Mic (test echa)."""

    def __init__(self, blocks=(), loop=None):
        self.q, self.muted, self.loop = queue.Queue(), [], loop
        for b in blocks:
            self.q.put(b)

    def read(self, timeout=0.1):
        try:
            return self.q.get(timeout=min(timeout, 0.01))
        except queue.Empty:
            return self.loop

    def mute(self, s):
        self.muted.append(s)

    def open(self): ...

    def close(self): ...


def tone(seconds, amp=0.3, sr=A.MIC_SR):
    t = np.arange(int(seconds * sr)) / sr
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def blocks(x):
    return [x[i:i + A.BLOCK] for i in range(0, len(x) - A.BLOCK + 1, A.BLOCK)]


class Lines(queue.Queue):
    """Kolejka linii stdin jak w CLI; get() bez timeout po wyczerpaniu zwraca None (EOF)."""

    def __init__(self, *ls):
        super().__init__()
        for ln in ls:
            self.put(ln)

    def get(self, block=True, timeout=None):
        try:
            return super().get(timeout=timeout if timeout is not None else 0.05)
        except queue.Empty:
            if timeout is None:
                return None
            raise
