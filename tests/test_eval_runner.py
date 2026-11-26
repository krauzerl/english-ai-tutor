"""F5.2: EvalQueue ↔ turn_eval.evaluate_texts ↔ ingest.apply_turn_evaluation; trwały status dropped."""
import json
from datetime import UTC, datetime

import pytest

from tutor.app.eval_queue import MAX_TRIES, EvalQueue, Pending
from tutor.app.eval_runner import make_queue
from tutor.llm.base import CancelToken, LLMUnavailable, Reply, Usage
from tutor.pedagogy import content as C
from tutor.store.db import open_db
from tutor.store.repo import Repo

GOAL = "en.gram.past_simple_regular"
NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)
ERR = {"s": "goed", "f": "went", "k": "error", "c": "tense.past_simple", "v": 2, "p": "h"}


@pytest.fixture(scope="module")
def pack():
    return C.load("en")          # prawdziwa brama: trusted_categories == []


class Prov:
    """Dostawca zwracający JSON TurnEval dla każdej wypowiedzi w partii; zlicza wywołania."""
    name, model, external = "fake", "m", False

    def __init__(self, fail=0, cancel=None):
        self.calls, self.fail, self.cancel = [], fail, cancel

    def chat(self, messages, **kw):
        self.calls.append(messages)
        if self.cancel:
            self.cancel.set()                   # nowa tura ucznia w trakcie oceny
        if self.fail:
            self.fail -= 1
            raise LLMUnavailable("down")
        n = sum(1 for ln in messages[-1].content.splitlines() if ln[:1].isdigit() and ln[1:3] == ': ')
        u = [{"i": i, "o": [ERR], "t": [], "cm": "ok", "cq": "I goed"} for i in range(n)]
        return Reply(json.dumps({"u": u}), Usage(1, 1), "fake", "m")


def structured(provider, messages, model, **kw):
    return model.model_validate_json(provider.chat(messages, **kw).text)


@pytest.fixture
def env(tmp_path, pack):
    conn = open_db(tmp_path / "t.db")
    repo = Repo(conn)
    pid = repo.create_profile("P")
    sid = repo.start_session(pid, "chat")
    yield repo, pid, sid, tmp_path
    conn.close()


def turns(repo, pid, sid, n):
    return [Pending(repo.add_turn(pid, sid, "user", f"I goed home {i}"), f"I goed home {i}", "text")
            for i in range(n)]


def queue(env, pack, prov, **kw):
    repo, pid, sid, _ = env
    return make_queue(repo, pack, prov, structured, profile_id=pid, session_id=sid, goals={GOAL: "past simple"},
                      clock=lambda: NOW, **kw)


def test_integration_batches_and_persists_ledger(env, pack):
    repo, pid, sid, _ = env
    prov = Prov()
    q = queue(env, pack, prov, batch=5)                            # wsad jawnie (domyślnie 1 od B-lite)
    ps = turns(repo, pid, sid, 7)
    for p in ps:
        q.submit(p)
    assert q.drain(CancelToken()) == 7
    assert len(prov.calls) == 2                                    # 5 + 2
    meta = repo.list_turn_meta(pid, sid)
    assert len(meta) == 7 and all(m["eval_status"] == "evaluated" and m["applied_at"] for m in meta)
    assert len(repo.list_observations(pid)) == 7


def test_gate_stays_closed_no_mastery_change(env, pack):
    repo, pid, sid, _ = env
    q = queue(env, pack, Prov())
    for p in turns(repo, pid, sid, 2):
        q.submit(p)
    q.drain(CancelToken())
    assert repo.attempt_history(pid, GOAL) == [] and repo.get_skill_state(pid, GOAL) is None


def test_no_double_apply_on_resubmit(env, pack):
    repo, pid, sid, _ = env
    prov = Prov()
    q = queue(env, pack, prov)
    p = turns(repo, pid, sid, 1)[0]
    q.submit(p); q.drain(CancelToken())
    snap = (repo.list_observations(pid), repo.list_errors(pid), repo.list_turn_meta(pid, sid))
    q.submit(p); q.drain(CancelToken())                           # ta sama tura ponownie
    assert (repo.list_observations(pid), repo.list_errors(pid), repo.list_turn_meta(pid, sid)) == snap
    assert len(prov.calls) == 2                                    # model wołany ponownie, zapis nie dubluje


def test_no_eval_during_conversation(env, pack):
    repo, pid, sid, _ = env
    prov = Prov()
    q = queue(env, pack, prov)
    q.submit(turns(repo, pid, sid, 1)[0])
    assert q.drain(CancelToken(), conversation_active=lambda: True) == 0
    assert prov.calls == [] and repo.list_turn_meta(pid, sid) == []


def test_cancel_then_retry_applies_once(env, pack):
    repo, pid, sid, _ = env
    c = CancelToken()
    prov = Prov(cancel=c)
    q = queue(env, pack, prov)
    q.submit(turns(repo, pid, sid, 1)[0])
    assert q.drain(c) == 0 and repo.list_turn_meta(pid, sid) == [] and len(q) == 1
    prov.cancel = None
    assert q.drain(CancelToken()) == 1 and len(repo.list_observations(pid)) == 1


def test_model_error_requeues_not_unrated_then_recovers(env, pack):
    repo, pid, sid, _ = env
    q = queue(env, pack, Prov(fail=2))                             # structured: 1 wywołanie chat na próbę
    q.submit(turns(repo, pid, sid, 1)[0])
    assert q.drain(CancelToken()) == 0 and len(q) == 1             # tura NIE zapisana jako unrated
    assert repo.list_turn_meta(pid, sid) == [] and repo.list_dropped(pid, sid) == []
    q.drain(CancelToken())
    assert q.drain(CancelToken()) == 1
    assert repo.list_turn_meta(pid, sid)[0]["eval_status"] == "evaluated"


def test_dropped_persisted_survives_restart_and_text_kept(env, pack):
    repo, pid, sid, tmp = env
    q = queue(env, pack, Prov(fail=99))
    p = turns(repo, pid, sid, 1)[0]
    q.submit(p)
    for _ in range(MAX_TRIES):
        q.drain(CancelToken())
    assert q.dropped == [p.turn_id]
    repo.conn.close()
    conn2 = open_db(tmp / "t.db")                                  # „restart”
    repo2 = Repo(conn2)
    d = repo2.list_dropped(pid, sid)
    assert [x["turn_id"] for x in d] == [p.turn_id] and d[0]["dropped_at"]
    assert repo2.get_turn_meta(pid, p.turn_id)["eval_status"] == "unrated"
    assert repo2.conn.execute("SELECT text FROM turn WHERE id=?", (p.turn_id,)).fetchone()[0] == p.text
    conn2.close()


def test_resubmit_after_drop_starts_fresh_try_cycle_and_clears_flag(env, pack):
    repo, pid, sid, _ = env
    prov = Prov(fail=MAX_TRIES)                                    # tyle porażek, ile wywołań do porzucenia
    q = queue(env, pack, prov)
    p = turns(repo, pid, sid, 1)[0]
    q.submit(p)
    for _ in range(MAX_TRIES):
        q.drain(CancelToken())
    assert len(repo.list_dropped(pid, sid)) == 1
    q.submit(p)                                                    # nowy cykl; model już działa
    assert q.dropped == [] and q.drain(CancelToken()) == 1
    assert repo.list_dropped(pid, sid) == []
    assert repo.get_turn_meta(pid, p.turn_id)["applied_at"]


def test_dropped_never_overwrites_applied_turn(env, pack):
    repo, pid, sid, _ = env
    p = turns(repo, pid, sid, 1)[0]
    q = queue(env, pack, Prov())
    q.submit(p); q.drain(CancelToken())
    repo.mark_dropped(pid, sid, p.turn_id, "text", "2026-11-24T10:00:00Z")
    assert repo.list_dropped(pid, sid) == [] and repo.get_turn_meta(pid, p.turn_id)["eval_status"] == "evaluated"


def test_queue_unit_retry_counter_reset_on_resubmit():
    calls = []
    q = EvalQueue(lambda b: (_ for _ in ()).throw(RuntimeError()), lambda p, r: None, on_drop=calls.append)
    p = Pending(1, "t", "text")
    q.submit(p)
    for _ in range(MAX_TRIES):
        q.drain(CancelToken())
    assert calls == [p] and len(q) == 0
    q.submit(p)
    q.drain(CancelToken())
    assert len(q) == 1 and calls == [p]                            # nowy cykl: jedna porażka nie porzuca
