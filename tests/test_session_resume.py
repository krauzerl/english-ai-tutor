"""F5.3: trwałość sesji, wznowienie, odtwarzanie oczekujących ocen po restarcie."""
import sqlite3
from datetime import UTC, datetime

import pytest

from tests.test_eval_runner import GOAL, Prov, structured
from tutor.app import ingest
from tutor.app.eval_queue import MAX_TRIES
from tutor.app.eval_runner import make_queue, restore_pending
from tutor.llm.base import CancelToken
from tutor.pedagogy import content as C
from tutor.store.db import MIGRATIONS_DIR, open_db
from tutor.store.repo import Repo

NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


class Box:
    """Plik bazy + „restart” = nowe połączenie."""
    def __init__(self, path):
        self.path, self.conn = path, None
        self.restart()

    def restart(self):
        if self.conn:
            self.conn.close()
        self.conn = open_db(self.path)
        self.repo = Repo(self.conn)
        return self.repo


@pytest.fixture
def box(tmp_path):
    b = Box(tmp_path / "t.db")
    yield b
    b.conn.close()


def queue(box, pack, pid, sid, prov=None):
    return make_queue(box.repo, pack, prov or Prov(), structured, profile_id=pid, session_id=sid,
                      goals={GOAL: "past simple"}, clock=lambda: NOW)


def test_session_status_lifecycle_and_resume(box):
    r = box.repo
    pid = r.create_profile("P")
    sid = r.start_session(pid, "chat")
    assert r.get_session(pid, sid)["status"] == "active"
    assert r.pause_session(pid, sid) and r.get_session(pid, sid)["status"] == "paused"
    r = box.restart()                                              # restart aplikacji
    assert r.find_open_session(pid)["id"] == sid                   # ten sam trwały identyfikator
    assert r.resume_session(pid, sid) and r.get_session(pid, sid)["status"] == "active"
    r.end_session(pid, sid)
    s = r.get_session(pid, sid)
    assert s["status"] == "ended" and s["ended_at"]
    assert r.find_open_session(pid) is None
    assert not r.resume_session(pid, sid) and not r.pause_session(pid, sid)   # zakończona nie wraca


def test_open_session_is_latest_unended(box):
    r = box.repo
    pid = r.create_profile("P")
    a = r.start_session(pid, "chat"); r.end_session(pid, a)
    b = r.start_session(pid, "chat")
    assert r.find_open_session(pid)["id"] == b


def test_pending_restored_after_restart_and_applied_once(box, pack):
    r = box.repo
    pid = r.create_profile("P"); sid = r.start_session(pid, "chat")
    t = [r.add_turn(pid, sid, "user", f"I goed home {i}") for i in range(3)]
    r.add_turn(pid, sid, "assistant", "Nice! Tell me more.")       # tura tutora nie jest oceniana
    r = box.restart()                                              # awaria przed oceną
    q = queue(box, pack, pid, sid)
    assert restore_pending(r, q, pid, sid) == 3 and len(q) == 3
    assert q.drain(CancelToken()) == 3
    obs = r.list_observations(pid)
    for _ in range(3):                                             # wielokrotny restart po ocenie
        r = box.restart()
        q = queue(box, pack, pid, sid)
        assert restore_pending(r, q, pid, sid) == 0 and q.drain(CancelToken()) == 0
    assert r.list_observations(pid) == obs and {m["turn_id"] for m in r.list_turn_meta(pid, sid)} == set(t)


def test_restore_is_idempotent_no_duplicates_in_queue(box, pack):
    r = box.repo
    pid = r.create_profile("P"); sid = r.start_session(pid, "chat")
    r.add_turn(pid, sid, "user", "I goed home")
    q = queue(box, pack, pid, sid)
    assert restore_pending(r, q, pid, sid) == 1
    assert restore_pending(r, q, pid, sid) == 0 and len(q) == 1


def test_dropped_not_restored_but_preserved(box, pack):
    r = box.repo
    pid = r.create_profile("P"); sid = r.start_session(pid, "chat")
    tid = r.add_turn(pid, sid, "user", "I goed home")
    q = queue(box, pack, pid, sid, Prov(fail=99))
    restore_pending(r, q, pid, sid)
    for _ in range(MAX_TRIES):
        q.drain(CancelToken())
    r = box.restart()
    q2 = queue(box, pack, pid, sid)
    assert restore_pending(r, q2, pid, sid) == 0 and len(q2) == 0   # nie wraca automatycznie
    assert [d["turn_id"] for d in r.list_dropped(pid, sid)] == [tid]  # ale ślad został


def test_crash_during_apply_leaves_turn_pending(box, pack, monkeypatch):
    r = box.repo
    pid = r.create_profile("P"); sid = r.start_session(pid, "chat")
    tid = r.add_turn(pid, sid, "user", "I goed home")
    q = queue(box, pack, pid, sid)
    restore_pending(r, q, pid, sid)
    monkeypatch.setattr(ingest, "_recompute_errors", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        q.drain(CancelToken())                                     # awaria w trakcie zapisu: transakcja wycofana
    monkeypatch.undo()
    r = box.restart()
    assert r.list_turn_meta(pid, sid) == [] and r.list_observations(pid) == []
    q2 = queue(box, pack, pid, sid)
    assert restore_pending(r, q2, pid, sid) == 1 and q2.drain(CancelToken()) == 1
    assert r.get_turn_meta(pid, tid)["applied_at"]


def test_voice_mode_and_low_probs_survive_restart(box, pack):
    r = box.repo
    pid = r.create_profile("P"); sid = r.start_session(pid, "chat")
    r.add_turn(pid, sid, "user", "I goed home", input_mode="voice", low_probs=["goed"])
    r = box.restart()
    items = r.list_pending_turns(pid, sid)
    assert items[0]["input_mode"] == "voice" and items[0]["low_probs"] == ["goed"]


def test_no_eval_during_active_conversation_after_restore(box, pack):
    r = box.repo
    pid = r.create_profile("P"); sid = r.start_session(pid, "chat")
    r.add_turn(pid, sid, "user", "I goed home")
    prov = Prov()
    q = queue(box, pack, pid, sid, prov)
    restore_pending(r, q, pid, sid)
    assert q.drain(CancelToken(), conversation_active=lambda: True) == 0 and prov.calls == []
    assert q.drain(CancelToken()) == 1


def test_profile_isolation(box, pack):
    r = box.repo
    a = r.create_profile("A"); b = r.create_profile("B")
    sa = r.start_session(a, "chat"); sb = r.start_session(b, "chat")
    r.add_turn(a, sa, "user", "I goed home")
    assert r.list_pending_turns(b, sa) == [] and r.list_pending_turns(a, sb) == []
    assert r.get_session(b, sa) is None
    assert not r.pause_session(b, sa) and not r.resume_session(b, sa)
    r.end_session(b, sa)                                           # cudza sesja: no-op
    assert r.get_session(a, sa)["status"] == "active" and r.find_open_session(b)["id"] == sb
    q = queue(box, pack, b, sb)
    assert restore_pending(r, q, b, sa) == 0                       # profil B nie odtworzy tur profilu A


def test_gate_closed_after_restore(box, pack):
    r = box.repo
    pid = r.create_profile("P"); sid = r.start_session(pid, "chat")
    r.add_turn(pid, sid, "user", "I goed home")
    r = box.restart()
    q = queue(box, pack, pid, sid)
    restore_pending(r, q, pid, sid); q.drain(CancelToken())
    assert r.attempt_history(pid, GOAL) == [] and r.get_skill_state(pid, GOAL) is None
    assert len(r.list_observations(pid)) == 1                      # sugestia zapisana, mastery bez zmian


def test_migration_006_backfills_status_and_checks_values(tmp_path):
    old = tmp_path / "mig"
    old.mkdir()
    for f in MIGRATIONS_DIR.glob("00[1-5]_*.sql"):
        (old / f.name).write_text(f.read_text())
    p = tmp_path / "m.db"
    c = open_db(p, old)                                            # baza sprzed F5.3
    pid = Repo(c).create_profile("P")
    c.execute("INSERT INTO session(profile_id,kind,ended_at) VALUES (?,?,?)", (pid, "chat", "2026-01-01T00:00:00Z"))
    c.execute("INSERT INTO session(profile_id,kind) VALUES (?,?)", (pid, "chat"))
    c.close()
    c = open_db(p)
    assert [r[0] for r in c.execute("SELECT status FROM session ORDER BY id")] == ["ended", "active"]
    with pytest.raises(sqlite3.IntegrityError):
        c.execute("UPDATE session SET status='bogus'")
    c.close()
