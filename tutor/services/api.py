"""Warstwa usług dla przyszłego interfejsu (GUI). Brak logiki UI i brak sieci: cienka fasada nad `tutor.app`,
profil-scoped, zwraca WYŁĄCZNIE struktury JSON-owalne (dict/list/str/int/float/bool/None).

Podział:
 * zapytania i komendy jednorazowe — metody `TutorAPI` (poniżej);
 * sesje interaktywne (lekcja, powtórki, dopasowanie, egzamin) — te same funkcje `run(...)` z modułów
   `lesson/placement/review/exams` z wywołaniami zwrotnymi `ask(item, n) -> Answer|None`, `say(str)`, `speak(str)`;
   GUI podaje własne implementacje (kontrakt: docs/ai-work/SERVICES.md). Rozmowa: `VoiceTutor` + `SessionService`.
Jeśli kiedyś dodamy serwer HTTP, wiążemy WYŁĄCZNIE 127.0.0.1."""
from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

from tutor.app import achievements as AC
from tutor.app import exams as EX
from tutor.app import goal as G
from tutor.app import history as H
from tutor.app import lesson as L
from tutor.app import placement as PL
from tutor.app import progress as PG
from tutor.app import quickchat as QC
from tutor.app import review as RV
from tutor.app import settings as ST
from tutor.app import topics as T
from tutor.app import weakspots as WS
from tutor.pedagogy import content as C
from tutor.store.repo import Repo


class ServiceError(Exception):
    pass


class TutorAPI:
    def __init__(self, repo: Repo, now=lambda: datetime.now(UTC)):
        self.repo, self.now, self._packs = repo, now, {}

    # --- profile ---
    def profiles(self) -> list[dict]:
        return [{"id": p["id"], "name": p["name"], "target_lang": p["target_lang"]} for p in self._all_profiles()]

    def _all_profiles(self):
        return [dict(r) for r in self.repo.conn.execute("SELECT * FROM profile ORDER BY id")]

    def create_profile(self, name: str) -> dict:
        try:
            pid = self.repo.create_profile(name)
        except Exception as e:  # noqa: BLE001 - nazwa zajęta/pusta
            raise ServiceError(f"Nie można utworzyć profilu: {e}") from e
        return {"id": pid, "name": name.strip()}

    def _profile(self, pid: int) -> dict:
        p = self.repo.get_profile(pid)
        if p is None:
            raise ServiceError(f"Brak profilu {pid}")
        return p

    def pack(self, pid: int) -> C.Pack:
        lang = self._profile(pid)["target_lang"]
        if lang not in self._packs:
            self._packs[lang] = C.load(lang)
        return self._packs[lang]

    # --- ekran główny ---
    def home(self, pid: int) -> dict:
        p, pack = self._profile(pid), self.pack(pid)
        ch = G.choose(self.repo, pack, pid, self.now())
        s = H.sessions(self.repo, pid, 1)
        return {"profile": {"id": pid, "name": p["name"]},
                "suggested_lesson": dataclasses.asdict(ch) if ch else None,
                "due_reviews": len(RV.due_skills(self.repo, pack, pid, self.now(),
                                                 bool(p["allow_unreviewed_practice"]))),
                "streak": AC.stats(self.repo, pid, self.now())["streak"],
                "last_session": s[0] if s else None,
                "placement_done": bool(self.repo.list_competence(pid)),
                "open_session": self.repo.find_open_session(pid)}

    # --- Quick Chat ---
    def chat_topics(self, pid: int, n: int = 4, seed: int | None = None) -> list[dict]:
        return T.suggest(self.repo, pid, n, seed=seed)

    def chat_start(self, pid: int, topic_id: str | None = None, custom: str | None = None,
                   minutes: int | None = None, correction: str | None = None) -> dict:
        topic = T.get(topic_id) if topic_id else T.custom(custom) if custom else None
        if topic is None:
            raise ServiceError("Podaj topic_id albo custom")
        if minutes is not None and minutes not in QC.MINUTES:
            raise ServiceError(f"minutes: {QC.MINUTES}")
        sid = QC.start(self.repo, pid, topic, minutes, correction)
        self.repo.add_turn(pid, sid, "assistant", QC.opener(topic))        # pytanie otwierające jest w historii
        return {"session_id": sid, "topic": topic, "opener": QC.opener(topic), "system_prompt": QC.system_prompt(topic)}

    def chat_history(self, pid: int) -> list[dict]:
        return QC.history(self.repo, pid)

    # --- lekcje ---
    def lesson_suggestion(self, pid: int) -> dict | None:
        ch = G.choose(self.repo, self.pack(pid), pid, self.now())
        return dataclasses.asdict(ch) if ch else None

    def lesson_catalog(self, pid: int) -> list[dict]:
        """Tematy do ręcznego wyboru — tylko takie, do których są materiały."""
        pack, allow, out = self.pack(pid), bool(self._profile(pid)["allow_unreviewed_practice"]), []
        for s in sorted(pack.skills.values(), key=lambda s: (s.cefr, s.id)):
            try:
                L.prepare(pack, s.id, allow_unreviewed=allow)
            except L.LessonError:
                continue
            out.append({"skill_id": s.id, "cefr": s.cefr, "area": s.area, "can_do_pl": s.can_do_pl})
        return out

    # --- określanie poziomu (dobrowolne) ---
    def placement_info(self, pid: int) -> dict:
        pack, allow = self.pack(pid), bool(self._profile(pid)["allow_unreviewed_practice"])
        return {"areas": [{"area": a, "items": len(PL._items(pack, a, allow))} for a in PL.AREAS],
                "results": H.placements(self.repo, pid), "voluntary": True,
                "notice": "Wynik jest szacunkiem wstępnym, nie diagnozą CEFR."}

    # --- raporty ---
    def progress(self, pid: int) -> dict:
        return PG.build(self.repo, self.pack(pid), pid, self.now())

    def weakspots(self, pid: int) -> dict:
        return WS.build(self.repo, self.pack(pid), pid, self.now())

    def achievements(self, pid: int, award: bool = True) -> dict:
        new = AC.award(self.repo, pid, self.now()) if award else []
        return {**AC.overview(self.repo, pid, self.now()), "new": new}

    def history(self, pid: int, limit: int = 50) -> dict:
        return {"totals": H.totals(self.repo, pid), "sessions": H.sessions(self.repo, pid, limit),
                "placements": H.placements(self.repo, pid), "chats": QC.history(self.repo, pid),
                "exams": EX.history(self.repo, pid)}

    def skill_timeline(self, pid: int, skill_id: str) -> list[dict]:
        return H.skill_timeline(self.repo, pid, skill_id)

    # --- egzaminy ---
    def exam_paths(self, pid: int) -> list[dict]:
        pack, allow = self.pack(pid), bool(self._profile(pid)["allow_unreviewed_practice"])
        return [{"id": p["id"], "name": p["name_pl"], "coverage": EX.coverage(pack, p, allow),
                 "readiness": EX.readiness(self.repo, pack, pid, p, allow), "official": p["official"],
                 "disclaimer": p["disclaimer_pl"], "speaking_topics": p.get("speaking_extra", {}).get("topics", [])}
                for p in EX.load_all().values()]

    # --- ustawienia ---
    def settings(self, pid: int) -> dict:
        return {"values": ST.effective(self.repo, pid),
                "schema": {k: {kk: list(vv) if isinstance(vv, tuple) else vv for kk, vv in v.items() if kk != "column"}
                           for k, v in ST.SCHEMA.items()}}

    def update_settings(self, pid: int, changes: dict) -> dict:
        try:
            return ST.update(self.repo, pid, changes)
        except ST.SettingError as e:
            raise ServiceError(str(e)) from e
