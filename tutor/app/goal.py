"""Wybór celu lekcji (F5.9): istniejący planer F4 + dane ucznia z SQLite. Bez nowej diagnozy i nowego algorytmu.

Wybierany jest tylko cel, który da się poprowadzić (`lesson.prepare`: wyjaśnienie + zadania zamknięte). Brak
diagnozy i historii ⇒ jawnie oznaczony wybór STARTOWY (poziom domyślny z rubryki), nie wynik diagnozy.
Funkcja niczego nie zapisuje (żadnych zmian mastery).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from tutor.app import lesson as L
from tutor.pedagogy import content as C
from tutor.pedagogy import planner
from tutor.pedagogy.mastery import SkillState

NO_DIAGNOSIS = "To jest wybór startowy, nie jest wynikiem diagnozy."


@dataclass(frozen=True)
class Choice:
    skill_id: str
    source: str            # starter | plan | error
    reason: str
    provisional: bool      # poziom niezweryfikowany diagnozą
    category: str | None = None   # source=error: kategoria błędu, którą lekcja ma potwierdzić ćwiczeniem (AGV)


def completed(repo, profile_id: int) -> dict[str, dict]:
    """Ukończone lekcje (wszystkie zadania zrobione) per cel: wynik ostatniej {ok, total}."""
    out: dict[str, dict] = {}
    for s in repo.list_sessions(profile_id):
        if s["kind"] != "lesson":
            continue
        plan = repo.get_session_plan(profile_id, s["id"])
        items, done = plan.get("items") or [], plan.get("done") or []
        if plan.get("lesson") and items and len(done) >= len(items):
            out[plan["lesson"]] = {"ok": len(plan.get("ok") or []), "total": len(items)}
    return out


def declared_easy(repo, profile_id: int) -> set[str]:
    """Cele, które uczeń uznał za łatwe/znane (niepotwierdzone): pomijane przy wyborze, bez wpływu na mastery."""
    out = set()
    for s in repo.list_sessions(profile_id):
        plan = repo.get_session_plan(profile_id, s["id"]) if s["kind"] == "lesson" else {}
        if plan.get("declared_easy") and plan.get("lesson"):
            out.add(plan["lesson"])
    return out


def agv_checks(repo, profile_id: int) -> dict[str, dict]:
    """Ostatni zakończony wynik ćwiczenia potwierdzającego (AGV) per kategoria błędu: {outcome, at, skill_id}."""
    out: dict[str, dict] = {}
    for s in repo.list_sessions(profile_id):
        if s["kind"] != "lesson":
            continue
        a = (repo.get_session_plan(profile_id, s["id"]) or {}).get("agv") or {}
        if a.get("outcome") in ("confirmed", "not_confirmed", "inconclusive") and \
                a["at"] >= out.get(a["category"], {}).get("at", ""):
            out[a["category"]] = a
    return out


def _state(r: dict) -> SkillState:
    return SkillState(r["skill_id"], r["p_mastery"], r["status"], r["attempts"], r["mastered_at"],
                      r["verify_due_at"], r["verified_7d_at"], r["verified_30d_at"], r["relapses"])


def choose(repo, pack: C.Pack, profile_id: int, now: datetime, _use_easy: bool = True) -> Choice | None:
    allow = bool(repo.get_profile(profile_id)["allow_unreviewed_practice"])
    comp: dict[str, dict] = {}
    for r in repo.list_competence(profile_id):          # od najstarszego: ostatni pomiar wygrywa
        comp[r["area"]] = r
    inp = planner.PlanInput(
        minutes=30, now=now, seed=profile_id, pack=pack,
        states={r["skill_id"]: _state(r) for r in repo.list_skill_states(profile_id)},
        levels={a: r["theta"] for a, r in comp.items()},
        due_cards=repo.due_cards(profile_id, now.strftime("%Y-%m-%dT%H:%M:%SZ")),
        errors=repo.list_errors(profile_id), allow_unreviewed_practice=allow,
        provisional_areas={a for a, r in comp.items() if r["source"] != "diagnosis"})
    done = completed(repo, profile_id)
    easy = declared_easy(repo, profile_id) if _use_easy else set()

    def usable(sid: str) -> str | None:
        """None = pomiń; inaczej prefiks uzasadnienia powtórki ('' gdy to nie powtórka)."""
        if sid in easy:
            return None
        try:
            L.prepare(pack, sid, allow_unreviewed=allow)
        except L.LessonError:
            return None
        d = done.get(sid)
        if d is None:
            return ""
        return f"Powtórka: poprzednia lekcja {d['ok']}/{d['total']} — pomyłki do utrwalenia. " \
            if d["ok"] < d["total"] else None

    plan = planner.plan(inp)
    checks = agv_checks(repo, profile_id)
    for e in sorted(repo.list_errors(profile_id), key=lambda e: (-(e.get("severity_max") or 1), e["category"])):
        recurring = e.get("status") == "recurring" or (
            e.get("count", 0) >= 3 and e.get("status") not in ("resolved", "improving"))
        if not recurring:
            continue
        chk = checks.get(e["category"])
        if chk and chk["outcome"] != "confirmed" and (e.get("last_seen") or "") <= chk["at"]:
            continue        # ćwiczenie nie potwierdziło problemu, a od tego czasu brak nowej obserwacji: nie wymuszamy
        cat, parent = e["category"], e["category"].split(".")[0]
        rank = {sid: 0 if cat in pack.skills[sid].error_categories else 1 for sid in pack.skills
                if {cat, parent} & set(pack.skills[sid].error_categories)}
        for sid in sorted(rank, key=lambda x: (rank[x], x)):      # dokładna kategoria przed jej rodzicem
            if usable(sid) is not None:
                why = ("Powtarzający się błąd w rozmowach ({cat}), potwierdzony wcześniej w ćwiczeniu — utrwalimy to."
                       if chk and chk["outcome"] == "confirmed" else "Powtarzający się błąd w rozmowach ({cat}). To "
                       "sugestia modelu, niezweryfikowana — sprawdzimy to w zadaniach.")
                return Choice(sid, "error", why.format(cat=cat), True, category=cat)
    for t in plan["practice"]:
        pre = usable(t["skill_id"])
        if pre is None:
            continue
        sid, st = t["skill_id"], inp.states.get(t["skill_id"])
        if t["kind"] == "learning" and st and st.attempts < 3:
            why = (f"Umiejętność sprawdzona dotąd tylko {st.attempts}× (np. w dopasowaniu) — za mało, by cokolwiek "
                   "twierdzić; poćwiczymy ją.")
        elif t["kind"] == "learning":
            why = (f"Kontynuacja: umiejętność w trakcie nauki (szacunkowe p={st.p:.2f}, to nie jest potwierdzone "
                   "opanowanie).")
        elif t["kind"] == "new" and not comp:
            return Choice(sid, "starter", f"Pierwsza lekcja: {pack.skills[sid].cefr}, następna odblokowana "
                          f"umiejętność przy poziomie domyślnym. {NO_DIAGNOSIS}", True)
        elif t["kind"] == "new":
            why = f"Następna umiejętność odblokowana na Twoim poziomie ({pack.skills[sid].cefr})."
        else:
            why = f"Plan nauki: {t['reason']} (niezweryfikowane)."
        return Choice(sid, "plan", pre + why, t["provisional_level"] or not comp)
    for sid in [L.DEFAULT_SKILL, *sorted(pack.skills, key=lambda s: (pack.skills[s].cefr, s))]:
        if sid in pack.skills and usable(sid) == "":                # plan nic nie dał: najprostszy dostępny cel
            return Choice(sid, "starter", f"Wybór startowy: pierwszy cel z materiałami. {NO_DIAGNOSIS}", True)
    return choose(repo, pack, profile_id, now, _use_easy=False) if easy else None   # wszystko „łatwe”: wróć do nich
