"""F7 audyt nauczyciela: poprawki potwierdzone w rozmowie z Qwen3 8B (prośba o temat, „nie rozumiem”, formułki)."""
import pytest

from tutor.app import intent as INTENT
from tutor.voice.guard import Guard


@pytest.mark.parametrize("text,topic", [
    ("Can we talk about something else? Maybe travel.", "travel"),
    ("Let's talk about my job, please", "my job"),
    ("Can we change the topic to football?", "football"),
    ("Can we change the topic? How about music instead?", "music"),
    ("I'd like to switch to films", "films"),
])
def test_requested_topic_is_extracted(text, topic):
    assert INTENT.requested_topic(text) == topic


@pytest.mark.parametrize("text", ["Can we change the topic?", "Can we talk about something else?",
                                  "Let's move on.", "New topic please", "Can we talk about it later? I'm tired",
                                  "My dad likes to talk about politics.", "Maybe I will cook pasta tomorrow."])
def test_no_topic_named_means_random(text):
    assert INTENT.requested_topic(text) is None


def test_repeat_request_differs_from_not_understanding():
    assert INTENT.wants_repeat("Could you repeat that, please?")
    assert INTENT.wants_repeat("Sorry, I didn't catch that")
    assert not INTENT.wants_repeat("Sorry, I don't understand what you mean.")
    assert not INTENT.wants_repeat("Could you explain that in simpler words?")


def test_guard_blocks_verbatim_repeat_from_older_replies():
    old = ["That's a shame — cooking is so rewarding! Do you use any gadgets to help you cook faster?",
           "Nice.", "Where do you live?", "Ok.", "What do you do?", "Cool."]
    g = Guard(old)
    assert g("Do you use any gadgets to help you cook faster?") is None
    assert g("Which city did you like most?") == "Which city did you like most?"


def test_guard_allows_repeat_only_when_asked():
    g = Guard(["Do you like pasta?"], repeats=False)
    assert g("Do you like pasta?") == "Do you like pasta?"


@pytest.mark.parametrize("phrase", ["That sounds delicious!", "That sounds amazing!", "That's interesting!",
                                    "That's a great point!"])
def test_formulaic_reaction_not_in_every_reply(phrase):
    assert Guard(["That sounds fun! Where did you go?"])(phrase) is None      # była w ostatniej odpowiedzi
    assert Guard(["Where did you go?", "Ok.", "Right."])(phrase) == phrase       # dawno nie było: wolno
