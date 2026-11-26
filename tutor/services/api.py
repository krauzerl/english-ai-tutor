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
import threading
from datetime import UTC, datetime

from tutor.app import achievements as AC
from tutor.app import diagnostic as DG
from tutor.app import exams as EX
from tutor.app import goal as G
from tutor.app import growth as GR
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

_PACK_LOCK = threading.Lock()      # GUI: równoległe żądania nie wczytują paczki treści kilka razy naraz


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

    def reset_or_delete(self, pid: int, op: str, confirm: str, make_backup: bool = True) -> dict:
        from tutor.app import profiles as PR
        self._profile(pid)
        try:
            fn = PR.delete if op == "delete" else PR.reset_progress
            return fn(self.repo, pid, confirm, make_backup=make_backup)
        except PR.ProfileOpError as e:
            raise ServiceError(str(e)) from e

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
        with _PACK_LOCK:
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
                "pending_evals": sum(self.repo.pending_by_session(pid).values()),
                "open_session": self.repo.find_open_session(pid)}

    # --- Quick Chat ---
    def chat_topics(self, pid: int, n: int = 4, seed: int | None = None, category: str = "general",
                    level: str = "auto", mode: str = "natural") -> list[dict]:
        lv = QC.resolve_level(self.repo, pid, level)[0]
        return [{**t, "opener": T.opener(t, lv)} for t in T.suggest(self.repo, pid, n, seed=seed, category=category,
                                                                    level=lv, mode=mode)]

    def chat_options(self, pid: int) -> dict:
        """Wybór przed rozmową: poziomy, kategorie, tryby, ostatnie ustawienia profilu i wynik poziomu „auto”."""
        eff = ST.effective(self.repo, pid)
        lv, src, notice = QC.resolve_level(self.repo, pid, "auto")
        cats = list(T.chat_catalog()["categories"].values()) + [
            {"id": "custom", "pl": "Custom Topic", "about_pl": "Dowolny własny temat."}]
        return {"levels": ["auto", *T.LEVELS], "categories": cats,
                "modes": [{"id": m, "pl": QC.MODES_PL[m]} for m in T.MODES],
                "prefs": {"level": eff["chat_level"], "category": eff["chat_category"], "mode": eff["chat_mode"]},
                "auto": {"level": lv, "source": src, "notice": notice}}

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
        pend = self.repo.pending_by_session(pid)
        return [{**c, "pending_evals": pend.get(c["session_id"], 0)} for c in QC.history(self.repo, pid)]

    def session_feedback(self, pid: int, sid: int) -> dict:
        """Podsumowanie korekt rozmowy do odczytu później; `complete` = wszystkie wypowiedzi ocenione."""
        from tutor.app import feedback as FB
        if self.repo.get_session(pid, sid) is None:
            raise ServiceError("Brak sesji")
        left = self.repo.pending_by_session(pid).get(sid, 0)
        return {"session_id": sid, "pending": left, "complete": left == 0,
                "lines": FB.summary_lines(self.repo, self.pack(pid), pid, sid, pending=left)}

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

    def assessment(self, pid: int) -> dict:
        """Pełna diagnoza: profil sześciu kompetencji, pokrycie banku, otwarta (wznawialna) sesja."""
        pack, allow = self.pack(pid), bool(self._profile(pid)["allow_unreviewed_practice"])
        cur = self.repo.find_open_session(pid)
        resume = None
        if cur and cur["kind"] == "assessment":
            st = (self.repo.get_session_plan(pid, cur["id"]) or {}).get("assessment") or {}
            resume = {"session_id": cur["id"], "areas": st.get("areas", []), "finished": st.get("finished", [])}
        return {"profile": DG.profile(self.repo, pack, pid), "coverage": DG.coverage(pack, allow),
                "areas": list(DG.AREAS), "open_areas": list(DG.OPEN), "resume": resume, "voluntary": True}

    # --- raporty ---
    def progress(self, pid: int) -> dict:
        pack = self.pack(pid)
        return {**PG.build(self.repo, pack, pid, self.now()), "growth": GR.build(self.repo, pack, pid, self.now()),
                "assessment": DG.profile(self.repo, pack, pid)}

    def weakspots(self, pid: int) -> dict:
        return WS.build(self.repo, self.pack(pid), pid, self.now())

    def review_observation(self, pid: int, observation_id: int, verdict: str) -> dict:
        """Uczeń kwestionuje korektę / oznacza błąd STT / przywraca. Historia zostaje."""
        from tutor.app import ingest
        try:
            ingest.review_observation(self.repo, self.pack(pid), pid, int(observation_id), verdict, self.now())
        except ValueError as e:
            raise ServiceError(f"Nie można zapisać: {e}") from e
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
        schema = {k: {kk: list(vv) if isinstance(vv, tuple) else vv for kk, vv in v.items() if kk != "column"}
                  for k, v in ST.SCHEMA.items()}
        schema["speed"]["presets"] = ST.SPEED_PRESETS
        return {"values": ST.effective(self.repo, pid), "schema": schema}

    def update_settings(self, pid: int, changes: dict) -> dict:
        try:
            return ST.update(self.repo, pid, changes)
        except ST.SettingError as e:
            raise ServiceError(str(e)) from e
