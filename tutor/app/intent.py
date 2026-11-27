"""Jasne sygnały ucznia wykrywane regułami — bez LLM i bez klasyfikatora.

`classify` zwraca szczegółową intencję: finish (koniec sesji), change_topic, skip (dalej / za łatwe), repeat,
explain, help (nie rozumiem), unknown („nie wiem”) albo None. `detect` to zgrubna wersja dla ćwiczeń
(finish | skip | help | unknown). Reguły są odporne na typowe błędy gramatyczne i zapis STT („wanna”, „finished”,
brak apostrofu). Sygnał zmienia tylko przebieg rozmowy; NIGDY nie jest dowodem opanowania (nic nie trafia do mastery).
"""
from __future__ import annotations

import re

_V_END = r"(?:finish(?:ed|ing)?|stop(?:ped|ping)?|end(?:ed|ing)?|quit|wrap(?:\s+it)?\s+up|close)"
# Co kończymy: rozmowę/sesję albo „na teraz”. Ćwiczenia/zadania to `skip` (przejście dalej), nie koniec sesji.
_TAIL_OK = re.compile(
    r"^\s*(?:(?:the|this|our|my|a|that)\s+)?(?:conversation|chat|talk|talking|session|lesson|class|here|now|today|"
    r"it|everything|for\s+(?:now|today|the\s+day|this\s+time|a\s+while)|already|please|soon|then|right\s+now)?"
    r"\s*(?:for\s+(?:now|today|the\s+day|this\s+time)|now|here|please|today|then)?\s*$", re.I)
_TAIL_EX = re.compile(r"^\s*(?:(?:the|this|these|my)\s+)?(?:exercises?|tasks?|practi[cs]e|questions?|quiz)\b", re.I)
_WANT = re.compile(
    r"\b(?:i|we|i'?d|we'?d)\s*(?:really\s+|just\s+)?(?:want|wanna|would\s+like|'d\s+like|like|need|have|got|gotta|"
    r"wish|prefer)\s*(?:to\s+)?" + _V_END + r"(?P<tail>[^.?!;]*)", re.I)
_LETS = re.compile(
    r"\b(?:let'?s|let\s+us|lets|can\s+we|could\s+we|shall\s+we|we\s+can|we\s+could|we\s+should|maybe\s+we|"
    r"please|i\s+think\s+we\s+(?:can|should))\s+(?:just\s+)?" + _V_END + r"(?P<tail>[^.?!;]*)", re.I)
_IMPER = re.compile(r"\b" + _V_END + r"\s+(?:the|this|our)\s+(?:conversation|chat|session|lesson|talk)\b", re.I)
_DONE = re.compile(r"\b(?:i'?m|i\s+am|we'?re|we\s+are)\s+(?:done|finished)(?P<tail>[^.?!;]*)", re.I)
_GO = re.compile(r"\b(?:i|we)\s+(?:have\s+to|need\s+to|must|gotta|got\s+to|should)\s+go(?P<tail>[^.?!;]*)", re.I)
_ENOUGH = re.compile(r"\b(?:that'?s|that\s+is|this\s+is|it'?s)\s+(?:all|enough|it)\s+for\s+(?:now|today)\b", re.I)
_BYE = re.compile(r"^\W*(?:(?:ok(?:ay)?|so|well|thanks?|thank\s+you)[\s,!.]*)*(?:good\s*bye|bye(?:\s*bye)?|"
                  r"see\s+you(?:\s+(?:later|next\s+time|tomorrow|soon))?|talk\s+to\s+you\s+later)\b", re.I)
_BARE = re.compile(r"^\W*(?:no|ok(?:ay)?|so|please|right)?[\s,]*(?:stop|finish|end|quit|enough)"
                   r"(?:[\s,]+(?:please|now|here|it))?\W*$", re.I)
_NEG = re.compile(r"\b(?:don'?t|do\s+not|doesn'?t|didn'?t|not|never|can'?t|cannot)\s+(?:want\s+to\s+|wanna\s+|"
                  r"need\s+to\s+|have\s+to\s+)?(?:" + _V_END + r"|go)\b", re.I)

_TOPIC_CHANGE = re.compile(
    r"\b(?:(?:change|switch)\s+(?:the\s+)?(?:topic|subject)|(?:different|new|another|other)\s+(?:topic|subject)|"
    r"talk\s+about\s+something\s+else|something\s+else|(?:next|another)\s+(?:topic|scenario|situation))\b", re.I)
_SKIP = re.compile(
    r"\b(move on|moving on|(can we|let'?s|i want to|i'd like to|we can) skip|skip (this|it|that|the)"
    r"|next (one|question|task|exercise)|(stop|end|finish|quit) (the |this |these )?(exercises?|tasks?|practice)"
    r"|too easy|that'?s enough)\b", re.I)
_REPEAT = re.compile(r"\b(repeat|say (that|it) again|once more|one more time|didn'?t (hear|catch)|pardon\??$)\b", re.I)
_EXPLAIN = re.compile(r"\b(explain|what does (?:the word |the phrase )?\S+(?: \S+)? mean|what is the meaning of|"
                      r"what'?s the meaning of|meaning of the word|what do you mean by)\b", re.I)
_HELP = re.compile(
    r"\b(i (do not|don'?t|didn'?t|did not|can'?t|cannot) (really )?(understand|get it)|don'?t get it|what do you mean"
    r"|i'?m (confused|lost)|(can|could|would) you (please )?(rephrase|say it (more )?simpl(y|er))|"
    r"(simpler|easier) (words|english))\b", re.I)
_UNKNOWN = re.compile(r"\b(i (do not|don'?t) know|no idea|i have no idea|i'?m not sure|not sure)\b", re.I)

_TOPIC = re.compile(      # prośba o konkretny temat: „let's talk about X”, „change the topic to X”, „switch to X”
    r"(?:(?:let'?s|let us|can we|could we|shall we|i want to|i'?d like to|i would like to|we can)\s+"
    r"(?:talk|chat|speak|switch|move on)\s+(?:about|to)|change the (?:topic|subject) to)\s+(?P<a>[^.?!,;]{2,60})", re.I)
_MAYBE = re.compile(r"(?:^|[.?!,;]\s*)(?:maybe|how about|what about|perhaps)\s+(?P<a>[^.?!,;]{2,60})", re.I)
_NOT_TOPIC = re.compile(r"^(something|anything|it|this|that|the topic|another topic|a different topic|other things?|"
                        r"else|something else)\b", re.I)


def _norm(text: str) -> str:
    t = text.replace("’", "'").replace("`", "'")
    return re.sub(r"\s+", " ", t).strip()


def _tail_ok(tail: str) -> bool:
    return bool(_TAIL_OK.match(tail)) and not _TAIL_EX.match(tail)


def wants_finish(text: str) -> bool:
    """Prośba o zakończenie sesji („No, I want to finish our conversation for now”, „let's stop here”, „bye”).
    Nie: „I want to finish my project”, „When do you finish work?”, „I don't want to stop”, „stop the exercise”."""
    t = _norm(text)
    if not t or _NEG.search(t):
        return False
    if _ENOUGH.search(t) or _IMPER.search(t) or _BARE.match(t):
        return True
    if _BYE.match(t) and len(t.split()) <= 8:
        return True
    for pat in (_WANT, _LETS, _DONE):
        for m in pat.finditer(t):
            if _tail_ok(m["tail"]):
                return True
    m = _GO.search(t)
    return bool(m and re.match(r"^\s*(?:now|soon|sorry|already|,|bye|right now|for now)?[\s,]*(?:sorry|bye)?\s*$",
                               m["tail"], re.I))


def wants_repeat(text: str) -> bool:
    """Prośba o powtórzenie (wtedy powtórka zdania jest właściwa); „nie rozumiem” to prośba o inne słowa."""
    return bool(_REPEAT.search(_norm(text)))


def classify(text: str) -> str | None:
    """finish | change_topic | skip | repeat | explain | help | unknown | None. Koniec sesji ma pierwszeństwo."""
    t = _norm(text)
    if not t:
        return None
    if wants_finish(t):
        return "finish"
    if _TOPIC_CHANGE.search(t):
        return "change_topic"
    if _SKIP.search(t):
        return "skip"
    if _REPEAT.search(t):
        return "repeat"
    if _EXPLAIN.search(t):
        return "explain"
    if _HELP.search(t):
        return "help"
    if len(t.split()) <= 6 and _UNKNOWN.search(t):
        return "unknown"
    return None


_COARSE = {"finish": "finish", "change_topic": "skip", "skip": "skip", "repeat": "help", "explain": "help",
           "help": "help", "unknown": "unknown"}


def detect(text: str) -> str | None:
    """finish | skip | help | unknown (krótkie „nie wiem”: brak odpowiedzi, nie błąd językowy) | None."""
    return _COARSE.get(classify(text) or "")


# Pilot: pytanie o życie nauczyciela („What do you usually do on weekends?”, „Have you ever been there?”). Qwen3 8B
# odpowiadał wtedy zmyślonym doświadczeniem mimo zakazu w prompcie (pomiar 6/20). Prośby o pomoc („can you repeat”,
# „do you know what X means”) NIE są pytaniem o nauczyciela.
_ABOUT_YOU = re.compile(
    r"\b(?:what|how|where|when) (?:do|did) you (?:usually |normally |often )?(?:do|like|enjoy|eat|cook|spend|go)\b"
    r"|\b(?:do|did) you (?:usually |ever |often |also |really )?(?:like|love|enjoy|prefer|have (?:a|any|kids|children|"
    r"pets?|family|hobb)|live|work|cook|travel|play|watch|go|eat|drink|spend|visit)\b"
    r"|\bhave you (?:ever|been|tried|seen|visited|travelled|traveled)\b|\bare you (?:married|tired|from|a fan)\b"
    r"|\b(?:what|how) about you\b|\band you\s*\?|\byour (?:weekend|hobby|hobbies|favou?rite|family|childhood|"
    r"holiday|vacation|day|life)\b", re.I)


def asks_about_tutor(text: str) -> bool:
    """Uczeń pyta nauczyciela o jego życie/upodobania (nie o pomoc ani znaczenie słowa)."""
    t = _norm(text)
    return bool(_ABOUT_YOU.search(t)) and not re.search(r"\b(?:can|could|would) you\b|\bdo you know\b", t, re.I)


PERSONA_NOTE = ("(Tutor note: the student asked about you personally. You are an AI, so you have no weekends, "
                "hobbies, tastes, family or memories: say that in a few friendly words, then answer with a general "
                "view or what many people do.)")


def requested_topic(text: str) -> str | None:
    """Temat wskazany w prośbie o zmianę („let's talk about my job”; „Maybe travel” tylko obok prośby o zmianę tematu)
    albo None (wtedy temat losujemy). Zwykłe zdania o rozmowach („My dad talks about politics”) nie są prośbą."""
    t0 = _norm(text)
    pats = [_TOPIC] + ([_MAYBE] if classify(t0) in ("change_topic", "skip") else [])
    for m in (m for pat in pats for m in pat.finditer(t0)):
        t = " ".join(m["a"].split()).strip(" '\"")
        t = re.sub(r"\s+(please|instead|now|then)$", "", t, flags=re.I)
        if t and not _NOT_TOPIC.match(t) and len(t.split()) <= 6:
            return t
    return None


NOTES = {
    "skip": (" Student signal: they want to move on, change the subject or stop practising. Acknowledge it in a few "
             "words, do not keep drilling the same grammar, and switch to a new everyday topic with ONE question. "
             "Do not say they have mastered anything."),
    "change_topic": (" Student signal: they want a different topic. Acknowledge it in a few words and move to the "
                     "new topic with ONE question."),
    "repeat": (" Student signal: they asked you to repeat. Say your last point again, more slowly and in the same "
               "or slightly simpler words. Do not add a new question."),
    "explain": (" Student signal: they asked what something means. Explain only that word or phrase in one or two "
                "simple sentences with one short example, then return to the conversation."),
    "help": (" Student signal: they did not understand. Rephrase your last point in simpler words, one short "
             "sentence, then ask ONE very easy question. Do not repeat the same sentence."),
}


# Smart corrections: Qwen3 w dłuższej rozmowie sam komentował i poprawiał język ucznia mimo zakazu w prompcie
# systemowym („Arrived to the cinema is a bit awkward…”), także poprawne zdania. Notatka przy wiadomości ucznia
# (jak PERSONA_NOTE) działa lepiej niż w prompcie systemowym; korekty pokazuje tylko zwalidowana ścieżka oceny.
NO_CORRECT_NOTE = ("(Tutor note: in this reply do not comment on, praise or correct the student's English, words or "
                   "phrases; just react to what they said.)")
