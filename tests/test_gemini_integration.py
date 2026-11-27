"""Opcjonalne Gemini per profil: klucz (magazyn sekretów / pamięć), zgoda, wybór modeli, test połączenia, fallback na
lokalny model, liczniki i dziennik. Bez sieci: atrapy klienta Gemini i magazynu sekretów; prawdziwego keyringa nie
dotykamy (monkeypatch `_backend`)."""
import json
import subprocess
from pathlib import Path

import pytest
from google.genai import errors

from tests.llm_fakes import FakeProvider
from tests.test_eval_runner import ERR, GOAL, NOW, turns
from tests.test_eval_runner import structured as plain_structured
from tests.test_gui import srv, xdg  # noqa: F401 - fixtury serwera GUI
from tests.voice_fakes import FakeTTS
from tutor.app import ai_models as AM
from tutor.app import settings as ST
from tutor.app.eval_runner import make_queue
from tutor.llm import keystore
from tutor.llm.base import CancelToken, LLMError, LLMUnavailable, Message, Reply, StreamInterrupted, Usage
from tutor.llm.gemini import GeminiProvider, classify_api_error
from tutor.llm.route import Budget, Routed
from tutor.pedagogy import content as C
from tutor.services.api import ServiceError, TutorAPI
from tutor.voice import audio as A
from tutor.voice.conversation import VoiceTutor

KEY = "AIzaTEST-not-a-real-key-0123456789"
KEY2 = "AIzaTEST-second-profile-key-987654"
MSG = [Message("user", "hi")]


class FakeKeyring:
    priority = 5

    def __init__(self):
        self.store = {}

    def set_password(self, s, u, p):
        self.store[(s, u)] = p

    def get_password(self, s, u):
        return self.store.get((s, u))

    def delete_password(self, s, u):
        self.store.pop((s, u))


@pytest.fixture
def kr(monkeypatch):
    k = FakeKeyring()
    monkeypatch.setattr(keystore, "_backend", lambda: k)
    keystore._memory.clear()
    yield k
    keystore._memory.clear()


@pytest.fixture
def pid(repo):
    return repo.create_profile("ann")


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def gem(replies=(), chunks=(), fail_after=None):
    return FakeProvider(name="gemini", model="gemini-x", external=True, replies=replies, chunks=chunks,
                        fail_after=fail_after)


def local(**kw):
    return FakeProvider(name="ollama", model="qwen3:8b", **kw)


def quota(reason="quota_minute", retry=None):
    return LLMUnavailable("limit", reason=reason, retry_after=retry)


# --- 1. bez klucza / domyślnie lokalnie ---------------------------------------------------------------------------
def test_new_profile_is_local_only_and_needs_no_key(repo, pid, kr):
    v = ST.effective(repo, pid)
    assert (v["gemini_enabled"], v["chat_provider"], v["eval_provider"]) == (False, "local", "local")
    r = AM.build(repo, pid, "conversation", local(replies=["hi"]), budget=Budget(5))
    assert r.primary is None and not r.external and r.chat(MSG).text == "hi"
    st = AM.status(repo, pid)
    assert st["key"] is None and st["consent_at"] is None and "AIza" not in json.dumps(st)


# --- 2. klucz: zapis, zastąpienie, usunięcie, izolacja, pamięć ---------------------------------------------------
def test_key_saved_in_keyring_not_db_and_never_returned(repo, conn, pid, kr, tmp_path):
    st = AM.save_key(repo, pid, KEY)
    assert st["saved"] == "keyring" and st["key"] == "keyring" and KEY not in json.dumps(st)
    ref = repo.get_settings(pid)["secret_ref"]
    assert kr.store == {("english-ai-tutor", f"gemini:{ref}"): KEY} and "ann" not in ref and str(pid) != ref
    dump = "\n".join(conn.iterdump())
    assert KEY not in dump
    assert not any(KEY.encode() in f.read_bytes() for f in tmp_path.rglob("*") if f.is_file())
    AM.save_key(repo, pid, KEY2)                                     # zastąpienie
    assert keystore.get(repo, pid) == KEY2
    AM.delete_key(repo, pid)
    assert keystore.get(repo, pid) is None and kr.store == {} and AM.status(repo, pid)["key"] is None


def test_keys_isolated_between_profiles_and_deleted_with_profile(repo, pid, kr):
    from tutor.app import profiles as PR
    other = repo.create_profile("bob")
    AM.save_key(repo, pid, KEY)
    AM.save_key(repo, other, KEY2)
    assert (keystore.get(repo, pid), keystore.get(repo, other)) == (KEY, KEY2)
    PR.delete(repo, other, "bob", make_backup=False)
    assert keystore.get(repo, pid) == KEY and list(kr.store.values()) == [KEY]
    new = repo.create_profile("carl")                                # nowy profil nie dziedziczy klucza
    assert keystore.get(repo, new) is None


def test_memory_only_when_no_secure_store(repo, pid, monkeypatch):
    monkeypatch.setattr(keystore, "_backend", lambda: None)
    keystore._memory.clear()
    st = AM.save_key(repo, pid, KEY)
    assert st["saved"] == "memory" and st["persistent_store"] is False and keystore.get(repo, pid) == KEY
    keystore._memory.clear()                                         # „restart aplikacji”
    assert keystore.get(repo, pid) is None


def test_plaintext_keyring_backend_rejected(monkeypatch):
    import keyring

    class PlaintextKeyring:
        priority = 5
    monkeypatch.setattr(keyring, "get_keyring", lambda: PlaintextKeyring())
    assert keystore._backend() is None


@pytest.mark.parametrize("bad", ["", "  ", "a b", "x" * 201])
def test_bad_key_rejected_without_echo(repo, pid, kr, bad):
    with pytest.raises(ValueError) as e:
        AM.save_key(repo, pid, bad)
    assert bad.strip() == "" or bad not in str(e.value)


# --- 3. zgoda i wybór modeli ---------------------------------------------------------------------------------------
def test_gemini_selection_requires_consent_key_and_model(repo, pid, kr):
    on = {"gemini_enabled": True, "chat_provider": "gemini", "gemini_chat_model": "gemini-x"}
    with pytest.raises(ST.SettingError, match="zgod"):
        ST.update(repo, pid, on)
    AM.set_consent(repo, pid, True)
    with pytest.raises(ST.SettingError, match="klucz"):
        ST.update(repo, pid, on)
    AM.save_key(repo, pid, KEY)
    with pytest.raises(ST.SettingError, match="model"):
        ST.update(repo, pid, {**on, "gemini_chat_model": ""})
    v = ST.update(repo, pid, on)
    assert (v["chat_provider"], v["eval_provider"]) == ("gemini", "local")   # ocena niezależna, nadal lokalna
    with pytest.raises(ST.SettingError):
        ST.update(repo, pid, {"gemini_chat_model": "../etc"})
    AM.set_consent(repo, pid, False)                                 # wycofanie zgody = tylko lokalnie
    v = ST.effective(repo, pid)
    assert (v["gemini_enabled"], v["chat_provider"]) == (False, "local")


def _enable(repo, pid, chat="gemini-x", ev=None):
    AM.set_consent(repo, pid, True)
    AM.save_key(repo, pid, KEY)
    ch = {"gemini_enabled": True, "chat_provider": "gemini", "gemini_chat_model": chat}
    if ev:
        ch |= {"eval_provider": "gemini", "gemini_eval_model": ev}
    ST.update(repo, pid, ch)


def test_build_uses_profile_choice_per_role(repo, pid, kr):
    _enable(repo, pid, "gemini-x")
    b = Budget(10)
    chat = AM.build(repo, pid, "conversation", local(), budget=b)
    ev = AM.build(repo, pid, "evaluation", local(), budget=b)
    assert isinstance(chat.primary, GeminiProvider) and chat.primary.model == "gemini-x" and chat.external
    assert ev.primary is None and not ev.external and AM.chosen(repo, pid) == {"chat": "gemini-x", "eval": "local"}
    assert KEY not in repr(chat) and KEY not in repr(chat.primary)


# --- 4. test połączenia --------------------------------------------------------------------------------------------
class TP:
    def __init__(self, models=("gemini-3.5-flash-lite", "gemini-x"), list_exc=None, ping_exc=None):
        self.models, self.list_exc, self.ping_exc, self.pinged = list(models), list_exc, ping_exc, []

    def __call__(self, model, key, timeout):
        assert key == KEY
        self.model = model
        return self

    def list_text_models(self):
        if self.list_exc:
            raise self.list_exc
        return self.models

    def ping(self):
        if self.ping_exc:
            raise self.ping_exc
        self.pinged.append(self.model)
        return Reply("OK", Usage(5, 1, latency_ms=120), "gemini", self.model)


def test_connection_steps_and_messages(repo, pid, kr):
    assert AM.test_connection(repo, pid, "gemini-x", make=TP())["code"] == "no_key"
    AM.save_key(repo, pid, KEY)
    r = AM.test_connection(repo, pid, None, make=(t := TP()))
    assert r["code"] == "pick" and not r["ok"] and t.pinged == [] and r["candidates"] == ["gemini-3.5-flash-lite"]
    r = AM.test_connection(repo, pid, "gemini-x", make=(t := TP()))
    assert r["ok"] and r["message"].startswith("Połączenie z Gemini działa") and t.pinged == ["gemini-x"]
    assert AM.usage(repo, pid)["requests_total"] == 1               # test liczy się do licznika aplikacji
    assert AM.test_connection(repo, pid, "gemini-4-hydrogen", make=TP())["message"] == "Model niedostępny."
    bad = classify_api_error(400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}})
    assert AM.test_connection(repo, pid, "gemini-x", make=TP(list_exc=bad))["message"] == "Nieprawidłowy klucz API."
    lim = classify_api_error(429, {"error": {"status": "RESOURCE_EXHAUSTED"}})
    assert AM.test_connection(repo, pid, "gemini-x", make=TP(ping_exc=lim))["message"] == "Osiągnięto limit API."
    net = LLMUnavailable("x", reason="network")
    assert AM.test_connection(repo, pid, "gemini-x", make=TP(list_exc=net))["message"] == "Błąd połączenia."


@pytest.mark.parametrize("code,details,reason,retry", [
    (400, {"error": {"details": [{"reason": "API_KEY_INVALID"}]}}, "auth", None),
    (403, {"error": {"status": "PERMISSION_DENIED"}}, "auth", None),
    (404, {"error": {"status": "NOT_FOUND"}}, "model", None),
    (429, {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerDayPerProjectPerModel-FreeTier"}]}]}},
     "quota_day", None),
    (429, {"error": {"details": [{"violations": [{"quotaId": "GenerateRequestsPerMinutePerProjectPerModel"}]},
                                 {"retryDelay": "37s"}]}}, "quota_minute", 37.0),
    (429, {"error": {"status": "RESOURCE_EXHAUSTED"}}, "quota", None),       # przyczyna nieznana: nie zgadujemy
    (503, {"error": {}}, "server", None),
    (400, {"error": {"status": "INVALID_ARGUMENT"}}, "bad_request", None),
])
def test_api_error_classification(code, details, reason, retry):
    e = classify_api_error(code, details)
    assert (e.reason, e.retry_after) == (reason, retry)


def test_provider_maps_sdk_errors_without_key(monkeypatch):
    class M:
        def generate_content(self, **kw):
            raise errors.ClientError(400, {"error": {"message": f"API key not valid {KEY}",
                                                     "details": [{"reason": "API_KEY_INVALID"}]}})
    from types import SimpleNamespace as NS
    p = GeminiProvider("gemini-x", KEY, client=NS(models=M()))
    with pytest.raises(LLMError) as e:
        p.chat(MSG)
    assert e.value.reason == "auth" and KEY not in str(e.value)


# --- 5. fallback ---------------------------------------------------------------------------------------------------
def test_429_falls_back_once_cools_down_then_retries(repo):
    clock, notes, evs = Clock(), [], []
    g, lo = gem(replies=[quota(retry=30), "gem-again"]), local(replies=["l1", "l2"])
    r = Routed("conversation", lo, g, budget=Budget(10), notify=notes.append, on_event=evs.append, clock=clock)
    assert r.chat(MSG).text == "l1" and r.chat(MSG).text == "l2"
    assert len(g.calls) == 1 and len(notes) == 1 and "lokalnie" in notes[0]   # bez ponowień w trakcie awarii
    assert r.fallbacks == 1 and r.model == "qwen3:8b"
    clock.t = 31
    assert r.chat(MSG).text == "gem-again" and len(g.calls) == 2 and "znów" in notes[-1]
    assert [e["provider"] for e in evs] == ["gemini", "ollama", "ollama", "gemini"]
    assert evs[1]["fallback"] and evs[1]["reason"] == "quota_minute" and evs[0]["status"] == "error"


@pytest.mark.parametrize("reason", ["auth", "model", "quota_day", "consent"])
def test_permanent_errors_stay_local_until_manual_restore(reason):
    clock, notes = Clock(), []
    g = gem(replies=[LLMError("x", reason=reason), "back"])
    r = Routed("conversation", local(replies=["l"] * 5), g, notify=notes.append, clock=clock)
    r.chat(MSG)
    clock.t = 10_000
    r.chat(MSG)
    assert len(g.calls) == 1 and len(notes) == 1
    if reason in ("auth", "model", "consent"):
        assert "Popraw" in notes[0]                                  # fallback nie ukrywa, że trzeba naprawić klucz
    assert r.restore() and r.chat(MSG).text == "back"


def test_timeout_and_network_fall_back():
    for reason in ("timeout", "network", "server"):
        r = Routed("conversation", local(replies=["l"]), gem(replies=[LLMUnavailable("x", reason=reason)]))
        assert r.chat(MSG).text == "l"


def test_both_down_is_a_clear_error_not_a_fake_reply():
    r = Routed("conversation", local(replies=[LLMUnavailable("ollama down")]), gem(replies=[quota()]))
    with pytest.raises(LLMError) as e:
        r.chat(MSG)
    assert "niedostępne" in e.value.user_message and "nie została wygenerowana" in e.value.user_message


def test_session_request_limit_then_local(repo):
    b, notes = Budget(2), []
    r = Routed("conversation", local(replies=["l"]), gem(replies=["g1", "g2", "g3"]), budget=b, notify=notes.append)
    assert [r.chat(MSG).text for _ in range(3)] == ["g1", "g2", "l"]
    assert b.requests == 2 and "limit żądań" in notes[0]


def test_budget_shared_between_roles_and_eval_independent():
    b = Budget(1)
    chat = Routed("conversation", local(replies=["lc"]), gem(replies=[quota()]), budget=b)
    ev = Routed("evaluation", local(replies=["le"]), gem(replies=["ge"]), budget=b)
    chat.chat(MSG)                                   # awaria rozmowy nie przełącza oceny (osobny stan)…
    assert chat.model == "qwen3:8b" and ev.model == "gemini-x"
    assert ev.chat(MSG).text == "le"                 # …ale wspólny limit żądań na sesję obowiązuje obie role


def test_consent_revoked_midsession_stops_gemini(repo, pid, kr):
    _enable(repo, pid)
    r = AM.build(repo, pid, "conversation", local(replies=["l"]), budget=Budget(5))
    r.primary = gem(replies=["g"])
    repo.set_consent(pid, False)
    assert r.chat(MSG).text == "l" and r.primary.calls == [] and r.down_reason == "consent"


def test_stream_falls_back_before_first_chunk_only():
    g = FakeProvider(name="gemini", model="gemini-x", external=True, chunks=["a"], fail_after=0)
    r = Routed("conversation", local(chunks=["Local ", "reply."]), g)
    s = r.stream(MSG, cancel=CancelToken())
    assert "".join(s) == "Local reply." and r.down_reason is not None
    g2 = FakeProvider(name="gemini", model="gemini-x", external=True, chunks=["Gem ", "par", "tial"], fail_after=2)
    lo = local(chunks=["NEVER"])
    r2 = Routed("conversation", lo, g2)
    s2 = r2.stream(MSG, cancel=CancelToken())
    got = []
    with pytest.raises(StreamInterrupted):
        for c in s2:
            got.append(c)
    assert got == ["Gem ", "par"] and lo.calls == []                 # bez doklejania drugiej odpowiedzi
    assert r2.model == "qwen3:8b"                                    # następna tura lokalnie


def test_voice_tutor_keeps_history_and_single_reply_on_fallback(repo):
    pid = repo.create_profile("v")
    sid = repo.start_session(pid, "chat")
    g = FakeProvider(name="gemini", model="gemini-x", external=True, chunks=["x"], fail_after=0)
    lo = local(chunks=["Sure. ", "Tell me more."])
    r = Routed("conversation", lo, g)
    t = VoiceTutor(repo, pid, sid, r, FakeTTS(), A.SimSink())
    t.respond("I like tea")
    t.respond("And coffee")
    rows = [(x["role"], x["text"]) for x in repo.list_turns(pid, sid)]
    assert rows == [("user", "I like tea"), ("assistant", "Sure. Tell me more."), ("user", "And coffee"),
                    ("assistant", "Sure. Tell me more.")]
    second = lo.calls[-1]
    assert any("I like tea" in m.content for m in second)            # kontekst rozmowy przechodzi do Qwen3
    assert len(g.calls) == 1


# --- 6. ocena: te same walidatory, brak podwójnych zapisów, model faktycznie użyty ---------------------------------
class EvalProv:
    def __init__(self, name, model, external, bad=False, fail=None):
        self.name, self.model, self.external, self.bad, self.fail, self.calls = name, model, external, bad, fail, []

    def chat(self, messages, **kw):
        self.calls.append(1)
        if self.fail:
            raise self.fail
        if self.bad:
            return Reply('{"u": [{"bad": 1}]}', Usage(1, 1), self.name, self.model)
        n = sum(1 for ln in messages[-1].content.splitlines() if ln[:1].isdigit() and ln[1:3] == ": ")
        return Reply(json.dumps({"u": [{"i": i, "o": [ERR], "t": [], "cm": "ok", "cq": "I goed"} for i in range(n)]}),
                     Usage(1, 1), self.name, self.model)

    def health(self):
        return True


@pytest.mark.parametrize("gemini", [dict(bad=True), dict(fail=LLMUnavailable("x", reason="quota"))])
def test_eval_invalid_or_failed_gemini_scored_once_locally(repo, gemini):
    from tutor.llm.structured import structured
    pack = C.load("en")
    pid = repo.create_profile("e")
    sid = repo.start_session(pid, "chat")
    g = EvalProv("gemini", "gemini-x", True, **gemini)
    lo = EvalProv("ollama", "qwen3:8b", False)
    r = Routed("evaluation", lo, g)
    q = make_queue(repo, pack, r, structured, profile_id=pid, session_id=sid, goals={GOAL: "past"},
                   clock=lambda: NOW, model="gemini-x")
    for p in turns(repo, pid, sid, 1):
        q.submit(p)
    assert q.drain(CancelToken()) == 1
    rows = repo.conn.execute("SELECT model, status FROM observation WHERE profile_id=?", (pid,)).fetchall()
    assert len(rows) == 1 and rows[0][0] == "qwen3:8b"             # jeden zapis, model faktycznie oceniający


def test_eval_gemini_result_goes_through_same_validators(repo):
    """Gemini nie omija bramek: obserwacja to sugestia (`assessment` + mastery bez zmian), nie potwierdzony błąd."""
    pack = C.load("en")
    assert pack.rubric.correction is not None
    pid = repo.create_profile("e2")
    sid = repo.start_session(pid, "chat")
    r = Routed("evaluation", EvalProv("ollama", "qwen3:8b", False), EvalProv("gemini", "gemini-x", True))
    q = make_queue(repo, pack, r, plain_structured, profile_id=pid, session_id=sid, goals={GOAL: "past"},
                   clock=lambda: NOW, model="gemini-x")
    for p in turns(repo, pid, sid, 1):
        q.submit(p)
    q.drain(CancelToken())
    models = {m for (m,) in repo.conn.execute("SELECT model FROM observation WHERE profile_id=?", (pid,))}
    assert models == {"gemini-x"}
    assert not repo.conn.execute("SELECT 1 FROM skill_state WHERE profile_id=? AND mastered_at IS NOT NULL",
                                 (pid,)).fetchall()


# --- 7. dziennik i liczniki ----------------------------------------------------------------------------------------
def test_llm_events_and_usage_logged_without_secrets(repo, pid, kr):
    _enable(repo, pid)
    r = AM.build(repo, pid, "conversation", local(replies=["l"]), budget=Budget(5), prompt="conversation.v1")
    r.primary = gem(replies=["g", quota("quota_day")])
    r.chat(MSG)
    r.chat(MSG)
    ev = [json.loads(d) for (d,) in repo.conn.execute(
        "SELECT data_json FROM app_event WHERE profile_id=? AND kind='log.llm' ORDER BY id", (pid,))]
    assert [(e["provider"], e["status"], e.get("fallback")) for e in ev] == [
        ("gemini", "ok", False), ("gemini", "error", False), ("ollama", "ok", True)]
    assert ev[0]["requested_model"] == "gemini-x" and ev[0]["prompt"] == "conversation.v1" and "latency_ms" in ev[0]
    assert ev[0]["in_tokens"] == 10 and ev[2]["reason"] == "quota_day"
    u = AM.usage(repo, pid)
    assert u["requests_total"] == 2 and "nie stan konta Google" in u["note"]
    cost = repo.conn.execute("SELECT cost_usd FROM llm_usage WHERE profile_id=?", (pid,)).fetchall()
    assert all(c is None for (c,) in cost)                          # koszt nieznany ≠ zero
    assert KEY not in json.dumps(ev)


# --- 8. GUI / API ---------------------------------------------------------------------------------------------------
def test_api_never_returns_key_and_settings_open_makes_no_calls(repo, pid, kr, monkeypatch):
    calls = []
    monkeypatch.setattr(AM, "_provider", lambda *a: calls.append(a))
    api = TutorAPI(repo)
    out = api.ai_save_key(pid, KEY)
    for x in (out, api.ai_models(pid), api.settings(pid)):
        assert KEY not in json.dumps(x, default=str)
    assert calls == []                                               # otwarcie ustawień nie łączy się z Google
    with pytest.raises(ServiceError) as e:
        api.ai_save_key(pid, "with space " + KEY)
    assert KEY not in str(e.value)


def test_gui_routes_hide_key(srv, kr):  # noqa: F811 - fixtura z test_gui
    _, p = srv.post("/api/profiles", {"name": "g"})
    code, r = srv.post("/api/ai_models/key", {"pid": p["id"], "key": KEY})
    assert code == 200 and r["key"] == "keyring" and KEY not in json.dumps(r)
    code, r = srv.get(f"/api/ai_models?pid={p['id']}")
    assert code == 200 and KEY not in json.dumps(r) and "consent_text" in r
    code, r = srv.post("/api/ai_models/key", {"pid": p["id"], "key": 5})
    assert code == 400
    code, r = srv.post("/api/ai_models/key", {"pid": p["id"], "key": KEY}, headers={"X-Tutor-Token": "zly"})
    assert code == 403
    code, r = srv.post("/api/ai_models/key_delete", {"pid": p["id"]})
    assert code == 200 and r["key"] is None


def test_no_secrets_in_repository():
    root = Path(__file__).resolve().parents[1]
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True).stdout.split()
    import re
    pat = re.compile(rb"AIza[0-9A-Za-z_\-]{35}")
    hits = [f for f in files if (root / f).is_file() and pat.search((root / f).read_bytes())]
    assert hits == []


def test_cli_chat_with_gemini_429_continues_locally_and_evaluates_once(conn, repo, kr, monkeypatch, tmp_path):
    """Pełna sesja Quick Chat (tryb tekstowy): Gemini rozmowy i oceny zwraca 429 → jedna informacja na rolę, rozmowa
    i ocena lokalnie, każda tura zapisana raz, `/gemini` przywraca próbę Gemini, log.llm z modelem użytym."""
    from tests.voice_fakes import Lines
    from tutor.voice import cli as CLI
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    pid = repo.create_profile("gem")
    _enable(repo, pid, "gemini-x", ev="gemini-x")
    chat_local = local(chunks=["Sure. ", "Tell me more."])
    eval_local = EvalProv("ollama", "qwen3:8b", False)
    gems = []

    class Gem:
        name, external = "gemini", True

        def __init__(self, model, key, timeout, *a):
            assert key == KEY
            self.model, self.calls = model, 0
            gems.append(self)

        def chat(self, *a, **k):
            self.calls += 1
            raise quota()

        def stream(self, *a, **k):
            self.calls += 1
            raise quota()

        def health(self):
            return True
    monkeypatch.setattr(AM, "_provider", Gem)
    monkeypatch.setattr(CLI, "_chat_provider", lambda a: chat_local)
    monkeypatch.setattr(CLI, "build_provider", lambda role, *a: eval_local)
    out = []
    code = CLI.run(["--voice", "--profile", "gem", "--chat=custom travel", "--no-audio"],
                   tts=FakeTTS(), lines=Lines("I goed home yesterday", "I like tea", "/gemini", "And coffee", "q"),
                   out=out.append, db=conn)
    assert code == 0
    notes = [o for o in out if "Gemini jest chwilowo niedostępny" in o]
    # po jednej informacji na rolę i awarię: 1. awaria + ponowna po ręcznym `/gemini`
    assert sum("Rozmowa" in n for n in notes) == 2 and sum("Ocena" in n for n in notes) == 2
    assert [g.calls for g in gems] == [2, 2]                                       # bez pętli ponowień
    assert any("Gemini przywrócone" in o for o in out)
    sid = repo.conn.execute("SELECT id FROM session WHERE profile_id=? ORDER BY id DESC", (pid,)).fetchone()[0]
    users = [t["text"] for t in repo.list_turns(pid, sid) if t["role"] == "user"]
    assert users == ["I goed home yesterday", "I like tea", "And coffee"]          # „/gemini” nie trafia do rozmowy
    assistants = [t for t in repo.list_turns(pid, sid) if t["role"] == "assistant"]
    assert len(assistants) == 4                                     # otwarcie + 3 odpowiedzi, bez duplikatów
    obs = repo.conn.execute("SELECT turn_id, model FROM observation WHERE profile_id=?", (pid,)).fetchall()
    assert len(obs) == len({o[0] for o in obs}) == 3 and {o[1] for o in obs} == {"qwen3:8b"}   # ocena raz, lokalnie
    ev = [json.loads(d) for (d,) in repo.conn.execute(
        "SELECT data_json FROM app_event WHERE profile_id=? AND kind='log.llm'", (pid,))]
    assert {e["role"] for e in ev} == {"conversation", "evaluation"}
    assert all(e["requested_model"] == "gemini-x" for e in ev)
    meta = json.loads(repo.conn.execute("SELECT model_json FROM session WHERE id=?", (sid,)).fetchone()[0])
    assert meta["ai_models"] == {"chat": "gemini-x", "eval": "gemini-x"}


def test_bench_cap_has_no_fallback():
    from bench.speaking import Capped
    c = Capped(gem(replies=["a", "b"]), 1)
    assert c.chat(MSG).text == "a"
    with pytest.raises(LLMError) as e:
        c.chat(MSG)
    assert e.value.reason == "limit" and c.n == 1


def test_missing_sdk_means_local_with_message(repo, pid, kr, monkeypatch):
    _enable(repo, pid)
    monkeypatch.setattr(AM, "sdk_available", lambda: False)
    notes = []
    r = AM.build(repo, pid, "conversation", local(), budget=Budget(5), notify=notes.append)
    assert r.primary is None and "pip install" in notes[0]
    assert AM.test_connection(repo, pid, "gemini-x")["code"] == "no_sdk"
