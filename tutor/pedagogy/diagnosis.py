"""Diagnoza: siatka bayesowska per obszar (04_PEDAGOGY_SPEC §4.2–§4.4). Czysta, deterministyczna.

Dwa tryby, ten sam algorytm, RÓŻNY status wyniku:
 * `verified`    – tylko zadania human_reviewed i otwarta brama (≥15/poziom).
                   Wynik = diagnoza (competence.source=diagnosis).
 * `provisional` – zadania ai_checked/human_reviewed. Wynik = WSTĘPNE dopasowanie trudności nauki
                   (competence.source=placement_provisional), nigdy diagnoza CEFR ani podstawa testów trwałości.
Stan (JSON) zawiera tylko odpowiedzi; posterior jest liczony na nowo ⇒ wznowienie = wczytanie stanu.
Symulacje (T-PED-1/2) dowodzą wyłącznie spójności algorytmu, nie trafności CEFR (§4.4).
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass
from typing import Protocol

from tutor.pedagogy.cefr import clamp_theta, interval_text, label_of, level_index
from tutor.pedagogy.content import MC_TYPES, Pack, Rubric, diagnosis_gate, select_items


class GateClosed(Exception):
    """Brak wystarczającej liczby zadań o wymaganym statusie dla trybu diagnozy."""


class ItemLike(Protocol):
    id: str
    cefr: str
    difficulty: float
    type: str
    options: list[str] | None


def item_b(it: ItemLike, rubric: Rubric) -> float:
    return level_index(it.cefr) + rubric.diagnosis["difficulty_scale"] * it.difficulty


def item_g(it: ItemLike) -> float:
    return 1 / len(it.options) if it.type in MC_TYPES and it.options else 0.0


def p_correct(theta: float, b: float, g: float, slope: float) -> float:
    return g + (1 - g) / (1 + math.exp(-slope * (theta - b)))


def _grid(d: dict) -> list[float]:
    n = round((d["theta_max"] - d["theta_min"]) / d["step"])
    return [d["theta_min"] + i * d["step"] for i in range(n + 1)]


def posterior(asked: list[dict], rubric: Rubric, prior: tuple[float, float] | None = None) -> list[float]:
    d = rubric.diagnosis
    mean, sd = prior or (d["prior_mean"], d["prior_sd"])
    logs = []
    for th in _grid(d):
        lp = -0.5 * ((th - mean) / sd) ** 2
        for a in asked:
            p = min(max(p_correct(th, a["b"], a["g"], d["slope"]), 1e-9), 1 - 1e-9)
            lp += a.get("w", 1.0) * math.log(p if a["correct"] else 1 - p)
        logs.append(lp)
    m = max(logs)
    w = [math.exp(x - m) for x in logs]
    z = sum(w)
    return [x / z for x in w]


def stats(post: list[float], rubric: Rubric) -> dict:
    d = rubric.diagnosis
    grid = _grid(d)
    mean = sum(t * p for t, p in zip(grid, post, strict=True))
    sd = math.sqrt(sum(p * (t - mean) ** 2 for t, p in zip(grid, post, strict=True)))

    def pct(q: float) -> float:
        c = 0.0
        for t, p in zip(grid, post, strict=True):
            c += p
            if c >= q / 100:
                return t
        return grid[-1]
    lo, hi = d["interval_pct"]
    return {"mean": mean, "sd": sd, "lo": pct(lo), "hi": pct(hi)}


def available_items(pack: Pack, area: str, mode: str) -> list:
    purpose = "diagnosis" if mode == "verified" else "placement"
    return select_items(pack, pool="diagnosis", purpose=purpose, area=area)


def start(pack: Pack, area: str, mode: str, seed: int) -> dict:
    """Nowy stan. `verified` wymaga otwartej bramy (T-CONTENT-2); `provisional` ≥ min_items użytecznych zadań."""
    d = pack.rubric.diagnosis
    if mode == "verified":
        if not diagnosis_gate(pack, area, d["gate_min_per_level"])["open"]:
            raise GateClosed(f"diagnoza {area}: brama human_reviewed zamknięta (≥{d['gate_min_per_level']}/poziom)")
    elif mode == "provisional":
        if len(available_items(pack, area, mode)) < d["min_items"]:
            raise GateClosed(f"wstępne dopasowanie {area}: za mało zadań ai_checked/human_reviewed")
    else:
        raise ValueError(mode)
    return {"area": area, "mode": mode, "seed": seed, "asked": [], "elapsed_min": 0.0}


def next_item(state: dict, items: list[ItemLike], rubric: Rubric) -> ItemLike | None:
    """Zadanie o `b` najbliższym średniej a posteriori; remis losowo (ziarno ze stanu)."""
    used = {a["id"] for a in state["asked"]}
    cands = [i for i in items if i.id not in used]
    if not cands:
        return None
    mean = stats(posterior(state["asked"], rubric), rubric)["mean"]
    dist = {i.id: abs(item_b(i, rubric) - mean) for i in cands}
    best = min(dist.values())
    ties = sorted((i for i in cands if dist[i.id] - best < 1e-9), key=lambda i: i.id)
    return random.Random(f"{state['seed']}:{len(state['asked'])}").choice(ties)


def record(state: dict, item: ItemLike, correct: bool, rubric: Rubric, minutes: float = 0.0) -> dict:
    a = {"id": item.id, "b": item_b(item, rubric), "g": item_g(item), "correct": bool(correct), "w": 1.0}
    return {**state, "asked": [*state["asked"], a], "elapsed_min": state["elapsed_min"] + minutes}


def stop_reason(state: dict, rubric: Rubric) -> str | None:
    d = rubric.diagnosis
    n = len(state["asked"])
    if n >= d["max_items"]:
        return "max_items"
    if state["elapsed_min"] >= d["time_limit_min"]:
        return "time_limit"
    if n >= d["min_items"] and stats(posterior(state["asked"], rubric), rubric)["sd"] < d["stop_sd"]:
        return "precision"
    return None


@dataclass(frozen=True)
class Result:
    area: str
    mode: str
    theta: float
    se: float
    lo: float
    hi: float
    level: str
    label: str
    ceiling: bool
    floor: bool
    n_items: int
    provisional: bool
    source: str           # wartość competence.source
    notice: str           # tekst, który UI/raport musi pokazać obok wyniku

    def as_dict(self) -> dict:
        return asdict(self)


def result(state: dict, rubric: Rubric) -> Result:
    d = rubric.diagnosis
    asked = state["asked"]
    s = stats(posterior(asked, rubric), rubric)
    top = level_index(d["top_level"])
    recent = asked[-d["recent_window"]:]
    right = sum(a["correct"] for a in recent)
    ceiling = s["hi"] > d["ceiling_p90"] and right >= d["recent_threshold"]
    floor = s["lo"] < d["floor_p10"] and (len(recent) - right) >= d["recent_threshold"]
    theta = clamp_theta(s["mean"], top)
    prov = state["mode"] == "provisional"
    text = interval_text(theta, s["lo"], s["hi"], ceiling=ceiling, floor=floor, top_index=top)
    if prov:
        notice = d["provisional"]["label_pl"]
        label = f"wstępnie: {text}"
    else:
        notice = rubric.report["disclaimer_pl"]
        label = text
    return Result(state["area"], state["mode"], round(theta, 3), round(s["sd"], 3), round(s["lo"], 3),
                  round(s["hi"], 3), label_of(theta, top), label, ceiling, floor, len(asked), prov,
                  "placement_provisional" if prov else "diagnosis", notice)


def refine(theta: float, se: float, item: ItemLike, correct: bool, rubric: Rubric) -> tuple[float, float]:
    """Mini-weryfikacja w lekcji (pula practice, human_reviewed): posterior obszaru z wagą `cefr_weight` (§4.6)."""
    a = {"b": item_b(item, rubric), "g": item_g(item), "correct": correct, "w": rubric.mastery["cefr_weight"]}
    s = stats(posterior([a], rubric, prior=(theta, max(se, 0.05))), rubric)
    return s["mean"], s["sd"]
