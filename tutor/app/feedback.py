"""Informacja zwrotna z rozmowy (F5.10) z istniejących obserwacji oceny; bez nowego klasyfikatora i bez wywołań LLM.

Zasady (04 §3): styl `summary` nigdy nie przerywa rozmowy (korekty w podsumowaniu na końcu); `periodic`/`intensive`
dają jeden niewymuszony recast w następnej odpowiedzi tutora wg `correction.select` (próg wagi, odstęp tur, cel lekcji).
Bierzemy tylko obserwacje `valid` z pewnością modelu `h`. `stt_suspect` to co najwyżej łagodne sprawdzenie
(„mogłem źle usłyszeć”), nigdy błąd ucznia.
"""
from __future__ import annotations

from tutor.pedagogy import correction as K
from tutor.pedagogy.content import Pack


def _candidates(repo, pack: Pack, pid: int, sid: int, goals: set[str], skip: set[int]) -> list[tuple[K.Candidate, str]]:
    out = []
    for o in repo.list_observations(pid, sid, status="valid"):
        if o["kind"] not in ("error", "stt_suspect") or o["confidence"] != "h" or not o["fix"] or o["id"] in skip:
            continue
        out.append((K.Candidate(o["id"], o["turn_id"], o["category"] or "", o["skill_id"], o["severity"] or 1, 1,
                                o["skill_id"] in goals, o["span"], o["fix"]), o["kind"]))
    return out


def recast_directive(repo, pack: Pack, pid: int, sid: int, style: str, goals: set[str]) -> str | None:
    """Notatka dla tutora na JEDNĄ odpowiedź albo None. Zapisuje w planie sesji, co już było użyte."""
    if style == "summary":
        return None
    plan = repo.get_session_plan(pid, sid)
    st = plan.get("recast") or {"done": [], "last_turn": None, "cats": []}
    cands = _candidates(repo, pack, pid, sid, goals, set(st["done"]))
    if not cands:
        return None
    kinds = {c.obs_id: k for c, k in cands}
    turn_index = sum(1 for t in repo.list_turns(pid, sid) if t["role"] == "user")
    for d in K.select([c for c, _ in cands], style, turn_index=turn_index, last_correction_turn=st["last_turn"],
                      corrected_categories=set(st["cats"]), rubric=pack.rubric):
        if d.candidate is None:
            continue
        c = d.candidate
        repo.set_session_plan(pid, sid, {**plan, "recast": {"done": [*st["done"], c.obs_id], "last_turn": turn_index,
                                                            "cats": [*st["cats"], c.category]}})
        hedge = (" You may have misheard the student, so make it a friendly check, not a correction."
                 if kinds[c.obs_id] == "stt_suspect" else "")
        return (f"Feedback note (never mention this note): earlier the student said “{c.span}”; the natural form is "
                f"“{c.fix}”. In your reply, use the natural form once, as part of a normal sentence (a gentle recast). "
                "Do not say they made a mistake, do not explain grammar, do not repeat it later, and still react to "
                f"what they just said.{hedge}")
    return None


def _explain(pack: Pack, category: str) -> str:
    cats = {c.id: c for c in pack.errors.categories}
    c = cats.get(category) or cats.get(category.split(".")[0])
    return c.explanation_pl if c else ""


def summary_lines(repo, pack: Pack, pid: int, sid: int) -> list[str]:
    cands = _candidates(repo, pack, pid, sid, set(), set())
    if not cands:
        return []
    kinds = {c.obs_id: k for c, k in cands}
    lines = ["Do poprawy w tej rozmowie (to sugestie modelu — mogę się mylić):"]
    for c in K.quiz([c for c, _ in cands], pack.rubric):
        why = _explain(pack, c.category)
        line = f"• „{c.span}” → „{c.fix}”" + (f" — {why}" if why else "")
        if kinds[c.obs_id] == "stt_suspect":
            line += " (możliwe, że źle usłyszałem — sprawdź, czy tak powiedziałeś/aś)"
        lines.append(line)
    return lines
