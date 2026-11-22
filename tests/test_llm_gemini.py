"""Gemini na atrapie klienta SDK (bez sieci, bez kosztów)."""
from types import SimpleNamespace as NS

import pytest
from google.genai import errors

from tutor.llm.base import (
    CancelToken,
    LLMError,
    LLMTimeout,
    LLMUnavailable,
    Message,
    StreamInterrupted,
)
from tutor.llm.gemini import GeminiProvider

KEY = "AIza-SEKRETNY-KLUCZ"
MSG = [Message("system", "SYS"), Message("user", "hi"), Message("assistant", "yo"), Message("user", "q")]


def resp(text, i=10, o=4, t=6):
    return NS(text=text, usage_metadata=NS(prompt_token_count=i, candidates_token_count=o,
                                           thoughts_token_count=t))


class FakeModels:
    def __init__(self, result=None, chunks=None, exc=None):
        self.result, self.chunks, self.exc, self.calls = result, chunks, exc, []

    def generate_content(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        return self.result

    def generate_content_stream(self, **kw):
        self.calls.append(kw)
        if self.exc:
            raise self.exc
        yield from self.chunks()


def prov(models, **kw):
    return GeminiProvider(model="gemini-test", api_key=KEY, client=NS(models=models), **kw)


def test_chat_maps_messages_usage_and_reasoning():
    m = FakeModels(resp("hello"))
    r = prov(m).chat(MSG, temperature=0.2, max_tokens=50)
    assert r.text == "hello" and (r.usage.in_tokens, r.usage.out_tokens, r.usage.reasoning_tokens) == (10, 4, 6)
    kw = m.calls[0]
    assert kw["model"] == "gemini-test"
    assert kw["config"].system_instruction == "SYS"
    assert [c.role for c in kw["contents"]] == ["user", "model", "user"]
    assert kw["config"].max_output_tokens == 50


def test_model_name_required():
    with pytest.raises(ValueError):
        GeminiProvider(model="", api_key=KEY, client=NS(models=FakeModels()))


def test_structured_uses_json_schema():
    m = FakeModels(resp("{}"))
    prov(m).chat(MSG, temperature=0, max_tokens=50, schema={"type": "object"})
    cfg = m.calls[0]["config"]
    assert cfg.response_mime_type == "application/json" and cfg.response_json_schema == {"type": "object"}


def test_stream_and_usage_from_last_chunk():
    m = FakeModels(chunks=lambda: iter([resp("He", 0, 0, 0), resp("llo", 10, 4, 6)]))
    s = prov(m).stream(MSG, temperature=0, max_tokens=9)
    assert "".join(s) == "Hello" and s.usage.reasoning_tokens == 6


def test_stream_cancel():
    m = FakeModels(chunks=lambda: iter([resp("a"), resp("b"), resp("c")]))
    tok = CancelToken()
    s = prov(m).stream(MSG, temperature=0, max_tokens=9, cancel=tok)
    assert next(s) == "a"
    tok.set()
    assert list(s) == [] and s.cancelled


def test_stream_failure_midway_interrupted():
    def chunks():
        yield resp("a")
        raise errors.ServerError(503, {"error": {"message": "x"}})
    s = prov(FakeModels(chunks=chunks)).stream(MSG, temperature=0, max_tokens=9)
    with pytest.raises(StreamInterrupted) as e:
        list(s)
    assert e.value.partial == "a"


@pytest.mark.parametrize("exc,cls", [
    (errors.ServerError(503, {"error": {"message": "x"}}), LLMUnavailable),
    (errors.ClientError(429, {"error": {"message": "quota"}}), LLMUnavailable),
    (errors.ClientError(400, {"error": {"message": "bad"}}), LLMError),
    (TimeoutError("t"), LLMTimeout),
    (ConnectionError("c"), LLMUnavailable),
])
def test_errors_are_controlled(exc, cls):
    with pytest.raises(cls) as e:
        prov(FakeModels(exc=exc)).chat(MSG, temperature=0, max_tokens=5)
    assert e.type is cls or issubclass(e.type, cls)


def test_key_scrubbed_from_errors_and_repr():
    exc = errors.ClientError(400, {"error": {"message": f"bad key {KEY}"}})
    p = prov(FakeModels(exc=exc))
    with pytest.raises(LLMError) as e:
        p.chat(MSG, temperature=0, max_tokens=5)
    assert KEY not in str(e.value) and KEY not in repr(e.value) and KEY not in repr(p)
    assert e.value.__cause__ is None or KEY not in str(e.value.__cause__)


def test_is_external():
    assert prov(FakeModels()).external is True
