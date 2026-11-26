"""F5.11: lekcja głosowa — tutor mówi cel, objaśnienie, zadania i informację zwrotną po angielsku (bez LLM na polecenie),
uczeń odpowiada głosem. Atrapy audio/STT/TTS; kolejność wypowiedzi weryfikowana na wspólnej osi zdarzeń."""
import threading

import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tests.test_stt_detailed import DetailedSTT
from tests.voice_fakes import FakeMic, FakeTTS, Lines, blocks, tone
from tutor.app import lesson as L
from tutor.app import lesson_voice as LV
from tutor.pedagogy import content as C
from tutor.voice import audio as A
from tutor.voice.conversation import VoiceTutor
from tutor.voice.stt import Transcript

SKILL = "en.gram.to_be_present"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


class RecTTS(FakeTTS):
    """Zapisuje wypowiedzi na wspólnej osi zdarzeń razem z wyjściem ekranu."""

    def __init__(self, events, **kw):
        super().__init__(**kw)
        self.events = events

    def synth(self, text):
        a = super().synth(text)
        self.events.append(("tts", text))
        return a


def spoken(events):
    return [t for k, t in events if k == "tts"]


def full(item):
    return item.prompt.replace("___", item.answers[0]) if item.type == "gap" else item.answers[0]


def voice_lesson(env, answers, chat="Hello there", extra=(), tts_kw=None, lines=None, argv=(), conv=None):
    """Lekcja głosem (PTT): każda odpowiedź = dwa Enter-y; STT zwraca pewne transkrypcje."""
    events = []
    tts = RecTTS(events, **(tts_kw or {}))
    stt = DetailedSTT(*[Transcript(t, []) if isinstance(t, str) else t for t in answers], Transcript(chat, []))
    script = lines if lines is not None else [*[""] * (2 * (len(answers) + 1)), "q"]
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    sink = A.SimSink()
    out = []
    code = env_go(env, Gated({}, *script), ["--mode", "ptt", "--lesson", SKILL, *argv], events, out, tts=tts,
                  mic=mic, stt=stt, sink=sink, conv=conv)
    return code, events, out, tts, sink


def env_go(env, lines, argv, events, out, **kw):
    conv = kw.pop("conv", None) or FakeProvider(chunks=["Nice. ", "Tell me more."])
    tts = kw.pop("tts")
    from tutor.voice.cli import run
    return run(["--voice", "--profile", "ann", "--summary-wait", "0", *argv], llm=conv, eval_llm=EvalProv(), tts=tts,
               lines=lines, out=lambda s: (events.append(("out", s)), out.append(s)), db=env.conn, **kw)


# --- komunikaty (czyste funkcje, bez modeli) ---
def test_phrases_are_short_english_and_never_read_polish_material(pack):
    sk, items = L.prepare(pack, SKILL)
    plan = [LV.greeting(sk), *LV.explanation(pack, sk), LV.task(items[0], 0, 3), LV.task(items[2], 2, 3),
            LV.retry(), LV.reask(), LV.reveal(items[0]), LV.chat_start(2, 3), LV.farewell(True)]
    plan = [LV.clean(x) for x in plan]
    for t in plan:
        assert t and t.isascii() and len(t) < 260                                   # krótkie angielskie zdania
    polish = pack.explanations[sk.explanation_ref]                                   # materiał PL nie trafia do TTS
    assert sk.can_do_pl not in " ".join(plan) and "Dlaczego" not in " ".join(plan) and polish


def test_task_phrase_reads_gap_as_blank_and_mc_as_lettered_options(pack):
    _, items = L.prepare(pack, SKILL)
    gap = next(i for i in items if i.type == "gap")
    mc = next(i for i in items if i.type == "mc")
    g = LV.task(gap, 0, 3)
    assert "___" not in g and "blank" in g.lower() and "whole sentence" in g
    m = LV.task(mc, 2, 3)
    assert "A." in m and "B." in m and mc.options[1] in m


def test_non_english_or_text_heavy_tasks_point_to_the_screen(pack):
    it = next(i for i in pack.items.values() if i.type == "translate_pl")
    assert "screen" in LV.task(it, 0, 3).lower() and it.prompt not in LV.task(it, 0, 3)


# --- pełna lekcja ---
def test_complete_voice_lesson_speaks_in_order_and_records_once(env, pack):
    _, items = L.prepare(pack, SKILL)
    code, events, out, tts, sink = voice_lesson(env, [full(i) for i in items])
    assert code == 0
    sp = spoken(events)
    joined = " | ".join(sp)
    # kolejność: powitanie → cel/objaśnienie → zadanie 1 → ocena → zadanie 2 → ... → rozmowa → odpowiedź tutora → pożegnanie
    order = [next(n for n, s in enumerate(sp) if key in s) for key in
             ("Hello", "I am a student", "Task 1", "Correct", "Task 2", "Task 3", "chat", "Nice")]
    assert order == sorted(order) and len(set(order)) == len(order), joined
    assert sp[-1].startswith(("Well done", "Good work", "Great work")) or "next time" in sp[-1]
    # ekran: pełny materiał zostaje jako pomoc
    text = "\n".join(s for k, s in events if k == "out")
    assert "Cel lekcji" in text and items[0].prompt in text
    # zapis: dokładnie raz, bez automatycznej biegłości
    assert len(env.repo.attempt_history(env.pid, SKILL)) == 3
    assert env.repo.get_skill_state(env.pid, SKILL)["status"] == "learning"
    assert sink.written is not None


def test_screen_line_precedes_its_speech_and_speech_precedes_listening(env, pack):
    _, items = L.prepare(pack, SKILL)
    _, events, _, _, _ = voice_lesson(env, [full(i) for i in items])
    i_out = next(n for n, (k, s) in enumerate(events) if k == "out" and "Zadanie 1/3" in s)
    i_tts = next(n for n, (k, s) in enumerate(events) if k == "tts" and "Task 1" in s)
    i_rec = next(n for n, (k, s) in enumerate(events) if k == "out" and "nagrywam" in s and n > i_tts)
    assert i_out < i_tts < i_rec


def test_wrong_answer_gives_short_hint_and_allows_retry(env, pack):
    _, items = L.prepare(pack, SKILL)
    wrong = items[0].prompt.replace("___", "are")
    ans = [wrong, full(items[0]), full(items[1]), full(items[2])]
    _, events, _, tts, _ = voice_lesson(env, ans, lines=[*[""] * 10, "q"])
    sp = spoken(events)
    i_hint = next(n for n, s in enumerate(sp) if "not quite" in s.lower())
    assert "try" in " ".join(sp[i_hint:i_hint + 2]).lower()                          # krótka wskazówka + ponowna próba
    i_task2 = next(n for n, s in enumerate(sp) if "Task 2" in s)
    assert i_hint < i_task2 and any(s.startswith("Correct") for s in sp[i_hint:i_task2])
    h = env.repo.attempt_history(env.pid, SKILL)
    assert len(h) == 3                                                               # jedna próba na zadanie
    assert any(sp_ for sp_ in sp if "after a hint" in sp_.lower())


def test_second_miss_reveals_answer_and_moves_on(env, pack):
    _, items = L.prepare(pack, SKILL)
    wrong = items[0].prompt.replace("___", "are")
    ans = [wrong, wrong, full(items[1]), full(items[2])]
    _, events, _, _, _ = voice_lesson(env, ans, lines=[*[""] * 10, "q"])
    sp = spoken(events)
    assert any("correct answer" in s.lower() and full(items[0]) in s for s in sp)
    assert len(env.repo.attempt_history(env.pid, SKILL)) == 3


def test_uncertain_transcription_is_not_graded_and_asks_again(env, pack):
    _, items = L.prepare(pack, SKILL)
    ans = [Transcript("mumble", None), full(items[0]), full(items[1]), full(items[2])]
    _, events, _, _, _ = voice_lesson(env, ans, lines=[*[""] * 10, "q"])
    sp = spoken(events)
    i_re = next(n for n, s in enumerate(sp) if "not sure I heard" in s)
    i_t2 = next(n for n, s in enumerate(sp) if "Task 2" in s)
    assert i_re < i_t2 and not any("not quite" in s.lower() for s in sp[:i_re])    # niepewne ≠ błąd ucznia
    assert len(env.repo.attempt_history(env.pid, SKILL)) == 3 and not env.repo.list_errors(env.pid)


# --- przerwanie wypowiedzi tutora ---
def test_say_is_cancellable_and_stops_before_next_sentence():
    events = []
    tts = RecTTS(events, delay=0.15)
    t = VoiceTutor.__new__(VoiceTutor)
    sink = A.SimSink()
    VoiceTutor.__init__(t, None, 1, 1, None, tts, sink)
    threading.Timer(0.2, t.cancel).start()
    done = t.say("One sentence here. Second sentence there. Third sentence now. Fourth one too.")
    assert done is False and 1 <= len(tts.calls) < 4 and sink.written == []
    assert t.say("Short one.") is True                                              # kolejne wypowiedzi działają


def test_enter_during_greeting_cancels_it_and_lesson_continues(env, pack):
    _, items = L.prepare(pack, SKILL)
    events, out = [], []
    tts = RecTTS(events, delay=0.2)
    lines = Lines("", *[full(i) for i in items], "q")        # pusta linia = Enter w trakcie mowy tutora
    code = env_go(env, lines, ["--lesson", SKILL], events, out, tts=tts, sink=A.SimSink())
    sp = spoken(events)
    assert code == 0 and not any("I am a student" in s for s in sp[:2])              # powitanie przerwane
    assert len(env.repo.attempt_history(env.pid, SKILL)) == 3


def test_tts_failure_does_not_break_lesson(env, pack):
    _, items = L.prepare(pack, SKILL)
    events, out = [], []
    tts = RecTTS(events, fail_on="Task")
    code = env_go(env, Lines(*[full(i) for i in items], "q"), ["--lesson", SKILL], events, out, tts=tts,
                  sink=A.SimSink())
    assert code == 0 and len(env.repo.attempt_history(env.pid, SKILL)) == 3
    assert sum("błąd TTS" in s for s in out) == 1                                  # jedna informacja, dalej tekst


# --- zatrzymanie i wznowienie ---
def test_quit_mid_lesson_then_resume_continues_without_duplicates(env, pack):
    _, items = L.prepare(pack, SKILL)
    # pierwsza sesja: jedno zadanie, potem q
    _, ev1, _, _, _ = voice_lesson(env, [full(items[0])], lines=["", "", "q"])
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and s[0]["status"] == "paused"
    assert len(env.repo.attempt_history(env.pid, SKILL)) == 1
    _, ev2, _, _, _ = voice_lesson(env, [full(items[1]), full(items[2])], lines=[*[""] * 6, "q"])
    sp = spoken(ev2)
    assert any("Welcome back" in s for s in sp) and not any("Task 1" in s for s in sp)
    assert any("Task 2" in s for s in sp)
    assert len(env.repo.attempt_history(env.pid, SKILL)) == 3 and len(env.repo.list_sessions(env.pid)) == 1


# --- tryb tekstowy bez regresji ---
def test_no_audio_lesson_does_not_speak_lesson_phrases(env, pack):
    _, items = L.prepare(pack, SKILL)
    events, out = [], []
    tts = RecTTS(events)
    code = env_go(env, Lines(*[i.answers[0] for i in items], "Hello", "q"), ["--no-audio", "--lesson", SKILL], events,
                  out, tts=tts)
    sp = spoken(events)
    assert code == 0 and sp and not any(k in s for s in sp for k in ("Task", "Correct", "Hello", "Welcome", "chat"))
    assert len(env.repo.attempt_history(env.pid, SKILL)) == 3
    assert env.repo.get_skill_state(env.pid, SKILL)["status"] == "learning"


def test_evaluation_waits_while_tutor_speaks_lesson_phrases(env, pack):
    """Podczas mowy tutora (komunikaty lekcji) ocena w tle jest wstrzymana: begin_activity/tutor_done parami."""
    _, items = L.prepare(pack, SKILL)
    seen = []
    from tutor.app import session_service as SS
    orig_b, orig_d = SS.SessionService.begin_activity, SS.SessionService.tutor_done
    SS.SessionService.begin_activity = lambda self: (seen.append("b"), orig_b(self))[1]
    SS.SessionService.tutor_done = lambda self: (seen.append("d"), orig_d(self))[1]
    try:
        voice_lesson(env, [full(i) for i in items])
    finally:
        SS.SessionService.begin_activity, SS.SessionService.tutor_done = orig_b, orig_d
    assert seen.count("b") == seen.count("d") and seen.count("b") > 10


# --- F7: tempo i pauzy ---
def test_task_parts_are_spoken_separately_with_silence_between(repo, pack):
    _, items = L.prepare(pack, SKILL)
    mc = next(i for i in items if i.type == "mc")
    parts = LV.task(mc, 0, 3).split(LV.PAUSE)
    assert parts[0] == "Task 1 of 3." and "Choose the correct answer." in parts
    assert any(p.startswith("A. ") for p in parts) and any(p.startswith("B. ") for p in parts)
    assert parts[-1] == "Say the whole sentence."
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    sink = A.SimSink()
    t = VoiceTutor(repo, pid, sid, FakeProvider(), FakeTTS(), sink)
    assert t.say(["First part.", "Second part."], gap=0.5) is True
    assert t.say(["First part.", "Second part."], gap=0.25) is True
    w = sink.written[-3:]                                                         # część, pauza, część
    assert len(w) == 3 and len(w[1]) == int(FakeTTS().sample_rate * 0.25) and not w[1].any()


def test_speed_presets_and_comfortable_default():
    from tutor.app import settings as ST
    from tutor.voice import tts as TT
    assert ST.SPEED_PRESETS == {"slow": 0.8, "normal": 0.9, "fast": 1.05} and ST.DEFAULTS["speed"] == 0.9
    # tempo idzie do modelu Kokoro (`speed=`), częstotliwość próbkowania jest stała — wysokość głosu bez zmian
    assert TT.KokoroTTS.sample_rate == 24000 and "speed=self.speed" in open(TT.__file__).read()
