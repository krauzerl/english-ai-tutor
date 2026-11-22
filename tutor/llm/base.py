"""Wspólny interfejs dostawców LLM, typy, wyjątki, strumień z anulowaniem, fallback."""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Protocol

log = logging.getLogger("tutor.llm")  # tylko metadane; nigdy treść ani klucze


@dataclass(frozen=True)
class Message:
    role: str  # system | user | assistant
    content: str


@dataclass
class Usage:
    in_tokens: int = 0
    out_tokens: int = 0  # bez rozumowania
    reasoning_tokens: int = 0  # rozliczane jak wyjście, jeśli dostawca je raportuje
    latency_ms: int = 0
    estimated: bool = False

    @property
    def billed_out(self) -> int:
        return self.out_tokens + self.reasoning_tokens


@dataclass
class Reply:
    text: str
    usage: Usage
    provider: str
    model: str
    notices: list[str] = field(default_factory=list)


# --- wyjątki: user_message = tekst dla ucznia/UI, str(e) = bez treści rozmów ---
class LLMError(Exception):
    def __init__(self, user_message: str = "Błąd modelu językowego."):
        super().__init__(user_message)
        self.user_message = user_message


class LLMTimeout(LLMError): ...
class LLMUnavailable(LLMError): ...
class ConsentRequired(LLMError): ...
class LimitsNotConfigured(LLMError): ...
class BudgetExceeded(LLMError): ...
class InvalidStructuredOutput(LLMError): ...
class ContextTooLarge(LLMError): ...


class StreamInterrupted(LLMError):
    """Awaria w trakcie streamingu. `partial` tylko do pokazania; nie łączyć z inną odpowiedzią."""

    def __init__(self, user_message: str = "Połączenie przerwane w trakcie odpowiedzi.",
                 partial: str = ""):
        super().__init__(user_message)
        self.partial = partial


class CancelToken:
    def __init__(self):
        self._ev, self._cbs = threading.Event(), []

    def set(self) -> None:
        self._ev.set()
        for cb in self._cbs:
            try:
                cb()
            except Exception:  # noqa: S110 - zamknięcie połączenia best-effort
                pass

    def is_set(self) -> bool:
        return self._ev.is_set()

    def on_cancel(self, cb: Callable[[], None]) -> None:
        self._cbs.append(cb)


class Stream:
    """Iterator fragmentów tekstu. `source` to generator; jego `return` = Usage.

    Po zakończeniu/anulowaniu/awarii woła `on_finish` dokładnie raz.
    """

    def __init__(self, source: Iterator[str], cancel: CancelToken | None = None):
        self._src, self.cancel = source, cancel or CancelToken()
        self.usage: Usage | None = None
        self.cancelled = False
        self.notices: list[str] = []
        self.on_finish: Callable[[Stream, bool], None] | None = None  # (stream, ok)
        self.guard: Callable[[], None] | None = None  # np. kontrola zgody przed każdym fragmentem
        self._parts: list[str] = []
        self._done = False

    @property
    def text(self) -> str:
        return "".join(self._parts)

    def __iter__(self):
        return self

    def _finish(self, ok: bool) -> None:
        if self._done:
            return
        self._done = True
        try:
            self._src.close()
        except Exception:  # noqa: S110
            pass
        if self.on_finish:
            self.on_finish(self, ok)

    def close(self) -> None:
        self._finish(False)

    def __next__(self) -> str:
        if self._done:
            raise StopIteration
        if self.cancel.is_set():
            self.cancelled = True
            self._finish(False)
            raise StopIteration
        try:
            if self.guard:
                self.guard()
        except LLMError:
            self.cancel.set()
            self._finish(False)
            raise
        try:
            chunk = next(self._src)
        except StopIteration as e:
            if isinstance(e.value, Usage):
                self.usage = e.value
            self._finish(True)
            raise
        except (ConsentRequired, StreamInterrupted):
            self._finish(False)
            raise
        except Exception as e:
            self._finish(False)
            msg = e.user_message if isinstance(e, LLMError) else "Połączenie przerwane."
            raise StreamInterrupted(msg, self.text) from None
        if self.cancel.is_set():  # anulowano w trakcie blokującego odczytu
            self.cancelled = True
            self._finish(False)
            raise StopIteration
        self._parts.append(chunk)
        return chunk


class LLMProvider(Protocol):
    name: str
    model: str
    external: bool  # True = dane opuszczają komputer (wymaga zgody i limitów)

    def chat(self, messages: list[Message], *, temperature: float = 0.7, max_tokens: int = 512,
             schema: dict | None = None) -> Reply: ...

    def stream(self, messages: list[Message], *, temperature: float = 0.7, max_tokens: int = 512,
               cancel: CancelToken | None = None) -> Stream: ...

    def health(self) -> bool: ...


class LocalFallback:
    """Chmura → lokalny, jawnie sygnalizowane (`notices`). Odwrotnie: nigdy.

    Strumień: przełączenie tylko przed pierwszym fragmentem; awaria później
    = StreamInterrupted (częściowej odpowiedzi nie łączymy z inną).
    """

    def __init__(self, primary: LLMProvider, local: LLMProvider):
        if local.external or not primary.external:
            raise ValueError("fallback dozwolony wyłącznie chmura -> lokalny")
        self.primary, self.local = primary, local
        self.name, self.model, self.external = primary.name, primary.model, True

    def _notice(self, e: LLMError) -> str:
        return (f"Model {self.primary.name} niedostępny ({e.user_message}) – "
                f"użyto modelu lokalnego {self.local.name}:{self.local.model}.")

    def chat(self, messages, **kw) -> Reply:
        try:
            return self.primary.chat(messages, **kw)
        except LLMError as e:
            if isinstance(e, InvalidStructuredOutput):
                raise
            log.warning("fallback %s -> %s (%s)", self.primary.name, self.local.name, type(e).__name__)
            r = self.local.chat(messages, **kw)
            r.notices.append(self._notice(e))
            return r

    def stream(self, messages, *, cancel: CancelToken | None = None, **kw) -> Stream:
        cancel = cancel or CancelToken()
        notices: list[str] = []

        def gen():
            try:
                s = self.primary.stream(messages, cancel=cancel, **kw)
                it = iter(s)
                first = next(it)
            except StopIteration:
                return s.usage
            except LLMError as e:
                log.warning("fallback %s -> %s (%s)", self.primary.name, self.local.name,
                            type(e).__name__)
                notices.append(self._notice(e))
                s = self.local.stream(messages, cancel=cancel, **kw)
                yield from s
                return s.usage
            yield first
            yield from it
            return s.usage

        out = Stream(gen(), cancel)
        out.notices = notices
        return out

    def health(self) -> bool:
        return self.primary.health() or self.local.health()
