"""Ollama (/api/chat). Lokalny: external=False. Wywołanie przeniesione z pierwotnego main.py."""
from __future__ import annotations

import json
import time
from collections.abc import Iterator

import requests

from tutor.llm.base import (
    CancelToken,
    LLMError,
    LLMTimeout,
    LLMUnavailable,
    Message,
    Reply,
    Stream,
    Usage,
    log,
)

DEFAULT_URL = "http://localhost:11434"
DEFAULT_MODEL = "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M"


class OllamaProvider:
    name, external = "ollama", False

    def __init__(self, model: str = DEFAULT_MODEL, url: str = DEFAULT_URL, num_ctx: int = 8192,
                 timeout: float = 120, keep_alive: str | None = None, think: bool | None = None):
        self.model, self.url, self.num_ctx = model, url.rstrip("/"), num_ctx
        self.timeout, self.keep_alive, self.think = timeout, keep_alive, think

    def _body(self, messages, temperature, max_tokens, stream, schema=None) -> dict:
        body = {
            "model": self.model, "stream": stream,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "options": {"temperature": temperature, "num_predict": max_tokens, "num_ctx": self.num_ctx},
        }
        if schema is not None:
            body["format"] = schema
        if self.keep_alive:
            body["keep_alive"] = self.keep_alive
        if self.think is not None:          # Ollama ≥ 0.9: modele z trybem „thinking” (Qwen3); None = nie wysyłamy
            body["think"] = self.think
        return body

    def _post(self, body, stream: bool):
        try:
            r = requests.post(f"{self.url}/api/chat", json=body, timeout=self.timeout, stream=stream)
        except requests.Timeout:
            raise LLMTimeout("Ollama nie odpowiedziała w czasie.") from None
        except requests.RequestException:
            raise LLMUnavailable("Nie można połączyć się z Ollamą (czy działa `ollama serve`?).") from None
        if r.status_code >= 400:
            r.close()
            hint = " Model nie jest pobrany (`ollama pull`)." if r.status_code == 404 else ""
            raise LLMError(f"Ollama zwróciła błąd HTTP {r.status_code}.{hint}")
        return r

    @staticmethod
    def _usage(d: dict, t0: float) -> Usage:
        return Usage(d.get("prompt_eval_count", 0), d.get("eval_count", 0),
                     latency_ms=int((time.monotonic() - t0) * 1000))

    def chat(self, messages: list[Message], *, temperature=0.7, max_tokens=512, schema=None) -> Reply:
        t0 = time.monotonic()
        r = self._post(self._body(messages, temperature, max_tokens, False, schema), False)
        try:
            d = r.json()
            text = d["message"]["content"]
        except (ValueError, KeyError, TypeError):
            raise LLMError("Ollama zwróciła nieczytelną odpowiedź.") from None
        u = self._usage(d, t0)
        log.info("ollama chat model=%s in=%d out=%d", self.model, u.in_tokens, u.out_tokens)
        return Reply(text, u, self.name, self.model)

    def stream(self, messages, *, temperature=0.7, max_tokens=512, cancel: CancelToken | None = None) -> Stream:
        cancel = cancel or CancelToken()
        t0 = time.monotonic()

        def gen() -> Iterator[str]:
            r = self._post(self._body(messages, temperature, max_tokens, True), True)
            cancel.on_cancel(r.close)  # odblokowuje czytanie z innego wątku
            try:
                for line in r.iter_lines():
                    if not line:
                        continue
                    d = json.loads(line)
                    if d.get("done"):
                        return self._usage(d, t0)
                    if c := d.get("message", {}).get("content"):
                        yield c
                raise LLMUnavailable("Strumień Ollamy zakończył się bez zakończenia odpowiedzi.")
            except requests.Timeout:
                raise LLMTimeout("Ollama przestała odpowiadać.") from None
            except (requests.RequestException, ValueError):
                if cancel.is_set():
                    return None
                raise LLMUnavailable("Połączenie z Ollamą przerwane.") from None
            finally:
                r.close()
        return Stream(gen(), cancel)

    def health(self) -> bool:
        try:
            return requests.get(f"{self.url}/api/tags", timeout=3).ok
        except requests.RequestException:
            return False
