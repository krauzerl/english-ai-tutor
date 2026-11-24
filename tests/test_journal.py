"""Achievements (trwałe, idempotentne, osobne od kompetencji) i dziennik słabych stron (statusy wiarygodności, drill)."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated, obs
from tutor.app import achievements as AC
from tutor.app import ingest
from tutor.app import quickchat as QC
from tutor.app import topics as T
from tutor.app import weakspots as WS
from tutor.pedagogy import content as C

NOW = datetime.now(UTC)
SKILL = "en.gram.to_be_present"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def turn_at(repo, pid, sid, text, when, role="user"):
    repo.conn.execute("INSERT INTO turn(session_id,profile_id,role,text,created_at) VALUES (?,?,?,?,?)",
                      (sid, pid, role, text, when.strftime("%Y-%m-%dT%H:%M:%S.000Z")))


def chat_on(repo, pid, day, topic="fd.favorite", n=3):
    sid = QC.start(repo, pid, T.get(topic), 10)
    repo.conn.execute("UPDATE session SET started_at=? WHERE id=?", (day.strftime("%Y-%m-%dT10:00:00.000Z"), sid))
    for k in range(n):
        turn_at(repo, pid, sid, "hello", day.replace(hour=10, minute=k))
    return sid


# --- achievements ---
def test_nothing_earned_without_activity(repo):
    pid = repo.create_profile("ann")
    assert AC.award(repo, pid, NOW) == [] and AC.overview(repo, pid, NOW)["earned"] == 0


def test_streak_and_first_session_awarded_once(repo):
    pid = repo.create_profile("ann")
    for d in range(3):
        chat_on(repo, pid, NOW - timedelta(days=d))
    first = {a["code"] for a in AC.award(repo, pid, NOW)}
    assert {"streak_3", "first_session", "days_10"} & first == {"streak_3", "first_session"}
    assert AC.award(repo, pid, NOW) == []                                     # idempotentne
    assert len([a for a in repo.list_achievements(pid) if a["code"] == "streak_3"]) == 1


def test_resumed_session_does_not_double_count(repo):
    pid = repo.create_profile("ann")
    sid = chat_on(repo, pid, NOW)
    AC.award(repo, pid, NOW)
    repo.pause_session(pid, sid)
    repo.resume_session(pid, sid)
    assert AC.award(repo, pid, NOW) == [] and len(repo.list_achievements(pid)) == len({
        a["code"] for a in repo.list_achievements(pid)})


def test_talk_time_comes_from_turn_timestamps(repo):
    pid = repo.create_profile("ann")
    sid = QC.start(repo, pid, T.get("fd.favorite"))
    for k in range(11):                                   # 11 tur co 60 s ⇒ 10 minut
        turn_at(repo, pid, sid, "x", NOW - timedelta(hours=1) + timedelta(seconds=60 * k))
    assert AC.stats(repo, pid, NOW)["talk_minutes"] == 10
    assert "talk_10m" in {a["code"] for a in AC.award(repo, pid, NOW)}


def test_comeback_and_triple_day_and_topic_explorer(repo):
    pid = repo.create_profile("ann")
    chat_on(repo, pid, NOW - timedelta(days=20))
    for i, t in enumerate(["tr.dream", "wk.job", "hb.music", "tc.apps", "pp.family"]):
        chat_on(repo, pid, NOW - timedelta(days=i), t)
    codes = {a["code"] for a in AC.award(repo, pid, NOW)}
    assert {"comeback", "topics_5"} <= codes


def test_no_competence_badge_without_engine_mastery(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    for k in range(5):
        ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", SKILL, True, source="practice",
                                  dedupe_key=f"k{k}", now=NOW - timedelta(days=k), allow_mastery=False)
    AC.award(repo, pid, NOW)
    assert not [a for a in repo.list_achievements(pid) if a["code"].startswith("mastered:")]
    repo.upsert_skill_state(pid, SKILL, 0.9, 5, "2026-01-01T00:00:00Z", status="mastered")
    assert any(a["code"] == f"mastered:{SKILL}" for a in AC.award(repo, pid, NOW))


def test_achievements_isolated_between_profiles(repo):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    chat_on(repo, a, NOW)
    AC.award(repo, a, NOW)
    assert repo.list_achievements(b) == [] and AC.overview(repo, b, NOW)["earned"] == 0


def test_overview_progress_is_real_counts(repo):
    pid = repo.create_profile("ann")
    chat_on(repo, pid, NOW)
    i = {x["code"]: x for x in AC.overview(repo, pid, NOW)["items"]}
    assert i["streak_3"]["progress"] == 1 and i["streak_3"]["target"] == 3 and not i["streak_3"]["earned"]


def test_cli_achievements_and_weakspots_need_no_models(repo, conn):
    env = Env(repo, conn)
    chat_on(repo, env.pid, NOW)
    code, out = env.go(Gated({}), ["--achievements"], ev=EvalProv())
    assert code == 0 and any("Nowe osiągnięcie" in x for x in out) and any("Osiągnięcia:" in x for x in out)
    code, out = env.go(Gated({}), ["--weakspots"], ev=EvalProv())
    assert code == 0 and any("Brak danych" in x for x in out)


# --- dziennik słabych stron ---
def test_model_suggestion_is_labelled_not_confirmed(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I goed home.", cat="tense.past_simple", span="goed", fix="went")
    ingest._recompute_errors(repo, pack, pid, NOW)
    rep = WS.build(repo, pack, pid, NOW)
    e = rep["errors"][0]
    assert e["category"] == "tense.past_simple" and e["reliability"] == "sugestia modelu"
    assert e["trend"]["direction"] == "za mało danych" and rep["has_data"]


def test_stt_suspect_is_never_listed_as_error(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I goed", kind="stt_suspect", cat="tense.past_simple", span="goed", fix="went", mode="voice")
    ingest._recompute_errors(repo, pack, pid, NOW)
    rep = WS.build(repo, pack, pid, NOW)
    assert rep["stt_uncertain"]["count"] == 1
    assert all(e["reliability"] != "sugestia modelu" for e in rep["errors"])
    text = "\n".join(WS.render(rep))
    assert "to nie są błędy" in text.lower() or "NIE są błędy" in text


def test_exercise_failure_upgrades_to_confirmed(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I goed home.", cat="tense.past_simple", span="goed", fix="went")
    ingest._recompute_errors(repo, pack, pid, NOW)
    ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", "en.gram.past_simple_regular", False,
                              source="practice", dedupe_key="x", now=NOW, allow_mastery=False)
    e = WS.build(repo, pack, pid, NOW)["errors"][0]
    assert e["reliability"] == "potwierdzony ćwiczeniami" and e["confirmed_by_exercises"] == 1


def test_trend_needs_enough_utterances_and_shows_improvement(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    for k in range(6):                                          # poprzednie 14 dni: 3 błędy na 6 wypowiedzi
        t = NOW - timedelta(days=20, hours=k)
        turn_at(repo, pid, sid, "x", t)
        if k < 3:
            tid = repo.conn.execute("SELECT max(id) FROM turn").fetchone()[0]
            repo.add_observation(pid, sid, tid, "error", f"s{k}", category="tense.past_simple", fix="went", severity=2,
                                 confidence="h")
            repo.conn.execute("UPDATE observation SET created_at=? WHERE turn_id=?",
                              (t.strftime("%Y-%m-%dT%H:%M:%S.000Z"), tid))
    for k in range(6):                                          # ostatnie 14 dni: 0 błędów na 6 wypowiedzi
        turn_at(repo, pid, sid, "y", NOW - timedelta(days=2, hours=k))
    ingest._recompute_errors(repo, pack, pid, NOW)
    t = WS.build(repo, pack, pid, NOW)["errors"][0]["trend"]
    assert t["direction"] == "poprawa" and t["last_14d"] == 0 and t["previous_14d"] == 3


def test_vocabulary_misses_listed_from_attempts(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    it = next(i for i in pack.items.values() if i.skill_ids[0].startswith("en.vocab.") and i.answers
              and "practice" in i.pools)
    ingest.apply_item_attempt(repo, pack, pid, sid, it.id, it.skill_ids[0], False, source="practice",
                              dedupe_key="v", now=NOW, allow_mastery=False)
    v = WS.build(repo, pack, pid, NOW)["vocabulary"]
    assert v and v[0]["term"] == it.answers[0] and v[0]["misses"] == 1


def test_drill_runs_targeted_exercises_via_cli(repo, conn, pack):
    env = Env(repo, conn)
    sid = repo.start_session(env.pid, "voice")
    obs(repo, env.pid, sid, "I goed home.", cat="tense.past_simple", span="goed", fix="went")
    ingest._recompute_errors(repo, pack, env.pid, NOW)
    skills = WS.resolve_drill(WS.build(repo, pack, env.pid, NOW), pack, "1")
    assert skills and all(s in pack.skills for s in skills)
    from tests.test_placement import sentence
    from tutor.app import lesson as L
    _, items = L.prepare(pack, skills[0])
    code, out = env.go(Gated({}, *[sentence(i) for i in items] * 2), ["--no-audio", "--drill", "1"], ev=EvalProv())
    text = "\n".join(out)
    assert code == 0 and "Powtórki:" in text
    h = repo.attempt_history(env.pid, skills[0])
    assert h and all(json.loads(x["feedback_json"])["no_mastery"] for x in h)
    assert [s["kind"] for s in repo.list_sessions(env.pid)].count("drill") == 1


def test_drill_unknown_target_is_reported(repo, conn):
    env = Env(repo, conn)
    code, out = env.go(Gated({}, "q"), ["--no-audio", "--drill", "nope.nope"], ev=EvalProv())
    assert code == 0 and any("Brak materiałów" in x for x in out)
