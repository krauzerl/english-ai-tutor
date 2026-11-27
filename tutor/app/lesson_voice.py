"""Komunikaty głosowe lekcji (F5.11): krótkie, angielskie, składane z danych zadania — bez LLM i bez czytania
polskiego materiału (głos `bf_emma` jest angielski). Pełny tekst zostaje na ekranie jako pomoc."""
from __future__ import annotations

import re

from tutor.app import lesson as L
from tutor.pedagogy import content as C
from tutor.voice.text import clean_for_speech

_SCREEN_ONLY = ("translate_pl", "listening_mc", "dictation", "reading_mc")
_PL = re.compile("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]")


def clean(text: str) -> str:
    return clean_for_speech(text)


def _topic(sk: C.Skill) -> str:
    # shortcut: paczka nie ma angielskiej nazwy celu, bierzemy ją z id; upgrade: pole `title_en` w Skill
    return sk.id.rsplit(".", 1)[-1].replace("_", " ")


def greeting(sk: C.Skill) -> str:
    return f"Hello! Today we practise: {_topic(sk)}. First, a quick explanation."


def greeting_check(sk: C.Skill) -> str:
    return f"Hello! Today we work on: {_topic(sk)}. First, a short check without hints."


def welcome_back() -> str:
    return "Welcome back. Let's continue where we stopped."


def explanation(pack: C.Pack, sk: C.Skill) -> list[str]:
    ex = L._examples(pack, sk)
    parts = ["Listen to some correct sentences."] if ex else []
    return [*parts, *ex, "The full explanation is on your screen. Now let's practise."]


def _english(text: str) -> bool:
    return text.isascii() or not _PL.search(text)


PAUSE = "\n\n"       # granica części komunikatu: TTS robi tu wyraźną pauzę (`VoiceTutor.say`)


def task(item: C.Item, idx: int, n: int) -> str:
    """Instrukcja, zadanie, każda opcja i polecenie osobno, z pauzami (test właściciela: całe ćwiczenie jednym
    ciągiem było nieczytelne ze słuchu)."""
    head = f"Task {idx + 1} of {n}."
    if item.type in _SCREEN_ONLY or item.stimulus or not _english(item.prompt):
        return PAUSE.join([head, "Look at the screen for this task.", "Then say your answer as a whole sentence."])
    prompt = item.prompt.replace("___", ", blank, ") if item.type == "gap" else item.prompt
    how = {"gap": "Fill in the blank.", "mc": "Choose the correct answer."}.get(item.type)
    opts = [f"{'ABCDEFGH'[k]}. {o}." for k, o in enumerate(item.options or [])]
    parts = [head, how, " ".join(prompt.split()), *opts, "Say the whole sentence."]
    return PAUSE.join(p for p in parts if p)


def correct(tries: int) -> str:
    return "Correct, after a hint!" if tries else "Correct!"


def retry() -> str:
    return "Not quite. Check the form and try once more. Say the whole sentence."


def reveal(item: C.Item) -> str:
    gap = item.type == "gap" and "___" in item.prompt
    ans = item.prompt.replace("___", item.answers[0]) if gap else item.answers[0]
    return f"The correct answer is: {ans}"


def reask(heard: str = "") -> str:
    said = f"I heard: {heard}. " if heard.strip() else ""
    return f"{said}Sorry, I'm not sure I heard you correctly. Please say the whole sentence again."


def help_(examples: list[str]) -> str:
    return "No problem. Here are some correct examples. " + " ".join(examples) + " Let's try the task again."


def stop_exercises() -> str:
    return "Okay, we'll stop the exercises here."


def silence() -> str:
    return "Sorry, I didn't catch anything. Please try again."


def skipped() -> str:
    return "Let's leave this one for now. We can come back to it later."


CHAT_Q = "How was your day?"


def chat_start(correct_n: int, total: int) -> str:
    score = f"Well done. You got {correct_n} out of {total}. " if total else "Okay. "
    return score + "Now let's chat for a bit."


def farewell(notes: bool) -> str:
    return "Good work today. " + ("I left a few notes on your screen. " if notes else "") + "See you next time."
