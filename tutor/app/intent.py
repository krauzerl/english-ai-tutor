"""Jasne sygnały ucznia (F5.11b) wykrywane regułami — bez LLM i bez klasyfikatora.

`skip` = chce przejść dalej / zmienić temat / zakończyć ćwiczenia; `help` = nie rozumie albo prosi o wyjaśnienie.
Sygnał zmienia tylko przebieg rozmowy; NIGDY nie jest dowodem opanowania umiejętności (nic nie trafia do mastery).
"""
from __future__ import annotations

import re

_SKIP = re.compile(
    r"\b(move on|moving on|(can we|let'?s|i want to|i'd like to|we can) skip|skip (this|it|that|the)"
    r"|next (one|question|task|exercise|topic)|something else|(change|different|new) (the )?(topic|subject)"
    r"|(stop|end|finish|quit) (the |this |these )?(exercises?|lesson|task|practice)"
    r"|(i )?(want|would like) to (stop|finish|end)|let'?s (stop|finish|end)|too easy|that'?s enough)\b", re.I)
_HELP = re.compile(
    r"\b(i (do not|don'?t|didn'?t|did not|can'?t) (really )?(understand|get it)|don'?t get it|what do you mean"
    r"|i'?m (confused|lost)|(can|could|would) you (please )?(explain|repeat|say (that|it) again|rephrase)"
    r"|explain|repeat (that|the question|please)|say (that|it) again)\b", re.I)


_UNKNOWN = re.compile(r"\b(i (do not|don'?t) know|no idea|i have no idea|i'?m not sure|not sure)\b", re.I)


_REPEAT = re.compile(r"\b(repeat|say (that|it) again|once more|one more time|didn'?t (hear|catch))\b", re.I)
_TOPIC = re.compile(      # prośba o konkretny temat: „let's talk about X”, „change the topic to X”, „switch to X”
    r"(?:(?:let'?s|let us|can we|could we|shall we|i want to|i'?d like to|i would like to|we can)\s+"
    r"(?:talk|chat|speak|switch|move on)\s+(?:about|to)|change the (?:topic|subject) to)\s+(?P<a>[^.?!,;]{2,60})", re.I)
_MAYBE = re.compile(r"(?:^|[.?!,;]\s*)(?:maybe|how about|what about|perhaps)\s+(?P<a>[^.?!,;]{2,60})", re.I)
_NOT_TOPIC = re.compile(r"^(something|anything|it|this|that|the topic|another topic|a different topic|other things?|"
                        r"else|something else)\b", re.I)


def wants_repeat(text: str) -> bool:
    """Prośba o powtórzenie (wtedy powtórka zdania jest właściwa); „nie rozumiem” to prośba o inne słowa."""
    return bool(_REPEAT.search(text.replace("’", "'")))


def requested_topic(text: str) -> str | None:
    """Temat wskazany w prośbie o zmianę („let's talk about my job”; „Maybe travel” tylko obok prośby o zmianę tematu)
    albo None (wtedy temat losujemy). Zwykłe zdania o rozmowach („My dad talks about politics”) nie są prośbą."""
    t0 = text.replace("’", "'")
    pats = [_TOPIC] + ([_MAYBE] if detect(t0) == "skip" else [])
    for m in (m for pat in pats for m in pat.finditer(t0)):
        t = " ".join(m["a"].split()).strip(" '\"")
        t = re.sub(r"\s+(please|instead|now|then)$", "", t, flags=re.I)
        if t and not _NOT_TOPIC.match(t) and len(t.split()) <= 6:
            return t
    return None


def detect(text: str) -> str | None:
    """skip | help | unknown (krótkie „nie wiem”: brak odpowiedzi, nie błąd językowy) | None."""
    t = text.replace("’", "'")
    if _SKIP.search(t):
        return "skip"
    if _HELP.search(t):
        return "help"
    if len(t.split()) <= 6 and _UNKNOWN.search(t):
        return "unknown"
    return None


NOTES = {
    "skip": (" Student signal: they want to move on, change the subject or stop practising. Acknowledge it in a few "
             "words, do not keep drilling the same grammar, and switch to a new everyday topic with ONE question. "
             "Do not say they have mastered anything."),
    "help": (" Student signal: they did not understand or want an explanation. Rephrase your last point in simpler "
             "words, one short sentence, then ask ONE very easy question. Do not repeat the same sentence."),
}
