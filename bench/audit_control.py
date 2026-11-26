"""Niezależny zestaw kontrolny oceny wypowiedzi (audyt końcowy F7) na prawdziwym modelu roli `evaluation`.

  python -m bench.audit_control [--out PLIK.json] [--repeat N]

Kryteria w `bench/cases/audit_control.yaml` (ustalone przed uruchomieniem, niezależnie od modelu).
Zgłoszenie = obserwacja `valid`, `kind=error`, `confidence=h` — dokładnie to, co trafia do dziennika błędów.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from collections import Counter
from pathlib import Path

import yaml

CASES = Path(__file__).parent / "cases" / "audit_control.yaml"


def _applied(text: str, o) -> str:
    """Zdanie po poprawce. Najpierw dopasowanie całych słów („an” nie trafia w „Can”), potem podciąg."""
    pat = rf"(?<!\w){re.escape(o.span)}(?!\w)" if o.span else None
    if pat and re.search(pat, text):
        s = re.sub(pat, lambda _m: o.fix or "", text, count=1)
    else:
        s = text.replace(o.span, o.fix or "", 1) if o.span and o.span in text else (o.fix or "")
    return " ".join(s.split())


def _has(text: str, phrase: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(phrase)}(?!\w)", text, re.I) is not None


def _fixed(text: str, o, alts: list[str]) -> bool:
    """Oczekiwana forma pojawia się dopiero po poprawce (nie była w zdaniu: „children” ⊄ „childrens”)."""
    return any(_has(_applied(text, o), a) and not _has(text, a) for a in alts)


def score(cases: list[dict], results: list) -> dict:
    """Czysta funkcja (testowalna bez modelu): `results[i]` = UttResult dla `cases[i]`."""
    by_kind: Counter = Counter()
    fp: Counter = Counter()
    err_n = hit_n = cat_ok = unrated = 0
    rows = []
    for c, res in zip(cases, results, strict=True):
        rep = [o for o in res.observations if o.status == "valid" and o.kind == "error" and o.confidence == "h"]
        row = {"id": c["id"], "kind": c["kind"], "status": res.eval_status,
               "reported": [[o.span, o.fix, o.category] for o in rep],
               "stt_suspect": [[o.span, o.fix] for o in res.observations if o.kind == "stt_suspect"]}
        by_kind[c["kind"]] += 1
        if res.eval_status != "evaluated":
            unrated += 1
            row["verdict"] = "unrated"
        elif c["kind"] in ("clean", "variant", "stt") and rep:
            fp[c["kind"]] += 1
            row["verdict"] = "false_correction"
        for e in c.get("errors", []):
            err_n += 1
            alts = e["fix_has"].split("|")
            hit = [o for o in rep if _fixed(c["text"], o, alts)]
            if hit:
                hit_n += 1
                cat_ok += any(w in (hit[0].category or "") for w in e["cat"].split("|"))
            else:
                row.setdefault("missed", []).append(e["fix_has"])
        rows.append(row)
    neg = {k: by_kind[k] for k in ("clean", "variant", "stt")}
    return {"cases": len(cases), "unrated": unrated,
            "false_corrections": {k: f"{fp[k]}/{n}" for k, n in neg.items()},
            "false_correction_rate": round(sum(fp.values()) / max(1, sum(neg.values())), 3),
            "errors_detected": f"{hit_n}/{err_n}", "category_ok": f"{cat_ok}/{hit_n}", "rows": rows}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--repeat", type=int, default=1, help="powtórzenia (stabilność przy temperature=0)")
    a = ap.parse_args(argv)
    from tutor.app.turn_eval import evaluate_texts
    from tutor.llm import build_provider
    from tutor.llm.structured import structured
    from tutor.pedagogy import content as C
    cases = yaml.safe_load(CASES.read_text())["eval"]
    pack = C.load("en")
    ev = build_provider("evaluation")
    runs = []
    for _ in range(a.repeat):
        results, times = [], []
        for c in cases:
            t0 = time.monotonic()
            results.append(evaluate_texts(pack, ev, structured, [c["text"]], input_modes=[c.get("mode", "text")],
                                          low_probs=[set(c.get("low", []))])[0])
            times.append(time.monotonic() - t0)
        r = score(cases, results)
        r["eval_s_median"] = round(statistics.median(times), 2)
        runs.append(r)
    out = {"model": ev.model, "runs": runs}
    print(json.dumps({"model": ev.model, "runs": [{k: v for k, v in r.items() if k != "rows"} for r in runs]},
                     indent=1, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
