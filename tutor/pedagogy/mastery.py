"""BKT, statusy umiejętności, odblokowanie prerekwizytów (§4.5–§4.6). Parametry z `rubric.yaml`."""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from tutor.pedagogy.cefr import level_index
from tutor.pedagogy.content import Rubric, Skill

MASTERED = ("mastered", "retained_7d", "retained_30d")
PRODUCTIVE_SRC = ("production", "conversation", "correction")


def _sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def bkt_step(p: float, correct: bool, learn: float, slip: float, guess: float) -> float:
    if correct:
        post = p * (1 - slip) / (p * (1 - slip) + (1 - p) * guess)
    else:
        post = p * slip / (p * slip + (1 - p) * (1 - guess))
    return post + (1 - post) * learn


def bkt_source(src: str, hint_level: int, rubric: Rubric) -> str:
    """Mapa źródła próby na wiersz tabeli BKT. L1 (sam sygnał) liczy się jak rozmowa (§3.2)."""
    if src == "correction":
        return rubric.mastery["correction_l1_source"] if hint_level <= 1 else "correction"
    return src


def _params(rubric: Rubric, bkt: str, n_options: int | None):
    b = rubric.bkt[bkt]
    guess = (1 / n_options if n_options else 0.25) if b.p_guess == "options" else b.p_guess
    return b.p_learn, b.p_slip, guess


def replay(attempts: list[dict], rubric: Rubric, p0: float) -> float:
    """p z całej historii prób (kolejność chronologiczna). Pochodne od prób ⇒ idempotentne.

    Próba: {correct: bool, bkt: mc|production|conversation|correction, n_options: int|None}.
    """
    p = p0
    for a in attempts:
        p = bkt_step(p, bool(a["correct"]), *_params(rubric, a["bkt"], a.get("n_options")))
    return p


def p_init(theta_area: float | None, b_skill: float, rubric: Rubric) -> float:
    lo, hi = rubric.mastery["p_init_clamp"]
    if theta_area is None:
        return rubric.bkt["production"].p_init or lo
    return min(max(_sigmoid(theta_area - b_skill), lo), hi)


@dataclass(frozen=True)
class SkillState:
    skill_id: str
    p: float = 0.2
    status: str = "new"
    attempts: int = 0
    mastered_at: str | None = None
    verify_due_at: str | None = None
    verified_7d_at: str | None = None
    verified_30d_at: str | None = None
    relapses: int = 0


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def update_status(st: SkillState, p: float, attempts: list[dict], area: str, rubric: Rubric,
                  now: datetime) -> SkillState:
    """new → learning → mastered. Opanowanie: p ≥ próg i poprawne próby PRODUKCYJNE (bez podpowiedzi)
    w ≥ min_days różnych dniach; w obszarach receptywnych (reading/listening) wystarczą poprawne próby.
    Statusy retained_* zmienia wyłącznie `retention`."""
    m = rubric.mastery
    n = len(attempts)
    if st.status in MASTERED:
        return replace(st, p=p, attempts=n)
    receptive = area in m["receptive_areas"]
    days = {a["day"] for a in attempts if a["correct"] and a.get("hint_level", 0) == 0
            and not a.get("no_mastery")                    # próby ćwiczeniowe / niepewne STT nie dają statusu
            and (receptive or a["bkt"] in PRODUCTIVE_SRC)}
    if p >= m["p_master"] and len(days) >= m["min_days"]:
        return replace(st, p=p, attempts=n, status="mastered", mastered_at=_iso(now),
                       verify_due_at=_iso(now + timedelta(days=rubric.retention["d7"])))
    return replace(st, p=p, attempts=n, status="learning" if n else st.status)


def unlocked(skill: Skill, states: dict[str, SkillState], levels: dict[str, float],
             skills: dict[str, Skill]) -> bool:
    """Prerekwizyt spełniony: status ≥ mastered LUB poziom obszaru ≥ poziom prerekwizytu + 1 (§4.5)."""
    for pid in skill.prereqs:
        pre = skills[pid]
        st = states.get(pid)
        if st and st.status in MASTERED:
            continue
        if levels.get(pre.area, 0) >= level_index(pre.cefr) + 1:
            continue
        return False
    return True
