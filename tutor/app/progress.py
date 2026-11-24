"""Postęp ucznia wyłącznie z zapisanych dowodów (F6): liczby prób, statusy silnika, harmonogram FSRS, pomiary.
Żadnych wymyślonych procentów poprawy ani poziomów CEFR; wszystko, co niepewne, jest tak oznaczone."""
from __future__ import annotations

import json
from datetime import datetime

from tutor.pedagogy import content as C
from tutor.pedagogy.mastery import MASTERED

MIN_ATTEMPTS = 3        # poniżej: „za mało prób, żeby coś twierdzić”


def _fb(a: dict) -> dict:
    return json.loads(a["feedback_json"]) if a["feedback_json"] else {}


def build(repo, pack: C.Pack, pid: int, now: datetime) -> dict:
    comp: dict[str, dict] = {}
    for r in repo.list_competence(pid):
        comp[r["area"]] = r
    competence = []
    for area in ("grammar", "vocabulary"):
        r = comp.get(area)
        if r is None:
            competence.append({"area": area, "state": "nie sprawdzono"})
            continue
        rat = json.loads(r["rationale"]) if r["rationale"] else {}
        prov = r["source"] != "diagnosis"
        competence.append({"area": area, "state": "szacunek wstępny" if prov else "zmierzone",
                           "label": rat.get("label"), "measured_at": r["measured_at"], "counts": rat.get("counts"),
                           "notice": rat.get("notice")})
    skills = {"mastered": [], "working": [], "struggling": [], "too_few": []}
    transfer = {}
    last_two: dict[str, list[tuple[int, int]]] = {}
    errors = {e["skill_id"] for e in repo.list_errors(pid)
              if e.get("skill_id") and (e.get("status") == "recurring" or (e.get("count") or 0) >= 3)}
    for st in repo.list_skill_states(pid):
        sid = st["skill_id"]
        hist = repo.attempt_history(pid, sid)
        ok = sum(1 for h in hist if h["correct"])
        row = {"skill": sid, "attempts": len(hist), "correct": ok, "status": st["status"]}
        seen: set[str] = set()
        first = [h for h in hist if not (h["item_id"] in seen or seen.add(h["item_id"]))]
        row["new_items"] = f"{sum(1 for h in first if h['correct'])}/{len(first)}"   # transfer: zadania widziane 1. raz
        transfer[sid] = row["new_items"]
        by_sess: dict[int, list[int]] = {}
        for h in hist:
            by_sess.setdefault(h["session_id"] or 0, []).append(1 if h["correct"] else 0)
        for v in by_sess.values():
            last_two.setdefault(sid, []).append((sum(v), len(v)))
        if st["status"] in MASTERED:
            skills["mastered"].append(row)
        elif len(hist) < MIN_ATTEMPTS:
            skills["too_few"].append(row)
        elif sid in errors or ok * 2 < len(hist):
            skills["struggling"].append(row)
        else:
            skills["working"].append(row)
    changes = [{"skill": s, "previous": v[-2], "latest": v[-1]} for s, v in last_two.items() if len(v) >= 2]
    due = [c["ref_id"] for c in repo.due_cards(pid, now.strftime("%Y-%m-%dT%H:%M:%SZ"))
           if c["card_type"] in ("construction", "skill_check")]
    unverified = sum(c.get("unverified", 0) for x in repo.list_sessions(pid) if x["kind"] == "placement"
                     for c in repo.get_session_plan(pid, x["id"]).get("placement", {}).get("counts", {}).values())
    return {"competence": competence, "skills": skills, "changes": changes, "due": sorted(set(due)),
            "unverified_stt": unverified, "attempts_total": sum(r["attempts"] for g in skills.values() for r in g)}


def render(rep: dict) -> list[str]:
    out = ["Twój postęp (tylko z zapisanych dowodów; to nie jest egzamin ani poziom CEFR):"]
    out.append("\nKompetencje:")
    for c in rep["competence"]:
        if c["state"] == "nie sprawdzono":
            out.append(f"  • {c['area']}: nie sprawdzono — uruchom `--placement`.")
        else:
            out.append(f"  • {c['area']}: {c['state']} — {c['label']} ({c['measured_at'][:10]})")
    s = rep["skills"]
    out.append("\nUmiejętności:")
    for title, key in (("opanowane (potwierdzone przez silnik)", "mastered"), ("w nauce", "working"),
                       ("sprawiają trudność", "struggling"), ("za mało prób, by coś twierdzić", "too_few")):
        for r in s[key]:
            out.append(f"  • {title}: {r['skill']} — {r['correct']}/{r['attempts']} poprawnych prób, "
                       f"na nowych zadaniach {r['new_items']}")
    if not any(s.values()):
        out.append("  (brak prób — zacznij lekcję: `--lesson`)")
    if rep["changes"]:
        out.append("\nZmiana od poprzedniej sesji (poprawne/próby, surowe liczby):")
        for c in rep["changes"]:
            out.append(f"  • {c['skill']}: poprzednio {c['previous'][0]}/{c['previous'][1]}, "
                       f"ostatnio {c['latest'][0]}/{c['latest'][1]}")
    out.append("\nDo powtórki: " + (", ".join(rep["due"]) if rep["due"] else "nic zaległego") +
               (" — `--review`" if rep["due"] else ""))
    unc = []
    if any(c["state"] == "szacunek wstępny" for c in rep["competence"]):
        unc.append("pomiary kompetencji są wstępne (materiał niezweryfikowany przez człowieka)")
    if s["too_few"]:
        unc.append("część umiejętności ma mało prób")
    if rep["unverified_stt"]:
        unc.append(f"{rep['unverified_stt']} odpowiedzi głosowych było niepewnie rozpoznanych i nie weszło do wyniku")
    out.append("\nNiepewne: " + ("; ".join(unc) if unc else "brak zgłoszonych zastrzeżeń") + ".")
    return out
