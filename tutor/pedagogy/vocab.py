"""Słownictwo (07 §3): przejścia wiedzy, test tak/nie z pseudosłowami, polityka kart, detekcja użycia.

Czyste funkcje (T-ARCH-1). Zasady: rozpoznanie ≠ opanowanie; samo wykrycie słowa w transkrypcji
nie potwierdza opanowania (liczy się dopiero ≥ N poprawnych użyć w różnych sesjach); brak kart masowych.
"""
from __future__ import annotations

import re
from collections import defaultdict
from collections.abc import Iterable

from tutor.pedagogy.assessment import Prefilter, _tokens
from tutor.pedagogy.content import Rubric

# --- pisownia BrE/AmE (07 §3.1, §4.4) ---
# US → UK: our/or, ise/ize, yse/yze, re/er, ll/l, ogue/og. Para uznana tylko, gdy OBIE formy są znane.
US_TO_UK = [(r"or(s|ed|ing|ings)?$", r"our\1"), (r"ize(s|d)?$", r"ise\1"), (r"izing$", "ising"),
            (r"yze(s|d)?$", r"yse\1"), (r"yzing$", "ysing"), (r"er(s|ed)?$", r"re\1"),
            (r"([aeiou])l(ed|ing)$", r"\1ll\2"), (r"og(s|ed|ing)?$", r"ogue\1")]


def variants_of(forms: list[str]) -> list[tuple[str, str]]:
    fs, pairs = set(forms), []
    for f in forms:
        for pat, rep in US_TO_UK:
            g = re.sub(pat, rep, f)
            if g != f and g in fs and (f, g) not in pairs:
                pairs.append((f, g))
    return pairs


def bre_ame_pair(a: str, b: str) -> bool:
    """Czy `a` i `b` to ta sama pisownia w BrE i AmE (reguły z listy, w obu kierunkach)."""
    a, b = a.lower(), b.lower()
    return bool(variants_of([a, b]) or variants_of([b, a]))


# --- przejścia wiedzy (§3.2) ---
def apply_event(st: dict, event: str, rubric: Rubric, *, day: str | None = None,
                session: int | None = None) -> dict:
    """Zwraca zmienione pola stanu. Zdarzenia: recognized | recall_ok | recall_fail | used_ok.
    `active` nigdy nie wraca do `unknown`; po `fail_to_passive` porażkach z rzędu spada do `passive`."""
    cfg = rubric.vocab
    k, out = st.get("knowledge", "unknown"), {}
    if event == "recognized":
        out["seen_count"] = st.get("seen_count", 0) + 1
        if k == "unknown":
            out["knowledge"] = "passive"
    elif event == "recall_ok":
        out["recall_fail"] = 0
        if day != st.get("last_recall_day"):
            out["recall_ok"] = st.get("recall_ok", 0) + 1
            out["last_recall_day"] = day
        if k == "unknown":
            k = out["knowledge"] = "passive"
        if out.get("recall_ok", st.get("recall_ok", 0)) >= cfg["active_recall_days"]:
            out["knowledge"] = "active"
    elif event == "recall_fail":
        n = st.get("recall_fail", 0) + 1
        out["recall_fail"] = n
        if k == "active" and n >= cfg["fail_to_passive"]:
            out["knowledge"], out["recall_fail"] = "passive", 0
    elif event == "used_ok":
        out["used_count"] = st.get("used_count", 0) + 1
        if session != st.get("last_use_session"):
            out["use_sessions"] = st.get("use_sessions", 0) + 1
            out["last_use_session"] = session
        if k == "unknown":
            k = out["knowledge"] = "passive"
        if out.get("use_sessions", st.get("use_sessions", 0)) >= cfg["active_use_sessions"]:
            out["knowledge"] = "active"
    else:
        raise ValueError(event)
    return out


# --- test tak/nie z pseudosłowami (§3.3) ---
def recognition_result(yes: dict[str, bool], bands: dict[str, int | None], pseudo: Iterable[str], rubric: Rubric,
                       *, pseudo_reviewed: bool) -> dict:
    """`yes`: słowo → odpowiedź „znam”; `bands`: słowo → freq_band (None = brak rang ⇒ wynik przybliżony);
    `pseudo`: pseudosłowa wśród pytań. Wynik per warstwa = trafienia/n − odsetek fałszywych „tak” (h − f)."""
    cfg, pseudo = rubric.vocab, set(pseudo)
    fa_n = sum(1 for w in pseudo if yes.get(w))
    fa = fa_n / len(pseudo) if pseudo else 1.0
    words = [w for w in yes if w not in pseudo]
    by: dict[object, list[str]] = defaultdict(list)
    for w in words:
        by[bands.get(w)].append(w)
    res = {"false_alarm_rate": fa, "rejected": fa >= cfg["false_alarm_reject"] or not pseudo,
           "preliminary": (not pseudo_reviewed) or None in by, "bands": {}, "passive": []}
    if res["rejected"]:
        return res
    for b, ws in by.items():
        hit = sum(1 for w in ws if yes[w]) / len(ws)
        score = max(hit - fa, 0.0)
        res["bands"][b] = round(score, 3)
        if score >= cfg["recognition_pass"]:
            res["passive"] += [w for w in ws if yes[w]]
    res["passive"].sort()
    return res


# --- polityka kart (§3.4) ---
CARD_TRIGGERS = {"lesson_target_not_recalled", "correction", "manual"}


def card_allowed(trigger: str, rubric: Rubric, *, active_cards: int, new_today: int) -> bool:
    """Karta `vocab` tylko z 4 wyzwalaczy (cel lekcji NIEprzywołany w zadaniu produkcyjnym / poprawka word_choice
    lub collocation z pewnością h/m / ręcznie) i w limitach. Rozpoznanie i sama obecność w liście NIE tworzą kart."""
    s = rubric.srs
    return (trigger in CARD_TRIGGERS and active_cards < s["vocab_max_active"]
            and new_today < s["vocab_new_per_day"])


# --- detekcja użycia w rozmowie (§3.5) ---
def detect_use(text: str, pre: Prefilter, forms: set[str], rubric: Rubric, *, tutor_prev: str | None = None,
               low_prob_words: set[str] = frozenset()) -> bool:
    """Czy wypowiedź ucznia (po prefiltrze) zawiera słowo: forma ∈ `forms` (z wariantami BrE/AmE), poza
    wypełniaczami/powtórzeniami/fałszywymi startami (`pre.spans`), poza słowami o niskim prob STT i poza echem
    tutora (≥ `echo_ngram` kolejnych słów identycznych jak w poprzedniej wypowiedzi tutora)."""
    n = rubric.vocab["echo_ngram"]
    toks = _tokens(text)
    words = [w for _, _, w in toks]
    tutor = [w for _, _, w in _tokens(tutor_prev or "")]
    tgrams = {tuple(tutor[i:i + n]) for i in range(len(tutor) - n + 1)}
    for i, (a, b, w) in enumerate(toks):
        if w not in forms or w in low_prob_words:
            continue
        if any(sa <= a and b <= sb for sa, sb, _ in pre.spans):
            continue
        if any(tuple(words[j:j + n]) in tgrams for j in range(max(0, i - n + 1), min(i, len(words) - n) + 1)):
            continue
        return True
    return False
