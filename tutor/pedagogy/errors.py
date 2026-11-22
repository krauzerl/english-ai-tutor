"""Taksonomia błędów i rejestr powtarzających się błędów (§4.9). Stan pochodny od obserwacji (idempotentny)."""
from __future__ import annotations

from datetime import datetime, timedelta

from tutor.pedagogy.content import CORE_CATEGORIES, Errors, Rubric


def core_of(category: str) -> str:
    return category.split(".")[0]


def allowed_categories(errors: Errors) -> set[str]:
    """Kod zna tylko rdzeń i listę z YAML."""
    return errors.ids() | set(CORE_CATEGORIES)


def counted_confidences(rubric: Rubric) -> tuple[str, ...]:
    return ("h",) if rubric.confidence["treat_m_as_l"] else ("h", "m")


def is_counted(o: dict, rubric: Rubric) -> bool:
    """Obserwacja wchodzi do error_log/BKT: ważny `error` o pewności h (i m, jeśli nie traktujemy m jak l)."""
    return o["kind"] == "error" and o["status"] == "valid" and o["confidence"] in counted_confidences(rubric)


def _p(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def aggregate(obs: list[dict], now: datetime, rubric: Rubric) -> dict[tuple[str, str | None], dict]:
    """Per (kategoria, skill_id): liczności w oknie, ważność, przykład (najnowszy)."""
    since = now - timedelta(days=rubric.errors["window_days"])
    out: dict[tuple[str, str | None], dict] = {}
    for o in sorted((x for x in obs if is_counted(x, rubric)), key=lambda x: (x["created_at"], x["id"])):
        g = out.setdefault((o["category"], o.get("skill_id")), {
            "count": 0, "count_30d": 0, "utts_30d": set(), "severity_max": 1, "first_seen": o["created_at"],
            "last_seen": o["created_at"], "example_obs_id": o["id"], "example": o["span"], "correction": o["fix"]})
        g["count"] += 1
        g["severity_max"] = max(g["severity_max"], o["severity"] or 1)
        g["last_seen"], g["example_obs_id"], g["example"], g["correction"] = (
            o["created_at"], o["id"], o["span"], o["fix"])
        if _p(o["created_at"]) >= since:
            g["count_30d"] += 1
            g["utts_30d"].add(o["turn_id"])
    for g in out.values():
        g["utts_30d"] = len(g["utts_30d"])
    return out


def next_status(prev: str, reopened: int, *, count_30d: int, utts_30d: int, remediated: bool,
                sessions: list[dict], new_error_since_resolved: bool, rubric: Rubric) -> tuple[str, int]:
    """Przejścia active → recurring → improving → resolved (+ ponowne otwarcie).

    `sessions`: ostatnie sesje Z OKAZJĄ użycia (nowsze na końcu): {errors: int, correct: int}.
    Okazja = obserwacja `t` lub zadanie tej kategorii (liczy `app/ingest`)."""
    e = rubric.errors
    last = sessions[-e["sessions_window"]:]
    errs, ok = sum(s["errors"] for s in last), sum(s["correct"] for s in last)
    if prev == "resolved":
        if new_error_since_resolved:
            return "recurring", reopened + 1
        return "resolved", reopened
    if len(last) >= e["sessions_window"] and errs == 0 and ok >= e["resolved_correct_min"] and prev in (
            "recurring", "improving"):
        return "resolved", reopened
    if remediated and prev in ("recurring", "improving") and ok >= e["improving_correct_min"] \
            and errs <= e["improving_wrong_max"]:
        return "improving", reopened
    if count_30d >= e["recurring_count"] and utts_30d >= e["recurring_utterances"]:
        return "recurring", reopened
    if prev in ("recurring", "improving"):
        return prev, reopened
    return "active", reopened
