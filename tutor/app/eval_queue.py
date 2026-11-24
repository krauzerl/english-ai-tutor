"""Kolejka oceny wypowiedzi (04 §3.3, T-CORR-4). Rozmowa ma zawsze priorytet.

Zasady: partia ≤ 5 wypowiedzi; ocena startuje tylko gdy rozmowa nie trwa; `cancel` (nowa tura ucznia)
przerywa ocenę, a niedokończona partia wraca do kolejki i jest oceniana później. Zapis wyniku idzie przez
`apply` (w F5: `ingest.apply_turn_evaluation`, idempotentne). Bez wątków: `drain` woła worker (F6) lub CLI.
"""
from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from tutor.llm.base import CancelToken

MAX_TRIES = 3   # shortcut: wsad, który trzy razy zawiódł, jest porzucany (nieoceniony), by nie blokować kolejki


@dataclass(frozen=True)
class Pending:
    turn_id: int
    text: str
    input_mode: str
    low_probs: frozenset[str] = frozenset()


class EvalQueue:
    def __init__(self, evaluate: Callable[[list[Pending]], list], apply: Callable[[Pending, object], None],
                 *, batch: int = 5, on_drop: Callable[[Pending], None] | None = None):
        self._evaluate, self._apply, self._batch, self._on_drop = evaluate, apply, batch, on_drop
        self._q: list[Pending] = []
        self._tries: dict[int, int] = {}
        self._lock = threading.Lock()
        self.dropped: list[int] = []

    def submit(self, p: Pending) -> None:
        with self._lock:
            if all(x.turn_id != p.turn_id for x in self._q):
                self._q.append(p)
                self._tries.pop(p.turn_id, None)           # ponowne zgłoszenie = nowy cykl prób
                self.dropped = [i for i in self.dropped if i != p.turn_id]

    def __len__(self) -> int:
        return len(self._q)

    def drain(self, cancel: CancelToken, *, conversation_active: Callable[[], bool] = lambda: False) -> int:
        """Ocenia partie do wyczerpania kolejki lub przerwania. Zwraca liczbę ocenionych wypowiedzi."""
        done = 0
        while not cancel.is_set() and not conversation_active():
            with self._lock:
                batch = self._q[:self._batch]
            if not batch:
                break
            try:
                results = self._evaluate(batch)
                if len(results) != len(batch):
                    raise ValueError("evaluate returned wrong result count")
            except Exception:  # noqa: BLE001 - błąd modelu nie może zatrzymać rozmowy
                self._fail(batch)
                break
            if cancel.is_set():          # wynik po przerwaniu odrzucony: partia wraca do kolejki
                break
            for p, r in zip(batch, results, strict=True):
                self._apply(p, r)
                self._tries.pop(p.turn_id, None)
            with self._lock:
                ids = {p.turn_id for p in batch}
                self._q = [x for x in self._q if x.turn_id not in ids]
            done += len(batch)
        return done

    def _fail(self, batch: list[Pending]) -> None:
        gone = []
        with self._lock:
            for p in batch:
                n = self._tries[p.turn_id] = self._tries.get(p.turn_id, 0) + 1
                if n >= MAX_TRIES:
                    gone.append(p)
                    self.dropped.append(p.turn_id)
            self._q = [x for x in self._q if x not in gone]
        for p in gone:
            if self._on_drop:
                self._on_drop(p)
