"""F7 wiarygodność oceniania: przypadki z testu właściciela (fałszywe korekty, korekty bez zmiany, wyjaśnienia)."""
import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tutor.app import feedback as FB
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import errors as ER
from tutor.pedagogy.schemas import Obs

PACK = C.load("en")


def cls(text, span, fix, cat, mode="text", low=()):
    o = Obs(s=span, f=fix, k="error", c=cat, v=2, p="h")
    return A.classify(o, text, input_mode=mode, low_prob_words=set(low), pre=A.prefilter(text, PACK.disfluency),
                      variants=PACK.variants, confusables=PACK.confusables,
                      taxonomy=ER.allowed_categories(PACK.errors), rubric=PACK.rubric)


@pytest.mark.parametrize("text,span,fix", [
    ("We have ten paying customers.", "have", "had"),                        # poprawne zdanie: inny czas ≠ błąd
    ("We have ten paying customers.", "We have", "We had"),
    ("She is my best friend.", "is", "was"),
    ("I use my phone to book tickets.", "use", "used"),
])
def test_tense_change_without_time_context_is_dropped(text, span, fix):
    c = cls(text, span, fix, "tense.past_simple")
    assert (c.status, c.drop_reason) == ("dropped", "unsupported_tense")


@pytest.mark.parametrize("text,span,fix", [
    ("Yesterday we have ten customers.", "have", "had"),                     # znacznik przeszłości
    ("I went to Rome and I have a great time.", "have", "had"),              # spójność z innym czasownikiem
    ("Two years ago I work in a bank.", "work", "worked"),
])
def test_tense_change_with_past_context_is_kept(text, span, fix):
    assert cls(text, span, fix, "tense.past_simple").status == "valid"


def test_correction_identical_to_original_is_dropped():
    text = "We use booking come to reserve our state for a week."
    assert cls(text, "come to reserve", "come to reserve", "word_choice").drop_reason == "fix_equals_span"
    assert cls(text, "come to reserve", "come  to reserve.", "word_choice").drop_reason == "fix_equals_span"


def test_real_error_still_reported():
    c = cls("She have a dog.", "have", "has", "agreement.subject_verb")
    assert c.status == "valid"


def test_uncertain_stt_word_is_suspect_not_error():
    text = "We use booking come to reserve our stay."
    c = cls(text, "booking come", "Booking.com", "word_choice", mode="voice", low=["come"])
    assert c.kind == "stt_suspect" or c.status == "dropped"


@pytest.mark.parametrize("span,fix,cat,want", [
    ("I'm paramedic", "I'm a paramedic", "article.missing", "rodzajnik „a”"),
    ("She have", "She has", "agreement.subject_verb", "mówimy „has”"),
    ("He work", "He works", "agreement.subject_verb", "końcówkę -s"),
    ("I goed", "I went", "morphology.irregular_past", "nieregularny"),
    ("in Monday", "on Monday", "preposition.time", "przyimka „on”"),
    ("the life is hard", "life is hard", "article.extra", "zbędny"),
])
def test_explanation_matches_the_actual_edit(span, fix, cat, want):
    assert want in FB.explain_edit(PACK, span, fix, cat)


def test_unknown_pattern_falls_back_to_category_explanation():
    t = FB.explain_edit(PACK, "make a photo", "take a photo", "collocation")
    assert "take a photo" in t


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def test_summary_states_incomplete_evaluation(repo):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "chat")
    assert "niekompletna" in FB.summary_lines(repo, PACK, pid, sid, pending=2)[0]
    assert FB.summary_lines(repo, PACK, pid, sid, pending=0) == []


def test_roleplay_does_not_interrupt_with_corrections(env):
    conv = FakeProvider(chunks=["Ok. "])
    env.go(Gated({1: lambda: env.applied() >= 1}, "I goed home", "And then", "q"),
           ["--no-audio", "--chat", "x", "--chat-mode", "roleplay", "--summary-wait", "5"],
           llm=conv, ev=EvalProv())
    assert all("went" not in c[0].content for c in conv.calls)               # recast nie przerywa scenariusza


def test_balanced_default_recasts_in_conversation(env):
    conv = FakeProvider(chunks=["Ok. "])
    env.go(Gated({1: lambda: env.applied() >= 1}, "I goed home yesterday", "And then", "q"),
           ["--no-audio", "--summary-wait", "5"], llm=conv, ev=EvalProv())
    assert "went" in conv.calls[0][0].content                                   # recast w odpowiedzi na tę wypowiedź


def test_noun_number_change_is_not_explained_as_verb_ending():
    """Audyt F7: „medicines” → „medicine” dostało wyjaśnienie o końcówce czasownika."""
    t = FB.explain_edit(PACK, "medicines", "medicine", "agreement.number")
    assert "czasownik" not in t and "pojedyncza" in t
    assert "mnoga" in FB.explain_edit(PACK, "two cat", "two cats", "agreement.number")
    assert "końcówkę -s" in FB.explain_edit(PACK, "He work", "He works", "agreement.subject_verb")
