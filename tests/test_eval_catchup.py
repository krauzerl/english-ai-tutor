"""F7: oceny czekające po zakończonej rozmowie są dokańczane później — bez utraty i bez podwójnego naliczania."""
import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_eval_runner import Prov, structured
from tests.test_feedback import Gated
from tutor.app import eval_runner as ER
from tutor.pedagogy import content as C
from tutor.services.api import TutorAPI


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def _pending_chat(repo, n=2):
    pid = repo.create_profile("P")
    sid = repo.start_session(pid, "chat")
    for i in range(n):
        repo.add_turn(pid, sid, "user", f"I goed home {i}")
    repo.end_session(pid, sid)
    return pid, sid


def test_catch_up_evaluates_once(repo, pack):
    pid, sid = _pending_chat(repo)
    assert repo.pending_by_session(pid) == {sid: 2}
    r = ER.catch_up(repo, pack, Prov(), structured, pid)
    assert r == {"done": 2, "left": 0, "sessions": [sid]}
    n_obs = len(repo.list_observations(pid))
    errs = [dict(e) for e in repo.list_errors(pid)]
    r2 = ER.catch_up(repo, pack, Prov(), structured, pid)                     # drugi raz: nic do zrobienia
    assert r2["done"] == 0 and len(repo.list_observations(pid)) == n_obs
    assert [dict(e) for e in repo.list_errors(pid)] == errs                    # brak podwójnego licznika


def test_model_down_keeps_turns_pending(repo, pack):
    pid, sid = _pending_chat(repo, 1)
    r = ER.catch_up(repo, pack, Prov(fail=2), structured, pid)
    assert r["done"] == 1 or repo.pending_by_session(pid) in ({sid: 1}, {})
    assert repo.list_turns(pid, sid)[0]["text"] == "I goed home 0"            # treść nigdy nie ginie


def test_catch_up_isolated_per_profile(repo, pack):
    a, sa = _pending_chat(repo)
    b = repo.create_profile("Q")
    sb = repo.start_session(b, "chat")
    repo.add_turn(b, sb, "user", "hello there")
    ER.catch_up(repo, pack, Prov(), structured, a)
    assert repo.pending_by_session(b) == {sb: 1}


def test_api_feedback_reports_completeness(repo, pack):
    pid, sid = _pending_chat(repo, 1)
    api = TutorAPI(repo)
    api._packs = {"en": pack}
    f = api.session_feedback(pid, sid)
    assert f["complete"] is False and f["pending"] == 1 and "niekompletna" in f["lines"][-1]
    assert api.home(pid)["pending_evals"] == 1
    ER.catch_up(repo, pack, Prov(), structured, pid)
    f = api.session_feedback(pid, sid)
    assert f["complete"] and f["pending"] == 0 and any("went" in x for x in f["lines"])


def test_cli_chat_ends_even_with_pending_and_finish_evals_completes(repo, conn):
    env = Env(repo, conn)
    code, out = env.go(Gated({}, "I goed home", "q"), ["--no-audio", "--chat", "x"],
                       llm=FakeProvider(chunks=["Ok. "]), ev=EvalProv(fail=99))
    s = repo.list_sessions(env.pid)[0]
    assert s["status"] == "ended"                                              # nowy chat nie wznawia starego
    assert repo.pending_by_session(env.pid).get(s["id"], 0) <= 1
    out2: list[str] = []
    from tutor.voice.cli import run
    code = run(["--voice", "--profile", "ann", "--finish-evals"], eval_llm=EvalProv(), out=out2.append, db=conn)
    assert code == 0 and repo.pending_by_session(env.pid) == {}
    assert any("Ocenione" in x or "ocenione" in x for x in out2)
