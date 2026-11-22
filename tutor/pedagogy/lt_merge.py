"""Konwersja dopasowań LanguageTool → kandydaci obserwacji i scalenie z oceną modelu (07 §4.4–§4.5).

Czyste funkcje (T-ARCH-1, bez I/O). LanguageTool NIE jest źródłem prawdy: kandydaci przechodzą przez te same
walidatory deterministyczne (`classify`), a reguły R1–R7 ograniczają jego wpływ. Brak dopasowań LT nie jest
dowodem poprawności. Zaufanie `trust` z `lt_map` jest hipotezą: efektywne `m` tylko dla reguł z `lt_trusted_rules`
(puste do czasu benchmarku i recenzji człowieka).
"""
from __future__ import annotations

from collections import Counter

from tutor.app.languagetool import LTMatch
from tutor.pedagogy.assessment import find_spans
from tutor.pedagogy.content import LtMap, norm_answer
from tutor.pedagogy.errors import core_of
from tutor.pedagogy.schemas import Obs, TurnEval, Utt
from tutor.pedagogy.vocab import bre_ame_pair

IGNORED_ISSUES = {"style", "locale-violation", "whitespace", "typographical"}
_UP = {"l": "m", "m": "h", "h": "h"}


def _rng(text: str, span: str) -> tuple[int, int] | None:
    w = find_spans(text, span)
    return w[0] if w else None


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
        span = text[m.offset:m.offset + m.length]
        fix = m.replacements[0] if m.replacements else ""
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
    """R1–R7. Zwraca (obserwacje, odrzucone alternatywy LT do logu benchmarku)."""
    out, alts = list(bielik), []
    b_rng = [_rng(text, b.s) for b in bielik]
    ok_rng = [_rng(text, s) for s in ok_spans]
    for lo in lt:
        r = _rng(text, lo.s)
        hit = next((i for i, br in enumerate(b_rng) if _overlap(r, br)), None)
        if hit is not None:
            b = bielik[hit]
            if b.k in ("variant", "natural"):          # R6: wygrywa klasyfikacja (wariant/naturalne)
                alts.append(lo)
            elif norm_answer(b.s) == norm_answer(lo.s) and core_of(b.c) == core_of(lo.c):   # R1
                fix = b.f if b.f and norm_answer(b.f) != norm_answer(b.s) else lo.f
                out[hit] = b.model_copy(update={"p": _UP[b.p], "f": fix, "src": "bielik+lt"})   # out[i] ↔ bielik[i]
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
