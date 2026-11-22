"""Repozytorium: każda metoda ucznia przyjmuje profile_id; własność dodatkowo wymusza SQLite."""
import json
import sqlite3

from tutor.store.db import student_tables


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


class Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def student_tables(self) -> list[str]:
        return student_tables(self.conn)

    # --- profile ---
    def create_profile(self, name: str, target_lang: str = "en", ui_lang: str = "pl",
                       daily_minutes: int = 30, correction_mode: str = "immediate") -> int:
        cur = self.conn.execute(
            "INSERT INTO profile(name,target_lang,ui_lang,daily_minutes,correction_mode)"
            " VALUES (?,?,?,?,?)", (name.strip(), target_lang, ui_lang, daily_minutes,
                                    correction_mode))
        return cur.lastrowid

    def list_profiles(self) -> list[dict]:
        return _rows(self.conn.execute("SELECT * FROM profile ORDER BY id"))

    def get_profile(self, profile_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM profile WHERE id=?", (profile_id,)).fetchone()
        return dict(r) if r else None

    def find_profile(self, name_or_id: str) -> dict | None:
        if str(name_or_id).isdigit():
            return self.get_profile(int(name_or_id))
        r = self.conn.execute("SELECT * FROM profile WHERE name=?", (name_or_id,)).fetchone()
        return dict(r) if r else None

    def set_consent(self, profile_id: int, granted: bool) -> None:
        self.conn.execute(
            "UPDATE profile SET external_api_consent_at="
            "CASE WHEN ? THEN strftime('%Y-%m-%dT%H:%M:%fZ','now') END WHERE id=?",
            (int(granted), profile_id))

    def delete_profile(self, profile_id: int) -> None:
        """Kaskada FK usuwa dane ucznia (audio: brak; F7 doda usuwanie plików)."""
        self.conn.execute("DELETE FROM profile WHERE id=?", (profile_id,))

    def export_profile(self, profile_id: int) -> dict:
        profile = self.get_profile(profile_id)
        if profile is None:
            raise KeyError(profile_id)
        self.conn.execute("BEGIN")  # jeden spójny odczyt
        try:
            tables = {t: _rows(self.conn.execute(
                f"SELECT * FROM {t} WHERE profile_id=? ORDER BY 1", (profile_id,)))
                for t in self.student_tables()}
        finally:
            self.conn.execute("COMMIT")
        return {"format_version": 1, "profile": profile, "tables": tables}

    # --- sesje, tury, checkpointy ---
    def start_session(self, profile_id: int, kind: str, planned_minutes: int | None = None) -> int:
        return self.conn.execute(
            "INSERT INTO session(profile_id,kind,planned_minutes) VALUES (?,?,?)",
            (profile_id, kind, planned_minutes)).lastrowid

    def end_session(self, profile_id: int, session_id: int) -> None:
        self.conn.execute(
            "UPDATE session SET ended_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')"
            " WHERE id=? AND profile_id=?", (session_id, profile_id))

    def list_sessions(self, profile_id: int) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM session WHERE profile_id=? ORDER BY id", (profile_id,)))

    def add_turn(self, profile_id: int, session_id: int, role: str, text: str) -> int:
        return self.conn.execute(
            "INSERT INTO turn(session_id,profile_id,role,text) VALUES (?,?,?,?)",
            (session_id, profile_id, role, text)).lastrowid

    def list_turns(self, profile_id: int, session_id: int) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM turn WHERE profile_id=? AND session_id=? ORDER BY id",
            (profile_id, session_id)))

    def add_checkpoint(self, profile_id: int, session_id: int, upto_turn_id: int,
                       summary: str) -> int:
        return self.conn.execute(
            "INSERT INTO checkpoint(session_id,profile_id,upto_turn_id,summary) VALUES (?,?,?,?)",
            (session_id, profile_id, upto_turn_id, summary)).lastrowid

    def list_checkpoints(self, profile_id: int, session_id: int) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM checkpoint WHERE profile_id=? AND session_id=? ORDER BY id",
            (profile_id, session_id)))

    def put_session_summary(self, profile_id: int, level: str, summary: str,
                            session_id: int | None = None, period_start: str | None = None) -> int:
        return self.conn.execute(
            "INSERT INTO session_summary(profile_id,level,session_id,period_start,summary_json)"
            " VALUES (?,?,?,?,?)",
            (profile_id, level, session_id, period_start, json.dumps(summary))).lastrowid

    def list_summaries(self, profile_id: int, level: str | None = None) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM session_summary WHERE profile_id=? AND (? IS NULL OR level=?)"
            " ORDER BY id", (profile_id, level, level)))

    # --- próby i mastery ---
    def add_attempt(self, profile_id: int, skill_id: str, correct: bool, score: float | None = None,
                    session_id: int | None = None, item_id: str | None = None,
                    response: str | None = None, feedback: dict | None = None,
                    created_at: str | None = None) -> int:
        return self.conn.execute(
            "INSERT INTO attempt(profile_id,skill_id,session_id,item_id,correct,score,response,"
            "feedback_json,created_at) VALUES (?,?,?,?,?,?,?,?,COALESCE(?,"
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
            (profile_id, skill_id, session_id, item_id, int(correct), score, response,
             json.dumps(feedback) if feedback is not None else None, created_at)).lastrowid

    def attempt_history(self, profile_id: int, skill_id: str) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM attempt WHERE profile_id=? AND skill_id=? ORDER BY created_at, id",
            (profile_id, skill_id)))

    def attempt_days(self, profile_id: int, skill_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT day FROM attempt WHERE profile_id=? AND skill_id=? ORDER BY day",
            (profile_id, skill_id))]

    def upsert_skill_state(self, profile_id: int, skill_id: str, p_mastery: float,
                           attempts: int, mastered_at: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO skill_state(profile_id,skill_id,p_mastery,attempts,last_seen,mastered_at)"
            " VALUES (?,?,?,?,strftime('%Y-%m-%dT%H:%M:%fZ','now'),?)"
            " ON CONFLICT(profile_id,skill_id) DO UPDATE SET p_mastery=excluded.p_mastery,"
            " attempts=excluded.attempts, last_seen=excluded.last_seen,"
            " mastered_at=excluded.mastered_at",
            (profile_id, skill_id, p_mastery, attempts, mastered_at))

    def get_skill_state(self, profile_id: int, skill_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM skill_state WHERE profile_id=? AND skill_id=?",
                              (profile_id, skill_id)).fetchone()
        return dict(r) if r else None

    # --- błędy, słownictwo ---
    def log_error(self, profile_id: int, category: str, skill_id: str | None = None,
                  example: str | None = None, correction: str | None = None) -> int:
        return self.conn.execute(
            "INSERT INTO error_log(profile_id,category,skill_id,example,correction)"
            " VALUES (?,?,?,?,?)", (profile_id, category, skill_id, example, correction)).lastrowid

    def list_errors(self, profile_id: int) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM error_log WHERE profile_id=? ORDER BY id", (profile_id,)))

    def add_vocab(self, profile_id: int, lang: str, term: str, meaning_pl: str | None = None,
                  example: str | None = None, source: str | None = None) -> int:
        return self.conn.execute(
            "INSERT INTO vocab(profile_id,lang,term,meaning_pl,example,source)"
            " VALUES (?,?,?,?,?,?)",
            (profile_id, lang, term, meaning_pl, example, source)).lastrowid

    def list_vocab(self, profile_id: int) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM vocab WHERE profile_id=? ORDER BY id", (profile_id,)))
