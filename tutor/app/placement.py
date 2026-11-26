"""Wstępne dopasowanie poziomu (F6): istniejący silnik `pedagogy.diagnosis` w trybie `provisional` (materiał
niezweryfikowany przez człowieka) + istniejąca walidacja odpowiedzi z lekcji (`lesson.judge`, STT).

Wynik to profil kompetencji ze statusem wiarygodności, NIE diagnoza CEFR i nie mastery: zapis w `competence`
(source=placement_provisional) oraz próby `source=diagnosis` z flagą `no_mastery`.
Rozróżniamy: poprawna / błąd językowy /
brak odpowiedzi („nie wiem”) / niezweryfikowane (STT). Tylko pierwsze trzy wchodzą do wyniku; niepewne STT nigdy.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from tutor.app import ingest
from tutor.app import lesson as L
from tutor.app import lesson_voice as V
from tutor.pedagogy import content as C
from tutor.pedagogy import diagnosis as D

AREAS = ("grammar", "vocabulary")
MIN_ANSWERED = 3        # mniej odpowiedzi = za mało danych, nic nie zapisujemy jako wynik


@dataclass
class Outcome:
    area: str
    saved: bool
    counts: dict = field(default_factory=dict)       # correct / wrong / no_answer / unverified
    result: dict | None = None
    stop: str | None = None


@dataclass
class Report:
    outcomes: list[Outcome] = field(default_factory=list)
    quit: bool = False
    ended_early: bool = False                         # uczeń chciał przejść dalej


def _items(pack: C.Pack, area: str, allow: bool) -> list[C.Item]:
    return [i for i in D.available_items(pack, area, "provisional")
            if i.type not in C.OPEN_TYPES and i.answers and i.type not in ("listening_mc", "dictation", "reading_mc")
            and C.usable(i, "placement", allow)]


def _skill(item: C.Item) -> str:
    return item.skill_ids[0]


def _plan(repo, pid, sid) -> dict:
    return repo.get_session_plan(pid, sid) or {}


def run(repo, pack: C.Pack, pid: int, sid: int, ask: Callable[[C.Item, int], L.Answer | None],
        say: Callable[[str], None], *, now: datetime, speak: Callable[[str], None] | None = None,
        areas: tuple[str, ...] = AREAS, allow_unreviewed: bool = True, mode: str = "text") -> Report:
    speak = speak or (lambda _t: None)
    rb = pack.rubric
    rep = Report()
    plan = _plan(repo, pid, sid)
    st = plan.get("placement") or {"areas": {}, "counts": {}, "skipped": [], "finished": []}
    for area in areas:
        if area in st["finished"]:
            continue
        pool = D.fresh_pool(_items(pack, area, allow_unreviewed), repo.practiced_items(pid), rb.diagnosis["min_items"])
        if len(pool) < rb.diagnosis["min_items"]:
            continue
        state = st["areas"].get(area) or D.start(pack, area, "provisional", pid)
        cnt = st["counts"].get(area) or {"correct": 0, "wrong": 0, "no_answer": 0, "unverified": 0}
        say(f"\n— Wstępne dopasowanie: {area} (to nie jest diagnoza CEFR; niepewna mowa nie obniża wyniku) —")
        speak(f"Let's check your {area}. Answer in whole sentences if you can.")
        while True:
            reason = D.stop_reason(state, rb)
            left = [i for i in pool if i.id not in st["skipped"]]
            if reason or (it := D.next_item(state, left, rb)) is None:
                st["finished"].append(area)
                break
            n = len(state["asked"]) + 1
            say(L._show(it, n - 1, rb.diagnosis["max_items"]))
            speak(V.task(it, n - 1, rb.diagnosis["max_items"]))
            verdict, a, reasks = None, None, 0
            while True:
                a = ask(it, n)
                if a is None:
                    st["areas"][area], st["counts"][area] = state, cnt
                    repo.set_session_plan(pid, sid, {**plan, "placement": st})
                    rep.quit = True
                    return rep
                if a.mode == "voice":
                    say(L._heard(a))
                verdict = L.judge(pack, _skill(it), it, a)
                if verdict == "help":                    # powtórz zadanie, nie liczymy tego jako próby
                    say(L._show(it, n - 1, rb.diagnosis["max_items"]))
                    speak(V.task(it, n - 1, rb.diagnosis["max_items"]))
                    continue
                if verdict == "unclear":
                    reasks += 1
                    if reasks <= L.MAX_REASK:
                        say(f"Nie jestem pewien, czy dobrze usłyszałem („{a.text}”). Powiedz jeszcze raz albo wpisz.")
                        speak(V.reask(a.text))
                        continue
                break
            if verdict in ("skip", "finish"):
                say("Dobrze, kończymy dopasowanie. Wynik będzie wstępny albo niepełny.")
                speak(V.stop_exercises())
                st["areas"][area], st["counts"][area] = state, cnt
                rep.ended_early = True
                break
            if verdict == "unclear":                     # STT: pominięte, nie wchodzi do wyniku ani do prób
                cnt["unverified"] += 1
                st["skipped"].append(it.id)
                continue
            correct = verdict == "correct"
            cnt["correct" if correct else "no_answer" if verdict == "unknown" else "wrong"] += 1
            state = D.record(state, it, correct, rb)
            ingest.apply_item_attempt(repo, pack, pid, sid, it.id, _skill(it), correct, source="diagnosis",
                                      dedupe_key=f"placement:{sid}:{it.id}", now=now, response=a.text,
                                      hint_level=0, n_options=len(it.options) if it.options else None,
                                      allow_mastery=False)
            st["areas"][area], st["counts"][area] = state, cnt
            repo.set_session_plan(pid, sid, {**plan, "placement": st})      # zapis po każdej odpowiedzi (wznowienie)
        answered = len(state["asked"])
        out = Outcome(area, False, cnt, stop=D.stop_reason(state, rb))
        if answered >= MIN_ANSWERED:
            r = D.result(state, rb)
            repo.add_competence(pid, area, r.level, r.theta, r.se, r.n_items, r.source,
                                {"label": r.label, "notice": r.notice, "counts": cnt, "stop": out.stop,
                                 "input": mode, "range": [r.lo, r.hi], "ceiling": r.ceiling, "floor": r.floor})
            out.saved, out.result = True, r.as_dict()
            say(f"{area}: {r.label}. {r.notice}")
        else:
            say(f"{area}: za mało pewnych odpowiedzi ({answered}) — nic nie zapisano jako wynik. "
                f"Niezweryfikowane (rozpoznanie mowy): {cnt['unverified']}.")
        rep.outcomes.append(out)
        st["areas"][area], st["counts"][area] = state, cnt
        repo.set_session_plan(pid, sid, {**plan, "placement": st})
        if rep.ended_early:
            break
    return rep


def needs_placement(repo, pid: int) -> bool:
    """Brak jakiegokolwiek pomiaru i historii prób: uczeń „bez historii”."""
    return not repo.list_competence(pid) and not repo.list_skill_states(pid)
