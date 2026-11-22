"""Repozytorium: każda metoda ucznia przyjmuje profile_id; własność dodatkowo wymusza SQLite."""
import json
import sqlite3
from contextlib import contextmanager

from tutor.store.db import student_tables


def _rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]


class Repo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def student_tables(self) -> list[str]:
        return student_tables(self.conn)

    @contextmanager
    def transaction(self):
        """Jedna atomowa jednostka pracy (połączenie jest w trybie autocommit)."""
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield
        except BaseException:
            self.conn.execute("ROLLBACK")
            raise
        self.conn.execute("COMMIT")

    # --- profile ---
    def create_profile(self, name: str, target_lang: str = "en", ui_lang: str = "pl",
                       daily_minutes: int = 30, correction_mode: str = "immediate",
                       correction_style: str = "summary") -> int:
        # correction_mode jest przestarzałe (nieczytane); styl domyślnie `summary` do czasu bramy jakości (F8)
        cur = self.conn.execute(
            "INSERT INTO profile(name,target_lang,ui_lang,daily_minutes,correction_mode,correction_style)"
            " VALUES (?,?,?,?,?,?)", (name.strip(), target_lang, ui_lang, daily_minutes,
                                      correction_mode, correction_style))
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
                    created_at: str | None = None, source: str = "practice", hint_level: int = 0,
                    dedupe_key: str | None = None) -> int | None:
        """Zwraca id; None, gdy `dedupe_key` już istnieje (ta sama próba nie liczy się dwa razy)."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO attempt(profile_id,skill_id,session_id,item_id,correct,score,response,"
            "feedback_json,created_at,source,hint_level,dedupe_key) VALUES (?,?,?,?,?,?,?,?,COALESCE(?,"
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')),?,?,?)",
            (profile_id, skill_id, session_id, item_id, int(correct), score, response,
             json.dumps(feedback) if feedback is not None else None, created_at, source, hint_level,
             dedupe_key))
        return cur.lastrowid if cur.rowcount else None

    def attempt_history(self, profile_id: int, skill_id: str) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM attempt WHERE profile_id=? AND skill_id=? ORDER BY created_at, id",
            (profile_id, skill_id)))

    def attempt_days(self, profile_id: int, skill_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT day FROM attempt WHERE profile_id=? AND skill_id=? ORDER BY day",
            (profile_id, skill_id))]

    def upsert_skill_state(self, profile_id: int, skill_id: str, p_mastery: float,
                           attempts: int, mastered_at: str | None = None, *, status: str = "new",
                           verify_due_at: str | None = None, verified_7d_at: str | None = None,
                           verified_30d_at: str | None = None, relapses: int = 0,
                           last_seen: str | None = None) -> None:
        self.conn.execute(
            "INSERT INTO skill_state(profile_id,skill_id,p_mastery,attempts,last_seen,mastered_at,status,"
            "verify_due_at,verified_7d_at,verified_30d_at,relapses)"
            " VALUES (?,?,?,?,COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')),?,?,?,?,?,?)"
            " ON CONFLICT(profile_id,skill_id) DO UPDATE SET p_mastery=excluded.p_mastery,"
            " attempts=excluded.attempts, last_seen=excluded.last_seen, mastered_at=excluded.mastered_at,"
            " status=excluded.status, verify_due_at=excluded.verify_due_at,"
            " verified_7d_at=excluded.verified_7d_at, verified_30d_at=excluded.verified_30d_at,"
            " relapses=excluded.relapses",
            (profile_id, skill_id, p_mastery, attempts, last_seen, mastered_at, status, verify_due_at,
             verified_7d_at, verified_30d_at, relapses))

    def list_skill_states(self, profile_id: int) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM skill_state WHERE profile_id=? ORDER BY skill_id", (profile_id,)))

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

    # --- użycie LLM (limity wspólne dla wszystkich profili; wiersze bez treści) ---
    def add_llm_usage(self, profile_id: int | None, provider: str, model: str, role: str,
                      in_tokens: int, out_tokens: int, latency_ms: int | None, cost_usd: float,
                      created_at: str | None = None) -> int:
        return self.conn.execute(
            "INSERT INTO llm_usage(profile_id,provider,model,role,in_tokens,out_tokens,latency_ms,"
            "cost_usd,created_at) VALUES (?,?,?,?,?,?,?,?,COALESCE(?,"
            "strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
            (profile_id, provider, model, role, in_tokens, out_tokens, latency_ms, cost_usd,
             created_at)).lastrowid

    def llm_cost_since(self, since_iso: str) -> float:
        return self.conn.execute(
            "SELECT COALESCE(SUM(cost_usd),0) FROM llm_usage WHERE created_at>=?",
            (since_iso,)).fetchone()[0]

    def settle_llm_usage(self, usage_id: int, in_tokens: int, out_tokens: int, latency_ms: int | None,
                         cost_usd: float) -> float:
        """Zamienia rezerwację na rzeczywiste zużycie; zwraca koszt rezerwacji."""
        old = self.conn.execute("SELECT cost_usd FROM llm_usage WHERE id=?", (usage_id,)).fetchone()[0]
        self.conn.execute(
            "UPDATE llm_usage SET in_tokens=?, out_tokens=?, latency_ms=?, cost_usd=? WHERE id=?",
            (in_tokens, out_tokens, latency_ms, cost_usd, usage_id))
        return old

    # --- obserwacje i meta tury (F4) ---
    def put_turn_meta(self, profile_id: int, session_id: int, turn_id: int, input_mode: str,
                      eval_status: str = "unrated", comm: str | None = None, comm_quote: str | None = None,
                      fluency: dict | None = None, low_prob_words: list | None = None,
                      model: str | None = None, prompt_version: str | None = None) -> None:
        """Upsert; nie zmienia `applied_at`. Cudza tura (inny profil/sesja) => IntegrityError, nie nadpisanie."""
        cur = self.conn.execute(
            "INSERT INTO turn_meta(turn_id,session_id,profile_id,input_mode,comm,comm_quote,fluency_json,"
            "low_prob_words,eval_status,model,prompt_version) VALUES (?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(turn_id) DO UPDATE SET input_mode=excluded.input_mode, comm=excluded.comm,"
            " comm_quote=excluded.comm_quote, fluency_json=excluded.fluency_json,"
            " low_prob_words=excluded.low_prob_words, eval_status=excluded.eval_status,"
            " model=excluded.model, prompt_version=excluded.prompt_version"
            " WHERE turn_meta.profile_id=excluded.profile_id AND turn_meta.session_id=excluded.session_id",
            (turn_id, session_id, profile_id, input_mode, comm, comm_quote,
             json.dumps(fluency) if fluency is not None else None,
             json.dumps(low_prob_words) if low_prob_words is not None else None, eval_status, model,
             prompt_version))
        if cur.rowcount == 0:
            raise sqlite3.IntegrityError("turn_meta należy do innego profilu lub sesji")

    def get_turn_meta(self, profile_id: int, turn_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM turn_meta WHERE profile_id=? AND turn_id=?",
                              (profile_id, turn_id)).fetchone()
        return dict(r) if r else None

    def list_turn_meta(self, profile_id: int, session_id: int) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM turn_meta WHERE profile_id=? AND session_id=? ORDER BY turn_id",
            (profile_id, session_id)))

    def mark_applied(self, profile_id: int, turn_id: int, now: str) -> None:
        self.conn.execute("UPDATE turn_meta SET applied_at=? WHERE profile_id=? AND turn_id=?",
                          (now, profile_id, turn_id))

    def add_observation(self, profile_id: int, session_id: int, turn_id: int, kind: str, span: str, *,
                        category: str | None = None, skill_id: str | None = None, fix: str | None = None,
                        severity: int | None = None, confidence: str | None = None, status: str = "valid",
                        drop_reason: str | None = None, model: str | None = None,
                        prompt_version: str | None = None, created_at: str | None = None) -> int | None:
        """None = identyczna obserwacja już istnieje (idempotencja)."""
        cur = self.conn.execute(
            "INSERT OR IGNORE INTO observation(profile_id,session_id,turn_id,kind,category,skill_id,span,fix,"
            "severity,confidence,status,drop_reason,model,prompt_version,created_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
            (profile_id, session_id, turn_id, kind, category, skill_id, span, fix, severity, confidence,
             status, drop_reason, model, prompt_version, created_at))
        return cur.lastrowid if cur.rowcount else None

    def list_observations(self, profile_id: int, session_id: int | None = None, since: str | None = None,
                          status: str | None = None) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM observation WHERE profile_id=? AND (? IS NULL OR session_id=?)"
            " AND (? IS NULL OR created_at>=?) AND (? IS NULL OR status=?) ORDER BY id",
            (profile_id, session_id, session_id, since, since, status, status)))

    # --- rejestr błędów ---
    def put_error_log(self, profile_id: int, category: str, skill_id: str | None, *, count: int, status: str,
                      severity_max: int, reopened: int, example: str | None, correction: str | None,
                      example_observation_id: int | None, first_seen: str, last_seen: str) -> None:
        """Stan pochodny: liczony z obserwacji, więc ponowne wywołanie nie dubluje (nadpisuje)."""
        r = self.conn.execute(
            "SELECT id FROM error_log WHERE profile_id=? AND category=? AND IFNULL(skill_id,'')=IFNULL(?,'')"
            " ORDER BY id LIMIT 1", (profile_id, category, skill_id)).fetchone()
        resolved = "strftime('%Y-%m-%dT%H:%M:%fZ','now')" if status == "resolved" else "NULL"
        vals = (count, status, severity_max, reopened, example, correction, example_observation_id,
                first_seen, last_seen)
        if r:
            self.conn.execute(
                "UPDATE error_log SET count=?,status=?,severity_max=?,reopened=?,example=?,correction=?,"
                f"example_observation_id=?,first_seen=?,last_seen=?,resolved_at={resolved} WHERE id=?",
                (*vals, r["id"]))
        else:
            self.conn.execute(
                "INSERT INTO error_log(count,status,severity_max,reopened,example,correction,"
                "example_observation_id,first_seen,last_seen,profile_id,category,skill_id,resolved_at)"
                f" VALUES (?,?,?,?,?,?,?,?,?,?,?,?,{resolved})", (*vals, profile_id, category, skill_id))

    # --- SRS, kompetencje, diagnoza, plan ---
    def get_card(self, profile_id: int, card_type: str, ref_id: str) -> dict | None:
        r = self.conn.execute("SELECT * FROM srs_card WHERE profile_id=? AND card_type=? AND ref_id=?",
                              (profile_id, card_type, ref_id)).fetchone()
        return dict(r) if r else None

    def put_card(self, profile_id: int, card_type: str, ref_id: str, fsrs_json: str, due_at: str) -> None:
        self.conn.execute(
            "INSERT INTO srs_card(profile_id,card_type,ref_id,fsrs_json,due_at) VALUES (?,?,?,?,?)"
            " ON CONFLICT(profile_id,card_type,ref_id) DO UPDATE SET fsrs_json=excluded.fsrs_json,"
            " due_at=excluded.due_at", (profile_id, card_type, ref_id, fsrs_json, due_at))

    def due_cards(self, profile_id: int, now_iso: str) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM srs_card WHERE profile_id=? AND due_at<=? ORDER BY due_at", (profile_id, now_iso)))

    def add_competence(self, profile_id: int, area: str, cefr: str, theta: float, se: float, n_items: int,
                       source: str, rationale: dict | None = None, measured_at: str | None = None) -> int:
        return self.conn.execute(
            "INSERT INTO competence(profile_id,area,cefr,theta,se,n_items,source,rationale,measured_at)"
            " VALUES (?,?,?,?,?,?,?,?,COALESCE(?,strftime('%Y-%m-%dT%H:%M:%fZ','now')))",
            (profile_id, area, cefr, theta, se, n_items, source,
             json.dumps(rationale) if rationale is not None else None, measured_at)).lastrowid

    def list_competence(self, profile_id: int, area: str | None = None) -> list[dict]:
        return _rows(self.conn.execute(
            "SELECT * FROM competence WHERE profile_id=? AND (? IS NULL OR area=?) ORDER BY measured_at, id",
            (profile_id, area, area)))

    def start_diagnosis_run(self, profile_id: int, state: dict) -> int:
        return self.conn.execute("INSERT INTO diagnosis_run(profile_id,state_json) VALUES (?,?)",
                                 (profile_id, json.dumps(state))).lastrowid

    def save_diagnosis_run(self, profile_id: int, run_id: int, state: dict, finished_at: str | None = None) -> None:
        self.conn.execute("UPDATE diagnosis_run SET state_json=?, finished_at=? WHERE id=? AND profile_id=?",
                          (json.dumps(state), finished_at, run_id, profile_id))

    def get_diagnosis_run(self, profile_id: int, run_id: int) -> dict | None:
        r = self.conn.execute("SELECT * FROM diagnosis_run WHERE id=? AND profile_id=?",
                              (run_id, profile_id)).fetchone()
        if not r:
            return None
        d = dict(r)
        d["state"] = json.loads(d["state_json"])
        return d

    def put_next_plan(self, profile_id: int, plan: dict) -> None:
        self.conn.execute(
            "INSERT INTO next_plan(profile_id,plan_json) VALUES (?,?) ON CONFLICT(profile_id) DO UPDATE SET"
            " plan_json=excluded.plan_json, created_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')",
            (profile_id, json.dumps(plan)))

    def get_next_plan(self, profile_id: int) -> dict | None:
        r = self.conn.execute("SELECT plan_json FROM next_plan WHERE profile_id=?", (profile_id,)).fetchone()
        return json.loads(r[0]) if r else None

    def set_session_plan(self, profile_id: int, session_id: int, plan: dict) -> None:
        self.conn.execute("UPDATE session SET plan_json=? WHERE id=? AND profile_id=?",
                          (json.dumps(plan), session_id, profile_id))

    def get_session_plan(self, profile_id: int, session_id: int) -> dict:
        r = self.conn.execute("SELECT plan_json FROM session WHERE id=? AND profile_id=?",
                              (session_id, profile_id)).fetchone()
        return json.loads(r[0]) if r and r[0] else {}
