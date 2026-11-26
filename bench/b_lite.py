"""Benchmark B-lite: warianty oceny wypowiedzi na zbiorze kontrolnym `control_b_lite.yaml` (lub `audit_control`).

  python -m bench.b_lite --variant A,B,C,D --split dev [--repeat 3] [--lt-url http://127.0.0.1:18081] [--out F.json]

Warianty (ten sam model roli `evaluation`, prompt `turn_eval.v3` bez zmian):
  A  obecna produkcja: bez kontekstu rozmowy, bez LanguageTool;
  B  A + poprzednia wypowiedź tutora (`tutor_prev`, pole `prev` przypadku);
  C  B + LanguageTool przez politykę fuzji `lt_merge` (F1–F5, opis w `tutor/pedagogy/lt_merge.py`);
  D  C + walidacja kandydatów tylko-LT drugim zapytaniem do tego samego modelu (tak/nie na konkretną edycję).

Poziomy zgłoszenia: `recast` = valid+error+pewność h (to widzi uczeń w rozmowie); `log` = valid+error+pewność
liczona w dzienniku błędów (h|m). Metryki na poziom: TP/FP zgłoszeń, precision (Wilson 95%), recall błędów
(wszystkie / pojedyncze / wielokrotne / kontekstowe), F0.5, fałszywe korekty na przypadkach bez błędu (FCR),
krytyczne zmiany znaczenia (poprawka usuwa token `keep`), czas oceny p50/p95. Zgłoszenie na przypadku z błędem,
które nie pasuje do żadnego oczekiwanego błędu, liczy się jako FP i trafia do listy `unexpected` (do recenzji:
autor zbioru mógł pominąć prawdziwy błąd).
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import yaml

from bench.audit_control import _applied, _fixed, _has
from bench.grammar import wilson

CASES = {"b_lite": Path(__file__).parent / "cases" / "control_b_lite.yaml",
         "audit": Path(__file__).parent / "cases" / "audit_control.yaml"}
NEG = ("clean", "variant", "critical", "ctx_clean", "voice_clean", "stt")
LEVELS = {"recast": ("h",), "log": ("h", "m")}


def load(name: str, split: str) -> list[dict]:
    cases = yaml.safe_load(CASES[name].read_text())["eval"]
    for c in cases:
        c.setdefault("split", "dev")
    return [c for c in cases if split == "all" or c["split"] == split]


def _kept(text: str, o, keep: list[str]) -> bool:
    """Poprawka nie usuwa żadnego tokenu chronionego (negacja, liczba, nazwa), który był w zdaniu."""
    after = _applied(text, o)
    return all(any(_has(after, k) for k in alts) for alts in (k.split("|") for k in keep)
               if any(_has(text, k) for k in alts))


def score(cases: list[dict], results: list, level: str = "recast") -> dict:
    """Czysta funkcja: `results[i]` = UttResult dla `cases[i]`. Zwraca metryki i wiersze do przeglądu."""
    conf = LEVELS[level]
    tp = fp = crit = unrated = neg_n = neg_fp = 0
    err = {"single": [0, 0], "multi": [0, 0], "ctx": [0, 0]}
    rows = []
    for c, res in zip(cases, results, strict=True):
        row = {"id": c["id"], "kind": c["kind"], "status": res.eval_status}
        if res.eval_status != "evaluated":
            unrated += 1
            row["verdict"] = "unrated"
            rows.append(row)
            continue
        rep = [o for o in res.observations if o.status == "valid" and o.kind == "error" and o.confidence in conf]
        row["reported"] = [[o.span, o.fix, o.category, o.confidence, o.source] for o in rep]
        errors = c.get("errors", [])
        hit = [False] * len(errors)
        for o in rep:                  # jedno zgłoszenie może naprawić kilka oczekiwanych błędów naraz
            m = [j for j, e in enumerate(errors) if _fixed(c["text"], o, e["fix_has"].split("|"))]
            if not m:
                fp += 1
                row.setdefault("unexpected" if errors else "false", []).append([o.span, o.fix])
            elif not all(hit[j] for j in m):          # duplikat już trafionego błędu: ani TP, ani FP
                tp += 1
                for j in m:
                    hit[j] = True
            if c.get("keep") and not _kept(c["text"], o, c["keep"]):
                crit += 1
                row.setdefault("critical", []).append([o.span, o.fix])
        if c["kind"] in NEG:
            neg_n += 1
            neg_fp += bool(rep)
        bucket = "ctx" if c["kind"] == "ctx_error" else "multi" if len(errors) > 1 else "single"
        if errors:
            err[bucket][0] += sum(hit)
            err[bucket][1] += len(errors)
            row["missed"] = [e["fix_has"] for e, h in zip(errors, hit, strict=True) if not h]
        rows.append(row)
    found, total = sum(v[0] for v in err.values()), sum(v[1] for v in err.values())
    p = tp / (tp + fp) if tp + fp else None
    r = found / total if total else None
    f05 = (1.25 * p * r / (0.25 * p + r)) if p and r else 0.0

    def ci(k, n):
        w = wilson(k, n)
        return [round(w[0], 3), round(w[1], 3)] if w else None
    return {"level": level, "cases": len(cases), "unrated": unrated, "tp": tp, "fp": fp,
            "precision": round(p, 3) if p is not None else None, "precision_ci": ci(tp, tp + fp),
            "recall": round(r, 3) if r is not None else None, "recall_ci": ci(found, total),
            "recall_by": {k: f"{a}/{b}" for k, (a, b) in err.items()}, "f05": round(f05, 3),
            "fcr": f"{neg_fp}/{neg_n}", "fcr_rate": round(neg_fp / neg_n, 3) if neg_n else None,
            "fcr_ci": ci(neg_fp, neg_n), "critical": crit, "rows": rows}


# --- uruchomienie na modelu ---
VERIFY = ("You check ONE proposed correction of an English learner's sentence. British and American forms are both "
          "correct. Answer JSON {{\"ok\": true}} only if the original words are clearly wrong English (not style, "
          "not a variant, not a speech-recognition guess) AND the replacement fixes them without changing the "
          "meaning; otherwise {{\"ok\": false}}.\nSentence: {text}\nOriginal words: {span}\nReplacement: {fix}")


def _lt_obs(c: dict, pack, lt_cfg: dict, forms: set[str]):
    from tutor.app import languagetool as LT
    from tutor.pedagogy import lt_merge
    ms = LT.check(c["text"], lt_cfg, disabled_categories=pack.lt_map.ignore_categories)
    if ms is None:
        return None
    # eksperyment: kandydaci `trust: h` z lt_map (wybrani na dev); produkcja używa rubric `lt_trusted_rules` (pusta)
    trusted = {k for k, r in pack.lt_map.rules.items() if r.trust == "h"}
    obs, _ = lt_merge.to_obs(ms, c["text"], pack.lt_map, input_mode=c.get("mode", "text"), known_forms=forms,
                             trusted_rules=trusted, version=pack.lt_map.lt_version_tested)
    return obs


def _verify(provider, structured, c: dict, obs):
    from pydantic import BaseModel

    from tutor.llm.base import Message

    class V(BaseModel):
        ok: bool
    out = []
    for o in obs:
        if o.p != "m" or not (o.src or "").startswith("languagetool"):
            out.append(o)
            continue
        try:
            v = structured(provider, [Message("user", VERIFY.format(text=c["text"], span=o.s, fix=o.f))], V,
                           temperature=0.0, max_tokens=20).ok
        except Exception:  # noqa: BLE001 - weryfikator niedostępny = kandydat zostaje podejrzeniem
            v = False
        out.append(o if v else o.model_copy(update={"p": "l"}))
    return out


def run_variant(variant: str, cases: list[dict], pack, provider, structured, lt_cfg: dict | None) -> tuple[list, list]:
    from tutor.app.turn_eval import evaluate_texts
    from tutor.pedagogy import content as C
    forms = {f.lower() for e in C.load_vocab(pack.root.parent).values() for f in e.forms}
    results, times = [], []
    for c in cases:
        t0 = time.monotonic()
        lt = None
        if variant in ("C", "D") and lt_cfg:
            lt = _lt_obs(c, pack, lt_cfg, forms)
            if lt is not None and variant == "D":
                lt = _verify(provider, structured, c, lt)
        prev = c.get("prev", "") if variant != "A" else ""
        results.append(evaluate_texts(pack, provider, structured, [c["text"]], input_modes=[c.get("mode", "text")],
                                      low_probs=[set(c.get("low", []))], tutor_prev=prev,
                                      lt=[lt] if lt else None)[0])
        times.append(time.monotonic() - t0)
    return results, times


def _pct(xs: list[float], q: float) -> float:
    xs = sorted(xs)
    return round(xs[min(len(xs) - 1, int(q * len(xs)))], 2)


def conversation_latency(rounds: int = 2) -> dict:
    """TTFT i czas pierwszego zdania rozmowy (rola `conversation`, prompt produkcyjny) + zasoby: RSS LanguageTool,
    VRAM. Ocena biegnie w kolejce PO odpowiedzi tutora, więc LT nie leży na ścieżce TTFT — mierzymy, czy w ogóle
    przeszkadza (CPU/RAM) gdy działa w tle."""
    from bench.grammar import _pids, rss_mib, vram_mib
    from bench.models import CONV, stream_stats
    from tutor.llm import build_provider
    from tutor.llm.base import Message
    from tutor.voice.conversation import SYSTEM_PROMPT
    p = build_provider("conversation")
    msgs = [[Message("system", SYSTEM_PROMPT), Message("user", u)] for _ in range(rounds) for u in CONV]
    rows = [stream_stats(p, m) for m in msgs]
    lt = _pids("org.languagetool.server.HTTPServer")
    t, f = sorted(r["ttft_s"] for r in rows), sorted(r["first_sentence_s"] or r["wall_s"] for r in rows)
    return {"model": p.model, "n": len(rows), "ttft_p50": round(_pct(t, 0.5), 2), "ttft_p95": round(_pct(t, 0.95), 2),
            "first_sentence_p50": round(_pct(f, 0.5), 2), "first_sentence_p95": round(_pct(f, 0.95), 2),
            "lt_running": bool(lt), "lt_rss_mib": max((rss_mib(x) or 0 for x in lt), default=None),
            "vram_mib": vram_mib()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="A")
    ap.add_argument("--split", default="dev", choices=["dev", "held", "all"])
    ap.add_argument("--set", default="b_lite", choices=sorted(CASES))
    ap.add_argument("--repeat", type=int, default=1)
    ap.add_argument("--lt-url", default=None, help="lokalny serwer LanguageTool (C/D); brak = C/D jak B")
    ap.add_argument("--out")
    ap.add_argument("--conv", action="store_true", help="tylko czas odpowiedzi rozmowy i zasoby")
    a = ap.parse_args(argv)
    if a.conv:
        r = conversation_latency()
        print(json.dumps(r, ensure_ascii=False))
        if a.out:
            Path(a.out).write_text(json.dumps(r, indent=1))
        return 0
    from tutor.llm import build_provider
    from tutor.llm.structured import structured
    from tutor.pedagogy import content as C
    pack = C.load("en")
    cases = load(a.set, a.split)
    provider = build_provider("evaluation")
    lt_cfg = None
    if a.lt_url:
        from tutor.app import languagetool as LT
        lt_cfg = LT.settings({"languagetool": {"enabled": True, "url": a.lt_url, "timeout": 3.0}})
        if LT.check("ping", lt_cfg) is None:
            print("LanguageTool niedostępny — C/D liczone bez LT")
            lt_cfg = None
    out = {"model": provider.model, "set": a.set, "split": a.split, "lt": bool(lt_cfg), "runs": []}
    for v in a.variant.split(","):
        for rep in range(a.repeat):
            res, times = run_variant(v, cases, pack, provider, structured, lt_cfg)
            run = {"variant": v, "repeat": rep, "eval_p50": _pct(times, 0.5), "eval_p95": _pct(times, 0.95),
                   "levels": {lv: score(cases, res, lv) for lv in LEVELS}}
            out["runs"].append(run)
            s = {lv: {k: x for k, x in m.items() if k != "rows"} for lv, m in run["levels"].items()}
            print(json.dumps({"variant": v, "repeat": rep, "p50": run["eval_p50"], "p95": run["eval_p95"], **s},
                             ensure_ascii=False))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
