"""Pilot readiness: learning logs + 8 scenariuszy integracyjnych (silnik CLI/GUI → SQLite → dziennik → raport).

Prawdziwa baza SQLite w tmp_path (nigdy baza właściciela), atrapy modeli rozmowy/oceny/STT. Mastery zamknięte.
"""
import json
import os
import stat
import time
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_cli_e2e import Env, EvalProv, Interrupt, WaitLines
from tests.test_stt_detailed import DetailedSTT
from tests.voice_fakes import FakeMic, Lines, blocks, tone
from tutor.app import goal as G
from tutor.app import growth
from tutor.app import learning_report as LR
from tutor.app import learnlog as LL
from tutor.app import profiles as PR
from tutor.pedagogy import content as C
from tutor.services.api import ServiceError, TutorAPI
from tutor.voice import audio as A
from tutor.voice.stt import Transcript


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def jsonl(env, sid):
    f = LL.session_file(env.repo, env.pid, sid)
    return [json.loads(x) for x in f.read_text().splitlines()] if f and f.exists() else []


def kinds(env, sid=None):
    return [e["kind"] for e in LL.events(env.repo, env.pid, session_id=sid)]


# --- Scenariusz 1: rozmowa z błędem, korekta, koniec ---
def test_s1_conversation_logs_dialogue_observation_and_session(env, pack):
    ev = EvalProv()
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, "I goed home yesterday"),
                       ["--no-audio", "--chat", "Weekend plans", "--chat-level", "B1"], ev=ev)
    assert code == 0
    s = env.repo.list_sessions(env.pid)[0]
    assert s["kind"] == "chat" and s["status"] == "ended"
    meta = json.loads(s["model_json"])
    for k in ("app", "conversation", "evaluation", "eval_prompt", "correction", "level", "activity", "io", "lang"):
        assert k in meta, k
    assert meta["level"] == "B1" and meta["io"] == "text" and meta["eval_prompt"] == "turn_eval.v3"
    roles = [t["role"] for t in env.turns()]
    assert roles[0] == "assistant" and "user" in roles                       # otwarcie + wypowiedź, kolejność tur
    obs = env.repo.list_observations(env.pid)
    assert [(o["kind"], o["span"], o["fix"], o["model"], o["prompt_version"]) for o in obs] == \
        [("error", "goed", "went", "m", "turn_eval.v3")]
    ks = kinds(env, s["id"])
    assert ks[0] == "log.session_start" and ks[-1] == "log.session_end" and "log.tutor_turn" in ks
    end = LL.events(env.repo, env.pid, session_id=s["id"])[-1]["data"]
    assert end["reason"] == "quit" and end["status"] == "ended" and end["user_turns"] == 1
    env.repo.add_observation(env.pid, s["id"], obs[0]["turn_id"], "error", "I go there", fix="I went there",
                             category="tense.past_simple", confidence="h", status="dropped",
                             drop_reason="span_not_found")
    case = next(c for c in LR.build(env.repo, pack, env.pid)["cases"] if c["type"] == "dropped_suggestion")
    assert case["observation"]["drop_reason"] == "span_not_found" and case["context"]["utterance"]
    rows = jsonl(env, s["id"])                                               # lustro JSONL: id, bez tekstu
    assert rows and {r["profile"] for r in rows} == {env.pid} and all(r["session"] == s["id"] for r in rows)
    assert "goed" not in json.dumps(rows) and "Weekend" not in json.dumps(rows)
    rep = LR.build(env.repo, pack, env.pid, session_id=s["id"])
    assert rep["errors"]["by_category"]["tense.past_simple"]["n"] == 1
    ex = rep["errors"]["by_category"]["tense.past_simple"]["examples"][0]
    assert ex["utterance"] == "I goed home yesterday" and ex["fix"] == "went"


def test_s1_finish_intent_reason(env):
    env.go(Lines("Let's stop here", "q"), ["--no-audio"], ev=EvalProv())
    sid = env.repo.list_sessions(env.pid)[0]["id"]
    assert LL.events(env.repo, env.pid, session_id=sid)[-1]["data"]["reason"] == "finish_intent"


# --- Scenariusz 2: powtarzający się błąd → rekomendacja lekcji ---
def test_s2_recurring_error_drives_recommendation(env, pack):
    ev = EvalProv()
    utts = ["I goed home", "Then we goed out", "They goed to work"]
    env.go(WaitLines(lambda: env.applied() >= 3, *utts), ["--no-audio"], ev=ev)
    errs = {e["category"]: e for e in env.repo.list_errors(env.pid)}
    assert errs["tense.past_simple"]["count"] == 3 and errs["tense.past_simple"]["status"] == "recurring"
    ch = G.choose(env.repo, pack, env.pid, datetime.now(UTC))
    assert ch.source == "error" and ch.category == "tense.past_simple"
    assert "sugestia modelu" in ch.reason and ch.provisional                 # nie twierdzimy, że to potwierdzone
    api = TutorAPI(env.repo)
    assert api.home(env.pid)["suggested_lesson"]["category"] == "tense.past_simple"


# --- Scenariusz 3: lekcja z dziennika błędów → potwierdzenie, plan, mastery zamknięte ---
class LessonLines(Lines):
    """Odpowiada błędnie na każde zadanie lekcji, dopóki ćwiczenia trwają; potem kończy (q)."""

    def __init__(self, env, answer):
        super().__init__()
        self.env, self.answer = env, answer

    def get(self, block=True, timeout=None):
        if timeout is not None:
            raise __import__("queue").Empty
        cur = self.env.repo.find_open_session(self.env.pid)
        plan = self.env.repo.get_session_plan(self.env.pid, cur["id"]) if cur else {}
        items, done = plan.get("items") or [], plan.get("done") or []
        return self.answer if items and len(done) < len(items) else "q"


def test_s3_error_lesson_confirmation_and_mastery_guard(env, pack):
    ev = EvalProv()
    env.go(WaitLines(lambda: env.applied() >= 3, "I goed home", "Then we goed out", "They goed to work"),
           ["--no-audio"], ev=ev)
    ch = G.choose(env.repo, pack, env.pid, datetime.now(UTC))
    code, out = env.go(LessonLines(env, "zzz wrong answer"), ["--no-audio", "--lesson"], ev=EvalProv())
    assert code == 0
    les = [s for s in env.repo.list_sessions(env.pid) if s["kind"] == "lesson"][0]
    plan = env.repo.get_session_plan(env.pid, les["id"])
    assert plan["lesson"] == ch.skill_id and plan["choice"]["source"] == "error"
    assert plan["agv"]["outcome"] == "confirmed" and plan["agv"]["category"] == "tense.past_simple"
    atts = env.repo.conn.execute("SELECT source, feedback_json FROM attempt WHERE profile_id=? AND session_id=?",
                                 (env.pid, les["id"])).fetchall()
    assert atts and {a[0] for a in atts} <= {"remediation", "practice"} and \
        all(json.loads(a[1])["no_mastery"] for a in atts)
    assert all(s["status"] != "mastered" for s in env.repo.list_skill_states(env.pid))
    again = G.choose(env.repo, pack, env.pid, datetime.now(UTC) + timedelta(days=1))   # test nieudany: powtórka
    assert again.source == "error" and "Test po lekcji" in again.reason
    meta = json.loads(les["model_json"])
    assert meta["lesson"] == ch.skill_id and meta["choice"] == "error"
    rep = LR.build(env.repo, pack, env.pid, session_id=les["id"])
    assert rep["progress"]["agv"][0]["outcome"] == "confirmed"
    assert rep["progress"]["choices"][0]["reason"] == plan["choice"]["reason"]   # dlaczego ta lekcja
    md = LR.render(rep, pack)
    assert "confirmed" in md and "Dlaczego ta lekcja" in md


# --- Scenariusz 4: retencja tylko na nowym zadaniu ---
def test_s4_retention_same_item_does_not_inflate(repo, pack):
    pid = repo.create_profile("ret")
    sid = repo.start_session(pid, "lesson")
    skill = next(s for s in pack.skills if any(skill_id == s for i in pack.items.values() for skill_id in i.skill_ids))
    items = [i.id for i in pack.items.values() if skill in i.skill_ids][:2]
    t0 = datetime(2026, 11, 1, 10, tzinfo=UTC)

    def att(item, day):
        repo.conn.execute("INSERT INTO attempt(profile_id,item_id,skill_id,session_id,correct,source,created_at) "
                          "VALUES (?,?,?,?,1,'practice',?)", (pid, item, skill, sid,
                                                              (t0 + timedelta(days=day)).isoformat()))
    att(items[0], 0)
    att(items[0], 8)                                                         # to samo zadanie po 8 dniach
    rows = growth._attempts(repo, pid)
    assert growth._retention(rows, pack)["after_7_days"]["n"] == 0
    att(items[1], 16)                                                        # nowe zadanie po przerwie
    r = growth._retention(growth._attempts(repo, pid), pack)
    assert r["after_7_days"] == {"correct": 1, "n": 1}


# --- Scenariusz 5: uczeń kwestionuje korektę ---
def test_s5_disputed_correction_goes_to_log_with_context(env, pack):
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=EvalProv())
    api = TutorAPI(env.repo)
    o = env.repo.list_observations(env.pid)[0]
    ws = api.review_observation(env.pid, o["id"], "disputed", note="I went home")
    assert ws["errors"] == [] or all(e["category"] != "tense.past_simple" for e in ws["errors"])
    r = api.report_problem(env.pid, "wrong_correction", observation_id=o["id"], note="variant is fine")
    assert r["status"] == "unverified" and r["session_id"] == o["session_id"] and r["turn_id"] == o["turn_id"]
    rep = LR.build(env.repo, pack, env.pid)
    assert rep["errors"]["by_category"] == {}                                # zakwestionowane nie są liczone
    case = next(c for c in rep["cases"] if c["type"] == "disputed_correction")
    assert case["review"]["note"] == "I went home" and case["label"] == "unverified"
    assert case["context"]["utterance"] == "I goed home" and case["context"]["tutor_after"]
    assert any(c["type"] == "report.wrong_correction" for c in rep["cases"])
    with pytest.raises(ServiceError):                                       # cudza korekta: odmowa
        api.review_observation(env.repo.create_profile("x"), o["id"], "disputed")


def test_s5_missed_error_and_answer_key_reports_keep_context(env, pack):
    env.go(WaitLines(lambda: env.applied() >= 1, "She have two cats"), ["--no-audio"], ev=EvalProv())
    api = TutorAPI(env.repo)
    r = api.report_problem(env.pid, "missed_error", quote="She have", note="should be has")
    assert r["turn_id"] and r["status"] == "unverified"
    assert env.repo.list_errors(env.pid) == [] or all(e["category"] != "agreement" for e in env.repo.list_errors(env.pid))
    case = next(c for c in LR.build(env.repo, pack, env.pid)["cases"] if c["type"] == "report.missed_error")
    assert case["quote"] == "She have" and case["context"]["utterance"] == "She have two cats"


# --- Scenariusz 6: błędna transkrypcja poprawiona przez ucznia ---
def test_s6_stt_correction_keeps_both_versions_no_language_error(env, pack):
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = DetailedSTT(Transcript("I want to by a car", ["by"]))
    ev = EvalProv()
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, "", "", "I want to buy a car"),
                       ["--mode", "ptt", "--stt-confirm", "uncertain"], mic=mic, stt=stt, sink=A.SimSink(), ev=ev)
    assert code == 0
    u = env.users()
    assert [(x["text"], x["input_mode"]) for x in u] == [("I want to buy a car", "voice")]   # poprawka = nadal mowa
    sid = u[0]["session_id"]
    stt_ev = [e for e in LL.events(env.repo, env.pid, session_id=sid) if e["kind"] == "log.stt"]
    assert stt_ev[-1]["data"]["status"] == "corrected"
    assert (stt_ev[-1]["data"]["original"], stt_ev[-1]["data"]["corrected"]) == ("I want to by a car",
                                                                                 "I want to buy a car")
    assert "stt_s" in stt_ev[-1]["data"] and "audio_s" in stt_ev[-1]["data"]
    assert [o for o in env.repo.list_observations(env.pid, status="valid") if o["kind"] == "error"] == []
    assert env.repo.list_errors(env.pid) == []                               # brak błędu językowego
    rows = [r for r in jsonl(env, sid) if r["kind"] == "log.stt"]
    assert rows[-1]["original_len"] == len("I want to by a car") and "original" not in rows[-1]
    case = next(c for c in LR.build(env.repo, pack, env.pid)["cases"] if c["type"] == "stt_transcript")
    assert case["stt"]["original"] == "I want to by a car"


# --- Scenariusz 7: awaria i wznowienie ---
def test_s7_crash_during_eval_resume_no_double_count(env, pack):
    env.go(Interrupt("I goed home"), ["--no-audio"], ev=EvalProv(fail=99))
    s = env.repo.list_sessions(env.pid)[0]
    assert s["status"] == "paused"
    assert LL.events(env.repo, env.pid, session_id=s["id"])[-1]["data"]["reason"] == "interrupted"
    env.go(WaitLines(lambda: env.applied() >= 1), ["--no-audio"], ev=EvalProv())
    env.go(WaitLines(lambda: env.applied() >= 1), ["--no-audio"], ev=EvalProv())   # kolejny restart: bez dublowania
    assert env.applied() == 1 and len(env.repo.list_observations(env.pid)) == 1
    assert env.repo.list_errors(env.pid)[0]["count"] == 1
    assert env.repo.conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert env.repo.conn.execute("PRAGMA foreign_key_check").fetchall() == []
    for r in jsonl(env, s["id"]):                                            # każda linia JSONL kompletna
        assert r["v"] == LL.FORMAT_VERSION


def test_s7_logging_failure_never_blocks_session(env, monkeypatch):
    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(LL, "_append", boom)
    code, _ = env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=EvalProv())
    assert code == 0 and env.applied() == 1
    assert env.repo.list_sessions(env.pid)[0]["status"] == "ended"


def test_s7_db_insert_failure_is_swallowed(repo):
    pid = repo.create_profile("z")

    class Broken:
        def execute(self, *a):
            raise RuntimeError("locked")
    r = type("R", (), {"conn": Broken(), "get_settings": lambda self, p: {}})()
    assert LL.log(r, pid, "log.x", 1) is None


# --- Scenariusz 8: izolacja profili ---
def test_s8_profile_isolation_of_history_logs_and_exports(env, pack, tmp_path):
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=EvalProv())
    bob = env.repo.create_profile("bob")
    bsid = env.repo.start_session(bob, "chat")
    btid = env.repo.add_turn(bob, bsid, "user", "Bob secret sentence")
    LL.log(env.repo, bob, "log.stt", bsid, status="ok", text="Bob secret sentence")
    ann = LR.build(env.repo, pack, env.pid)
    assert "Bob secret" not in json.dumps(ann, default=str)
    out = LR.export(env.repo, pack, env.pid, days=None)
    blob = "".join(p.read_text() for p in out.iterdir())
    assert "Bob secret" not in blob and out.name.startswith(f"p{env.pid}-")
    with pytest.raises(ValueError):                                         # zgłoszenie do cudzej sesji
        LL.report(env.repo, env.pid, "missed_error", session_id=bsid)
    with pytest.raises(ValueError):
        LL.report(env.repo, env.pid, "unclear_explanation", observation_id=10**6)
    files = {f.name for f in (LL.logs_dir(env.repo) / "sessions").iterdir()}
    assert any(f.startswith(f"p{bob}-") for f in files) and any(f.startswith(f"p{env.pid}-") for f in files)
    LL.delete_profile_logs(env.repo, bob)
    files = {f.name for f in (LL.logs_dir(env.repo) / "sessions").iterdir()}
    assert not any(f.startswith(f"p{bob}-") for f in files) and any(f.startswith(f"p{env.pid}-") for f in files)
    assert env.repo.list_turns(bob, bsid)[0]["id"] == btid                   # historia nauki zostaje
    assert LL.events(env.repo, env.pid)                                      # zdarzenia Ann nietknięte


# --- przechowywanie, uprawnienia, prywatność ---
def test_files_private_and_redacted_export(env, pack):
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home, mail me at jan.k@example.com or 600 700 800"),
           ["--no-audio"], ev=EvalProv())
    sid = env.repo.list_sessions(env.pid)[0]["id"]
    LL.report(env.repo, env.pid, "missed_error", quote="Ann goed to Kraków", note="call +48 600 700 800")
    d = LL.logs_dir(env.repo)
    assert stat.S_IMODE(os.stat(d).st_mode) == 0o700
    assert stat.S_IMODE(os.stat(LL.session_file(env.repo, env.pid, sid)).st_mode) == 0o600
    out = LR.export(env.repo, pack, env.pid, days=None, extra_words=["Kraków"])
    assert stat.S_IMODE(os.stat(out).st_mode) == 0o700
    for f in out.iterdir():
        assert stat.S_IMODE(os.stat(f).st_mode) == 0o600
    blob = "".join(f.read_text() for f in out.iterdir())
    assert "jan.k@example.com" not in blob and "600 700 800" not in blob and "Ann goed" not in blob \
        and "Kraków" not in blob
    assert "[EMAIL]" in blob and "[PHONE]" in blob and "[NAME]" in blob
    assert "ręcznie" in (out / "README.md").read_text()
    for ln in (out / "cases.jsonl").read_text().splitlines():
        assert json.loads(ln)["label"] == "unverified"
    raw = LR.export(env.repo, pack, env.pid, days=None, redacted=False)
    assert "jan.k@example.com" in (raw / "cases.jsonl").read_text() or "jan.k" in (raw / "report.md").read_text()


def test_learning_log_off_keeps_learning_but_reports_still_saved(env):
    env.repo.set_setting(env.pid, "learning_log", False)
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=EvalProv())
    sid = env.repo.list_sessions(env.pid)[0]["id"]
    assert kinds(env, sid) == [] and jsonl(env, sid) == []
    assert env.applied() == 1                                               # nauka działa normalnie
    LL.report(env.repo, env.pid, "missed_error", quote="x")
    assert kinds(env, sid) == ["report.missed_error"]


def test_prune_only_old_jsonl_never_db(env):
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=EvalProv())
    sid = env.repo.list_sessions(env.pid)[0]["id"]
    f = LL.session_file(env.repo, env.pid, sid)
    old = time.time() - 200 * 86400
    os.utime(f, (old, old))
    assert LL.prune(env.repo) == 1 and not f.exists()
    assert LL.events(env.repo, env.pid, session_id=sid) and env.repo.list_turns(env.pid, sid)


def test_profile_delete_and_reset_remove_log_files(env, pack):
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=EvalProv())
    LR.write_report(env.repo, pack, env.pid)
    d = LL.logs_dir(env.repo)
    assert list(d.glob(f"sessions/p{env.pid}-*")) and list(d.glob(f"reports/p{env.pid}-*"))
    PR.reset_progress(env.repo, env.pid, "ann", make_backup=False)
    assert not list(d.glob(f"sessions/p{env.pid}-*")) and not list(d.glob(f"reports/p{env.pid}-*"))


def test_report_render_full_period_and_cli(env, pack, monkeypatch, tmp_path, capsys):
    env.go(WaitLines(lambda: env.applied() >= 1, "I goed home"), ["--no-audio"], ev=EvalProv())
    md = LR.render(LR.build(env.repo, pack, env.pid, since=LL.since_days(7)), pack)
    for h in ("## A. Przebieg nauki", "## B. Błędy i słabości", "## C. Postępy", "## D. Problemy techniczne",
              "## E. Materiał do rozwoju"):
        assert h in md
    assert "sugestiami" in md                                                # niepewność oceny AI jawnie
    from tutor import cli
    monkeypatch.setattr(cli.config, "db_path", lambda: tmp_path / "data" / "tutor.db")
    lines: list[str] = []
    assert cli.logs_main(["--profile", "ann", "report", "--days", "7"], out=lines.append) == 0
    assert lines[0].endswith(".md") and os.path.exists(lines[0])
    assert cli.logs_main(["--profile", "ann", "flag", "missed_error", "--quote", "x"], out=lines.append) == 0
    assert cli.logs_main(["--profile", "ann", "off"], out=lines.append) == 0
    assert LL.enabled(env.repo, env.pid) is False
    assert cli.logs_main(["--profile", "ann", "delete"], out=lines.append) == 1           # bez --yes: odmowa


def test_logging_overhead_is_small(repo):
    pid = repo.create_profile("perf")
    sid = repo.start_session(pid, "chat")
    t0 = time.perf_counter()
    for i in range(200):
        LL.log(repo, pid, "log.tutor_turn", sid, first_audio_s=0.1, i=i)
    per = (time.perf_counter() - t0) / 200
    assert per < 0.01                                                        # ≪ czas odpowiedzi tutora (~0,1 s TTFT)


def test_migration_009_from_v8_keeps_rows_and_backs_up(tmp_path):
    import shutil
    import sqlite3

    from tutor.store.db import MIGRATIONS_DIR, open_db
    old = tmp_path / "old"
    old.mkdir()
    for f in MIGRATIONS_DIR.glob("00[1-8]_*.sql"):
        shutil.copy(f, old / f.name)
    path = tmp_path / "db" / "tutor.db"
    c = open_db(path, old)
    pid = c.execute("INSERT INTO profile(name) VALUES ('a')").lastrowid
    c.execute("INSERT INTO app_event(profile_id,kind) VALUES (?, 'ui_lang')", (pid,))
    assert c.execute("PRAGMA user_version").fetchone()[0] == 8
    c.close()
    c = open_db(path)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 9
    assert [tuple(r) for r in c.execute("SELECT kind, session_id FROM app_event")] == [("ui_lang", None)]
    bak = list((path.parent / "backups").glob("*.v8.*.bak"))
    assert bak and sqlite3.connect(bak[0]).execute("SELECT COUNT(*) FROM app_event").fetchone()[0] == 1
    c.close()


# --- GUI: zgłoszenia i raport przez serwer lokalny ---
from tests.test_gui import make_profile, srv, xdg  # noqa: E402,F401 - fikstury serwera GUI


def test_gui_report_routes(srv):  # noqa: F811 - fikstura z test_gui
    pid = make_profile(srv)
    assert srv.post("/api/report", {"pid": pid, "kind": "missed_error"}, headers={"X-Tutor-Token": "zly"})[0] == 403
    assert srv.post("/api/report", {"pid": pid, "kind": "rm -rf"})[0] == 400
    assert srv.post("/api/report", {"pid": pid, "kind": "missed_error", "quote": "x" * 501})[0] == 400
    code, r = srv.post("/api/report", {"pid": pid, "kind": "missed_error", "quote": "She have", "note": "has"})
    assert code == 200 and r["status"] == "unverified"
    code, r = srv.post("/api/learning_report", {"pid": pid, "days": 7})
    assert code == 200 and r["path"].endswith(".md") and "## E. Materiał" in r["markdown"]
    assert srv.post("/api/learning_report", {"pid": pid, "days": -1})[0] == 400
    code, s = srv.get(f"/api/settings?pid={pid}")
    assert s["values"]["learning_log"] is True and "learning_log" in s["schema"]
