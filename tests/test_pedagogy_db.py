"""T-DB-3: migracja 003 od v2 z danymi + idempotencja na poziomie bazy."""
import shutil
import sqlite3

import pytest

from tutor.store.db import LATEST_VERSION, MIGRATIONS_DIR, open_db, student_tables

OLD = ["profile", "skill_state", "competence", "diagnosis_run", "session", "turn", "checkpoint", "attempt",
       "error_log", "vocab", "srs_card", "session_summary", "next_plan", "llm_usage"]


@pytest.fixture
def v2db(tmp_path):
    d = tmp_path / "v2"
    d.mkdir()
    for f in sorted(MIGRATIONS_DIR.glob("00[12]_*.sql")):
        shutil.copy(f, d)
    c = open_db(tmp_path / "data" / "t.db", migrations_dir=d)
    ids = {}
    for name, mode in (("imm", "immediate"), ("sum", "summary")):
        pid = c.execute("INSERT INTO profile(name,correction_mode) VALUES (?,?)", (name, mode)).lastrowid
        ids[name] = pid
        s = c.execute("INSERT INTO session(profile_id,kind) VALUES (?,?)", (pid, "lesson")).lastrowid
        t = c.execute("INSERT INTO turn(session_id,profile_id,role,text) VALUES (?,?,?,?)", (s, pid, "user", "hi")).lastrowid
        c.execute("INSERT INTO checkpoint(session_id,profile_id,upto_turn_id,summary) VALUES (?,?,?,?)", (s, pid, t, "c"))
        c.execute("INSERT INTO attempt(profile_id,skill_id,session_id,correct) VALUES (?,?,?,1)", (pid, "sk", s))
        c.execute("INSERT INTO skill_state(profile_id,skill_id,p_mastery,attempts) VALUES (?,?,0.5,1)", (pid, "sk"))
        c.execute("INSERT INTO competence(profile_id,area,cefr,theta,se,n_items,source) VALUES (?,?,?,?,?,?,?)",
                  (pid, "grammar", "B1", 3, 0.4, 8, "diag"))
        c.execute("INSERT INTO diagnosis_run(profile_id) VALUES (?)", (pid,))
        c.execute("INSERT INTO error_log(profile_id,category) VALUES (?,?)", (pid, "tense"))
        c.execute("INSERT INTO vocab(profile_id,lang,term) VALUES (?,?,?)", (pid, "en", "w"))
        c.execute("INSERT INTO srs_card(profile_id,card_type,ref_id,fsrs_json,due_at) VALUES (?,?,?,?,?)",
                  (pid, "vocab", "w", "{}", "2026-12-01"))
        c.execute("INSERT INTO session_summary(profile_id,level,session_id,summary_json) VALUES (?,?,?,?)",
                  (pid, "session", s, "{}"))
        c.execute("INSERT INTO next_plan(profile_id,plan_json) VALUES (?,?)", (pid, "{}"))
    c.close()
    return tmp_path / "data" / "t.db", ids


def test_t_db_3_migration_003_from_v2_keeps_all_rows(v2db):
    path, ids = v2db
    raw = sqlite3.connect(path)
    before = {t: raw.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in OLD}
    raw.close()
    assert before["profile"] == 2 and before["attempt"] == 2
    c = open_db(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION >= 3
    after = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in OLD}
    assert after == before
    rows = {r["name"]: r for r in c.execute("SELECT * FROM profile")}
    # decyzja 2: brama jakości Bielika niespełniona → `summary` dla wszystkich (także dawnego `immediate`)
    assert rows["imm"]["correction_style"] == "summary" and rows["sum"]["correction_style"] == "summary"
    assert rows["imm"]["correction_mode"] == "immediate" and rows["imm"]["allow_unreviewed_practice"] == 1
    assert c.execute("SELECT status, relapses FROM skill_state").fetchone()[:] == ("new", 0)
    assert c.execute("SELECT source, hint_level, dedupe_key FROM attempt").fetchone()[:] == ("practice", 0, None)
    assert c.execute("PRAGMA foreign_key_check").fetchall() == []
    assert {"observation", "turn_meta"} <= set(student_tables(c))
    assert list((path.parent / "backups").glob("*.v2.*.bak"))
    c.close()


def test_t_db_3_fresh_db_default_style_summary(repo):
    pid = repo.create_profile("X")
    assert repo.get_profile(pid)["correction_style"] == "summary"
    with pytest.raises(sqlite3.IntegrityError):
        repo.conn.execute("UPDATE profile SET correction_style='bogus' WHERE id=?", (pid,))


@pytest.fixture
def turn(repo):
    pid = repo.create_profile("P")
    s = repo.start_session(pid, "chat")
    return pid, s, repo.add_turn(pid, s, "user", "I goed there")


def test_observation_and_attempt_dedupe(repo, turn):
    pid, s, t = turn
    first = repo.add_observation(pid, s, t, "error", "goed", category="morphology", severity=2, confidence="h")
    assert first and repo.add_observation(pid, s, t, "error", "goed", category="morphology") is None
    assert repo.add_observation(pid, s, t, "error", "goed", category="tense") is not None  # inna kategoria
    assert len(repo.list_observations(pid)) == 2
    a1 = repo.add_attempt(pid, "sk", False, source="conversation", dedupe_key=f"conv:{t}:sk")
    assert a1 and repo.add_attempt(pid, "sk", False, source="conversation", dedupe_key=f"conv:{t}:sk") is None
    assert len(repo.attempt_history(pid, "sk")) == 1
    repo.add_attempt(pid, "sk", True)  # bez klucza: wiele prób dozwolone (powtórki zadań)
    repo.add_attempt(pid, "sk", True)
    assert len(repo.attempt_history(pid, "sk")) == 3


def test_turn_meta_upsert_keeps_applied(repo, turn):
    pid, s, t = turn
    repo.put_turn_meta(pid, s, t, "text", eval_status="evaluated", comm="ok", comm_quote="I goed there")
    repo.mark_applied(pid, t, "2026-11-22T10:00:00Z")
    repo.put_turn_meta(pid, s, t, "text", eval_status="evaluated", comm="ok", comm_quote="I goed there")
    assert repo.get_turn_meta(pid, t)["applied_at"] == "2026-11-22T10:00:00Z"


def test_transaction_rolls_back(repo, turn):
    pid, s, t = turn
    with pytest.raises(RuntimeError), repo.transaction():
        repo.add_observation(pid, s, t, "error", "x")
        raise RuntimeError
    assert repo.list_observations(pid) == []
