"""F7 jakość: intencje ucznia. Koniec sesji ma pierwszeństwo przed nowym tematem; przypadkowe „finish” nie kończy."""
import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tutor.app import intent as I


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


FINISH = [
    "No, I want to finish our conversation for now.",       # zgłoszone w teście użytkownika
    "I want to finished conversation",                       # błąd gramatyczny / STT
    "i wanna stop now", "Lets stop here.", "can we finish for today?", "That is all for today",
    "Thats all for now, thanks", "Bye!", "OK, goodbye", "see you later", "I have to go now, sorry.",
    "I need to go.", "Please end the session.", "stop the conversation please", "I am done for today", "Im done",
    "Stop.", "Enough, please", "We can finish now", "I would like to end the lesson", "I think we should stop here",
]
NOT_FINISH = [
    "I want to finish my project this week.", "When do you finish work?", "I finished work at five.",
    "I don't want to stop talking.", "I had to stop the car", "I have to go to work tomorrow",
    "I want to end up in Spain", "We should never stop learning", "I am done with my homework",
    "He said goodbye to his friends and left the station after a long day", "I would like to stop smoking",
    "The film ends at nine", "My shift finishes at seven, then I go home.",
]


@pytest.mark.parametrize("text", FINISH)
def test_finish_detected(text):
    assert I.classify(text) == "finish" and I.detect(text) == "finish"


@pytest.mark.parametrize("text", NOT_FINISH)
def test_accidental_finish_word_is_not_a_finish_request(text):
    assert I.classify(text) != "finish"


@pytest.mark.parametrize("text,want", [
    ("Let's change the topic", "change_topic"), ("Can we talk about something else?", "change_topic"),
    ("Can you repeat that?", "repeat"), ("Sorry, I didn't catch that", "repeat"),
    ("What does booking mean?", "explain"), ("Could you explain that word?", "explain"),
    ("I don't understand", "help"), ("Can we skip this?", "skip"), ("I want to stop the exercise", "skip"),
    ("I don't know", "unknown"), ("I like swimming in the lake.", None),
])
def test_fine_intents(text, want):
    assert I.classify(text) == want


def test_repeat_and_explain_have_distinct_notes():
    assert I.NOTES["repeat"] != I.NOTES["explain"] != I.NOTES["help"]


def test_chat_finish_ends_session_without_new_topic(env):
    conv = FakeProvider(chunks=["Ok. "])
    code, out = env.go(Gated({}, "I like tea", "No, I want to finish our conversation for now.", "more text"),
                       ["--no-audio", "--chat", "fd.favorite"], llm=conv, ev=EvalProv())
    plan = env.repo.get_session_plan(env.pid, env.repo.list_sessions(env.pid)[0]["id"])
    assert code == 0 and len(plan["topics"]) == 1 and not any("nowy temat" in x for x in out)
    assert len(conv.calls) == 1                                 # na prośbę o koniec nie ma kolejnej odpowiedzi LLM
    assert any("stop here" in x for x in out)
    assert "more text" not in [t["text"] for t in env.users()]


def test_chat_accidental_finish_continues(env):
    conv = FakeProvider(chunks=["Ok. "])
    env.go(Gated({}, "I want to finish my project this week.", "q"), ["--no-audio", "--chat", "fd.favorite"],
           llm=conv, ev=EvalProv())
    assert len(conv.calls) == 1
