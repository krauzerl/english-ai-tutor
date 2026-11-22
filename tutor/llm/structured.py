"""Odpowiedzi strukturalne: JSON → Pydantic, maks. 1 ponowna próba, potem wyjątek."""
from __future__ import annotations

from pydantic import BaseModel, ValidationError

from tutor.llm.base import InvalidStructuredOutput, LLMProvider, Message, log

RETRY_HINT = ("Poprzednia odpowiedź nie była poprawnym JSON zgodnym ze schematem. "
              "Zwróć wyłącznie poprawny JSON.")


def structured[T: BaseModel](provider: LLMProvider, messages: list[Message], model: type[T], *,
                             temperature: float = 0.0, max_tokens: int = 1024) -> T:
    """Zwraca wyłącznie zwalidowany obiekt; nic niezweryfikowanego nie wychodzi na zewnątrz."""
    schema = model.model_json_schema()
    msgs = list(messages)
    for attempt in (1, 2):
        reply = provider.chat(msgs, temperature=temperature, max_tokens=max_tokens, schema=schema)
        try:
            return model.model_validate_json(reply.text)
        except ValidationError:
            log.warning("structured output invalid (attempt %d, schema %s)", attempt, model.__name__)
            msgs = [*messages, Message("user", RETRY_HINT)]
    raise InvalidStructuredOutput("Model zwrócił niepoprawną odpowiedź strukturalną.")
