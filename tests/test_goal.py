"""F5.9: wybór celu lekcji (planer F4 + dane ucznia) — bez ręcznego wskazywania tematu."""
import dataclasses
from datetime import UTC, datetime

import pytest

from tests.test_cli_e2e import Env, EvalProv, Interrupt, WaitLines
from tutor.app import goal as G
from tutor.app import lesson as L
from tutor.pedagogy import content as C

NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def learning(repo, pid, skill, p=0.5):
    repo.upsert_skill_state(pid, skill, p, 3, status="learning")


def finish_lesson(repo, pid, skill, ok, total=3):
    sid = repo.start_session(pid, "lesson")
    ids = [f"i{k}" for k in range(total)]
    repo.set_session_plan(pid, sid, {"lesson": skill, "items": ids, "done": ids, "ok": ids[:ok]})
    repo.end_session(pid, sid)
    return sid


def test_new_student_gets_marked_starter_goal_that_can_be_taught(repo, pack):
    pid = repo.create_profile("ann")
    c = G.choose(repo, pack, pid, NOW)
    assert c is not None and c.source == "starter" and c.provisional
    L.prepare(pack, c.skill_id)                                       # są wyjaśnienie i zadania
    assert "nie jest wynikiem diagnozy" in c.reason
    assert G.choose(repo, pack, pid, NOW) == c                         # deterministyczny
    assert repo.list_skill_states(pid) == [] and repo.list_competence(pid) == []   # wybór niczego nie zapisuje


def test_student_with_history_continues_skill_in_progress(repo, pack):
    pid = repo.create_profile("ann")
    learning(repo, pid, "en.gram.present_simple", 0.5)
    c = G.choose(repo, pack, pid, NOW)
    assert c.skill_id == "en.gram.present_simple" and c.source == "plan"
    assert "w trakcie nauki" in c.reason and "nie jest potwierdzone" in c.reason     # szacunek, nie potwierdzone opanowanie


def test_skill_without_materials_is_skipped(repo, pack):
    pid = repo.create_profile("ann")
    learning(repo, pid, "en.listen.numbers_names", 0.5)               # brak wyjaśnienia/zadań zamkniętych
    with pytest.raises(L.LessonError):
        L.prepare(pack, "en.listen.numbers_names")
    c = G.choose(repo, pack, pid, NOW)
    assert c is not None and c.skill_id != "en.listen.numbers_names"


def test_no_teachable_skill_returns_none(repo, pack):
    bare = dataclasses.replace(pack, items={})
    pid = repo.create_profile("ann")
    assert G.choose(repo, bare, pid, NOW) is None


def test_completed_lesson_is_not_repeated_without_reason(repo, pack):
    pid = repo.create_profile("ann")
    learning(repo, pid, "en.gram.present_simple", 0.5)
    finish_lesson(repo, pid, "en.gram.present_simple", ok=3)         # bezbłędna, ukończona
    c = G.choose(repo, pack, pid, NOW)
    assert c.skill_id != "en.gram.present_simple"


def test_lesson_with_misses_may_be_repeated_with_stated_reason(repo, pack):
    pid = repo.create_profile("ann")
    learning(repo, pid, "en.gram.present_simple", 0.5)
    finish_lesson(repo, pid, "en.gram.present_simple", ok=1)
    c = G.choose(repo, pack, pid, NOW)
    assert c.skill_id == "en.gram.present_simple" and "pomyłk" in c.reason


def test_unfinished_lesson_does_not_count_as_completed(repo, pack):
    pid = repo.create_profile("ann")
    learning(repo, pid, "en.gram.present_simple", 0.5)
    sid = repo.start_session(pid, "lesson")
    repo.set_session_plan(pid, sid, {"lesson": "en.gram.present_simple", "items": ["a", "b", "c"], "done": ["a"],
                                     "ok": ["a"]})
    assert G.choose(repo, pack, pid, NOW).skill_id == "en.gram.present_simple"


def test_profiles_are_isolated(repo, pack):
    a, b = repo.create_profile("ann"), repo.create_profile("bob")
    learning(repo, b, "en.gram.present_simple", 0.5)
    finish_lesson(repo, b, "en.gram.to_be_present", ok=3)
    ca, cb = G.choose(repo, pack, a, NOW), G.choose(repo, pack, b, NOW)
    assert cb.skill_id == "en.gram.present_simple" and ca.source == "starter"
    assert G.completed(repo, a) == {} and "en.gram.to_be_present" in G.completed(repo, b)


def test_profile_without_unreviewed_practice_gets_no_ai_checked_lesson(repo, pack):
    pid = repo.create_profile("ann")
    repo.conn.execute("UPDATE profile SET allow_unreviewed_practice=0 WHERE id=?", (pid,))
    assert G.choose(repo, pack, pid, NOW) is None                     # 0 zadań human_reviewed ⇒ brak lekcji


# --- CLI ---
@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def test_cli_auto_lesson_records_choice_and_passes_goal_to_evaluation(env, pack):
    c = G.choose(env.repo, pack, env.pid, NOW)
    _, items = L.prepare(pack, c.skill_id)
    ev = EvalProv()
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, *[i.answers[0] for i in items], "I am here"),
                       ["--no-audio", "--no-placement", "--lesson"], ev=ev)
    text = "\n".join(out)
    assert code == 0 and f"Cel lekcji: {c.skill_id}" in text and "Dlaczego ten cel" in text and c.reason in text
    s = env.repo.list_sessions(env.pid)[0]
    plan = env.repo.get_session_plan(env.pid, s["id"])
    assert plan["lesson"] == c.skill_id and plan["choice"]["source"] == "starter" and plan["choice"]["reason"] == c.reason
    assert any(c.skill_id in m.content for call in ev.calls for m in call)       # cel w ocenie
    st = env.repo.get_skill_state(env.pid, c.skill_id)
    assert st["status"] != "mastered" and st["mastered_at"] is None


def test_cli_manual_goal_still_works_and_records_manual_choice(env, pack):
    _, items = L.prepare(pack, "en.gram.present_perfect")
    env.go(Lines_(*[i.answers[0] for i in items], "q"), ["--no-audio", "--lesson", "en.gram.present_perfect"],
           ev=EvalProv())
    plan = env.repo.get_session_plan(env.pid, env.repo.list_sessions(env.pid)[0]["id"])
    assert plan["lesson"] == "en.gram.present_perfect" and plan["choice"]["source"] == "manual"


def Lines_(*ls):
    from tests.voice_fakes import Lines
    return Lines(*ls)


def test_cli_auto_lesson_resumes_same_goal_after_interrupt(env, pack):
    c = G.choose(env.repo, pack, env.pid, NOW)
    _, items = L.prepare(pack, c.skill_id)
    env.go(Interrupt(items[0].answers[0]), ["--no-audio", "--no-placement", "--lesson"], ev=EvalProv())
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and s[0]["status"] == "paused"
    # stan ucznia zmienił się w międzyczasie: wznowienie i tak zostaje przy rozpoczętym celu
    learning(env.repo, env.pid, "en.gram.present_simple", 0.5)
    code, out = env.go(Lines_(*[i.answers[0] for i in items[1:]], "q"), ["--no-audio", "--no-placement", "--lesson"], ev=EvalProv())
    text = "\n".join(out)
    assert "Wznawiam" in text and len(env.repo.list_sessions(env.pid)) == 1
    assert len(env.repo.attempt_history(env.pid, c.skill_id)) == len(items) and items[0].prompt not in text


def test_cli_auto_lesson_next_run_picks_different_goal_after_completion(env, pack):
    c1 = G.choose(env.repo, pack, env.pid, NOW)
    _, items = L.prepare(pack, c1.skill_id)
    env.go(Lines_(*[i.answers[0] for i in items], "q"), ["--no-audio", "--no-placement", "--lesson"], ev=EvalProv())
    assert env.repo.list_sessions(env.pid)[0]["status"] == "ended"
    env.go(Lines_("q"), ["--no-audio", "--no-placement", "--lesson"], ev=EvalProv())
    plans = [env.repo.get_session_plan(env.pid, s["id"]) for s in env.repo.list_sessions(env.pid)]
    assert len(plans) == 2 and plans[1]["lesson"] != c1.skill_id
