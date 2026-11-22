"""Metryki płynności ze znaczników czasu słów Whispera (§2.6). Czyste funkcje; bez wymowy."""
from __future__ import annotations

from statistics import median

from tutor.pedagogy.content import Rubric

Word = tuple[str, float, float, float]  # (słowo, start s, koniec s, prawdopodobieństwo)


def metrics(words: list[Word], rubric: Rubric, repairs: int = 0) -> dict | None:
    """Tempo artykulacji [sł/min], długie pauzy/min, średnia długość ciągu (MLR), autonaprawy.
    Zwraca None dla < 2 słów (brak podstaw). Zapisujemy tylko agregaty, nie czasy pojedynczych słów."""
    f = rubric.fluency
    if len(words) < 2:
        return None
    art, long_p, run_p = f["articulation_pause_ms"] / 1000, f["long_pause_ms"] / 1000, f["run_pause_ms"] / 1000
    speech = words[-1][2] - words[0][1]
    gaps = [max(0.0, b[1] - a[2]) for a, b in zip(words, words[1:], strict=False)]
    pauses = sum(g for g in gaps if g >= art)
    art_time = max(speech - pauses, 1e-6)
    runs, cur = [], 1
    for g in gaps:
        if g >= run_p:
            runs.append(cur)
            cur = 1
        else:
            cur += 1
    runs.append(cur)
    return {"words": len(words), "speech_s": round(speech, 3), "articulation_s": round(art_time, 3),
            "tempo_wpm": round(len(words) / (art_time / 60), 2),
            "long_pauses": sum(1 for g in gaps if g >= long_p),
            "long_pauses_per_min": round(sum(1 for g in gaps if g >= long_p) / (speech / 60), 3),
            "mlr": round(sum(runs) / len(runs), 3), "repairs": repairs}


def aggregate(ms: list[dict]) -> dict | None:
    """Agregat sesji z metryk wypowiedzi (ważony czasem)."""
    ms = [m for m in ms if m]
    if not ms:
        return None
    speech = sum(m["speech_s"] for m in ms)
    art = sum(m["articulation_s"] for m in ms)
    return {"utterances": len(ms), "speech_s": round(speech, 3),
            "tempo_wpm": round(sum(m["words"] for m in ms) / (art / 60), 2),
            "long_pauses_per_min": round(sum(m["long_pauses"] for m in ms) / (speech / 60), 3),
            "mlr": round(sum(m["mlr"] for m in ms) / len(ms), 3), "repairs": sum(m["repairs"] for m in ms)}


def baseline(sessions: list[dict], rubric: Rubric) -> dict | None:
    """Mediana z `baseline_sessions` ostatnich sesji głosowych (linia bazowa ucznia, nie norma CEFR)."""
    last = [s for s in sessions if s][-rubric.evidence["fluency"]["baseline_sessions"]:]
    if not last:
        return None
    return {k: median(s[k] for s in last) for k in ("tempo_wpm", "long_pauses_per_min", "mlr")}


def delta_pct(cur: float, base: float) -> float:
    if base == 0:
        return 0.0 if cur == 0 else 100.0
    return (cur - base) / base * 100
