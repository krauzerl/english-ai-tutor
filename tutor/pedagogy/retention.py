"""Testy trwałości 7 i 30 dni (§4.8). Tylko zadania `human_reviewed`, niewidziane w nauce umiejętności."""
from __future__ import annotations

import random
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

from tutor.pedagogy.content import Item, Pack, Rubric, select_items
from tutor.pedagogy.mastery import SkillState


def _p(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def stage_of(st: SkillState) -> str | None:
    return {"mastered": "7d", "retained_7d": "30d"}.get(st.status)


def is_due(st: SkillState, now: datetime) -> bool:
    return stage_of(st) is not None and st.verify_due_at is not None and _p(st.verify_due_at) <= now


def delay_days(st: SkillState, now: datetime) -> int:
    """Rzeczywiste opóźnienie względem terminu (zapisywane w attempt.feedback_json.delay_days)."""
    return max(0, (now - _p(st.verify_due_at)).days) if st.verify_due_at else 0


@dataclass(frozen=True)
class Pick:
    items: list[Item]
    deferred: bool = False
    reason: str | None = None  # "not_enough_content": sygnał dla autora treści, nie udawana weryfikacja


def pick_items(pack: Pack, rubric: Rubric, skill_id: str, seen_item_ids: set[str], seed: int) -> Pick:
    """3 zadania niewidziane w nauce tej umiejętności (w tym ≥ 1 produkcyjne); inaczej odroczenie."""
    r = rubric.retention
    pool = [i for i in select_items(pack, pool="retention", purpose="retention", skill_id=skill_id,
                                    exclude=set(seen_item_ids)) if "practice" not in i.pools]
    prod = [i for i in pool if i.productive]
    if len(pool) < r["n_items"] or len(prod) < r["productive_required"]:
        return Pick([], True, "not_enough_content")
    rng = random.Random(f"{seed}:{skill_id}")
    chosen = rng.sample(prod, r["productive_required"])
    rest = [i for i in pool if i not in chosen]
    chosen += rng.sample(rest, r["n_items"] - len(chosen))
    return Pick(chosen)


def passed(results: list[tuple[bool, bool]], rubric: Rubric) -> bool:
    """results: (poprawnie, produkcyjne). Zaliczony: ≥ pass_min poprawnych, w tym ≥ 1 produkcyjne."""
    r = rubric.retention
    ok = [x for x in results if x[0]]
    return len(ok) >= r["pass_min"] and sum(1 for _, prod in ok if prod) >= r["productive_required"]


def apply_result(st: SkillState, ok: bool, now: datetime, rubric: Rubric) -> SkillState:
    r = rubric.retention
    stage = stage_of(st)
    if stage is None:
        raise ValueError(f"umiejętność w statusie {st.status} nie czeka na test trwałości")
    if not ok:
        return replace(st, status="learning", p=min(st.p, rubric.mastery["relapse_p_cap"]), mastered_at=None,
                       verify_due_at=None, relapses=st.relapses + 1)
    if stage == "7d":
        due = _iso(_p(st.mastered_at) + timedelta(days=r["d30"]))
        return replace(st, status="retained_7d", verified_7d_at=_iso(now), verify_due_at=due)
    return replace(st, status="retained_30d", verified_30d_at=_iso(now), verify_due_at=None)
