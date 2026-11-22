"""Benchmark jakości korekt (07 §5): systemy A (Bielik), B (LanguageTool), C (A+B).

  python -m bench.grammar --system A|B|C|all [--only-reviewed] [--limit N] [--out PLIK_BEZ_ROZSZERZENIA]

Zasady:
  * dopasowanie zgłoszeń do złotego standardu jest JEDNOZNACZNE (1 zgłoszenie ↔ ≤ 1 span złoty, maks. skojarzenie);
    wielokrotne trafienia w ten sam span nie podnoszą wyniku, nadmiarowe zgłoszenia to fałszywe alarmy;
  * minimalna czułość: brama wymaga recall ≥ `recall_min` ORAZ minimalnej liczby zgłoszeń — system niewykrywający
    błędów nie przechodzi;
  * brak recenzji człowieka ⇒ wynik WSTĘPNY, brama nie jest oceniana jako „dopuszczona” i nic nie zmienia w treści
    ani w `rubric.yaml`; rekomendacje tylko w raporcie.
"""
from __future__ import annotations

import argparse
import difflib
import json
import math
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from tutor.app import languagetool as LT
from tutor.app.turn_eval import evaluate_texts
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import lt_merge
from tutor.pedagogy.errors import core_of
from tutor.pedagogy.schemas import TurnEval, Utt

CASES = Path(__file__).parent / "cases" / "en"
SET_SIZES = {"E1": 45, "E2": 15, "C1": 25, "C2": 15, "C3": 10, "S": 12, "D": 8}
CLEAN_SETS = ("C1", "C2", "C3", "S", "D")


@dataclass
class Gold:
    span: str
    fix_accept: list[str]
    category: str
    severity: int = 1


@dataclass
class Case:
    id: str
    set: str
    input_mode: str
    text: str
    gold: list[Gold]
    words: list | None = None
    meaning: str | None = None
    variety: str = "any"
    status: str = "draft"


def load_cases(path: Path | None = None, only_reviewed: bool = False) -> list[Case]:
    raw = yaml.safe_load((path or CASES / "grammar_gold.yaml").read_text(encoding="utf-8"))
    out = [Case(d["id"], d["set"], d["input_mode"], d["text"], [Gold(**g) for g in d["gold"]], d.get("words"),
                d.get("meaning"), d.get("variety", "any"), d["review"]["status"]) for d in raw]
    return [c for c in out if c.status == "human_reviewed"] if only_reviewed else out


def validate_cases(cases: list[Case], *, sizes: dict[str, int] | None = SET_SIZES) -> list[str]:
    """T-BENCH-1: liczności podzbiorów, schemat, spany złote dosłownie w `text`, brak duplikatów."""
    errs, ids = [], set()
    for c in cases:
        if c.id in ids:
            errs.append(f"{c.id}: zdublowane id")
        ids.add(c.id)
        if c.input_mode not in ("text", "voice") or c.set not in SET_SIZES:
            errs.append(f"{c.id}: zły input_mode/set")
        if c.input_mode == "voice" and not c.words:
            errs.append(f"{c.id}: voice wymaga words")
        if (c.set in CLEAN_SETS) == bool(c.gold):
            errs.append(f"{c.id}: podzbiór {c.set} {'nie ' if c.set in CLEAN_SETS else ''}może mieć spany złote")
        for g in c.gold:
            if g.span not in c.text:
                errs.append(f"{c.id}: span złoty „{g.span}” nie występuje dosłownie w tekście")
            if not g.fix_accept:
                errs.append(f"{c.id}: brak fix_accept")
    if sizes:
        n = Counter(c.set for c in cases)
        errs += [f"podzbiór {k}: {n[k]} zamiast {v}" for k, v in sizes.items() if n[k] != v]
    return errs


# --- statystyka ---
def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float] | None:
    if n == 0:
        return None
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, c - h), min(1.0, c + h)


def pct(xs: list[float], q: float) -> float | None:
    if not xs:
        return None
    xs = sorted(xs)
    return xs[min(len(xs) - 1, math.ceil(q * len(xs)) - 1)]


# --- dopasowanie jednoznaczne ---
def _tokset(text: str, a: int, b: int) -> set[int]:
    return {i for i, (s, e, _) in enumerate(A._tokens(text)) if s < b and a < e}


def one_to_one(edges: dict[int, list[int]]) -> dict[int, int]:
    """Maksymalne skojarzenie (Kuhn): zgłoszenie → span złoty; każdy span złoty ma ≤ 1 zgłoszenie."""
    owner: dict[int, int] = {}

    def try_(r: int, seen: set[int]) -> bool:
        for g in edges.get(r, []):
            if g in seen:
                continue
            seen.add(g)
            if g not in owner or try_(owner[g], seen):
                owner[g] = r
                return True
        return False
    for r in sorted(edges):
        try_(r, set())
    return {r: g for g, r in owner.items()}


def match(text: str, reports: list[A.Classified], golds: list[Gold]) -> dict[int, int]:
    gr = [(g, text.find(g.span)) for g in golds]
    edges: dict[int, list[int]] = {}
    for ri, rep in enumerate(reports):
        w = A.find_spans(text, rep.span)
        if not w:
            continue
        rt = _tokset(text, *w[0])
        edges[ri] = [gi for gi, (g, a) in enumerate(gr) if a >= 0 and rt & _tokset(text, a, a + len(g.span))]
    return one_to_one(edges)


def _apply(text: str, a: int, b: int, repl: str) -> str:
    return text[:a] + repl + text[b:]


def correction_ok(text: str, rep: A.Classified, gold: Gold) -> bool:
    w = A.find_spans(text, rep.span)
    ga = text.find(gold.span)
    if not w or ga < 0 or not rep.fix:
        return False
    got = C.norm_answer(_apply(text, *w[0], rep.fix))
    return any(got == C.norm_answer(_apply(text, ga, ga + len(gold.span), acc)) for acc in gold.fix_accept)


def meaning_guard_fail(text: str, rep: A.Classified) -> bool:
    """Automatyczny strażnik: poprawka zmieniająca > 50% tokenów zdania jest podejrzana (ocena człowieka osobno)."""
    w = A.find_spans(text, rep.span)
    if not w or not rep.fix:
        return True
    a = C.norm_answer(text).split()
    b = C.norm_answer(_apply(text, *w[0], rep.fix)).split()
    same = sum(blk.size for blk in difflib.SequenceMatcher(None, a, b).get_matching_blocks())
    return (max(len(a), len(b)) - same) / max(len(a), 1) > 0.5


# --- uruchamianie systemów ---
@dataclass
class CaseRun:
    case: Case
    reports: list[A.Classified] = field(default_factory=list)       # zgłoszenia liczone
    suggestions: list[A.Classified] = field(default_factory=list)   # pozostałe ważne `error` (p=l): tylko sugestie
    rated: bool = True
    lt_ok: bool = True
    t_lt: float = 0.0
    t_eval: float = 0.0
    lt_stats: Counter = field(default_factory=Counter)


def _low(case: Case, pack: C.Pack) -> set[str]:
    thr = pack.rubric.classify["stt_prob_min"]
    return {A._t(w[0]) for w in (case.words or []) if w[3] < thr}


def run_case(system: str, case: Case, pack: C.Pack, *, provider=None, structured=None, lt_fn=None) -> CaseRun:
    run = CaseRun(case)
    lt_obs: list = []
    forms = {f.lower() for e in C.load_vocab(pack.root.parent).values() for f in e.forms}
    if system in ("B", "C"):
        t0 = time.perf_counter()
        ms = lt_fn(case.text) if lt_fn else None
        run.t_lt = time.perf_counter() - t0
        if ms is None:
            run.lt_ok = False
            if system == "B":
                run.rated = False
                return run
        else:
            # pomiar: reguły z hipotezą trust=h traktujemy jako zaufane (bez tego B nigdy nie ma p=m)
            hyp = {k for k, r in pack.lt_map.rules.items() if r.trust == "h"}
            lt_obs, run.lt_stats = lt_merge.to_obs(ms, case.text, pack.lt_map, input_mode=case.input_mode,
                                                   known_forms=forms, trusted_rules=hyp, version="6.6")
    low = _low(case, pack)
    t0 = time.perf_counter()
    if system == "B":
        ev = TurnEval(u=[Utt(i=0, o=lt_obs)])
        res = A.evaluate_batch(ev, [case.text], input_modes=[case.input_mode], low_probs=[low], pack=pack,
                               goals=set())[0]
    else:
        res = evaluate_texts(pack, provider, structured, [case.text], input_modes=[case.input_mode],
                             low_probs=[low], lt=[lt_obs] if system == "C" and lt_obs else None)[0]
    run.t_eval = time.perf_counter() - t0
    run.rated = res.rated
    ok = {"h", "m"}
    for c in res.observations:
        if c.status != "valid" or c.kind != "error":
            continue
        # B mierzy surową trafność LT (p jest tu polityką, nie trafnością); A i C: tylko p ∈ {h, m} (jak produkcja)
        (run.reports if (c.confidence in ok or system == "B") else run.suggestions).append(c)
    return run


# --- miary ---
def score(runs: list[CaseRun]) -> dict:
    tp = rep_n = gold_n = hits_correct = guard_fail = cat_agree = 0
    per_cat: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    fp_cases: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    stt = [0, 0]
    dis = [0, 0]
    sugg = 0
    for r in runs:
        c = r.case
        if not r.rated:
            continue
        sugg += len(r.suggestions)
        if c.gold:
            gold_n += len(c.gold)
        m = match(c.text, r.reports, c.gold) if c.gold else {}
        rep_n += len(r.reports)
        tp += len(m)
        for ri, rep in enumerate(r.reports):
            cat = core_of(rep.category or "?")
            per_cat[cat][0] += 1
            per_cat[cat][1] += ri in m
        for ri, gi in m.items():
            rep, g = r.reports[ri], c.gold[gi]
            hits_correct += correction_ok(c.text, rep, g)
            guard_fail += meaning_guard_fail(c.text, rep)
            cat_agree += core_of(rep.category or "?") == core_of(g.category)
        if c.set in CLEAN_SETS:
            fp_cases[c.set][0] += 1
            fp_cases[c.set][1] += bool(r.reports)
        if c.set == "S":
            stt[0] += 1
            stt[1] += not r.reports
        if c.set == "D":
            dis[0] += 1
            dis[1] += not r.reports
    clean = [fp_cases[s] for s in ("C1", "C2", "C3")]
    n123, f123 = sum(x[0] for x in clean), sum(x[1] for x in clean)
    lat_lt = [r.t_lt * 1000 for r in runs if r.t_lt]
    lat_all = [(r.t_lt + r.t_eval) for r in runs if r.rated]
    return {
        "cases": len(runs), "unrated": sum(not r.rated for r in runs), "reports": rep_n, "tp": tp, "gold": gold_n,
        "precision": tp / rep_n if rep_n else None, "precision_ci": wilson(tp, rep_n),
        "recall": tp / gold_n if gold_n else None, "recall_ci": wilson(tp, gold_n),
        "fpr": {s: (v[1] / v[0] if v[0] else None) for s, v in fp_cases.items()},
        "fpr_c123": f123 / n123 if n123 else None, "n_c123": n123,
        "bre_ame_acceptance": (1 - fp_cases["C2"][1] / fp_cases["C2"][0]) if fp_cases["C2"][0] else None,
        "stt_clean": stt[1] / stt[0] if stt[0] else None, "disfluency_clean": dis[1] / dis[0] if dis[0] else None,
        "correction_accuracy": hits_correct / tp if tp else None,
        "meaning_guard_fail": guard_fail, "meaning_human": None,
        "category_agreement": cat_agree / tp if tp else None, "explanation_human": None,
        "suggestions_p_l": sugg,
        "per_category": {k: {"reports": v[0], "hits": v[1], "precision": v[1] / v[0] if v[0] else None}
                         for k, v in sorted(per_cat.items())},
        "latency_ms": {"lt_p50": pct(lat_lt, .5), "lt_p95": pct(lat_lt, .95),
                       "queue_p50_s": pct(lat_all, .5), "queue_p95_s": pct(lat_all, .95)},
    }


def gate(sc: dict, rb_gate: dict, *, reviewed_cases: int, reviewed_gold: int, resources: dict | None = None) -> dict:
    """Kryteria 07 §5.4 + minimalna czułość. `eligible` TYLKO przy zrecenzowanym złotym standardzie
    (n ≥ 100, ≥ 50 spanów) i spełnionych wszystkich kryteriach mierzalnych bez udziału człowieka ORAZ z ocenami
    człowieka (znaczenie, wyjaśnienia). Ten moduł niczego nie odblokowuje: zwraca werdykt do raportu."""
    prec, ci = sc["precision"], sc["precision_ci"]
    rec, rci = sc["recall"], sc["recall_ci"]
    lat = sc["latency_ms"]
    res = resources or {}
    chk = {
        "precision>=0.80": prec is not None and prec >= rb_gate["precision_min"],
        "precision_wilson_low>=0.70": ci is not None and ci[0] >= 0.70,
        f"recall>={rb_gate['recall_min']}": rec is not None and rec >= rb_gate["recall_min"],
        f"recall_wilson_low>={rb_gate['recall_wilson_low_min']}":
            rci is not None and rci[0] >= rb_gate["recall_wilson_low_min"],
        f"reports>={rb_gate['min_reports']}": sc["reports"] >= rb_gate["min_reports"],
        "fpr_c123<0.10": sc["fpr_c123"] is not None and sc["fpr_c123"] < rb_gate["false_alarm_max"],
        "fpr_c2<0.10": (sc["fpr"].get("C2") is not None and sc["fpr"]["C2"] < rb_gate["false_alarm_max"]),
        "stt_clean>=0.95": sc["stt_clean"] is not None and sc["stt_clean"] >= 0.95,
        "disfluency_clean==1": sc["disfluency_clean"] == 1.0,
        "correction>=0.85": sc["correction_accuracy"] is not None and sc["correction_accuracy"] >= 0.85,
        "category_agreement>=0.85": sc["category_agreement"] is not None and sc["category_agreement"] >= 0.85,
        "meaning_human>=0.95": sc["meaning_human"] is not None and sc["meaning_human"] >= 0.95,
        "explanation_human>=4": sc["explanation_human"] is not None and sc["explanation_human"] >= 4,
        "queue_p95<=6s": lat["queue_p95_s"] is not None and lat["queue_p95_s"] <= 6,
    }
    if res.get("lt_rss_mib") is not None:
        chk["lt_rss<=1GiB"] = res["lt_rss_mib"] <= 1024
        chk["lt_p95<=300ms"] = lat["lt_p95"] is not None and lat["lt_p95"] <= 300
    pre = []
    if reviewed_cases < 100:
        pre.append(f"zrecenzowanych przypadków {reviewed_cases} < 100")
    if reviewed_gold < 50:
        pre.append(f"zrecenzowanych spanów złotych {reviewed_gold} < 50")
    return {"checks": chk, "failed": [k for k, v in chk.items() if not v], "blockers": pre,
            "eligible": not pre and all(chk.values())}


def category_recommendations(sc: dict, rb_gate: dict) -> dict:
    """REKOMENDACJA (nie zmiana konfiguracji): kategoria kwalifikuje się do `trusted_categories` przy precision ≥ 0,85
    i ≥ `category_min_n` zgłoszeń. Wpis do rubric.yaml tylko po recenzji człowieka."""
    return {k: v for k, v in sc["per_category"].items()
            if v["reports"] >= rb_gate["category_min_n"] and v["precision"] is not None
            and v["precision"] >= rb_gate["category_precision_min"]}


# --- zasoby i TTFT (tylko live) ---
def _pids(pattern: str) -> list[int]:
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True)
    return [int(x) for x in r.stdout.split() if int(x) != __import__("os").getpid()]


def rss_mib(pid: int) -> float | None:
    try:
        for ln in Path(f"/proc/{pid}/status").read_text().splitlines():
            if ln.startswith("VmRSS:"):
                return int(ln.split()[1]) / 1024
    except OSError:
        return None
    return None


def cpu_seconds(pid: int) -> float | None:
    try:
        f = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
        return (int(f[11]) + int(f[12])) / __import__("os").sysconf("SC_CLK_TCK")
    except OSError:
        return None


def vram_mib() -> float | None:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=5)
        return float(r.stdout.split()[0])
    except (OSError, ValueError, IndexError, subprocess.SubprocessError):
        return None


def measure_ttft(provider, lt_fn, text: str, n: int = 3) -> dict | None:
    """TTFT rozmowy: z bezczynnym LT vs tuż po sprawdzeniu (sekwencyjnie, jak w kolejce)."""
    from tutor.llm.base import Message

    def one() -> float:
        t0 = time.perf_counter()
        it = iter(provider.stream([Message("user", "Say hello in one short sentence.")], max_tokens=16))
        next(it)
        return time.perf_counter() - t0
    try:
        one()  # rozgrzewka
        base = [one() for _ in range(n)]
        after = []
        for _ in range(n):
            lt_fn(text)
            after.append(one())
    except Exception:  # noqa: BLE001 — pomiar opcjonalny
        return None
    b, a = sum(base) / n, sum(after) / n
    return {"baseline_s": b, "after_lt_s": a, "degradation": a / b - 1}


# --- sędzia zadań (F3 niezgodności) ---
def judge_f3(pack: C.Pack, provider, structured, lt_fn=None, path: Path | None = None) -> dict:
    from tools import gen_items
    rows = yaml.safe_load((path or CASES / "f3_mismatch.yaml").read_text(encoding="utf-8"))
    out, agree_store, agree_human, n_human = [], 0, 0, 0
    for r in rows:
        it = pack.items.get(r["item_id"])
        if it is None or it.type in C.OPEN_TYPES:
            continue
        s = gen_items.solve(pack, provider, structured, it) if provider else None
        a_store = gen_items.agrees(pack, it, s)
        a_human = None
        if r.get("human_key"):
            n_human += 1
            a_human = gen_items.agrees(pack, it, s, [r["human_key"]])
            agree_human += a_human
        agree_store += a_store
        lt_key = lt_dis = None
        if lt_fn and it.area == "grammar" and "___" in it.prompt and it.type in ("gap", "mc"):
            def flagged(opt: str, prompt: str = it.prompt) -> bool | None:
                ms = lt_fn(prompt.replace("___", opt))
                return None if ms is None else any(m.rule_id for m in ms if m.category_id not in ("TYPOS", "STYLE"))
            lt_key = flagged(it.answers[0])
            lt_dis = [flagged(o) for o in (it.options or []) if o != it.answers[0]]
        out.append({"item": it.id, "answer": s.answer if s else None, "agrees_stored_key": a_store,
                    "agrees_human_key": a_human, "lt_flags_key": lt_key, "lt_flags_distractors": lt_dis})
    n = len(out)
    return {"n": n, "agree_stored_key": agree_store, "agree_human_key": agree_human, "n_human_keys": n_human,
            "preliminary": n_human == 0, "items": out}


# --- raport ---
def _ci(v, ci):
    return f"{_f(v)} [{_f(ci[0]) if ci else '–'}; {_f(ci[1]) if ci else '–'}]"


def _f(x, d=3):
    return "–" if x is None else (f"{x:.{d}f}" if isinstance(x, float) else str(x))


def render_md(results: dict[str, dict], meta: dict) -> str:
    L = ["# Benchmark korekt gramatycznych — F4.6", ""]
    pre = meta["reviewed_cases"] == 0
    L.append("> **WSTĘPNY — złoty standard niezrecenzowany, bramy nieotwierane.**" if pre else
             f"> Zrecenzowanych przypadków: {meta['reviewed_cases']}.")
    L += ["", f"Zestaw: {meta['n_cases']} przypadków ({meta['n_reviewed']} human_reviewed). "
          f"LanguageTool: {meta.get('lt_version', 'niedostępny')}. Model oceny: {meta.get('model', '–')}. "
          f"Data: {meta['date']}.", ""]
    L += ["| miara | " + " | ".join(results) + " |", "|---|" + "---|" * len(results)]
    def row(name, fn):
        L.append(f"| {name} | " + " | ".join(fn(r["score"]) for r in results.values()) + " |")
    row("przypadki ocenione / nieocenione", lambda s: f"{s['cases'] - s['unrated']}/{s['unrated']}")
    row("zgłoszenia liczone", lambda s: str(s["reports"]))
    row("trafienia (1:1)", lambda s: f"{s['tp']}/{s['gold']}")
    row("precision [Wilson 95%]", lambda s: _ci(s["precision"], s["precision_ci"]))
    row("recall [Wilson 95%]", lambda s: _ci(s["recall"], s["recall_ci"]))
    row("FPR C1+C2+C3", lambda s: _f(s["fpr_c123"]))
    row("FPR C1 / C2 / C3", lambda s: " / ".join(_f(s["fpr"].get(k)) for k in ("C1", "C2", "C3")))
    row("akceptacja BrE/AmE (1−FPR C2)", lambda s: _f(s["bre_ame_acceptance"]))
    row("S: bez zgłoszeń liczonych", lambda s: _f(s["stt_clean"]))
    row("D: bez zgłoszeń liczonych", lambda s: _f(s["disfluency_clean"]))
    row("poprawność korekty", lambda s: _f(s["correction_accuracy"]))
    row("zgodność kategorii", lambda s: _f(s["category_agreement"]))
    row("strażnik znaczenia: podejrzane poprawki", lambda s: str(s["meaning_guard_fail"]))
    row("sugestie (p=l, poza zgłoszeniami)", lambda s: str(s["suggestions_p_l"]))
    row("LT p50/p95 [ms]", lambda s: "/".join(_f(s["latency_ms"][k], 0) for k in ("lt_p50", "lt_p95")))
    row("kolejka p50/p95 [s]", lambda s: "/".join(_f(s["latency_ms"][k], 2) for k in ("queue_p50_s", "queue_p95_s")))
    L += ["", "## Brama jakości (07 §5.4 + minimalna czułość)", ""]
    for k, r in results.items():
        g = r["gate"]
        L.append(f"- **System {k}**: {'DOPUSZCZONY' if g['eligible'] else 'NIE dopuszczony'}. "
                 f"Blokery: {'; '.join(g['blockers']) or 'brak'}. Niespełnione: {', '.join(g['failed']) or 'brak'}.")
    L += ["", "## Rekomendacje kategorii (nie zmieniają konfiguracji)", ""]
    for k, r in results.items():
        rec = r["recommend"]
        txt = ", ".join(f"{c} (p={v['precision']:.2f}, n={v['reports']})" for c, v in rec.items())
        L.append(f"- System {k}: " + (txt or "żadna kategoria nie spełnia progu (precision ≥ 0,85, n ≥ 8)"))
    L += ["", "## Precision per kategoria (zgłoszona kategoria rdzeniowa)", ""]
    for k, r in results.items():
        L.append(f"**{k}**: " + ", ".join(f"{c} {v['hits']}/{v['reports']}"
                                          for c, v in r["score"]["per_category"].items()))
    if meta.get("resources"):
        L += ["", "## Zasoby i wpływ na rozmowę", "", "```json", json.dumps(meta["resources"], indent=1), "```"]
    if meta.get("judge"):
        j = meta["judge"]
        L += ["", "## Sędzia zadań (11 niezgodności F3)", "",
              f"Zgodność Bielika z kluczem w bazie: {j['agree_stored_key']}/{j['n']}; z kluczem człowieka: "
              f"{j['agree_human_key']}/{j['n_human_keys']}"
              + (" — **wstępnie, brak kluczy człowieka**" if j["preliminary"] else "")]
    return "\n".join(L) + "\n"


class CachingProvider:
    """Ten sam prompt (temperatura 0) nie jest liczony drugi raz: system C korzysta z odpowiedzi modelu systemu A.
    Opóźnienie C = opóźnienie A + LT (dodawane w `run_all`), nie czas trafienia w cache."""

    def __init__(self, inner):
        self.inner, self.cache = inner, {}

    def chat(self, messages, **kw):
        key = json.dumps([getattr(m, "content", str(m)) for m in messages] + [kw.get("max_tokens")])
        if key not in self.cache:
            self.cache[key] = self.inner.chat(messages, **kw)
        return self.cache[key]

    def __getattr__(self, name):
        return getattr(self.inner, name)


def run_all(systems: list[str], cases: list[Case], pack: C.Pack, *, provider=None, structured=None, lt_fn=None,
            meta_extra: dict | None = None, reviewed: list[Case] | None = None) -> tuple[dict, dict]:
    rb_gate = pack.rubric.correction["quality_gate"]
    reviewed = [c for c in (reviewed if reviewed is not None else cases) if c.status == "human_reviewed"]
    res = {}
    for s in systems:
        runs = [run_case(s, c, pack, provider=provider, structured=structured, lt_fn=lt_fn) for c in cases]
        if s == "C" and "A" in res and isinstance(provider, CachingProvider):
            for rc, ra in zip(runs, res["A"]["runs"], strict=True):
                rc.t_eval += ra.t_eval                       # wynik modelu pochodzi z cache systemu A
        sc = score(runs)
        res[s] = {"score": sc, "runs": runs,
                  "gate": gate(sc, rb_gate, reviewed_cases=len(reviewed),
                               reviewed_gold=sum(len(c.gold) for c in reviewed),
                               resources=(meta_extra or {}).get("resources")),
                  "recommend": category_recommendations(sc, rb_gate)}
    meta = {"n_cases": len(cases), "n_reviewed": len(reviewed), "reviewed_cases": len(reviewed),
            "date": time.strftime("%Y-%m-%d"), **(meta_extra or {})}
    return res, meta


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="bench.grammar")
    ap.add_argument("--system", default="all", choices=["A", "B", "C", "all"])
    ap.add_argument("--only-reviewed", action="store_true")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--judge", action="store_true", help="także sędzia zadań (11 niezgodności F3)")
    a = ap.parse_args(argv)
    from tutor.llm import build_provider
    from tutor.llm.structured import structured
    pack = C.load("en")
    allc = load_cases()
    cases = load_cases(only_reviewed=a.only_reviewed)
    if a.limit:
        cases = cases[:a.limit]
    cfg = LT.settings()
    cfg["enabled"] = True
    pat = _pids("org.languagetool.server.HTTPServer")
    lt_ok = LT.check("ping", cfg) is not None
    lt_fn = (lambda t: LT.check(t, cfg, disabled_categories=pack.lt_map.ignore_categories)) if lt_ok else None
    systems = ["A", "B", "C"] if a.system == "all" else [a.system]
    systems = [s for s in systems if s == "A" or lt_ok]
    provider = CachingProvider(build_provider("evaluation"))
    cpu0 = {p: cpu_seconds(p) for p in pat}
    t0 = time.perf_counter()
    meta_extra = {"lt_version": pack.lt_map.lt_version_tested if lt_ok else None, "model": provider.model}
    res, meta = run_all(systems, cases, pack, provider=provider, structured=structured, lt_fn=lt_fn,
                        meta_extra=meta_extra, reviewed=allc)
    wall = time.perf_counter() - t0
    resources = {"lt_rss_mib": max((rss_mib(p) or 0 for p in pat), default=None) if pat else None,
                 "vram_mib": vram_mib(),
                 "lt_cpu_pct": (100 * sum((cpu_seconds(p) or 0) - (cpu0[p] or 0) for p in pat) / wall) if pat else None,
                 "ollama_rss_mib": max((rss_mib(p) or 0 for p in _pids("ollama")), default=None),
                 "wall_s": wall}
    if lt_fn:
        resources["ttft"] = measure_ttft(provider, lt_fn, "She have a apple.")
    meta["resources"] = resources
    if a.judge:
        meta["judge"] = judge_f3(pack, provider, structured, lt_fn)
    md = render_md(res, meta)
    print(md)
    if a.out:
        a.out.with_suffix(".md").write_text(md, encoding="utf-8")
        a.out.with_suffix(".json").write_text(json.dumps({"meta": meta, "systems": {
            k: {"score": v["score"], "gate": v["gate"], "recommend": v["recommend"]} for k, v in res.items()}},
            indent=1, ensure_ascii=False, default=str), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
