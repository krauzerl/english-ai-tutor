"""Raport sesji z danych (04_PEDAGOGY_SPEC §6): deterministyczny, każdy wniosek ma dowód.

Wejście: dane z DB w dataclassie. Wyjście: JSON raportu + walidator narracji. Zasady:
 * każdy błąd i mocna strona ma DOSŁOWNY cytat z `turn.text` (cytat nieobecny w tekście = pozycja odrzucona),
 * brak dowodów = „za mało danych”, nigdy ogólnik; mastery jako status, nie surowe p,
 * wymowa nieoceniana; żadnych liczb spoza danych wejściowych w narracji.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from tutor.pedagogy.assessment import find_spans
from tutor.pedagogy.cefr import interval_text
from tutor.pedagogy.content import Pack
from tutor.pedagogy.correction import priority

NO_DATA = "za mało danych"
NOT_APPLICABLE = "nie dotyczy"


@dataclass
class ReportInput:
    session_id: int
    pack: Pack
    turns: dict[int, str]                       # turn_id -> tekst wypowiedzi ucznia
    input_modes: set[str] = field(default_factory=lambda: {"text"})
    skill_events: list[dict] = field(default_factory=list)       # {skill_id, from, to}
    retention_results: list[dict] = field(default_factory=list)  # {skill_id, stage, passed, delay_days}
    error_events: list[dict] = field(default_factory=list)       # {category, from, to}
    srs: dict = field(default_factory=lambda: {"new_cards": 0, "reviews": 0})
    # {turn_id, span, fix, category, severity, count_session, count_30d, is_goal}
    errors: list[dict] = field(default_factory=list)
    # {skill_id, turn_id, quote, hint_level, kind: goal_use|self_repair}
    strengths: list[dict] = field(default_factory=list)
    clean_categories: list[dict] = field(default_factory=list)   # {category, opportunities, errors, turn_id, quote}
    dims: dict = field(default_factory=dict)
    next_plan: dict = field(default_factory=dict)
    competence: list[dict] = field(default_factory=list)  # {area, theta, lo, hi, ceiling, floor, provisional}


def _quote_ok(text: str | None, turns: dict[int, str], turn_id: int) -> bool:
    return bool(text) and turn_id in turns and bool(find_spans(turns[turn_id], text))


def _dim_label(d: dict, rubric_fluency_note: str | None = None) -> str:
    s = d["status"]
    if s == "scored":
        return str(d["score"]) if d["score"] is not None else f"{d['range'][0]}–{d['range'][1]}, niepewne"
    if s == "not_applicable":
        return NOT_APPLICABLE
    if s == "metrics_only":
        return "tylko metryki (ocena po 3. sesji głosowej)"
    return NO_DATA


def build(inp: ReportInput) -> dict:
    pack, rb = inp.pack, inp.pack.rubric
    r = rb.report
    cats = {c.id: c for c in pack.errors.categories}

    # najważniejsze błędy: top-3 wg priorytetu, tylko z dosłownym cytatem
    ranked = sorted(inp.errors, reverse=True, key=lambda e: (
        priority(e["severity"], e["count_30d"], e.get("is_goal", False), False, rb), e["turn_id"]))
    top = []
    for e in ranked:
        if not _quote_ok(e["span"], inp.turns, e["turn_id"]):
            continue
        c = cats.get(e["category"])
        top.append({"quote": e["span"], "fix": e["fix"], "category": e["category"],
                    "category_pl": c.explanation_pl if c else None, "count_session": e["count_session"],
                    "count_30d": e["count_30d"], "severity": e["severity"], "turn_id": e["turn_id"]})
        if len(top) == r["top_errors"]:
            break

    # mocne strony: umiejętności użyte poprawnie ≥ N× bez podpowiedzi + udane autonaprawy + kategorie bez błędów
    by_skill: dict[str, list[dict]] = {}
    for s in inp.strengths:
        if s["kind"] == "goal_use" and s.get("hint_level", 0) == 0 and _quote_ok(s["quote"], inp.turns, s["turn_id"]):
            by_skill.setdefault(s["skill_id"], []).append(s)
    items = []
    for sid, uses in sorted(by_skill.items()):
        if len(uses) >= r["strength_min_uses"]:
            sk = pack.skills.get(sid)
            items.append({"kind": "goal_use", "skill_id": sid, "can_do_pl": sk.can_do_pl if sk else None,
                          "uses": len(uses), "quote": uses[0]["quote"]})
    for s in inp.strengths:
        if s["kind"] == "self_repair" and _quote_ok(s["quote"], inp.turns, s["turn_id"]):
            items.append({"kind": "self_repair", "skill_id": s.get("skill_id"), "quote": s["quote"]})
    for c in inp.clean_categories:
        if c["opportunities"] >= r["strength_min_opportunities"] and c["errors"] == 0 \
                and _quote_ok(c.get("quote"), inp.turns, c["turn_id"]):
            items.append({"kind": "clean_category", "category": c["category"], "opportunities": c["opportunities"],
                          "quote": c["quote"]})
    strengths = {"status": "ok", "items": items} if items else {"status": NO_DATA, "items": []}

    dims = {k: {"label": _dim_label(v), "status": v["status"], "score": v["score"], "range": v["range"],
                "quotes": [q for q in v.get("quotes", []) if any(find_spans(t, q) for t in inp.turns.values())]
                if k != "fluency" else [], **({"metrics": v["metrics"]} if v.get("metrics") else {})}
            for k, v in inp.dims.items()}

    top_levels = rb.diagnosis["top_level"]
    comp = []
    for c in inp.competence:
        label = interval_text(c["theta"], c["lo"], c["hi"], ceiling=c.get("ceiling", False),
                              floor=c.get("floor", False), top_index={"C1": 5}.get(top_levels, 5))
        entry = {"area": c["area"], "label": ("wstępnie: " if c.get("provisional") else "") + label,
                 "provisional": bool(c.get("provisional"))}
        entry["notice"] = rb.diagnosis["provisional"]["label_pl"] if c.get("provisional") else r["disclaimer_pl"]
        comp.append(entry)

    plan = inp.next_plan
    recommended = [{"kind": t["kind"], "skill_id": t["skill_id"], "reason": t["reason"]}
                   for t in plan.get("practice", [])]
    recommended += [{"kind": "retention", "skill_id": v["skill_id"], "reason": f"verify_{v['stage']}",
                     "deferred": v["deferred"]} for v in plan.get("verify", [])]
    notes = {"disclaimer": r["disclaimer_pl"]}
    if "voice" in inp.input_modes:
        notes["pronunciation"] = r["pronunciation_pl"]
    rep = {
        "session_id": inp.session_id,
        "progress": {"skill_status_changes": inp.skill_events, "retention": inp.retention_results,
                     "error_transitions": inp.error_events, "srs": inp.srs},
        "top_errors": top, "strengths": strengths, "dimensions": dims, "competence": comp,
        "recommended": recommended,
        "next_plan": {"minutes": plan.get("minutes"), "blocks": plan.get("blocks"),
                      "content_gaps": plan.get("content_gaps", [])},
        "notes": notes,
    }
    rep["counts"] = {"status_changes": len(inp.skill_events), "errors_shown": len(top),
                     "strengths_shown": len(items)}
    return rep


def validate_report(rep: dict, turns: dict[int, str]) -> list[str]:
    """Walidator raportu: cytaty dosłowne, ocena < 4 w G/V/N ma cytat, brak twierdzeń o wymowie."""
    probs = []
    for e in rep["top_errors"]:
        if not _quote_ok(e["quote"], turns, e["turn_id"]):
            probs.append(f"error_quote:{e['quote']}")
    for s in rep["strengths"]["items"]:
        if not any(find_spans(t, s["quote"]) for t in turns.values()):
            probs.append(f"strength_quote:{s['quote']}")
    for k in ("grammar", "vocabulary", "naturalness"):
        d = rep["dimensions"].get(k)
        if d and d["status"] == "scored":
            lo = d["score"] if d["score"] is not None else d["range"][0]
            if lo < 4 and not d["quotes"]:
                probs.append(f"no_quote:{k}")
    text = json.dumps(rep, ensure_ascii=False)
    for m in re.finditer(r"wymow\w*", text):
        if not text[m.end():m.end() + 12].lstrip().startswith("nieoceni"):
            probs.append("pronunciation_claim")
    return probs


# --- narracja ---
_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_CEFR = re.compile(r"\b[ABC][12]\b")
_QUOTE = re.compile(r"[\"„“”](.+?)[\"”“]")


def _json_numbers(obj) -> set[str]:
    out: set[str] = set()

    def walk(x):
        if isinstance(x, bool) or x is None:
            return
        if isinstance(x, int | float):
            out.add(str(x).replace(",", "."))
            if isinstance(x, float) and x == int(x):
                out.add(str(int(x)))
        elif isinstance(x, str):
            out.update(n.replace(",", ".") for n in _NUM.findall(x))
        elif isinstance(x, dict):
            for k, v in x.items():
                walk(str(k))
                walk(v)
        elif isinstance(x, list | tuple):
            for v in x:
                walk(v)
    walk(obj)
    return out


def validate_narrative(text: str, rep: dict) -> list[str]:
    """Pusta lista = narracja dozwolona. Każda liczba i cytat muszą pochodzić z JSON raportu; zakaz `%`,
    poziomów CEFR spoza JSON i twierdzeń o wymowie."""
    probs = []
    dump = json.dumps(rep, ensure_ascii=False)
    nums = _json_numbers(rep)
    if "%" in text:
        probs.append("percent_sign")
    for n in _NUM.findall(text):
        if n.replace(",", ".") not in nums:
            probs.append(f"number:{n}")
    for lv in set(_CEFR.findall(text)):
        if lv not in dump:
            probs.append(f"cefr:{lv}")
    for q in _QUOTE.findall(text):
        if q not in dump:
            probs.append(f"quote:{q}")
    for m in re.finditer(r"wymow\w*", text, re.I):
        if not text[m.end():m.end() + 12].lstrip().lower().startswith("nieoceni"):
            probs.append("pronunciation_claim")
    return probs


def template_narrative(rep: dict) -> str:
    """Szablon pokazywany, gdy narracja LLM odpadnie (lub LLM niedostępny). Tylko fakty z JSON."""
    parts = []
    c = rep["counts"]
    if c["status_changes"]:
        parts.append(f"W tej sesji zmieniły się statusy umiejętności: {c['status_changes']}.")
    if rep["top_errors"]:
        e = rep["top_errors"][0]
        parts.append(f"Najważniejszy błąd do poprawy: „{e['quote']}” → „{e['fix']}”.")
    else:
        parts.append("Nie ma jeszcze wystarczająco danych o błędach.")
    if rep["strengths"]["status"] == "ok":
        s = rep["strengths"]["items"][0]
        parts.append(f"Mocna strona: „{s['quote']}”.")
    else:
        parts.append(f"Mocne strony: {NO_DATA}.")
    parts.append(rep["notes"]["disclaimer"])
    if "pronunciation" in rep["notes"]:
        parts.append(rep["notes"]["pronunciation"])
    return " ".join(parts)


def choose_narrative(llm_text: str | None, rep: dict) -> tuple[str, str]:
    """(tekst, źródło). Narracja LLM odrzucona przy jakimkolwiek naruszeniu: pokazujemy szablon."""
    if llm_text and not validate_narrative(llm_text, rep):
        return llm_text, "llm"
    return template_narrative(rep), "template"
