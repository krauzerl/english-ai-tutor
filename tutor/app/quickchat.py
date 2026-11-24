"""Quick Chat: swobodna rozmowa na wybrany temat, bez celu lekcji i bez diagnozy (sesja `kind="chat"`).

Wykorzystuje istniejące `VoiceTutor`/`SessionService`; tu tylko stan sesji (temat, zmiany, limit czasu, historia).
Rozmowa NIE zapisuje prób zadań, więc nie może zmienić `skill_state` ani nadać mastery."""
from __future__ import annotations

from datetime import datetime

from tutor.app import topics as T
from tutor.voice.conversation import SYSTEM_PROMPT

MINUTES = (5, 10, 15, 20, 30)


def start(repo, profile_id: int, topic: dict, minutes: int | None = None, correction: str | None = None) -> int:
    sid = repo.start_session(profile_id, "chat", planned_minutes=minutes)
    repo.set_session_plan(profile_id, sid, {"topic": topic, "topics": [topic], "minutes": minutes,
                                            "correction": correction})
    return sid


def system_prompt(topic: dict) -> str:
    return (SYSTEM_PROMPT + f" Free chat. Current topic: “{topic['pl']}” ({topic['category_pl']}). "
            "Stay on this topic unless the student changes it; the student leads, you follow with interest.")


def switch_note(topic: dict) -> str:
    return (f" The student asked to change the topic. In this reply, agree in a few words and then ask exactly this "
            f"question: \u201c{topic['q']}\u201d")


def opener(topic: dict) -> str:
    return topic["q"]


def switch(repo, profile_id: int, sid: int, topic: dict) -> str:
    """Zmiana tematu w trakcie sesji (zapis w historii tematów). Zwraca nowy prompt systemowy."""
    plan = repo.get_session_plan(profile_id, sid)
    plan["topic"] = topic
    plan["topics"] = [*plan.get("topics", []), topic]
    repo.set_session_plan(profile_id, sid, plan)
    return system_prompt(topic)


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def time_up(repo, profile_id: int, sid: int, now: datetime) -> bool:
    """Limit liczony z czasu aktywnej rozmowy (zapisane tury); przerwy między uruchomieniami nie liczą się."""
    plan = repo.get_session_plan(profile_id, sid)
    m = plan.get("minutes")
    return bool(m) and active_seconds(repo, profile_id, sid) >= m * 60


def active_seconds(repo, profile_id: int, sid: int, gap_cap: int = 120) -> int:
    """Czas rozmowy z zapisów tur: suma odstępów między kolejnymi turami, każdy odstęp ≤ gap_cap s."""
    ts = [_dt(t["created_at"]) for t in repo.list_turns(profile_id, sid)]
    return int(sum(min((b - a).total_seconds(), gap_cap) for a, b in zip(ts, ts[1:], strict=False)))


def history(repo, profile_id: int, limit: int = 20) -> list[dict]:
    out = []
    for s in repo.list_sessions(profile_id):
        if s["kind"] != "chat":
            continue
        plan = repo.get_session_plan(profile_id, s["id"])
        turns = repo.list_turns(profile_id, s["id"])
        out.append({"session_id": s["id"], "started_at": s["started_at"], "status": s["status"],
                    "topics": [t["pl"] for t in plan.get("topics", [])], "minutes_planned": plan.get("minutes"),
                    "seconds_active": active_seconds(repo, profile_id, s["id"]),
                    "user_turns": sum(1 for t in turns if t["role"] == "user")})
    return out[-limit:][::-1]


def pick(repo, profile_id: int, choice: str, shown: list[dict], seed_counter: int) -> tuple[str, dict | list | None]:
    """Obsługa wyboru z listy: numer → temat; `r` → nowa lista; inny tekst → temat własny."""
    c = choice.strip()
    if c.isdigit() and 1 <= int(c) <= len(shown):
        return "topic", shown[int(c) - 1]
    if c.lower() in ("r", "reroll", "losuj"):
        return "list", T.suggest(repo, profile_id, len(shown), seed=seed_counter, exclude={t["id"] for t in shown})
    if c:
        return "topic", T.custom(c)
    return "none", None
