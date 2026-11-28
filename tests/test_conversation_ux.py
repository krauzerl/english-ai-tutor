"""UX rozmowy (2026-11-28): powitanie nowej rozmowy, korekty przy wypowiedzi w trakcie sesji, krótka korekta głosowa
poważnego błędu przed odpowiedzią, ćwiczenia z dziennika, ortografia z mowy, rzeczywisty model w oknie."""
import json
import random
import time
from datetime import UTC, datetime

import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv, Interrupt, WaitLines
from tests.voice_fakes import Lines
from tutor.app import feedback as FB
from tutor.app import quickchat as QC
from tutor.app import remediation as R
from tutor.app import review as RV
from tutor.app import weakspots as W
from tutor.gui.runner import classify
from tutor.llm.base import Reply, Usage
from tutor.pedagogy import content as C

PACK = C.load("en")
ERRS = {   # tekst ucznia → obserwacja modelu (atrapa); reszta wypowiedzi bez uwag
    "I am boring at work": {"s": "boring", "f": "bored", "k": "error", "c": "morphology.word_form", "v": 2, "p": "h"},
    "I goed home": {"s": "goed", "f": "went", "k": "error", "c": "tense.past_simple", "v": 2, "p": "h"},
    "We met in Monday": {"s": "in", "f": "on", "k": "error", "c": "preposition.time", "v": 1, "p": "h"},
}


class TextEval(EvalProv):
    """Ocena zależna od treści wypowiedzi (partia 1); `delay` = czas „myślenia” modelu."""

    def __init__(self, delay=0.0, **kw):
        super().__init__(**kw)
        self.delay = delay

    def chat(self, messages, **kw):
        self.calls.append(messages)
        time.sleep(self.delay)
        body = messages[-1].content
        line = next(ln for ln in body.splitlines() if ln[:1].isdigit() and ln[1:3] == ": ")
        text = line[3:].strip().strip('"')
        obs = [o for k, o in ERRS.items() if k in text]
        u = [{"i": 0, "o": obs, "t": [], "cm": "ok", "cq": text[:20]}]
        return Reply(json.dumps({"u": u}), Usage(1, 1), "fake", "m")


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def _chat(env, lines, conv=None, ev=None, extra=()):
    conv = conv or FakeProvider(chunks=["Okay. ", "Tell me more."])
    code, out = env.go(lines, ["--no-audio", "--chat", "my job", "--correction", "periodic", *extra],
                       llm=conv, ev=ev or TextEval())
    return code, out, conv


# --- 1–2: powitanie ---
def test_new_chat_starts_with_greeting_intro_and_one_question(env):
    _, out, _ = _chat(env, Lines("q"))
    first = next(t for t in env.turns() if t["role"] == "assistant")["text"]
    assert first.split()[0].rstrip("!") in {"Hi", "Hello", "Hey", "Good"} or first.startswith("Hi there")
    assert first.count("?") == 1 and first.endswith("?")                     # jedno pytanie, na końcu
    assert "Nice to meet you" in first or "talk today" in first or "relaxed chat" in first   # pierwsza rozmowa


def test_resumed_chat_is_not_greeted_again(env):
    _chat(env, Interrupt("I like my job"))
    assert env.repo.list_sessions(env.pid)[0]["status"] == "paused"
    _, out, _ = _chat(env, WaitLines(lambda: True, "Still here"))
    assert any("Wznawiam" in o for o in out)
    tutor = [t["text"] for t in env.turns() if t["role"] == "assistant"]
    hellos = [t for t in tutor if t.split()[0].rstrip("!,") in {"Hi", "Hello", "Hey", "Good"}]
    assert len(hellos) == 1                                                  # powitanie tylko na starcie rozmowy


def test_greeting_varies_between_conversations_and_roleplay_keeps_role_opener(env):
    topic = {"id": "gen.trip", "kind": "topic", "q": "Tell me about a trip?", "category": "general", "pl": "x"}
    s1 = env.repo.start_session(env.pid, "chat")
    g1 = QC.greeting(env.repo, env.pid, s1, topic, "B1", rnd=random.Random(1), now=datetime(2026, 1, 1, 9))
    s2 = env.repo.start_session(env.pid, "chat")
    g2 = QC.greeting(env.repo, env.pid, s2, topic, "B1", rnd=random.Random(1), now=datetime(2026, 1, 1, 9))
    p1, p2 = (env.repo.get_session_plan(env.pid, s)["greeting"] for s in (s1, s2))
    assert all(p1[k] != p2[k] for k in ("hello", "intro"))                   # nie ten sam wariant co ostatnio
    assert g1 != g2 and "again" in g2 or "back" in g2                       # druga rozmowa: „znów”
    rp = {"id": "gen.rp.hotel", "kind": "roleplay", "q": "Good evening, reception. How can I help you?"}
    assert QC.greeting(env.repo, env.pid, s2, rp, "B1") == rp["q"]


# --- 3–6: status, korekta przy wypowiedzi, głos tylko dla poważnych ---
def test_status_then_correction_attached_to_the_right_turn_without_ending_session(env):
    ev = TextEval()
    _, out, _ = _chat(env, WaitLines(lambda: env.applied() >= 2, "I goed home", "I like my job"), ev=ev)
    tid = next(t["id"] for t in env.users() if t["text"] == "I goed home")
    i_status = out.index(f"Ocena #{tid}: sprawdzam…")
    i_corr = next(i for i, o in enumerate(out) if o.startswith(f"Korekta #{tid}."))
    i_reply = next(i for i, o in enumerate(out) if o.startswith("Tutor:") and i > i_status)
    assert i_status < i_corr < i_reply                                        # korekta widoczna przed odpowiedzią
    ev_ = classify(out[i_corr])
    assert ev_["kind"] == "live_correction" and (ev_["tid"], ev_["span"], ev_["fix"]) == (tid, "goed", "went")
    other = next(t["id"] for t in env.users() if t["text"] == "I like my job")
    assert f"Ocena #{other}: bez uwag · model m" in out
    assert sum(o.startswith("Korekta #") for o in out) == 1                  # bez duplikatów
    assert len(ev.calls) == 2                                                 # bez dodatkowej oceny dla okna


def test_serious_error_gets_short_spoken_correction_in_the_same_reply(env):
    conv = FakeProvider(chunks=["Sure, ", "let me explain."])
    _, out, _ = _chat(env, WaitLines(lambda: env.applied() >= 1, "I am boring at work"), conv=conv)
    reply = next(o for o in out if o.startswith("Tutor: Quick note"))
    assert "“bored”" in reply and "not “boring”" in reply                        # zdanie korekty od kodu, nie modelu
    tid = env.users()[0]["id"]
    assert any(o.startswith(f"Omówiono #{tid}.") and o.endswith("głosem") for o in out)
    spoken = [json.loads(r[0]) for r in env.conn.execute(
        "SELECT data_json FROM app_event WHERE kind='log.tutor_turn'")]
    assert spoken[-1]["correction_spoken"] is True and spoken[-1]["correction_mode"] == "głosem"
    waits = [json.loads(r[0]) for r in env.conn.execute("SELECT data_json FROM app_event WHERE kind='log.eval_wait'")]
    assert waits and waits[0]["result"] == "done" and waits[0]["waited_s"] < 3.0
    live = [json.loads(r[0]) for r in env.conn.execute("SELECT data_json FROM app_event WHERE kind='log.eval_live'")]
    assert live[0]["before_reply"] is True and live[0]["model"] == "m" and live[0]["shown_after_s"] is not None


def test_minor_error_is_shown_but_not_spoken(env):
    _, out, conv = _chat(env, WaitLines(lambda: env.applied() >= 1, "We met in Monday"))
    assert any(o.startswith("Korekta #") and "[drobne]" in o for o in out)
    assert not any(o.startswith("Tutor: Quick note") for o in out)
    assert all("“on”" not in c[0].content for c in conv.calls)             # brak recastu/korekty w odpowiedzi


def test_slow_evaluation_does_not_block_reply_and_correction_arrives_later(env, monkeypatch):
    from tutor.voice import cli as CLI
    monkeypatch.setattr(CLI, "_eval_wait", lambda: 0.2)
    ev = TextEval(delay=0.6)
    _, out, _ = _chat(env, WaitLines(lambda: env.applied() >= 1 and time.sleep(0.3) is None, "I am boring at work"), ev=ev)
    tid = env.users()[0]["id"]
    assert f"Ocena #{tid}: w toku — sugestie pojawią się, gdy będą gotowe" in out
    assert not any(o.startswith("Tutor: Quick note") for o in out[:out.index(f"Ocena #{tid}: w toku — sugestie "
                                                                             "pojawią się, gdy będą gotowe") + 3])
    assert sum(o.startswith(f"Korekta #{tid}.") for o in out) == 1          # pojawiła się później, raz


# --- 7–9: odrzucone sugestie, niepewne STT, zakwestionowanie ---
def test_live_lines_skip_invalid_disputed_and_mark_stt(env):
    repo, pid = env.repo, env.pid
    sid = repo.start_session(pid, "chat")
    tid = repo.add_turn(pid, sid, "user", "I goed home and I no understand", input_mode="voice", low_probs=["goed"])
    ins = ("INSERT INTO observation(profile_id,session_id,turn_id,kind,span,fix,category,severity,confidence,status)"
           " VALUES (?,?,?,?,?,?,?,?,?,?)")
    bad = env.conn.execute(ins, (pid, sid, tid, "error", "home", "house", "word_choice", 1, "h", "dropped")).lastrowid
    stt = env.conn.execute(ins, (pid, sid, tid, "stt_suspect", "goed", "went", "tense.past_simple", 2, "h",
                                 "valid")).lastrowid
    ok = env.conn.execute(ins, (pid, sid, tid, "error", "no", "don't", "omission.auxiliary", 2, "h", "valid")).lastrowid
    lines = FB.live_lines(repo, PACK, pid, sid, tid)
    assert not any(f".{bad} " in ln for ln in lines)                         # walidator odrzucił: nie pokazujemy
    assert any(ln.startswith(f"Korekta #{tid}.{stt} [stt]") for ln in lines)  # niepewna transkrypcja ≠ pewny błąd
    repo.add_observation_review(pid, ok, "disputed")
    assert not any(f".{ok} " in ln for ln in FB.live_lines(repo, PACK, pid, sid, tid))   # zakwestionowane znika
    assert classify(lines[-1])["kind"] == "evalstate"


# --- 10–11: ćwiczenia z dziennika ---
def test_preposition_weakspots_have_matching_practice():
    assert W._skills_for(PACK, "preposition.time") == ["en.gram.prep_time"]
    assert W._skills_for(PACK, "preposition.dependent") == ["en.gram.prep_dependent"]
    assert set(W._skills_for(PACK, "preposition")) == {"en.gram.prep_time", "en.gram.prep_place_basic",
                                                       "en.gram.prep_dependent"}       # model zwrócił samo „preposition”
    assert W._skills_for(PACK, "tense.past_continuous") == []      # nie strona bierna (dopasowanie tylko po rodzicu)
    for sid in ("en.gram.prep_time", "en.gram.prep_place_basic", "en.gram.prep_dependent"):
        st = R.staged(PACK, sid, set(), True)
        assert len(st["pre"]) == 2 and len(st["post"]) == 2 and len(st["practice"]) == 3
        assert not {i.id for i in st["pre"]} & {i.id for i in st["post"]}
        assert len(R.fresh_items(PACK, sid, set(), True)) == 2


def test_drill_never_uses_retention_transfer_items(env):
    sid = "en.gram.prep_time"
    drill = {i.id for i in RV.pick_items(env.repo, PACK, env.pid, sid, n=99)}
    transfer = {i.id for i in R.fresh_items(PACK, sid, set(), True)}
    assert drill and transfer and not drill & transfer                       # zadania kontrolne poza ćwiczeniami
    assert all("retention" not in PACK.items[i].pools for i in drill)


# --- historyczna ortografia z poprawionej transkrypcji ---
def test_spelling_from_corrected_transcript_is_hidden_on_read(env):
    repo, pid = env.repo, env.pid
    sid = repo.start_session(pid, "chat")
    tid = repo.add_turn(pid, sid, "user", "Maybe I don't realy remember that", input_mode="text")
    env.conn.execute("INSERT INTO app_event(profile_id,kind,data_json,session_id) VALUES (?,?,?,?)",
                     (pid, "log.stt", json.dumps({"status": "corrected", "corrected": "Maybe I don't  realy remember "
                                                  "that"}), sid))
    oid = env.conn.execute("INSERT INTO observation(profile_id,session_id,turn_id,kind,span,fix,category,severity,"
                           "confidence,status) VALUES (?,?,?,?,?,?,?,?,?,?)",
                           (pid, sid, tid, "error", "realy", "really", "spelling", 1, "h", "valid")).lastrowid
    repo.put_error_log(pid, "spelling", None, count=1, status="active", severity_max=1, reopened=0, example="realy",
                       correction="really", example_observation_id=oid, first_seen="2026-11-27", last_seen="2026-11-27")
    assert repo.spoken_orthography_ids(pid) == {oid}
    assert [e["category"] for e in repo.list_errors(pid)] == []              # ukryte przy odczycie
    assert [e["category"] for e in repo.list_errors(pid, raw=True)] == ["spelling"]   # wiersz w bazie został
    rep = W.build(repo, PACK, pid, datetime.now(UTC))
    assert not rep["errors"]
    entry = next(e for e in rep["entries"] if e["id"] == oid)
    assert entry["counted"] is False and "mówionej" in entry["review_pl"]


# --- 12–13: rzeczywisty model i fallback ---
def test_model_line_reports_the_model_that_answered_and_fallback(env):
    class Routed(FakeProvider):
        last_provider, last_model, last_fallback = "gemini", "gemini-3.5-flash-lite", False
    _, out, _ = _chat(env, WaitLines(lambda: env.applied() >= 1, "I goed home"), conv=Routed(chunks=["Ok."]))
    m = classify(next(o for o in out if o.startswith("Model rozmowy:")))
    assert (m["kind"], m["provider"], m["model"], m["fallback"]) == ("model", "gemini", "gemini-3.5-flash-lite", False)
    assert m["eval_model"] == "m"                                             # model, który faktycznie ocenił
    from tutor.voice.cli import _Live, _model_line
    local = FakeProvider()
    local.last_provider, local.last_model, local.last_fallback = "ollama", "qwen3:8b", True
    line = _model_line(local, _Live(None, 0, 0, None, print))
    m = classify(line)
    assert (m["provider"], m["model"], m["fallback"]) == ("local", "qwen3:8b", True)


# --- 15: przerwanie i wznowienie bez duplikatów ---
def test_interrupt_and_resume_does_not_duplicate_corrections(env):
    _chat(env, Interrupt("I goed home"), ev=EvalProv(fail=99))
    _, out, _ = _chat(env, WaitLines(lambda: env.applied() >= 1, "Back again"))
    tid = next(t["id"] for t in env.users() if t["text"] == "I goed home")
    assert sum(o.startswith(f"Korekta #{tid}.") for o in out) == 1          # restore_pending: raz, w oknie wznowienia
    assert len([o for o in env.repo.list_observations(env.pid) if o["turn_id"] == tid]) == 1


def test_waited_turn_jumps_ahead_of_a_late_one():
    from tutor.app.eval_queue import EvalQueue, Pending
    q = EvalQueue(lambda b: [None] * len(b), lambda p, r: None)
    for i in (1, 2, 3):
        q.submit(Pending(i, "x", "text"))
    q.prioritize(3)
    assert [p.turn_id for p in q._q] == [3, 1, 2]                          # starsze zostają w kolejności
