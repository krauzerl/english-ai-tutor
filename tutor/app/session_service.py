"""Minimalny SessionService (F5.4): kolejka oceny ↔ cykl aktywności rozmowy. Bez cyklu lekcji, diagnozy, GUI.

Rozmowa ma priorytet: `user_turn` ustawia „rozmowa aktywna” i anuluje trwającą ocenę; ocena rusza w wątku roboczym
dopiero po `tutor_done`. Tury `dropped` nie wracają automatycznie; głosowe bez `low_probs` nie są oceniane.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable

from tutor.app.eval_queue import EvalQueue, Pending
from tutor.app.eval_runner import restore_pending
from tutor.llm.base import CancelToken

log = logging.getLogger(__name__)


class SessionService:
    def __init__(self, repo, open_worker_repo: Callable[[], object], queue_factory: Callable[[object], EvalQueue],
                 profile_id: int, session_id: int):
        """`repo`: połączenie rozmowy. Wątek roboczy otwiera WŁASNE połączenie (`open_worker_repo`), by jego
        transakcje nie mieszały się z zapisami rozmowy; `queue_factory(worker_repo)` buduje kolejkę na nim."""
        self._repo, self._open, self._qf = repo, open_worker_repo, queue_factory
        self._pid, self._sid = profile_id, session_id
        self._q: EvalQueue | None = None
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._active = False
        self._token: CancelToken | None = None
        self._wake, self._idle, self._closed = threading.Event(), threading.Event(), False
        self._idle.set()
        self._thread: threading.Thread | None = None
        self.last_error: Exception | None = None

    def start(self) -> int:
        """Odtwarza oczekujące oceny z SQLite i uruchamia przetwarzanie w tle. Zwraca liczbę odtworzonych tur."""
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True, name="eval-worker")
            self._thread.start()
            self._ready.wait()
        n = restore_pending(self._repo, self._q, self._pid, self._sid)
        self._kick()
        return n

    def user_turn(self, text: str, *, input_mode: str = "text", low_probs: list[str] | None = None) -> int:
        """Zapisuje turę ucznia (cudza sesja ⇒ IntegrityError), wstrzymuje ocenę i anuluje trwającą."""
        with self._lock:
            self._active = True
            if self._token:
                self._token.set()
        tid = self._repo.add_turn(self._pid, self._sid, "user", text, input_mode=input_mode, low_probs=low_probs)
        # głosowa bez STT-prob nie jest oceniana (patrz `list_pending_turns`)
        if self._q is not None and (input_mode == "text" or low_probs is not None):
            self._q.submit(Pending(tid, text, input_mode, frozenset(low_probs or ())))
        return tid

    def tutor_done(self) -> None:
        with self._lock:
            self._active = False
        self._kick()

    def wait_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout)

    @property
    def pending(self) -> int:
        return len(self._q) if self._q is not None else 0

    @property
    def dropped(self) -> list[int]:
        return list(self._q.dropped) if self._q is not None else []

    def close(self, timeout: float = 1.0) -> None:
        """Nie czeka na trwającą ocenę dłużej niż `timeout`: przerwana tura wróci po restarcie z SQLite."""
        self._closed = True
        with self._lock:
            if self._token:
                self._token.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout)

    def _kick(self) -> None:
        with self._lock:                    # pod blokadą: bez wyścigu z końcem przebiegu roboczego
            self._idle.clear()
            self._wake.set()

    def _run(self) -> None:
        wrepo = self._open()
        try:
            self._q = self._qf(wrepo)
        finally:
            self._ready.set()
        try:
            self._loop()
        finally:
            wrepo.conn.close()

    def _loop(self) -> None:
        while True:
            self._wake.wait()
            if self._closed:
                return
            self._wake.clear()
            with self._lock:
                token = None if self._active else CancelToken()
                self._token = token
            if token:
                try:
                    self._q.drain(token, conversation_active=lambda: self._active)
                except Exception as e:  # noqa: BLE001 - błąd zapisu nie zabija wątku; tura zostaje oczekująca
                    self.last_error = e
                    log.warning("eval drain failed: %s", e)
            with self._lock:
                if not self._wake.is_set():
                    self._idle.set()
