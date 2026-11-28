"""Model jednej roli (rozmowa / ocena) dla profilu: lokalny model albo Gemini z bezpiecznym przejściem na lokalny.

Zasady (brief „Gemini API integration”):
 * Gemini jest używany, dopóki działa. Błąd → JEDNO przejście na model lokalny i okres wyłączenia Gemini; w tym czasie
   nie odpytujemy Gemini (brak pętli ponowień, brak przełączania w kółko podczas jednej awarii).
 * Limit chwilowy (minuta / nieokreślony 429 / serwer / sieć / timeout): wyłączenie na `retry_after` z API albo stały
   czas, potem jedna próba. Limit dzienny, limit żądań na sesję, zły klucz, niedostępny model, brak zgody: do końca
   sesji (albo do ręcznego `restore()`); komunikat mówi, że klucz/ustawienia wymagają naprawy.
 * Strumień: przełączenie tylko przed pierwszym fragmentem. Awaria w trakcie = przerwana odpowiedź (bez doklejania
   drugiej odpowiedzi innego modelu), następna tura idzie już lokalnie.
 * Każde wywołanie → `on_event` (metadane, bez treści): dostawca, model żądany i użyty, czasy, tokeny, powód, fallback.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from tutor.llm.base import CancelToken, LLMError, LLMProvider, Reply, Stream, log

SHORT_COOLDOWN_S = 120.0          # sieć / serwer / timeout / 429 bez jawnego czasu
MAX_COOLDOWN_S = 900.0
SESSION = float("inf")
REPAIR = {"auth", "model", "bad_request", "consent"}          # wymaga działania użytkownika
UNTIL_END = REPAIR | {"quota_day", "limit"}
REASON_PL = {"auth": "nieprawidłowy klucz API lub brak uprawnień", "model": "model niedostępny",
             "bad_request": "Gemini odrzuciło żądanie", "consent": "brak zgody na Gemini w tym profilu",
             "quota_day": "osiągnięto dzienny limit API", "quota_minute": "osiągnięto limit API na minutę",
             "quota": "osiągnięto limit API", "limit": "wyczerpany limit żądań na sesję (ustawienie aplikacji)",
             "server": "błąd serwera Gemini", "network": "błąd połączenia", "timeout": "przekroczony czas odpowiedzi"}


class Budget:
    """Licznik żądań TEJ aplikacji do Gemini w bieżącej sesji (wspólny dla rozmowy i oceny). To nie jest stan konta
    Google: rzeczywisty limit i ewentualne opłaty widać tylko w Google AI Studio."""

    def __init__(self, max_requests: int):
        self.max_requests, self.requests, self.in_tokens, self.out_tokens = max_requests, 0, 0, 0
        self.routes: list[Routed] = []           # role tej sesji (ręczne przywrócenie Gemini: wszystkie naraz)
        self._lock = threading.Lock()

    def take(self) -> None:
        with self._lock:
            if self.requests >= self.max_requests:
                raise LLMError(f"Limit żądań Gemini na sesję ({self.max_requests}) wyczerpany.", reason="limit")
            self.requests += 1

    def add_tokens(self, i: int, o: int) -> None:
        with self._lock:
            self.in_tokens += i
            self.out_tokens += o


class Routed:
    def __init__(self, role: str, local: LLMProvider, primary: LLMProvider | None = None, *,
                 budget: Budget | None = None, gate: Callable[[], None] | None = None,
                 on_event: Callable[[dict], None] | None = None, notify: Callable[[str], None] | None = None,
                 prompt: str | None = None, clock: Callable[[], float] = time.monotonic):
        if local.external:
            raise ValueError("model zapasowy musi być lokalny")
        self.role, self.local, self.primary, self.budget = role, local, primary, budget
        self.gate, self.on_event, self.notify, self.prompt, self.clock = gate, on_event, notify, prompt, clock
        self.down_until: float | None = None
        self.down_reason: str | None = None
        self.fallbacks = 0                       # liczba przejść na model lokalny (awarii), nie wywołań
        self.last_provider, self.last_model, self.last_fallback = None, None, False
        self._lock = threading.Lock()

    # --- tożsamość: dostawca, który zostanie użyty w następnym wywołaniu ---
    def active(self) -> bool:
        with self._lock:
            return self.primary is not None and (self.down_until is None or self.clock() >= self.down_until)

    @property
    def _cur(self) -> LLMProvider:
        return self.primary if self.active() else self.local

    @property
    def name(self) -> str:
        return self._cur.name

    @property
    def model(self) -> str:
        return self._cur.model

    @property
    def external(self) -> bool:
        return self._cur.external

    def __repr__(self) -> str:
        return f"Routed(role={self.role!r}, primary={self.primary!r}, local={self.local!r})"

    def restore(self) -> bool:
        """Ręczne przywrócenie Gemini (np. polecenie w sesji). False = Gemini nie jest skonfigurowany."""
        with self._lock:
            self.down_until = self.down_reason = None
        return self.primary is not None

    # --- awaria i powrót ---
    def _down(self, e: LLMError) -> None:
        reason = e.reason or "error"
        if reason in UNTIL_END:
            wait = SESSION
        else:
            wait = min(MAX_COOLDOWN_S, e.retry_after) if e.retry_after else SHORT_COOLDOWN_S
        with self._lock:
            first = self.down_until is None
            self.down_until, self.down_reason = self.clock() + wait, reason
            if first:
                self.fallbacks += 1
        log.warning("route %s: gemini down reason=%s wait=%s", self.role, reason, wait)
        if first and self.notify:
            what = "Rozmowa" if self.role == "conversation" else "Ocena wypowiedzi"
            why = REASON_PL.get(reason, e.user_message)
            fix = " Popraw to w Ustawieniach → Modele AI." if reason in REPAIR else ""
            self.notify(f"[Gemini jest chwilowo niedostępny ({why}). {what}: kontynuujesz lokalnie z "
                        f"{self.local.model}.{fix}]")

    def _recovered(self) -> None:
        with self._lock:
            was = self.down_reason is not None
            self.down_until = self.down_reason = None
        if was and self.notify:
            self.notify("[Gemini znów odpowiada — wracam do Gemini.]")

    def _pre(self) -> None:
        if self.gate:
            self.gate()
        if self.budget:
            self.budget.take()

    def _event(self, prov: LLMProvider, t0: float, *, usage=None, error: LLMError | None = None,
               fallback: bool = False, first_ms: int | None = None, status: str = "ok") -> None:
        self.last_provider, self.last_model, self.last_fallback = prov.name, prov.model, fallback
        if usage and prov.external and self.budget:
            self.budget.add_tokens(usage.in_tokens, usage.billed_out)
        if not self.on_event:
            return
        ev = {"role": self.role, "requested_provider": (self.primary or self.local).name,
              "requested_model": (self.primary or self.local).model, "provider": prov.name, "model": prov.model,
              "latency_ms": int((self.clock() - t0) * 1000), "first_token_ms": first_ms, "prompt": self.prompt,
              "in_tokens": getattr(usage, "in_tokens", None), "out_tokens": getattr(usage, "billed_out", None),
              "tokens_estimated": getattr(usage, "estimated", None), "fallback": fallback,
              "reason": (error.reason or "error") if error else None, "status": status}
        try:
            self.on_event(ev)
        except Exception:  # noqa: BLE001, S110 - dziennik nigdy nie przerywa rozmowy
            pass

    def _local_failed(self, e: LLMError, primary_tried: bool) -> LLMError:
        if self.primary is None:
            return e
        msg = ("Gemini i lokalny model są niedostępne — odpowiedź nie została wygenerowana. "
               "Sprawdź `ollama serve` i połączenie z internetem.")
        return LLMError(msg, reason=e.reason) if primary_tried or not self.active() else e

    # --- interfejs dostawcy ---
    def chat(self, messages, **kw) -> Reply:
        tried = False
        if self.active():
            tried = True
            t0 = self.clock()
            try:
                self._pre()
                r = self.primary.chat(messages, **kw)
            except LLMError as e:
                self._event(self.primary, t0, error=e, status="error")
                self._down(e)
            else:
                self._recovered()
                self._event(self.primary, t0, usage=r.usage)
                return r
        t0 = self.clock()
        try:
            r = self.local.chat(messages, **kw)
        except LLMError as e:
            self._event(self.local, t0, error=e, fallback=tried, status="error")
            raise self._local_failed(e, tried) from None
        self._event(self.local, t0, usage=r.usage, fallback=self.primary is not None,
                    error=LLMError(reason=self.down_reason) if self.down_reason else None)
        return r

    def stream(self, messages, *, cancel: CancelToken | None = None, **kw) -> Stream:
        cancel = cancel or CancelToken()

        def run(prov, s, it, t0, fallback, why):
            """`s`: strumień dostawcy (usage, close); `it`: jego fragmenty (pierwszy już pobrany)."""
            first_ms = int((self.clock() - t0) * 1000)
            try:
                yield from it
            except GeneratorExit:                 # anulowanie (uczeń przerwał): zapis bez tokenów
                self._event(prov, t0, fallback=fallback, first_ms=first_ms, status="cancelled")
                raise
            except LLMError as e:
                self._event(prov, t0, error=e, fallback=fallback, first_ms=first_ms, status="interrupted")
                if prov is self.primary:
                    self._down(e)
                raise
            finally:
                s.close()
            self._event(prov, t0, usage=s.usage, fallback=fallback, first_ms=first_ms,
                        error=LLMError(reason=why) if why else None,
                        status="cancelled" if cancel.is_set() else "ok")
            return s.usage

        def gen():
            tried = False
            if self.active():
                tried = True
                t0 = self.clock()
                try:
                    self._pre()
                    s = self.primary.stream(messages, cancel=cancel, **kw)
                    it = iter(s)
                    first = next(it)
                except StopIteration:
                    self._recovered()
                    self._event(self.primary, t0, usage=s.usage)
                    return s.usage
                except LLMError as e:
                    self._event(self.primary, t0, error=e, status="error")
                    self._down(e)
                else:
                    self._recovered()
                    return (yield from run(self.primary, s, _chain(first, it), t0, False, None))
            t0 = self.clock()
            try:
                s = self.local.stream(messages, cancel=cancel, **kw)
                it = iter(s)
                first = next(it)
            except StopIteration:
                self._event(self.local, t0, usage=s.usage, fallback=tried)
                return s.usage
            except LLMError as e:
                self._event(self.local, t0, error=e, fallback=tried, status="error")
                raise self._local_failed(e, tried) from None
            return (yield from run(self.local, s, _chain(first, it), t0, self.primary is not None,
                                   self.down_reason))

        return Stream(gen(), cancel)

    def health(self) -> bool:
        return self.local.health() or (self.primary is not None and self.primary.health())


def _chain(first: str, rest):
    yield first
    yield from rest
