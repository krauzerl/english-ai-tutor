"""Symulacja diagnozy (kod produkcyjny `pedagogy.diagnosis`, prawdziwy bank `app.diagnostic.items_for`).

  python -m bench.diagnosis_sim [--n 10,15,20] [--learners 300] [--out bench/results/b_lite/diagnosis_sim.json]

To NIE jest trafność poziomu CEFR. Symulowany uczeń odpowiada według tego samego modelu 1PL, którego używa
diagnoza („model idealny” = górna granica), a w wariancie `noisy_b` według trudności przesuniętych o N(0, 0,5)
(bank nieskalibrowany — bliżej rzeczywistości). Metryki: trafny poziom (etykieta θ̂ = etykieta θ), mediana sd,
szerokość przedziału 80 %, pokrycie przedziału 80 %, zgodność dwóch niezależnych przebiegów (test–retest tego samego
ucznia, inne losowanie odpowiedzi), wpływ priora z innego obszaru (niezależność kompetencji) i szacowany czas.
"""
from __future__ import annotations

import argparse
import json
import random
import statistics
from pathlib import Path

from tutor.app.diagnostic import CLOSED, items_for
from tutor.pedagogy import content as C
from tutor.pedagogy import diagnosis as D
from tutor.pedagogy.cefr import label_of

SECONDS = {"mc": 25, "gap": 35, "reading_mc": 60, "listening_mc": 40}   # założenie (brak pomiaru czasu odpowiedzi)


def one(items, rb, theta: float, seed: int, *, noise: dict[str, float] | None = None, prior=None) -> dict:
    rng = random.Random(seed)
    st = {"area": "sim", "mode": "provisional", "seed": seed, "asked": [], "elapsed_min": 0.0, "prior": prior}
    secs = 0
    while D.stop_reason(st, rb) is None and (it := D.next_item(st, items, rb)):
        b = D.item_b(it, rb) + (noise or {}).get(it.id, 0.0)
        st = D.record(st, it, rng.random() < D.p_correct(theta, b, D.item_g(it), rb.diagnosis["slope"]), rb)
        secs += SECONDS.get(it.type, 30)
    r = D.result(st, rb)
    return {"theta": r.theta, "se": r.se, "lo": r.lo, "hi": r.hi, "n": r.n_items, "secs": secs,
            "ok": label_of(r.theta, 5) == label_of(theta, 5), "cover": r.lo <= theta <= r.hi}


def area_sim(pack, area: str, n: int, learners: int, noisy: bool) -> dict:
    rb = pack.rubric.model_copy(deep=True)
    rb.diagnosis["max_items"] = n
    items = items_for(pack, area)
    rng = random.Random(f"{area}:{n}:{noisy}")
    noise = {i.id: rng.gauss(0, 0.5) for i in items} if noisy else None
    rows, agree = [], 0
    for k in range(learners):
        th = rng.uniform(0.8, 5.2)
        a, b = one(items, rb, th, 2 * k, noise=noise), one(items, rb, th, 2 * k + 1, noise=noise)
        rows.append(a)
        agree += label_of(a["theta"], 5) == label_of(b["theta"], 5)
    q = lambda xs: round(statistics.median(xs), 2)  # noqa: E731
    return {"area": area, "max_items": n, "bank": len(items), "noisy_b": noisy,
            "level_ok": round(sum(r["ok"] for r in rows) / learners, 3),
            "sd_median": q([r["se"] for r in rows]), "interval80_width": q([r["hi"] - r["lo"] for r in rows]),
            "coverage80": round(sum(r["cover"] for r in rows) / learners, 3),
            "retest_same_level": round(agree / learners, 3), "items_median": q([r["n"] for r in rows]),
            "minutes_median": round(statistics.median(r["secs"] for r in rows) / 60, 1)}


def prior_effect(pack, n: int, learners: int) -> dict:
    """Uczeń z gramatyką o 2 poziomy niższą niż słownictwo: o ile prior z gramatyki zaniża wynik słownictwa."""
    rb = pack.rubric.model_copy(deep=True)
    rb.diagnosis["max_items"] = n
    items = items_for(pack, "vocabulary")
    from tutor.app.diagnostic import PRIOR_SD
    bias_with, bias_without = [], []
    for k in range(learners):
        th = 4.0
        bias_with.append(one(items, rb, th, k, prior=[2.0, PRIOR_SD])["theta"] - th)
        bias_without.append(one(items, rb, th, k)["theta"] - th)
    return {"max_items": n, "true_vocab": 4.0, "grammar_prior_mean": 2.0, "prior_sd": PRIOR_SD,
            "bias_with_prior": round(statistics.mean(bias_with), 2),
            "bias_default_prior": round(statistics.mean(bias_without), 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", default="10,15,20")
    ap.add_argument("--learners", type=int, default=300)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    pack = C.load("en")
    ns = [int(x) for x in a.n.split(",")]
    areas = [x for x in CLOSED if len(items_for(pack, x)) >= pack.rubric.diagnosis["min_items"]]
    out = {"note": "symulacja ≠ trafność CEFR; uczeń odpowiada wg modelu diagnozy (noisy_b: trudności ±0,5)",
           "seconds_per_item_assumed": SECONDS, "areas": [], "prior": []}
    for area in areas:
        for n in ns:
            for noisy in (False, True):
                r = area_sim(pack, area, n, a.learners, noisy)
                out["areas"].append(r)
                print(json.dumps(r, ensure_ascii=False))
    for n in ns:
        r = prior_effect(pack, n, a.learners)
        out["prior"].append(r)
        print(json.dumps(r, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps(out, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
