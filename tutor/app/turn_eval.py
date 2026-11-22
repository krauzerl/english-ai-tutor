"""Punkt wywołania oceny wypowiedzi (04 §3.4, 07 §4.2). Używany przez benchmark; NIE jest podłączony do rozmowy (F5).

Kolejność: prefiltr → TurnEval (model) → [opcjonalnie scalenie z kandydatami LanguageTool] → `classify` + walidatory.
Brak oceny modelu ⇒ wypowiedź nieoceniona (LanguageTool sam nie dowodzi poprawności ani błędu).
"""
from __future__ import annotations

import json
import unicodedata

from tutor.llm.base import InvalidStructuredOutput, LLMError, Message
from tutor.pedagogy import assessment as A
from tutor.pedagogy import edits as E
from tutor.pedagogy import lt_merge
from tutor.pedagogy.content import Pack
from tutor.pedagogy.schemas import Obs, TurnEval


def build_prompt(pack: Pack, texts: list[str], *, goals: dict[str, str] | None = None, tutor_prev: str = "") -> str:
    marked = [A.prefilter(t, pack.disfluency).marked for t in texts]
    p = pack.prompts["turn_eval"]["text"]
    tax = ", ".join(sorted(A.allowed_categories(pack.errors)))
    goals_s = "\n".join(f"- {k}: {v}" for k, v in (goals or {}).items()) or "(none)"
    utts = "\n".join(f"{i}: {json.dumps(t, ensure_ascii=False)}" for i, t in enumerate(marked))
    for k, v in {"max_utterances": len(texts), "taxonomy": tax, "goals": goals_s,
                 "tutor_prev": tutor_prev or "(none)", "utterances": utts}.items():
        p = p.replace("{" + k + "}", str(v))
    return p


def evaluate_texts(pack: Pack, provider, structured, texts: list[str], *, input_modes: list[str],
                   low_probs: list[set[str]], goals: dict[str, str] | None = None, tutor_prev: str = "",
                   lt: list[list[Obs]] | None = None, max_tokens: int = 700) -> list[A.UttResult]:
    texts = [unicodedata.normalize("NFC", t) for t in texts]      # tekst kanoniczny: offsety LT i cytaty spójne
    ev: TurnEval | None
    try:
        ev = structured(provider, [Message("user", build_prompt(pack, texts, goals=goals, tutor_prev=tutor_prev))],
                        TurnEval, temperature=0.0, max_tokens=max_tokens)
    except (InvalidStructuredOutput, LLMError):
        ev = None
    if ev is not None:                 # F4.7: minimalny jednoznaczny span (prompt tego wymaga, kod pilnuje)
        ev = TurnEval(u=[u.model_copy(update={"o": [E.minimize(texts[u.i], o) if o.k == "error" and u.i < len(texts)
                                                      else o for o in u.o]}) for u in ev.u])
    if ev is not None and lt:
        ev = lt_merge.merge_eval(ev, texts, lt)
    return A.evaluate_batch(ev, texts, input_modes=input_modes, low_probs=low_probs, pack=pack,
                            goals=set(goals or {}))
