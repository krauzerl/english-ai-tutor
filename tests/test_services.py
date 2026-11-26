"""Warstwa usług (fasada pod GUI): JSON-owalność, izolacja profili, brak ekranów bez danych, ustawienia w CLI, historia."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tests.test_journal import chat_on
from tutor.app import history as H
from tutor.services.api import ServiceError, TutorAPI

NOW = datetime.now(UTC)


@pytest.fixture
def api(repo):
    return TutorAPI(repo, now=lambda: NOW)


def js(x):
    return json.loads(json.dumps(x))                               # musi być serializowalne


def test_every_read_endpoint_is_json_serialisable_for_new_profile(api):
    pid = api.create_profile("ann")["id"]
    for call in (api.home, api.lesson_suggestion, api.lesson_catalog, api.placement_info, api.progress, api.weakspots,
                 api.achievements, api.history, api.exam_paths, api.settings, api.chat_history):
        assert js(call(pid)) is not None or call(pid) is None
    assert js(api.chat_topics(pid))


def test_new_profile_can_learn_and_chat_without_placement(api):
    pid = api.create_profile("ann")["id"]
    h = api.home(pid)
    assert h["placement_done"] is False and h["suggested_lesson"] is not None and h["due_reviews"] == 0
    assert api.placement_info(pid)["voluntary"] is True
    cat = api.lesson_catalog(pid)
    assert cat and all(set(c) >= {"skill_id", "cefr", "can_do_pl"} for c in cat)
    start = api.chat_start(pid, topic_id=api.chat_topics(pid)[0]["id"], minutes=10)
    assert start["opener"] and api.chat_history(pid)[0]["session_id"] == start["session_id"]


def test_chat_start_validation_and_history_opener(api, repo):
    pid = api.create_profile("ann")["id"]
    with pytest.raises(ServiceError):
        api.chat_start(pid)
    with pytest.raises(ServiceError):
        api.chat_start(pid, custom="x", minutes=7)
    s = api.chat_start(pid, custom="my garden")
    assert [t["role"] for t in repo.list_turns(pid, s["session_id"])] == ["assistant"]


def test_profile_isolation_across_endpoints(api, repo):
    a, b = api.create_profile("a")["id"], api.create_profile("b")["id"]
    chat_on(repo, a, NOW)
    api.achievements(a)
    assert api.history(b)["sessions"] == [] and api.achievements(b)["earned"] == 0 and api.chat_history(b) == []


def test_unknown_profile_is_a_service_error(api):
    with pytest.raises(ServiceError):
        api.home(999)


def test_settings_roundtrip_and_validation(api):
    pid = api.create_profile("ann")["id"]
    s = api.settings(pid)
    assert s["values"]["speed"] == 0.9 and "choices" in s["schema"]["correction"]   # F7: komfortowe tempo
    assert api.update_settings(pid, {"speed": "slow"})["speed"] == 0.8
    assert api.update_settings(pid, {"speed": 1.25})["speed"] == 1.25
    with pytest.raises(ServiceError):
        api.update_settings(pid, {"speed": 5})


def test_exam_paths_expose_limits_and_no_points(api):
    pid = api.create_profile("ann")["id"]
    p = api.exam_paths(pid)[0]
    assert p["id"] == "e8_english" and p["official"]["status"] == "confirm_in_cke_informator"
    assert p["readiness"]["limits"] and p["speaking_topics"]
    assert "points" not in json.dumps(p["readiness"]).lower()


def test_history_comes_from_records_only(api, repo):
    pid = api.create_profile("ann")["id"]
    assert api.history(pid)["totals"] == {"sessions": 0, "sessions_by_kind": {}, "study_seconds": 0,
                                          "lessons_completed": 0, "reviews_done": 0, "user_turns": 0}
    chat_on(repo, pid, NOW - timedelta(days=1))
    h = api.history(pid)
    assert h["totals"]["sessions"] == 1 and h["totals"]["user_turns"] == 3 and h["totals"]["study_seconds"] == 120
    assert h["sessions"][0]["title"] and H.skill_timeline(repo, pid, "en.gram.to_be_present") == []


# --- CLI: ustawienia i historia ---
def test_cli_set_and_history(repo, conn):
    env = Env(repo, conn)
    code, out = env.go(Gated({}), ["--set", "speed=1.2", "--set", "correction=periodic"], ev=EvalProv())
    assert code == 0 and any("speed = 1.2" in x for x in out)
    assert repo.get_profile(env.pid)["correction_style"] == "periodic"
    code, out = env.go(Gated({}), ["--set", "speed=9"], ev=EvalProv())
    assert any("Błąd ustawień" in x for x in out)
    code, out = env.go(Gated({}), ["--history"], ev=EvalProv())
    assert code == 0 and any("Historia nauki" in x for x in out)


def test_cli_explicit_option_wins_over_profile_setting(repo, conn):
    from tutor.voice.cli import _apply_settings, parse
    pid = repo.create_profile("ann")
    TutorAPI(repo).update_settings(pid, {"speed": 0.8, "tts_voice": "bf_isabella"})
    p = repo.get_profile(pid)
    a = parse(["--voice", "--speed", "1.4"])
    _apply_settings(a, ["--voice", "--speed", "1.4"], repo, p)
    assert a.speed == 1.4 and a.tts_voice == "bf_isabella"
