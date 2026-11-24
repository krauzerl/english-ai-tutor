"""F5.6: CLI (`main.py --voice`) → SQLite → SessionService → EvalQueue → ocena → zapis. Prawdziwa baza SQLite, atrapy modeli."""
import threading
import time

import pytest

from tests.llm_fakes import FakeProvider
from tests.test_eval_runner import Prov
from tests.test_stt_detailed import DetailedSTT
from tests.voice_fakes import FakeMic, FakeSTT, FakeTTS, Lines, blocks, tone
from tutor.voice import audio as A
from tutor.voice.cli import run
from tutor.voice.stt import Transcript

T = 8


class EvalProv(Prov):
    def health(self):
        return True


class WaitLines(Lines):
    """Po wyczerpaniu linii czeka (≤ T s) aż `cond()` stanie się prawdą, potem zwraca 'q'."""

    def __init__(self, cond, *ls):
        super().__init__(*ls)
        self.cond = cond

    def get(self, block=True, timeout=None):
        try:
            return queue_get(self)
        except Exception:
            end = time.monotonic() + T
            while not self.cond() and time.monotonic() < end:
                time.sleep(0.02)
            return "q"


def queue_get(q):
    import queue
    return queue.Queue.get(q, timeout=0.05)


class Env:
    def __init__(self, repo, conn):
        self.repo, self.conn = repo, conn
        self.pid = repo.create_profile("ann")

    def turns(self, sid=None):
        out = []
        for s in self.repo.list_sessions(self.pid):
            if sid in (None, s["id"]):
                out += self.repo.list_turns(self.pid, s["id"])
        return out

    def users(self):
        return [t for t in self.turns() if t["role"] == "user"]

    def applied(self):
        return sum(1 for s in self.repo.list_sessions(self.pid)
                   for m in self.repo.list_turn_meta(self.pid, s["id"]) if m["applied_at"])

    def go(self, lines, argv=(), llm=None, ev=None, **kw):
        out = []
        code = run(["--voice", "--profile", "ann", *argv], llm=llm or FakeProvider(chunks=["Nice. ", "Go on."]),
                   eval_llm=ev, tts=FakeTTS(), lines=lines, out=out.append, db=self.conn, **kw)
        return code, out


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def test_text_conversation_end_to_end(env):
    ev = EvalProv()
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=ev)
    assert code == 0
    users = env.users()
    assert len(users) == 1 and users[0]["input_mode"] == "text"              # zapis dokładnie raz
    assert [t["role"] for t in env.turns()] == ["user", "assistant"]
    assert env.applied() == 1 and len(ev.calls) == 1                          # ocena poszła kolejką, jedna
    obs = env.repo.list_observations(env.pid)
    assert [o["kind"] for o in obs] == ["error"]
    s = env.repo.list_sessions(env.pid)[0]
    assert s["status"] == "ended" and s["ended_at"] and s["kind"] == "voice"


def test_voice_conversation_with_stt_probs(env):
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = DetailedSTT(Transcript("I goed home", ["goed"]))
    ev = EvalProv()
    code, _ = env.go(WaitLines(lambda: env.applied() >= 1, "", ""), ["--mode", "ptt"], mic=mic, stt=stt,
                     sink=A.SimSink(), ev=ev)
    u = env.users()
    assert code == 0 and len(u) == 1 and (u[0]["input_mode"], u[0]["low_prob_json"]) == ("voice", '["goed"]')
    assert [o["kind"] for o in env.repo.list_observations(env.pid)] == ["stt_suspect"]   # kryteria głosowe


def test_voice_without_stt_data_never_evaluated_as_text(env):
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    ev = EvalProv()
    env.go(Lines("", "", "q"), ["--mode", "ptt"], mic=mic, stt=FakeSTT("I goed home"), sink=A.SimSink(), ev=ev)
    time.sleep(0.3)
    u = env.users()
    assert len(u) == 1 and (u[0]["input_mode"], u[0]["low_prob_json"]) == ("voice", None)
    assert ev.calls == [] and env.repo.list_observations(env.pid) == [] and env.applied() == 0


class SlowConv(FakeProvider):
    """Podczas strumienia odpowiedzi tutora sprawdza, czy kolejka oceny milczy (rozmowa aktywna)."""

    def __init__(self, ev):
        super().__init__(chunks=["Nice. ", "Go on."])
        self.ev, self.seen = ev, []

    def stream(self, messages, **kw):
        base = super().stream(messages, **kw)
        orig = base._src

        def gen():
            time.sleep(0.4)                                                   # worker miałby czas wystartować
            self.seen.append(len(self.ev.calls))
            yield from orig
        base._src = gen()
        return base


def test_no_evaluation_while_tutor_is_replying(env):
    ev = EvalProv()
    conv = SlowConv(ev)
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], llm=conv, ev=ev)
    assert conv.seen == [0] and len(ev.calls) == 1                           # 0 ocen w trakcie, potem dokładnie 1


def test_ollama_eval_error_does_not_block_tutor(env):
    ev = EvalProv(fail=99)
    code, out = env.go(WaitLines(lambda: len(ev.calls) >= 1, "I goed home"), ["--no-audio"], ev=ev)
    assert code == 0
    assert [t["role"] for t in env.turns()] == ["user", "assistant"]         # odpowiedź tutora była
    assert env.applied() == 0 and env.repo.list_observations(env.pid) == []
    assert any("ocen" in o and "oczekuj" in o for o in out)                  # porażka widoczna, nie „sukces”


class Interrupt(Lines):
    """Po zadanych liniach: czeka aż turę zapisano i rzuca Ctrl+C."""

    def get(self, block=True, timeout=None):
        try:
            return super(Lines, self).get(timeout=0.05)
        except Exception:
            time.sleep(0.3)
            raise KeyboardInterrupt from None


def test_ctrl_c_pauses_session_and_restart_resumes_without_duplicates(env):
    ev1 = EvalProv(fail=99)                                                  # ocena nie zdąży/nie uda się
    code, _ = env.go(Interrupt("I goed home"), ["--no-audio"], ev=ev1)
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and s[0]["status"] == "paused" and s[0]["ended_at"] is None
    assert len(env.users()) == 1 and env.applied() == 0                      # wypowiedź zapisana, nieoceniona
    ev2 = EvalProv()
    out = env.go(WaitLines(lambda: env.applied() >= 1), ["--no-audio"], ev=ev2)[1]
    assert len(env.repo.list_sessions(env.pid)) == 1                         # ta sama sesja wznowiona
    assert any("Wznawiam" in o for o in out)
    assert len(env.users()) == 1 and env.applied() == 1 and len(ev2.calls) == 1
    assert len(env.repo.list_observations(env.pid)) == 1
    ev3 = EvalProv()                                                         # kolejny start: nowa sesja, bez ponownej oceny
    env.go(Lines("q"), ["--no-audio"], ev=ev3)
    time.sleep(0.3)
    assert ev3.calls == [] and len(env.repo.list_observations(env.pid)) == 1
    assert len(env.repo.list_sessions(env.pid)) == 2


def test_whisper_error_keeps_conversation_alive(env):
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = DetailedSTT(RuntimeError("whisper down"), Transcript("I went home", []))
    ev = EvalProv()
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, "", "", "", ""), ["--mode", "ptt"], mic=mic, stt=stt,
                       sink=A.SimSink(), ev=ev)
    assert code == 0 and any("rozpoznawania" in o for o in out)
    assert [u["text"] for u in env.users()] == ["I went home"] and env.applied() == 1


class Boom(FakeProvider):
    def __init__(self):
        super().__init__(chunks=["Fine. "])
        self.n = 0

    def stream(self, messages, **kw):
        self.n += 1
        if self.n == 1:
            raise RuntimeError("llm exploded")
        return super().stream(messages, **kw)


def test_exception_in_reply_does_not_leave_conversation_active(env):
    ev = EvalProv()
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, "I goed home", "I runned home"), ["--no-audio"],
                       llm=Boom(), ev=ev)
    assert code == 0 and any("błąd tutora" in o for o in out)
    assert len(env.users()) == 2 and env.applied() == 2                      # obie tury ocenione mimo wyjątku


def test_worker_close_does_not_wait_for_running_eval(env):
    ev = EvalProv()
    gate, started = threading.Event(), threading.Event()
    orig = ev.chat

    def hang(messages, **kw):
        started.set()
        gate.wait(T)
        return orig(messages, **kw)
    ev.chat = hang
    t0 = time.monotonic()
    code, _ = env.go(WaitLines(started.is_set, "I goed home"), ["--no-audio"], ev=ev)
    took = time.monotonic() - t0
    gate.set()
    assert code == 0 and took < 4                                           # zamknięcie nie czeka na ocenę
    assert env.applied() == 0 and len(env.users()) == 1                     # tura czeka na restart
    time.sleep(0.2)


def test_profile_isolation_and_gates_closed(env):
    other = env.repo.create_profile("bob")
    osid = env.repo.start_session(other, "voice")
    env.repo.add_turn(other, osid, "user", "I goed home")                    # cudza, oczekująca tura
    ev = EvalProv()
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=ev)
    assert env.repo.list_turn_meta(other, osid) == []                        # bob nietknięty
    assert env.repo.list_observations(other) == []
    goal = "en.gram.past_simple_regular"
    assert env.repo.attempt_history(env.pid, goal) == [] and env.repo.get_skill_state(env.pid, goal) is None
