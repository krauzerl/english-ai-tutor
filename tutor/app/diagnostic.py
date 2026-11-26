"""Pełna diagnoza kompetencji (F7, „Comprehensive Assessment”). Dobrowolna; nie blokuje rozmów ani lekcji.

Sześć kompetencji. Gramatyka, słownictwo, czytanie i słuchanie: istniejący silnik `pedagogy.diagnosis` (siatka
bayesowska, zadanie o największej informacji przy aktualnym szacunku, stop po osiągnięciu precyzji) w trybie
`provisional` — materiał AI (`ai_checked`), więc wynik to WSTĘPNY szacunek z przedziałem, nie poziom CEFR.
Adaptacja między obszarami: prior kolejnego obszaru = średnia wyników już sprawdzonych obszarów (szerszy niż
pewność), więc zaczynamy od zadań na prawdopodobnym poziomie, a nie zawsze od A2.
Pisanie i mówienie: zadania otwarte; wynik to tylko DOWODY (liczba słów, sugestie błędów modelu na 100 słów),
bez poziomu — ocena produkcji wymaga zwalidowanej rubryki (obszary jawnie oznaczone jako „niegotowe do oceny”).
Stan w `session.plan_json["assessment"]` (kind `assessment`): przerwanie i wznowienie bez utraty odpowiedzi.
Próby zapisujemy z `source=diagnosis` i `no_mastery` (diagnoza nigdy nie nadaje mastery).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import yaml

from tutor.app import ingest
from tutor.app import lesson as L
from tutor.app import lesson_voice as V
from tutor.pedagogy import content as C
from tutor.pedagogy import diagnosis as D

AREAS = ("grammar", "vocabulary", "reading", "listening", "writing", "speaking")
CLOSED = ("grammar", "vocabulary", "reading", "listening")
OPEN = ("writing", "speaking")
QUICK = ("grammar", "vocabulary")
SOURCE = "assessment_provisional"
SOURCES = ("placement_provisional", SOURCE, "diagnosis")
MIN_ANSWERED = 3
PRIOR_SD = 2.0                      # audyt F7: 1.2 ciągnął obszar A1 o ~0,8 θ ku C1 innych obszarów
NAMES_PL = {"grammar": "gramatyka", "vocabulary": "słownictwo", "reading": "czytanie", "listening": "słuchanie",
            "writing": "pisanie", "speaking": "mówienie"}
NOT_READY_PL = ("Ocena produkcji (pisanie, mówienie) nie ma jeszcze zwalidowanej rubryki: pokazujemy dowody "
                "(objętość, sugestie błędów), bez poziomu.")


@dataclass
class AreaOutcome:
    area: str
    status: str                       # estimated | insufficient | not_tested | evidence | ended_early
    counts: dict = field(default_factory=dict)
    result: dict | None = None
    reason: str | None = None


@dataclass
class Report:
    outcomes: list[AreaOutcome] = field(default_factory=list)
    quit: bool = False


def open_tasks() -> list[dict]:
    p = Path(__file__).resolve().parents[1] / "content" / "assessment_open_en.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8"))["tasks"]


def items_for(pack: C.Pack, area: str, allow: bool = True) -> list[C.Item]:
    """Zadania zamknięte puli diagnosis ze statusem dopuszczonym do wstępnego dopasowania (draft nigdy)."""
    out = []
    for i in D.available_items(pack, area, "provisional"):
        if i.type in C.OPEN_TYPES or not i.answers or not C.usable(i, "placement", allow):
            continue
        if i.type == "dictation" or (i.type == "listening_mc" and not i.audio_text):
            continue
        out.append(i)
    return out


def coverage(pack: C.Pack, allow: bool = True) -> dict:
    """Ile zadań na poziom ma każdy obszar — GUI pokazuje, gdzie bank jest cienki."""
    out = {}
    for a in CLOSED:
        its = items_for(pack, a, allow)
        out[a] = {lv: sum(1 for i in its if i.cefr == lv) for lv in ("A1", "A2", "B1", "B2", "C1")}
    for a in OPEN:
        out[a] = {lv: sum(1 for t in open_tasks() if t["area"] == a and t["cefr"] == lv)
                  for lv in ("A1", "A2", "B1", "B2", "C1")}
    return out


def _prior(st: dict) -> list[float] | None:
    th = [r["theta"] for a, r in st.get("results", {}).items() if a in CLOSED and r]
    return [sum(th) / len(th), PRIOR_SD] if th else None


def _task_level(st: dict) -> str:
    th = [r["theta"] for r in st.get("results", {}).values() if r]
    if not th:
        return "A2"
    lv = ("A1", "A2", "B1", "B2", "C1")
    return lv[max(0, min(4, round(sum(th) / len(th)) - 1))]


def _show_item(it: C.Item, n: int, total: int, area: str) -> str:
    head = f"\n[{NAMES_PL[area]}] Zadanie {n}/{total}"
    if it.type == "listening_mc":
        opts = "".join(f"\n  {k}. {o}" for k, o in enumerate(it.options or [], 1))
        return f"{head}: (posłuchaj nagrania) {it.prompt}{opts}"
    if it.stimulus:
        return f"{head}:\n„{it.stimulus}”\n{L._show(it, n - 1, total).split(': ', 1)[-1]}"
    return head + ": " + L._show(it, n - 1, total).split(": ", 1)[-1]


def run(repo, pack: C.Pack, pid: int, sid: int, ask: Callable[[C.Item | dict, int], L.Answer | None],
        say: Callable[[str], None], *, now: datetime, speak: Callable[[str], None] | None = None,
        areas: tuple[str, ...] = AREAS, allow_unreviewed: bool = True, mode: str = "text", audio: bool = True,
        evaluate: Callable[[str, str], dict | None] | None = None) -> Report:
    """`audio`: czy działa TTS (bez niego słuchanie nie jest sprawdzane); `mode`: voice = jest mikrofon
    (bez niego mówienie nie jest sprawdzane); `evaluate(text, mode)` = sugestie błędów modelu dla zadań otwartych."""
    speak = speak or (lambda _t: None)
    rb = pack.rubric
    rep = Report()
    plan = repo.get_session_plan(pid, sid) or {}
    st = plan.get("assessment") or {"areas": list(areas), "states": {}, "counts": {}, "skipped": [],
                                    "finished": [], "results": {}, "open": {}}
    areas = tuple(st["areas"])

    def save() -> None:
        repo.set_session_plan(pid, sid, {**(repo.get_session_plan(pid, sid) or {}), "assessment": st})

    save()
    for area in areas:
        if area in st["finished"]:
            continue
        if area == "listening" and not audio:
            st["finished"].append(area)
            rep.outcomes.append(AreaOutcome(area, "not_tested", reason="wymaga dźwięku (tryb tekstowy)"))
            st["results"][area] = None
            save()
            continue
        if area in OPEN:
            r = _open_area(st, area, ask, say, speak, mode, evaluate, save)
            if r is None:
                rep.quit = True
                return rep
            rep.outcomes.append(r)
            continue
        pool = D.fresh_pool(items_for(pack, area, allow_unreviewed), repo.practiced_items(pid),
                            rb.diagnosis["min_items"])
        if len(pool) < rb.diagnosis["min_items"]:
            st["finished"].append(area)
            rep.outcomes.append(AreaOutcome(area, "not_tested", reason="za mało zadań w banku"))
            save()
            continue
        state = st["states"].get(area)
        if state is None:
            state = {**D.start(pack, area, "provisional", pid), "prior": _prior(st)}
        cnt = st["counts"].get(area) or {"correct": 0, "wrong": 0, "no_answer": 0, "unverified": 0}
        say(f"\n— {NAMES_PL[area].capitalize()} (szacunek wstępny, nie poziom CEFR) —")
        speak(f"Now: {area}.")
        ended = False
        while True:
            reason = D.stop_reason(state, rb)
            left = [i for i in pool if i.id not in st["skipped"]]
            if reason or (it := D.next_item(state, left, rb)) is None:
                break
            n = len(state["asked"]) + 1
            say(_show_item(it, n, rb.diagnosis["max_items"], area))
            if it.type == "listening_mc":
                speak(V.PAUSE.join(["Listen.", it.audio_text, "Once more.", it.audio_text]))
            else:
                speak(V.task(it, n - 1, rb.diagnosis["max_items"]))
            verdict, a, reasks = None, None, 0
            while True:
                a = ask(it, n)
                if a is None:
                    st["states"][area], st["counts"][area] = state, cnt
                    save()
                    rep.quit = True
                    return rep
                if a.mode == "voice":
                    say(L._heard(a))
                verdict = L.judge(pack, it.skill_ids[0], it, a)
                if verdict == "help":
                    say(_show_item(it, n, rb.diagnosis["max_items"], area))
                    if it.type == "listening_mc":
                        speak(it.audio_text)
                    continue
                if verdict == "unclear":
                    reasks += 1
                    if reasks <= L.MAX_REASK:
                        say(f"Nie jestem pewien, czy dobrze usłyszałem („{a.text}”). Powiedz jeszcze raz albo wpisz.")
                        continue
                break
            if verdict == "finish":
                st["states"][area], st["counts"][area] = state, cnt
                save()
                rep.quit = True
                return rep
            if verdict == "skip":                       # „dalej”: kończymy ten obszar, następny obszar
                ended = True
                break
            if verdict == "unclear":                    # niepewne STT nigdy nie obniża wyniku
                cnt["unverified"] += 1
                st["skipped"].append(it.id)
                continue
            correct = verdict == "correct"
            cnt["correct" if correct else "no_answer" if verdict == "unknown" else "wrong"] += 1
            state = D.record(state, it, correct, rb)
            ingest.apply_item_attempt(repo, pack, pid, sid, it.id, it.skill_ids[0], correct, source="diagnosis",
                                      dedupe_key=f"assessment:{sid}:{it.id}", now=now, response=a.text,
                                      hint_level=0, n_options=len(it.options) if it.options else None,
                                      allow_mastery=False)
            st["states"][area], st["counts"][area] = state, cnt
            save()
        st["finished"].append(area)
        out = AreaOutcome(area, "insufficient", cnt, reason=D.stop_reason(state, rb))
        if len(state["asked"]) >= MIN_ANSWERED:
            r = D.result(state, rb)
            repo.add_competence(pid, area, r.level, r.theta, r.se, r.n_items, SOURCE,
                                {"label": r.label, "notice": r.notice, "counts": cnt, "stop": out.reason,
                                 "input": mode, "range": [r.lo, r.hi], "ceiling": r.ceiling, "floor": r.floor,
                                 "prior": state.get("prior"), "session": sid})
            out.status, out.result = "estimated", r.as_dict()
            st["results"][area] = {"theta": r.theta, "se": r.se, "label": r.label}
            say(f"{NAMES_PL[area]}: {r.label} (zadań: {r.n_items}).")
        else:
            st["results"][area] = None
            say(f"{NAMES_PL[area]}: za mało pewnych odpowiedzi ({len(state['asked'])}) — bez wyniku.")
        if ended:
            out.status = "ended_early" if out.status != "estimated" else out.status
        rep.outcomes.append(out)
        save()
    st["done"] = True
    save()
    return rep


def _open_area(st, area, ask, say, speak, mode, evaluate, save) -> AreaOutcome | None:
    if area == "speaking" and mode != "voice":
        st["finished"].append(area)
        st["open"][area] = {"status": "not_tested", "reason": "wymaga mikrofonu"}
        save()
        return AreaOutcome(area, "not_tested", reason="wymaga mikrofonu (tryb tekstowy)")
    lv = _task_level(st)
    task = next((t for t in open_tasks() if t["area"] == area and t["cefr"] == lv), None)
    if task is None:
        st["finished"].append(area)
        save()
        return AreaOutcome(area, "not_tested", reason="brak zadania na tym poziomie")
    say(f"\n— {NAMES_PL[area].capitalize()} (zadanie otwarte, {lv}; zbieramy dowody, bez poziomu) —\n"
        f"{task['prompt']}\n({task['prompt_pl']} Co najmniej {task['min_words']} słów.)")
    speak(task["prompt"])
    a = ask({"id": task["id"], "open": True, "area": area}, 1)
    if a is None:
        return None
    words = len(a.text.split())
    ev = {"task": task["id"], "cefr_task": lv, "words": words, "enough": words >= task["min_words"],
          "input": a.mode, "status": "evidence"}
    if evaluate and words:
        try:
            ev.update(evaluate(a.text, a.mode) or {})
        except Exception:  # noqa: BLE001 - brak modelu = dowód bez sugestii błędów
            ev["errors_note"] = "model oceny niedostępny"
    st["open"][area] = ev
    st["finished"].append(area)
    save()
    say(f"{NAMES_PL[area]}: zapisano dowód ({words} słów"
        + (f", sugestie błędów modelu: {ev['errors_per_100']} na 100 słów" if "errors_per_100" in ev else "")
        + "). " + NOT_READY_PL)
    return AreaOutcome(area, "evidence", result=ev)


# --- profil kompetencji (wynik dla ucznia) ---
def profile(repo, pack: C.Pack, pid: int) -> dict:
    """Profil sześciu kompetencji: ostatni wynik, historia, liczba dowodów, niepewność, obszary nieprzetestowane,
    mocne/słabe strony i rekomendacje. Bez „oficjalnego CEFR” i bez jednego wskaźnika ogólnego."""
    rows = [r for r in repo.list_competence(pid) if r["source"] in SOURCES]
    import json as _j
    areas = {}
    for a in AREAS:
        hist = [{"date": r["measured_at"][:10], "level": r["cefr"], "theta": round(r["theta"], 2),
                 "se": round(r["se"], 2), "n_items": r["n_items"], "source": r["source"],
                 "label": (_j.loads(r["rationale"]) if r["rationale"] else {}).get("label", r["cefr"]),
                 "range": (_j.loads(r["rationale"]) if r["rationale"] else {}).get("range")}
                for r in rows if r["area"] == a]
        areas[a] = {"area": a, "name_pl": NAMES_PL[a], "history": hist, "latest": hist[-1] if hist else None,
                    "tested": bool(hist), "evidence": sum(h["n_items"] for h in hist),
                    "kind": "closed" if a in CLOSED else "open"}
    for s in repo.list_sessions(pid):                            # dowody z zadań otwartych
        if s["kind"] != "assessment":
            continue
        for a, ev in ((repo.get_session_plan(pid, s["id"]) or {}).get("assessment", {}).get("open") or {}).items():
            if ev.get("status") == "evidence":
                areas[a].setdefault("open_evidence", []).append({**ev, "date": s["started_at"][:10]})
                areas[a]["tested"] = True
    est = {a: v["latest"] for a, v in areas.items() if v["latest"]}
    strengths, weaknesses = [], []
    if len(est) >= 2:
        for a, r in est.items():
            others = [x["theta"] for b, x in est.items() if b != a]
            m = sum(others) / len(others)
            lo, hi = (r["range"] or [r["theta"] - r["se"], r["theta"] + r["se"]])
            if lo > m:
                strengths.append(a)
            elif hi < m:
                weaknesses.append(a)
    untested = [a for a, v in areas.items() if not v["tested"]]
    recs = []
    if est:
        low = min(est, key=lambda a: est[a]["theta"])
        lv = est[low]["level"]
        skills = [s for s in pack.skills.values() if s.area == low and s.cefr == lv][:3]
        recs.append({"kind": "practice_area", "area": low,
                     "text_pl": f"Najniższy szacunek: {NAMES_PL[low]} ({est[low]['label']}). "
                                "Ćwicz cele z tego obszaru.",
                     "skills": [s.id for s in skills]})
    for a in untested:
        recs.append({"kind": "test_area", "area": a, "text_pl": f"Nie sprawdzono: {NAMES_PL[a]}."})
    wide = [a for a, r in est.items() if r["se"] > 0.6 or r["n_items"] < 6]
    if wide:
        recs.append({"kind": "retest", "areas": wide,
                     "text_pl": "Szeroki przedział niepewności: " + ", ".join(NAMES_PL[a] for a in wide)
                     + " — powtórz diagnozę tych obszarów, by go zawęzić."})
    return {"areas": [areas[a] for a in AREAS], "strengths": strengths, "weaknesses": weaknesses,
            "untested": untested, "recommendations": recs, "not_ready": list(OPEN),
            "notice": ("Szacunki wstępne z materiału niezweryfikowanego przez człowieka — to nie jest oficjalny "
                       "poziom CEFR. Przedział pokazuje niepewność. " + NOT_READY_PL)}

