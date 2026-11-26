"""F7: pomiar jakości nauczyciela na prawdziwym modelu (Ollama, rola `evaluation`/`conversation`).

  python -m bench.teacher [--out PLIK.json] [--skip-conv]

Oczekiwania z `bench/cases/teacher_f7.yaml` są ustalone ręcznie, niezależnie od modelu (Qwen3 nie ocenia sam siebie).
Mierzy: fałszywe korekty (zgłoszenie błędu w zdaniu poprawnym), pominięte błędy, błędne kategorie, wyjaśnienia
dopasowane do błędu, rozpoznanie poleceń, czas oceny; w rozmowie: czas odpowiedzi, odsetek odpowiedzi z pytaniem,
stockowe pochwały, zmyślone doświadczenia („I went / my family…”). Działa też na starszym kodzie (porównanie przed/po:
uruchom z PYTHONPATH wskazującym inną kopię repozytorium).
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import time
from pathlib import Path

import yaml

CASES = Path(__file__).parent / "cases" / "teacher_f7.yaml"
_PRAISE = re.compile(r"\b(great job|well done|you'?re doing great|good job|excellent|awesome|amazing|fantastic)\b",
                     re.I)
_FAKE_EXP = re.compile(r"\b(i (went|visited|have been|used to|grew up|live|lived|remember when|love|enjoy|like)|"
                       r"my (family|wife|husband|kids|children|mother|father|friend|job|hometown))\b", re.I)
_EXCL = re.compile(r"^\W*\w[^.?!]{0,45}!")


def _cat_ok(cat: str, want: str) -> bool:
    return any(w in (cat or "") for w in want.split("|"))


def _applied(text: str, o) -> str:
    """Zdanie po zastosowaniu poprawki (oczekiwanie sprawdzamy na wyniku, nie na samym fragmencie)."""
    return text.replace(o.span, o.fix or "", 1) if o.span in text else (o.fix or "")


def eval_cases(pack, provider, structured, cases: list[dict]) -> dict:
    from tutor.app.turn_eval import evaluate_texts
    try:
        from tutor.app.feedback import explain_edit
    except ImportError:                                  # starszy kod: wyjaśnienie ogólne z kategorii
        from tutor.app.feedback import _explain

        def explain_edit(pack, span, fix, cat):
            return _explain(pack, cat)
    rows, times = [], []
    fp = miss = wrong_cat = expl_ok = expl_n = clean_n = err_n = 0
    for c in cases:
        mode = c.get("mode", "text")
        t0 = time.monotonic()
        res = evaluate_texts(pack, provider, structured, [c["text"]], input_modes=[mode],
                             low_probs=[set(c.get("low", []))])[0]
        times.append(time.monotonic() - t0)
        rep = [o for o in res.observations if o.status == "valid" and o.kind == "error" and o.confidence == "h"]
        row = {"id": c["id"], "text": c["text"], "reported": [[o.span, o.fix, o.category] for o in rep],
               "status": res.eval_status, "drops": res.drops}
        if c.get("clean") or c.get("clean_or_stt"):
            clean_n += 1
            if rep:
                fp += 1
                row["verdict"] = "false_correction"
        for e in c.get("errors", []):
            err_n += 1
            hit = [o for o in rep if e["fix_has"].lower() in _applied(c["text"], o).lower()]
            if not hit:
                miss += 1
                row.setdefault("verdict", "missed")
                continue
            if not _cat_ok(hit[0].category, e["cat"]):
                wrong_cat += 1
                row["verdict"] = f"wrong_category:{hit[0].category}"
            if "explain_kw" in e:
                expl_n += 1
                why = explain_edit(pack, hit[0].span, hit[0].fix, hit[0].category or "")
                row["why"] = why
                if e["explain_kw"].lower() in why.lower():
                    expl_ok += 1
        rows.append(row)
    return {"clean_cases": clean_n, "false_corrections": fp, "error_cases": err_n, "missed": miss,
            "wrong_category": wrong_cat, "explanations_specific": f"{expl_ok}/{expl_n}",
            "eval_s_median": round(statistics.median(times), 2), "eval_s_max": round(max(times), 2), "rows": rows}


def commands(cases: list[dict]) -> dict:
    from tutor.app import intent as I
    ok, bad = 0, []
    for c in cases:
        got = I.detect(c["text"])
        if got == "finish" and c["want"] is None:
            got = "finish"
        if got == c["want"]:
            ok += 1
        else:
            bad.append({"text": c["text"], "want": c["want"], "got": got})
    return {"correct": f"{ok}/{len(cases)}", "errors": bad}


def conversation(provider, turns: list[str]) -> dict:
    from tutor.llm.base import Message
    from tutor.voice import conversation as CV
    note = getattr(CV, "style_note", lambda prev: "")          # starszy kod: bez notatki stylu
    msgs = [Message("system", CV.SYSTEM_PROMPT), Message("assistant", "Hi! What do you do for a living?")]
    out, times = [], []
    for u in turns:
        msgs[0] = Message("system", CV.SYSTEM_PROMPT + note(out[-3:]))
        msgs.append(Message("user", u))
        t0 = time.monotonic()
        r = provider.chat(msgs, temperature=0.7, max_tokens=100).text.strip()
        times.append(time.monotonic() - t0)
        from tutor.voice.guard import Guard  # ten sam filtr co w rozmowie (stare i nowe wersje)
        g = Guard(out[-8:])
        r = " ".join(x for x in (g(s) for s in re.split(r"(?<=[.!?])\s+", r) if s.strip()) if x) or r
        msgs.append(Message("assistant", r))
        out.append(r)
    q = sum("?" in r for r in out)
    starts = [r.split()[0].lower().strip(",.!") for r in out if r.split()]
    return {"replies": out, "with_question": f"{q}/{len(out)}",
            "stock_praise": sum(bool(_PRAISE.search(r)) for r in out),
            "exclamation_openings": sum(bool(_EXCL.match(r)) for r in out),
            "invented_experience": sum(bool(_FAKE_EXP.search(r)) for r in out),
            "distinct_openings": f"{len(set(starts))}/{len(starts)}",
            "reply_s_median": round(statistics.median(times), 2), "reply_s_max": round(max(times), 2)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    ap.add_argument("--skip-conv", action="store_true")
    a = ap.parse_args(argv)
    from tutor.llm import build_provider
    from tutor.llm.structured import structured
    from tutor.pedagogy import content as C
    data = yaml.safe_load(CASES.read_text())
    pack = C.load("en")
    ev = build_provider("evaluation")
    res = {"model": ev.model, "eval": eval_cases(pack, ev, structured, data["eval"]),
           "commands": commands(data["commands"])}
    if not a.skip_conv:
        res["conversation"] = conversation(build_provider("conversation"), data["conversation"])
    summary = {k: v for k, v in res["eval"].items() if k != "rows"}
    print(json.dumps({"model": res["model"], "eval": summary, "commands": res["commands"]["correct"],
                      "conversation": {k: v for k, v in res.get("conversation", {}).items() if k != "replies"}},
                     indent=1, ensure_ascii=False))
    if a.out:
        Path(a.out).write_text(json.dumps(res, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
