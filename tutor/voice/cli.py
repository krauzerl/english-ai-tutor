"""python main.py --voice: rozmowa głosowa z tutorem (prototyp, bez silnika dydaktycznego)."""
from __future__ import annotations

import argparse
import queue
import sys
import threading
import time
from datetime import UTC, datetime

from tutor import config
from tutor.app import intent as INTENT
from tutor.app import topics as T
from tutor.llm import build_provider, context_window
from tutor.store.db import open_db
from tutor.store.repo import Repo
from tutor.voice import audio as A
from tutor.voice.conversation import SPEAK_TAIL_S, SYSTEM_PROMPT, VoiceTutor
from tutor.voice.text import clean_for_speech

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
    ap.add_argument("--speed", type=float, default=v.get("speed", 0.9))
    ap.add_argument("--stt-model", default=v.get("stt_model", "small.en"))
    ap.add_argument("--stt-confirm", choices=["uncertain", "always", "never"], default=None,
                    help="potwierdzanie rozpoznanej wypowiedzi przed oceną (domyślnie: tylko niepewne)")
    ap.add_argument("--language", default=v.get("language", "en"))
    ap.add_argument("--input-device", default=v.get("input_device"))
    ap.add_argument("--output-device", default=v.get("output_device"))
    ap.add_argument("--profile", help="nazwa lub id profilu (domyślnie ostatnio wybrany)")
    ap.add_argument("--lesson", nargs="?", const="default", metavar="SKILL",
                    help="lekcja (wyjaśnienie, ćwiczenia, rozmowa). Bez SKILL: tutor dobiera cel z danych ucznia "
                         "lub wznawia rozpoczętą lekcję")
    ap.add_argument("--correction", choices=["summary", "periodic", "intensive"], default=None,
                    help="styl korekt w tej sesji (domyślnie ze stylu profilu; summary = tylko podsumowanie na końcu)")
    ap.add_argument("--summary-wait", type=float, default=8.0, metavar="S",
                    help="na końcu rozmowy czekaj do S sekund na ocenę ostatnich wypowiedzi (podsumowanie korekt)")
    ap.add_argument("--placement", action="store_true",
                    help="wstępne dopasowanie poziomu (gramatyka, słownictwo; głosem lub tekstem), potem koniec")
    ap.add_argument("--review", action="store_true", help="powtórki zaległych umiejętności (FSRS), potem koniec")
    ap.add_argument("--progress", action="store_true", help="pokaż postęp z zapisanych dowodów i zakończ")
    ap.add_argument("--finish-evals", action="store_true",
                    help="dokończ oceny wypowiedzi czekających po zakończonych rozmowach, pokaż podsumowania")
    ap.add_argument("--chat", nargs="?", const="ask", metavar="TEMAT",
                    help="Quick Chat: swobodna rozmowa bez celu lekcji (bez TEMAT: wybierzesz z propozycji)")
    ap.add_argument("--minutes", type=int, default=None, help="limit czasu Quick Chat w minutach")
    ap.add_argument("--chat-level", choices=["auto", "A1", "A2", "B1", "B2", "C1"], default=None,
                    help="Quick Chat: poziom (domyślnie z profilu; auto = z diagnozy albo ostrożne A2)")
    ap.add_argument("--chat-category", choices=["general", "technical", "medical", "business", "professional",
                                                "custom"], default=None, help="Quick Chat: kategoria rozmowy")
    ap.add_argument("--chat-mode", choices=["natural", "guided", "roleplay"], default=None,
                    help="Quick Chat: naturalna rozmowa, rozmowa prowadzona albo roleplay")
    ap.add_argument("--weakspots", action="store_true", help="dziennik słabych stron i zakończ")
    ap.add_argument("--drill", metavar="CEL", help="ćwiczenia słabej strony: NUMER z --weakspots, kategoria lub skill")
    ap.add_argument("--achievements", action="store_true", help="osiągnięcia i zakończ")
    ap.add_argument("--exam", nargs="?", const="list", metavar="ŚCIEŻKA",
                    help="ścieżki egzaminacyjne: bez argumentu lista i gotowość; ŚCIEŻKA = sesja ćwiczeń")
    ap.add_argument("--history", action="store_true", help="historia nauki z zapisów i zakończ")
    ap.add_argument("--set", action="append", metavar="KLUCZ=WARTOŚĆ",
                    help="ustawienie profilu, np. speed=1.1 lub correction=periodic; `--set ?` pokazuje wszystkie")
    ap.add_argument("--no-placement", action="store_true", help=argparse.SUPPRESS)   # zgodność wsteczna (no-op)
    ap.add_argument("--no-audio", action="store_true", help="bez mikrofonu i głośnika (tekst -> tekst)")
    ap.add_argument("--list-devices", action="store_true")
    return ap.parse_args(argv)


def _chat_provider(a):
    """Model rozmowy: jawny wybór w profilu (ustawienia GUI/`--set chat_model=`) ma pierwszeństwo przed config.toml.
    Model oceny zostaje bez zmian."""
    from tutor.llm import QWEN3_8B, llm_settings
    s = llm_settings()
    m = getattr(a, "chat_model", None)
    if m and s["roles"]["conversation"]["provider"] == "ollama":
        s["roles"]["conversation"] = {"provider": "ollama", "model": m, **({"think": False} if m == QWEN3_8B else {})}
    return build_provider("conversation", s)


def _lines() -> queue.Queue:
    q: queue.Queue = queue.Queue()
    threading.Thread(target=lambda: [q.put(ln.strip()) for ln in sys.stdin] and q.put(None), daemon=True).start()
    return q


def run(argv: list[str], *, stt=None, tts=None, sink=None, mic=None, llm=None, lines=None,
        out=print, db=None, eval_llm=None, err=None) -> int:
    """`err`: komunikaty błędów (domyślnie stderr; GUI przekazuje je do okna sesji)."""
    err = err or (lambda m: print(m, file=sys.stderr))
    a = parse(argv)
    if a.list_devices:
        try:
            print("\n".join(A.device_names()))
        except A.AudioUnavailable as e:
            err(e)
            return 1
        return 0
    conn = db or open_db(config.db_path())
    repo = Repo(conn)
    p = repo.find_profile(a.profile) if a.profile else (repo.get_profile(config.get_last_profile() or -1))
    if p is None:
        err("Brak profilu. Utwórz: python main.py profile create NAZWA")
        return 1
    if a.progress:
        from tutor.app import progress as PG
        from tutor.pedagogy import content as C
        for ln in PG.render(PG.build(repo, C.load(p["target_lang"]), p["id"], datetime.now(UTC))):
            out(ln)
        if db is None:
            conn.close()
        return 0
    if a.finish_evals:
        code = _finish_evals(repo, p, out, eval_llm, err)
        if db is None:
            conn.close()
        return code
    _apply_settings(a, argv, repo, p)
    if a.history or a.set:
        _history_settings(a, repo, p, out)
        if db is None:
            conn.close()
        return 0
    if a.exam == "list":
        _exam_list(repo, p, out)
        if db is None:
            conn.close()
        return 0
    if a.weakspots or a.achievements:
        _reports(a, repo, p, out)
        if db is None:
            conn.close()
        return 0
    build_eval = llm is None and eval_llm is None     # produkcja: modele z config.toml; wstrzyknięte `llm` = bez oceny
    if llm is None:
        llm = _chat_provider(a)
    if llm.external:
        err("Rozmowa głosowa używa tylko modeli lokalnych (Gemini odroczony).")
        return 1
    if not llm.health():
        err("Ollama nie odpowiada: uruchom `ollama serve`.")
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
        from tutor.voice import tts as TT
        tts = TT.SilentTTS() if a.no_audio else TT.build_tts(a.tts, a.tts_voice, a.speed)

    q = lines or _lines()
    lines = q
    if a.placement:                                   # dobrowolne: nigdy automatycznie przy pierwszej lekcji
        _placement_phase(a, repo, p, llm, tts, sink, mic, stt, lines, out)
        _shutdown(mic, sink, conn, db)
        return 0
    if a.exam:
        _exam_phase(a, repo, p, llm, tts, sink, mic, stt, lines, out)
        _shutdown(mic, sink, conn, db)
        return 0
    if a.review or a.drill:
        _review_phase(a, repo, p, llm, tts, sink, mic, stt, lines, out)
        _shutdown(mic, sink, conn, db)
        return 0
    lesson_pack = skill = items = choice = None
    kind = "voice"
    allow = bool(p["allow_unreviewed_practice"])
    cur = repo.find_open_session(p["id"])
    chat_topic = None
    chat_level = chat_level_src = chat_level_note = None
    if a.chat:
        from tutor.app import quickchat as QC
        kind = "chat"
        chat_level, chat_level_src, chat_level_note = QC.resolve_level(repo, p["id"], a.chat_level)
        if cur and cur["kind"] == "chat":
            chat_topic = repo.get_session_plan(p["id"], cur["id"]).get("topic")
            if a.chat != "ask" and chat_topic and (T0 := _choose_topic(a, repo, p, q, out)) and \
                    (T0.get("id"), T0["pl"]) != (chat_topic.get("id"), chat_topic["pl"]):
                chat_topic, cur = T0, dict(cur) | {"kind": "chat-other"}   # inny temat: nowa rozmowa
        if chat_topic is None:
            chat_topic = _choose_topic(a, repo, p, q, out)
            if chat_topic is None:
                _shutdown(mic, sink, conn, db)
                return 0
    if a.lesson:
        from tutor.app import goal as G
        from tutor.app import lesson as L
        from tutor.pedagogy import content as C
        lesson_pack = C.load(p["target_lang"])
        open_plan = repo.get_session_plan(p["id"], cur["id"]) if cur and cur["kind"] == "lesson" else {}
        if a.lesson != "default":                      # ręczny cel: `--lesson SKILL_ID`
            goal = a.lesson
            choice = {"source": "manual", "reason": "Cel wskazany ręcznie (--lesson).", "provisional": False}
        elif open_plan.get("lesson"):                  # wznowienie rozpoczętej lekcji: ten sam cel
            goal = open_plan["lesson"]
        else:                                          # automatyczny wybór z danych ucznia
            ch = G.choose(repo, lesson_pack, p["id"], datetime.now(UTC))
            if ch is None:
                err("Brak celu lekcji z dostępnymi materiałami (wyjaśnienie i zadania).")
                return 1
            goal, choice = ch.skill_id, {"source": ch.source, "reason": ch.reason, "provisional": ch.provisional}
        try:
            L.prepare(lesson_pack, goal, allow_unreviewed=allow)
        except L.LessonError as e:
            err(e)
            return 1
        kind = "lesson"
    if a.chat and not (cur and cur["kind"] == "chat"):
        if cur:
            repo.pause_session(p["id"], cur["id"])
        if not chat_topic.get("id") and a.chat_category in T.chat_catalog()["categories"]:
            cat = T.chat_catalog()["categories"][a.chat_category]          # własny temat w wybranej kategorii
            chat_topic = {**chat_topic, "category": cat["id"], "category_pl": cat["pl"]}
        sid = QC.start(repo, p["id"], chat_topic, a.minutes, a.correction, level=chat_level,
                       level_source=chat_level_src, category=chat_topic.get("category"), mode=a.chat_mode)
    elif cur and cur["kind"] == kind and (not a.lesson or
                                        repo.get_session_plan(p["id"], cur["id"]).get("lesson") == goal):
        sid = cur["id"]                                # niezakończona sesja (Ctrl+C / awaria): wznów, bez duplikatów
        repo.resume_session(p["id"], sid)
        out(f"Wznawiam sesję #{sid}.")
    else:
        if cur:
            repo.pause_session(p["id"], cur["id"])     # inna otwarta sesja zostaje wznawialna
        sid = repo.start_session(p["id"], kind)
    goals = {}
    system = SYSTEM_PROMPT
    if a.chat:
        cplan = repo.get_session_plan(p["id"], sid)         # wznowienie: scenariusz, poziom i tryb jak w planie
        chat_level, chat_mode = cplan.get("level") or chat_level, cplan.get("mode") or a.chat_mode or (
            "roleplay" if chat_topic.get("kind") == "roleplay" else "natural")
        system = QC.system_prompt(chat_topic, chat_level, chat_mode)
        if a.minutes is None:
            a.minutes = repo.get_session_plan(p["id"], sid).get("minutes")
    if a.lesson:
        skill, items = L.begin(repo, lesson_pack, p["id"], sid, goal, choice, allow)
        goals = {skill.id: skill.can_do_pl}            # cel lekcji trafia do oceny wypowiedzi
        system += L.system_focus(lesson_pack, skill)
    conv_pack = lesson_pack
    if conv_pack is None and (build_eval or eval_llm is not None):
        from tutor.pedagogy import content as C
        conv_pack = C.load(p["target_lang"])
    svc = _eval_service(repo, conn, p, sid, eval_llm, build_eval, out, goals, conv_pack)
    feedback = None
    if svc and conv_pack:
        from tutor.app import feedback as FB
        from tutor.pedagogy.correction import effective_style
        style = a.correction or effective_style(p["correction_style"], conv_pack.rubric)["style"]
        if a.chat and chat_mode == "roleplay":           # roleplay: nie przerywamy scenariusza (intensywna = recast)
            style = {"intensive": "periodic"}.get(style, "summary")
        feedback = lambda text: FB.directive(repo, conv_pack, p["id"], sid, style, set(goals), text)  # noqa: E731
    tutor = VoiceTutor(repo, p["id"], sid, llm, tts, sink, system=system, context_window=cw,
                       echo=lambda s: out(f"Tutor: {s}"), record_user_turn=svc.user_turn if svc else None,
                       feedback=feedback)
    speak = None if a.no_audio else _speaker(tutor, q, mic, svc, out)       # lekcja głosowa; --no-audio = sam tekst
    out(f"Profil: {p['name']} · LLM: {llm.model} · TTS: {tts.name}/{tts.voice} · tryb: {a.mode if mic else 'tekst'}")
    out(HELP)
    ep = A.Endpointer()
    clean = False
    proceed = True
    try:
        if a.chat:
            fresh = not repo.list_turns(p["id"], sid)
            out(f"Quick Chat — temat: {chat_topic['pl']}. (Powiedz „change the topic”, by zmienić; q = koniec.)")
            cat_pl = T.chat_catalog()["categories"].get(cplan.get("category") or "", {}).get("pl", "Własny temat")
            out(f"Ustawienia rozmowy: {chat_level} · {cat_pl} · {QC.MODES_PL.get(chat_mode, chat_mode)}")
            if fresh:
                if cplan.get("level_source") != "manual" and chat_level_note:
                    out(f"[{chat_level_note}]")
                if (sc := QC.scenario_line(chat_topic)) and chat_mode == "roleplay":
                    out(sc)
                first = QC.opener(chat_topic, chat_level)
                out(f"Tutor: {first}")
                repo.add_turn(p["id"], sid, "assistant", first)
                if speak:
                    speak(first)
        if a.lesson:
            proceed = _lesson(L, repo, lesson_pack, p, sid, skill, items, svc, a, q, mic, stt, ep, out, speak)
        switched = None
        while proceed:
            if a.chat and QC.time_up(repo, p["id"], sid, datetime.now(UTC)):
                out("Czas rozmowy minął — kończymy.")
                if speak:
                    speak("Our time is up. That was a nice chat. See you next time.")
                break
            try:
                text, t_end, mode, low = _listen(a, q, mic, stt, ep, out,
                                                 svc.begin_activity if svc else (lambda: None),
                                                 svc.tutor_done if svc else (lambda: None))
                if text is None:
                    break
                if not text:
                    continue
                out(f"You: {text}")
                if INTENT.classify(text) == "finish":      # koniec sesji ma pierwszeństwo przed nowym tematem
                    out("Tutor: Okay, let's stop here. Thanks for the chat!")
                    if speak:
                        speak("Okay, let's stop here. Thanks for the chat!")
                    break
                req = INTENT.requested_topic(text) if a.chat else None
                if a.chat and (req or INTENT.detect(text) == "skip"):  # „zmień temat”: wskazany albo z generatora
                    cp = repo.get_session_plan(p["id"], sid)
                    used = {t["id"] for t in cp.get("topics", []) if t.get("id")}
                    nxt = T.custom(req) if req else T.suggest(
                        repo, p["id"], 1, exclude=used, category=cp.get("category") or "general",
                        level=cp.get("level") or "B1", mode=cp.get("mode") or "natural")[0]
                    base = QC.switch(repo, p["id"], sid, nxt)
                    tutor.system = base + QC.switch_note(nxt, cp.get("level") or "B1")   # tylko na tę odpowiedź
                    switched = base
                    out(f"[nowy temat: {nxt['pl']}]")
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
                if switched:
                    tutor.system, switched = switched, None
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
            finally:
                if svc:
                    svc.tutor_done()     # każdy cykl (też przerwany: STT, TTS, Ctrl+C) zwalnia ocenianie
        if proceed and svc and conv_pack:
            if a.summary_wait and svc.pending:             # ograniczone czekanie na ocenę ostatnich wypowiedzi
                out(f"[sprawdzam jeszcze {svc.pending} wypowiedzi przed podsumowaniem…]")
                svc.wait_idle(min(60.0, max(a.summary_wait, 3.0 * svc.pending)))   # ~2 s na wypowiedź (Qwen3 8B)
            from tutor.app import feedback as FB
            notes = FB.summary_lines(repo, conv_pack, p["id"], sid, pending=svc.pending)
            for ln in notes:
                out(ln)
            if a.chat and not notes:
                out("Brak sugestii poprawek w ocenionych wypowiedziach.")
            if svc.pending:
                out(f"[{svc.pending} wypowiedzi oceni później: GUI (Historia) albo `--finish-evals`.]")
            if speak and a.lesson:
                from tutor.app import lesson_voice as LV
                speak(LV.farewell(bool(notes)))
        if proceed and a.chat and repo.get_session_plan(p["id"], sid).get("category") == "medical":
            out("Informacja zwrotna dotyczy wyłącznie języka, nie wiedzy ani decyzji klinicznych.")
        clean = proceed                               # `q` w trakcie ćwiczeń = pauza (lekcję można wznowić)
    except KeyboardInterrupt:
        pass
    finally:
        if svc:
            svc.close()
            _report(svc, out)
        if clean and (a.chat or not (svc and svc.pending)):
            repo.end_session(p["id"], sid)             # rozmowa: oczekujące oceny dokończy `--finish-evals`/GUI
        else:
            repo.pause_session(p["id"], sid)           # Ctrl+C / wyjątek / nieocenione tury: sesję można wznowić
        if mic:
            mic.close()
        if hasattr(sink, "close"):
            sink.close()
        if db is None:
            conn.close()
    return 0


def _choose_topic(a, repo, p, q, out) -> dict | None:
    """`--chat TEMAT` = własny temat; bez argumentu: propozycje (numer, `r` = losuj nowe, własny tekst, q = anuluj)."""
    from tutor.app import quickchat as QC
    from tutor.app import topics as T
    if a.chat != "ask":
        return T.get(a.chat) or T.custom(a.chat)
    shown, n = T.suggest(repo, p["id"], 4, category=a.chat_category or "general", mode=a.chat_mode or "natural",
                         level=QC.resolve_level(repo, p["id"], a.chat_level)[0]), 0
    while True:
        out("Wybierz temat rozmowy (numer), `r` = wylosuj inne, albo wpisz własny temat; q = anuluj:")
        for i, t in enumerate(shown, 1):
            out(f"  {i}. {t['pl']} ({t['category_pl']})")
        ln = q.get()
        if ln in (None, "q", "quit"):
            return None
        n += 1
        kind, val = QC.pick(repo, p["id"], ln, shown, n)
        if kind == "topic":
            return val
        if kind == "list":
            shown = val


def _shutdown(mic, sink, conn, db) -> None:
    if mic:
        mic.close()
    if hasattr(sink, "close"):
        sink.close()
    if db is None:
        conn.close()


def _asker(a, q, mic, stt, ep, svc, speak, out):
    """Pobiera odpowiedź ucznia (tekst/głos) jako `lesson.Answer`; None = koniec. Wspólne dla lekcji i dopasowania."""
    from tutor.app import lesson as L
    from tutor.app import lesson_voice as LV

    def ask(item, i):
        while True:
            try:
                text, _, mode, low = _listen(a, q, mic, stt, ep, out, svc.begin_activity if svc else (lambda: None),
                                             svc.tutor_done if svc else (lambda: None))
            finally:
                if svc:
                    svc.tutor_done()
            if text is None:
                return None
            if text:
                return L.Answer(text, mode, low)
            if mode == "voice" and speak:
                speak(LV.silence())
    return ask


def _placement_phase(a, repo, p, llm, tts, sink, mic, stt, lines, out) -> bool:
    """Dopasowanie poziomu. True = ukończone; False = przerwane (sesja wstrzymana, wznowienie `--placement`)."""

    from tutor.app import placement as PL
    from tutor.pedagogy import content as C
    pack = C.load(p["target_lang"])
    cur = repo.find_open_session(p["id"])
    if cur and cur["kind"] == "placement":
        sid = cur["id"]
        repo.resume_session(p["id"], sid)
        out(f"Wznawiam dopasowanie (sesja #{sid}).")
    else:
        if cur:
            repo.pause_session(p["id"], cur["id"])
        sid = repo.start_session(p["id"], "placement")
    q = lines or _lines()
    tutor = VoiceTutor(repo, p["id"], sid, llm, tts, sink)
    speak = None if a.no_audio else _speaker(tutor, q, mic, None, out)
    out("Wstępne dopasowanie: kilka krótkich pytań o gramatykę i słownictwo (q = przerwij i wznów później). "
        "To nie jest diagnoza CEFR; niepewne rozpoznanie mowy nie obniża wyniku.")
    if speak:
        speak("Let's start with a few short questions. Please answer in whole sentences.")
    ask = _asker(a, q, mic, stt, A.Endpointer(), None, speak, out)
    try:
        rep = PL.run(repo, pack, p["id"], sid, ask, out, now=datetime.now(UTC), speak=speak,
                     allow_unreviewed=bool(p["allow_unreviewed_practice"]), mode="voice" if mic else "text")
    except KeyboardInterrupt:
        repo.pause_session(p["id"], sid)
        return False
    if rep.quit:
        repo.pause_session(p["id"], sid)
        out("Dopasowanie przerwane — wznowisz je poleceniem `--placement`.")
        return False
    repo.end_session(p["id"], sid)
    return True


def _apply_settings(a, argv, repo, p) -> None:
    """Ustawienia profilu wypełniają tylko te opcje, których NIE podano w wierszu poleceń (CLI wygrywa)."""
    from tutor.app import settings as ST
    eff = ST.effective(repo, p["id"])
    given = lambda *names: any(x == n or x.startswith(n + "=") for x in argv for n in names)  # noqa: E731
    if not given("--tts-voice"):
        a.tts_voice = eff["tts_voice"]
    if not given("--speed"):
        a.speed = float(eff["speed"])
    if not given("--mode"):
        a.mode = eff["mic_mode"]
    if not given("--stt-model"):
        a.stt_model = eff["stt_model"]
    if not given("--stt-confirm"):
        a.stt_confirm = eff["stt_confirm"]
    if eff["io_mode"] == "text":
        a.no_audio = True
    for dev in ("input_device", "output_device"):
        if not given("--" + dev.replace("_", "-")) and eff[dev] != "default":
            setattr(a, dev, eff[dev])
    a.chat_model = repo.get_settings(p["id"]).get("chat_model")    # tylko jawny wybór w profilu nadpisuje config
    for opt, key in (("--chat-level", "chat_level"), ("--chat-category", "chat_category"),
                     ("--chat-mode", "chat_mode")):
        if not given(opt):
            setattr(a, key, eff[key])


def _history_settings(a, repo, p, out) -> None:
    from tutor.app import history as H
    from tutor.app import settings as ST
    if a.set:
        changes = {}
        for kv in a.set:
            k, _, v = kv.partition("=")
            if kv.strip() == "?" or not v:
                for key, val in ST.effective(repo, p["id"]).items():
                    out(f"  {key} = {val}")
                return
            changes[k.strip()] = v.strip()
        try:
            for key, val in ST.update(repo, p["id"], changes).items():
                out(f"  {key} = {val}")
        except ST.SettingError as e:
            out(f"Błąd ustawień: {e}")
    if a.history:
        for ln in H.render(repo, p["id"]):
            out(ln)


def _exam_list(repo, p, out) -> None:
    from tutor.app import exams as EX
    from tutor.pedagogy import content as C
    pack = C.load(p["target_lang"])
    for path in EX.load_all().values():
        for ln in EX.render(EX.readiness(repo, pack, p["id"], path, bool(p["allow_unreviewed_practice"]))):
            out(ln)
        out(f"Uruchom ćwiczenia: `--exam {path['id']}`")


def _exam_phase(a, repo, p, llm, tts, sink, mic, stt, lines, out) -> None:
    from tutor.app import exams as EX
    from tutor.pedagogy import content as C
    pack = C.load(p["target_lang"])
    try:
        path = EX.get(a.exam)
    except EX.ExamError as e:
        out(str(e))
        return
    cur = repo.find_open_session(p["id"])
    same = cur and cur["kind"] == "exam" and \
        repo.get_session_plan(p["id"], cur["id"]).get("exam", {}).get("path") == path["id"]
    if same:
        sid = cur["id"]
        repo.resume_session(p["id"], sid)
        out(f"Wznawiam ćwiczenia (sesja #{sid}).")
    else:
        if cur:
            repo.pause_session(p["id"], cur["id"])
        sid = repo.start_session(p["id"], "exam")
    q = lines or _lines()
    speak = None if a.no_audio else _speaker(VoiceTutor(repo, p["id"], sid, llm, tts, sink), q, mic, None, out)
    ask = _asker(a, q, mic, stt, A.Endpointer(), None, speak, out)
    try:
        res = EX.run(repo, pack, p["id"], sid, path, ask, out, now=datetime.now(UTC), speak=speak,
                     allow=bool(p["allow_unreviewed_practice"]))
    except KeyboardInterrupt:
        repo.pause_session(p["id"], sid)
        return
    if res["finished"]:
        repo.end_session(p["id"], sid)
    else:
        repo.pause_session(p["id"], sid)
        out("Ćwiczenia przerwane — wznowisz je tym samym poleceniem.")


def _finish_evals(repo, p, out, eval_llm, err) -> int:
    """Dokańcza oceny oczekujących wypowiedzi (bez podwójnego liczenia) i pokazuje podsumowania tych rozmów."""
    from tutor.app import eval_runner as ER
    from tutor.app import feedback as FB
    from tutor.llm.structured import structured
    from tutor.pedagogy import content as C
    pending = repo.pending_by_session(p["id"])
    if not pending:
        out("Wszystkie wypowiedzi są ocenione.")
        return 0
    prov = eval_llm or build_provider("evaluation")
    if prov.external or not prov.health():
        err("Model oceny niedostępny lokalnie — oceny zostają w kolejce.")
        return 1
    pack = C.load(p["target_lang"])
    out(f"Oceniam {sum(pending.values())} wypowiedzi z {len(pending)} rozmów…")
    r = ER.catch_up(repo, pack, prov, structured, p["id"], model=getattr(prov, "model", None))
    for sid in r["sessions"]:
        left = repo.pending_by_session(p["id"]).get(sid, 0)
        out(f"\nRozmowa #{sid}:")
        for ln in FB.summary_lines(repo, pack, p["id"], sid, pending=left) or ["Brak sugestii poprawek."]:
            out(ln)
    out(f"\nOcenione: {r['done']}, wciąż w kolejce: {r['left']}.")
    return 0


def _reports(a, repo, p, out) -> None:
    from tutor.app import achievements as AC
    from tutor.app import weakspots as WS
    from tutor.pedagogy import content as C
    now = datetime.now(UTC)
    if a.weakspots:
        for ln in WS.render(WS.build(repo, C.load(p["target_lang"]), p["id"], now)):
            out(ln)
    if a.achievements:
        for n in AC.award(repo, p["id"], now):
            out(f"★ Nowe osiągnięcie: {n['name']} — {n['description']}")
        ov = AC.overview(repo, p["id"], now)
        out(f"Osiągnięcia: {ov['earned']}/{ov['total']} ({ov['note']})")
        for i in ov["items"]:
            mark = "✓" if i["earned"] else f"{i['progress']}/{i['target']}"
            out(f"  [{mark}] {AC.CATEGORIES[i['category']]}: {i['name']}")


def _review_phase(a, repo, p, llm, tts, sink, mic, stt, lines, out) -> None:

    from tutor.app import review as RV
    from tutor.pedagogy import content as C
    pack = C.load(p["target_lang"])
    only = None
    if a.drill:
        from tutor.app import weakspots as WS
        rep = WS.build(repo, pack, p["id"], datetime.now(UTC))
        only = WS.resolve_drill(rep, pack, a.drill, bool(p["allow_unreviewed_practice"]))
        if not only:
            out("Brak materiałów do ćwiczeń dla tego celu — wybierz inny wpis z `--weakspots`.")
            return
    kind = "drill" if a.drill else "review"
    cur = repo.find_open_session(p["id"])
    if cur and cur["kind"] == kind:
        sid = cur["id"]
        repo.resume_session(p["id"], sid)
        out(f"Wznawiam {'ćwiczenia' if a.drill else 'powtórki'} (sesja #{sid}).")
    else:
        if cur:
            repo.pause_session(p["id"], cur["id"])
        sid = repo.start_session(p["id"], kind)
    q = lines or _lines()
    speak = None if a.no_audio else _speaker(VoiceTutor(repo, p["id"], sid, llm, tts, sink), q, mic, None, out)
    ask = _asker(a, q, mic, stt, A.Endpointer(), None, speak, out)
    try:
        res = RV.run(repo, pack, p["id"], sid, ask, out, now=datetime.now(UTC), speak=speak,
                     allow=bool(p["allow_unreviewed_practice"]), only=only)
    except KeyboardInterrupt:
        repo.pause_session(p["id"], sid)
        return
    if res.nothing_due:
        out("Brak zaległych powtórek na dziś.")
    if res.quit:
        repo.pause_session(p["id"], sid)
        out("Powtórki przerwane — wznowisz je poleceniem `--review`.")
    else:
        repo.end_session(p["id"], sid)


def _eval_service(repo, conn, p, sid, eval_llm, build_eval, out, goals=None, pack=None):
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
    pack = pack or C.load(p["target_lang"])
    path = conn.execute("PRAGMA database_list").fetchone()[2]
    svc = SessionService(
        repo, lambda: Repo(open_db(path)),
        lambda wrepo: make_queue(wrepo, pack, eval_llm, structured, profile_id=p["id"], session_id=sid,
                                goals=goals or {}, batch=1),
        # batch=1: Qwen3 8B ocenia 1 wypowiedź w ~2 s, partię 5 w ~30 s (pomiar F7); wypowiedź ucznia anuluje całą
        # trwającą partię, więc przy partiach po 5 ocena w rozmowie prawie nigdy się nie kończyła.
        p["id"], sid)
    n = svc.start()
    if n:
        out(f"[do oceny z poprzedniej sesji: {n}]")
    return svc


def _speaker(tutor, q, mic, svc, out):
    """Bezpieczne mówienie gotowych komunikatów: mikrofon wyciszony, Enter przerywa, ocena w tle wstrzymana,
    błąd TTS = jedna informacja i dalej sam tekst."""
    state = {"on": True}

    def speak(text: str) -> None:
        parts = [c for x in text.split("\n\n") if (c := clean_for_speech(x))]   # \n\n = pauza (lesson_voice.PAUSE)
        if not state["on"] or not parts:
            return
        if svc:
            svc.begin_activity()
        speaking = threading.Event()
        speaking.set()
        watcher = threading.Thread(target=_cancel_on_enter, args=(q, tutor, speaking), daemon=True)
        watcher.start()
        if mic:
            mic.mute(3600)
        try:
            tutor.say(parts)
            if tutor.last_error:
                out(f"[błąd TTS: {tutor.last_error} — dalej bez głosu]")
                state["on"] = False
        finally:
            speaking.clear()
            watcher.join(timeout=0.3)
            if mic:
                mic.mute(SPEAK_TAIL_S)
            if svc:
                svc.tutor_done()
    return speak


def _lesson(L, repo, pack, p, sid, sk, items, svc, a, q, mic, stt, ep, out, speak=None) -> bool:
    """Wyjaśnienie + ćwiczenia (odpowiedzi tekstem lub głosem). True = idziemy do rozmowy; False = uczeń przerwał."""

    from tutor.app import lesson_voice as LV
    say = speak or (lambda _t: None)
    plan = repo.get_session_plan(p["id"], sid)
    if not plan.get("done"):
        out(L.intro(pack, sk, plan.get("choice")))
        say(LV.greeting(sk))
        for part in LV.explanation(pack, sk):
            say(part)
    else:
        say(LV.welcome_back())

    ask = _asker(a, q, mic, stt, ep, svc, speak, out)

    res = L.run_exercises(repo, pack, p["id"], sid, sk, items, ask, out, now=datetime.now(UTC), speak=speak)
    if res.quit:
        out("Lekcja przerwana — wznowisz ją przy następnym uruchomieniu z tym samym `--lesson`.")
        return False
    if res.moved_on and res.declared_easy:      # „to łatwe”: zmiana celu na następnej lekcji, bez mastery
        repo.set_session_plan(p["id"], sid, {**repo.get_session_plan(p["id"], sid), "declared_easy": True})
        out("Zapisano, że ten cel wydaje Ci się łatwy — następna lekcja dobierze inny cel. To nie jest potwierdzenie "
            "opanowania (umiejętność zostaje do sprawdzenia).")
    if res.skipped and not res.moved_on:
        out(L.summary(res))
        out("Lekcja niedokończona — wróć do pominiętych zadań poleceniem `--lesson`.")
        return False
    if not plan.get("done") or len(plan["done"]) < len(items):
        out(L.summary(res))
        out("\nTeraz krótka rozmowa po angielsku — użyj tego, co ćwiczysz (q = koniec).")
        say(LV.chat_start(res.correct, res.total))
        say(LV.CHAT_Q)
        out(f"Tutor: {LV.CHAT_Q}")
        repo.add_turn(p["id"], sid, "assistant", LV.CHAT_Q)    # pytanie otwierające jest w historii rozmowy
    return True


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


def _listen(a, q, mic, stt, ep, out, begin=lambda: None,
            end=lambda: None) -> tuple[str | None, float, str, list[str] | None]:
    """`begin()` = uczeń zaczyna wypowiedź (nagrywanie/wpisanie linii); `end()` = odrzucony impuls (kliknięcie).
    Koniec cyklu po rozpoznaniu i odpowiedzi sygnalizuje pętla w `run`."""
    def typed(ln):
        if ln in (None, "q", "quit"):
            return None, 0.0, "text", None
        begin()
        return ln, time.monotonic(), "text", None

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
        begin()                                # przed nagrywaniem: ocena nie rusza i trwająca jest anulowana
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
        audio = A.listen_auto(mic, ep, poll=poll, on_speech=begin, on_noise=end)
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
    conf = getattr(a, "stt_confirm", "uncertain")
    if conf == "always" or (conf == "uncertain" and (low is None or low)):
        # F7: niepewna transkrypcja wraca do ucznia przed oceną. Poprawka tekstu to korekta ROZPOZNANIA (wypowiedź
        # idzie jak wpisana), nigdy poprawka błędu językowego; nic nie trafia do dziennika błędów.
        unsure = f" (niepewne: {', '.join(low)})" if low else ""
        out(f"[Sprawdź rozpoznanie: „{text}”{unsure} — Enter = wyślij · r = nagraj ponownie · wpisz poprawny tekst]")
        ln = q.get()
        if ln in ("q", "quit"):
            return None, 0.0, "text", None
        if ln.strip().lower() in ("r", "again", "ponownie"):
            out("(nagraj jeszcze raz)")
            return "", t_end, "text", None
        if ln.strip() and ln.strip() != text:
            out("[poprawiona transkrypcja — to nie jest błąd językowy]")
            return ln.strip(), t_end, "text", None
    return text, t_end, "voice", low
