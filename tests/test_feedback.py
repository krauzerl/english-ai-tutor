"""F5.10: informacja zwrotna w rozmowie (recast wg stylu, podsumowanie na końcu), cel lekcji w rozmowie,
pominięte zadania nie kończą lekcji."""
import time
from datetime import UTC, datetime

import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_stt_detailed import DetailedSTT
from tests.voice_fakes import FakeMic, Lines, blocks, tone
from tutor.app import feedback as FB
from tutor.app import lesson as L
from tutor.pedagogy import content as C
from tutor.pedagogy.correction import effective_style
from tutor.voice import audio as A
from tutor.voice.stt import Transcript

NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)
SKILL = "en.gram.to_be_present"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def obs(repo, pid, sid, text, *, kind="error", cat="article.missing", span="paramedic", fix="a paramedic", sev=2,
        conf="h", mode="text"):
    tid = repo.add_turn(pid, sid, "user", text, input_mode=mode, low_probs=[] if mode == "voice" else None)
    repo.add_observation(pid, sid, tid, kind, span, category=cat, fix=fix, severity=sev, confidence=conf)
    return tid


def style(pack, s):
    return effective_style(s, pack.rubric)["style"]


# --- kandydaci i dyrektywa ---
def test_summary_style_never_interrupts_conversation(repo, pack):
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I'm paramedic.")
    assert FB.recast_directive(repo, pack, pid, sid, "summary", set()) is None


def test_periodic_recasts_significant_error_once_without_lecture(repo, pack):
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I'm paramedic.")
    d = FB.recast_directive(repo, pack, pid, sid, "periodic", set())
    assert d and "a paramedic" in d and "paramedic" in d and "do not" in d.lower()
    assert "mistake" in d.lower()                                       # nakaz: nie mówić o błędzie
    assert FB.recast_directive(repo, pack, pid, sid, "periodic", set()) is None   # raz, bez powtórek


def test_minor_error_is_not_interrupted_but_goal_error_is(repo, pack):
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I'm paramedic.", sev=1)
    assert FB.recast_directive(repo, pack, pid, sid, "periodic", set()) is None       # drobiazg: nie przerywamy
    sk = next(s for s in pack.skills.values() if "article.missing" in s.error_categories)
    repo.conn.execute("UPDATE observation SET skill_id=?", (sk.id,))
    assert FB.recast_directive(repo, pack, pid, sid, "periodic", {sk.id}) is not None  # cel lekcji: wolno


def test_uncertain_or_dropped_observations_are_not_corrections(repo, pack):
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I'm paramedic.", conf="m")                        # niepewna ocena modelu
    tid = obs(repo, pid, sid, "x", kind="error")
    repo.conn.execute("UPDATE observation SET status='dropped' WHERE turn_id=?", (tid,))
    assert FB.recast_directive(repo, pack, pid, sid, "intensive", set()) is None


def test_stt_suspect_is_only_a_soft_check_never_an_error(repo, pack):
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I'm paramedic.", kind="stt_suspect", mode="voice", sev=2)
    d = FB.recast_directive(repo, pack, pid, sid, "periodic", set())
    assert d and "misheard" in d.lower() and "a paramedic" in d
    lines = FB.summary_lines(repo, pack, pid, sid)
    assert any("źle usłyszałem" in x for x in lines) and not any("błąd" in x.lower() for x in lines)


def test_directive_does_not_leak_other_sessions_or_profiles(repo, pack):
    a, b = repo.create_profile("ann"), repo.create_profile("bob")
    sa, sb = repo.start_session(a, "voice"), repo.start_session(b, "voice")
    obs(repo, a, sa, "I'm paramedic.")
    assert FB.recast_directive(repo, pack, b, sb, "periodic", set()) is None
    s2 = repo.start_session(a, "voice")
    assert FB.recast_directive(repo, pack, a, s2, "periodic", set()) is None and FB.summary_lines(repo, pack, a, s2) == []


# --- podsumowanie ---
def test_summary_lists_up_to_limit_with_explanation_and_hedge(repo, pack):
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "voice")
    for i in range(8):
        obs(repo, pid, sid, f"I'm paramedic {i}.", span=f"paramedic {i}", fix=f"a paramedic {i}")
    lines = FB.summary_lines(repo, pack, pid, sid)
    text = "\n".join(lines)
    assert "sugestie" in text and len([x for x in lines if x.startswith("•")]) == pack.rubric.correction["quiz_sentences_max"]
    assert "Rzeczownik policzalny" in text                                   # wyjaśnienie kategorii z silnika


# --- VoiceTutor ---
def test_feedback_hook_extends_system_for_that_turn_only_and_survives_errors(repo):
    from tests.voice_fakes import FakeTTS
    from tutor.voice.conversation import VoiceTutor
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "voice")
    llm = FakeProvider(chunks=["Nice. "])
    notes = ["NOTE-1", None, RuntimeError("boom")]

    def fb(_text=""):
        n = notes.pop(0)
        if isinstance(n, Exception):
            raise n
        return n
    t = VoiceTutor(repo, pid, sid, llm, FakeTTS(), A.SimSink(), feedback=fb)
    t.respond("one"); t.respond("two"); t.respond("three")
    sys_ = [c[0].content for c in llm.calls]
    assert "NOTE-1" in sys_[0] and "NOTE-1" not in sys_[1] and "NOTE-1" not in sys_[2]
    assert all(r["role"] != "system" for r in repo.list_turns(pid, sid))      # nic nie trafia do historii


# --- CLI ---
class Gated(Lines):
    """Linie podawane na żądanie; przed `n`-tą czeka na warunek (ocena poprzedniej tury zakończona)."""

    def __init__(self, gates, *script):
        super().__init__()
        self.gates, self.script, self.i = gates, list(script), 0

    def get(self, block=True, timeout=None):
        if not self.script:
            return "q"
        if self.i in self.gates:
            end = time.monotonic() + 8
            while not self.gates[self.i]() and time.monotonic() < end:
                time.sleep(0.02)
        self.i += 1
        return self.script.pop(0)


def test_cli_periodic_style_recasts_next_turn_once(env):
    conv = FakeProvider(chunks=["Nice. ", "Go on."])
    ev = EvalProv()
    env.go(Gated({1: lambda: env.applied() >= 1}, "I goed home", "And then", "More"), ["--no-audio", "--correction",
           "periodic", "--summary-wait", "0"], llm=conv, ev=ev)
    sys_ = [c[0].content for c in conv.calls]
    assert len(sys_) == 3
    assert "went" not in sys_[0] and "went" in sys_[1] and "went" not in sys_[2]       # raz, w następnej turze
    assert [u["text"] for u in env.users()] == ["I goed home", "And then", "More"]     # rozmowa nie przerwana


def test_cli_default_summary_style_gives_end_of_session_feedback_not_inline(env):
    conv = FakeProvider(chunks=["Nice. "])
    ev = EvalProv()
    code, out = env.go(Gated({1: lambda: env.applied() >= 1}, "I goed home", "And then"),
                       ["--no-audio", "--summary-wait", "5"], llm=conv, ev=ev)
    assert all("went" not in c[0].content for c in conv.calls)                         # nie w trakcie
    text = "\n".join(out)
    assert "Do poprawy" in text and "went" in text and "sugestie" in text            # na końcu, z zastrzeżeniem


def test_cli_stt_uncertain_word_is_not_reported_as_error(env):
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = DetailedSTT(Transcript("I goed home", ["goed"]))                            # niska pewność STT
    ev = EvalProv()
    code, out = env.go(Gated({}, "", ""), ["--mode", "ptt", "--summary-wait", "5"], mic=mic, stt=stt, ev=ev,
                       sink=A.SimSink())
    text = "\n".join(out)
    assert [o["kind"] for o in env.repo.list_observations(env.pid)] == ["stt_suspect"]    # podejrzenie STT, nie błąd
    assert env.repo.list_errors(env.pid) == []                                            # nic w rejestrze błędów ucznia
    assert "źle usłyszałem" not in text or "Do poprawy" in text                           # co najwyżej łagodna uwaga
    assert env.repo.attempt_history(env.pid, "en.gram.past_simple_regular") == []


# --- lekcja: cel w rozmowie ---
def test_lesson_system_focus_gives_concrete_target_forms(pack):
    sk, _ = L.prepare(pack, SKILL)
    f = L.system_focus(pack, sk)
    assert SKILL in f and "I am a student" in f and "do not quiz" in f.lower()        # przykłady z wyjaśnienia lekcji


def test_cli_lesson_conversation_gets_goal_in_system_prompt(env, pack):
    _, items = L.prepare(pack, SKILL)
    conv = FakeProvider(chunks=["Nice. "])
    env.go(Lines(*[i.answers[0] for i in items], "Hello", "q"), ["--no-audio", "--lesson", SKILL, "--summary-wait", "0"],
           llm=conv, ev=EvalProv())
    assert SKILL in conv.calls[0][0].content and "I am a student" in conv.calls[0][0].content


# --- lekcja: pominięcie i wznowienie (odtworzenie raportu użytkownika) ---
def A_(text, mode="text", low=None):
    return L.Answer(text, mode, low)


def test_gap_accepts_full_spoken_sentence(pack):
    sk, items = L.prepare(pack, SKILL)
    gap = next(i for i in items if i.type == "gap")
    sentence = gap.prompt.replace("___", gap.answers[0])
    assert L.check(pack, gap, sentence) and L.check(pack, gap, sentence.lower().rstrip("."))
    assert not L.check(pack, gap, gap.prompt.replace("___", "are"))                  # zła forma w pełnym zdaniu


def test_unverified_voice_answers_skip_items_without_completing_lesson(repo, pack):
    pid = repo.create_profile("ann"); sid = repo.start_session(pid, "lesson")
    sk, items = L.begin(repo, pack, pid, sid, SKILL)
    out = []
    res = L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i: A_("mumble", "voice", None), out.append,
                          now=NOW)
    plan = repo.get_session_plan(pid, sid)
    assert res.skipped == 3 and res.correct == 0 and plan["done"] == []             # nic nie jest „zrobione”
    from tutor.app import goal as G
    assert G.completed(repo, pid) == {} and "wrócą" in L.summary(res)
    again = []
    feed = {i.id: A_(i.answers[0]) for i in items}
    res2 = L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i: feed[it.id], again.append, now=NOW)
    assert res2.skipped == 0 and res2.correct == 3 and len(repo.attempt_history(pid, SKILL)) == 3
    assert items[0].prompt in "\n".join(again)                                       # wznowienie wraca do zadania 1/3


def test_cli_resume_after_all_skipped_returns_to_exercises(env, pack):
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = DetailedSTT(*[Transcript("mumble", None)] * 9)
    env.go(Gated({}, *([""] * 18)), ["--mode", "ptt", "--lesson", SKILL, "--summary-wait", "0"],
           mic=mic, stt=stt, ev=EvalProv(), sink=A.SimSink())
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and env.repo.get_session_plan(env.pid, s[0]["id"])["done"] == []
    _, items = L.prepare(pack, SKILL)
    code, out = env.go(Lines(*[i.answers[0] for i in items], "q"), ["--no-audio", "--lesson", SKILL, "--summary-wait", "0"],
                       ev=EvalProv())
    text = "\n".join(out)
    assert "Wznawiam" in text and items[0].prompt in text and len(env.repo.attempt_history(env.pid, SKILL)) == 3
