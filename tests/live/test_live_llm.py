"""Testy live (domyślnie pomijane): `pytest -m live`.

Ollama: wymaga `ollama serve` i zainstalowanego modelu (OLLAMA_LIVE_MODEL, domyślnie Bielik 11B).
Gemini: PŁATNE/limitowane. Wymaga GEMINI_API_KEY (env lub ~/.config/english-ai-tutor/.env)
oraz GEMINI_LIVE_MODEL; wykonuje 2 krótkie żądania (max_tokens ≤ 64).
"""
import os

import pytest
from pydantic import BaseModel

from tutor import config
from tutor.llm.base import CancelToken, Message
from tutor.llm.ollama import DEFAULT_MODEL, OllamaProvider
from tutor.llm.structured import structured

pytestmark = pytest.mark.live
MSG = [Message("system", "You are a concise English tutor."), Message("user", "Say hello in 5 words.")]


class Greeting(BaseModel):
    greeting: str


@pytest.fixture(scope="module")
def ollama():
    p = OllamaProvider(os.environ.get("OLLAMA_LIVE_MODEL", DEFAULT_MODEL), timeout=300)
    if not p.health():
        pytest.skip("Ollama nie działa (uruchom `ollama serve`)")
    return p


def test_ollama_chat_usage(ollama):
    r = ollama.chat(MSG, temperature=0, max_tokens=40)
    assert r.text and r.usage.in_tokens > 0 and r.usage.out_tokens > 0


def test_ollama_stream_and_cancel(ollama):
    tok = CancelToken()
    s = ollama.stream([Message("user", "Count from 1 to 100.")], temperature=0, max_tokens=300, cancel=tok)
    next(s)
    tok.set()
    list(s)
    assert s.cancelled


def test_ollama_structured(ollama):
    g = structured(ollama, [Message("user", 'Return JSON {"greeting": "<a greeting>"}')], Greeting, max_tokens=60)
    assert g.greeting


@pytest.fixture(scope="module")
def gemini():
    key, model = config.gemini_api_key(), os.environ.get("GEMINI_LIVE_MODEL")
    if not key or not model:
        pytest.skip("ODROCZONE: Gemini nieskonfigurowany (brak GEMINI_API_KEY lub GEMINI_LIVE_MODEL)")
    from tutor.llm.gemini import GeminiProvider
    return GeminiProvider(model, key)


def test_gemini_chat_usage(gemini):
    r = gemini.chat(MSG, temperature=0, max_tokens=64)
    assert r.text and r.usage.in_tokens > 0


def test_gemini_structured(gemini):
    g = structured(gemini, [Message("user", "Give a greeting.")], Greeting, max_tokens=64)
    assert g.greeting
