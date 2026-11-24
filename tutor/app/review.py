"""Powtórki na podstawie harmonogramu FSRS (F6): karty tworzy i przesuwa `ingest._srs` przy każdej próbie.

* karta `construction`/`skill_check` ref=skill_id; zaległa ⇒ 1–2 NOWE (nieużyte wcześniej) zadania z tej umiejętności
  (transfer, nie odtwarzanie zapamiętanego przykładu); gdy wszystkie były widziane — najdawniej użyte;
* wynik to próba ćwiczeniowa (`no_mastery`): powtórka mierzy utrwalenie, NIE nadaje opanowania;
* ochrona: ≤ MAX_SKILLS umiejętności na sesję i ≤ DAILY_CAP prób powtórek dziennie; „później” przekłada kartę o 1 dzień;
* idempotentne: `dedupe_key=review:SID:ITEM`, postęp w `session.plan_json` (wznowienie bez podwójnego naliczania).
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from tutor.app import ingest
from tutor.app import lesson as L
from tutor.app import lesson_voice as V
from tutor.pedagogy import content as C

MAX_SKILLS = 6
ITEMS_PER_SKILL = 2
DAILY_CAP = 20


@dataclass
class Result:
    asked: int = 0
    correct: int = 0
    postponed: list[str] = field(default_factory=list)
    quit: bool = False
    nothing_due: bool = False
    capped: bool = False


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def done_today(repo, pid: int, day: str) -> int:
    return repo.conn.execute("SELECT COUNT(*) FROM attempt WHERE profile_id=? AND day=? AND "
                             "json_extract(feedback_json,'$.review')=1", (pid, day)).fetchone()[0]


def due_skills(repo, pack: C.Pack, pid: int, now: datetime, allow: bool = True) -> list[str]:
    """Zaległe umiejętności z materiałem; najpierw te z nawracającymi błędami, potem wg terminu."""
    recurring = {e["skill_id"] for e in repo.list_errors(pid) if e.get("skill_id") and
                 (e.get("status") == "recurring" or (e.get("count") or 0) >= 3)}
    out = []
    for c in repo.due_cards(pid, _iso(now)):
        sid = c["ref_id"]
        if c["card_type"] not in ("construction", "skill_check") or sid in out or sid not in pack.skills:
            continue
        try:
            L.prepare(pack, sid, allow_unreviewed=allow)
        except L.LessonError:
            continue
        out.append(sid)
    return sorted(out, key=lambda s: (s not in recurring, out.index(s)))


def pick_items(repo, pack: C.Pack, pid: int, skill_id: str, n: int = ITEMS_PER_SKILL,
               allow: bool = True) -> list[C.Item]:
    _, pool = L.prepare(pack, skill_id, n=99, allow_unreviewed=allow)
    last = {}
    for h in repo.attempt_history(pid, skill_id):
        if h["item_id"]:
            last[h["item_id"]] = h["created_at"]
    # nowe zadania najpierw, potem najdawniej użyte
    pool.sort(key=lambda i: (i.id in last, last.get(i.id, ""), i.difficulty, i.id))
    return pool[:n]


def postpone(repo, pid: int, skill_id: str, now: datetime, days: int = 1) -> None:
    card = repo.get_card(pid, "construction", skill_id) or repo.get_card(pid, "skill_check", skill_id)
    if card:
        repo.put_card(pid, card["card_type"], skill_id, card["fsrs_json"], _iso(now + timedelta(days=days)))


def run(repo, pack: C.Pack, pid: int, sid: int, ask: Callable[[C.Item, int], L.Answer | None],
        say: Callable[[str], None], *, now: datetime, speak: Callable[[str], None] | None = None,
        allow: bool = True, only: list[str] | None = None) -> Result:
    """`only` = ćwiczenia ukierunkowane (dziennik słabych stron): podane umiejętności zamiast zaległych kart."""
    speak = speak or (lambda _t: None)
    res = Result()
    plan = repo.get_session_plan(pid, sid) or {}
    st = plan.get("review") or {"done": [], "ok": [], "postponed": []}
    day = now.strftime("%Y-%m-%d")
    budget = DAILY_CAP - done_today(repo, pid, day)
    planned = plan.get("review_skills") or only or due_skills(repo, pack, pid, now, allow)
    skills = [s for s in planned if s not in st["postponed"]]
    if not skills:
        res.nothing_due = True
        return res
    skills = skills[:MAX_SKILLS]
    repo.set_session_plan(pid, sid, {**plan, "review_skills": skills, "review": st})
    say(f"Powtórki: {len(skills)} umiejętności do utrwalenia. To sprawdza utrwalenie — nie nadaje opanowania.")
    speak("Time for a short review. These are new examples of things you have practised.")
    chosen = plan.get("review_items") or {}
    for skill in skills:
        sk = pack.skills[skill]
        if skill not in chosen:                       # wybór zapisany w sesji: wznowienie bierze te same zadania
            chosen[skill] = [i.id for i in pick_items(repo, pack, pid, skill, allow=allow)]
            repo.set_session_plan(pid, sid, {**repo.get_session_plan(pid, sid), "review_items": chosen})
        for idx, it in enumerate(pack.items[x] for x in chosen[skill]):
            if it.id in st["done"]:
                continue
            if budget <= 0:
                res.capped = True
                say("Dzienny limit powtórek osiągnięty — reszta poczeka do jutra.")
                speak("That's enough reviews for today.")
                return res
            say(f"\n[{skill}]" + L._show(it, idx, ITEMS_PER_SKILL))
            speak(V.task(it, idx, ITEMS_PER_SKILL))
            reasks = 0
            while True:
                a = ask(it, idx)
                if a is None:
                    res.quit = True
                    return res
                if a.mode == "voice":
                    say(L._heard(a))
                v = L.judge(pack, skill, it, a)
                if v == "help":
                    ex = L._examples(pack, sk)
                    say("Przypomnienie: " + "; ".join(ex))
                    speak(V.help_(ex))
                    continue
                if v == "unclear" and reasks < L.MAX_REASK:
                    reasks += 1
                    say(f"Nie jestem pewien, czy dobrze usłyszałem („{a.text}”). Powiedz jeszcze raz albo wpisz.")
                    speak(V.reask(a.text))
                    continue
                break
            if v in ("skip", "unclear"):             # „później” albo niepewne STT: bez próby, karta przesunięta o dzień
                postpone(repo, pid, skill, now)
                st["postponed"].append(skill)
                res.postponed.append(skill)
                say("Przekładam tę powtórkę na jutro (bez wpływu na ocenę).")
                speak("Okay, we'll do this one tomorrow.")
                break
            ok = v == "correct"
            ingest.apply_item_attempt(repo, pack, pid, sid, it.id, skill, ok, source="practice",
                                      dedupe_key=f"review:{sid}:{it.id}", now=now, response=a.text,
                                      hint_level=0 if ok else 4, allow_mastery=False, extra={"review": 1},
                                      n_options=len(it.options) if it.options else None)
            st["done"].append(it.id)
            res.asked += 1
            budget -= 1
            if ok:
                st["ok"].append(it.id)
                res.correct += 1
                say("✓ Dobrze.")
                speak(V.correct(0))
            else:
                say(f"Poprawna odpowiedź: {it.answers[0]}" + (f"\n{it.explanation_pl}" if it.explanation_pl else ""))
                speak(V.reveal(it))
            repo.set_session_plan(pid, sid, {**repo.get_session_plan(pid, sid), "review": st})
    post = f" Przełożone: {len(res.postponed)}." if res.postponed else ""
    say(f"\nPowtórki: {res.correct}/{res.asked} poprawnie.{post}")
    return res


def summary_json(res: Result) -> str:
    return json.dumps({"asked": res.asked, "correct": res.correct, "postponed": res.postponed})
