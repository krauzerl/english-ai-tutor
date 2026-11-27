import threading
import time

import numpy as np

from tests.llm_fakes import FakeProvider
from tests.voice_fakes import FakeMic, FakeSTT, FakeTTS, Lines, blocks, tone
from tutor.llm.base import CancelToken, LLMUnavailable, Stream, Usage
from tutor.llm.context import estimate_tokens
from tutor.voice import audio as A
from tutor.voice.cli import run
from tutor.voice.conversation import VoiceTutor


def mk(repo, llm=None, tts=None, sink=None, **kw):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    llm = llm or FakeProvider(chunks=["Nice! ", "I like ", "tea too. ", "What kind?"])
    return VoiceTutor(repo, pid, sid, llm, tts or FakeTTS(), sink or A.SimSink(), **kw), pid, sid


def test_turn_speaks_sentences_and_saves_spoken_text(repo):
    t, pid, sid = mk(repo)
    r = t.respond("I like tea")
    assert t.tts.calls == ["Nice! I like tea too.", "What kind?"] and r.sentences == 2
    assert r.reply == "Nice! I like tea too. What kind?" and not r.cancelled and r.error is None
    assert [x["role"] for x in repo.list_turns(pid, sid)] == ["user", "assistant"]
    assert repo.list_turns(pid, sid)[1]["text"] == r.reply
    assert r.m["first_audio"] >= r.m["first_sentence"] >= r.m["llm_first_token"] >= 0


def test_tts_starts_before_llm_finishes(repo):
    gate, synth_started = threading.Event(), threading.Event()

    class Slow(FakeProvider):
        def stream(self, messages, *, temperature=0.0, max_tokens=256, cancel=None):
            def gen():
                yield "First sentence here. "
                assert gate.wait(3), "TTS nie wystartowało przed końcem odpowiedzi LLM"
                yield "Second one."
                return Usage(1, 1)
            return Stream(gen(), cancel or CancelToken())

    class T(FakeTTS):
        def synth(self, text):
            synth_started.set()
            gate.set()
            return super().synth(text)

    t, *_ = mk(repo, llm=Slow(), tts=T())
    r = t.respond("hi")
    assert synth_started.is_set() and r.reply == "First sentence here. Second one."


def test_cancel_stops_generation_and_keeps_only_spoken(repo):
    started = threading.Event()

    class Endless(FakeProvider):
        n = 1000

        def stream(self, messages, *, temperature=0.0, max_tokens=256, cancel=None):
            def gen():
                yield "Hello there. "
                started.set()
                for _ in range(self.n):
                    time.sleep(0.01)
                    yield "More words. "
                return Usage(1, 1)
            return Stream(gen(), cancel or CancelToken())

    t, pid, sid = mk(repo, llm=Endless())
    threading.Timer(0.15, lambda: (started.wait(2), t.cancel())).start()
    t0 = time.monotonic()
    r = t.respond("hi")
    assert r.cancelled and time.monotonic() - t0 < 2
    assert len(t.tts.calls) < 50 and r.reply.startswith("Hello there.")
    assert t.sink.written == []  # głośnik wyczyszczony
    t.llm.n = 3
    t.respond("again")  # kolejna tura po przerwaniu działa


def test_llm_error_keeps_user_turn_and_reports(repo):
    t, pid, sid = mk(repo, llm=FakeProvider(chunks=["Hi there. ", "x"], fail_after=1))
    r = t.respond("hello")
    assert r.error and r.reply == "Hi there."
    assert repo.list_turns(pid, sid)[0]["text"] == "hello"


def test_tts_failure_does_not_hang(repo):
    t, *_ = mk(repo, tts=FakeTTS(fail_on="Nice"))
    r = t.respond("hi")
    assert r.error and r.error.startswith("TTS") and not r.reply


def test_markdown_only_chunk_skipped(repo):
    t, *_ = mk(repo, llm=FakeProvider(chunks=["*** ", "Hello **you**. "]))
    t.respond("hi")
    assert t.tts.calls == ["Hello you."]


def test_memory_and_context_limits_over_25_turns(repo):
    llm = FakeProvider(chunks=["Interesting point about that. ", "And why?"])
    t, pid, sid = mk(repo, llm=llm, context_window=2000, max_tokens=100)
    for i in range(25):
        r = t.respond(f"Turn {i}: I think this is a long enough sentence about topic {i}.")
        assert not r.error
    sent = llm.calls[-1]
    assert sent[-1].content.startswith("Turn 24") and any("Turn 23" in m.content for m in sent)
    assert sum(estimate_tokens(m.content) for m in sent) + 100 <= 2000
    assert len(repo.list_checkpoints(pid, sid)) >= 4 and "Earlier in this session" in sent[0].content
    assert len(repo.list_turns(pid, sid)) == 50


def test_pipeline_no_gap_when_tts_faster_than_playback(repo):
    t, *_ = mk(repo, tts=FakeTTS(secs=1.0))
    r = t.respond("hi")
    assert r.m["underrun_s"] == 0 and r.m["n_gaps"] == 0


# ---- CLI z atrapami ----
def cli(repo, conn, lines, argv=(), **kw):
    out = []
    repo.create_profile("ann")
    llm = kw.pop("llm", FakeProvider(chunks=["Sure. ", "Tell me more."]))
    code = run(["--voice", "--profile", "ann", *argv], llm=llm, tts=FakeTTS(), lines=lines, out=out.append,
               db=conn, **kw)
    return code, out, llm


def test_cli_text_mode_when_no_mic(repo, conn, monkeypatch, tmp_path):
    def boom(self):
        raise A.AudioUnavailable("brak")
    monkeypatch.setattr(A.Mic, "open", boom)
    monkeypatch.setattr(A, "Speaker", lambda dev=None: A.SimSink())
    code, out, llm = cli(repo, conn, Lines("I like tea", "q"))
    assert code == 0 and any("brak mikrofonu" in o for o in out) and any(o.startswith("Tutor: Sure.") for o in out)
    assert llm.calls[0][-1].content == "I like tea"


def test_cli_ptt_flow_empty_transcript_and_no_recordings(repo, conn, tmp_path, monkeypatch):
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.chdir(cwd)
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = FakeSTT("", "I went to London")  # pierwsza transkrypcja pusta (szum)
    code, out, llm = cli(repo, conn, Lines("", "", "", "", "q"), ["--mode", "ptt", "--stt-confirm", "never"], mic=mic, stt=stt,
                         sink=A.SimSink())
    assert code == 0 and stt.audio_seen
    assert any("nic nie zrozumiałem" in o for o in out)
    assert llm.calls[0][-1].content == "I went to London" and len(llm.calls) == 1
    assert list(cwd.iterdir()) == []  # żadnych plików z nagraniami
    assert mic.muted and mic.muted[-1] == 0.4  # ogon echa po mowie


def test_cli_rejects_external_llm_and_missing_profile(repo, conn):
    ext = FakeProvider(external=True)
    code, _, _ = cli(repo, conn, Lines("q"), llm=ext)
    assert code == 1
    assert run(["--voice", "--profile", "nobody"], llm=ext, tts=FakeTTS(), lines=Lines("q"), db=conn) == 1


def test_cli_ollama_down(repo, conn):
    llm = FakeProvider()
    llm.health = lambda: False
    code, _, _ = cli(repo, conn, Lines("q"), argv=["--no-audio"], llm=llm)
    assert code == 1


def test_enter_cancels_speech_in_cli(repo, conn):
    class Endless(FakeProvider):
        def stream(self, messages, *, temperature=0.0, max_tokens=256, cancel=None):
            def gen():
                for _ in range(2000):
                    time.sleep(0.01)
                    yield "Another sentence. "
                return Usage(1, 1)
            return Stream(gen(), cancel or CancelToken())

    lines = Lines("hello")
    threading.Timer(0.3, lambda: lines.put("")).start()  # Enter w trakcie mowy
    threading.Timer(1.5, lambda: lines.put("q")).start()
    llm = Endless()
    llm.health = lambda: True
    repo.create_profile("ann")
    out = []
    t0 = time.monotonic()
    code = run(["--voice", "--profile", "ann", "--no-audio"], llm=llm, tts=FakeTTS(), lines=lines, out=out.append, db=conn)
    assert code == 0 and any("przerwano" in o for o in out) and time.monotonic() - t0 < 3.5


def test_llm_unavailable_message(repo):
    t, *_ = mk(repo, llm=FakeProvider(chunks=["a"], fail_after=0))
    assert t.respond("x").error
    assert isinstance(LLMUnavailable("x"), Exception) and np  # import użyty


def test_typed_lines_keep_order_while_tutor_speaks(repo, conn):
    code, out, llm = cli(repo, conn, Lines("first", "second", "q"), ["--no-audio"])
    assert code == 0 and [c[-1].content for c in llm.calls] == ["first", "second"]


# --- Pilot: pytanie o życie nauczyciela → notatka persona przy wiadomości (tylko dla modelu) ---
def test_persona_note_only_in_llm_message_not_in_db(repo):
    from tutor.app import intent as INTENT
    t, pid, sid = mk(repo)
    t.respond("What do you usually do on weekends?")
    last = t.llm.calls[-1][-1]
    assert last.role == "user" and last.content.endswith(INTENT.PERSONA_NOTE)
    assert INTENT.PERSONA_NOTE not in t.llm.calls[-1][0].content                     # system bez zmian
    assert repo.list_turns(pid, sid)[0]["text"] == "What do you usually do on weekends?"   # baza: czysty tekst
    t.respond("I usually cook on Sundays.")
    assert INTENT.PERSONA_NOTE not in t.llm.calls[-1][-1].content
    assert all(INTENT.PERSONA_NOTE not in m.content for m in t.llm.calls[-1][1:-1])  # historia bez notatek


def test_persona_note_off_in_roleplay(repo):
    from tutor.app import intent as INTENT
    t, _, _ = mk(repo, persona=False)
    t.respond("Do you have any kids?")
    assert INTENT.PERSONA_NOTE not in t.llm.calls[-1][-1].content


def test_asks_about_tutor_detector():
    from tutor.app.intent import asks_about_tutor
    for s in ("What do you usually do on weekends?", "Do you like cooking?", "Have you ever been there?",
              "What about you?", "I love jazz, and you?", "What is your favourite film?"):
        assert asks_about_tutor(s), s
    for s in ("Can you repeat that, please?", "Could you explain that in simpler words?", "Do you know what it means?",
              "I usually cook on Sundays.", "Do you think it is a good idea?", "What did you say?", "What do you mean?"):
        assert not asks_about_tutor(s), s
