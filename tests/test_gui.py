"""F7: lokalny serwer GUI — bezpieczeństwo HTTP, trasy, sesje przez ten sam silnik co CLI (atrapy modeli)."""
import http.client
import json
import threading
import time

import pytest

from tests.llm_fakes import FakeProvider
from tutor.gui import runner as R
from tutor.gui import server as SV
from tutor.store.db import open_db
from tutor.store.repo import Repo
from tutor.voice import cli


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return tmp_path


def fake_run(argv, **kw):
    return cli.run(argv, llm=FakeProvider(chunks=["Nice. ", "Tell me more."]), **kw)


STATUS = {"ollama": True, "models": ["qwen3:8b"], "roles": {}, "kokoro": False, "voices": [], "devices": [],
          "audio_error": "brak"}


@pytest.fixture
def srv(xdg):
    app = SV.App(runner=R.Runner(run=fake_run), token="T0K", status=lambda: STATUS)
    httpd = SV.serve(app, 0)
    th = threading.Thread(target=httpd.serve_forever, daemon=True)
    th.start()
    port = httpd.server_address[1]

    class C:
        def req(self, method, path, body=None, headers=None, host=None):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            h = {"Host": host or f"127.0.0.1:{port}"}
            data = None
            if body is not None:
                data = json.dumps(body).encode()
                h.update({"Content-Type": "application/json", "X-Tutor-Token": "T0K"})
            h.update(headers or {})
            c.request(method, path, body=data, headers=h)
            r = c.getresponse()
            raw = r.read()
            c.close()
            try:
                return r.status, json.loads(raw)
            except ValueError:
                return r.status, raw.decode()

        def get(self, path, **kw):
            return self.req("GET", path, **kw)

        def post(self, path, body, **kw):
            return self.req("POST", path, body, **kw)

        def wait_end(self, t=10):
            end = time.monotonic() + t
            while time.monotonic() < end:
                _, r = self.get("/api/session/events?since=0")
                if not r["running"] and any(e["kind"] == "end" for e in r["events"]):
                    return r["events"]
                time.sleep(0.05)
            raise AssertionError("sesja nie skończyła się")

        def wait_for(self, kind, t=10):
            end = time.monotonic() + t
            while time.monotonic() < end:
                _, r = self.get("/api/session/events?since=0")
                if any(e["kind"] == kind for e in r["events"]):
                    return r["events"]
                time.sleep(0.05)
            raise AssertionError(f"brak zdarzenia {kind}")

    c = C()
    c.app, c.port = app, port
    yield c
    app.runner.stop()
    httpd.shutdown()
    httpd.server_close()


def make_profile(c, name="ann"):
    code, p = c.post("/api/profiles", {"name": name})
    assert code == 200, p
    return p["id"]


# --- klasyfikacja wyjścia silnika ---

def test_classify_engine_lines():
    assert R.classify("Tutor: Hello there")["kind"] == "tutor"
    assert R.classify("You: hi")["text"] == "hi"
    t = R.classify("\nZadanie 2/5: She is ___ engineer.\n  1. a\n  2. an")
    assert (t["kind"], t["index"], t["total"]) == ("task", 2, 5) and "1. a" in t["text"]
    r = R.classify("\n[en.gram.articles_basic]\nZadanie 1/3: Translate")
    assert r["kind"] == "task" and r["tag"] == "en.gram.articles_basic"
    assert R.classify("  Usłyszałem: „I am” (niepewne słowa: am)")["kind"] == "heard"
    assert R.classify("✓ Dobrze.")["kind"] == "feedback"
    assert R.classify("[nowy temat: Transport]") == {"kind": "notice", "text": "nowy temat: Transport"}
    assert R.classify("> ")["kind"] == "prompt"
    assert R.classify("coś innego")["kind"] == "info"


def test_runner_one_session_at_a_time_and_errors_are_events():
    gate = threading.Event()

    def slow(argv, lines, out, err):
        err("Ollama nie odpowiada")
        gate.wait(5)
        raise RuntimeError("awaria")
    r = R.Runner(run=slow)
    r.start(["--voice"], "chat")
    with pytest.raises(R.Busy):
        r.start(["--voice"], "lesson")
    gate.set()
    r.thread.join(5)
    kinds = [e["kind"] for e in r.since(0)["events"]]
    assert kinds == ["start", "error", "error", "end"]
    with pytest.raises(R.Busy):
        r.send("hello")


# --- bezpieczeństwo HTTP ---

def test_binds_only_localhost(srv):
    assert srv.app is not None
    httpd = SV.serve(srv.app, 0)
    try:
        assert httpd.server_address[0] == "127.0.0.1"
    finally:
        httpd.server_close()


def test_foreign_host_header_rejected(srv):
    assert srv.get("/api/profiles", host="evil.example:80")[0] == 403
    assert srv.get("/", host=f"attacker.test:{srv.port}")[0] == 403


def test_post_requires_token_origin_and_json(srv):
    assert srv.post("/api/profiles", {"name": "x"}, headers={"X-Tutor-Token": "zly"})[0] == 403
    assert srv.post("/api/profiles", {"name": "x"}, headers={"Origin": "http://evil.example"})[0] == 403
    assert srv.post("/api/profiles", {"name": "x"}, headers={"Content-Type": "text/plain"})[0] == 415
    assert srv.req("PUT", "/api/profiles")[0] == 405
    c = http.client.HTTPConnection("127.0.0.1", srv.port, timeout=5)
    c.request("POST", "/api/profiles", body=b"x" * 10, headers={"Host": f"127.0.0.1:{srv.port}",
              "Content-Type": "application/json", "X-Tutor-Token": "T0K", "Content-Length": str(SV.MAX_BODY + 1)})
    assert c.getresponse().status == 413
    c.close()


def test_static_files_and_no_traversal(srv):
    code, html = srv.get("/")
    assert code == 200 and 'content="T0K"' in html and "__TOKEN__" not in html
    assert srv.get("/app.js")[0] == 200
    assert srv.get("/../server.py")[0] == 404
    assert srv.get("/%2e%2e/server.py")[0] == 404


def test_input_validation(srv):
    pid = make_profile(srv)
    assert srv.post("/api/profiles", {"name": ""})[0] == 400
    assert srv.post("/api/profiles", {"name": "x" * 41})[0] == 400
    assert srv.get("/api/home?pid=999")[0] == 400
    bad = [{"kind": "rm"}, {"kind": "chat", "args": {"topic": "nope"}}, {"kind": "chat", "args": {"custom": "x" * 81}},
           {"kind": "chat", "args": {"custom": "ask"}}, {"kind": "chat", "args": {"topic": "fd.cooking", "minutes": 7}},
           {"kind": "lesson", "args": {"skill": "--help"}}, {"kind": "exam", "args": {"path": "../x"}},
           {"kind": "drill", "args": {"target": "1; rm"}}, {"kind": "chat", "args": {"topic": "fd.cooking",
                                                                                      "correction": "loud"}}]
    for b in bad:
        code, r = srv.post("/api/session/start", {"pid": pid, **b})
        assert code == 400, (b, r)
    assert srv.post("/api/session/send", {"text": "a\nb"})[0] == 400
    assert srv.post("/api/session/send", {"text": "x" * 501})[0] == 400
    assert srv.post("/api/settings", {"pid": pid, "changes": {"speed": 9}})[0] == 400
    assert srv.post("/api/settings", {"pid": pid, "changes": {"chat_model": "evil:1b"}})[0] == 400


def test_custom_topic_cannot_become_a_flag(srv, xdg):
    pid = make_profile(srv)
    argv = SV.session_argv(SV.App(token="t", status=lambda: STATUS).api()[0], pid, "chat", {"custom": "--profile=9"})
    assert "--chat=--profile=9" in argv and argv.count(f"--profile={pid}") == 1


# --- trasy i sesje ---

def test_profiles_and_reports(srv):
    pid = make_profile(srv)
    code, r = srv.get("/api/profiles")
    assert code == 200 and r["profiles"][0]["name"] == "ann" and r["last"] == pid
    for path in ("home", "topics", "lessons", "placement", "progress", "weakspots", "achievements", "history",
                 "exams", "settings", "chats"):
        code, body = srv.get(f"/api/{path}?pid={pid}")
        assert code == 200, (path, body)
    assert srv.get("/api/system")[1]["ollama"] is True
    assert srv.get("/api/nope?pid=1")[0] == 404


def test_quick_chat_through_gui_saves_turns_and_no_mastery(srv, xdg):
    pid = make_profile(srv)
    assert srv.post("/api/session/start", {"pid": pid, "kind": "chat",
                                           "args": {"topic": "fd.cooking", "text_mode": True}})[0] == 200
    assert srv.post("/api/session/start", {"pid": pid, "kind": "lesson", "args": {}})[0] == 400   # jedna naraz
    srv.wait_for("tutor")
    srv.post("/api/session/send", {"text": "I like soup"})
    srv.post("/api/session/send", {"text": "Can we change the topic?"})
    time.sleep(0.3)
    srv.post("/api/session/stop", {})
    evs = srv.wait_end()
    kinds = [e["kind"] for e in evs]
    assert "you" in kinds and "tutor" in kinds and any(e["kind"] == "notice" and "nowy temat" in e["text"] for e in evs)
    conn = open_db(xdg / "data" / "english-ai-tutor" / "tutor.db")
    repo = Repo(conn)
    s = [x for x in repo.list_sessions(pid) if x["kind"] == "chat"][0]
    users = [t["text"] for t in repo.list_turns(pid, s["id"]) if t["role"] == "user"]
    assert users == ["I like soup", "Can we change the topic?"]
    assert s["status"] == "ended"
    assert not conn.execute("SELECT COUNT(*) FROM attempt WHERE profile_id=?", (pid,)).fetchone()[0]
    assert not [x for x in repo.list_skill_states(pid) if x["status"] in ("mastered", "verified")]
    conn.close()


def test_lesson_through_gui_records_attempts_and_resumes(srv, xdg):
    pid = make_profile(srv)
    code, les = srv.get(f"/api/lessons?pid={pid}")
    skill = les["suggestion"]["skill_id"]
    srv.post("/api/session/start", {"pid": pid, "kind": "lesson", "args": {"skill": skill, "text_mode": True}})
    evs = srv.wait_for("task")
    task = next(e for e in evs if e["kind"] == "task")
    assert task["index"] == 1 and any(e["kind"] == "goal" for e in evs)
    srv.post("/api/session/send", {"text": "zzz wrong answer"})
    time.sleep(0.3)
    srv.post("/api/session/stop", {})            # przerwanie w trakcie ćwiczeń = pauza
    srv.wait_end()
    conn = open_db(xdg / "data" / "english-ai-tutor" / "tutor.db")
    repo = Repo(conn)
    s = repo.find_open_session(pid)
    assert s and s["kind"] == "lesson" and s["status"] == "paused"
    n_before = conn.execute("SELECT COUNT(*) FROM attempt WHERE profile_id=?", (pid,)).fetchone()[0]
    conn.close()
    srv.post("/api/session/start", {"pid": pid, "kind": "lesson", "args": {"text_mode": True}})   # wznowienie
    evs = srv.wait_for("task")
    assert any("Wznawiam" in e.get("text", "") for e in evs)
    srv.post("/api/session/stop", {})
    srv.wait_end()
    conn = open_db(xdg / "data" / "english-ai-tutor" / "tutor.db")
    n_after = conn.execute("SELECT COUNT(*) FROM attempt WHERE profile_id=?", (pid,)).fetchone()[0]
    sessions = Repo(conn).list_sessions(pid)
    conn.close()
    assert n_after == n_before                      # wznowienie nie dubluje prób
    assert len([x for x in sessions if x["kind"] == "lesson"]) == 1


def test_profile_isolation_in_api(srv):
    a, b = make_profile(srv, "ann"), make_profile(srv, "bob")
    srv.post("/api/settings", {"pid": a, "changes": {"speed": 1.2}})
    assert srv.get(f"/api/settings?pid={b}")[1]["values"]["speed"] == 1.0
    assert srv.get(f"/api/settings?pid={a}")[1]["values"]["speed"] == 1.2


def test_session_error_reaches_gui(srv, monkeypatch):
    pid = make_profile(srv)
    srv.app.runner._run = lambda argv, **kw: cli.run(argv, **kw)   # prawdziwy dostawca -> brak Ollamy
    monkeypatch.setattr("tutor.llm.ollama.OllamaProvider.health", lambda self: False)
    srv.post("/api/session/start", {"pid": pid, "kind": "chat", "args": {"topic": "fd.cooking", "text_mode": True}})
    evs = srv.wait_end()
    assert any(e["kind"] == "error" and "Ollama" in e["text"] for e in evs)
