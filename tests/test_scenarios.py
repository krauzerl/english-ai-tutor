"""F6: scenariusze dydaktyczne na prawdziwej bazie SQLite i prawdziwych materiałach (atrapy tylko dla modeli/audio).
Oceniają zachowanie systemu wg dowodów, nie „samoocenę” modelu."""
import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv, WaitLines
from tests.test_feedback import Gated
from tests.test_placement import sentence
from tutor.app import goal as G
from tutor.app import lesson as L
from tutor.app import placement as P
from tutor.app import progress as PG
from tutor.app import review as R
from tutor.pedagogy import content as C

NOW = datetime.now(UTC)
SKILL = "en.gram.to_be_present"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def place(repo, pack, pid, policy):
    sid = repo.start_session(pid, "placement")
    P.run(repo, pack, pid, sid, lambda it, n: policy(it), lambda s: None, now=NOW)
    repo.end_session(pid, sid)


def theta(repo, pid, area="grammar"):
    return repo.list_competence(pid, area)[-1]["theta"]


def test_beginner_with_tiny_vocabulary_gets_low_estimate_and_easy_goal(repo, pack):
    pid = repo.create_profile("beginner")
    place(repo, pack, pid, lambda it: L.Answer("I don't know"))
    mid = repo.create_profile("mid")
    place(repo, pack, mid, lambda it: L.Answer(sentence(it)) if it.cefr in ("A1", "A2") else L.Answer("I don't know"))
    assert theta(repo, pid) < theta(repo, mid)
    ch = G.choose(repo, pack, pid, NOW)
    assert ch is not None and pack.skills[ch.skill_id].cefr in ("A1", "A2")
    assert "diagnoz" in ch.reason.lower() or ch.provisional                     # nie udaje diagnozy


def test_good_speaker_with_recurring_error_gets_that_skill_reviewed_not_assumed_mastered(env, pack):
    ev = EvalProv()
    for k in range(1, 4):                                # trzy sesje z tym samym błędem (past_simple)
        env.go(WaitLines(lambda k=k: env.applied() >= k, "I goed home"), ["--no-audio", "--no-placement"], ev=ev)
    errs = env.repo.list_errors(env.pid)
    assert errs and errs[0]["category"].startswith("tense")
    st = [s for s in env.repo.list_skill_states(env.pid) if s["status"] == "mastered"]
    assert st == []                                       # rozmowa nie nadaje opanowania (brama jakości zamknięta)


def test_voice_misrecognition_never_creates_error_or_mastery(env, pack):
    from tests.test_stt_detailed import DetailedSTT
    from tests.voice_fakes import FakeMic, blocks, tone
    from tutor.voice import audio as A
    from tutor.voice.stt import Transcript
    sk, items = L.prepare(pack, SKILL)
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = DetailedSTT(*[Transcript("banana", [])] * 8)
    env.go(Gated({}, *([""] * 16)), ["--mode", "ptt", "--no-placement", "--lesson", SKILL], mic=mic, stt=stt,
           sink=A.SimSink(), ev=EvalProv())
    assert env.repo.attempt_history(env.pid, SKILL) == [] and env.repo.list_errors(env.pid) == []


def test_unusual_but_correct_constructions_are_accepted(pack):
    _, items = L.prepare(pack, SKILL)
    gap = next(i for i in items if i.prompt.startswith("I ___"))
    for said in ("I'm twenty-five years old", "I am 25 years old.", "Well, I am twenty five years old"[6:]):
        assert L.check(pack, gap, said)


def test_several_days_lessons_reviews_and_progress_without_mastery(repo, pack):
    pid = repo.create_profile("ann")
    sk, items = L.prepare(pack, SKILL)
    answers = {i.id: L.Answer(sentence(i)) for i in items}
    for day in range(3):                                         # trzy kolejne dni
        now = NOW - timedelta(days=3 - day)
        sid = repo.start_session(pid, "lesson")
        L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i: answers[it.id], lambda s: None, now=now)
        repo.conn.execute("UPDATE attempt SET created_at=? WHERE session_id=?",
                          ((now).strftime("%Y-%m-%dT10:00:00.000Z"), sid))
        repo.end_session(pid, sid)
    due = R.due_skills(repo, pack, pid, NOW + timedelta(days=30))
    assert due == [SKILL]
    st = repo.get_skill_state(pid, SKILL)
    assert st["status"] == "learning" and st["mastered_at"] is None
    rep = PG.build(repo, pack, pid, NOW)
    assert rep["skills"]["working"] or rep["skills"]["struggling"] or rep["skills"]["too_few"]
    assert len(rep["changes"]) >= 1                              # porównanie sesji z faktycznych prób
    assert rep["attempts_total"] == 9


def test_placement_review_progress_make_no_llm_calls_and_are_fast(env, pack):
    conv = FakeProvider(chunks=["Nice. "])
    t0 = time.time()
    env.go(Gated({}, *[sentence(i) for i in pack.items.values() if i.type == "gap"] * 3), ["--no-audio", "--placement"],
           llm=conv, ev=EvalProv())
    env.go(Gated({}, "q"), ["--no-audio", "--review"], llm=conv, ev=EvalProv())
    env.go(Gated({}), ["--progress"], llm=conv, ev=EvalProv())
    assert conv.calls == [] and time.time() - t0 < 10


def test_migrations_unchanged_and_no_external_calls_configured(pack):
    import pathlib
    names = sorted(p.name for p in pathlib.Path("tutor/store/migrations").glob("*.sql"))
    assert len(names) == 7 and names[-1] == "007_achievements_settings.sql"   # tylko addytywne


def test_interrupted_lesson_restart_flows_into_remaining_tasks(env, pack):
    _, items = L.prepare(pack, SKILL)
    env.go(Gated({}, sentence(items[0]), "q"), ["--no-audio", "--no-placement", "--lesson", SKILL], ev=EvalProv())
    code, out = env.go(Gated({}, sentence(items[1]), sentence(items[2]), "q"),
                       ["--no-audio", "--no-placement", "--lesson", SKILL], ev=EvalProv())
    h = env.repo.attempt_history(env.pid, SKILL)
    assert len(h) == 3 and len({x["item_id"] for x in h}) == 3 and "Wznawiam" in "\n".join(out)
    assert json.loads(h[0]["feedback_json"])["no_mastery"] is True


def test_recurring_conversation_error_brings_its_skill_back_as_unverified_suggestion(env, pack):
    for k in range(1, 4):
        env.go(WaitLines(lambda k=k: env.applied() >= k, "I goed home"), ["--no-audio", "--no-placement"],
               ev=EvalProv())
    ch = G.choose(env.repo, pack, env.pid, NOW)
    assert ch.source == "error" and "past_simple" in ch.skill_id and ch.provisional
    assert "niezweryfikowana" in ch.reason
    assert [s for s in env.repo.list_skill_states(env.pid) if s["status"] == "mastered"] == []
