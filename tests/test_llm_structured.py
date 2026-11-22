"""T-LLM-1, T-LLM-2 + zachowanie retry."""
from typing import Literal

import pytest
from pydantic import BaseModel

from tests.llm_fakes import FakeProvider
from tutor.llm.base import InvalidStructuredOutput, LLMTimeout, Message
from tutor.llm.structured import structured


class Err(BaseModel):
    category: Literal["tense", "article", "word_order"]
    level: Literal["A1", "A2", "B1", "B2", "C1", "C2"]


MSG = [Message("user", "x")]


def test_valid_first_try():
    p = FakeProvider(replies=['{"category":"tense","level":"B1"}'])
    assert structured(p, MSG, Err) == Err(category="tense", level="B1")
    assert len(p.calls) == 1


def test_bad_json_retries_once_then_raises():  # T-LLM-1
    p = FakeProvider(replies=["nie json", "{still bad"])
    with pytest.raises(InvalidStructuredOutput):
        structured(p, MSG, Err)
    assert len(p.calls) == 2  # dokładnie jedna ponowna próba


def test_retry_can_succeed():
    p = FakeProvider(replies=["zle", '{"category":"article","level":"A2"}'])
    assert structured(p, MSG, Err).category == "article"


@pytest.mark.parametrize("bad", [
    '{"category":"vibes","level":"B1"}',   # niedozwolona kategoria
    '{"category":"tense","level":"D9"}',   # poziom spoza A1-C2
    '{"category":"tense"}',                # brak pola
])
def test_t_llm_2_schema_violations_rejected(bad):
    p = FakeProvider(replies=[bad, bad])
    with pytest.raises(InvalidStructuredOutput):
        structured(p, MSG, Err)


def test_error_message_has_no_model_output():
    p = FakeProvider(replies=["SEKRET-TRESC", "SEKRET-TRESC"])
    with pytest.raises(InvalidStructuredOutput) as e:
        structured(p, MSG, Err)
    assert "SEKRET-TRESC" not in str(e.value)


def test_provider_error_is_not_retried():
    p = FakeProvider(replies=[LLMTimeout("t")])
    with pytest.raises(LLMTimeout):
        structured(p, MSG, Err)
    assert len(p.calls) == 1


@pytest.mark.skip(reason="T-LLM-3 pełny przepływ (tura ucznia zachowana przez SessionService): odroczony do F5")
def test_t_llm_3_session_flow_deferred():
    ...
