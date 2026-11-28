"""Dziennik słabych stron: z `error_log`, obserwacji, prób i kart FSRS — bez nowych źródeł prawdy.

Każdy wpis ma JAWNY status wiarygodności:
 * potwierdzony ćwiczeniami — niezależne zadanie (lekcja/powtórka/dopasowanie) z błędną odpowiedzią
   na umiejętność tej kategorii;
 * sugestia modelu — błąd z rozmowy (pewność wysoka); brama jakości jest zamknięta, więc to nie jest dowód;
 * niepewna transkrypcja STT — tylko podejrzenia z mowy (nigdy błąd ucznia);
 * za mało danych — pojedyncze/niepewne obserwacje."""
from __future__ import annotations

from datetime import datetime, timedelta

from tutor.pedagogy import content as C
from tutor.pedagogy.mastery import MASTERED

MIN_TURNS_FOR_TREND = 5


def _iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%fZ")


def _skills_for(pack: C.Pack, category: str, allow: bool = True) -> list[str]:
    """Umiejętności z materiałem do ćwiczeń dla kategorii: najlepsze dopasowanie (`content.skills_for_category`), które
    ma wyjaśnienie i zadania zamknięte. Bez dopasowania po samym rodzicu kategorii (np. „tense” przy
    „tense.past_continuous” dawało stronę bierną) — lepiej uczciwe „brak materiałów” niż ćwiczenie czegoś innego."""
    from tutor.app import lesson as L
    tiers: dict[int, list[str]] = {}
    for rank, sid in C.skills_for_category(pack, category, parents=False):
        try:
            L.prepare(pack, sid, allow_unreviewed=allow)
        except L.LessonError:
            continue
        tiers.setdefault(rank, []).append(sid)
    return tiers[min(tiers)] if tiers else []


def _user_turns_between(repo, pid: int, a: str, b: str) -> int:
    return repo.conn.execute("SELECT COUNT(*) FROM turn WHERE profile_id=? AND role='user' AND created_at>=? AND "
                             "created_at<?", (pid, a, b)).fetchone()[0]


def _trend(repo, pid: int, obs: list[dict], now: datetime) -> dict:
    """Ostatnie 14 dni vs poprzednie 14: liczba błędów na liczbę wypowiedzi; ocena tylko przy dość wypowiedzi."""
    t1, t0, t_1 = _iso(now), _iso(now - timedelta(days=14)), _iso(now - timedelta(days=28))
    now_n = sum(1 for o in obs if t0 <= o["created_at"] < t1)
    prev_n = sum(1 for o in obs if t_1 <= o["created_at"] < t0)
    now_u, prev_u = _user_turns_between(repo, pid, t0, t1), _user_turns_between(repo, pid, t_1, t0)
    out = {"last_14d": now_n, "previous_14d": prev_n, "utterances_last_14d": now_u, "utterances_previous_14d": prev_u}
    if now_u < MIN_TURNS_FOR_TREND or prev_u < MIN_TURNS_FOR_TREND:
        return {**out, "direction": "za mało danych"}
    a, b = now_n / now_u, prev_n / prev_u
    return {**out, "direction": "poprawa" if a < b else "pogorszenie" if a > b else "bez zmian"}


SOURCE_PL = {"turn_eval.v3": "ocena wypowiedzi (model)"}
SPOKEN_PL = "pisownia z wypowiedzi mówionej (transkrypcja) — nie liczy się jako błąd"
VERDICT_PL = {"disputed": "zakwestionowane przez Ciebie", "stt_error": "oznaczone jako błąd rozpoznania mowy",
              "accepted": "potwierdzone przez Ciebie", "restored": "przywrócone"}


def entries(repo, pack: C.Pack, pid: int, limit: int = 60) -> list[dict]:
    """Wpisy dziennika: wypowiedź, kontekst (poprzednia kwestia tutora), korekta, kategoria, wiarygodność, data,
    źródło oceny, wyjaśnienie dopasowane do edycji i stan przeglądu przez ucznia. Najnowsze pierwsze."""
    from tutor.app.feedback import explain_edit
    reviews = repo.observation_reviews(pid)
    spoken = repo.spoken_orthography_ids(pid)       # pisownia z mowy: zostaje w historii, oznaczona, nie liczy się
    out = []
    obs = [o for o in repo.list_observations(pid, status="valid")
           if o["kind"] in ("error", "stt_suspect") and o["fix"]][-limit:]
    turns: dict[int, list[dict]] = {}
    for o in reversed(obs):
        sess = turns.setdefault(o["session_id"], repo.list_turns(pid, o["session_id"]))
        idx = next((k for k, t in enumerate(sess) if t["id"] == o["turn_id"]), None)
        utt = sess[idx] if idx is not None else None
        ctx = next((t["text"] for t in reversed(sess[:idx or 0]) if t["role"] == "assistant"), None)
        rv = reviews.get(o["id"])
        if o["kind"] == "stt_suspect":
            rel = "niepewna transkrypcja STT"
        elif o["confidence"] == "h":
            rel = "sugestia modelu (wysoka pewność)"
        else:
            rel = "sugestia modelu (niska pewność)"
        out.append({"id": o["id"], "utterance": utt["text"] if utt else None,
                    "input": utt["input_mode"] if utt else None, "context": ctx, "span": o["span"], "fix": o["fix"],
                    "category": o["category"], "kind": o["kind"], "confidence": o["confidence"], "reliability": rel,
                    "date": o["created_at"], "source": SOURCE_PL.get(o["prompt_version"] or "", "ocena wypowiedzi")
                    + (f" · {o['model']}" if o["model"] else ""),
                    "explanation": explain_edit(pack, o["span"], o["fix"], o["category"] or ""),
                    "review": rv["verdict"] if rv else ("spoken_orthography" if o["id"] in spoken else None),
                    "review_pl": VERDICT_PL.get(rv["verdict"]) if rv else (SPOKEN_PL if o["id"] in spoken else None),
                    "counted": not (rv and rv["verdict"] in ("disputed", "stt_error")) and o["id"] not in spoken})
    return out


def build(repo, pack: C.Pack, pid: int, now: datetime) -> dict:
    rejected = repo.ignored_observation_ids(pid)                 # F7: zakwestionowane nie są słabą stroną
    obs = [o for o in repo.list_observations(pid, status="valid") if o["category"] and o["id"] not in rejected]
    errors = []
    wrong = [(h, s) for s in repo.list_skill_states(pid) for h in repo.attempt_history(pid, s["skill_id"])
             if not h["correct"]]
    from tutor.app import remediation as R
    from tutor.app.goal import agv_checks
    checks = agv_checks(repo, pid)
    hist = R.history(repo, pid)
    uptake: dict[str, dict] = {}            # ponowne użycie po korekcie (obserwacja z rozmów, bez wpływu na plan)
    for sess in repo.list_sessions(pid):
        for u in (repo.get_session_plan(pid, sess["id"]) or {}).get("uptake") or []:
            c = uptake.setdefault(u.get("category"), {"used_ok": 0, "repeated": 0})
            if u.get("result") in c:
                c[u["result"]] += 1
    for e in sorted(repo.list_errors(pid), key=lambda e: (-e["count"], e["category"])):
        cat = e["category"]
        agv = (checks.get(cat) or {}).get("outcome")
        mine = [o for o in obs if o["category"] == cat]
        allow = bool((repo.get_profile(pid) or {}).get("allow_unreviewed_practice", True))
        skills = _skills_for(pack, cat, allow)
        related = {sid for _r, sid in C.skills_for_category(pack, cat, parents=False)}
        confirmed = [h for h, s in wrong if s["skill_id"] in related and h["source"] in ("practice", "remediation",
                                                                                         "diagnosis", "retention")]
        sure = [o for o in mine if o["kind"] == "error" and o["confidence"] == "h"]
        stt = [o for o in mine if o["kind"] == "stt_suspect"]
        if agv == "confirmed":
            rel = "potwierdzony ćwiczeniem kontrolnym"
        elif agv == "not_confirmed" and (e["last_seen"] or "") <= checks[cat]["at"]:
            rel = "w ćwiczeniu kontrolnym poprawnie — błąd widziany tylko w rozmowie"
        elif confirmed:
            rel = "potwierdzony ćwiczeniami"
        elif sure:
            rel = "sugestia modelu"
        elif stt and not sure:
            rel = "niepewna transkrypcja STT"
        else:
            rel = "za mało danych"
        errors.append({"category": cat, "count": e["count"], "status": e["status"], "reliability": rel,
                       "example": e["example"], "correction": e["correction"], "skills": skills,
                       "trend": _trend(repo, pid, mine, now), "first_seen": e["first_seen"],
                       "last_seen": e["last_seen"], "confirmed_by_exercises": len(confirmed), "agv": agv,
                       "uptake": uptake.get(cat),
                       "learning": R.status_pl(hist[cat], e) if cat in hist else None,
                       "learning_lines": R.lines(hist[cat]) if cat in hist else []})
    stt_only = [o for o in repo.list_observations(pid, status="valid") if o["kind"] == "stt_suspect"
                and o["id"] not in rejected]
    words = {}
    for h, s in wrong:
        sk = pack.skills.get(s["skill_id"])
        it = pack.items.get(h["item_id"]) if h["item_id"] else None
        if sk and sk.area == "vocabulary" and it and it.answers:
            w = words.setdefault(it.answers[0], {"term": it.answers[0], "misses": 0, "skill": sk.id})
            w["misses"] += 1
    due = [c["ref_id"] for c in repo.due_cards(pid, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
           if c["card_type"] in ("construction", "skill_check")]
    weak_skills = []
    for s in repo.list_skill_states(pid):
        h = repo.attempt_history(pid, s["skill_id"])
        if s["status"] not in MASTERED and len(h) >= 3 and sum(1 for x in h if x["correct"]) * 2 < len(h):
            ok = sum(1 for x in h if x["correct"])
            weak_skills.append({"skill": s["skill_id"], "attempts": len(h), "correct": ok})
    return {"errors": errors, "stt_uncertain": {"count": len(stt_only), "note": "to NIE są błędy ucznia — możliwe "
            "pomyłki rozpoznawania mowy"}, "vocabulary": sorted(words.values(), key=lambda w: -w["misses"]),
            "weak_skills": weak_skills, "due_reviews": sorted(set(due)), "entries": entries(repo, pack, pid),
            "has_data": bool(errors or words or weak_skills or stt_only or rejected)}


def render(rep: dict) -> list[str]:
    out = ["Dziennik słabych stron (statusy wiarygodności są częścią wyniku):"]
    if not rep["has_data"]:
        return out + ["  Brak danych — porozmawiaj (`--chat`) albo zrób lekcję (`--lesson`)."]
    for i, e in enumerate(rep["errors"], 1):
        t = e["trend"]
        out.append(f"  {i}. {e['category']} ×{e['count']} — {e['reliability']}; trend: {t['direction']} "
                   f"({t['last_14d']} vs {t['previous_14d']} w poprzednim okresie)")
        if e["example"]:
            out.append(f"       np. „{e['example']}” → „{e['correction']}”")
        if e.get("learning"):
            out.append(f"       sprawdzanie w zadaniach: {e['learning']}")
    if rep["vocabulary"]:
        words = ", ".join(f"{w['term']} (×{w['misses']})" for w in rep["vocabulary"][:8])
        out.append(f"  Słownictwo do utrwalenia: {words}")
    if rep["weak_skills"]:
        out.append("  Umiejętności z wieloma pomyłkami: " + ", ".join(
            f"{w['skill']} ({w['correct']}/{w['attempts']})" for w in rep["weak_skills"]))
    if rep["stt_uncertain"]["count"]:
        out.append(f"  Niepewne rozpoznanie mowy: {rep['stt_uncertain']['count']} — {rep['stt_uncertain']['note']}")
    if rep["due_reviews"]:
        out.append("  Do powtórki: " + ", ".join(rep["due_reviews"]) + " (`--review`)")
    out.append("  Ćwiczenia ukierunkowane: `--drill NUMER|KATEGORIA|SKILL`")
    return out


def resolve_drill(rep: dict, pack: C.Pack, target: str, allow: bool = True) -> list[str]:
    """NUMER wpisu dziennika / kategoria błędu / skill_id → umiejętności z materiałem do ćwiczeń."""
    from tutor.app import lesson as L
    if target in pack.skills:
        skills = [target]
    elif target.isdigit() and 1 <= int(target) <= len(rep["errors"]):
        skills = rep["errors"][int(target) - 1]["skills"]
    else:
        skills = _skills_for(pack, target, allow)
    out = []
    for s in skills:
        try:
            L.prepare(pack, s, allow_unreviewed=allow)
            out.append(s)
        except L.LessonError:
            continue
    return out
