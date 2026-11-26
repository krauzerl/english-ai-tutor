"""Sesje interaktywne dla GUI: ten sam silnik co CLI (`tutor.voice.cli.run`) w wątku roboczym.

GUI wysyła linie (tekst ucznia, "" = Enter: start/stop nagrywania lub przerwanie mowy tutora, "q" = koniec),
a odbiera zdarzenia z polem `kind` nadanym na podstawie stałych prefiksów komunikatów silnika.
Cała dydaktyka (ocena, zapis prób, mastery, FSRS, wznowienie) zostaje w Pythonie, bez zmian.
"""
from __future__ import annotations

import queue
import re
import threading
import time
from collections.abc import Callable

from tutor.i18n import tr_event

MAX_EVENTS = 3000
_CORR = re.compile(r"^•\s*„(?P<span>.+?)”\s*→\s*„(?P<fix>.+?)”(?:\s*—\s*(?P<why>.*?))?(?:\s*\(możliwe.*\))?$")
_STT_CONFIRM = re.compile(r"^\[Sprawdź rozpoznanie: „(?P<text>.*)”(?: \(niepewne: (?P<unsure>[^)]*)\))? — ")
_SUMMARY = re.compile(r"Powtórki: \d+/\d+")
_TASK = re.compile(r"^(?:\[(?P<tag>[^\]]+)\])?\s*Zadanie (?P<i>\d+)/(?P<n>\d+): (?P<text>.*)$", re.S)


# Wskazówki silnika pisane dla terminala -> nazwy przycisków GUI.
_GUI_WORDS = [
    ("poleceniem `--placement`", "przyciskiem „Określ poziom”"),
    ("poleceniem `--review`", "przyciskiem „Powtórki”"),
    ("z tym samym `--lesson`", "przyciskiem „Lekcja”"),
    ("poleceniem `--lesson`", "przyciskiem „Lekcja”"),
    ("z `--weakspots`", "z dziennika słabych stron"),
    ("(`--review`)", ""),
    ("tym samym poleceniem", "tym samym przyciskiem"),
    ("q = przerwij i wznów później", "„Zakończ” = przerwij i wznów później"),
    ("(q = przerwij, lekcję można wznowić)", "(„Zakończ” = przerwij, lekcję można wznowić)"),
    ("(q = koniec)", "(„Zakończ” = koniec)"),
    ("q = koniec", "„Zakończ” = koniec"),
]


def _gui_text(s: str) -> str:
    for a, b in _GUI_WORDS:
        s = s.replace(a, b)
    return s


def classify(line: str) -> dict:
    """Jedna linia wyjścia silnika -> zdarzenie GUI. Nieznane linie to `info` (nic nie ginie)."""
    t = _gui_text(line.strip("\n"))
    s = t.strip()
    if m := _TASK.match(s):
        return {"kind": "task", "text": m["text"], "index": int(m["i"]), "total": int(m["n"]), "tag": m["tag"]}
    for prefix, kind in (("Tutor: ", "tutor"), ("You: ", "you"), ("Usłyszałem:", "heard"), ("Cel lekcji:", "goal"),
                         ("● nagrywam", "recording"), ("(słucham", "listening"), ("★ Nowe osiągnięcie", "achievement"),
                         ("(STT ", "metric"), ("(start mowy", "metric"), ("(przerwano", "metric")):
        if s.startswith(prefix):
            return {"kind": kind, "text": s[len(prefix):].strip() if kind in ("tutor", "you", "heard") else s}
    if s == ">":
        return {"kind": "prompt", "text": ""}
    if s.startswith(("✓", "✗", "Poprawna odpowiedź", "Wynik ćwiczeń", "Koniec ćwiczeń")) or _SUMMARY.match(s):
        return {"kind": "feedback", "text": s}
    if s.startswith("Scenariusz:"):
        return {"kind": "scenario", "text": s.removeprefix("Scenariusz:").strip()}
    if s.startswith("Ustawienia rozmowy:"):
        return {"kind": "chatinfo", "text": s.removeprefix("Ustawienia rozmowy:").strip()}
    if s.startswith("Do poprawy w tej rozmowie"):
        return {"kind": "correction_head", "text": s}
    if m := _CORR.match(s):                           # „• „span” → „fix” — wyjaśnienie” z podsumowania korekt
        return {"kind": "correction", "text": s, "span": m["span"], "fix": m["fix"], "why": m["why"] or "",
                "stt": "źle usłyszałem" in s}
    if s.endswith("Spróbuj jeszcze raz."):           # drabina pomocy w ćwiczeniach (L1–L3)
        return {"kind": "hint", "text": s}
    if m := _STT_CONFIRM.match(s):                  # F7: potwierdzenie/poprawa niepewnej transkrypcji
        return {"kind": "stt_confirm", "text": m["text"], "unsure": m["unsure"] or ""}
    if s.startswith("[") and s.endswith("]"):
        return {"kind": "notice", "text": s[1:-1]}
    return {"kind": "info", "text": t}


class Busy(Exception):
    pass


class Runner:
    """Jedna aktywna sesja naraz (jeden uczeń, jeden mikrofon)."""

    def __init__(self, run: Callable | None = None):
        self._run = run
        self._lock = threading.Lock()
        self.events: list[dict] = []
        self.thread: threading.Thread | None = None
        self.lines: queue.Queue | None = None
        self.kind: str | None = None
        self.text_mode = False
        self.seq = 0

    def _emit(self, ev: dict) -> None:
        with self._lock:
            self.seq += 1
            self.events.append({**ev, "seq": self.seq, "t": round(time.time(), 2)})
            if len(self.events) > MAX_EVENTS:
                del self.events[: len(self.events) - MAX_EVENTS]

    @property
    def running(self) -> bool:
        return bool(self.thread and self.thread.is_alive())

    def start(self, argv: list[str], kind: str, lang: str = "pl") -> None:
        with self._lock:
            if self.thread and self.thread.is_alive():
                raise Busy("Trwa inna sesja — zakończ ją najpierw.")
            self.events, self.kind, self.lines, self.text_mode = [], kind, queue.Queue(), "--no-audio" in argv
        run = self._run
        if run is None:
            from tutor.voice.cli import run

        def work():
            self._emit({"kind": "start", "text": kind})
            code = 1
            try:
                code = run(argv, lines=self.lines, out=lambda s: self._emit(tr_event(classify(str(s)), lang)),
                           err=lambda s: self._emit(tr_event({"kind": "error", "text": str(s)}, lang)))
            except Exception as e:  # noqa: BLE001 - awaria silnika = komunikat w oknie, serwer działa dalej
                self._emit({"kind": "error", "text": f"{type(e).__name__}: {e}"})
            finally:
                self._emit({"kind": "end", "text": "", "code": code})

        self.thread = threading.Thread(target=work, name="tutor-session", daemon=True)
        self.thread.start()

    def send(self, text: str) -> None:
        if not self.running or self.lines is None:
            raise Busy("Brak aktywnej sesji.")
        self.lines.put(text)

    def stop(self) -> None:
        """`q` kończy sesję tak jak w terminalu (lekcja/powtórki: pauza z możliwością wznowienia)."""
        if self.running and self.lines is not None:
            self.lines.put("")          # zatrzymaj ewentualne nagrywanie lub mowę tutora
            self.lines.put("q")

    def since(self, seq: int) -> dict:
        with self._lock:
            evs = [e for e in self.events if e["seq"] > seq]
        return {"events": evs, "running": self.running, "kind": self.kind, "text_mode": self.text_mode}
