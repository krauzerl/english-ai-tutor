"""T-ISO + spójność własności na poziomie SQLite."""
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from tutor.store.db import student_tables


@pytest.fixture
def two(repo):
    a, b = repo.create_profile("A"), repo.create_profile("B")
    for pid, tag in ((a, "alpha"), (b, "bravo")):
        s = repo.start_session(pid, "lesson", 15)
        t = repo.add_turn(pid, s, "user", f"text-{tag}")
        repo.add_checkpoint(pid, s, t, f"cp-{tag}")
        repo.add_attempt(pid, "sk1", True, session_id=s, response=f"resp-{tag}")
        repo.upsert_skill_state(pid, "sk1", 0.5, 1)
        repo.log_error(pid, "tense", example=f"ex-{tag}", correction="c")
        repo.add_vocab(pid, "en", f"term-{tag}", "znaczenie")
        repo.put_session_summary(pid, "session", f"sum-{tag}", session_id=s)
        repo.put_session_summary(pid, "week", f"wk-{tag}", period_start="2026-11-16")
        repo.put_turn_meta(pid, s, t, "text", eval_status="evaluated", comm="ok", comm_quote=f"quote-{tag}")
        repo.add_observation(pid, s, t, "error", f"span-{tag}", category="tense", fix="f", severity=2,
                             confidence="h")
        repo.put_card(pid, "vocab", f"card-{tag}", "{}", "2026-12-01T00:00:00Z")
        repo.add_competence(pid, "grammar", "B1", 3.0, 0.4, 8, "diagnosis")
    return a, b


def _calls(repo, pid):
    return {
        "list_turns": lambda s: repo.list_turns(pid, s),
        "list_checkpoints": lambda s: repo.list_checkpoints(pid, s),
        "attempt_history": lambda s: repo.attempt_history(pid, "sk1"),
        "get_skill_state": lambda s: repo.get_skill_state(pid, "sk1"),
        "list_errors": lambda s: repo.list_errors(pid),
        "list_vocab": lambda s: repo.list_vocab(pid),
        "list_summaries": lambda s: repo.list_summaries(pid),
        "list_sessions": lambda s: repo.list_sessions(pid),
        "list_observations": lambda s: repo.list_observations(pid),
        "list_observations_session": lambda s: repo.list_observations(pid, s),
        "list_turn_meta": lambda s: repo.list_turn_meta(pid, s),
        "get_turn_meta": lambda s: repo.get_turn_meta(pid, repo.list_turns(pid2(pid), s)[0]["id"]
                                                      if repo.list_turns(pid2(pid), s) else 0),
        "list_skill_states": lambda s: repo.list_skill_states(pid),
        "get_card": lambda s: repo.get_card(pid, "vocab", "card-bravo"),
        "due_cards": lambda s: repo.due_cards(pid, "2027-01-01T00:00:00Z"),
        "list_competence": lambda s: repo.list_competence(pid),
    }


def pid2(pid):  # pomocnik: get_turn_meta pyta o turę innego profilu (nie może jej zobaczyć)
    return pid


def test_t_iso_1_repo_never_returns_other_profile(repo, two):
    a, b = two
    sess_b = repo.list_sessions(b)[0]["id"]
    for name, call in _calls(repo, a).items():
        out = repr(call(sess_b))
        assert "bravo" not in out and "term-bravo" not in out, name
    # sesja B przez profil A: pusto
    assert repo.list_turns(a, sess_b) == []
    assert repo.list_checkpoints(a, sess_b) == []


def test_t_iso_2_cascade_delete_all_tables(conn, repo, two):
    a, b = two
    # po jednym wierszu w tabelach nieobjętych metodami repo
    for pid in (a, b):
        conn.execute("INSERT INTO competence(profile_id,area,cefr,theta,se,n_items,source)"
                     " VALUES (?,?,?,?,?,?,?)", (pid, "grammar", "B1", 3.0, 0.4, 8, "diag"))
        conn.execute("INSERT INTO diagnosis_run(profile_id,state_json) VALUES (?,?)", (pid, "{}"))
        conn.execute("INSERT INTO srs_card(profile_id,card_type,ref_id,fsrs_json,due_at)"
                     " VALUES (?,?,?,?,?)", (pid, "word", "x", "{}", "2026-12-01"))
        conn.execute("INSERT INTO next_plan(profile_id,plan_json) VALUES (?,?)", (pid, "{}"))
        conn.execute("INSERT INTO llm_usage(profile_id,provider,model,role) VALUES (?,?,?,?)",
                     (pid, "ollama", "m", "conversation"))
    tables = student_tables(conn)
    assert {"attempt", "turn", "checkpoint", "session", "session_summary", "competence",
            "srs_card", "llm_usage", "observation", "turn_meta"} <= set(tables)

    def count(pid):
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t} WHERE profile_id=?", (pid,)
                                ).fetchone()[0] for t in tables}

    before_b = count(b)
    assert all(n > 0 for n in count(a).values()), count(a)
    repo.delete_profile(a)
    assert repo.get_profile(a) is None
    assert sum(count(a).values()) == 0
    assert count(b) == before_b
    # żadnych sierot (turn/checkpoint/attempt bez rodzica)
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_t_iso_3_export_contains_only_own_data(repo, two):
    a, b = two
    dump = repr(repo.export_profile(a))
    assert "alpha" in dump
    for tag in ("bravo", "text-bravo", "term-bravo", "cp-bravo", "sum-bravo", "wk-bravo"):
        assert tag not in dump


def test_export_integrity_roundtrip_json(repo, two):
    import json

    a, _ = two
    data = json.loads(json.dumps(repo.export_profile(a)))
    assert data["format_version"] == 1
    assert data["profile"]["id"] == a
    assert len(data["tables"]["turn"]) == 1
    assert data["tables"]["turn"][0]["text"] == "text-alpha"
    assert all(r["profile_id"] == a for rows in data["tables"].values() for r in rows)
    assert set(data["tables"]) == set(repo.student_tables())


# --- własność wymuszona przez SQLite, nie tylko filtr ---

def test_cross_profile_turn_rejected(repo, two):
    a, b = two
    sess_b = repo.list_sessions(b)[0]["id"]
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_turn(a, sess_b, "user", "intruz")


def test_cross_profile_attempt_checkpoint_summary_rejected(repo, two):
    a, b = two
    sess_b = repo.list_sessions(b)[0]["id"]
    turn_b = repo.list_turns(b, sess_b)[0]["id"]
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_attempt(a, "sk1", True, session_id=sess_b)
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_checkpoint(a, sess_b, turn_b, "x")
    with pytest.raises(sqlite3.IntegrityError):
        repo.put_session_summary(a, "session", "x", session_id=sess_b)
    # własna sesja A + tura B
    sess_a = repo.list_sessions(a)[0]["id"]
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_checkpoint(a, sess_a, turn_b, "x")


def test_raw_sql_cannot_reassign_owner(conn, repo, two):
    a, b = two
    sess_a = repo.list_sessions(a)[0]["id"]
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE session SET profile_id=? WHERE id=?", (b, sess_a))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("UPDATE turn SET profile_id=? WHERE session_id=?", (b, sess_a))


# --- session_summary: klucz ---

def test_summary_keys(repo, two):
    a, _ = two
    sess_a = repo.list_sessions(a)[0]["id"]
    # kilka tygodni, jeden profil: OK
    repo.put_session_summary(a, "week", "w2", period_start="2026-11-23")
    # duplikat tygodnia / sesji: odrzucony
    with pytest.raises(sqlite3.IntegrityError):
        repo.put_session_summary(a, "week", "dup", period_start="2026-11-23")
    with pytest.raises(sqlite3.IntegrityError):
        repo.put_session_summary(a, "session", "dup", session_id=sess_a)
    # poziom week bez period_start / session z period_start: odrzucone
    with pytest.raises(sqlite3.IntegrityError):
        repo.put_session_summary(a, "week", "x")
    with pytest.raises(sqlite3.IntegrityError):
        repo.put_session_summary(a, "session", "x", session_id=sess_a, period_start="2026-11-16")


# --- historia prób w różnych dniach ---

def test_attempt_history_across_days(repo, two):
    a, b = two
    base = datetime(2026, 11, 1, 10, tzinfo=UTC)
    for d in range(3):
        ts = (base + timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        repo.add_attempt(a, "sk2", d > 0, score=0.9, created_at=ts)
        repo.add_attempt(a, "sk2", True, score=0.95, created_at=ts)  # 2 próby tego samego dnia
    h = repo.attempt_history(a, "sk2")
    assert len(h) == 6
    assert [x["created_at"] for x in h] == sorted(x["created_at"] for x in h)
    assert repo.attempt_days(a, "sk2") == ["2026-11-01", "2026-11-02", "2026-11-03"]
    assert repo.attempt_days(b, "sk2") == []


def test_iso_new_tables_other_profile_invisible(repo, two):
    a, b = two
    sess_b = repo.list_sessions(b)[0]["id"]
    turn_b = repo.list_turns(b, sess_b)[0]["id"]
    assert repo.get_turn_meta(a, turn_b) is None
    assert repo.list_turn_meta(a, sess_b) == []
    assert repo.list_observations(a, sess_b) == []
    assert repo.get_card(a, "vocab", "card-bravo") is None
    assert all("bravo" not in repr(x) for x in (repo.list_observations(a), repo.due_cards(a, "2999-01-01T00:00:00Z")))


def test_cross_profile_observation_and_turn_meta_rejected(repo, two):
    a, b = two
    sess_b = repo.list_sessions(b)[0]["id"]
    turn_b = repo.list_turns(b, sess_b)[0]["id"]
    with pytest.raises(sqlite3.IntegrityError):
        repo.add_observation(a, sess_b, turn_b, "error", "x")
    with pytest.raises(sqlite3.IntegrityError):
        repo.put_turn_meta(a, sess_b, turn_b, "text")
