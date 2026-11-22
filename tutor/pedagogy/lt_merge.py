"""Konwersja dopasowań LanguageTool → kandydaci obserwacji i scalenie z oceną modelu (07 §4.4–§4.5).

Czyste funkcje (T-ARCH-1, bez I/O). LanguageTool NIE jest źródłem prawdy: kandydaci przechodzą przez te same
walidatory deterministyczne (`classify`), a reguły R1–R7 ograniczają jego wpływ. Brak dopasowań LT nie jest
dowodem poprawności. Zaufanie `trust` z `lt_map` jest hipotezą: efektywne `m` tylko dla reguł z `lt_trusted_rules`
(puste do czasu benchmarku i recenzji człowieka).
"""
from __future__ import annotations

from collections import Counter

from tutor.app.languagetool import LTMatch
from tutor.pedagogy import edits as E
from tutor.pedagogy.content import LtMap, norm_answer
from tutor.pedagogy.errors import core_of
from tutor.pedagogy.schemas import Obs, TurnEval, Utt
from tutor.pedagogy.vocab import bre_ame_pair

IGNORED_ISSUES = {"style", "locale-violation", "whitespace", "typographical"}
_UP = {"l": "m", "m": "h", "h": "h"}
_DOWN = {"h": "m", "m": "l", "l": "l"}


def _overlap(a: tuple[int, int] | None, b: tuple[int, int] | None) -> bool:
    return bool(a and b and a[0] < b[1] and b[0] < a[1])


def to_obs(matches: list[LTMatch], text: str, lt_map: LtMap, *, input_mode: str, known_forms: set[str],
           trusted_rules: set[str], version: str) -> tuple[list[Obs], Counter]:
    """Dopasowania → `Obs`. Statystyki: ignored, unmapped (rule_id), voice, no_fix, variant."""
    stats: Counter = Counter()
    out: list[Obs] = []
    seen: set[str] = set()
    for m in matches:
        if m.category_id in lt_map.ignore_categories or m.issue_type.lower() in IGNORED_ISSUES:
            stats["ignored"] += 1
            continue
        info = lt_map.rules.get(m.rule_id) or lt_map.categories.get(m.category_id)
        if info is None or info.category is None:      # nieznana reguła: nie zgadujemy kategorii
            stats[f"unmapped:{m.rule_id}"] += 1
            continue
        if input_mode == "voice" and not info.voice:
            stats["voice"] += 1
            continue
        a = E.utf16_index(text, m.offset)                  # LT (Java) liczy jednostki UTF-16
        b = E.utf16_index(text, m.offset + m.length)
        fix = m.replacements[0] if m.replacements else ""
        a2, b2 = E.word_bounds(text, a, b)                  # fragment słowa („do” w „don't”) ⇒ pełny token
        span, fix = text[a2:b2], (text[a2:a] + fix + text[b:b2]) if fix else ""
        if not span.strip() or not fix:
            stats["no_fix"] += 1
            continue
        if info.category.split(".")[0] == "spelling" and (norm_answer(span) in known_forms
                                                           or bre_ame_pair(span, fix)):
            stats["variant"] += 1                      # BrE i AmE równorzędne: nie błąd
            continue
        key = norm_answer(span)
        if key in seen:                                # jedna obserwacja na span (observation_dedupe)
            continue
        seen.add(key)
        trusted = m.rule_id in trusted_rules and info.trust == "h" and input_mode == "text"
        out.append(Obs(s=span, f=fix, k="error", c=info.category, v=info.severity, p="m" if trusted else "l",
                       src=f"languagetool-{version}"))                                  # R4 / R5
    return out, stats


def merge(bielik: list[Obs], lt: list[Obs], text: str, ok_spans: list[str] = ()) -> tuple[list[Obs], list[Obs]]:
    """R1–R7 na minimalnych edycjach (F4.7), nie na zakresach. Zwraca (obserwacje, alternatywy LT do logu).
    same + zgodna kategoria ⇒ R1 (pewność +1); same + inna kategoria ⇒ `src` bielik+lt-fix (pewność bez zmian);
    partial ⇒ R2 (Bielik, alternatywa w logu);
    conflict (różne zmiany w tym samym miejscu) ⇒ Bielik z pewnością −1 i `src` bielik|lt-conflict."""
    out, alts = list(bielik), []
    b_ed = [E.edits(text, E.locate(text, b.s), b.f) for b in bielik]
    b_rng = [E.locate(text, b.s) for b in bielik]
    ok_rng = [E.locate(text, s) for s in ok_spans]
    for lo in lt:
        r = E.locate(text, lo.s)
        le = E.edits(text, r, lo.f)
        hit = next((i for i, be in enumerate(b_ed) if E.overlaps(be, le)), None)
        if hit is None:                                # Bielik bez zmian w tym miejscu (wariant/naturalne): zakres
            hit = next((i for i, b in enumerate(bielik) if not b_ed[i] and _overlap(r, b_rng[i])), None)
        if hit is not None:
            b = bielik[hit]
            rel = E.relation(b_ed[hit], le)
            if b.k in ("variant", "natural"):          # R6: wygrywa klasyfikacja (wariant/naturalne)
                alts.append(lo)
            elif rel == "same" and core_of(b.c) == core_of(lo.c):                       # R1
                out[hit] = b.model_copy(update={"p": _UP[b.p], "src": "bielik+lt"})       # out[i] ↔ bielik[i]
            elif rel == "same":                        # ta sama poprawka, inna kategoria: bez podniesienia pewności
                out[hit] = b.model_copy(update={"src": "bielik+lt-fix"})
                alts.append(lo)
            elif rel == "conflict":
                out[hit] = b.model_copy(update={"p": _DOWN[b.p], "src": "bielik|lt-conflict"})
                alts.append(lo)
            else:                                      # R2: zostaje Bielik, alternatywa tylko w logu
                alts.append(lo)
            continue
        if any(_overlap(r, o) for o in ok_rng):        # R7: model uznał konstrukcję celu za poprawną
            lo = lo.model_copy(update={"p": "l"})
        out.append(lo)                                 # R3/R4/R5 (p ustawione w to_obs)
    return out, alts


def merge_eval(ev: TurnEval, texts: list[str], lt_per_utt: list[list[Obs]]) -> TurnEval:
    """Scala kandydatów LT z wynikiem modelu dla każdej wypowiedzi; `Utt.t`, `cm`, `cq` bez zmian.
    Wypowiedź bez wpisu modelu nie jest oceniana (sam LT nie dowodzi poprawności)."""
    us = []
    for u in ev.u:
        lt = lt_per_utt[u.i] if u.i < len(lt_per_utt) else []
        obs, _ = merge(u.o, lt, texts[u.i], [t.s for t in u.t if t.r == "ok"]) if lt else (u.o, [])
        us.append(Utt(i=u.i, o=obs, t=u.t, cm=u.cm, cq=u.cq))
    return TurnEval(u=us)
