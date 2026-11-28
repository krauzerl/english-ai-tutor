"""F5.7: aktywność rozmowy zaczyna się przed nagrywaniem (nie po zapisie tury) i kończy po każdym cyklu."""
import threading

import numpy as np
import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv, Interrupt, WaitLines
from tests.test_session_service import Blocking, Box, T
from tests.test_stt_detailed import DetailedSTT
from tests.voice_fakes import FakeMic, FakeTTS, Lines, blocks, tone
from tutor.pedagogy import content as C
from tutor.voice import audio as A
from tutor.voice.stt import Transcript

# --- SessionService ---


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def box(tmp_path):
    b = Box(tmp_path / "t.db")
    pid = b.repo.create_profile("P")
    b.pid, b.sid = pid, b.repo.start_session(pid, "voice")
    yield b
    for s in b.svcs:
        s.close()
    b.conn.close()


def test_begin_activity_cancels_running_eval_and_result_is_discarded(box, pack):
    prov = Blocking()
    s = box.svc(pack, box.pid, box.sid, prov)
    s.start()
    s.user_turn("I goed home"); s.tutor_done()
    assert prov.entered.wait(T)                                    # ocena w toku
    s.begin_activity()                                             # uczeń zaczyna mówić (jeszcze nie ma tury)
    prov.release.set()
    assert s.wait_idle(T)
    assert box.repo.list_turn_meta(box.pid, box.sid) == [] and s.pending == 1   # wynik odrzucony, tura czeka
    s.tutor_done()
    assert s.wait_idle(T)
    assert box.repo.list_turn_meta(box.pid, box.sid)[0]["applied_at"]
    assert len(box.repo.list_observations(box.pid)) == 1


def test_no_new_evaluation_while_activity_open(box, pack):
    prov = Blocking()
    prov.first = False
    s = box.svc(pack, box.pid, box.sid, prov)
    s.start(); assert s.wait_idle(T)
    s.begin_activity()
    s.user_turn("I goed home")
    for _ in range(3):
        s._kick(); assert s.wait_idle(T)                           # worker budzony wielokrotnie: milczy
    assert prov.calls == [] and s.pending == 1
    s.tutor_done(); assert s.wait_idle(T)
    assert len(prov.calls) == 1


def test_activity_released_after_cancelled_cycle(box, pack):
    prov = Blocking()
    prov.first = False
    s = box.svc(pack, box.pid, box.sid, prov)
    s.start()
    s.user_turn("I goed home")
    s.begin_activity()                                             # nagrywanie anulowane: brak nowej tury
    s.tutor_done(); assert s.wait_idle(T)                          # koniec cyklu zwalnia ocenę
    assert len(prov.calls) == 1 and box.repo.list_turn_meta(box.pid, box.sid)[0]["applied_at"]


def test_end_after_close_is_noop(box, pack):
    s = box.svc(pack, box.pid, box.sid)
    s.start(); s.close()
    s.begin_activity(); s.tutor_done()                             # nie rzuca, nie budzi martwego workera


# --- listen_auto ---
def test_listen_auto_signals_speech_start_and_noise():
    sil = np.zeros(A.MIC_SR // 2, np.float32)
    ev = []
    x = np.concatenate([sil, tone(0.8), np.zeros(A.MIC_SR, np.float32)])
    out = A.listen_auto(FakeMic(blocks(x)), A.Endpointer(), timeout=2, on_speech=lambda: ev.append("speech"),
                        on_noise=lambda: ev.append("noise"))
    assert out is not None and ev == ["speech"]                    # raz, przed zwróceniem nagrania
    ev.clear()
    click = np.concatenate([np.zeros(8000, np.float32), tone(0.1), np.zeros(2 * A.MIC_SR, np.float32)])
    assert A.listen_auto(FakeMic(blocks(click)), A.Endpointer(), timeout=0.5, on_speech=lambda: ev.append("speech"),
                         on_noise=lambda: ev.append("noise")) is None
    assert ev == ["speech", "noise"]                               # kliknięcie: aktywność zwolniona


# --- CLI ---
@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


class Spy(EvalProv):
    """Atrapa oceny: pierwsze wywołanie czeka na `gate`; zlicza i sygnalizuje zakończenie."""

    def __init__(self, **kw):
        super().__init__(**kw)
        self.gate, self.started, self.returned = threading.Event(), threading.Event(), threading.Event()
        self.first = True

    def chat(self, messages, **kw):
        if self.first:
            self.first = False
            self.started.set()
            assert self.gate.wait(T)
            try:
                return super().chat(messages, **kw)
            finally:
                self.returned.set()
        return super().chat(messages, **kw)


class Probe:
    """Odczyt stanu bazy z innego wątku (własne połączenie)."""

    def __init__(self, env):
        self.path = env.conn.execute("PRAGMA database_list").fetchone()[2]

    def applied(self):
        from tutor.store.db import open_db
        c = open_db(self.path)
        try:
            return c.execute("SELECT COUNT(*) FROM turn_meta WHERE applied_at IS NOT NULL").fetchone()[0]
        finally:
            c.close()


class StopReleases(WaitLines):
    """Skrypt linii PTT podawany na żądanie (nie w kolejce: wątek „Enter = przerwij” zjadłby wstępnie wpisane
    puste linie). Gdy uczeń kończy nagrywanie (druga pusta linia), zwalnia zablokowaną ocenę."""

    def __init__(self, spy, cond, *script):
        super().__init__(cond)
        self.spy, self.script, self.n = spy, list(script), 0

    def get(self, block=True, timeout=None):
        if not self.script:
            return super().get(block, timeout)
        v = self.script.pop(0)
        if v == "":
            self.n += 1
            if self.n == 1:
                assert self.spy.started.wait(T)                    # nagrywanie zaczyna się przy trwającej ocenie
            if self.n == 2:
                self.spy.gate.set()
        return v


def test_recording_cancels_running_eval_and_nothing_runs_until_reply_done(env, monkeypatch):
    from tutor.voice import cli as CLI
    monkeypatch.setattr(CLI, "_eval_wait", lambda: 0.0)        # bez czekania na ocenę przed odpowiedzią (eval_wait_s=0)
    spy, probe = Spy(), Probe(env)
    window = {}
    mic = FakeMic(loop=blocks(tone(0.1))[0])

    class Stt(DetailedSTT):
        def transcribe_detailed(self, audio):
            assert spy.returned.wait(T)                            # ocena z tury 1 już wróciła (w trakcie STT)
            window["stt"] = (probe.applied(), len(spy.calls))
            return super().transcribe_detailed(audio)

    class Conv(FakeProvider):
        def stream(self, messages, **kw):
            window.setdefault("gen", []).append((probe.applied(), len(spy.calls)))
            return super().stream(messages, **kw)

    # tura 1 (tekst) → ocena rusza i blokuje się; tura 2 (głos): Enter start, Enter stop
    lines = StopReleases(spy, lambda: env.applied() >= 2, "I goed home", "", "")
    env.go(lines, ["--mode", "ptt"], llm=Conv(chunks=["Nice. "]), ev=spy, mic=mic,
           stt=Stt(Transcript("I runned home", [])), sink=A.SimSink())
    assert window["stt"] == (0, 1)                                 # zwrócony wynik anulowanej oceny NIE został zapisany
    assert window["gen"][-1] == (0, 1)                             # ani nowa ocena nie wystartowała przed końcem odpowiedzi
    assert env.applied() == 2 and len(env.repo.list_observations(env.pid)) == 2
    assert [u["input_mode"] for u in env.users()] == ["text", "voice"]
    assert len(spy.calls) == 3                                     # odrzucona + po jednej ocenie na turę (batch=1)


def test_stt_error_releases_activity_and_eval_resumes(env):
    spy = Spy()
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    spy.gate.set()
    stt = DetailedSTT(RuntimeError("whisper down"))
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, "I goed home", "", "", ""), ["--mode", "ptt"],
                       ev=spy, mic=mic, stt=stt, sink=A.SimSink())
    assert code == 0 and any("rozpoznawania" in o for o in out)
    assert env.applied() == 1 and len(env.users()) == 1


def test_no_recognised_speech_releases_activity(env):
    spy = Spy()
    spy.gate.set()
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home", "", "", ""), ["--mode", "ptt"], ev=spy, mic=mic,
           stt=DetailedSTT(Transcript("", None)), sink=A.SimSink())
    assert env.applied() == 1 and len(env.users()) == 1


def test_recording_aborted_with_q_ends_session_cleanly(env):
    spy = Spy()
    spy.gate.set()
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    code, _ = env.go(Lines("", "q"), ["--mode", "ptt"], ev=spy, mic=mic, stt=DetailedSTT(), sink=A.SimSink())
    assert code == 0 and env.repo.list_sessions(env.pid)[0]["status"] == "ended" and env.users() == []


def test_tts_error_releases_activity_and_eval_resumes(env):
    spy = Spy()
    spy.gate.set()
    out = []
    from tutor.voice.cli import run
    code = run(["--voice", "--profile", "ann", "--no-audio"], llm=FakeProvider(chunks=["Nice. "]), eval_llm=spy,
               tts=FakeTTS(fail_on="Nice"), lines=WaitLines(lambda: env.applied() >= 1, "I goed home"),
               out=out.append, db=env.conn)
    assert code == 0 and env.applied() == 1 and len(env.users()) == 1


def test_ctrl_c_during_recording_then_restart_evaluates_once(env):
    spy1 = Spy(fail=99)
    spy1.gate.set()
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    env.go(Interrupt("I goed home", ""), ["--mode", "ptt"], ev=spy1, mic=mic, stt=DetailedSTT(), sink=A.SimSink())
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and s[0]["status"] == "paused" and len(env.users()) == 1 and env.applied() == 0
    spy2 = Spy()
    spy2.gate.set()
    env.go(WaitLines(lambda: env.applied() >= 1), ["--no-audio"], ev=spy2)
    assert len(env.repo.list_sessions(env.pid)) == 1 and len(env.users()) == 1
    assert env.applied() == 1 and len(env.repo.list_observations(env.pid)) == 1 and len(spy2.calls) == 1
    goal = "en.gram.past_simple_regular"
    assert env.repo.attempt_history(env.pid, goal) == [] and env.repo.get_skill_state(env.pid, goal) is None
