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


# --- waga błędu dla rozmowy (Quick Chat): deterministycznie, z edycji — NIE z deklarowanej pewności modelu ---
SERIOUS, GRAMMAR, MINOR = "serious", "grammar", "minor"
# Drobne w rozmowie: zrozumiałe mimo błędu albo zależne od stylu; nigdy nie przerywają (tylko podsumowanie).
MINOR_CORES = {"preposition", "article", "determiner", "word_choice", "collocation", "register", "l1_calque",
               "spelling", "punctuation", "capitalization"}
# Pary, w których pomyłka zmienia sens (uczeń mówi co innego, niż myśli). Mała, jawna lista — nie klasyfikator.
_ING_ED = {"bor", "interest", "excit", "tir", "confus", "embarrass", "disappoint", "surpris", "annoy", "worr",
           "frighten", "amaz", "satisf", "exhaust", "frustrat", "relax", "shock", "terrify", "terrif"}
_PAIRS = {frozenset(p): why for p, why in (
    (("borrow", "lend"), "you borrow FROM someone, you lend TO someone"),
    (("borrowed", "lent"), "you borrow FROM someone, you lend TO someone"),
    (("borrows", "lends"), "you borrow FROM someone, you lend TO someone"),
    (("actually", "currently"), "“actually” means “in fact”; “currently” means “now”"),
    (("eventually", "possibly"), "“eventually” means “in the end”; “possibly” means “maybe”"),
    (("sympathetic", "nice"), "“sympathetic” means “understanding someone's problems”, not “nice”"),
    (("sensible", "sensitive"), "“sensible” means “reasonable”; “sensitive” means “easily affected”"),
    (("receipt", "recipe"), "a “recipe” is for cooking; a “receipt” is proof that you paid"),
)}   # he/she celowo nie: walidator `meaning_change` odrzuca zmianę osoby (nie wiemy, o kim mowa)
_NEG_BAD = {"no", "not"}
_NEG_GOOD = {"don't", "doesn't", "didn't", "do not", "does not", "did not", "haven't", "hasn't", "can't", "won't"}


def _ing_ed(x: str, y: str) -> bool:
    for a, b in ((x, y), (y, x)):
        if a.endswith("ing") and b.endswith(("ed", "d")):
            stem = a[:-3]
            if any(stem.startswith(s) for s in _ING_ED) and (b.startswith(stem[:3]) or b[:3] == a[:3]):
                return True
    return False


def impact(text: str, span: str, fix: str, category: str, *, count_30d: int = 1, discussed: bool = False,
           rubric: Rubric | None = None) -> tuple[str, str]:
    """(waga, powód) błędu dla decyzji w rozmowie. `serious` tylko z jawnych reguł: sens zmienia para słów
    (bored/boring, borrow/lend, fałszywi przyjaciele), rozbita negacja („I no understand”), albo ten sam
    wyraźny błąd gramatyczny powtarza się i był już omawiany. Pewność „h” zadeklarowana przez model nie wystarcza."""
    from tutor.pedagogy import edits as E
    es = E.edits(text, E.locate(text, span), fix)
    core = (category or "").split(".")[0]
    for e in es:
        old = [w.lower() for w in e.old]
        new = [w.lower() for w in e.new]
        if len(old) == 1 and len(new) == 1:
            if _ing_ed(old[0], new[0]):
                return SERIOUS, "meaning:ing_ed"
            if frozenset((old[0], new[0])) in _PAIRS:
                return SERIOUS, "meaning:pair"
        if set(old) & _NEG_BAD and (" ".join(new) in _NEG_GOOD or set(new) & {"don't", "doesn't", "didn't"}):
            return SERIOUS, "negation_form"
    if core in MINOR_CORES or not es:
        return MINOR, f"minor:{core or '?'}"
    rec = rubric.errors["recurring_count"] if rubric else 3
    if discussed and count_30d >= rec:
        return SERIOUS, "recurring_discussed"
    return GRAMMAR, f"grammar:{core}"


def fixed_category(text: str, span: str, fix: str, category: str) -> str:
    """Kategoria zgodna z edycją dla par zmieniających sens: -ing/-ed → `morphology.word_form` (Qwen3 dawał np.
    `morphology.irregular_past` dla „boring → bored”), rozbita negacja → `omission.auxiliary`."""
    tier, why = impact(text, span, fix, category)
    if why == "meaning:ing_ed":
        return "morphology.word_form"
    if why == "negation_form":
        return "omission.auxiliary"
    return category


def pair_note(text: str, span: str, fix: str) -> str | None:
    """Jedno zdanie różnicy (po angielsku, do notatki dla tutora) albo None."""
    from tutor.pedagogy import edits as E
    for e in E.edits(text, E.locate(text, span), fix):
        if len(e.old) == 1 and len(e.new) == 1:
            a, b = e.old[0].lower(), e.new[0].lower()
            if frozenset((a, b)) in _PAIRS:
                return _PAIRS[frozenset((a, b))]
            if _ing_ed(a, b):
                return "“-ed” is how a person feels; “-ing” is what makes them feel it"
    return None


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
def add_reuse_target(plan: dict, *, skill_id: str | None, category: str, fix: str, from_turn: int,
                     span: str | None = None, obs_id: int | None = None) -> dict:
    targets = list(plan.get("reuse_targets", []))
    key = (category, skill_id, fix)
    if all((t["category"], t["skill_id"], t["fix"]) != key for t in targets):
        targets.append({"skill_id": skill_id, "category": category, "fix": fix, "from_turn": from_turn,
                        "span": span, "obs_id": obs_id})
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


def changed_words(span: str, fix: str) -> set[str]:
    """Słowa poprawki, których nie było w cytacie („I go there” → „I went there” ⇒ {went})."""
    sw = set(norm_answer(span).split())
    return {w for w in norm_answer(fix).split() if w not in sw}


def uptake_check(target: dict, turn_index: int, text: str, error_categories: set[str],
                 rubric: Rubric) -> str | None:
    """Deterministyczny ślad uptake po korekcie: `repeated` — ocena tej tury znów zgłasza tę kategorię (dowód
    zależny od modelu); `used_ok` — uczeń sam użył poprawionej formy (wszystkie zmienione słowa) bez błędu tej
    kategorii; None — poza oknem albo brak okazji. To NIE jest dowód opanowania (nie zasila BKT)."""
    lo, hi = reuse_window(target, rubric)
    if not lo <= turn_index <= hi:
        return None
    if target["category"] in error_categories:
        return "repeated"
    want = changed_words(target.get("span") or "", target["fix"])
    words = set(norm_answer(text).split())
    return "used_ok" if want and want <= words else None
