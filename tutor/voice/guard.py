"""Zabezpieczenie odpowiedzi tutora (F5.11b), bez dodatkowego wywołania LLM: filtruje zdania w strumieniu.

1. Uporczywe powtarzanie: zdanie identyczne (po normalizacji) z zdaniem z ostatnich odpowiedzi tutora jest pomijane.
2. Mechaniczne pochwały („You're doing great!”): pomijane, gdy któraś z ostatnich odpowiedzi już taką miała.
3. (F7) Krótki wykrzyknik na początku odpowiedzi („That sounds intense!”) jest pomijany, gdy poprzednia odpowiedź też
   tak się zaczynała — Qwen3 8B ignorował tę instrukcję w prompcie (schemat „wykrzyknik → pytanie”).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

_STOCK = re.compile(
    r"^\W*((you'?re|you are) (doing )?(great|amazing|fantastic|awesome|wonderful|really well|so well)"
    r"|(great|good|excellent|fantastic|amazing|awesome|wonderful) (job|work)\b|well done\b"
    r"|(that'?s|that is) (great|excellent|fantastic|wonderful|amazing|perfect|interesting|awesome|lovely|so cool"
    r"|a great point)"
    r"|that sounds (great|amazing|fantastic|wonderful|lovely|delicious|fun|interesting|nice|awesome|exciting))", re.I)
_SPLIT = re.compile(r"(?<=[.!?])\s+")


_EVAL = re.compile(r"^\W*(?:(?:that|this|it)(?:'s|’s| is| sounds| must| seems)|what an?\b|wow\b|oh\b|how\b)", re.I)
_HEAD = re.compile(r"^[^—–.!?]{0,70}?(?:\s[—–-]\s|!\s+)")


def _excl(s: str) -> bool:
    s = s.strip()
    return (s.endswith("!") and len(s.split()) <= 7) or bool(_EVAL.match(s))


def _n(s: str) -> str:
    return " ".join(re.findall(r"[\w']+", s.replace("’", "'").lower()))


class Guard:
    def __init__(self, previous_replies: list[str], repeats: bool = True, praise_window: int = 2):
        """`previous_replies`: ostatnie odpowiedzi tutora (od najstarszej). Powtórki sprawdzamy na całej liście,
        formułki pochwał tylko w `praise_window` ostatnich (jedna na kilka odpowiedzi jest naturalna)."""
        sents = [s for r in previous_replies for s in _SPLIT.split(r) if s.strip()]
        self.seen = [n for s in sents if len((n := _n(s)).split()) >= 3]
        last = previous_replies[-praise_window:] if praise_window else []
        recent = [s for r in last for s in _SPLIT.split(r) if s.strip()]
        self.praised = any(_STOCK.match(s.strip()) for s in recent)
        self.dropped = 0
        self.first = True
        self.prev_excl = bool(previous_replies) and _excl(_SPLIT.split(previous_replies[-1].strip())[0])
        self.check_repeats = repeats      # False: uczeń prosi o powtórzenie/wyjaśnienie, więc powtórka jest właściwa

    def __call__(self, sentence: str) -> str | None:
        first, self.first = self.first, False
        if first and self.prev_excl and _excl(sentence):
            m = _HEAD.match(sentence.strip())
            rest = sentence.strip()[m.end():].strip() if m else ""
            if rest and len(rest.split()) >= 3:      # „That's amazing — helping people…” → „Helping people…”
                return rest[0].upper() + rest[1:]
            self.dropped += 1
            self.first = True                  # następne zdanie staje się początkiem odpowiedzi
            return None
        if self.praised and _STOCK.match(sentence.strip()):
            self.dropped += 1
            return None
        n = _n(sentence)
        if self.check_repeats and len(n.split()) >= 3 and \
                any(SequenceMatcher(None, n, s).ratio() >= 0.9 for s in self.seen):
            self.dropped += 1
            return None
        return sentence
