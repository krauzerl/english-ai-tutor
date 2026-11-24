"""Historia nauki wyłącznie z zapisów: sesje, czas (z odstępów między zapisami, każdy ≤ 2 min), lekcje, powtórki,
diagnoza, oś czasu umiejętności. Zero wartości szacowanych „na oko”."""
from __future__ import annotations

import json
from datetime import datetime

from tutor.app import goal as G

GAP_CAP = 120


def _t(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def session_seconds(repo, pid: int, sid: int) -> int:
    ts = [r[0] for r in repo.conn.execute("SELECT created_at FROM turn WHERE profile_id=? AND session_id=?",
                                          (pid, sid))]
    ts += [r[0] for r in repo.conn.execute("SELECT created_at FROM attempt WHERE profile_id=? AND session_id=?",
                                           (pid, sid))]
    ts = sorted(_t(x) for x in ts)
    return int(sum(min((b - a).total_seconds(), GAP_CAP) for a, b in zip(ts, ts[1:], strict=False)))


def _title(kind: str, plan: dict) -> str:
    if kind == "chat":
        return (plan.get("topic") or {}).get("pl", "Quick Chat")
    if kind == "lesson":
        return plan.get("lesson") or "Lekcja"
    if kind == "exam":
        return (plan.get("exam") or {}).get("path", "Egzamin")
    return {"review": "Powtórki", "drill": "Ćwiczenia słabej strony", "placement": "Określanie poziomu",
            "voice": "Rozmowa"}.get(kind, kind)


def sessions(repo, pid: int, limit: int = 50) -> list[dict]:
    out = []
    for s in repo.list_sessions(pid):
        plan = repo.get_session_plan(pid, s["id"])
        turns = repo.list_turns(pid, s["id"])
        att = repo.conn.execute("SELECT COUNT(*), COALESCE(SUM(correct),0) FROM attempt WHERE profile_id=? AND "
                                "session_id=?", (pid, s["id"])).fetchone()
        out.append({"session_id": s["id"], "kind": s["kind"], "title": _title(s["kind"], plan),
                    "started_at": s["started_at"], "ended_at": s["ended_at"], "status": s["status"],
                    "seconds": session_seconds(repo, pid, s["id"]),
                    "user_turns": sum(1 for t in turns if t["role"] == "user"),
                    "attempts": att[0], "attempts_correct": att[1]})
    return out[-limit:][::-1]


def totals(repo, pid: int) -> dict:
    ss = sessions(repo, pid, limit=10**6)
    kinds: dict[str, int] = {}
    for s in ss:
        kinds[s["kind"]] = kinds.get(s["kind"], 0) + 1
    reviews = repo.conn.execute("SELECT COUNT(*) FROM attempt WHERE profile_id=? AND "
                                "json_extract(feedback_json,'$.review')=1", (pid,)).fetchone()[0]
    return {"sessions": len(ss), "sessions_by_kind": kinds, "study_seconds": sum(s["seconds"] for s in ss),
            "lessons_completed": len(G.completed(repo, pid)), "reviews_done": reviews,
            "user_turns": sum(s["user_turns"] for s in ss)}


def placements(repo, pid: int) -> list[dict]:
    out = []
    for c in repo.list_competence(pid):
        rat = json.loads(c["rationale"]) if c["rationale"] else {}
        out.append({"area": c["area"], "measured_at": c["measured_at"], "label": rat.get("label"),
                    "status": "szacunek wstępny" if c["source"] != "diagnosis" else "zmierzone",
                    "counts": rat.get("counts"), "notice": rat.get("notice")})
    return out


def skill_timeline(repo, pid: int, skill_id: str) -> list[dict]:
    rows = repo.conn.execute("SELECT day, COUNT(*), SUM(correct) FROM attempt WHERE profile_id=? AND skill_id=? "
                             "GROUP BY day ORDER BY day", (pid, skill_id)).fetchall()
    return [{"day": r[0], "attempts": r[1], "correct": r[2]} for r in rows]


def render(repo, pid: int) -> list[str]:
    t = totals(repo, pid)
    out = [f"Historia nauki: {t['sessions']} sesji, łączny czas aktywny {t['study_seconds'] // 60} min, "
           f"ukończone lekcje: {t['lessons_completed']}, zadania powtórek: {t['reviews_done']}."]
    for s in sessions(repo, pid, 15):
        out.append(f"  #{s['session_id']} {s['started_at'][:16].replace('T', ' ')} {s['kind']:<9} {s['title']} — "
                   f"{s['seconds'] // 60} min, wypowiedzi: {s['user_turns']}, próby: {s['attempts_correct']}/"
                   f"{s['attempts']} [{s['status']}]")
    for pl in placements(repo, pid):
        out.append(f"  Określanie poziomu ({pl['measured_at'][:10]}): {pl['area']} — {pl['label']} [{pl['status']}]")
    return out
