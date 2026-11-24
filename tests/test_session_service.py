"""F5.4: SessionService — kolejka oceny ↔ cykl aktywności rozmowy (wątek roboczy)."""
import sqlite3
import threading
from datetime import UTC, datetime

import pytest

from tests.test_eval_runner import GOAL, Prov, structured
from tutor.app.eval_runner import make_queue
from tutor.app.session_service import SessionService
from tutor.pedagogy import content as C
from tutor.store.db import open_db
from tutor.store.repo import Repo

NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)
T = 5     # s: limit oczekiwania w testach wątkowych


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


class Blocking(Prov):
    """Pierwsze wywołanie czeka na zwolnienie (symuluje trwającą ocenę)."""
    def __init__(self):
        super().__init__()
        self.entered, self.release, self.first = threading.Event(), threading.Event(), True

    def chat(self, messages, **kw):
        if self.first:
            self.first = False
            self.entered.set()
            assert self.release.wait(T)
        return super().chat(messages, **kw)


class Box:
    def __init__(self, path):
        self.path, self.conn, self.svcs = path, None, []
        self.restart()

    def restart(self):
        for s in self.svcs:
            s.close()
        if self.conn:
            self.conn.close()
        self.conn = open_db(self.path)
        self.repo = Repo(self.conn)
        return self.repo

    def svc(self, pack, pid, sid, prov=None):
        prov = prov or Prov()

        def qf(wrepo):
            return make_queue(wrepo, pack, prov, structured, profile_id=pid, session_id=sid,
                              goals={GOAL: "past simple"}, clock=lambda: NOW)
        s = SessionService(self.repo, lambda: Repo(open_db(self.path)), qf, pid, sid)
        self.svcs.append(s)
        return s


@pytest.fixture
def box(tmp_path):
    b = Box(tmp_path / "t.db")
    pid = b.repo.create_profile("P")
    b.pid, b.sid = pid, b.repo.start_session(pid, "chat")
    yield b
    for s in b.svcs:
        s.close()
    b.conn.close()


def test_evaluates_automatically_when_conversation_idle(box, pack):
    s = box.svc(pack, box.pid, box.sid)
    s.start()
    s.user_turn("I goed home")
    s.tutor_done()
    assert s.wait_idle(T)
    assert box.repo.list_turn_meta(box.pid, box.sid)[0]["applied_at"]


def test_no_evaluation_while_conversation_active(box, pack):
    prov = Prov()
    s = box.svc(pack, box.pid, box.sid, prov)
    s.start()
    s.user_turn("I goed home")                                     # rozmowa trwa: brak tutor_done
    assert s.wait_idle(T) and prov.calls == []
    assert box.repo.list_turn_meta(box.pid, box.sid) == []
    s.tutor_done()
    assert s.wait_idle(T) and len(prov.calls) == 1


def test_new_turn_cancels_running_eval_then_evaluates_once(box, pack):
    prov = Blocking()
    s = box.svc(pack, box.pid, box.sid, prov)
    s.start()
    s.user_turn("I goed home"); s.tutor_done()
    assert prov.entered.wait(T)                                    # ocena w toku
    s.user_turn("And I runned")                                    # uczeń wznawia rozmowę ⇒ anulowanie
    prov.release.set()
    assert s.wait_idle(T)
    assert box.repo.list_turn_meta(box.pid, box.sid) == []         # wynik przerwanej oceny odrzucony
    s.tutor_done()
    assert s.wait_idle(T)
    meta = box.repo.list_turn_meta(box.pid, box.sid)
    assert len(meta) == 2 and all(m["applied_at"] for m in meta)
    assert len(box.repo.list_observations(box.pid)) == 2           # bez duplikatów


def test_restart_restores_and_evaluates_automatically(box, pack):
    s = box.svc(pack, box.pid, box.sid)
    s.user_turn("I goed home")                                     # zapisane, nigdy nieocenione (awaria)
    repo = box.restart()
    s2 = box.svc(pack, box.pid, box.sid)
    s2.start()
    assert s2.wait_idle(T)
    assert repo.list_turn_meta(box.pid, box.sid)[0]["applied_at"]
    obs = repo.list_observations(box.pid)
    repo = box.restart()                                           # kolejny restart: bez duplikacji
    s3 = box.svc(pack, box.pid, box.sid)
    s3.start(); assert s3.wait_idle(T)
    assert repo.list_observations(box.pid) == obs


def test_dropped_not_reevaluated_automatically(box, pack):
    s = box.svc(pack, box.pid, box.sid, Prov(fail=99))
    s.start()
    s.user_turn("I goed home")
    for _ in range(3):
        s.tutor_done(); assert s.wait_idle(T)
    assert len(box.repo.list_dropped(box.pid, box.sid)) == 1
    prov = Prov()
    repo = box.restart()
    s2 = box.svc(pack, box.pid, box.sid, prov)
    s2.start(); s2.tutor_done(); assert s2.wait_idle(T)
    assert prov.calls == [] and len(repo.list_dropped(box.pid, box.sid)) == 1


def test_model_error_keeps_turn_and_service_alive(box, pack):
    s = box.svc(pack, box.pid, box.sid, Prov(fail=2))
    s.start()
    tid = s.user_turn("I goed home")
    s.tutor_done(); assert s.wait_idle(T)
    assert box.repo.list_turn_meta(box.pid, box.sid) == []
    assert box.repo.list_turns(box.pid, box.sid)[0]["id"] == tid   # tekst zachowany
    s.tutor_done(); assert s.wait_idle(T)                          # kolejna próba, usługa żyje
    s.tutor_done(); assert s.wait_idle(T)
    assert box.repo.list_turn_meta(box.pid, box.sid)[0]["applied_at"]


def test_apply_exception_does_not_kill_worker(box, pack, monkeypatch):
    from tutor.app import ingest
    s = box.svc(pack, box.pid, box.sid)
    s.start()
    s.user_turn("I goed home")
    monkeypatch.setattr(ingest, "_recompute_errors", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    s.tutor_done(); assert s.wait_idle(T)
    assert isinstance(s.last_error, RuntimeError) and box.repo.list_turn_meta(box.pid, box.sid) == []
    monkeypatch.undo()
    s.tutor_done(); assert s.wait_idle(T)
    assert box.repo.list_turn_meta(box.pid, box.sid)[0]["applied_at"]


def test_voice_turn_without_stt_probs_is_never_evaluated_as_text(box, pack):
    prov = Prov()
    s = box.svc(pack, box.pid, box.sid, prov)
    s.start()
    tid = s.user_turn("I goed home", input_mode="voice")           # brak low_probs (brak transcribe_detailed)
    s.tutor_done(); assert s.wait_idle(T)
    assert prov.calls == [] and box.repo.get_turn_meta(box.pid, tid) is None
    repo = box.restart()
    assert repo.list_pending_turns(box.pid, box.sid) == []         # restart też go nie odtwarza
    s2 = box.svc(pack, box.pid, box.sid, prov)
    s2.start(); s2.tutor_done(); assert s2.wait_idle(T) and prov.calls == []
    assert repo.list_turns(box.pid, box.sid)[0]["input_mode"] == "voice"


def test_voice_turn_with_stt_probs_is_evaluated_in_voice_mode(box, pack):
    s = box.svc(pack, box.pid, box.sid)
    s.start()
    tid = s.user_turn("I goed home", input_mode="voice", low_probs=[])
    s.tutor_done(); assert s.wait_idle(T)
    assert box.repo.get_turn_meta(box.pid, tid)["input_mode"] == "voice"


def test_profile_isolation(box, pack):
    other = box.repo.create_profile("Q")
    osid = box.repo.start_session(other, "chat")
    box.repo.add_turn(other, osid, "user", "I goed home")
    prov = Prov()
    s = box.svc(pack, box.pid, box.sid, prov)
    s.start(); s.tutor_done(); assert s.wait_idle(T)
    assert prov.calls == [] and box.repo.list_turn_meta(other, osid) == []
    with pytest.raises(sqlite3.IntegrityError):
        box.svc(pack, other, box.sid).user_turn("intruz")    # cudza sesja


def test_gate_closed(box, pack):
    s = box.svc(pack, box.pid, box.sid)
    s.start(); s.user_turn("I goed home"); s.tutor_done(); assert s.wait_idle(T)
    assert box.repo.attempt_history(box.pid, GOAL) == [] and box.repo.get_skill_state(box.pid, GOAL) is None
    assert len(box.repo.list_observations(box.pid)) == 1
