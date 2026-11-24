"""F5.5: WhisperSTT.transcribe_detailed — pewność słów Whispera → `low_probs` tury głosowej."""
from types import SimpleNamespace as NS

import numpy as np
import pytest

from tests.llm_fakes import FakeProvider
from tests.test_eval_runner import GOAL, Prov, structured
from tests.voice_fakes import FakeMic, FakeSTT, FakeTTS, Lines, blocks, tone
from tutor.app.eval_runner import make_queue, restore_pending
from tutor.llm.base import CancelToken
from tutor.pedagogy import content as C
from tutor.voice import audio as A
from tutor.voice.cli import run
from tutor.voice.conversation import VoiceTutor
from tutor.voice.stt import LOW_PROB, Transcript, WhisperSTT

AUDIO = np.zeros(16000, np.float32)


def seg(text, words=None, nsp=0.0, lp=-0.2):
    return NS(text=text, words=words, no_speech_prob=nsp, avg_logprob=lp)


def w(word, p):
    return NS(word=word, probability=p, start=0.0, end=0.1)


class FakeModel:
    def __init__(self, segs=(), exc=None):
        self.segs, self.exc, self.kw = list(segs), exc, None

    def transcribe(self, audio, **kw):
        self.kw = kw
        if self.exc:
            raise self.exc
        return iter(self.segs), NS()


def stt(model):
    s = object.__new__(WhisperSTT)
    s.m, s.language, s.beam = model, "en", 1
    return s


def test_transcribe_compatible_plain_string_and_no_word_timestamps():
    m = FakeModel([seg(" I went home. ", [w(" I", .9)])])
    assert stt(m).transcribe(AUDIO) == "I went home."
    assert not m.kw.get("word_timestamps")                      # dotychczasowa ścieżka bez zmian


def test_detailed_collects_low_prob_words_normalized():
    m = FakeModel([seg(" I goed home.", [w(" I", .95), w(" goed", .31), w(" home.", .8)]),
                   seg(" It’s “Fine”", [w(" It’s", .49), w(" “Fine”", LOW_PROB)])])
    t = stt(m).transcribe_detailed(AUDIO)
    assert m.kw["word_timestamps"] is True
    assert t == Transcript("I goed home. It’s “Fine”", ["goed", "it's"])   # < 0.5 niskie; == 0.5 nie; sort, bez interpunkcji


def test_detailed_empty_list_means_all_confident_not_missing():
    t = stt(FakeModel([seg(" Hello there", [w(" Hello", .9), w(" there", .9)])])).transcribe_detailed(AUDIO)
    assert t.text == "Hello there" and t.low_probs == []


def test_detailed_none_when_whisper_gives_no_word_data():
    t = stt(FakeModel([seg(" Hello there", None)])).transcribe_detailed(AUDIO)
    assert t.text == "Hello there" and t.low_probs is None      # brak danych ≠ brak niskich; nic nie zmyślamy


def test_detailed_none_if_any_kept_segment_lacks_words():
    t = stt(FakeModel([seg(" A", [w(" A", .9)]), seg(" b", None)])).transcribe_detailed(AUDIO)
    assert t.low_probs is None


def test_detailed_skips_discarded_segments_words():
    m = FakeModel([seg(" noise", [w(" noise", .1)], nsp=.9, lp=-1.5), seg(" Fine", [w(" Fine", .9)])])
    t = stt(m).transcribe_detailed(AUDIO)
    assert t == Transcript("Fine", [])                           # odrzucony segment nie wnosi słów


def test_detailed_short_audio_and_phantom():
    s = stt(FakeModel([seg(" you", [w(" you", .9)])]))
    assert s.transcribe_detailed(np.zeros(100, np.float32)) == Transcript("", None)
    assert s.transcribe_detailed(AUDIO) == Transcript("", None)  # halucynacja Whispera


def test_detailed_propagates_model_error():
    with pytest.raises(RuntimeError):
        stt(FakeModel(exc=RuntimeError("boom"))).transcribe_detailed(AUDIO)


# --- VoiceTutor i CLI ---
def mk(repo, **kw):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    return VoiceTutor(repo, pid, sid, FakeProvider(chunks=["Nice. "]), FakeTTS(), A.SimSink(), **kw), pid, sid


def last_user(repo, pid, sid):
    return [t for t in repo.list_turns(pid, sid) if t["role"] == "user"][-1]


def test_voicetutor_stores_voice_mode_and_low_probs(repo):
    t, pid, sid = mk(repo)
    t.respond("I goed home", low_probs=["goed"])
    t.respond("fine", low_probs=[])
    t.respond("no data")                                          # domyślnie: głos bez danych STT
    t.respond("typed line", input_mode="text")
    rows = [x for x in repo.list_turns(pid, sid) if x["role"] == "user"]
    assert [(r["input_mode"], r["low_prob_json"]) for r in rows] == [
        ("voice", '["goed"]'), ("voice", "[]"), ("voice", None), ("text", None)]


class DetailedSTT(FakeSTT):
    def __init__(self, *items):
        super().__init__()
        self.items = list(items)

    def transcribe_detailed(self, audio):
        it = self.items.pop(0)
        if isinstance(it, Exception):
            raise it
        return it


def cli(repo, conn, lines, argv, **kw):
    out = []
    code = run(["--voice", "--profile", "ann", *argv], llm=FakeProvider(chunks=["Nice. "]), tts=FakeTTS(),
               lines=lines, db=conn, out=out.append, **kw)
    return code, out


def test_cli_passes_detailed_transcript_and_typed_stays_text(repo, conn):
    repo.create_profile("ann")
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    s = DetailedSTT(Transcript("I goed home", ["goed"]))
    code, _ = cli(repo, conn, Lines("", "", "q"), ["--mode", "ptt"], mic=mic, stt=s, sink=A.SimSink())
    assert code == 0
    pid = repo.list_profiles()[0]["id"]
    sid = repo.list_sessions(pid)[0]["id"]
    u = last_user(repo, pid, sid)
    assert (u["input_mode"], u["low_prob_json"]) == ("voice", '["goed"]')
    code, _ = cli(repo, conn, Lines("hello typed", "q"), ["--no-audio"], mic=None, sink=A.SimSink())
    u = last_user(repo, pid, repo.list_sessions(pid)[-1]["id"])
    assert (u["input_mode"], u["low_prob_json"]) == ("text", None)


def test_cli_stt_error_does_not_crash_or_store_turn(repo, conn):
    repo.create_profile("ann")
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    s = DetailedSTT(RuntimeError("whisper down"), Transcript("I went home", []))
    code, out = cli(repo, conn, Lines("", "", "", "", "q"), ["--mode", "ptt"], mic=mic, stt=s, sink=A.SimSink())
    pid = repo.list_profiles()[0]["id"]
    sid = repo.list_sessions(pid)[0]["id"]
    assert code == 0 and any("nic nie zrozumiałem" in o for o in out)
    assert [t["text"] for t in repo.list_turns(pid, sid) if t["role"] == "user"] == ["I went home"]


def test_cli_legacy_stt_without_detailed_gives_unevaluable_voice_turn(repo, conn):
    repo.create_profile("ann")
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    code, _ = cli(repo, conn, Lines("", "", "q"), ["--mode", "ptt"], mic=mic, stt=FakeSTT("I goed home"),
                  sink=A.SimSink())
    pid = repo.list_profiles()[0]["id"]
    u = last_user(repo, pid, repo.list_sessions(pid)[0]["id"])
    assert (u["input_mode"], u["low_prob_json"]) == ("voice", None)


# --- ocena po restarcie ---
@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def evaluate_restored(repo, pack, pid, sid):
    q = make_queue(repo, pack, Prov(), structured, profile_id=pid, session_id=sid, goals={GOAL: "x"},
                   clock=lambda: __import__("datetime").datetime(2026, 11, 24, tzinfo=__import__("datetime").UTC))
    n = restore_pending(repo, q, pid, sid)
    q.drain(CancelToken())
    return n, [o["kind"] for o in repo.list_observations(pid)]


def test_voice_turn_with_low_probs_evaluated_as_voice_after_restart(repo, pack):
    t, pid, sid = mk(repo)
    t.respond("I goed home", low_probs=["goed"])               # niska pewność słowa ⇒ podejrzenie STT, nie błąd
    n, kinds = evaluate_restored(repo, pack, pid, sid)
    assert n == 1 and kinds == ["stt_suspect"]
    assert repo.get_turn_meta(pid, last_user(repo, pid, sid)["id"])["input_mode"] == "voice"


def test_voice_turn_without_data_never_evaluated_and_text_turn_unchanged(repo, pack):
    t, pid, sid = mk(repo)
    t.respond("I goed home")                                   # None: brak danych STT
    assert evaluate_restored(repo, pack, pid, sid) == (0, [])


def test_text_session_unchanged(repo, pack):
    pid = repo.create_profile("txt")
    sid = repo.start_session(pid, "chat")
    repo.add_turn(pid, sid, "user", "I goed home")
    n, kinds = evaluate_restored(repo, pack, pid, sid)
    assert n == 1 and kinds == ["error"]
