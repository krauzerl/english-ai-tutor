"""F5.11b: poprawki po teście na żywo — rozpoznawanie odpowiedzi głosowych, pętla pytań, intencje ucznia, pochwały."""
from datetime import UTC, datetime

import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tests.voice_fakes import FakeTTS
from tutor.app import intent as I
from tutor.app import lesson as L
from tutor.pedagogy import content as C
from tutor.voice import audio as A
from tutor.voice.conversation import VoiceTutor
from tutor.voice.guard import Guard

SKILL = "en.gram.to_be_present"
NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


@pytest.fixture
def gap(pack):
    _, items = L.prepare(pack, SKILL)
    return next(i for i in items if i.prompt.startswith("I ___"))          # "I ___ twenty-five years old."


def V(text, low=()):
    return L.Answer(text, "voice", list(low))


# --- 1. rozpoznawanie: co Whisper naprawdę pisze ---
@pytest.mark.parametrize("said", ["am", "Am.", "I am.", "I'm", "I'm 25 years old.", "I am 25 years old.",
                                  "I'm twenty-five years old.", "I am twenty five years old", "I am twenty-five",
                                  "I’m 25"])
def test_gap_accepts_how_whisper_writes_the_correct_answer(pack, gap, said):
    assert L.check(pack, gap, said), said


@pytest.mark.parametrize("said", ["are", "I are.", "I is 25 years old.", "I'm 26 years old.", "M.", "Um", "Em.", ""])
def test_gap_does_not_accept_wrong_or_unclear_utterances(pack, gap, said):
    assert not L.check(pack, gap, said), said                                # nic nie jest dopasowywane „na zgodę”


def test_mc_accepts_contraction_of_the_correct_option(pack):
    _, items = L.prepare(pack, SKILL)
    mc = next(i for i in items if i.type == "mc")
    assert L.check(pack, mc, "They're at home.") and not L.check(pack, mc, "They is at home.")


def test_clear_attempt_vs_unclear(pack, gap):
    assert L.clear_attempt(pack, SKILL, gap, "are") and L.clear_attempt(pack, SKILL, gap, "I is 25 years old")
    assert not L.clear_attempt(pack, SKILL, gap, "M.") and not L.clear_attempt(pack, SKILL, gap, "Um")
    assert not L.clear_attempt(pack, SKILL, gap, "banana split")


def run(repo, pack, answers, *, items=None, speak=None, name="ann"):
    pid = repo.find_profile(name)["id"] if repo.find_profile(name) else repo.create_profile(name)
    sid = repo.start_session(pid, "lesson")
    sk, its = L.begin(repo, pack, pid, sid, SKILL)
    its = items or its
    feed, out, spoken = list(answers), [], []
    res = L.run_exercises(repo, pack, pid, sid, sk, its, lambda it, i: feed.pop(0) if feed else None, out.append,
                          now=NOW, speak=spoken.append)
    return res, out, spoken, pid, sid


def test_voice_answer_is_displayed_before_grading_text_answer_is_not(repo, pack, gap):
    _, out, _, *_ = run(repo, pack, [V("I'm 25 years old.")], items=[gap])
    assert any("Usłyszałem" in x and "I'm 25 years old." in x for x in out)
    _, out2, *_ = run(repo, pack, [L.Answer("am")], items=[gap])
    assert not any("Usłyszałem" in x for x in out2)


def test_uncertain_words_are_marked_when_displayed(repo, pack, gap):
    _, out, *_ = run(repo, pack, [V("I am", ["am"]), V("am", [])], items=[gap])
    assert any("niepewne" in x and "am" in x for x in out)


def test_unclear_confident_utterance_asks_to_repeat_and_is_not_an_error(repo, pack, gap):
    res, out, spoken, pid, sid = run(repo, pack, [V("M.", []), V("I am twenty-five years old.", [])], items=[gap])
    assert res.correct == 1 and res.total == 1
    h = repo.attempt_history(pid, SKILL)
    assert len(h) == 1 and h[0]["correct"] == 1 and h[0]["hint_level"] == 0          # bez błędu, bez podpowiedzi
    assert any("I heard" in s and "M." in s for s in spoken)                         # prośba o powtórzenie z echem
    assert not repo.list_errors(pid)


def test_unclear_repeatedly_skips_task_without_recording(repo, pack, gap):
    res, _, _, pid, _ = run(repo, pack, [V("Um", [])] * 5, items=[gap])
    assert res.skipped == 1 and res.total == 0 and repo.attempt_history(pid, SKILL) == []


def test_clear_wrong_form_confident_stt_is_a_real_error_with_hint(repo, pack, gap):
    res, _, spoken, pid, _ = run(repo, pack, [V("are", []), V("am", [])], items=[gap])
    h = repo.attempt_history(pid, SKILL)
    assert res.correct == 1 and len(h) == 1 and h[0]["hint_level"] == 1
    assert any("not quite" in s.lower() for s in spoken)


def test_wrong_but_low_confidence_is_not_an_error(repo, pack, gap):
    res, *_ , pid, _ = run(repo, pack, [V("are", ["are"]), V("am", [])], items=[gap])
    assert repo.attempt_history(pid, SKILL)[0]["hint_level"] == 0


# --- 3. intencje ---
@pytest.mark.parametrize("text,want", [
    ("I think it's basic English knowledge, so we can move on.", "skip"),
    ("Can we skip this?", "skip"),
    ("let's talk about something else", "skip"),
    ("I want to stop the exercise", "skip"),
    ("I don't understand", "help"),
    ("what do you mean?", "help"),
    ("Can you explain it?", "help"),
    ("Can you repeat the question", "help"),
    ("I don't know any Beatrice, but if I would know, she was my friend.", None),
    ("He is a boy and his name is Beatrice.", None),
    ("I move to Warsaw next year", None),
    ("", None),
])
def test_intent_detection(text, want):
    assert I.detect(text) == want


def test_skip_in_exercises_ends_them_without_attempts_or_mastery(repo, pack):
    res, out, spoken, pid, sid = run(repo, pack, [L.Answer("I think it's basic, so we can move on.")])
    assert res.moved_on and res.total == 0 and res.skipped == 0
    assert repo.attempt_history(pid, SKILL) == []
    st = repo.get_skill_state(pid, SKILL)
    assert st is None or (st["status"] != "mastered" and st["mastered_at"] is None)
    assert repo.get_session_plan(pid, sid)["done"] == []                             # lekcja nie jest „zrobiona”
    assert "opanowanie" in L.summary(res).lower() or "nie " in L.summary(res).lower()


def test_correct_answer_containing_intent_words_is_still_graded(repo, pack):
    _, items = L.prepare(pack, SKILL)
    it = items[0]
    res, *_ = run(repo, pack, [L.Answer(it.answers[0])], items=[it])
    assert res.correct == 1 and not res.moved_on


def test_help_request_reexplains_and_repeats_same_task_without_counting_a_try(repo, pack, gap):
    res, out, spoken, pid, _ = run(repo, pack, [L.Answer("I don't understand"), L.Answer("am")], items=[gap])
    h = repo.attempt_history(pid, SKILL)
    assert res.correct == 1 and len(h) == 1 and h[0]["hint_level"] == 0
    assert sum(gap.prompt in x for x in out) == 2                                    # zadanie pokazane ponownie
    assert any("explain" in s.lower() or "example" in s.lower() or "sentence" in s.lower() for s in spoken)


# --- 2. pętla, kontekst, kolejność ---
class Rec(FakeProvider):
    pass


def tutor_for(repo, llm, **kw):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    return VoiceTutor(repo, pid, sid, llm, FakeTTS(), A.SimSink(), **kw), pid, sid


def test_history_is_complete_and_ordered_for_the_llm(repo):
    llm = FakeProvider(chunks=["Is Beatrice your friend? "])
    t, pid, sid = tutor_for(repo, llm)
    t.respond("He is a boy and his name is Beatrice.", input_mode="text")
    t.respond("I don't know any Beatrice.", input_mode="text")
    msgs = llm.calls[1]
    roles = [(m.role, m.content) for m in msgs]
    assert [r for r, _ in roles] == ["system", "user", "assistant", "user"]
    assert roles[2][1] == "Is Beatrice your friend?" and roles[3][1] == "I don't know any Beatrice."


def test_resumed_session_keeps_turn_order(repo):
    llm = FakeProvider(chunks=["Question one? "])
    t, pid, sid = tutor_for(repo, llm)
    t.respond("first", input_mode="text")
    repo.pause_session(pid, sid); repo.resume_session(pid, sid)
    t2 = VoiceTutor(repo, pid, sid, llm, FakeTTS(), A.SimSink())
    t2.respond("second", input_mode="text")
    assert [(m.role, m.content) for m in llm.calls[1]][1:] == [("user", "first"), ("assistant", "Question one?"),
                                                              ("user", "second")]


def test_guard_suppresses_repeated_question_and_keeps_new_content():
    g = Guard(["Is Beatrice your friend or your brother's friend?"])
    assert g("Is Beatrice your friend or your brother's friend?") is None
    assert g("Oh, I see.") == "Oh, I see."
    assert g("Is  Beatrice your friend, or your brother's friend") is None             # drobne różnice nie pomagają


def test_guard_drops_stock_praise_when_recently_used_but_allows_first_time():
    assert Guard([])("You're doing great!") == "You're doing great!"
    g = Guard(["You're doing great! Is Beatrice your friend?"])
    assert g("You're doing great!") is None and g("Where did you go?") == "Where did you go?"
    assert Guard(["Nice."])("Great job!") == "Great job!"


def test_repeated_question_is_not_spoken_and_costs_no_extra_llm_call(repo):
    llm = FakeProvider(chunks=["Is Beatrice your friend? ", "You're doing great! "])
    t, pid, sid = tutor_for(repo, llm)
    t.respond("hi", input_mode="text")
    llm.chunks = ["You're doing great! ", "Is Beatrice your friend? "]
    r = t.respond("I don't know any Beatrice", input_mode="text")
    assert len(llm.calls) == 2                                                         # bez ponownego generowania
    assert "Beatrice" not in r.reply and r.reply                                       # nie powtórzono, ale coś padło
    assert [x["text"] for x in repo.list_turns(pid, sid) if x["role"] == "assistant"][-1] == r.reply


def test_everything_suppressed_falls_back_to_short_neutral_line(repo):
    llm = FakeProvider(chunks=["Is Beatrice your friend? "])
    t, *_ = tutor_for(repo, llm)
    t.respond("hi", input_mode="text")
    r = t.respond("no idea", input_mode="text")
    assert r.reply and "Beatrice" not in r.reply


def test_system_prompt_forbids_stock_praise_and_repeating_questions():
    from tutor.voice.conversation import SYSTEM_PROMPT as S
    s = S.lower()
    assert "do not praise" in s and "repeat" in s and "doing great" in s


def test_lesson_chat_opener_is_in_history_so_llm_knows_what_the_student_answers(env, pack):
    _, items = L.prepare(pack, SKILL)
    conv = FakeProvider(chunks=["Nice. "])
    env.go(Gated({}, *[i.answers[0] for i in items], "My day was lazy", "q"),
           ["--no-audio", "--lesson", SKILL], llm=conv, ev=EvalProv())
    msgs = [(m.role, m.content) for m in conv.calls[0]]
    assert msgs[1][0] == "assistant" and "day" in msgs[1][1].lower() and msgs[-1] == ("user", "My day was lazy")


# --- 3b. intencje w rozmowie ---
def test_conversation_intent_adds_note_for_one_turn_only(repo):
    llm = FakeProvider(chunks=["Sure. "])
    t, pid, sid = tutor_for(repo, llm)
    t.respond("I think it's basic English knowledge, so we can move on.", input_mode="text")
    t.respond("I like football.", input_mode="text")
    first, second = llm.calls[0][0].content, llm.calls[1][0].content
    assert "move on" in first.lower() and "do not" in first.lower() and "move on" not in second.lower()
    t.respond("I don't understand", input_mode="text")
    assert "simpler" in llm.calls[2][0].content.lower()


def test_conversation_intent_never_touches_mastery(env, pack):
    _, items = L.prepare(pack, SKILL)
    env.go(Gated({}, "I think it's basic, so we can move on.", "q"), ["--no-audio", "--lesson", SKILL],
           llm=FakeProvider(chunks=["Sure. "]), ev=EvalProv())
    assert env.repo.attempt_history(env.pid, SKILL) == []
    st = env.repo.get_skill_state(env.pid, SKILL)
    assert st is None or st["status"] != "mastered"


def test_cli_move_on_during_exercises_goes_to_chat_not_quit(env, pack):
    conv = FakeProvider(chunks=["Sure. "])
    code, out = env.go(Gated({}, "we can move on", "Hello", "q"), ["--no-audio", "--lesson", SKILL], llm=conv,
                       ev=EvalProv())
    text = "\n".join(out)
    assert code == 0 and "rozmowa" in text and len(conv.calls) == 1
    assert env.repo.attempt_history(env.pid, SKILL) == []


# --- przegląd F5 przed zamknięciem ---
def test_single_common_word_is_not_a_clear_error(pack, gap):
    for w in ("they", "at", "home", "I"):
        assert not L.clear_attempt(pack, SKILL, gap, w), w            # to raczej błąd rozpoznania niż „odpowiedź”
    assert L.clear_attempt(pack, SKILL, gap, "is") and L.clear_attempt(pack, SKILL, gap, "be")


def test_partial_fragment_without_the_slot_or_with_wrong_form_is_not_accepted(pack, gap):
    for t in ("twenty five years old", "I twenty five", "I is twenty five years old", "am twenty five years"):
        assert not L.check(pack, gap, t) or t.startswith("am"), t
    assert not L.check(pack, gap, "I twenty-five years old") and not L.check(pack, gap, "years old")


def test_long_utterance_is_not_treated_as_intent_in_exercises(repo, pack, gap):
    long = "I could explain this to you but honestly my answer here is that she were twenty five years old today"
    res, _, _, pid, _ = run(repo, pack, [V(long, []), V("am", [])], items=[gap])
    assert not res.moved_on and res.correct == 1


def test_guard_allows_repeating_when_student_asks_for_it(repo):
    llm = FakeProvider(chunks=["Is Beatrice your friend? "])
    t, pid, sid = tutor_for(repo, llm)
    t.respond("hi", input_mode="text")
    r = t.respond("Can you repeat the question?", input_mode="text")
    assert "Beatrice" in r.reply
