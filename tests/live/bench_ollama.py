"""Pomiar live Ollamy: opóźnienia, tok/s, RAM, VRAM. Uruchom: .venv/bin/python tests/live/bench_ollama.py"""
import json
import subprocess
import sys
import time

import requests
from pydantic import BaseModel

from tutor.llm.base import CancelToken, Message
from tutor.llm.ollama import OllamaProvider
from tutor.llm.structured import structured

URL = "http://localhost:11434"


def vram_mib() -> int:
    out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                         capture_output=True, text=True).stdout
    return int(out.split()[0])


def ollama_rss_mib() -> int:
    out = subprocess.run(["ps", "-C", "ollama", "-o", "rss="], capture_output=True, text=True).stdout
    return sum(int(x) for x in out.split()) // 1024


def ps() -> dict:
    m = requests.get(f"{URL}/api/ps", timeout=5).json().get("models", [])
    return {x["name"]: {"size_mib": x["size"] // 2**20, "vram_mib": x["size_vram"] // 2**20} for x in m}


class Out(BaseModel):
    greeting: str


def bench(model: str) -> dict:
    p = OllamaProvider(model, timeout=600)
    res = {"model": model, "vram_before": vram_mib(), "rss_before": ollama_rss_mib()}
    msgs = [Message("system", "You are a concise English tutor."),
            Message("user", "Explain the difference between 'since' and 'for' in two sentences.")]
    t = time.monotonic()
    r = p.chat([Message("user", "Say hi.")], temperature=0, max_tokens=8)  # ładowanie modelu
    res["cold_first_request_s"] = round(time.monotonic() - t, 2)
    t = time.monotonic()
    r = p.chat(msgs, temperature=0, max_tokens=120)
    res["warm_chat_s"] = round(time.monotonic() - t, 2)
    res["warm_tokens"] = (r.usage.in_tokens, r.usage.out_tokens)
    t = time.monotonic()
    s = p.stream(msgs, temperature=0, max_tokens=120)
    first = None
    for _ in s:
        first = first or time.monotonic() - t
    tot = time.monotonic() - t
    res["stream_ttft_s"] = round(first, 2)
    res["stream_tok_per_s"] = round(s.usage.out_tokens / max(tot - first, 1e-6), 1)
    res["vram_loaded"], res["rss_loaded"], res["ollama_ps"] = vram_mib(), ollama_rss_mib(), ps()
    tok = CancelToken()
    t = time.monotonic()
    s = p.stream([Message("user", "Count from 1 to 200.")], temperature=0, max_tokens=400, cancel=tok)
    next(s)
    tok.set()
    list(s)
    res["cancel_latency_s"] = round(time.monotonic() - t, 2)
    res["cancelled"] = s.cancelled
    t = time.monotonic()
    g = structured(p, [Message("user", 'Return JSON {"greeting": "<short greeting>"}')], Out, max_tokens=60)
    res["structured_s"], res["structured_ok"] = round(time.monotonic() - t, 2), bool(g.greeting)
    return res


if __name__ == "__main__":
    models = [m["name"] for m in requests.get(f"{URL}/api/tags", timeout=5).json()["models"]]
    for m in models:
        requests.post(f"{URL}/api/generate", json={"model": m, "keep_alive": 0}, timeout=60)  # zwolnij
        time.sleep(2)
        try:
            print(json.dumps(bench(m), ensure_ascii=False))
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"model": m, "error": type(e).__name__}))
        sys.stdout.flush()
