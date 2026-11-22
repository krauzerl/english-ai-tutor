"""Planer sesji (ARCHITECTURE §4 + 04_PEDAGOGY_SPEC §2.9). Czysty, deterministyczny (now i ziarno jako parametry).

Priorytety: (1) zaległe powtórki FSRS ≤ 30% czasu, (2) błędy `recurring`/count≥3 i zadania pisemne za `stt_suspect`,
(3) umiejętności w nauce, (4) następna odblokowana umiejętność na poziomie θ…θ+0,5, (5) testy trwałości.
Suma minut bloków = wybrany czas. Brak treści ⇒ sygnał `content_gaps`, nie zmyślone zadanie.
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from tutor.pedagogy import retention
from tutor.pedagogy.cefr import level_index
from tutor.pedagogy.content import Item, Pack, usable
from tutor.pedagogy.diagnosis import item_b
from tutor.pedagogy.mastery import SkillState, unlocked


@dataclass
class PlanInput:
    minutes: int
    now: datetime
    seed: int
    pack: Pack
    states: dict[str, SkillState]
    levels: dict[str, float]                       # area -> θ (z competence; także wstępne dopasowanie)
    due_cards: list[dict] = field(default_factory=list)       # {card_type, ref_id, due_at, retrievability?}
    errors: list[dict] = field(default_factory=list)          # wiersze error_log: category, skill_id, status, count
    stt_suspects_14d: dict[str, int] = field(default_factory=dict)   # kategoria -> liczba
    seen_items: dict[str, set[str]] = field(default_factory=dict)    # skill_id -> id zadań widzianych w nauce
    last_dims: dict | None = None                  # oceny wymiarów z poprzedniej sesji
    allow_unreviewed_practice: bool = True
    fluency_drop_sessions: int = 0
    reuse_targets: list[dict] = field(default_factory=list)
    provisional_areas: set[str] = field(default_factory=set)  # obszary z wstępnym dopasowaniem (niezweryfikowanym)


def _blocks(inp: PlanInput) -> dict[str, int]:
    p = inp.pack.rubric.planner
    if inp.minutes not in p["blocks"]:
        raise ValueError(f"nieobsługiwany czas sesji {inp.minutes}; dozwolone: {sorted(p['blocks'])}")
    b = dict(p["blocks"][inp.minutes])
    # §2.9: insufficient_evidence → rozmowa dłuższa o N min (kosztem ćwiczeń; suma minut bez zmian)
    if inp.last_dims and any(d["status"] == "insufficient_evidence" for d in inp.last_dims.values()):
        extra = min(p["insufficient_evidence_extra_conversation_min"], max(b["practice"] - 1, 0))
        b["conversation"] += extra
        b["practice"] -= extra
    cap = math.floor(p["review_share_max"] * inp.minutes)
    if b["review"] > cap:                              # powtórki ≤ 30% czasu; reszta wraca do ćwiczeń
        b["practice"] += b["review"] - cap
        b["review"] = cap
    return b


def _theta(inp: PlanInput, area: str) -> float:
    th = inp.levels.get(area, inp.pack.rubric.planner["default_theta"])
    d = inp.last_dims
    p = inp.pack.rubric.planner
    if d and area in ("grammar", "vocabulary"):         # G/V ≤ 1 → następna lekcja na θ−0,5
        x = d.get(area)
        s = x["score"] if x and x["status"] == "scored" and x["score"] is not None else (
            x["range"][0] if x and x.get("range") else None)
        if s is not None and s <= p["low_score_threshold"]:
            th -= p["low_score_theta_drop"]
    return th


def _index(inp: PlanInput) -> dict[str, list[Item]]:
    """Jedno przejście po banku: zadania ćwiczeniowe użyteczne wg statusu, per umiejętność."""
    by: dict[str, list[Item]] = defaultdict(list)
    for it in inp.pack.items.values():
        if "practice" in it.pools and usable(it, "practice", inp.allow_unreviewed_practice):
            for s in it.skill_ids:
                by[s].append(it)
    return by


def _items_for(skill_id: str, theta: float, by: dict, inp: PlanInput, n: int, rng: random.Random) -> list[Item]:
    cands = sorted(by.get(skill_id, []), key=lambda i: (abs(item_b(i, inp.pack.rubric) - theta), i.id))
    top = cands[:max(n * 2, n)]
    rng.shuffle(top)
    return sorted(top[:n], key=lambda i: i.id)


def _task(kind: str, skill_id: str, items: list[Item], reason: str, theta: float, inp: PlanInput) -> dict:
    sk = inp.pack.skills[skill_id]
    return {"kind": kind, "skill_id": skill_id, "reason": reason, "area": sk.area, "cefr": sk.cefr,
            "explanation_ref": sk.explanation_ref,
            "items": [{"id": i.id, "unverified": i.review.status != "human_reviewed"} for i in items],
            "provisional_level": sk.area in inp.provisional_areas}


def plan(inp: PlanInput) -> dict:
    rb = inp.pack.rubric
    p = rb.planner
    rng = random.Random(f"{inp.seed}:{inp.now.date()}")
    blocks = _blocks(inp)
    skills = inp.pack.skills
    notes: list[str] = []
    gaps: list[str] = []

    # 1. powtórki
    due = sorted(inp.due_cards, key=lambda c: (c["due_at"], c.get("retrievability", 1.0), c["ref_id"]))
    n_cards = min(len(due), int(blocks["review"] / p["minutes_per_card"]))
    review_min = min(blocks["review"], math.ceil(n_cards * p["minutes_per_card"]))
    blocks["practice"] += blocks["review"] - review_min      # niewykorzystane minuty powtórek → ćwiczenia
    blocks["review"] = review_min

    # 2.–4. ćwiczenia
    by = _index(inp)
    capacity = max(1, int(blocks["practice"] / p["minutes_per_item"]))
    per = p["items_per_skill"]
    tasks: list[dict] = []
    chosen: set[str] = set()

    def add(kind: str, sid: str, reason: str) -> None:
        if sid in chosen or len(tasks) >= capacity or sid not in skills:
            return
        th = _theta(inp, skills[sid].area)
        items = _items_for(sid, th, by, inp, per, rng)
        if not items:
            gaps.append(f"practice:{sid}")
        chosen.add(sid)
        tasks.append(_task(kind, sid, items, reason, th, inp))

    by_cat: dict[str, list[str]] = defaultdict(list)     # kategoria i jej rodzic (article ← article.missing)
    for s in skills.values():
        for c in s.error_categories:
            for key in {c, c.split(".")[0]}:
                by_cat[key].append(s.id)
    for e in sorted(inp.errors, key=lambda e: (-(e.get("severity_max") or 1), e["category"])):
        if e.get("status") == "recurring" or (e.get("count", 0) >= p["recurring_min_count"]
                                              and e.get("status") not in ("resolved", "improving")):
            sid = e.get("skill_id") or next(iter(sorted(by_cat.get(e["category"], []))), None)
            if sid:
                add("remediation", sid, f"error:{e['category']}")
    for cat, n in sorted(inp.stt_suspects_14d.items()):
        if n >= inp.pack.rubric.errors["stt_suspect_count"]:
            sid = next(iter(sorted(by_cat.get(cat, []))), None)
            if sid:
                add("written_task", sid, f"stt_suspect:{cat}")        # zamienia niepewność w dowód deterministyczny
    learning = [s for s in inp.states.values() if s.status == "learning"
                and rb.mastery["learning_threshold"] < s.p < rb.mastery["p_master"] and s.skill_id in skills]
    for s in sorted(learning, key=lambda s: (s.p, s.skill_id)):
        add("learning", s.skill_id, "in_progress")
    cand = []
    for s in skills.values():
        st = inp.states.get(s.id)
        if st and st.status != "new":
            continue
        th = _theta(inp, s.area)
        k = level_index(s.cefr)
        if k - 0.5 < th + 0.5 and k + 0.5 > th and unlocked(s, inp.states, inp.levels, skills):
            cand.append((abs(k - th), s.id))
    for _, sid in sorted(cand):
        add("new", sid, "next_unlocked")
    if not tasks and not gaps:
        notes.append("no_skill_available")

    # 5. testy trwałości
    verify = []
    due_skills = sorted((s for s in inp.states.values() if retention.is_due(s, inp.now)),
                        key=lambda s: (-retention.delay_days(s, inp.now), s.skill_id))
    for s in due_skills[:max(blocks["verify"], 0)]:
        pk = retention.pick_items(inp.pack, rb, s.skill_id, inp.seen_items.get(s.skill_id, set()), inp.seed)
        if pk.deferred:
            gaps.append(f"retention:{s.skill_id}")
        verify.append({"skill_id": s.skill_id, "stage": retention.stage_of(s), "deferred": pk.deferred,
                       "reason": pk.reason, "items": [i.id for i in pk.items],
                       "delay_days": retention.delay_days(s, inp.now)})

    conv = {"minutes": blocks["conversation"], "reuse_targets": list(inp.reuse_targets),
            "scenario": _scenario(inp, chosen),
            "fluency_exercise": inp.fluency_drop_sessions >= p["fluency_drop_sessions"]}
    review = [{"card_type": c["card_type"], "ref_id": c["ref_id"]} for c in due[:n_cards]]
    out = {"minutes": inp.minutes, "blocks": blocks, "review": review,
           "practice": tasks, "verify": verify, "conversation": conv, "content_gaps": sorted(set(gaps)),
           "notes": notes, "created_at": inp.now.strftime("%Y-%m-%dT%H:%M:%SZ")}
    assert sum(blocks.values()) == inp.minutes, blocks
    return out


def _scenario(inp: PlanInput, skill_ids: set[str]) -> str | None:
    th = inp.levels.get("speaking", inp.levels.get("grammar", inp.pack.rubric.planner["default_theta"]))
    best = None
    for sc in sorted(inp.pack.scenarios.values(), key=lambda s: s.id):
        if sc.review.status in ("rejected", "suspect"):
            continue
        k = level_index(sc.cefr)
        score = (len(set(sc.target_skill_ids) & skill_ids), -abs(k - th))
        if best is None or score > best[0]:
            best = (score, sc.id)
    return best[1] if best else None
