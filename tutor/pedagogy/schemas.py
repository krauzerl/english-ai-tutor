"""Schematy wyjścia LLM (04_PEDAGOGY_SPEC §3.4). Wejście walidowane w `app/` przez `structured()`.

Klucze są krótkie (limit tokenów Bielika). LLM nie zwraca stt_suspect ani disfluency: nadaje je kod.
`cq` (cytat-dowód komunikatywności) dodano do §3.4: etykieta `cm` bez dosłownego cytatu = `na` (§2.1 wymaga cytatu).
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Obs(BaseModel):
    s: str                                   # span: dosłowny cytat
    f: str                                   # poprawka
    k: Literal["error", "natural", "variant"]
    c: str                                   # kategoria taksonomii (sprawdzana przez `classify`)
    v: int = Field(ge=1, le=3)               # waga: 1 sens bez zmian, 2 wyraźny, 3 utrudnia zrozumienie
    p: Literal["h", "m", "l"]


class Use(BaseModel):
    id: str                                  # skill_id celu lekcji
    r: Literal["ok", "bad"]
    s: str


class Utt(BaseModel):
    i: int = Field(ge=0)
    o: list[Obs] = []
    t: list[Use] = []
    cm: Literal["ok", "partial", "fail", "na"] = "na"
    cq: str = ""


class TurnEval(BaseModel):
    u: list[Utt]


class RubricScoreItem(BaseModel):
    descriptor_id: str
    status: Literal["met", "partial", "not_met"]
    evidence_quote: str = ""


class RubricScore(BaseModel):
    scores: list[RubricScoreItem]
