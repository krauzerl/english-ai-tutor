"""Opakowanie biblioteki `fsrs` + mapowanie oceny (§4.7). Czas `now` wstrzykiwany."""
from __future__ import annotations

import json
from datetime import UTC, datetime

from fsrs import Card, Rating, Scheduler

from tutor.pedagogy.content import MC_TYPES, Rubric


def grade(rubric: Rubric, *, correct: bool, hint_level: int = 0, partial: bool = False,
          elapsed_ms: int | None = None, item_type: str | None = None) -> Rating:
    """Błąd/brak → Again; po podpowiedzi L2–L3 lub częściowo → Hard; po L1 lub poprawnie → Good;
    poprawnie w zadaniu zamkniętym szybciej niż `fast_ms` (bez podpowiedzi) → Easy."""
    s = rubric.srs
    if not correct or hint_level >= 4:
        return Rating.Again
    if partial or hint_level in s["hint_hard"]:
        return Rating.Hard
    if hint_level in s["hint_good"]:
        return Rating.Good
    fast = s["fast_ms"].get(item_type) if item_type else None
    if fast and elapsed_ms is not None and elapsed_ms < fast and (item_type in MC_TYPES or item_type in s["fast_ms"]):
        return Rating.Easy
    return Rating.Good


def _utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def review(card_json: str | None, rating: Rating, now: datetime, rubric: Rubric) -> tuple[str, str]:
    """(nowy JSON karty, termin ISO). Brak karty = nowa."""
    sch = Scheduler(desired_retention=rubric.srs["desired_retention"])
    card = Card.from_dict(json.loads(card_json)) if card_json else Card()
    card, _ = sch.review_card(card, rating, review_datetime=_utc(now))
    return json.dumps(card.to_dict()), card.due.strftime("%Y-%m-%dT%H:%M:%SZ")


def retrievability(card_json: str, now: datetime, rubric: Rubric) -> float:
    sch = Scheduler(desired_retention=rubric.srs["desired_retention"])
    return sch.get_card_retrievability(Card.from_dict(json.loads(card_json)), current_datetime=_utc(now))
