"""Mechanizm korekty (§3): tryby, priorytet, drabina podpowiedzi L1–L4, ponowne użycie. Bez wywołań LLM.

Niejednoznaczna próba ucznia zwraca `NEEDS_EVAL` — jedno krótkie wywołanie TurnEval obsłuży `app/` (F5).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, replace

from tutor.pedagogy.content import ErrorCategory, Rubric, norm_answer

NEEDS_EVAL = "NEEDS_EVAL"
STYLES = ("summary", "periodic", "intensive")


def effective_style(profile_style: str | None, rubric: Rubric) -> dict:
    """Domyślnie `summary`, dopóki brama jakości oceny Bielika (F8) nie przeszła. Jawny wybór ucznia jest
    respektowany, ale przy niespełnionej bramie korekty są formułowane jako „sugestia” (§3.3)."""
    c = rubric.correction
    style = profile_style if profile_style in STYLES else c["default_style"]
    gate = bool(c["quality_gate"]["bielik_benchmark_passed"])
    return {"style": style, "gate_passed": gate,
            "suggestion_wording": (not gate) and style != "summary" and c["suggestion_wording_when_gate_open"]}


def priority(sev: int, count_30d: int, is_goal: bool, corrected_this_session: bool, rubric: Rubric) -> float:
    """sev × (1 + log2(count_30d)) × (2 jeśli cel lekcji) × (0,5 jeśli kategoria była korygowana w sesji)."""
    p = rubric.correction["priority"]
    return (sev * (1 + math.log2(max(count_30d, 1))) * (p["goal_multiplier"] if is_goal else 1.0)
            * (p["same_session_multiplier"] if corrected_this_session else 1.0))


@dataclass(frozen=True)
class Candidate:
    obs_id: int
    turn_id: int
    category: str
    skill_id: str | None
    severity: int
    count_30d: int
    is_goal: bool
    span: str
    fix: str


@dataclass(frozen=True)
class Decision:
    candidate: Candidate | None
    form: str | None            # recast | ladder | None
    reason: str


def _prio(c: Candidate, corrected: set[str], rubric: Rubric) -> tuple[float, int]:
    return (priority(c.severity, c.count_30d, c.is_goal, c.category in corrected, rubric), c.turn_id)


def select(candidates: list[Candidate], style: str, *, turn_index: int, last_correction_turn: int | None,
           corrected_categories: set[str], rubric: Rubric, elapsed_s: float | None = None) -> list[Decision]:
    """Polityka trybów (§3.1). `turn_index` = numer tury ucznia w sesji."""
    c = rubric.correction
    if style == "summary":
        return []                                        # nigdy w trakcie rozmowy
    if style == "intensive" and elapsed_s is not None and elapsed_s > c["intensive_timeout_s"]:
        return [Decision(None, None, "timeout")]         # tura bez korekty; nic nie zmyślamy
    sev_min = c["sev_min_interrupt"]
    rec = rubric.errors["recurring_count"]
    if style == "periodic":
        if last_correction_turn is not None and turn_index - last_correction_turn < c["periodic_turns_per_correction"]:
            return []
        ok = [x for x in candidates if x.severity >= sev_min or x.count_30d >= rec or x.is_goal]
        if not ok:
            return []
        best = max(ok, key=lambda x: _prio(x, corrected_categories, rubric))
        return [Decision(best, "recast", "periodic")]    # max 1 kategoria naraz
    ok = [x for x in candidates if x.severity >= sev_min or x.is_goal]       # intensive: także sev 1 w celu lekcji
    return [Decision(x, "ladder", "intensive") for x in sorted(
        ok, key=lambda x: _prio(x, corrected_categories, rubric), reverse=True)]


def summary_batch_due(pending: int, at_checkpoint_or_end: bool, rubric: Rubric) -> bool:
    return pending > 0 and (at_checkpoint_or_end or pending >= rubric.correction["summary_batch"])


def quiz(candidates: list[Candidate], rubric: Rubric) -> list[Candidate]:
    """Quiz autokorekty (summary): do `quiz_sentences_max` zdań ucznia z błędami, po jednym na wypowiedź."""
    best: dict[int, Candidate] = {}
    for x in sorted(candidates, key=lambda x: _prio(x, set(), rubric), reverse=True):
        best.setdefault(x.turn_id, x)
    return list(best.values())[:rubric.correction["quiz_sentences_max"]]


# --- drabina podpowiedzi ---
@dataclass(frozen=True)
class Ladder:
    category: str
    skill_id: str | None
    span: str
    fix: str
    level: int = 1                  # poziom aktualnie pokazanej podpowiedzi (1–4)
    done: bool = False
    outcome: str | None = None      # correct | failed
    tries: int = 0

    @property
    def final_hint_level(self) -> int:
        return self.level


def start_ladder(c: Candidate) -> Ladder:
    return Ladder(c.category, c.skill_id, c.span, c.fix)


def check_attempt(text: str, ladder: Ladder, patterns: list[str] | None = None) -> str:
    """correct | incorrect | NEEDS_EVAL. Deterministycznie: znormalizowana próba zawiera `fix`; zawiera dawny
    błąd bez `fix` → incorrect; reszta jest niejednoznaczna."""
    t = f" {norm_answer(text)} "
    if not t.strip():
        return "incorrect"
    fix, span = f" {norm_answer(ladder.fix)} ", f" {norm_answer(ladder.span)} "
    if fix in t:
        return "correct"
    if span in t:
        return "incorrect"
    return NEEDS_EVAL


def advance(lad: Ladder, result: str) -> tuple[Ladder, str]:
    """Po próbie ucznia. correct → koniec; incorrect → następny poziom, a po L4 porażka; NEEDS_EVAL → bez zmian."""
    if lad.done:
        raise ValueError("drabina zakończona")
    if result == NEEDS_EVAL:
        return lad, NEEDS_EVAL
    lad = replace(lad, tries=lad.tries + 1)
    if result == "correct":
        return replace(lad, done=True, outcome="correct"), "done"
    if lad.level >= 4:
        return replace(lad, done=True, outcome="failed"), "done"
    return replace(lad, level=lad.level + 1), f"show_L{lad.level + 1}"


def render_hint(level: int, cat: ErrorCategory | None, lad: Ladder, choice_template: str, seed: int = 0) -> str:
    """L1 sygnał; L2 podpowiedź metajęzykowa (PL); L3 elicytacja/wybór z 2; L4 jawna poprawka + wyjaśnienie."""
    if level == 1:
        return cat.l1 if cat else "Almost! Check it again."
    if level == 2:
        return cat.l2_pl if cat else "Sprawdź regułę dla tego zwrotu."
    if level == 3:
        if cat and cat.l3:
            return cat.l3
        pair = [lad.span, lad.fix]
        random.Random(f"{seed}:{lad.span}").shuffle(pair)
        return choice_template.format(a=pair[0], b=pair[1])
    return f"{lad.fix}\n{cat.explanation_pl}" if cat else lad.fix


def attempt_record(lad: Ladder, correct: bool) -> dict:
    """Wiersz `attempt` dla pojedynczej próby na poziomie `lad.level` (BKT: źródło `correction`/L1→rozmowa)."""
    return {"source": "correction", "hint_level": lad.level, "correct": correct, "skill_id": lad.skill_id,
            "dedupe_suffix": f"{lad.category}:{norm_answer(lad.span)}:L{lad.level}:{lad.tries}"}


# --- ponowne użycie (uptake) ---
def add_reuse_target(plan: dict, *, skill_id: str | None, category: str, fix: str, from_turn: int) -> dict:
    targets = list(plan.get("reuse_targets", []))
    key = (category, skill_id, fix)
    if all((t["category"], t["skill_id"], t["fix"]) != key for t in targets):
        targets.append({"skill_id": skill_id, "category": category, "fix": fix, "from_turn": from_turn})
    return {**plan, "reuse_targets": targets}


def reuse_window(target: dict, rubric: Rubric) -> tuple[int, int]:
    lo, hi = rubric.correction["uptake_turns"]
    return target["from_turn"] + lo, target["from_turn"] + hi


def reuse_outcome(target: dict, turn_index: int, *, positive_skills: set[str], error_categories: set[str],
                  rubric: Rubric) -> dict | None:
    """Poprawne użycie bez podpowiedzi = najsilniejszy dowód (hint_level=0). None = brak okazji w tej turze."""
    lo, hi = reuse_window(target, rubric)
    if not lo <= turn_index <= hi:
        return None
    if target["skill_id"] and target["skill_id"] in positive_skills:
        return {"source": "conversation", "hint_level": 0, "correct": True, "skill_id": target["skill_id"]}
    if target["category"] in error_categories:
        return {"source": "conversation", "hint_level": 0, "correct": False, "skill_id": target["skill_id"]}
    return None
