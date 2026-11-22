"""Benchmark rozmowy głosowej (live): STT -> Bielik (stream) -> TTS, ≥20 tur, zegar odtwarzania symulowany.

Uczeń = syntetyczny głos Piper (inny niż tutor) przepuszczony przez prawdziwy Endpointer i Whisper.
PYTHONPATH=. .venv/bin/python tests/live/bench_voice.py [--tts kokoro|piper] [--turns 22] [--json plik]
"""
import argparse
import json
import statistics as st
import subprocess
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

from tutor.llm import build_provider, context_window
from tutor.store.db import open_db
from tutor.store.repo import Repo
from tutor.voice import audio as A
from tutor.voice.conversation import VoiceTutor
from tutor.voice.stt import WhisperSTT
from tutor.voice.tts import PiperTTS, build_tts

LINES = [
    "Hello, my name is Jacek and I am learning English.", "I live in Poland, in a small city near Warsaw.",
    "Yesterday I go to the cinema with my friend.", "We watched a science fiction movie. It was very interesting.",
    "I work as a software developer in a big company.", "My job is difficult but I like it very much.",
    "In the weekend I usually play football with my brother.", "Sometimes I read books about history.",
    "I want to improve my speaking, because I have many meetings in English.",
    "What do you think is the best way to learn new words?", "I forget words very quickly after the lesson.",
    "Last summer I traveled to Italy for two weeks.", "The food was great, especially the pizza and the ice cream.",
    "I don't like when it is too hot, so I prefer spring.", "Can you give me some advice about listening practice?",
    "I try to watch series without subtitles, but it is hard.", "My favourite series is about a detective in London.",
    "Next month I will have a job interview in English.", "I am a little nervous about it.",
    "How can I sound more confident when I speak?", "I think I need to practice every day, even for ten minutes.",
    "Thank you, this was a very useful conversation.",
]


def sample(stop, out):
    def ollama_rss():
        t = 0
        for p in Path("/proc").glob("[0-9]*/status"):
            try:
                s = p.read_text()
            except OSError:
                continue
            if "Name:\tollama" in s:
                t += int(next(ln for ln in s.splitlines() if ln.startswith("VmRSS")).split()[1])
        return t // 1024

    def me():
        return int(next(ln for ln in Path("/proc/self/status").read_text().splitlines()
                        if ln.startswith("VmRSS")).split()[1]) // 1024
    while not stop.is_set():
        try:
            v = int(subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
                                   capture_output=True, text=True, timeout=3).stdout.strip())
        except (OSError, ValueError, subprocess.SubprocessError):
            v = 0
        out["vram_mib"] = max(out.get("vram_mib", 0), v)
        out["rss_app_mib"] = max(out.get("rss_app_mib", 0), me())
        out["rss_ollama_mib"] = max(out.get("rss_ollama_mib", 0), ollama_rss())
        stop.wait(1.0)


def student_audio(tts: PiperTTS, text: str) -> np.ndarray:
    a = tts.synth(text)
    x = np.interp(np.arange(0, len(a), tts.sample_rate / A.MIC_SR), np.arange(len(a)), a).astype(np.float32)
    return np.concatenate([np.zeros(A.MIC_SR // 2, np.float32), x * 0.5, np.zeros(A.MIC_SR, np.float32)])


def endpoint(audio: np.ndarray, ep: A.Endpointer) -> np.ndarray | None:
    """Przepuszcza audio blokami przez Endpointer jak mikrofon; zwraca wypowiedź lub None."""
    bl = [audio[i:i + A.BLOCK] for i in range(0, len(audio) - A.BLOCK + 1, A.BLOCK)]

    class M:
        def read(self, timeout=0.1):
            return bl.pop(0) if bl else None
    return A.listen_auto(M(), ep, poll=lambda: not bl)


def med(xs):
    return round(st.median(xs), 2) if xs else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tts", default="kokoro")
    ap.add_argument("--voice")
    ap.add_argument("--turns", type=int, default=22)
    ap.add_argument("--stt-threads", type=int, default=8)
    ap.add_argument("--stt-model", default="small.en")
    ap.add_argument("--json")
    a = ap.parse_args()

    llm = build_provider("conversation")
    assert not llm.external
    tts = build_tts(a.tts, a.voice)
    stt = WhisperSTT(a.stt_model, "en", cpu_threads=a.stt_threads)
    student = PiperTTS("en_US-lessac-medium")
    print("rozgrzewka...", flush=True)
    stt.transcribe(student_audio(student, "Warm up sentence."))
    tts.synth("Warm up.")
    from tutor.llm.base import Message
    llm.chat([Message("user", "Say hi.")], max_tokens=5)

    conn = open_db(Path(tempfile.mkdtemp()) / "bench.db")
    repo = Repo(conn)
    pid = repo.create_profile("bench")
    sid = repo.start_session(pid, "voice")
    sink = A.SimSink()
    tutor = VoiceTutor(repo, pid, sid, llm, tts, sink, context_window=context_window(llm.model))
    res: dict = {}
    stop = threading.Event()
    threading.Thread(target=sample, args=(stop, res), daemon=True).start()

    rows, ep = [], A.Endpointer()
    for i in range(a.turns):
        line = LINES[i % len(LINES)]
        utt = endpoint(student_audio(student, line), ep)
        assert utt is not None, "Endpointer nie wykrył końca wypowiedzi"
        t_end = time.monotonic()
        text = stt.transcribe(utt)
        stt_s = time.monotonic() - t_end
        r = tutor.respond(text, t_end)
        m = r.m
        rows.append({"turn": i + 1, "heard": text, "ref": line, "stt_s": round(stt_s, 2), "audio_s": round(len(utt) / A.MIC_SR, 1),
                     "reply": r.reply, "error": r.error, "sentences": r.sentences, **m})
        print(f"{i + 1:2d} stt={stt_s:.2f} tok1={m.get('llm_first_token')} sent1={m.get('first_sentence')} "
              f"audio={m.get('first_audio')} gaps={m.get('n_gaps')}/{m.get('underrun_s')}s | {r.reply[:70]}", flush=True)
    stop.set()
    fa = [r["first_audio"] for r in rows if "first_audio" in r]
    summary = {
        "tts": f"{tts.name}/{tts.voice}", "stt": a.stt_model, "llm": llm.model, "turns": len(rows),
        "median_first_audio_s": med(fa), "p90_first_audio_s": round(float(np.percentile(fa, 90)), 2),
        "max_first_audio_s": max(fa), "min_first_audio_s": min(fa),
        "median_stt_s": med([r["stt_s"] for r in rows]),
        "median_llm_first_token_from_end_s": med([r["llm_first_token"] for r in rows if "llm_first_token" in r]),
        "median_first_sentence_from_end_s": med([r["first_sentence"] for r in rows if "first_sentence" in r]),
        "median_llm_done_s": med([r["llm_done"] for r in rows]),
        "turns_with_gaps": sum(1 for r in rows if r.get("n_gaps")), "total_gap_s": round(sum(r.get("underrun_s", 0) for r in rows), 2),
        "errors": sum(1 for r in rows if r["error"]), "wer_proxy_exact": sum(
            1 for r in rows if r["heard"].lower().strip(" .!?") == r["ref"].lower().strip(" .!?")),
        "context_turns_in_db": len(repo.list_turns(pid, sid)), "checkpoints": len(repo.list_checkpoints(pid, sid)), **res,
    }
    print(json.dumps(summary, indent=1))
    if a.json:
        Path(a.json).write_text(json.dumps({"summary": summary, "turns": rows}, indent=1, ensure_ascii=False))


if __name__ == "__main__":
    main()
