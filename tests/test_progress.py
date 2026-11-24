"""F6: postęp wyłącznie z dowodów; niepewność jawnie oznaczona; brak wymyślonych procentów i poziomów CEFR."""
import re
from datetime import UTC, datetime, timedelta

import pytest

from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tests.test_placement import drive, sentence, setup
from tutor.app import ingest
from tutor.app import lesson as L
from tutor.app import progress as PG
from tutor.pedagogy import content as C

NOW = datetime.now(UTC)
SKILL = "en.gram.to_be_present"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def attempt(repo, pack, pid, sid, item, ok, k, days_ago=0):
    ingest.apply_item_attempt(repo, pack, pid, sid, item, SKILL, ok, source="practice", dedupe_key=f"k{k}",
                              now=NOW - timedelta(days=days_ago), allow_mastery=False)


def test_new_learner_report_says_nothing_checked(repo, pack):
    pid = repo.create_profile("ann")
    text = "\n".join(PG.render(PG.build(repo, pack, pid, NOW)))
    assert "nie sprawdzono" in text and "brak prób" in text and "nic zaległego" in text and "%" not in text


def test_report_after_placement_marks_estimate_as_provisional(repo, pack):
    pid, sid = setup(repo)
    drive(repo, pack, pid, sid, lambda it, n: L.Answer(sentence(it)))
    text = "\n".join(PG.render(PG.build(repo, pack, pid, NOW)))
    assert "szacunek wstępny" in text and "wstępnie" in text and "niezweryfikowany przez człowieka" in text
    assert not re.search(r"\b(A1|A2|B1|B2|C1|C2)\b.*(poziom|level)", text.lower()) or "nie jest diagnoz" in text


def test_difficulties_changes_and_counts_come_from_attempts(repo, pack):
    pid = repo.create_profile("ann")
    s1, s2 = repo.start_session(pid, "lesson"), repo.start_session(pid, "lesson")
    ids = ["en.f46.gram.a1.01", "en.f46.gram.a1.02", "en.f46.gram.a1.04"]
    for k, (it, ok) in enumerate(zip(ids, [False, False, True], strict=True)):
        attempt(repo, pack, pid, s1, it, ok, k, 3)
    for k, (it, ok) in enumerate(zip(ids, [True, True, True], strict=True)):
        attempt(repo, pack, pid, s2, it, ok, 10 + k)
    rep = PG.build(repo, pack, pid, NOW)
    ch = rep["changes"][0]
    assert ch["previous"] == (1, 3) and ch["latest"] == (3, 3)
    row = rep["skills"]["working"][0] if rep["skills"]["working"] else rep["skills"]["struggling"][0]
    assert row["attempts"] == 6 and row["correct"] == 4 and row["new_items"] == "1/3"         # transfer: 1. kontakt
    assert "poprzednio 1/3, ostatnio 3/3" in "\n".join(PG.render(rep))


def test_struggling_and_too_few_and_due(repo, pack):
    pid = repo.create_profile("ann")
    s = repo.start_session(pid, "lesson")
    for k in range(4):
        attempt(repo, pack, pid, s, "en.f46.gram.a1.01", False, k)
    rep = PG.build(repo, pack, pid, NOW + timedelta(days=30))
    assert rep["skills"]["struggling"] and rep["due"] == [SKILL]
    pid2 = repo.create_profile("bob")
    s2 = repo.start_session(pid2, "lesson")
    attempt_b = ingest.apply_item_attempt(repo, pack, pid2, s2, "en.f46.gram.a1.01", SKILL, True, source="practice",
                                          dedupe_key="b", now=NOW, allow_mastery=False)
    assert attempt_b["applied"] and PG.build(repo, pack, pid2, NOW)["skills"]["too_few"]


def test_unverified_stt_is_reported_as_uncertainty_not_as_result(repo, pack):
    pid, sid = setup(repo)
    drive(repo, pack, pid, sid, lambda it, n: L.Answer("mumble", "voice", None))
    text = "\n".join(PG.render(PG.build(repo, pack, pid, NOW)))
    assert "niepewnie rozpoznanych" in text


def test_no_invented_percentages(repo, pack):
    pid, sid = setup(repo)
    drive(repo, pack, pid, sid, lambda it, n: L.Answer(sentence(it)))
    assert "%" not in "\n".join(PG.render(PG.build(repo, pack, pid, NOW)))


def test_cli_progress_does_not_need_models_and_isolates_profiles(repo, conn):
    env = Env(repo, conn)
    other = repo.create_profile("zed")
    sid = repo.start_session(other, "lesson")
    repo.add_attempt(other, SKILL, True, session_id=sid, dedupe_key="z")
    code, out = env.go(Gated({}), ["--progress"], ev=EvalProv())
    text = "\n".join(out)
    assert code == 0 and "brak prób" in text and SKILL not in text
