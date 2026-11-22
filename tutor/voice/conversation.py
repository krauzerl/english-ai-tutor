"""Potok jednej tury: LLM (stream) -> zdania -> TTS -> głośnik, z anulowaniem i pomiarami."""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass, field

from tutor.llm.base import CancelToken, LLMError
from tutor.llm.context import build_context, make_checkpoint, needs_checkpoint
from tutor.voice.text import SentenceSplitter, clean_for_speech

SYSTEM_PROMPT = (
    "You are a warm, patient English conversation partner talking with a Polish adult learner. "
    "Your words are spoken aloud, so: reply in 1-2 short sentences (under 35 words), natural spoken English "
    "with contractions, no lists, no markdown, no emoji, no stage directions. "
    "First react to what the student actually said, then ask ONE short follow-up question. "
    "If a mistake would confuse a listener, model the correct phrasing naturally in your reply; "
    "otherwise ignore small slips. You only get a text transcript, so never comment on pronunciation. "
    "Always answer in English; if the student is stuck and asks in Polish, help in very simple English."
)
SPEAK_TAIL_S = 0.4  # ogon echa po mowie, zanim mikrofon znów słucha


@dataclass
class TurnResult:
    user: str
    reply: str = ""  # tekst faktycznie wypowiedziany (wysłany do głośnika)
    cancelled: bool = False
    error: str | None = None
    sentences: int = 0
    m: dict = field(default_factory=dict)  # pomiary w sekundach od t_end


class VoiceTutor:
    def __init__(self, repo, profile_id, session_id, llm, tts, sink, *, system=SYSTEM_PROMPT,
                 context_window=8192, max_tokens=100, temperature=0.7, clock=time.monotonic, echo=None):
        self.repo, self.pid, self.sid, self.llm, self.tts, self.sink = repo, profile_id, session_id, llm, tts, sink
        self.system, self.window, self.max_tokens, self.temp = system, context_window, max_tokens, temperature
        self.clock, self.echo = clock, echo or (lambda s: None)
        self._tok: CancelToken | None = None

    def cancel(self) -> None:
        """Zatrzymuje generowanie, syntezę i odtwarzanie (wątkowo bezpieczne)."""
        if self._tok:
            self._tok.set()

    def respond(self, user_text: str, t_end: float | None = None) -> TurnResult:
        user_text = user_text.strip()
        t_end = self.clock() if t_end is None else t_end
        res = TurnResult(user_text)
        ctx = build_context(self.repo, self.pid, self.sid, self.system, user_text,
                            context_window=self.window, reserve_out=self.max_tokens)
        self.repo.add_turn(self.pid, self.sid, "user", user_text)
        tok = self._tok = CancelToken()
        tok.on_cancel(self.sink.stop)
        sents: queue.Queue = queue.Queue()
        spoken: list[str] = []
        m = res.m

        def rel() -> float:
            return round(self.clock() - t_end, 3)

        def speaker() -> None:
            started = False
            while (s := sents.get()) is not None:
                if tok.is_set():
                    continue  # opróżnij kolejkę
                try:
                    audio = self.tts.synth(s)
                except Exception as e:  # noqa: BLE001 - błąd silnika TTS nie może zawiesić rozmowy
                    res.error = f"TTS: {type(e).__name__}"
                    tok.set()
                    continue
                if tok.is_set():
                    continue
                m.setdefault("tts_first_done", rel())
                if not started:
                    self.sink.start(self.tts.sample_rate)
                    started = True
                self.sink.write(audio)
                spoken.append(s)
                m.setdefault("first_audio", rel())

        th = threading.Thread(target=speaker, daemon=True)
        th.start()
        sp = SentenceSplitter()

        def emit(parts: list[str]) -> None:
            for p in parts:
                if (c := clean_for_speech(p)):
                    m.setdefault("first_sentence", rel())
                    res.sentences += 1
                    self.echo(c)
                    sents.put(c)

        try:
            stream = self.llm.stream(ctx.messages, temperature=self.temp, max_tokens=self.max_tokens, cancel=tok)
            for chunk in stream:
                m.setdefault("llm_first_token", rel())
                emit(sp.feed(chunk))
            if not tok.is_set():
                emit(sp.flush())
            if stream.usage:
                m["in_tokens"], m["out_tokens"] = stream.usage.in_tokens, stream.usage.out_tokens
        except LLMError as e:
            res.error = e.user_message  # już zakolejkowane zdania zostaną dokończone
        finally:
            sents.put(None)
            th.join()
        self.sink.seal()
        if not tok.is_set():
            self.sink.drain(tok)
        m["llm_done"] = rel()
        res.cancelled = tok.is_set() and res.error is None
        res.reply = " ".join(spoken)
        m["underrun_s"] = round(self.sink.underrun_s, 3)
        m["n_gaps"] = len(getattr(self.sink, "gaps", []))
        if res.reply:
            self.repo.add_turn(self.pid, self.sid, "assistant", res.reply)
        self._maybe_checkpoint()
        self._tok = None
        return res

    def _maybe_checkpoint(self) -> None:
        """Bez wywołania LLM (opóźnienie): ekstrakcyjne streszczenie ostatnich tur (≤300 tok)."""
        if needs_checkpoint(self.repo, self.pid, self.sid):
            def summarize(prev, turns):
                body = " | ".join(f"{'S' if t['role'] == 'user' else 'T'}: {t['text'][:90]}" for t in turns[-6:])
                return ((prev + " … ") if prev else "") + body
            make_checkpoint(self.repo, self.pid, self.sid, summarize)
