"""Benchmark STT na prawdziwych nagraniach ucznia (lista: `bench/cases/stt_prompts.yaml`).

  python -m bench.stt_bench record [--session NAZWA]          # nagrywa po kolei (Enter = start/stop, s = pomiń)
  python -m bench.stt_bench run --session NAZWA [--stt small.en] [--eval] [--out WYNIK.json]

Nagrania (WAV 16 kHz) i manifest zapisują się w `~/.local/share/english-ai-tutor/stt_bench/<sesja>/` — POZA Git.
Do repozytorium wolno dodać wyłącznie zagregowane metryki (bez tekstu transkrypcji z głosem właściciela, jeśli
właściciel tak zdecyduje). Ten sam katalog nagrań służy do późniejszego porównania alternatyw STT (`--stt`).

Warstwy liczone osobno (brief B-lite §6):
  1. transkrypcja — WER względem tekstu czytanego, zachowanie form `keep` (błąd ucznia / końcówki), czas STT,
     słowa niepewne (low_probs) a faktyczne pomyłki;
  2. interpretacja odpowiedzi — zadania zamknięte (`short`) przez `lesson._choice` + `lesson.check` (kod produkcyjny);
  3. ocena językowa — opcjonalnie (`--eval`): `turn_eval` na transkrypcji vs na tekście wzorcowym (ile zgłoszeń
     zmienia sama transkrypcja);
  4. wymowa — NIE oceniana (brak walidowanej metody; poprawna transkrypcja ≠ poprawna wymowa).
"""
from __future__ import annotations

import argparse
import json
import re
import time
import wave
from pathlib import Path

import numpy as np
import yaml

from tutor.config import data_dir

PROMPTS = Path(__file__).parent / "cases" / "stt_prompts.yaml"
SR = 16000


def root(session: str) -> Path:
    return data_dir() / "stt_bench" / session


def words(t: str) -> list[str]:
    return re.sub(r"[^\w' -]", " ", t.lower().replace("’", "'")).replace("-", " ").split()


def wer(ref: str, hyp: str) -> tuple[int, int]:
    r, h = words(ref), words(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
            prev, d[j] = d[j], cur
    return d[len(h)], len(r)


def kept(hyp: str, alts: str) -> bool:
    h = " " + " ".join(words(hyp)) + " "
    return any(f" {' '.join(words(a))} " in h for a in alts.split("|"))


def score(prompts: list[dict], hyps: dict[str, dict]) -> dict:
    """Czysta funkcja: `hyps[id]` = {text, low_probs, stt_s}. Brak nagrania ⇒ przypadek pominięty (nie liczony)."""
    from tutor.app import lesson as L
    edits = refs = 0
    keep = {"err": [0, 0], "ok": [0, 0], "num": [0, 0], "name": [0, 0]}
    short = [0, 0]
    low_hit = low_all = miss_flagged = miss_all = 0
    rows, times = [], []
    for p in prompts:
        h = hyps.get(p["id"])
        if h is None:
            continue
        times.append(h["stt_s"])
        row = {"id": p["id"], "kind": p["kind"], "heard": h["text"]}
        if p["kind"] == "short":
            ok = L._choice(p["options"], h["text"]).strip().lower() == p["answer"]
            short[0] += ok
            short[1] += 1
            row["ok"] = ok
        else:
            e, n = wer(p["text"], h["text"])
            edits, refs = edits + e, refs + n
            k = [kept(h["text"], a) for a in p.get("keep", [])]
            keep[p["kind"]][0] += sum(k)
            keep[p["kind"]][1] += len(k)
            row["kept"] = k
            wrong = set(words(h["text"])) - set(words(p["text"]))        # słowa, których uczeń nie powiedział
            low = set(h.get("low_probs") or [])
            low_all += len(low)
            low_hit += len(low & wrong)
            miss_all += len(wrong)
            miss_flagged += len(wrong & low)
        rows.append(row)
    ts = sorted(times)
    return {"n": len(rows), "wer": round(edits / refs, 3) if refs else None,
            "keep": {k: f"{a}/{b}" for k, (a, b) in keep.items()},
            "error_retention": round(keep["err"][0] / keep["err"][1], 3) if keep["err"][1] else None,
            "short_answer_ok": f"{short[0]}/{short[1]}",
            "low_probs_precision": round(low_hit / low_all, 3) if low_all else None,
            "misrecognitions_flagged": f"{miss_flagged}/{miss_all}",
            "stt_p50": ts[len(ts) // 2] if ts else None, "stt_p95": ts[min(len(ts) - 1, int(0.95 * len(ts)))] if ts
            else None, "pronunciation": "not assessed", "rows": rows}


def _save(path: Path, audio: np.ndarray) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype(np.int16).tobytes())


def _load(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32767


def record(session: str) -> int:
    import threading

    from tutor.voice.audio import Mic, record_manual
    d = root(session)
    d.mkdir(parents=True, exist_ok=True)
    prompts = yaml.safe_load(PROMPTS.read_text())["prompts"]
    mic = Mic()
    mic.open()
    try:
        for p in prompts:
            f = d / f"{p['id']}.wav"
            if f.exists():
                continue
            if input(f"\n[{p['id']}] Przeczytaj: {p['text']}\n  Enter = nagrywaj, s = pomiń: ").strip() == "s":
                continue
            stop = threading.Event()
            t = threading.Thread(target=lambda: input("  ● nagrywam… Enter = stop"))
            t.start()
            buf = []
            th = threading.Thread(target=lambda b=buf, s=stop: b.append(record_manual(mic, s)))
            th.start()
            t.join()
            stop.set()
            th.join()
            _save(f, buf[0])
            print(f"  zapisano {f.name} ({len(buf[0]) / SR:.1f} s)")
    finally:
        mic.close()
    (d / "manifest.json").write_text(json.dumps({"prompts": str(PROMPTS), "sr": SR}, indent=1))
    return 0


def run(session: str, stt_model: str, do_eval: bool, out: str | None) -> int:
    from tutor.voice.stt import WhisperSTT
    d = root(session)
    prompts = yaml.safe_load(PROMPTS.read_text())["prompts"]
    stt = WhisperSTT(stt_model)
    hyps = {}
    for p in prompts:
        f = d / f"{p['id']}.wav"
        if not f.exists():
            continue
        a = _load(f)
        t0 = time.monotonic()
        tr = stt.transcribe_detailed(a)
        hyps[p["id"]] = {"text": tr.text, "low_probs": tr.low_probs, "stt_s": round(time.monotonic() - t0, 2)}
    res = {"stt": stt_model, "session": session, **score(prompts, hyps)}
    if do_eval:
        res["eval_shift"] = _eval_shift(prompts, hyps)
    print(json.dumps({k: v for k, v in res.items() if k != "rows"}, ensure_ascii=False, indent=1))
    if out:
        Path(out).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


def _eval_shift(prompts: list[dict], hyps: dict) -> dict:
    """Warstwa 3: zgłoszenia oceny na transkrypcji vs na tekście wzorcowym (różnica = wpływ samego STT)."""
    from tutor.app.turn_eval import evaluate_texts
    from tutor.llm import build_provider
    from tutor.llm.structured import structured
    from tutor.pedagogy import content as C
    pack, prov = C.load("en"), build_provider("evaluation")
    same = diff = 0
    for p in prompts:
        h = hyps.get(p["id"])
        if h is None or p["kind"] == "short":
            continue
        a, b = (evaluate_texts(pack, prov, structured, [t], input_modes=[m], low_probs=[set(lp)])[0]
                for t, m, lp in ((p["text"], "text", []), (h["text"], "voice", h.get("low_probs") or [])))
        fa, fb = ({(o.span.lower(), (o.fix or "").lower()) for o in r.observations
                   if o.status == "valid" and o.kind == "error"} for r in (a, b))
        same += fa == fb
        diff += fa != fb
    return {"same_reports": same, "changed_by_stt": diff}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["record", "run"])
    ap.add_argument("--session", default="owner-1")
    ap.add_argument("--stt", default="small.en")
    ap.add_argument("--eval", action="store_true")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    return record(a.session) if a.cmd == "record" else run(a.session, a.stt, a.eval, a.out)


if __name__ == "__main__":
    raise SystemExit(main())
