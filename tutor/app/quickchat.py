"""Quick Chat: swobodna rozmowa na wybrany temat, bez celu lekcji i bez diagnozy (sesja `kind="chat"`).

Wykorzystuje istniejące `VoiceTutor`/`SessionService`; tu tylko stan sesji (temat, zmiany, limit czasu, historia).
Rozmowa NIE zapisuje prób zadań, więc nie może zmienić `skill_state` ani nadać mastery."""
from __future__ import annotations

from datetime import datetime

from tutor.app import topics as T
from tutor.voice.conversation import SYSTEM_PROMPT

MINUTES = (5, 10, 15, 20, 30)


MODES_PL = {"natural": "Naturalna rozmowa", "guided": "Rozmowa prowadzona", "roleplay": "Roleplay"}
DEFAULT_LEVEL = "A2"          # ostrożny start bez diagnozy

LEVEL_NOTES = {
    "A1": "The student is a beginner (CEFR A1): use very short, simple sentences and the most common words, one idea "
          "at a time, and questions that can be answered in a few words.",
    "A2": "The student is elementary (CEFR A2): use short, clear sentences and everyday words; introduce at most one "
          "new useful word or phrase at a time and explain it with an easy synonym if needed.",
    "B1": "The student is intermediate (CEFR B1): use natural everyday English at a moderate pace, common phrasal "
          "verbs and some topic vocabulary; ask open questions.",
    "B2": "The student is upper-intermediate (CEFR B2): use natural English with topic-specific vocabulary and some "
          "idioms; ask questions that invite opinions, comparisons and reasons.",
    "C1": "The student is advanced (CEFR C1): talk as you would to a fluent colleague, with precise vocabulary and "
          "nuance; you may use up to three sentences and challenge their reasoning politely.",
}
LONG_OK = " Never ask the student to keep answers short: longer answers are welcome at every level."
MODE_NOTES = {
    "natural": " Mode: natural conversation. Follow the student's lead like a real conversation partner and sometimes "
               "share a short opinion or experience of your own. Do not turn it into an interview and do not correct "
               "small slips.",
    "guided": " Mode: guided conversation. Lead the conversation step by step through the topic. When the student "
              "gives a very short answer or struggles, offer ONE useful phrase or sentence frame they could use "
              "(for example: You could say: ...) and introduce relevant vocabulary naturally.",
}
CATEGORY_NOTES = {
    "technical": " This is Technical English (IT): use correct technical terms. You practise how the student explains "
                 "technical ideas in English; do not grade their technical knowledge.",
    "medical": " This is Medical English for healthcare and emergency medical services. It is language practice, not "
               "clinical training: never present medical recommendations or treatment decisions as facts; if asked "
               "for clinical advice, say it depends on local protocols and the clinical team. Never comment on the "
               "student's clinical competence.",
    "business": " This is Business English: use a professional, clear and polite register.",
    "professional": " This is a professional situation: use a professional, clear and polite register.",
}


def start(repo, profile_id: int, topic: dict, minutes: int | None = None, correction: str | None = None,
          *, level: str | None = None, level_source: str | None = None, category: str | None = None,
          mode: str | None = None) -> int:
    sid = repo.start_session(profile_id, "chat", planned_minutes=minutes)
    mode = mode or ("roleplay" if topic.get("kind") == "roleplay" else "natural")
    repo.set_session_plan(profile_id, sid, {"topic": topic, "topics": [topic], "minutes": minutes,
                                            "correction": correction, "level": level, "level_source": level_source,
                                            "category": category or topic.get("category"),
                                            "mode": mode})
    return sid


def resolve_level(repo, profile_id: int, chosen: str | None) -> tuple[str, str, str]:
    """(poziom, źródło, komunikat). Ręczny wybór nie zmienia diagnozy ani mastery; „auto” bierze niższy z ostatnich
    wyników dobrowolnego sprawdzenia poziomu, a bez nich ostrożne A2."""
    if chosen in T.LEVELS:
        return chosen, "manual", f"Poziom: {chosen} (wybrany ręcznie)."
    latest: dict[str, str] = {}
    for c in repo.list_competence(profile_id):           # posortowane rosnąco po dacie: wygrywa ostatni pomiar
        latest[c["area"]] = c["cefr"]
    known = [lv if lv in T.LEVELS else ("C1" if lv == "C2" else "A1") for lv in latest.values() if lv]
    if known:
        lv = min(known, key=T.LEVELS.index)
        return lv, "placement", f"Poziom automatyczny: {lv} (z wyniku dobrowolnego sprawdzenia poziomu)."
    return DEFAULT_LEVEL, "default", (f"Poziom automatyczny: {DEFAULT_LEVEL}. Nie ma jeszcze sprawdzenia poziomu, "
                                      "więc zaczynam ostrożnie; możesz wybrać poziom ręcznie.")


def system_prompt(topic: dict, level: str = "B1", mode: str = "natural") -> str:
    """Prompt rozmowy: temat + poziom + tryb + charakter kategorii. Bez osobnego systemu rozmów (ten sam VoiceTutor)."""
    level = level if level in T.LEVELS else "B1"
    cat = topic.get("category", "general")
    base = SYSTEM_PROMPT + " " + LEVEL_NOTES[level] + LONG_OK + CATEGORY_NOTES.get(cat, "")
    if mode == "roleplay":
        role = topic.get("role") or "a person who naturally fits this situation (say who you are in your first reply)"
        learner = topic.get("learner") or "themselves"
        setup = topic.get("setup") or f"The situation is about: {topic['pl']}."
        return (base + f" Mode: role-play. You are {role}. The student is {learner}. Situation: {setup} "
                f"Stay in character the whole time and speak only as {role} would. You do not have to ask a question "
                "in every reply; react as the character would. Do not act as a teacher and do not correct grammar "
                "during the role-play (feedback comes after it). If the student asks you to explain a word or to "
                "repeat, do it briefly and stay in the role. If the student clearly asks to stop or to change the "
                "topic, follow that.")
    return (base + MODE_NOTES.get(mode, MODE_NOTES["natural"]) + f" Current topic: “{topic['pl']}” "
            f"({topic.get('category_pl', '')}). Stay on this topic unless the student changes it.")


def switch_note(topic: dict, level: str = "B1") -> str:
    q = T.opener(topic, level) if topic.get("id") else topic["q"]
    if topic.get("kind") == "roleplay":
        return (f" The student asked for a different situation. Say in a few words that you start a new role-play, "
                f"then speak as {topic.get('role')} and say exactly this: “{q}”")
    return (f" The student asked to change the topic. In this reply, agree in a few words and then ask exactly this "
            f"question: “{q}”")


def scenario_line(topic: dict) -> str | None:
    """Krótki kontekst scenariusza dla ucznia (po polsku), wyświetlany przed pierwszą kwestią w roli."""
    if topic.get("kind") == "roleplay" and topic.get("context_pl"):
        return f"Scenariusz: {topic['context_pl']}"
    return None


def opener(topic: dict, level: str = "B1") -> str:
    return T.opener(topic, level) if topic.get("id") and T.get(topic["id"]) else topic["q"]


def switch(repo, profile_id: int, sid: int, topic: dict) -> str:
    """Zmiana tematu w trakcie sesji (zapis w historii tematów; poziom i tryb bez zmian). Zwraca nowy prompt."""
    plan = repo.get_session_plan(profile_id, sid)
    plan["topic"] = topic
    plan["topics"] = [*plan.get("topics", []), topic]
    repo.set_session_plan(profile_id, sid, plan)
    return system_prompt(topic, plan.get("level") or "B1", plan.get("mode") or "natural")


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
                    "level": plan.get("level"), "category": plan.get("category"), "mode": plan.get("mode"),
                    "seconds_active": active_seconds(repo, profile_id, s["id"]),
                    "user_turns": sum(1 for t in turns if t["role"] == "user")})
    return out[-limit:][::-1]


def pick(repo, profile_id: int, choice: str, shown: list[dict], seed_counter: int) -> tuple[str, dict | list | None]:
    """Obsługa wyboru z listy: numer → temat; `r` → nowa lista; inny tekst → temat własny."""
    c = choice.strip()
    if c.isdigit() and 1 <= int(c) <= len(shown):
        return "topic", shown[int(c) - 1]
    if c.lower() in ("r", "reroll", "losuj"):
        t0 = shown[0] if shown else {}
        return "list", T.suggest(repo, profile_id, len(shown), seed=seed_counter, exclude={t["id"] for t in shown},
                                 category=t0.get("category", "general"),
                                 mode="roleplay" if t0.get("kind") == "roleplay" else "natural")
    if c:
        return "topic", T.custom(c)
    return "none", None
