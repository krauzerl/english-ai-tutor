"""Gemini przez oficjalny SDK google-genai. external=True. Model i klucz z konfiguracji."""
from __future__ import annotations

import time
from collections.abc import Iterator

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


class GeminiProvider:
    name, external = "gemini", True

    def __init__(self, model: str, api_key: str, timeout: float = 60, thinking_budget: int | None = None,
                 client=None):
        if not model:
            raise ValueError("Nazwa modelu Gemini jest wymagana (config.toml).")
        self.model, self.timeout, self.thinking_budget = model, timeout, thinking_budget
        self._key, self._client = api_key, client

    def __repr__(self) -> str:
        return f"GeminiProvider(model={self.model!r})"

    @property
    def client(self):
        if self._client is None:
            from google import genai
            from google.genai import types
            self._client = genai.Client(
                api_key=self._key, http_options=types.HttpOptions(timeout=int(self.timeout * 1000)))
        return self._client

    def _request(self, messages: list[Message], temperature, max_tokens, schema) -> dict:
        from google.genai import types
        system = "\n\n".join(m.content for m in messages if m.role == "system") or None
        contents = [types.Content(role="model" if m.role == "assistant" else "user",
                                  parts=[types.Part(text=m.content)])
                    for m in messages if m.role != "system"]
        kw = {"system_instruction": system, "temperature": temperature, "max_output_tokens": max_tokens}
        if schema is not None:
            kw.update(response_mime_type="application/json", response_json_schema=schema)
        if self.thinking_budget is not None:
            kw["thinking_config"] = types.ThinkingConfig(thinking_budget=self.thinking_budget)
        return {"model": self.model, "contents": contents, "config": types.GenerateContentConfig(**kw)}

    def _err(self, e: Exception) -> LLMError:
        """Komunikat zawsze własny: tekst wyjątku SDK może zawierać klucz lub treść."""
        from google.genai import errors
        if isinstance(e, errors.APIError):
            code = getattr(e, "code", 0) or 0
            if code in (401, 403):
                return LLMError("Gemini odrzuciło klucz API.")
            if code == 429 or code >= 500:
                return LLMUnavailable(f"Gemini chwilowo niedostępne (HTTP {code}, możliwy limit konta).")
            return LLMError(f"Gemini odrzuciło żądanie (HTTP {code}).")
        if isinstance(e, TimeoutError) or "Timeout" in type(e).__name__:
            return LLMTimeout("Gemini nie odpowiedziało w czasie.")
        if isinstance(e, OSError) or type(e).__module__.startswith("httpx"):
            return LLMUnavailable("Nie można połączyć się z Gemini.")
        return LLMError("Nieoczekiwany błąd Gemini.")

    @staticmethod
    def _usage(resp, t0: float) -> Usage:
        m = getattr(resp, "usage_metadata", None)
        g = lambda k: (getattr(m, k, 0) or 0) if m else 0  # noqa: E731
        return Usage(g("prompt_token_count"), g("candidates_token_count"), g("thoughts_token_count"),
                     int((time.monotonic() - t0) * 1000))

    def chat(self, messages, *, temperature=0.7, max_tokens=512, schema=None) -> Reply:
        t0 = time.monotonic()
        try:
            resp = self.client.models.generate_content(**self._request(messages, temperature, max_tokens, schema))
        except Exception as e:
            err = self._err(e)
            log.warning("gemini error %s", type(e).__name__)
            raise err from None
        u = self._usage(resp, t0)
        log.info("gemini chat model=%s in=%d out=%d reasoning=%d", self.model, u.in_tokens,
                 u.out_tokens, u.reasoning_tokens)
        return Reply(resp.text or "", u, self.name, self.model)

    def stream(self, messages, *, temperature=0.7, max_tokens=512, cancel: CancelToken | None = None) -> Stream:
        cancel = cancel or CancelToken()
        t0 = time.monotonic()

        def gen() -> Iterator[str]:
            last = None
            it = None
            try:
                it = self.client.models.generate_content_stream(
                    **self._request(messages, temperature, max_tokens, None))
                for chunk in it:
                    if getattr(chunk, "usage_metadata", None):
                        last = chunk
                    if chunk.text:
                        yield chunk.text
                    if cancel.is_set():
                        return None
            except GeneratorExit:
                raise
            except Exception as e:
                log.warning("gemini stream error %s", type(e).__name__)
                raise self._err(e) from None
            finally:
                close = getattr(it, "close", None)
                if close:
                    close()
            return self._usage(last, t0)
        return Stream(gen(), cancel)

    def health(self) -> bool:
        try:
            self.client.models.get(model=self.model)
            return True
        except Exception:
            return False
