"""Poziomy dowodu i kontrakt potwierdzenia (AGV) dla F5. Czyste funkcje, bez I/O.

Trzy poziomy (F4.7):
- `suspicion` — podejrzenie: niska pewność, podejrzenie STT, sam LanguageTool, sprzeczne propozycje korekt;
- `observation` — wiarygodna obserwacja: ważny błąd o liczonej pewności (h/m), po walidatorach i strażniku znaczenia;
- `confirmed` — potwierdzona ocena umiejętności: WYŁĄCZNIE wynik niezależnego ćwiczenia (zadanie z banku).
Rozmowa nigdy nie daje `confirmed`. Mastery zmienia się tylko przez istniejące ścieżki (zadania; zaufane kategorie
po otwarciu bramy) — ten moduł niczego nie odblokowuje, opisuje tylko kontrakt dla F5.
"""
from __future__ import annotations

from dataclasses import dataclass

from tutor.pedagogy.content import Pack, select_items
from tutor.pedagogy.errors import counted_confidences

SUSPICION, OBSERVATION, CONFIRMED = "suspicion", "observation", "confirmed"


def level(c, pack: Pack) -> str | None:
    """Poziom dowodu dla `assessment.Classified`. None: to nie jest problem ucznia (wariant, naturalne, odrzucone)."""
    if c.status != "valid":
        return None
    if c.kind == "stt_suspect":
        return SUSPICION
    if c.kind != "error":
        return None
    src = c.source or ""
    if c.confidence not in counted_confidences(pack.rubric) or src.startswith("languagetool") or "conflict" in src:
        return SUSPICION
    return OBSERVATION


@dataclass(frozen=True)
class ConfirmRequest:
    """Prośba o potwierdzenie problemu niezależnym ćwiczeniem. F5 pokazuje zadania i woła
    `ingest.apply_confirmation`."""
    skill_id: str
    category: str
    item_ids: tuple[str, ...]
    unverified_items: bool          # True: co najmniej jedno zadanie nie jest `human_reviewed` (etykieta dla ucznia)
    reason: str


def confirm_request(pack: Pack, suggestion: dict, *, n: int = 2, exclude: set[str] = frozenset(),
                    allow_unreviewed_practice: bool = True) -> ConfirmRequest | None:
    """`suggestion` = wpis `plan["suggested"]` ({skill_id, reason: "error:<kategoria>"}). Zadania z puli `practice`
    (nigdy `retention`), najpierw zrecenzowane i produktywne. Brak zadań ⇒ None (nic nie potwierdzamy)."""
    sid = suggestion.get("skill_id")
    if not sid:
        return None
    items = select_items(pack, pool="practice", purpose="practice", skill_id=sid, exclude=set(exclude),
                         allow_unreviewed_practice=allow_unreviewed_practice)
    items = sorted(items, key=lambda i: (i.review.status != "human_reviewed", not i.productive, i.id))[:n]
    if not items:
        return None
    reason = suggestion.get("reason", "")
    return ConfirmRequest(sid, reason.removeprefix("error:"), tuple(i.id for i in items),
                          any(i.review.status != "human_reviewed" for i in items), reason)


def outcome(results: list[bool]) -> str:
    """Wyniki zadań potwierdzających → `confirmed` (wszystkie błędne: problem potwierdzony), `not_confirmed`
    (wszystkie poprawne) lub `inconclusive` (mieszane albo brak)."""
    if results and not any(results):
        return CONFIRMED
    if results and all(results):
        return "not_confirmed"
    return "inconclusive"
