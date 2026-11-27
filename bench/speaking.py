"""Korekty w Quick Chat: pomiar przed/po (`bench/cases/speaking_corrections.yaml`).

Dwie części:
* `policy` — prawdziwa ocena Qwen3 (`turn_eval.v3`) + walidatory, potem decyzja w rozmowie: STARA (recast każdego
  błędu `h` z sev ≥ 2 i łagodne sprawdzenie każdego `stt_suspect`) vs NOWA (`correction.impact`: natychmiast tylko
  poważne, drobne do podsumowania, STT tylko przy sensie). Ta sama odpowiedź modelu dla obu polityk.
* `chat` — odpowiedź modelu rozmowy (bez notatki o korekcie) na stary i nowy prompt systemowy: czy tutor SAM
  poprawia ucznia (regex + lista do ręcznego przeglądu), pytania, czas.

Etykiety zbioru są niezweryfikowane (autor AI); nie oceniamy poprawności opinią Qwen3. Wyniki: `--out`.
"""
from __future__ import annotations

import argparse
import json
import re
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
CASES = ROOT / "cases" / "speaking_corrections.yaml"
OLD_LINE = ("If a mistake would confuse a listener, model the correct phrasing naturally in your reply; "
            "otherwise ignore small slips. ")
SELF_CORR = re.compile(r"\byou could (?:say|also say|use)\b|\binstead of\b|\bthe correct\b|\bcorrect(?:ly)? (?:form|"
                       r"way)\b|\byou should say\b|\bis correct, but\b|\bwe (?:usually )?say\b|\bbetter to say\b|"
                       r"\bmore natural\b|\bjust a (?:quick|small) note\b|\bit's \"|\bsmall correction\b", re.I)
INTERRUPT = {"immediate", "recast", "ask_stt", "stt_check"}


def load(split: str) -> list[dict]:
    d = yaml.safe_load(CASES.read_text(encoding="utf-8"))
    return [c for c in d["cases"] if split == "all" or c["split"] == split]


def old_decision(o) -> str | None:
    if o.status != "valid" or o.confidence != "h" or not o.fix:
        return None
    if o.kind == "stt_suspect":
        return "stt_check"
    if o.kind == "error":
        return "recast" if (o.severity or 1) >= 2 else "summary"
    return None


def new_decision(o, text: str, rubric) -> str | None:
    from tutor.pedagogy import correction as K
    if not hasattr(K, "impact"):              # uruchomienie na kodzie sprzed zmian (baseline)
        return None
    if o.status != "valid" or o.confidence != "h" or not o.fix or o.kind not in ("error", "stt_suspect"):
        return None
    tier, _ = K.impact(text, o.span, o.fix, o.category or "", rubric=rubric)
    if o.kind == "stt_suspect":
        return "ask_stt" if tier == K.SERIOUS else "skipped_stt"
    if tier == K.SERIOUS:
        return "immediate"
    if tier == K.GRAMMAR and (o.severity or 1) >= rubric.correction["sev_min_interrupt"]:
        return "recast"
    return "summary"


def _hit(c: dict, fix: str | None, text: str, span: str) -> bool:
    if not fix or not c.get("fix_has"):
        return False
    after = text.replace(span, fix, 1).lower()
    return any(f.lower() in after for f in c["fix_has"].split("|"))


def score(cases: list[dict], rows: list[dict], key: str) -> dict:
    out = {"n": len(cases), "false_interventions": 0, "false_cases": [], "serious_n": 0, "serious_caught": 0,
           "serious_any": 0, "grammar_n": 0, "grammar_recast": 0, "interventions": 0, "summary_items": 0,
           "summary_on_clean": 0}
    for c, r in zip(cases, rows, strict=True):
        ds = r[key]
        inter = [d for d in ds if d["decision"] in INTERRUPT]
        out["interventions"] += len(inter)
        out["summary_items"] += sum(d["decision"] == "summary" for d in ds)
        if c["kind"] in ("clean", "bre", "ame") and any(d["decision"] == "summary" for d in ds):
            out["summary_on_clean"] += 1
        if c["kind"] in ("clean", "bre", "ame", "minor", "stt", "bait") and inter:
            out["false_interventions"] += 1
            out["false_cases"].append(c["id"])
        if c["kind"] == "serious":
            out["serious_n"] += 1
            want = "immediate" if key == "new" else "recast"
            out["serious_caught"] += any(d["decision"] == want and _hit(c, d["fix"], c["text"], d["span"])
                                         for d in ds)
            out["serious_any"] += any(d["decision"] in INTERRUPT and _hit(c, d["fix"], c["text"], d["span"])
                                      for d in ds)
        if c["kind"] == "grammar":
            out["grammar_n"] += 1
            out["grammar_recast"] += any(d["decision"] in INTERRUPT for d in ds)
    return out


def run_policy(cases: list[dict]) -> dict:
    from tutor.app.turn_eval import evaluate_texts
    from tutor.llm import build_provider
    from tutor.llm.structured import structured
    from tutor.pedagogy import content as C
    pack, prov = C.load("en"), build_provider("evaluation")
    rows, times = [], []
    for c in cases:
        t0 = time.monotonic()
        r = evaluate_texts(pack, prov, structured, [c["text"]], input_modes=[c.get("mode", "text")],
                           low_probs=[set(c.get("low", []))])[0]
        times.append(time.monotonic() - t0)
        obs = [o for o in r.observations]
        rows.append({"id": c["id"], "kind": c["kind"], "status": r.eval_status,
                     "obs": [{"kind": o.kind, "status": o.status, "drop": o.drop_reason, "span": o.span, "fix": o.fix,
                              "cat": o.category, "sev": o.severity, "conf": o.confidence} for o in obs],
                     "old": [{"decision": d, "span": o.span, "fix": o.fix} for o in obs
                             if (d := old_decision(o))],
                     "new": [{"decision": d, "span": o.span, "fix": o.fix} for o in obs
                             if (d := new_decision(o, c["text"], pack.rubric))]})
    times.sort()
    return {"model": prov.model, "rows": rows, "old": score(cases, rows, "old"), "new": score(cases, rows, "new"),
            "eval_p50": round(times[len(times) // 2], 2), "eval_p95": round(times[int(len(times) * 0.95) - 1], 2)}


def run_chat(cases: list[dict], repeat: int = 2) -> dict:
    from bench.models import stream_stats
    from tutor.app import quickchat as QC
    from tutor.llm import build_provider
    from tutor.llm.base import Message
    from tutor.voice import conversation as CV
    p = build_provider("conversation")
    topic = {"pl": "Travel and work", "category": "general", "category_pl": "General English"}
    new_sys = QC.system_prompt(topic, "B1", "natural")
    old_sys = new_sys.replace(CV.NO_SELF_CORRECT, OLD_LINE)
    assert old_sys != new_sys
    out = {}
    for name, sysp in (("old", old_sys), ("new", new_sys)):
        rows = []
        for rep in range(repeat):
            for c in cases:
                m = [Message("system", sysp), Message("assistant", "What have you been up to recently?"),
                     Message("user", c["text"])]
                st = stream_stats(p, m, max_tokens=100, temperature=0.7)
                rows.append({"id": c["id"], "kind": c["kind"], "rep": rep, "reply": st["text"],
                             "self_correction": bool(SELF_CORR.search(st["text"])), "question": "?" in st["text"],
                             "ttft_s": st["ttft_s"], "first_sentence_s": st["first_sentence_s"]})
        t = sorted(r["ttft_s"] or 0 for r in rows)
        f = sorted(r["first_sentence_s"] or 0 for r in rows)
        out[name] = {"n": len(rows), "self_corrections": sum(r["self_correction"] for r in rows),
                     "self_corr_on_correct": sum(r["self_correction"] for r in rows
                                                 if r["kind"] in ("clean", "bre", "ame")),
                     "questions": sum(r["question"] for r in rows),
                     "ttft_p50": round(t[len(t) // 2], 2), "first_sentence_p50": round(f[len(f) // 2], 2),
                     "first_sentence_p95": round(f[int(len(f) * 0.95) - 1], 2), "rows": rows}
    return out


def run_chat_multi(cases: list[dict], per: int = 5, repeat: int = 1) -> dict:
    """Rozmowy wieloturowe (po `per` wypowiedzi z rzędu, odpowiedzi modelu w historii): nowy prompt sam vs nowy
    prompt + notatka przy wiadomości ucznia (`intent.NO_CORRECT_NOTE`). Liczymy komentarze o języku ucznia."""
    from bench.models import stream_stats
    from tutor.app import intent as INTENT
    from tutor.app import quickchat as QC
    from tutor.llm import build_provider
    from tutor.llm.base import Message
    p = build_provider("conversation")
    topic = {"pl": "Travel and work", "category": "general", "category_pl": "General English"}
    sysp = QC.system_prompt(topic, "B1", "natural")
    out = {}
    for name, note in (("prompt_only", ""), ("prompt+note", "\n\n" + INTENT.NO_CORRECT_NOTE)):
        rows = []
        for rep in range(repeat):
            for k in range(0, len(cases), per):
                hist = [Message("system", sysp), Message("assistant", "What have you been up to recently?")]
                for c in cases[k:k + per]:
                    st = stream_stats(p, [*hist, Message("user", c["text"] + note)], max_tokens=100, temperature=0.7)
                    hist += [Message("user", c["text"]), Message("assistant", st["text"])]
                    rows.append({"id": c["id"], "kind": c["kind"], "rep": rep, "reply": st["text"],
                                 "self_correction": bool(SELF_CORR.search(st["text"])),
                                 "quotes": bool(re.search(r"[\"“]", st["text"])), "question": "?" in st["text"],
                                 "first_sentence_s": st["first_sentence_s"]})
        f = sorted(r["first_sentence_s"] or 0 for r in rows)
        out[name] = {"n": len(rows), "self_corrections": sum(r["self_correction"] for r in rows),
                     "quoted_language_comments": sum(r["quotes"] for r in rows),
                     "questions": sum(r["question"] for r in rows), "first_sentence_p50": round(f[len(f) // 2], 2),
                     "first_sentence_p95": round(f[int(len(f) * 0.95) - 1], 2), "rows": rows}
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("part", choices=["policy", "chat", "multi"])
    ap.add_argument("--split", default="dev", choices=["dev", "held", "all"])
    ap.add_argument("--repeat", type=int, default=2)
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    cases = load(a.split)
    r = run_policy(cases) if a.part == "policy" else run_chat(cases, a.repeat) if a.part == "chat" else \
        run_chat_multi(cases, repeat=a.repeat)
    summary = {k: v for k, v in r.items() if k != "rows"} if a.part == "policy" else \
        {k: {x: y for x, y in v.items() if x != "rows"} for k, v in r.items()}
    print(json.dumps(summary, ensure_ascii=False))
    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
