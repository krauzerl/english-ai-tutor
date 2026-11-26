"""Poziomy CEFR, mapowanie θ ↔ etykieta, sufit/podłoga (04_PEDAGOGY_SPEC §4.2–§4.3). Czysty Python."""
from __future__ import annotations

import math

from tutor.pedagogy.content import CEFR_LEVELS


def level_index(label: str) -> int:
    return CEFR_LEVELS.index(label) + 1  # A1 = 1 … C2 = 6


def label_of(theta: float, top_index: int = 6) -> str:
    """Poziom k = przedział [k−0,5; k+0,5). `top_index` ogranicza etykietę (bank do C1 → 5)."""
    k = min(max(math.floor(theta + 0.5), 1), top_index)
    return CEFR_LEVELS[k - 1]


def clamp_theta(theta: float, top_index: int = 5) -> float:
    """Średnia θ obcięta przy zapisie poziomu (bank do C1 → 5,5): nigdy C2 bez zadań C2."""
    return min(theta, top_index + 0.5)


def interval_text(mean: float, lo: float, hi: float, *, ceiling: bool = False, floor: bool = False,
                  top_index: int = 5) -> str:
    top, bottom = CEFR_LEVELS[top_index - 1], CEFR_LEVELS[0]
    if ceiling:
        return f"{top} lub wyżej"
    if floor:
        return f"{bottom} lub niżej"
    m, a, b = (label_of(x, top_index) for x in (mean, lo, hi))
    return m if a == b else f"przedział {a}–{b} (środek: {m})"     # B-lite: przedział ważniejszy niż etykieta
