"""Quick Chat, generator tematów, ustawienia: bez diagnozy, bez celu lekcji, bez mastery."""
from datetime import UTC, datetime, timedelta

import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tutor.app import quickchat as QC
from tutor.app import settings as ST
from tutor.app import topics as T


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


# --- generator tematów ---
def test_catalog_is_diverse_and_local():
    c = T.catalog()
    assert len(c) >= 25 and len({t["category"] for t in c.values()}) >= 6
    assert all(len(t["q"]) > 15 for t in c.values())


def test_suggestions_come_from_different_categories(repo):
    pid = repo.create_profile("ann")
    s = T.suggest(repo, pid, 4, seed=1)
    assert len(s) == 4 and len({t["category"] for t in s}) == 4


def test_reroll_gives_other_topics_and_history_rotates(repo):
    pid = repo.create_profile("ann")
    a = T.suggest(repo, pid, 4, seed=1)
    b = T.suggest(repo, pid, 4, seed=2, exclude={t["id"] for t in a})
    assert not {t["id"] for t in a} & {t["id"] for t in b}
    seen = set()
    for _ in range(6):                                  # 6 rozmów: żaden temat nie powtarza się z ostatnich użyć
        t = T.suggest(repo, pid, 1)[0]
        assert t["id"] not in seen
        seen.add(t["id"])
        QC.start(repo, pid, t)
    assert T.history(repo, pid)[-6:] == [x for x in T.history(repo, pid)[-6:]] and len(set(T.history(repo, pid))) == 6


def test_least_recently_used_category_comes_first(repo):
    pid = repo.create_profile("ann")
    for tid in ("fd.favorite", "fd.cooking", "tr.dream"):
        QC.start(repo, pid, T.get(tid))
    cats = [t["category"] for t in T.suggest(repo, pid, 3, seed=5)]
    assert "food" not in cats and "travel" not in cats


def test_profiles_have_separate_history(repo):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    QC.start(repo, a, T.get("fd.favorite"))
    assert T.history(repo, b) == [] and T.history(repo, a) == ["fd.favorite"]


def test_custom_topic_is_not_in_rotation_history(repo):
    pid = repo.create_profile("ann")
    QC.start(repo, pid, T.custom("my garden"))
    assert T.history(repo, pid) == []
    assert "garden" in QC.history(repo, pid)[0]["topics"][0]


# --- CLI ---
def test_cli_chat_without_diagnosis_with_chosen_topic_no_mastery(env):
    conv = FakeProvider(chunks=["Sounds nice. ", "Tell me more."])
    code, out = env.go(Gated({}, "2", "I like cooking pasta", "q"), ["--no-audio", "--chat"], llm=conv, ev=EvalProv())
    text = "\n".join(out)
    assert code == 0 and "Wybierz temat" in text and "Quick Chat — temat:" in text
    s = env.repo.list_sessions(env.pid)
    assert [x["kind"] for x in s] == ["chat"] and s[0]["status"] in ("ended", "paused")   # paused: oczekuje ocena
    assert "Current topic" in conv.calls[0][0].content                     # temat w prompcie
    assert conv.calls[0][1].role == "assistant"                            # pytanie otwierające w historii
    assert env.repo.list_skill_states(env.pid) == [] and env.repo.list_competence(env.pid) == []
    assert env.repo.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0] == 0


def test_cli_chat_reroll_then_custom_topic(env):
    code, out = env.go(Gated({}, "r", "my cat Tom", "hello", "q"), ["--no-audio", "--chat"],
                       llm=FakeProvider(chunks=["Nice. "]), ev=EvalProv())
    text = "\n".join(out)
    assert text.count("Wybierz temat") == 2 and "temat: my cat Tom" in text


def test_cli_chat_topic_argument_and_change_topic_midway(env):
    conv = FakeProvider(chunks=["Ok. "])
    code, out = env.go(Gated({}, "hi", "can we change the topic please", "q"), ["--no-audio", "--chat", "fd.favorite"],
                       llm=conv, ev=EvalProv())
    plan = env.repo.get_session_plan(env.pid, env.repo.list_sessions(env.pid)[0]["id"])
    assert len(plan["topics"]) == 2 and plan["topic"]["id"] != "fd.favorite" and any("nowy temat" in x for x in out)
    assert plan["topic"]["pl"] in conv.calls[1][0].content                  # nowy temat w kolejnej odpowiedzi


def test_cli_chat_cancel_creates_no_session(env):
    code, _ = env.go(Gated({}, "q"), ["--no-audio", "--chat"], ev=EvalProv())
    assert code == 0 and env.repo.list_sessions(env.pid) == []


def test_cli_chat_time_limit_ends_session(repo, conn, monkeypatch):
    env = Env(repo, conn)
    monkeypatch.setattr(QC, "time_up", lambda *a, **k: True)
    code, out = env.go(Gated({}, "hello"), ["--no-audio", "--chat", "fd.favorite", "--minutes", "5"],
                       llm=FakeProvider(chunks=["Ok. "]), ev=EvalProv())
    assert any("Czas rozmowy minął" in x for x in out) and repo.list_sessions(env.pid)[0]["status"] == "ended"


def test_active_seconds_caps_idle_gaps(repo):
    pid = repo.create_profile("ann")
    sid = QC.start(repo, pid, T.get("fd.favorite"), 10)
    base = datetime(2026, 1, 1, tzinfo=UTC)
    for k, off in enumerate([0, 30, 60 * 60]):          # po 30 s, potem godzina przerwy
        repo.conn.execute("INSERT INTO turn(session_id,profile_id,role,text,created_at) VALUES (?,?,?,?,?)",
                          (sid, pid, "user", "x", (base + timedelta(seconds=off)).strftime("%Y-%m-%dT%H:%M:%S.000Z")))
    assert QC.active_seconds(repo, pid, sid) == 30 + 120


def test_chat_interrupt_resumes_same_session(env):
    env.go(Gated({}, "1", "hello", "q"), ["--no-audio", "--chat"], llm=FakeProvider(chunks=["Ok. "]), ev=EvalProv())
    sid = env.repo.list_sessions(env.pid)[0]["id"]
    env.repo.conn.execute("UPDATE session SET status='paused', ended_at=NULL WHERE id=?", (sid,))
    code, out = env.go(Gated({}, "again", "q"), ["--no-audio", "--chat"], llm=FakeProvider(chunks=["Ok. "]),
                       ev=EvalProv())
    assert "Wznawiam sesję" in "\n".join(out) and len(env.repo.list_sessions(env.pid)) == 1
    assert [t["role"] for t in env.repo.list_turns(env.pid, sid)].count("assistant") >= 2


# --- ustawienia ---
def test_settings_defaults_update_and_validation(repo):
    pid = repo.create_profile("ann")
    e = ST.effective(repo, pid)
    assert e["target_lang"] == "en" and e["correction"] == "summary" and e["mic_mode"] == "ptt"
    e = ST.update(repo, pid, {"speed": "1.2", "correction": "periodic", "session_minutes": "45", "tts_voice": "bf_emma",
                              "allow_unreviewed": "false", "conversation_mode": "quick_chat"})
    assert e["speed"] == 1.2 and e["correction"] == "periodic" and e["session_minutes"] == 45
    assert repo.get_profile(pid)["correction_style"] == "periodic" and repo.get_profile(pid)["daily_minutes"] == 45
    assert repo.get_profile(pid)["allow_unreviewed_practice"] == 0 and e["conversation_mode"] == "quick_chat"


@pytest.mark.parametrize("bad", [{"speed": 9}, {"correction": "wild"}, {"nope": 1}, {"session_minutes": 7},
                                 {"target_lang": "xx"}, {"tts_voice": " "}])
def test_invalid_settings_rejected_atomically(repo, bad):
    pid = repo.create_profile("ann")
    with pytest.raises(ST.SettingError):
        ST.update(repo, pid, {"speed": 1.1, **bad})
    assert ST.effective(repo, pid)["speed"] == 1.0                      # nic nie zapisano


def test_settings_isolated_per_profile(repo):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    ST.update(repo, a, {"speed": 0.8})
    assert ST.effective(repo, b)["speed"] == 1.0


def test_change_topic_instruction_applies_to_one_reply_only(env):
    conv = FakeProvider(chunks=["Ok. "])
    env.go(Gated({}, "hi", "can we change the topic please", "and now?", "q"), ["--no-audio", "--chat", "fd.favorite"],
           llm=conv, ev=EvalProv())
    plan = env.repo.get_session_plan(env.pid, env.repo.list_sessions(env.pid)[0]["id"])
    q = plan["topic"]["q"]
    assert q in conv.calls[1][0].content and q not in conv.calls[2][0].content and q not in conv.calls[0][0].content
