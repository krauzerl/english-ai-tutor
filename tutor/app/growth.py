"""Rzeczywisty pomiar postępów (F7). Wyłącznie z zapisanych dowodów, bez LLM i bez jednego „% angielskiego”.

Zasady:
 * szacunek kompetencji liczy się z PIERWSZYCH, samodzielnych prób na danym zadaniu (hint 0) — powtórka tego
   samego zadania nie podnosi szacunku; próby po podpowiedzi są pokazane osobno;
 * trudność zadań jest uwzględniona: ten sam model bayesowski co diagnoza (`pedagogy.diagnosis`, b = poziom
   + trudność), więc 5/5 na A1 ≠ 5/5 na B2;
 * trend tylko przy wystarczającej próbie w OBU okresach (`MIN_TREND`), inaczej „za mało danych”;
 * mówienie/pisanie: sugestie błędów modelu na 100 słów w ocenionych wypowiedziach (oznaczone jako sugestie);
 * trwałość: wyniki powtórek FSRS i prób po ≥ 3 dniach od poprzedniej próby tej umiejętności;
 * czas w aplikacji, XP i odznaki NIE są dowodem.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

from tutor.pedagogy import content as C
from tutor.pedagogy import diagnosis as D

AREAS = ("grammar", "vocabulary", "reading", "listening", "speaking", "writing")
MIN_TREND = 8              # pierwszych prób w każdym z porównywanych okresów
MIN_POINT = 5              # pierwszych prób w tygodniu, by pokazać punkt na wykresie
MIN_WORDS = 60             # słów w ocenionych wypowiedziach na okres (mówienie/pisanie)
RETENTION_DAYS = 3


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _fb(a: dict) -> dict:
    return json.loads(a["feedback_json"]) if a["feedback_json"] else {}


def _attempts(repo, pid: int) -> list[dict]:
    return [dict(r) for r in repo.conn.execute(
        "SELECT * FROM attempt WHERE profile_id=? ORDER BY created_at, id", (pid,))]


def _estimate(rows: list[dict], pack: C.Pack) -> dict | None:
    """θ ± sd z pierwszych prób (z uwzględnieniem trudności). None = brak prób."""
    asked = []
    for a in rows:
        it = pack.items.get(a["item_id"] or "")
        if it is None:
            continue
        asked.append({"b": D.item_b(it, pack.rubric), "g": D.item_g(it), "correct": bool(a["correct"]), "w": 1.0})
    if not asked:
        return None
    s = D.stats(D.posterior(asked, pack.rubric), pack.rubric)
    return {"theta": round(s["mean"], 2), "sd": round(s["sd"], 2), "n": len(asked),
            "correct": sum(1 for x in asked if x["correct"])}


def _classify(atts: list[dict], pack: C.Pack) -> dict[str, list[dict]]:
    """Podział prób na rodzaje dowodu. Klucz zadania: pierwsza próba danego `item_id` w historii."""
    seen: set[str] = set()
    out = {"first": [], "after_hint": [], "repeat": [], "review": [], "unknown_item": []}
    for a in atts:
        it = pack.items.get(a["item_id"] or "")
        if it is None:
            out["unknown_item"].append(a)
            continue
        fb = _fb(a)
        if fb.get("review"):
            out["review"].append(a)
        if a["item_id"] in seen:
            out["repeat"].append(a)
            continue
        seen.add(a["item_id"])
        if fb.get("stt_uncertain"):
            continue
        (out["first"] if a["hint_level"] == 0 else out["after_hint"]).append(a)
    return out


def _area(a: dict, pack: C.Pack) -> str | None:
    it = pack.items.get(a["item_id"] or "")
    return it.area if it else None


def _speech(repo, pid: int, since: datetime | None, until: datetime | None) -> dict:
    """Sugestie błędów modelu na 100 słów w ocenionych wypowiedziach (mówienie = głos, pisanie = tekst)."""
    rows = repo.conn.execute(
        "SELECT t.id, t.text, t.input_mode, t.created_at FROM turn t JOIN turn_meta m ON m.turn_id=t.id "
        "WHERE t.profile_id=? AND t.role='user' AND m.eval_status='evaluated'", (pid,)).fetchall()
    obs = {}
    for o in repo.conn.execute(
            "SELECT o.turn_id, COUNT(*) FROM observation o WHERE o.profile_id=? AND o.kind='error' AND "
            "o.status='valid' AND o.confidence='h' AND NOT EXISTS (SELECT 1 FROM observation_review r WHERE "
            "r.observation_id=o.id AND r.verdict IN ('disputed','stt_error') AND r.id=(SELECT MAX(id) FROM "
            "observation_review WHERE observation_id=o.id)) GROUP BY o.turn_id", (pid,)):
        obs[o[0]] = o[1]
    out = {}
    for area, mode in (("speaking", "voice"), ("writing", "text")):
        words = errs = turns = 0
        for r in rows:
            t = _dt(r["created_at"])
            if r["input_mode"] != mode or (since and t < since) or (until and t >= until):
                continue
            words += len(r["text"].split())
            errs += obs.get(r["id"], 0)
            turns += 1
        out[area] = {"words": words, "turns": turns, "errors": errs,
                     "per_100": round(100 * errs / words, 1) if words >= MIN_WORDS else None}
    return out


def _retention(atts: list[dict], pack: C.Pack) -> dict:
    """Próby wykonane ≥ RETENTION_DAYS po poprzedniej próbie tej samej umiejętności (pamięć po przerwie).
    Liczy się tylko NOWE zadanie (pierwsza próba tego `item_id`): powtórzenie znanego zadania mierzy pamięć zadania,
    nie umiejętności; próby bez zadania (rozmowa) też nie są niezależnym dowodem trwałości."""
    last: dict[str, datetime] = {}
    seen: set[tuple[str, str]] = set()
    delayed, reviews = [], []
    for a in atts:
        t = _dt(a["created_at"])
        prev = last.get(a["skill_id"])
        key = (a["skill_id"], a["item_id"])
        new_item = bool(a["item_id"]) and key not in seen
        if prev and (t - prev).days >= RETENTION_DAYS and a["hint_level"] == 0 and not _fb(a).get("stt_uncertain") \
                and new_item:
            delayed.append({"days": (t - prev).days, "correct": bool(a["correct"]), "new_item": True})
        if _fb(a).get("review"):
            reviews.append(bool(a["correct"]))
        if a["item_id"]:
            seen.add(key)
        last[a["skill_id"]] = t
    week = [d for d in delayed if d["days"] >= 7]
    two = [d for d in delayed if d["days"] >= 14]
    return {"after_3_days": {"correct": sum(d["correct"] for d in delayed), "n": len(delayed)},
            "after_7_days": {"correct": sum(d["correct"] for d in week), "n": len(week)},
            "after_14_days": {"correct": sum(d["correct"] for d in two), "n": len(two)},
            "reviews": {"correct": sum(reviews), "n": len(reviews)},
            "enough": len(delayed) >= MIN_POINT}


def _compare(first: dict | None, last: dict | None) -> dict:
    if not first or not last or first["n"] < MIN_TREND or last["n"] < MIN_TREND:
        return {"status": "insufficient", "first": first, "last": last}
    diff = round(last["theta"] - first["theta"], 2)
    noise = round((first["sd"] ** 2 + last["sd"] ** 2) ** 0.5, 2)
    direction = "up" if diff > noise else "down" if diff < -noise else "flat"
    return {"status": direction, "diff": diff, "noise": noise, "first": first, "last": last}


def build(repo, pack: C.Pack, pid: int, now: datetime, window_days: int = 14) -> dict:
    atts = _attempts(repo, pid)
    cls = _classify(atts, pack)
    t0 = _dt(atts[0]["created_at"]) if atts else now
    first_end = t0 + timedelta(days=window_days)
    last_start = now - timedelta(days=window_days)
    areas = {}
    for area in ("grammar", "vocabulary", "reading", "listening"):
        firsts = [a for a in cls["first"] if _area(a, pack) == area]
        hints = [a for a in cls["after_hint"] if _area(a, pack) == area]
        early = [a for a in firsts if _dt(a["created_at"]) < first_end]
        late = [a for a in firsts if _dt(a["created_at"]) >= max(last_start, first_end)]
        weeks: dict[str, list[dict]] = {}
        for a in firsts:
            d = _dt(a["created_at"])
            weeks.setdefault((d - timedelta(days=d.weekday())).date().isoformat(), []).append(a)
        points = [{"week": w, **e} for w, rows in sorted(weeks.items())
                  if len(rows) >= MIN_POINT and (e := _estimate(rows, pack))]
        areas[area] = {"area": area, "estimate": _estimate(firsts, pack), "independent": len(firsts),
                       "after_hint": {"n": len(hints), "correct": sum(a["correct"] for a in hints)},
                       "repeats_excluded": sum(1 for a in cls["repeat"] if _area(a, pack) == area),
                       "timeline": points, "compare": _compare(_estimate(early, pack), _estimate(late, pack))}
    sp_all = _speech(repo, pid, None, None)
    sp_first = _speech(repo, pid, None, first_end)
    sp_last = _speech(repo, pid, max(last_start, first_end), None)
    for area in ("speaking", "writing"):
        a, b = sp_first[area], sp_last[area]
        if a["per_100"] is None or b["per_100"] is None:
            cmp = {"status": "insufficient"}
        else:
            d = round(b["per_100"] - a["per_100"], 1)
            cmp = {"status": "fewer_errors" if d < -1 else "more_errors" if d > 1 else "flat", "diff": d}
        areas[area] = {"area": area, "suggestions": sp_all[area], "first": a, "last": b, "compare": cmp,
                       "note": "sugestie błędów modelu (nie potwierdzone), na 100 słów"}
    errors = [dict(e) for e in repo.list_errors(pid)]
    recurring = [e for e in errors if (e.get("count") or 0) >= 3 and not e.get("resolved_at")]
    resolved = [e for e in errors if e.get("resolved_at")]
    return {"areas": areas, "retention": _retention(atts, pack),
            "evidence": {"first_attempts": len(cls["first"]), "after_hint": len(cls["after_hint"]),
                         "repeats_excluded": len(cls["repeat"]), "reviews": len(cls["review"])},
            "errors": {"recurring": len(recurring), "resolved": len(resolved),
                       "top": [{"category": e["category"], "count": e["count"]} for e in
                               sorted(recurring, key=lambda e: -e["count"])[:5]]},
            "windows": {"days": window_days, "first_until": first_end.date().isoformat(),
                        "last_from": max(last_start, first_end).date().isoformat(),
                        "overlap": last_start < first_end},
            "rules": {"min_trend": MIN_TREND, "min_point": MIN_POINT, "min_words": MIN_WORDS},
            "not_evidence": ["czas w aplikacji", "XP i odznaki", "sama swobodna rozmowa bez oceny",
                             "powtarzanie tego samego zadania"]}
