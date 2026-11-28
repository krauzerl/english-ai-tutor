"""Minimalny SessionService (F5.4): kolejka oceny ↔ cykl aktywności rozmowy. Bez cyklu lekcji, diagnozy, GUI.

Rozmowa ma priorytet: `user_turn` ustawia „rozmowa aktywna” i anuluje trwającą ocenę; ocena rusza w wątku roboczym
dopiero po `tutor_done`. Tury `dropped` nie wracają automatycznie; głosowe bez `low_probs` nie są oceniane.
"""
from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from tutor.app.eval_queue import EvalQueue, Pending
from tutor.app.eval_runner import restore_pending
from tutor.llm.base import CancelToken

log = logging.getLogger(__name__)


class SessionService:
    def __init__(self, repo, open_worker_repo: Callable[[], object], queue_factory: Callable[[object], EvalQueue],
                 profile_id: int, session_id: int, on_evaluated: Callable[[object, Pending], None] | None = None):
        """`repo`: połączenie rozmowy. Wątek roboczy otwiera WŁASNE połączenie (`open_worker_repo`), by jego
        transakcje nie mieszały się z zapisami rozmowy; `queue_factory(worker_repo)` buduje kolejkę na nim.
        `on_evaluated(worker_repo, pending)`: po zapisie oceny tury (wątek roboczy) — np. korekta w oknie rozmowy."""
        self._repo, self._open, self._qf = repo, open_worker_repo, queue_factory
        self._pid, self._sid = profile_id, session_id
        self._on_eval = on_evaluated
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

    def begin_activity(self) -> None:
        """Uczeń zaczyna wypowiedź (nagrywanie/pisanie): wstrzymaj nowe oceny i anuluj trwającą. Kończy je `tutor_done`
        (po odpowiedzi, błędzie STT, braku rozpoznania, Ctrl+C...)."""
        with self._lock:
            self._active = True
            if self._token:
                self._token.set()

    def user_turn(self, text: str, *, input_mode: str = "text", low_probs: list[str] | None = None) -> int:
        """Zapisuje turę ucznia (cudza sesja ⇒ IntegrityError), wstrzymuje ocenę i anuluje trwającą."""
        self.begin_activity()
        tid = self._repo.add_turn(self._pid, self._sid, "user", text, input_mode=input_mode, low_probs=low_probs)
        # głosowa bez STT-prob nie jest oceniana (patrz `list_pending_turns`)
        if self._q is not None and (input_mode == "text" or low_probs is not None):
            self._q.submit(Pending(tid, text, input_mode, frozenset(low_probs or ())))
        return tid

    def queued(self, turn_id: int) -> bool:
        return self._q is not None and self._q.has(turn_id)

    def wait_turn(self, turn_id: int, timeout: float, *, cancel_on_timeout: bool = True) -> str:
        """Ograniczone czekanie na ocenę jednej tury PRZED odpowiedzią tutora (korekta przy właściwej wypowiedzi,
        nie kilka tur później). Na czas czekania ocena jest dozwolona; potem znów „rozmowa aktywna”. Po przekroczeniu
        czasu trwająca ocena jest przerywana (lokalny model: bez równoległej generacji) albo
        (`cancel_on_timeout=False`, model zdalny) kończy się w tle, a korekta trafia do okna, gdy będzie gotowa.
        Wynik: `done` (ocena zapisana), `timeout`, `failed` (model nie dał oceny; tura wraca do kolejki) albo
        `none` (tury nie ma w kolejce)."""
        if self._q is None or not self._q.has(turn_id):
            return "none"
        self._q.prioritize(turn_id)
        with self._lock:
            self._active = False
        self._kick()
        end = time.monotonic() + max(timeout, 0.0)
        res = "timeout"
        while time.monotonic() < end:
            if not self._q.has(turn_id):
                res = "failed" if turn_id in self._q.dropped else "done"
                break
            if self._idle.is_set() and not self._wake.is_set():   # przebieg skończony, tura nadal czeka = błąd modelu
                res = "failed"
                break
            time.sleep(0.03)
        with self._lock:
            self._active = True
            if res == "timeout" and cancel_on_timeout and self._token:
                self._token.set()
        return res

    def tutor_done(self) -> None:
        """Koniec cyklu rozmowy (także przerwanego): zwalnia ocenianie. Po `close` nic nie robi."""
        with self._lock:
            self._active = False
        if not self._closed:
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
            if self._on_eval:
                self._q.on_applied = lambda p: self._on_eval(wrepo, p)
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
