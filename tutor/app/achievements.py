"""Osiągnięcia (motywacja) — OSOBNO od oceny kompetencji. Liczone wyłącznie z zapisów w bazie; trwałe i idempotentne
(`achievement` PK profile+code), więc wznowienie sesji ani ponowne wywołanie nie nalicza drugi raz.
Odznaka „opanowano umiejętność” istnieje tylko dla umiejętności, które SILNIK uznał za opanowane (`skill_state`)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from tutor.app import goal as G
from tutor.app import quickchat as QC
from tutor.pedagogy.mastery import MASTERED

# (kod, kategoria, metryka, próg, nazwa PL, opis PL)
TIERS = [
    ("streak_3", "regularity", "streak", 3, "Trzy dni z rzędu", "Uczysz się 3 dni z rzędu."),
    ("streak_7", "regularity", "streak", 7, "Tydzień nauki", "Uczysz się 7 dni z rzędu."),
    ("streak_14", "regularity", "streak", 14, "Dwa tygodnie", "Uczysz się 14 dni z rzędu."),
    ("streak_30", "regularity", "streak", 30, "Miesiąc nauki", "Uczysz się 30 dni z rzędu."),
    ("days_10", "regularity", "study_days", 10, "Dziesięć dni nauki", "10 różnych dni z aktywnością."),
    ("talk_10m", "talk_time", "talk_minutes", 10, "Pierwsze 10 minut", "10 minut rozmów."),
    ("talk_60m", "talk_time", "talk_minutes", 60, "Godzina rozmów", "60 minut rozmów."),
    ("talk_300m", "talk_time", "talk_minutes", 300, "Pięć godzin rozmów", "300 minut rozmów."),
    ("lesson_1", "lessons", "lessons", 1, "Pierwsza lekcja", "Ukończona pierwsza lekcja."),
    ("lesson_5", "lessons", "lessons", 5, "Pięć lekcji", "Ukończone 5 lekcji."),
    ("lesson_20", "lessons", "lessons", 20, "Dwadzieścia lekcji", "Ukończone 20 lekcji."),
    ("review_10", "reviews", "reviews", 10, "Dziesięć powtórek", "10 zadań powtórkowych."),
    ("review_50", "reviews", "reviews", 50, "Pięćdziesiąt powtórek", "50 zadań powtórkowych."),
    ("review_200", "reviews", "reviews", 200, "Dwieście powtórek", "200 zadań powtórkowych."),
    ("improved_1", "improvement", "errors_improved", 1, "Pierwsza poprawa", "Jeden powtarzający się błąd ustępuje."),
    ("improved_3", "improvement", "errors_improved", 3, "Trzy poprawione błędy", "3 błędy wykazują poprawę."),
    ("improved_10", "improvement", "errors_improved", 10, "Dziesięć poprawionych błędów",
     "10 błędów wykazuje poprawę."),
    ("exam_1", "exams", "exam_sessions", 1, "Pierwsza próba egzaminacyjna",
     "Ukończona sesja ćwiczeń egzaminacyjnych."),
    ("exam_5", "exams", "exam_sessions", 5, "Pięć prób egzaminacyjnych", "5 sesji ćwiczeń egzaminacyjnych."),
    ("topics_5", "challenges", "chat_categories", 5, "Odkrywca tematów", "Rozmowy z 5 różnych kategorii tematów."),
    ("triple_day", "challenges", "triple_day", 1, "Pełny dzień", "Lekcja, powtórka i rozmowa tego samego dnia."),
    ("comeback", "challenges", "comeback", 1, "Powrót", "Powrót do nauki po co najmniej 7 dniach przerwy."),
    ("first_session", "milestones", "sessions", 1, "Początek", "Pierwsza sesja."),
    ("turns_100", "milestones", "user_turns", 100, "Sto wypowiedzi", "100 Twoich wypowiedzi w rozmowach."),
    ("placement_done", "milestones", "placements", 1, "Poznałem swój punkt wyjścia", "Dopasowanie poziomu wykonane "
     "(wynik wstępny, nie certyfikat)."),
]
CATEGORIES = {"regularity": "Regularność", "talk_time": "Czas rozmów", "lessons": "Lekcje", "reviews": "Powtórki",
              "improvement": "Poprawa błędów", "exams": "Egzaminy", "challenges": "Wyzwania",
              "milestones": "Kamienie milowe", "competence": "Opanowane umiejętności (potwierdzone przez silnik)"}


def _day(s: str) -> date:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def _streak(days: list[date], today: date) -> int:
    """Najdłuższa seria kolejnych dni (rekord się nie cofa, więc odznaka jest trwała)."""
    best = run = 0
    prev = None
    for d in sorted(set(days)):
        run = run + 1 if prev and d - prev == timedelta(days=1) else 1
        best, prev = max(best, run), d
    return best


def stats(repo, pid: int, now: datetime) -> dict:
    sessions = repo.list_sessions(pid)
    active_days: list[date] = []
    talk = turns = reviews = exam = 0
    chat_cats: set[str] = set()
    by_day: dict[date, set[str]] = {}
    for s in sessions:
        ts = repo.list_turns(pid, s["id"])
        plan = repo.get_session_plan(pid, s["id"])
        used = bool(ts) or s["kind"] in ("review", "exam", "placement", "lesson", "drill")
        if s["kind"] in ("review", "lesson", "chat", "exam", "drill") and used:
            by_day.setdefault(_day(s["started_at"]), set()).add(s["kind"])
        if ts or plan.get("done") or plan.get("review") or plan.get("placement") or plan.get("exam"):
            active_days.append(_day(s["started_at"]))
        if ts:
            talk += QC.active_seconds(repo, pid, s["id"])
            turns += sum(1 for t in ts if t["role"] == "user")
        if s["kind"] == "chat":
            chat_cats |= {t["category"] for t in plan.get("topics", []) if t.get("category") != "custom"}
        if s["kind"] == "exam" and plan.get("exam", {}).get("finished"):
            exam += 1
    reviews = repo.conn.execute("SELECT COUNT(*) FROM attempt WHERE profile_id=? AND "
                                "json_extract(feedback_json,'$.review')=1", (pid,)).fetchone()[0]
    improved = sum(1 for e in repo.list_errors(pid) if e["status"] in ("improving", "resolved"))
    days = sorted(set(active_days))
    comeback = any((b - a).days >= 7 for a, b in zip(days, days[1:], strict=False))
    return {"streak": _streak(days, now.date()), "study_days": len(days), "talk_minutes": talk // 60,
            "lessons": len(G.completed(repo, pid)), "reviews": reviews, "errors_improved": improved,
            "exam_sessions": exam, "chat_categories": len(chat_cats), "sessions": len(sessions),
            "triple_day": int(any({"lesson", "review", "chat"} <= k for k in by_day.values())),
            "comeback": int(comeback), "user_turns": turns,
            "placements": int(bool(repo.list_competence(pid)))}


def award(repo, pid: int, now: datetime | None = None) -> list[dict]:
    """Przyznaje zasłużone osiągnięcia; zwraca TYLKO nowe (idempotentne)."""
    now = now or datetime.now(UTC)
    st = stats(repo, pid, now)
    new = []
    for code, cat, metric, need, name, desc in TIERS:
        if st[metric] >= need and repo.add_achievement(pid, code, {"metric": metric, "value": st[metric]}):
            new.append({"code": code, "category": cat, "name": name, "description": desc})
    for s in repo.list_skill_states(pid):
        if s["status"] in MASTERED and repo.add_achievement(pid, f"mastered:{s['skill_id']}",
                                                            {"skill": s["skill_id"], "status": s["status"]}):
            new.append({"code": f"mastered:{s['skill_id']}", "category": "competence",
                        "name": "Opanowana umiejętność", "description": s["skill_id"]})
    return new


def overview(repo, pid: int, now: datetime | None = None) -> dict:
    """Zdobyte + zablokowane z postępem (liczby z bazy)."""
    now = now or datetime.now(UTC)
    st = stats(repo, pid, now)
    earned = {a["code"]: a for a in repo.list_achievements(pid)}
    items = []
    for code, cat, metric, need, name, desc in TIERS:
        a = earned.get(code)
        items.append({"code": code, "category": cat, "name": name, "description": desc, "earned": a is not None,
                      "earned_at": a["earned_at"] if a else None, "progress": min(st[metric], need), "target": need})
    for code, a in earned.items():
        if code.startswith("mastered:"):
            items.append({"code": code, "category": "competence", "name": "Opanowana umiejętność",
                          "description": json.loads(a["evidence_json"]).get("skill", ""), "earned": True,
                          "earned_at": a["earned_at"], "progress": 1, "target": 1})
    return {"earned": sum(1 for i in items if i["earned"]), "total": len(items), "items": items,
            "categories": CATEGORIES, "note": "Osiągnięcia motywują; nie są oceną kompetencji."}


