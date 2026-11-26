"""Potok jednej tury: LLM (stream) -> zdania -> TTS -> głośnik, z anulowaniem i pomiarami."""
from __future__ import annotations

import queue
import re
import threading
import time
from dataclasses import dataclass, field

from tutor.app import intent as INTENT
from tutor.llm.base import CancelToken, LLMError
from tutor.llm.context import build_context, make_checkpoint, needs_checkpoint
from tutor.voice.guard import Guard
from tutor.voice.text import SentenceSplitter, clean_for_speech

NO_FAKE = ("You are an AI tutor: never invent personal experiences, memories, family, travels, likes or a body; you "
           "may give a view phrased as an opinion (I think...) or share general knowledge. ")
SYSTEM_PROMPT = (
    "You are a warm, patient English conversation partner talking with a Polish adult learner. "
    "Your words are spoken aloud, so: reply in 1-3 short sentences (under 40 words), natural spoken English "
    "with contractions, no lists, no markdown, no emoji, no stage directions. "
    "First react to what the student actually said. "
    "React to the content: build on their idea, add a related fact or a different angle, or offer one useful "
    "word or phrase for what they were trying to say (with a short meaning). Ask a question only when it moves the "
    "conversation forward; it is fine to end some replies with a comment instead of a question. Vary how your "
    "replies start. Keep track of what the student told you earlier and refer back to it. "
    + NO_FAKE +
    "If a mistake would confuse a listener, model the correct phrasing naturally in your reply; "
    "otherwise ignore small slips. You only get a text transcript, so never comment on pronunciation. "
    "Always answer in English; if the student is stuck and asks in Polish, help in very simple English. "
    "Do not praise every answer: no stock phrases like \"You're doing great\" or \"Great job\"; comment on what the "
    "student said instead, and praise only something specific, rarely. "
    "Never repeat a question you already asked: if the student answered or said they don't know, react and move "
    "to something new."
)
FALLBACK = "Okay. Tell me more about that."
_OPEN_EXCL = re.compile(r"^\W*(?:that|it|this|what|how|wow|oh|sounds|so|really|nice|great)\b[^.?!]{0,45}!", re.I)


def style_note(prev: list[str]) -> str:
    """Deterministyczna notatka na jedną odpowiedź przeciw schematowi „wykrzyknik → pytanie” (audyt F7, Qwen3 8B
    ignorował samą instrukcję w prompcie). `prev` = poprzednie odpowiedzi tutora (najstarsze pierwsze)."""
    notes = []
    if len(prev) >= 2 and all("?" in r for r in prev[-2:]):
        notes.append("In this reply do NOT ask any question: respond with a comment, a related fact, or one useful "
                     "phrase the student could use, and stop.")
    if prev and _OPEN_EXCL.match(prev[-1]):
        notes.append("Do not open with an exclamation such as “That sounds…!” or “That's…!”; start directly with "
                     "something about the content.")
    return (" Style note for this reply: " + " ".join(notes)) if notes else ""
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
                 context_window=8192, max_tokens=100, temperature=0.7, clock=time.monotonic, echo=None,
                 record_user_turn=None, feedback=None):
        self.repo, self.pid, self.sid, self.llm, self.tts, self.sink = repo, profile_id, session_id, llm, tts, sink
        self.system, self.window, self.max_tokens, self.temp = system, context_window, max_tokens, temperature
        self.clock, self.echo = clock, echo or (lambda s: None)
        self.feedback = feedback          # () -> notatka dla tutora na jedną odpowiedź (recast) albo None
        self.record_user_turn = record_user_turn   # np. SessionService.user_turn: jedyna ścieżka zapisu tury ucznia
        self._tok: CancelToken | None = None
        self.last_error: str | None = None

    def _note(self, user_text: str = "") -> str:
        try:
            n = self.feedback(user_text) if self.feedback else None
        except Exception:  # noqa: BLE001 - informacja zwrotna nigdy nie psuje rozmowy
            n = None
        return f"\n\n{n}" if n else ""

    def say(self, text: str) -> bool:
        """Mówi gotowy tekst (bez LLM, bez zapisu tury). False = przerwano (cancel) lub błąd TTS (`self.last_error`)."""
        tok = self._tok = CancelToken()
        tok.on_cancel(self.sink.stop)
        self.last_error = None
        sp, started = SentenceSplitter(), False
        try:
            for s in [*sp.feed(text + " "), *sp.flush()]:
                if tok.is_set() or not (c := clean_for_speech(s)):
                    continue
                try:
                    audio = self.tts.synth(c)
                except Exception as e:  # noqa: BLE001 - błąd silnika TTS nie może zawiesić lekcji
                    self.last_error = f"TTS: {type(e).__name__}"
                    tok.set()
                    break
                if tok.is_set():
                    break
                if not started:
                    self.sink.start(self.tts.sample_rate)
                    started = True
                self.sink.write(audio)
            self.sink.seal()
            if not tok.is_set():
                self.sink.drain(tok)
            return not tok.is_set()
        finally:
            self._tok = None

    def cancel(self) -> None:
        """Zatrzymuje generowanie, syntezę i odtwarzanie (wątkowo bezpieczne)."""
        if self._tok:
            self._tok.set()

    def respond(self, user_text: str, t_end: float | None = None, *, input_mode: str = "voice",
                low_probs: list[str] | None = None) -> TurnResult:
        """`low_probs`: None = brak danych STT (tura głosowa nie będzie oceniana), [] = STT pewny wszystkich słów."""
        user_text = user_text.strip()
        t_end = self.clock() if t_end is None else t_end
        res = TurnResult(user_text)
        sig = INTENT.classify(user_text)                   # jasny sygnał ucznia → notatka na tę jedną odpowiedź
        guard = Guard([t["text"] for t in self.repo.list_turns(self.pid, self.sid)       # „nie rozumiem” ≠ „powtórz”
                       if t["role"] == "assistant"][-8:], repeats=not INTENT.wants_repeat(user_text))
        prev = [t["text"] for t in self.repo.list_turns(self.pid, self.sid) if t["role"] == "assistant"][-3:]
        system = self.system + self._note(user_text) + INTENT.NOTES.get(sig, "") + (
            "" if sig else style_note(prev))
        ctx = build_context(self.repo, self.pid, self.sid, system, user_text,
                            context_window=self.window, reserve_out=self.max_tokens)
        if self.record_user_turn:
            self.record_user_turn(user_text, input_mode=input_mode, low_probs=low_probs)
        else:
            self.repo.add_turn(self.pid, self.sid, "user", user_text, input_mode=input_mode, low_probs=low_probs)
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
                if (c := clean_for_speech(p)) and (c := guard(c)):
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
            if guard.dropped and not res.sentences and not tok.is_set():
                res.sentences += 1                         # wszystko było powtórką: krótka neutralna kontynuacja
                self.echo(FALLBACK)
                sents.put(FALLBACK)
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
