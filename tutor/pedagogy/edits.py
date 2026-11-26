"""Minimalne edycje korekt (F4.7). Czyste funkcje, tylko stdlib.

Korekty porównujemy po rzeczywistych zmianach tekstu (różnica tokenów oryginał → poprawiony tekst), a nie po
wskazanych zakresach: „She have a dog.” → „She has a dog.” i „have” → „has” to ta sama edycja.
Offsety: Python liczy znaki (punkty kodowe), LanguageTool (Java) jednostki UTF-16 — `utf16_index` przelicza.
Tekst wypowiedzi jest kanoniczny (NFC, `turn_eval`); `canon` dla cytatów/poprawek dodatkowo ujednolica apostrofy
i cudzysłowy (zamiana 1:1, długość bez zmian, więc offsety w tekście zostają ważne).
"""
from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass

_Q = str.maketrans({"’": "'", "‘": "'", "ʼ": "'", "`": "'", "“": '"', "”": '"', "„": '"'})
_TOK = re.compile(r"\w+(?:'\w+)*|[^\w\s]")


def canon(s: str) -> str:
    return unicodedata.normalize("NFC", s).translate(_Q)


def quotes(s: str) -> str:
    """Tylko zamiana cudzysłowów/apostrofów (zachowuje długość i offsety)."""
    return s.translate(_Q)


def word_bounds(text: str, a: int, b: int) -> tuple[int, int]:
    """Rozszerza [a, b) do granic tokenów, które przecina (offsety zewnętrznych narzędzi bywają podsłowne)."""
    for s, e, _ in _toks(text):
        if s < a < e:
            a = s
        if s < b < e:
            b = e
    return a, b


def utf16_index(text: str, units: int) -> int:
    """Offset w jednostkach UTF-16 (Java, LanguageTool) → indeks znaku w Pythonie."""
    n = 0
    for i, ch in enumerate(text):
        if n >= units:
            return i
        n += 2 if ord(ch) > 0xFFFF else 1
    return len(text)


def _toks(text: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in _TOK.finditer(quotes(text))]


@dataclass(frozen=True)
class Edit:
    a: int          # zakres w oryginale [a, b); a == b: wstawienie przed znakiem a
    b: int
    old: tuple[str, ...]
    new: tuple[str, ...]

    @property
    def key(self) -> tuple:
        return self.a, self.b, tuple(t.casefold() for t in self.new)


def find_spans(text: str, span: str) -> list[tuple[int, int]]:
    """Wszystkie wystąpienia `span` w `text` (wielkość liter, białe znaki, apostrofy/cudzysłowy i NFC bez znaczenia)."""
    toks = [re.escape(t) for t in canon(span).split()]
    if not toks:
        return []
    pat = (r"(?<!\w)" * bool(re.match(r"\w", toks[0])) + r"\s+".join(toks)
           + r"(?!\w)" * bool(re.search(r"\w$", toks[-1])))
    return [(m.start(), m.end()) for m in re.finditer(pat, quotes(text), re.I)]   # granice słów: „a” ≠ „have”


def locate(text: str, span: str) -> tuple[int, int] | None:
    w = find_spans(text, span)
    return w[0] if w else None


def edits(text: str, rng: tuple[int, int] | None, fix: str) -> list[Edit]:
    """Minimalne edycje tokenowe po zastąpieniu `text[rng]` przez `fix`."""
    if rng is None:
        return []
    fixed = text[:rng[0]] + canon(fix) + text[rng[1]:]
    a, b = _toks(text), _toks(fixed)
    out = []
    sm = difflib.SequenceMatcher(None, [t[2] for t in a], [t[2] for t in b], autojunk=False)
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and i2 - i1 == j2 - j1:      # sąsiednie zamiany słowo-za-słowo: osobne edycje
            out += [Edit(a[i][0], a[i][1], (a[i][2],), (b[j][2],))
                    for i, j in zip(range(i1, i2), range(j1, j2), strict=True)]
            continue
        pos = a[i1][0] if i1 < len(a) else len(text)
        end = a[i2 - 1][1] if i2 > i1 else pos
        out.append(Edit(pos, end, tuple(t[2] for t in a[i1:i2]), tuple(t[2] for t in b[j1:j2])))
    return out


def _ov(x: Edit, y: Edit) -> bool:
    if x.a == x.b or y.a == y.b:                       # wstawienie: punkt na granicy też się liczy
        return max(x.a, y.a) <= min(x.b, y.b)
    return max(x.a, y.a) < min(x.b, y.b)


def overlaps(e1: list[Edit], e2: list[Edit]) -> bool:
    return any(_ov(x, y) for x in e1 for y in e2)


def relation(e1: list[Edit], e2: list[Edit]) -> str:
    """same: te same edycje; partial: jedna propozycja zawiera drugą; conflict: różne zmiany w tym samym miejscu;
    disjoint: brak wspólnego miejsca (także gdy którakolwiek nie zmienia tekstu)."""
    k1, k2 = {e.key for e in e1}, {e.key for e in e2}
    if not k1 or not k2:
        return "disjoint"
    if k1 == k2:
        return "same"
    if k1 < k2 or k2 < k1:
        return "partial"
    return "conflict" if overlaps(e1, e2) else "disjoint"


def minimize(text: str, o):
    """Najkrótszy jednoznaczny cytat obejmujący wszystkie edycje obserwacji (`Obs`). Przy niepewności: bez zmian."""
    rng = locate(text, o.s)
    es = edits(text, rng, o.f)
    if not es:
        return o
    fixed = text[:rng[0]] + canon(o.f) + text[rng[1]:]
    toks = _toks(text)
    lo = next(i for i, t in enumerate(toks) if t[1] > es[0].a) if es[0].a < len(text) else len(toks)
    hi = max(i for i, t in enumerate(toks) if t[0] < es[-1].b) if es[-1].b > es[-1].a else lo - 1
    if hi < lo:                                        # samo wstawienie: dołącz następny (lub poprzedni) token
        lo, hi = (lo, lo) if lo < len(toks) else (lo - 1, lo - 1)
    if lo < 0:
        return o
    d = len(fixed) - len(text)
    while True:
        A, Bn = toks[lo][0], toks[hi][1]
        s = text[A:Bn]
        if len(find_spans(text, s)) == 1:
            break
        if hi + 1 < len(toks):
            hi += 1
        elif lo > 0:
            lo -= 1
        else:
            return o
    if fixed[:A] != text[:A] or fixed[Bn + d:] != text[Bn:]:
        return o
    return o.model_copy(update={"s": s, "f": fixed[A:Bn + d]})


# --- strażnik znaczenia ---
_NEG = {"not", "no", "never", "nobody", "nothing", "none", "nowhere", "neither", "nor", "cannot", "n't"}
_NUM = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve",
        "twenty", "thirty", "forty", "fifty", "hundred", "thousand", "million", "first", "second", "third"}
_PERSON = {**dict.fromkeys(("i", "me", "myself"), "1s"), **dict.fromkeys(("we", "us"), "1p"),
           **dict.fromkeys(("you",), "2"), **dict.fromkeys(("he", "him"), "3m"),
           **dict.fromkeys(("she",), "3f"), **dict.fromkeys(("it",), "3n"), **dict.fromkeys(("they", "them"), "3p"),
           **dict.fromkeys(("her",), "3f")}
_POSS = {"my", "our", "your", "his", "her", "its", "their"}   # dzierżawcze: częsty błąd L1 (jego/jej), nie sens
_LEXICAL = {"word_choice", "collocation", "l1_calque", "morphology", "tense", "aspect", "register", "spelling"}
_FUNC = {"a", "an", "the", "to", "of", "in", "on", "at", "for", "with", "by", "from", "about", "into", "and", "or",
         "but", "is", "are", "am", "was", "were", "be", "been", "being", "do", "does", "did", "have", "has", "had",
         "will", "would", "can", "could", "should", "may", "might", "must", "shall", "this", "that", "these",
         "those", "some", "any", "much", "many", "more", "most", "very", "so", "too", "than", "then", "there",
         "here", "up", "out", "off", "over", "as", "if", "when", "while", "which", "who", "what", "where", "how"}


def _neg(toks: list[str]) -> bool:
    return any(t.lower() in _NEG or t.lower().endswith("n't") for t in toks)


def _nums(toks: list[str]) -> list[str]:
    return sorted(t.lower() for t in toks if t.isdigit() or t.lower() in _NUM)


def meaning_change(text: str, span: str, fix: str, category: str) -> str | None:
    """Powód, dla którego poprawka zmienia znaczenie wypowiedzi, albo None. Heurystyka, celowo zachowawcza."""
    rng = locate(text, span)
    es = edits(text, rng, fix)
    if not es:
        return None
    before = [t[2] for t in _toks(text)]
    after = [t[2] for t in _toks(text[:rng[0]] + canon(fix) + text[rng[1]:])]
    if _neg(before) != _neg(after):
        return "polarity"
    if _nums(before) != _nums(after):
        return "number"
    core = category.split(".")[0]
    for e in es:
        if len(e.old) != len(e.new):
            continue
        for x, y in zip(e.old, e.new, strict=True):
            x, y = x.lower(), y.lower()
            if x == y or (x in _POSS and y in _POSS):
                continue
            if x in _PERSON and y in _PERSON and _PERSON[x] != _PERSON[y]:
                return "person"
            if (core not in _LEXICAL and x not in _FUNC and y not in _FUNC and x not in _PERSON
                    and difflib.SequenceMatcher(None, x, y).ratio() < 0.5):
                return "content_word"
    if len(before) >= 4:
        same = sum(m.size for m in difflib.SequenceMatcher(None, [t.lower() for t in before],
                                                           [t.lower() for t in after]).get_matching_blocks())
        if (max(len(before), len(after)) - same) / len(before) > 0.5:
            return "rewrite"
    return None


# --- korekta kategorii (F7): kategoria od modelu bywa sprzeczna z samą edycją ---
_SUBJ = {"i", "you", "we", "they", "he", "she", "it"}
_ADV = {"usually", "always", "often", "sometimes", "never", "also", "just", "still", "even", "only", "ever", "rarely",
        "seldom", "already", "all", "both", "sure", "too"}
_PASTISH = {"morphology", "morphology.irregular_past", "morphology.word_form", "tense.past_simple"}


def _s_form(x: str, y: str) -> bool:
    """x i y różnią się tylko końcówką 3. osoby: -s, -es albo -y → -ies."""
    a, b = sorted((x, y), key=len)
    return b in (a + "s", a + "es") or (a.endswith("y") and b == a[:-1] + "ies")


def recategorize(text: str, span: str, fix: str, category: str) -> str:
    """`agreement.subject_verb` zamiast kategorii „przeszłej”, gdy jedyna zmiana to -s/-es/-ies czasownika tuż po
    zaimku-podmiocie (pomijając przysłówki), np. „I usually drinks” → „drink”. W każdym innym przypadku bez zmian."""
    if category not in _PASTISH:
        return category
    es = edits(text, locate(text, span), fix)
    if len(es) != 1 or len(es[0].old) != 1 or len(es[0].new) != 1:
        return category
    x, y = es[0].old[0].lower(), es[0].new[0].lower()
    if not _s_form(x, y):
        return category
    before = [t[2].lower() for t in _toks(text) if t[1] <= es[0].a]
    while before and (before[-1] in _ADV or before[-1].endswith("ly")):
        before.pop()
    return "agreement.subject_verb" if before and before[-1] in _SUBJ else category
