"""python main.py --voice: rozmowa głosowa z tutorem (prototyp, bez silnika dydaktycznego)."""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time

from tutor import config
from tutor.llm import build_provider, context_window
from tutor.store.db import open_db
from tutor.store.repo import Repo
from tutor.voice import audio as A
from tutor.voice.conversation import SPEAK_TAIL_S, VoiceTutor

HELP = ("[Enter] nagrywaj/zatrzymaj nagrywanie · [Enter] w trakcie mowy tutora = przerwij · "
        "wpisz tekst + Enter = wyślij tekstowo · q = wyjście")


def parse(argv: list[str]) -> argparse.Namespace:
    v = config.raw_config().get("voice", {})
    ap = argparse.ArgumentParser(prog="main.py --voice")
    ap.add_argument("--voice", action="store_true")
    ap.add_argument("--mode", choices=["ptt", "auto"], default=v.get("mode", "ptt"),
                    help="ptt = ręczne nagrywanie (Enter); auto = bez przycisku (eksperymentalny)")
    ap.add_argument("--tts", choices=["kokoro", "piper"], default=v.get("tts", "kokoro"))
    ap.add_argument("--tts-voice", default=v.get("tts_voice"), help="np. bf_emma (kokoro), en_GB-alba-medium (piper)")
    ap.add_argument("--speed", type=float, default=v.get("speed", 1.0))
    ap.add_argument("--stt-model", default=v.get("stt_model", "small.en"))
    ap.add_argument("--language", default=v.get("language", "en"))
    ap.add_argument("--input-device", default=v.get("input_device"))
    ap.add_argument("--output-device", default=v.get("output_device"))
    ap.add_argument("--profile", help="nazwa lub id profilu (domyślnie ostatnio wybrany)")
    ap.add_argument("--no-audio", action="store_true", help="bez mikrofonu i głośnika (tekst -> tekst)")
    ap.add_argument("--list-devices", action="store_true")
    return ap.parse_args(argv)


def _lines() -> queue.Queue:
    q: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [q.put(ln.strip()) for ln in sys.stdin] and q.put(None), daemon=True).start()
    return q


def run(argv: list[str], *, stt=None, tts=None, sink=None, mic=None, llm=None, lines=None,
        out=print, db=None, eval_llm=None) -> int:
    a = parse(argv)
    if a.list_devices:
        try:
            print("\n".join(A.device_names()))
        except A.AudioUnavailable as e:
            print(e, file=sys.stderr)
            return 1
        return 0
    conn = db or open_db(config.db_path())
    repo = Repo(conn)
    p = repo.find_profile(a.profile) if a.profile else (repo.get_profile(config.get_last_profile() or -1))
    if p is None:
        print("Brak profilu. Utwórz: python main.py profile create NAZWA", file=sys.stderr)
        return 1
    build_eval = llm is None and eval_llm is None     # produkcja: modele z config.toml; wstrzyknięte `llm` = bez oceny
    if llm is None:
        llm = build_provider("conversation")
    if llm.external:
        print("Rozmowa głosowa używa tylko modeli lokalnych (Gemini odroczony).", file=sys.stderr)
        return 1
    if not llm.health():
        print("Ollama nie odpowiada: uruchom `ollama serve`.", file=sys.stderr)
        return 1
    cw = context_window(llm.model)

    text_only = a.no_audio
    if not text_only and mic is None:
        try:
            mic = A.Mic(a.input_device)
            mic.open()
        except A.AudioUnavailable as e:
            out(f"[brak mikrofonu: {e}] Tryb tekstowy: wpisuj wypowiedzi, tutor odpowie głosem.")
            mic = None
    if sink is None:
        sink = A.SimSink() if a.no_audio else A.Speaker(a.output_device)
    if stt is None and mic is not None:
        from tutor.voice.stt import WhisperSTT
        stt = WhisperSTT(a.stt_model, a.language)
    if tts is None:
        from tutor.voice.tts import build_tts
        tts = build_tts(a.tts, a.tts_voice, a.speed)

    cur = repo.find_open_session(p["id"])
    if cur and cur["kind"] == "voice":                 # niezakończona sesja (Ctrl+C / awaria): wznów, bez duplikatów
        sid = cur["id"]
        repo.resume_session(p["id"], sid)
        out(f"Wznawiam sesję #{sid}.")
    else:
        sid = repo.start_session(p["id"], "voice")
    svc = _eval_service(repo, conn, p, sid, eval_llm, build_eval, out)
    tutor = VoiceTutor(repo, p["id"], sid, llm, tts, sink, context_window=cw, echo=lambda s: out(f"Tutor: {s}"),
                       record_user_turn=svc.user_turn if svc else None)
    q = lines or _lines()
    out(f"Profil: {p['name']} · LLM: {llm.model} · TTS: {tts.name}/{tts.voice} · tryb: {a.mode if mic else 'tekst'}")
    out(HELP)
    ep = A.Endpointer()
    clean = False
    try:
        while True:
            text, t_end, mode, low = _listen(a, q, mic, stt, ep, out)
            if text is None:
                break
            if not text:
                continue
            out(f"You: {text}")
            speaking = threading.Event()
            watcher = threading.Thread(target=_cancel_on_enter, args=(q, tutor, speaking), daemon=True)
            speaking.set()
            watcher.start()
            if mic:
                mic.mute(3600)  # half-duplex: nie transkrybuj własnego głosu tutora
            try:
                r = tutor.respond(text, t_end, input_mode=mode, low_probs=low)
            except Exception as e:  # noqa: BLE001 - błąd odpowiedzi nie kończy rozmowy ani nie blokuje oceny
                out(f"[błąd tutora: {e}]")
                r = None
            finally:
                if svc:
                    svc.tutor_done()
            speaking.clear()
            watcher.join(timeout=0.3)
            if mic:
                mic.mute(SPEAK_TAIL_S)
            if r is None:
                continue
            if r.error:
                out(f"[{r.error}]")
            m = r.m
            out(f"  ({'przerwano · ' if r.cancelled else ''}start mowy {m.get('first_audio', '-')} s, "
                f"1. token {m.get('llm_first_token', '-')} s)")
        clean = True
    except KeyboardInterrupt:
        pass
    finally:
        if svc:
            svc.close()
            _report(svc, out)
        if clean:
            repo.end_session(p["id"], sid)
        else:
            repo.pause_session(p["id"], sid)           # Ctrl+C / wyjątek: sesję można wznowić
        if mic:
            mic.close()
        if hasattr(sink, "close"):
            sink.close()
        if db is None:
            conn.close()
    return 0


def _eval_service(repo, conn, p, sid, eval_llm, build_eval, out):
    """SessionService z kolejką oceny na modelu `evaluation`; None = tury tylko zapisujemy (ocena po wznowieniu)."""
    if build_eval:
        eval_llm = build_provider("evaluation")
    if eval_llm is None:
        return None
    if eval_llm.external or not eval_llm.health():
        out("[ocena wyłączona: model oceny niedostępny lokalnie; wypowiedzi zostaną ocenione później]")
        return None
    from tutor.app.eval_runner import make_queue
    from tutor.app.session_service import SessionService
    from tutor.llm.structured import structured
    from tutor.pedagogy import content as C
    pack = C.load(p["target_lang"])
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    svc = SessionService(
        repo, lambda: Repo(open_db(path)),
        lambda wrepo: make_queue(wrepo, pack, eval_llm, structured, profile_id=p["id"], session_id=sid, goals={}),
        p["id"], sid)
    n = svc.start()
    if n:
        out(f"[do oceny z poprzedniej sesji: {n}]")
    return svc


def _report(svc, out) -> None:
    """Błędy i zaległości oceny są widoczne (nie udajemy sukcesu)."""
    if svc.last_error:
        out(f"[ocena: błąd zapisu: {svc.last_error}]")
    if svc.dropped:
        out(f"[ocena: porzucono {len(svc.dropped)} wypowiedzi po powtórzonych błędach modelu]")
    if svc.pending:
        out(f"[ocena: {svc.pending} wypowiedzi oczekuje na ocenę — zostaną ocenione po wznowieniu]")


def _cancel_on_enter(q, tutor, speaking: threading.Event) -> None:
    """Pusta linia (Enter) na początku kolejki = przerwij; niepuste linie zostają na swoim miejscu."""
    while speaking.is_set():
        with q.mutex:
            if q.queue and q.queue[0] == "":
                q.queue.popleft()
                tutor.cancel()
        time.sleep(0.05)


def _listen(a, q, mic, stt, ep, out) -> tuple[str | None, float, str, list[str] | None]:
    def typed(ln):
        return (None, 0.0, "text", None) if ln in (None, "q", "quit") else (ln, time.monotonic(), "text", None)

    if mic is None:
        out("> ")
        ln = q.get()
        return typed(ln) if ln != "" else ("", 0.0, "text", None)
    if a.mode == "ptt":
        ln = q.get()
        if ln != "":
            return typed(ln)
        out("● nagrywam… (Enter = stop)")
        stop = threading.Event()
        res: list = []
        th = threading.Thread(target=lambda: res.append(A.record_manual(mic, stop)), daemon=True)
        mic.mute(0)
        th.start()
        ln = q.get()
        stop.set()
        th.join()
        audio = res[0]
        if ln in ("q", "quit"):
            return None, 0.0, "text", None
    else:
        out("(słucham… mów; q = wyjście)")
        pending: list = []

        def poll():
            try:
                ln = q.get_nowait()
            except queue.Empty:
                return False
            pending.append(ln)
            return True
        audio = A.listen_auto(mic, ep, poll=poll)
        if audio is None:
            ln = pending[0] if pending else None
            return typed(ln) if ln != "" else ("", 0.0, "text", None)
    t_end = time.monotonic()
    t0 = time.monotonic()
    text, low = "", None
    if len(audio):
        try:                                   # błąd STT nie kończy rozmowy: tura nie powstaje
            if hasattr(stt, "transcribe_detailed"):
                tr = stt.transcribe_detailed(audio)
                text, low = tr.text, tr.low_probs
            else:
                text = stt.transcribe(audio)
        except Exception as e:  # noqa: BLE001
            out(f"[błąd rozpoznawania mowy: {e}]")
    out(f"  (STT {time.monotonic() - t0:.2f} s, {len(audio) / A.MIC_SR:.1f} s nagrania)")
    if not text:
        out("(nic nie zrozumiałem — spróbuj jeszcze raz)")
    return text, t_end, "voice", low
