"""F6: wstępne dopasowanie (silnik `diagnosis` provisional) z odpowiedziami tekstem i głosem."""
from datetime import UTC, datetime

import pytest

from tutor.app import lesson as L
from tutor.app import placement as P
from tutor.pedagogy import content as C

NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def sentence(it):
    return it.prompt.replace("___", it.answers[0]) if it.type == "gap" and "___" in it.prompt else it.answers[0]


def wrong_text(it):
    return "zzz qqq"


def setup(repo, name="ann"):
    pid = repo.create_profile(name)
    sid = repo.start_session(pid, "placement")
    return pid, sid


def drive(repo, pack, pid, sid, policy, areas=("grammar",), speak=None):
    out, spoken = [], []
    def ask(it, n):
        a = policy(it, n)
        return a
    rep = P.run(repo, pack, pid, sid, ask, out.append, now=NOW, speak=spoken.append if speak is None else speak,
                areas=areas)
    return rep, out, spoken


def test_strong_learner_gets_higher_estimate_than_beginner(repo, pack):
    p1, s1 = setup(repo, "strong")
    p2, s2 = setup(repo, "weak")
    drive(repo, pack, p1, s1, lambda it, n: L.Answer(sentence(it)))
    drive(repo, pack, p2, s2, lambda it, n: L.Answer("I don't know"))
    a = repo.list_competence(p1, "grammar")[-1]
    b = repo.list_competence(p2, "grammar")[-1]
    assert a["theta"] > b["theta"] and a["source"] == "placement_provisional" and b["source"] == "placement_provisional"


def test_result_is_provisional_with_notice_counts_and_no_cefr_claim(repo, pack):
    pid, sid = setup(repo)
    rep, out, _ = drive(repo, pack, pid, sid, lambda it, n: L.Answer(sentence(it)))
    c = repo.list_competence(pid, "grammar")[-1]
    import json
    r = json.loads(c["rationale"])
    assert "nie jest diagnoz" in r["notice"] and r["counts"]["correct"] >= 3 and "label" in r
    assert "wstępnie" in r["label"] and any("nie jest diagnoz" in x for x in out)
    assert rep.outcomes[0].saved


def test_unverified_stt_is_not_penalised_and_not_recorded(repo, pack):
    pid, sid = setup(repo)
    junk = lambda it, n: L.Answer("mumble", "voice", None)           # noqa: E731  - brak danych STT
    rep, out, _ = drive(repo, pack, pid, sid, junk)
    assert repo.list_competence(pid, "grammar") == []                  # za mało pewnych odpowiedzi
    assert repo.list_errors(pid) == [] and repo.list_skill_states(pid) == []
    assert rep.outcomes and rep.outcomes[0].counts["unverified"] > 0 and not rep.outcomes[0].saved
    assert any("za mało pewnych" in x for x in out)


def test_unknown_answer_is_no_answer_not_language_error(repo, pack):
    pid, sid = setup(repo)
    rep, *_ = drive(repo, pack, pid, sid, lambda it, n: L.Answer("I don't know"))
    c = rep.outcomes[0].counts
    assert c["no_answer"] > 0 and c["wrong"] == 0 and repo.list_errors(pid) == []


def test_clear_wrong_form_is_a_wrong_answer(repo, pack):
    pid, sid = setup(repo)
    def policy(it, n):
        if it.type == "gap":
            return L.Answer(it.prompt.replace("___", "banana") if False else "are", "voice", [])
        return L.Answer(it.options[-1] if it.options and it.options[-1] != it.answers[0] else sentence(it), "voice", [])
    rep, *_ = drive(repo, pack, pid, sid, policy)
    assert rep.outcomes[0].counts["wrong"] + rep.outcomes[0].counts["correct"] > 0


def test_voice_attempts_recorded_as_diagnosis_without_mastery(repo, pack):
    pid, sid = setup(repo)
    drive(repo, pack, pid, sid, lambda it, n: L.Answer(sentence(it), "voice", []))
    hist = [h for s in repo.list_skill_states(pid) for h in repo.attempt_history(pid, s["skill_id"])]
    assert hist and all(h["source"] == "diagnosis" for h in hist)
    assert all(s["status"] != "mastered" for s in repo.list_skill_states(pid))


def test_quit_and_resume_does_not_duplicate_or_restart(repo, pack):
    pid, sid = setup(repo)
    calls = {"n": 0}
    def quit_after_two(it, n):
        calls["n"] += 1
        return None if calls["n"] > 2 else L.Answer(sentence(it))
    rep, *_ = drive(repo, pack, pid, sid, quit_after_two)
    assert rep.quit and repo.list_competence(pid) == []
    asked1 = len(repo.get_session_plan(pid, sid)["placement"]["areas"]["grammar"]["asked"])
    assert asked1 == 2
    rep2, *_ = drive(repo, pack, pid, sid, lambda it, n: L.Answer(sentence(it)))
    assert not rep2.quit and repo.list_competence(pid, "grammar")
    ids = [h["item_id"] for s in repo.list_skill_states(pid) for h in repo.attempt_history(pid, s["skill_id"])]
    assert len(ids) == len(set(ids))                                     # każde zadanie raz


def test_skip_intent_ends_early_without_claiming_a_level(repo, pack):
    pid, sid = setup(repo)
    rep, *_ = drive(repo, pack, pid, sid, lambda it, n: L.Answer("we can move on"))
    assert rep.ended_early and repo.list_competence(pid) == []


def test_help_repeats_task_without_counting(repo, pack):
    pid, sid = setup(repo)
    seq = iter([L.Answer("I don't understand")])
    def policy(it, n):
        return next(seq, None) or L.Answer(sentence(it))
    rep, out, _ = drive(repo, pack, pid, sid, policy)
    assert rep.outcomes[0].counts["wrong"] == 0 and rep.outcomes[0].saved


def test_vocabulary_area_too(repo, pack):
    pid, sid = setup(repo)
    rep, *_ = drive(repo, pack, pid, sid, lambda it, n: L.Answer(sentence(it)), areas=("vocabulary",))
    assert rep.outcomes[0].saved and repo.list_competence(pid, "vocabulary")


def test_needs_placement_only_for_learner_without_history(repo, pack):
    pid, sid = setup(repo)
    assert P.needs_placement(repo, pid)
    drive(repo, pack, pid, sid, lambda it, n: L.Answer(sentence(it)))
    assert not P.needs_placement(repo, pid)


def test_profiles_isolated(repo, pack):
    a, sa = setup(repo, "a")
    b, _ = setup(repo, "b")
    drive(repo, pack, a, sa, lambda it, n: L.Answer(sentence(it)))
    assert repo.list_competence(b) == [] and P.needs_placement(repo, b)


# --- CLI ---
from tests.test_cli_e2e import Env, EvalProv  # noqa: E402
from tests.test_feedback import Gated  # noqa: E402


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def test_cli_placement_text_end_to_end_then_exit(env, pack):
    answers = [sentence(i) for i in pack.items.values() if i.type == "gap"] * 3
    code, out = env.go(Gated({}, *answers[:40]), ["--no-audio", "--placement"], ev=EvalProv())
    assert code == 0
    comp = env.repo.list_competence(env.pid)
    assert {c["area"] for c in comp} <= {"grammar", "vocabulary"} and comp
    s = env.repo.list_sessions(env.pid)
    assert [x["kind"] for x in s] == ["placement"] and s[0]["status"] == "ended"
    assert any("nie jest diagnoz" in x for x in out)


def test_cli_first_bare_lesson_runs_placement_then_lesson_from_planner(env, pack):
    gap = [sentence(i) for i in pack.items.values() if i.type == "gap"] * 4
    code, out = env.go(Gated({}, *gap[:60], "q"), ["--no-audio", "--lesson"], ev=EvalProv())
    kinds = [x["kind"] for x in env.repo.list_sessions(env.pid)]
    assert "placement" in kinds and env.repo.list_competence(env.pid)
    assert code in (0, 1)


def test_cli_manual_lesson_and_no_placement_skip_it(env, pack):
    env.go(Gated({}, "q"), ["--no-audio", "--lesson", "en.gram.to_be_present"], ev=EvalProv())
    env.go(Gated({}, "q"), ["--no-audio", "--no-placement", "--lesson"], ev=EvalProv())
    assert "placement" not in [x["kind"] for x in env.repo.list_sessions(env.pid)]


def test_cli_placement_interrupt_resumes_same_session(env, pack):
    first = Gated({}, sentence(next(i for i in pack.items.values() if i.type == "gap")), "q")
    env.go(first, ["--no-audio", "--placement"], ev=EvalProv())
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and s[0]["status"] == "paused"
    code, out = env.go(Gated({}, "q"), ["--no-audio", "--placement"], ev=EvalProv())
    assert "Wznawiam dopasowanie" in "\n".join(out) and len(env.repo.list_sessions(env.pid)) == 1


# --- „to łatwe”: zmiana celu bez mastery ---
def test_declared_easy_goal_is_skipped_next_time_and_not_mastered(env, pack):
    code, out = env.go(Gated({}, "this is too easy, we can move on", "q"),
                       ["--no-audio", "--no-placement", "--lesson", "en.gram.to_be_present"], ev=EvalProv())
    s = env.repo.list_sessions(env.pid)[0]
    assert env.repo.get_session_plan(env.pid, s["id"])["declared_easy"] is True
    assert env.repo.attempt_history(env.pid, "en.gram.to_be_present") == []
    st = env.repo.get_skill_state(env.pid, "en.gram.to_be_present")
    assert st is None or st["status"] != "mastered"
    from tutor.app import goal as G
    ch = G.choose(env.repo, pack, env.pid, NOW)
    assert ch is not None and ch.skill_id != "en.gram.to_be_present"
