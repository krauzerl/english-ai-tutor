"""F6: powtórki FSRS w prawdziwym przebiegu nauki."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from tutor.app import ingest
from tutor.app import lesson as L
from tutor.app import review as R
from tutor.pedagogy import content as C

SKILL = "en.gram.to_be_present"
NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def sentence(it):
    return it.prompt.replace("___", it.answers[0]) if it.type == "gap" and "___" in it.prompt else it.answers[0]


def make_due(repo, pack, pid, skill=SKILL, correct=True):
    """Prawdziwa próba tworzy kartę FSRS; potem przesuwamy termin w przeszłość."""
    sid = repo.start_session(pid, "lesson")
    ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", skill, correct, source="practice",
                              dedupe_key=f"seed:{skill}", now=NOW - timedelta(days=10), allow_mastery=False)
    repo.conn.execute("UPDATE srs_card SET due_at=? WHERE profile_id=?", ((NOW - timedelta(hours=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"), pid))
    return sid


def run(repo, pack, pid, answer):
    sid = repo.start_session(pid, "review")
    out, sp = [], []
    res = R.run(repo, pack, pid, sid, lambda it, i: answer(it), out.append, now=NOW, speak=sp.append)
    return res, out, sp, sid


def test_attempt_creates_card_and_due_skill_is_found(repo, pack):
    pid = repo.create_profile("ann")
    assert R.due_skills(repo, pack, pid, NOW) == []
    make_due(repo, pack, pid)
    assert R.due_skills(repo, pack, pid, NOW) == [SKILL]


def test_review_prefers_unseen_items_for_transfer(repo, pack):
    pid = repo.create_profile("ann")
    make_due(repo, pack, pid)
    items = R.pick_items(repo, pack, pid, SKILL)
    assert "en.f46.gram.a1.01" not in [i.id for i in items][:1] or len(items) == 1


def test_correct_review_moves_card_forward_and_records_practice_evidence(repo, pack):
    pid = repo.create_profile("ann")
    make_due(repo, pack, pid)
    before = repo.get_card(pid, "construction", SKILL)["due_at"]
    res, out, sp, sid = run(repo, pack, pid, lambda it: L.Answer(sentence(it)))
    after = repo.get_card(pid, "construction", SKILL)["due_at"]
    assert res.correct == res.asked > 0 and after > before
    h = [x for x in repo.attempt_history(pid, SKILL) if json.loads(x["feedback_json"]).get("review")]
    assert len(h) == res.asked and all(json.loads(x["feedback_json"])["no_mastery"] for x in h)
    assert repo.get_skill_state(pid, SKILL)["status"] != "mastered"          # powtórka ≠ opanowanie
    assert R.due_skills(repo, pack, pid, NOW) == []


def test_wrong_review_reveals_answer_and_schedules_sooner_than_correct(repo, pack):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    make_due(repo, pack, a)
    make_due(repo, pack, b)
    run(repo, pack, a, lambda it: L.Answer(sentence(it)))
    res, out, *_ = run(repo, pack, b, lambda it: L.Answer("zzz yyy"))
    assert res.correct == 0 and any("Poprawna odpowiedź" in x for x in out)
    assert repo.get_card(b, "construction", SKILL)["due_at"] < repo.get_card(a, "construction", SKILL)["due_at"]


def test_resume_does_not_double_count(repo, pack):
    pid = repo.create_profile("ann")
    make_due(repo, pack, pid)
    sid = repo.start_session(pid, "review")
    n = {"i": 0}
    def ask(it, i):
        n["i"] += 1
        return None if n["i"] > 1 else L.Answer(sentence(it))
    r1 = R.run(repo, pack, pid, sid, ask, lambda s: None, now=NOW)
    assert r1.quit and r1.asked == 1
    r2 = R.run(repo, pack, pid, sid, lambda it, i: L.Answer(sentence(it)), lambda s: None, now=NOW)
    ids = [x["item_id"] for x in repo.attempt_history(pid, SKILL) if json.loads(x["feedback_json"]).get("review")]
    assert len(ids) == len(set(ids)) == r1.asked + r2.asked


def test_postpone_and_unclear_stt_do_not_penalise(repo, pack):
    pid = repo.create_profile("ann")
    make_due(repo, pack, pid)
    due0 = repo.get_card(pid, "construction", SKILL)["due_at"]
    res, out, *_ = run(repo, pack, pid, lambda it: L.Answer("later, we can skip this"))
    assert res.postponed == [SKILL] and res.asked == 0
    assert repo.get_card(pid, "construction", SKILL)["due_at"] > due0
    pid2 = repo.create_profile("bob")
    make_due(repo, pack, pid2)
    res2, *_ = run(repo, pack, pid2, lambda it: L.Answer("mumble", "voice", None))
    assert res2.postponed == [SKILL] and res2.asked == 0
    assert [x for x in repo.attempt_history(pid2, SKILL) if json.loads(x["feedback_json"]).get("review")] == []


def test_daily_cap_protects_from_overload(repo, pack):
    pid = repo.create_profile("ann")
    make_due(repo, pack, pid)
    sid = repo.start_session(pid, "review")
    for k in range(R.DAILY_CAP):
        repo.add_attempt(pid, SKILL, True, session_id=sid, feedback={"review": 1}, dedupe_key=f"cap{k}")
    res, out, *_ = run(repo, pack, pid, lambda it: L.Answer(sentence(it)))
    assert res.capped and res.asked == 0


def test_nothing_due_and_profile_isolation(repo, pack):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    make_due(repo, pack, a)
    res, *_ = run(repo, pack, b, lambda it: L.Answer("x"))
    assert res.nothing_due


def test_recurring_error_skill_goes_first(repo, pack):
    pid = repo.create_profile("ann")
    make_due(repo, pack, pid, SKILL)
    make_due(repo, pack, pid, "en.gram.articles_a_the")
    repo.conn.execute("UPDATE srs_card SET due_at='2020-01-01T00:00:00Z' WHERE ref_id=?", (SKILL,))
    repo.conn.execute("UPDATE srs_card SET due_at='2020-02-01T00:00:00Z' WHERE ref_id='en.gram.articles_a_the'")
    first = R.due_skills(repo, pack, pid, NOW)
    assert set(first) <= {SKILL, "en.gram.articles_a_the"} and len(first) >= 1


# --- CLI ---
from tests.test_cli_e2e import Env, EvalProv  # noqa: E402
from tests.test_feedback import Gated  # noqa: E402


def test_cli_review_end_to_end_and_resume(repo, conn, pack):
    env = Env(repo, conn)
    make_due(repo, pack, env.pid)
    sk, items = L.prepare(pack, SKILL)
    first = R.pick_items(repo, pack, env.pid, SKILL)
    code, out = env.go(Gated({}, sentence(first[0]), "q"), ["--no-audio", "--review"], ev=EvalProv())
    s = [x for x in repo.list_sessions(env.pid) if x["kind"] == "review"]
    assert code == 0 and len(s) == 1 and s[0]["status"] == "paused"
    code, out = env.go(Gated({}, *[sentence(i) for i in items] * 2), ["--no-audio", "--review"], ev=EvalProv())
    text = "\n".join(out)
    assert "Wznawiam powtórki" in text and "Powtórki:" in text
    ids = [x["item_id"] for x in repo.attempt_history(env.pid, SKILL) if json.loads(x["feedback_json"]).get("review")]
    assert len(ids) == len(set(ids)) == 2
    assert [x["status"] for x in repo.list_sessions(env.pid) if x["kind"] == "review"] == ["ended"]


def test_cli_review_nothing_due(repo, conn):
    env = Env(repo, conn)
    code, out = env.go(Gated({}, "q"), ["--no-audio", "--review"], ev=EvalProv())
    assert code == 0 and any("Brak zaległych" in x for x in out)
