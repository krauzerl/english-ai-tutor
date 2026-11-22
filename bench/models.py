"""F4.7: porównanie lokalnych modeli (sekwencyjnie, jeden model na GPU, checkpointy). Wyniki poza Git.

  python -m bench.models --model qwen3:8b --no-think [--subset elim|full] [--tasks grammar,conv,pl,it,voice]
  python -m bench.models --summary

Checkpointy: `<data_dir>/bench/f4_7/<model>/` — ukończone zadanie (plik JSON) nie jest powtarzane; odpowiedzi
modelu w ocenie gramatyki trafiają do `chat_cache.jsonl` (wznowienie bez ponownych wywołań).
Miary jakości tekstu są automatyczne (LanguageTool, heurystyki) i WSTĘPNE; teksty zapisane do odsłuchu/recenzji.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import statistics as st
import sys
import tempfile
import time
from pathlib import Path

import requests

from bench import grammar as G
from tutor.app import languagetool as LT
from tutor.config import data_dir
from tutor.llm.base import Message, Reply, Usage
from tutor.llm.ollama import OllamaProvider
from tutor.pedagogy import content as C

OUT = data_dir() / "bench" / "f4_7"
ELIM = {"E1": 12, "E2": 5, "C1": 8, "C2": 6, "C3": 4, "S": 3, "D": 2}     # 40 przypadków, stałe (pierwsze wg id)
CONV = ["Yesterday I go to the cinema with my friend.", "I work as a software developer in a big company.",
        "In the weekend I usually play football with my brother.", "I forget words very quickly after the lesson.",
        "Next month I will have a job interview in English.", "What do you think is the best way to learn new words?"]
PL = [("Yesterday I go to the cinema.", "Yesterday I went to the cinema."),
      ("She have two cats.", "She has two cats."),
      ("I am living here since 2019.", "I have been living here since 2019."),
      ("I want to make a photo.", "I want to take a photo.")]
PL_SYS = ("Jesteś nauczycielem angielskiego dla dorosłego Polaka. Wyjaśnij po polsku, w 2-3 krótkich zdaniach, "
          "dlaczego zdanie ucznia jest błędne i jak powiedzieć poprawnie. Bez list i bez markdownu.")
IT = [("Io ho andato al cinema ieri.", True, "sono andat"), ("La problema è molto difficile.", True, "il problema"),
      ("Ieri sono andata al mare con mia sorella.", False, None), ("Domani vado a Roma con mio padre.", False, None)]
IT_SCHEMA = {"type": "object", "properties": {"error": {"type": "boolean"}, "fix": {"type": "string"}},
             "required": ["error", "fix"]}
IT_SYS = ("You check Italian sentences written by a learner. Reply JSON only: {\"error\": true|false, \"fix\": "
          "\"corrected sentence or empty\"}. Correct sentences must get error=false.")
IT_CONV = "Ciao! Mi chiamo Anna e studio l'italiano. Che cosa mi consigli di visitare a Firenze?"
IT_CONV_SYS = "Sei un tutor di conversazione italiana. Rispondi in italiano, 1-2 frasi brevi, poi fai una domanda."


def slug(model: str) -> str:
    return re.sub(r"[^\w.-]+", "_", model)


class DiskCache(G.CachingProvider):
    """`CachingProvider` z trwałym checkpointem; zapisuje też czas i liczbę tokenów każdego wywołania."""

    def __init__(self, inner, path: Path):
        super().__init__(inner)
        self.path, self.rec, self.used = path, {}, set()      # used: klucze tego przebiegu (miary czasu)
        if path.exists():
            for ln in path.read_text().splitlines():
                d = json.loads(ln)
                self.rec[d["k"]] = d
                self.cache[d["k"]] = Reply(d["text"], Usage(d["in"], d["out"], latency_ms=d["ms"]), "ollama",
                                           inner.model)

    def chat(self, messages, **kw):
        key = json.dumps([getattr(m, "content", str(m)) for m in messages] + [kw.get("max_tokens")])
        k = hashlib.sha256(key.encode()).hexdigest()
        self.used.add(k)
        if k not in self.cache:
            r = self.inner.chat(messages, **kw)
            self.cache[k] = r
            self.rec[k] = {"k": k, "text": r.text, "in": r.usage.in_tokens, "out": r.usage.out_tokens,
                           "ms": r.usage.latency_ms}
            with self.path.open("a") as f:
                f.write(json.dumps(self.rec[k], ensure_ascii=False) + "\n")
        return self.cache[k]


def unload_all(url: str) -> None:
    """Jeden duży model na GPU: zwalnia wszystkie załadowane przed startem kolejnego."""
    for m in requests.get(f"{url}/api/ps", timeout=5).json().get("models", []):
        requests.post(f"{url}/api/generate", json={"model": m["name"], "keep_alive": 0}, timeout=60)


def ps(url: str) -> list[dict]:
    return [{"name": m["name"], "size_mib": m.get("size", 0) // 2**20, "vram_mib": m.get("size_vram", 0) // 2**20}
            for m in requests.get(f"{url}/api/ps", timeout=5).json().get("models", [])]


def stream_stats(p: OllamaProvider, messages: list[Message], max_tokens=100, temperature=0.7) -> dict:
    """TTFT, czas pierwszego zdania i tok/s z jednego strumienia (statystyki Ollamy z ostatniej linii)."""
    body = p._body(messages, temperature, max_tokens, True)
    t0 = time.perf_counter()
    text, first, sent, d = "", None, None, {}
    with requests.post(f"{p.url}/api/chat", json=body, stream=True, timeout=p.timeout) as r:
        for ln in r.iter_lines():
            if not ln:
                continue
            d = json.loads(ln)
            c = d.get("message", {}).get("content", "")
            if c and first is None:
                first = time.perf_counter() - t0
            text += c
            if sent is None and re.search(r"[.!?](\s|$)", text):
                sent = time.perf_counter() - t0
            if d.get("done"):
                break
    ev = d.get("eval_count", 0)
    return {"text": text, "ttft_s": first, "first_sentence_s": sent, "out_tokens": ev,
            "tok_s": ev / (d["eval_duration"] / 1e9) if d.get("eval_duration") else None,
            "prompt_tokens": d.get("prompt_eval_count"), "wall_s": time.perf_counter() - t0}


def lt_issues(text: str, lang: str, cfg: dict) -> int | None:
    ms = LT.check(text, {**cfg, "language": lang})
    if ms is None:
        return None
    return sum(1 for m in ms if m.issue_type.lower() not in ("style", "whitespace", "typographical"))


def words(text: str) -> int:
    return len(re.findall(r"\w+", text))


def polish_ratio(text: str) -> float:
    w = re.findall(r"\w+", text.lower())
    pl = {"jest", "nie", "się", "w", "z", "i", "to", "czasu", "czas", "zdanie", "poprawnie", "należy", "bo", "ponieważ",
          "używamy", "mówimy", "dlatego", "że", "przeszłego", "czasownik", "trzeba"}
    return (sum(t in pl for t in w) + len(re.findall(r"[ąćęłńóśźż]", text.lower()))) / max(len(w), 1)


def task_grammar(p, pack, cases, d: Path, lt_fn):
    from tutor.llm.structured import structured
    prov = DiskCache(p, d / "chat_cache.jsonl")
    systems = ["A", "C"] if lt_fn else ["A"]
    res, meta = G.run_all(systems, cases, pack, provider=prov, structured=structured, lt_fn=lt_fn,
                          reviewed=G.load_cases())
    recs = [prov.rec[k] for k in prov.used]
    lat = [r["ms"] / 1000 for r in recs]
    from tutor.pedagogy.schemas import TurnEval
    valid = 0
    for r in recs:
        try:
            TurnEval.model_validate_json(r["text"])
            valid += 1
        except ValueError:
            pass
    out = {"n_cases": len(cases), "systems": {k: v["score"] for k, v in res.items()},
           "unrated": {k: sum(not r.rated for r in v["runs"]) for k, v in res.items()},
           "json_valid_rate": valid / max(len(recs), 1), "n_calls": len(recs),
           "eval_p50_s": G.pct(lat, 0.5), "eval_p95_s": G.pct(lat, 0.95),
           "r1_agree": sum(o.source == "bielik+lt" for r in res.get("C", {}).get("runs", []) for o in r.reports),
           "fix_agree": sum((o.source or "").startswith("bielik+lt") for r in res.get("C", {}).get("runs", [])
                            for o in r.reports + r.suggestions),
           "conflicts": sum("conflict" in (o.source or "") for r in res.get("C", {}).get("runs", [])
                            for o in r.reports + r.suggestions)}
    return out


def task_conv(p, cfg):
    from tutor.voice.conversation import SYSTEM_PROMPT
    rows = [stream_stats(p, [Message("system", SYSTEM_PROMPT), Message("user", u)]) for u in CONV]
    for r in rows:
        r["lt_issues"] = lt_issues(r["text"], "en-GB", cfg)
        r["words"] = words(r["text"])
    return {"rows": rows, "ttft_p50_s": st.median(r["ttft_s"] for r in rows),
            "first_sentence_p50_s": st.median(r["first_sentence_s"] or r["wall_s"] for r in rows),
            "tok_s_p50": st.median(r["tok_s"] for r in rows if r["tok_s"]),
            "words_p50": st.median(r["words"] for r in rows),
            "lt_issues_per_100w": _per100(rows)}


def _per100(rows):
    n = [r for r in rows if r.get("lt_issues") is not None]
    return 100 * sum(r["lt_issues"] for r in n) / max(sum(r["words"] for r in n), 1) if n else None


def task_pl(p, cfg):
    rows = []
    for bad, good in PL:
        r = p.chat([Message("system", PL_SYS), Message("user", f"Zdanie ucznia: \"{bad}\"\nPoprawnie: \"{good}\"")],
                   temperature=0.3, max_tokens=200)
        rows.append({"in": bad, "text": r.text, "words": words(r.text), "pl_ratio": polish_ratio(r.text),
                     "lt_issues": lt_issues(r.text, "pl-PL", cfg), "s": r.usage.latency_ms / 1000})
    return {"rows": rows, "lt_issues_per_100w": _per100(rows), "pl_ratio_min": min(r["pl_ratio"] for r in rows)}


def task_it(p, cfg):
    rows, ok = [], 0
    for s, err, exp in IT:
        r = p.chat([Message("system", IT_SYS), Message("user", s)], temperature=0.0, max_tokens=120, schema=IT_SCHEMA)
        try:
            j = json.loads(r.text)
            good = bool(j.get("error")) == err and (not err or (exp or "").lower() in str(j.get("fix", "")).lower())
        except ValueError:
            j, good = None, False
        ok += good
        rows.append({"in": s, "out": r.text, "ok": good})
    conv = p.chat([Message("system", IT_CONV_SYS), Message("user", IT_CONV)], temperature=0.7, max_tokens=100).text
    return {"rows": rows, "correct": ok, "n": len(IT), "conv": conv, "conv_lt_issues": lt_issues(conv, "it", cfg),
            "conv_words": words(conv)}


def task_voice(p):
    """Start odpowiedzi głosowej: prawdziwy `VoiceTutor` + Kokoro (CPU) + zegar odtwarzania bez dźwięku.
    STT (Whisper small.en, CPU) nie zależy od modelu LLM — mierzony osobno w `tests/live/bench_voice.py`."""
    from tutor.store.db import open_db
    from tutor.store.repo import Repo
    from tutor.voice.audio import SimSink
    from tutor.voice.conversation import VoiceTutor
    from tutor.voice.tts import build_tts
    tts = build_tts("kokoro")
    tts.synth("Warm up.")
    repo = Repo(open_db(Path(tempfile.mkdtemp()) / "b.db"))
    pid = repo.create_profile("bench")
    sid = repo.start_session(pid, "voice")
    vt = VoiceTutor(repo, pid, sid, p, tts, SimSink(), context_window=p.num_ctx)
    ms = [vt.respond(u).m for u in CONV[:4]]
    fa = [m["first_audio"] for m in ms if "first_audio" in m]
    return {"rows": ms, "first_audio_p50_s": st.median(fa) if fa else None, "first_audio_max_s": max(fa, default=None)}


def run(model: str, *, think: bool | None, subset: str, tasks: list[str], num_ctx: int) -> dict:
    d = OUT / slug(model) / f"ctx{num_ctx}"
    d.mkdir(parents=True, exist_ok=True)
    p = OllamaProvider(model, num_ctx=num_ctx, timeout=180, think=think)
    unload_all(p.url)
    p.chat([Message("user", "Say hi.")], max_tokens=5, temperature=0.0)     # rozgrzewka (ładowanie)
    (d / "ps.json").write_text(json.dumps({"ps": ps(p.url), "vram_mib": G.vram_mib(),
                                           "ollama_rss_mib": max((G.rss_mib(x) or 0 for x in G._pids("ollama")),
                                                                 default=None)}))
    pack = C.load("en")
    cfg = {**LT.settings(), "enabled": True, "timeout": 10}     # pierwsze żądanie PL/IT ładuje model języka
    lt_ok = LT.check("ping", cfg) is not None
    lt_fn = (lambda t: LT.check(t, cfg, disabled_categories=pack.lt_map.ignore_categories)) if lt_ok else None
    for t in tasks:
        f = d / (f"grammar_{subset}.json" if t == "grammar" else f"{t}.json")
        if f.exists():
            print(f"[skip] {model} {t} (checkpoint)", flush=True)
            continue
        t0 = time.perf_counter()
        if t == "grammar":
            cases = G.load_cases()
            if subset == "elim":
                cases = [c for s, n in ELIM.items() for c in sorted((c for c in cases if c.set == s),
                                                                    key=lambda c: c.id)[:n]]
            r = task_grammar(p, pack, cases, d, lt_fn)
        else:
            r = {"conv": lambda: task_conv(p, cfg), "pl": lambda: task_pl(p, cfg), "it": lambda: task_it(p, cfg),
                 "voice": lambda: task_voice(p)}[t]()
        r["wall_s"] = time.perf_counter() - t0
        f.write_text(json.dumps(r, indent=1, ensure_ascii=False, default=str))
        print(f"[done] {model} {t} {r['wall_s']:.0f}s", flush=True)
    return {"dir": str(d)}


def summary() -> str:
    def g(o, *ks):
        for k in ks:
            o = (o or {}).get(k) if isinstance(o, dict) else None
        return o

    def f(x, n=2):
        return "–" if x is None else (f"{x:.{n}f}" if isinstance(x, float) else str(x))
    rows = []
    for md in sorted(OUT.glob("*/ctx*")):
        r = {p.stem: json.loads(p.read_text()) for p in md.glob("*.json")}
        ge = r.get("grammar_elim", {})
        a, c = g(ge, "systems", "A"), g(ge, "systems", "C")
        rows.append([md.parent.name, md.name, f(g(a, "precision")), f(g(a, "recall")), f(g(a, "fpr_c123")),
                     f(g(a, "correction_accuracy")), f(g(c, "precision")), f(ge.get("fix_agree")),
                     f(ge.get("json_valid_rate")),
                     f(ge.get("eval_p95_s"), 1), f(g(r, "conv", "ttft_p50_s")), f(g(r, "conv", "tok_s_p50"), 1),
                     f(g(r, "conv", "lt_issues_per_100w"), 1), f(g(r, "pl", "lt_issues_per_100w"), 1),
                     f(g(r, "pl", "pl_ratio_min")), f(g(r, "it", "correct")), f(g(r, "voice", "first_audio_p50_s")),
                     f(g(r, "ps", "vram_mib"), 0), f(g(r, "ps", "ollama_rss_mib"), 0)])
    hdr = ["model", "ctx", "P(A)", "R(A)", "FPR(A)", "korekta(A)", "P(C)", "zgodne B+LT", "JSON", "ocena p95 s",
           "TTFT s", "tok/s", "LT EN/100w", "LT PL/100w", "PL ratio", "IT ok/4", "głos start s", "VRAM MiB", "RSS MiB"]
    lines = ["| " + " | ".join(hdr) + " |", "|" + "---|" * len(hdr)] + ["| " + " | ".join(x) + " |" for x in rows]
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="bench.models")
    ap.add_argument("--model")
    ap.add_argument("--no-think", action="store_true")
    ap.add_argument("--subset", default="elim", choices=["elim", "full"])
    ap.add_argument("--tasks", default="grammar,conv,pl,it,voice")
    ap.add_argument("--num-ctx", type=int, default=2048)
    ap.add_argument("--summary", action="store_true")
    a = ap.parse_args(argv)
    if a.summary:
        print(summary())
        return 0
    print(run(a.model, think=False if a.no_think else None, subset=a.subset, tasks=a.tasks.split(","),
              num_ctx=a.num_ctx))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
