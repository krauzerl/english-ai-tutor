"""Mikrofon (sounddevice), głośnik, detekcja końca wypowiedzi. Audio tylko w pamięci, nigdy na dysku."""
from __future__ import annotations

import collections
import ctypes.util
import os
import queue
import threading
import time
from pathlib import Path

import numpy as np

MIC_SR = 16000
BLOCK = 480  # 30 ms
# Ubuntu: `sudo apt install libportaudio2`. Bez sudo: wypakuj .deb do tego katalogu (patrz docs).
LOCAL_PORTAUDIO = Path.home() / ".local/lib/english-ai-tutor/libportaudio.so.2"


class AudioUnavailable(RuntimeError):
    """Brak PortAudio / urządzenia audio; wywołujący przechodzi na tryb tekstowy."""


def sd():
    if (cached := globals().get("_sd")) is not None:
        return cached
    if LOCAL_PORTAUDIO.exists() and not ctypes.util.find_library("portaudio"):
        orig = ctypes.util.find_library
        ctypes.util.find_library = lambda n: str(LOCAL_PORTAUDIO) if n == "portaudio" else orig(n)
    try:
        import sounddevice
    except OSError as e:
        raise AudioUnavailable("Brak biblioteki PortAudio (sudo apt install libportaudio2).") from e
    globals()["_sd"] = sounddevice
    return sounddevice


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if len(x) else 0.0


class Endpointer:
    """Energia + adaptacyjny próg szumu. update(rms_ramki) -> 'idle' | 'speech' | 'end' | 'noise'.

    'noise' = zbyt krótki impuls (kliknięcie, szum) – wypowiedź odrzucona, stan wraca do idle.
    """

    def __init__(self, frame_s=BLOCK / MIC_SR, end_silence=0.7, min_speech=0.3, max_utt=30.0,
                 min_rms=0.01, factor=3.0, start_frames=3):
        self.fs, self.end_n = frame_s, round(end_silence / frame_s)
        self.min_n, self.max_n = round(min_speech / frame_s), round(max_utt / frame_s)
        self.min_rms, self.factor, self.start_n = min_rms, factor, start_frames
        self.tail = 0
        self.floor, self._calib = 0.0, 10  # pierwsze 10 ramek (0,3 s) = kalibracja szumu tła
        self.reset()

    def reset(self) -> None:
        self.state, self._run, self._silence, self._speech, self._total = "idle", 0, 0, 0, 0

    @property
    def threshold(self) -> float:
        return max(self.min_rms, self.floor * self.factor)

    def update(self, level: float) -> str:
        if self._calib:
            self._calib -= 1
            self.floor += (level - self.floor) / (10 - self._calib)  # średnia bieżąca
            return "idle"
        loud = level > self.threshold
        if self.state == "idle":
            if not loud:  # szum tła uczy próg tylko poza mową
                self.floor = 0.95 * self.floor + 0.05 * level
            self._run = self._run + 1 if loud else 0
            if self._run >= self.start_n:
                self.state, self._speech, self._silence, self._total = "speech", self._run, 0, self._run
            return self.state
        self._total += 1
        self._speech += loud
        self._silence = 0 if loud else self._silence + 1
        if self._silence >= self.end_n or self._total >= self.max_n:
            ok, self.tail = self._speech >= self.min_n, self._silence  # tail: ramki ciszy na końcu
            self.reset()
            return "end" if ok else "noise"
        return "speech"


class Mic:
    """16 kHz mono. Bloki w kolejce; `mute()` odrzuca dźwięk (tutor mówi — brak transkrypcji własnego głosu)."""

    def __init__(self, device=None):
        self.device, self.q, self._muted_until = device, queue.Queue(maxsize=400), 0.0
        self.stream = None

    def open(self) -> None:
        try:
            self.stream = sd().InputStream(samplerate=MIC_SR, channels=1, dtype="float32", blocksize=BLOCK,
                                           device=self.device, callback=self._cb)
            self.stream.start()
        except AudioUnavailable:
            raise
        except Exception as e:  # sounddevice.PortAudioError: brak/zajęty mikrofon
            raise AudioUnavailable(f"Nie można otworzyć mikrofonu: {e}") from e

    def _cb(self, indata, frames, t, status) -> None:
        if time.monotonic() < self._muted_until:
            return
        try:
            self.q.put_nowait(indata[:, 0].copy())
        except queue.Full:
            pass  # lepiej zgubić blok niż blokować wątek audio

    def mute(self, seconds: float) -> None:
        """Ignoruj mikrofon przez `seconds` (+ opróżnij kolejkę); wołać też po końcu mowy (ogon echa)."""
        self._muted_until = time.monotonic() + seconds
        with self.q.mutex:
            self.q.queue.clear()

    def read(self, timeout=0.1) -> np.ndarray | None:
        try:
            return self.q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None


def listen_auto(mic, ep: Endpointer, *, poll=None, timeout=None, preroll=10, on_speech=None, on_noise=None):
    """Czeka na wypowiedź. Zwraca float32 16k, 'None' przy timeout lub gdy poll() zwróci True.
    `on_speech`: początek mowy (raz na wypowiedź); `on_noise`: odrzucony impuls (kliknięcie)."""
    pre, buf, t0 = collections.deque(maxlen=preroll), [], time.monotonic()
    speaking = False
    ep.reset()
    while True:
        if (poll and poll()) or (timeout and time.monotonic() - t0 > timeout):
            return None
        b = mic.read()
        if b is None:
            continue
        st = ep.update(rms(b))
        if st == "idle":
            pre.append(b)
        elif st == "speech":
            if not speaking and on_speech:
                on_speech()
            speaking = True
            if pre:
                buf.extend(pre)
                pre.clear()
            buf.append(b)
        elif st == "end":
            buf.append(b)
            keep = len(buf) - max(0, ep.tail - 5)  # ucinamy ciszę końcową (Whisper szybszy), zostaje 150 ms
            return np.concatenate(buf[:keep])
        elif st == "noise":
            buf.clear()
            if speaking and on_noise:
                on_noise()
            speaking = False


def record_manual(mic, stop: threading.Event) -> np.ndarray:
    buf = []
    while not stop.is_set():
        if (b := mic.read()) is not None:
            buf.append(b)
    return np.concatenate(buf) if buf else np.zeros(0, np.float32)


class Speaker:
    """Odtwarzanie strumieniowe. write() dopisuje próbki; stop() natychmiast je kasuje (przerwanie mowy)."""

    def __init__(self, device=None):
        self.device, self._buf, self._lock = device, collections.deque(), threading.Lock()
        self.stream, self.sr, self.first_audio_at, self.underrun_s = None, 0, None, 0.0
        self._pending = 0
        self._sealed = True

    def start(self, sr: int) -> None:
        if self.stream and self.sr != sr:
            self.stream.close()
            self.stream = None
        self.sr, self.first_audio_at, self.underrun_s, self._sealed = sr, None, 0.0, False
        if not self.stream:
            try:
                self.stream = sd().OutputStream(samplerate=sr, channels=1, dtype="float32",
                                                device=self.device, callback=self._cb)
                self.stream.start()
            except AudioUnavailable:
                raise
            except Exception as e:
                raise AudioUnavailable(f"Nie można otworzyć głośnika: {e}") from e

    def _cb(self, out, frames, t, status) -> None:
        with self._lock:
            n = 0
            while n < frames and self._buf:
                a = self._buf[0]
                k = min(len(a), frames - n)
                out[n:n + k, 0] = a[:k]
                n += k
                if k == len(a):
                    self._buf.popleft()
                else:
                    self._buf[0] = a[k:]
            self._pending -= n
            if n and self.first_audio_at is None:
                self.first_audio_at = time.monotonic()
            if n < frames:
                out[n:, 0] = 0
                if self.first_audio_at is not None and not self._sealed:
                    self.underrun_s += (frames - n) / self.sr

    def write(self, samples: np.ndarray) -> None:
        with self._lock:
            self._buf.append(np.asarray(samples, np.float32))
            self._pending += len(samples)

    @property
    def playing(self) -> bool:
        return self._pending > 0

    def seal(self) -> None:
        """Koniec dopisywania: cisza po tym momencie nie jest niedomiarem."""
        self._sealed = True

    def drain(self, cancel=None, timeout=60.0) -> None:
        t0 = time.monotonic()
        while self.playing and not (cancel and cancel.is_set()) and time.monotonic() - t0 < timeout:
            time.sleep(0.02)

    def stop(self) -> None:
        with self._lock:
            self._buf.clear()
            self._pending = 0

    def close(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None


class SimSink:
    """Zegar odtwarzania bez dźwięku (benchmark/testy): mierzy start i przerwy między fragmentami."""

    def __init__(self, clock=time.monotonic):
        self.clock, self.sr = clock, 0
        self.start(0)

    def start(self, sr: int) -> None:
        self.sr, self.first_audio_at, self.underrun_s, self.end_at = sr, None, 0.0, 0.0
        self.written, self.gaps = [], []

    def write(self, samples) -> None:
        now, dur = self.clock(), len(samples) / (self.sr or 1)
        if self.first_audio_at is None:
            self.first_audio_at, self.end_at = now, now + dur
        else:
            if now > self.end_at:
                self.underrun_s += now - self.end_at
                self.gaps.append(now - self.end_at)
                self.end_at = now
            self.end_at += dur
        self.written.append(samples)

    playing = False

    def seal(self) -> None: ...

    def drain(self, cancel=None, timeout=0) -> None: ...

    def stop(self) -> None:
        self.written = []

    def close(self) -> None: ...


def device_names() -> list[str]:
    return [f"{i}: {d['name']} (in {d['max_input_channels']}, out {d['max_output_channels']})"
            for i, d in enumerate(sd().query_devices())]


def have_env_audio() -> bool:
    return bool(os.environ.get("TUTOR_NO_AUDIO"))
