"""F7: dziennik słabych stron — pełny wpis, kwestionowanie korekty, oznaczanie błędu STT, ślad historii."""
from datetime import UTC, datetime

import pytest

from tutor.app import feedback as FB
from tutor.app import ingest
from tutor.app import weakspots as WS
from tutor.pedagogy import content as C
from tutor.services.api import ServiceError, TutorAPI

NOW = datetime(2026, 11, 26, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def setup(repo, pack, n=3):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "chat")
    repo.add_turn(pid, sid, "assistant", "What do you do?")
    ids = []
    for k in range(n):
        tid = repo.add_turn(pid, sid, "user", f"I'm paramedic {k}.")
        ids.append(repo.add_observation(pid, sid, tid, "error", "paramedic", category="article.missing",
                                        fix="a paramedic", severity=2, confidence="h"))
    ingest._recompute_errors(repo, pack, pid, NOW)
    return pid, sid, ids


def test_entry_has_utterance_context_fix_category_reliability_date_source(repo, pack):
    pid, sid, ids = setup(repo, pack, 1)
    e = WS.build(repo, pack, pid, NOW)["entries"][0]
    assert e["utterance"] == "I'm paramedic 0." and e["context"] == "What do you do?"
    assert (e["span"], e["fix"], e["category"]) == ("paramedic", "a paramedic", "article.missing")
    assert "sugestia modelu" in e["reliability"] and e["date"] and e["source"]
    assert "rodzajnik „a”" in e["explanation"] and e["counted"]


def test_dispute_excludes_from_counts_but_keeps_history(repo, pack):
    pid, sid, ids = setup(repo, pack, 3)
    assert repo.list_errors(pid)[0]["count"] == 3
    ingest.review_observation(repo, pack, pid, ids[0], "disputed", NOW)
    assert repo.list_errors(pid)[0]["count"] == 2
    assert len(repo.list_observations(pid)) == 3                                  # nic nie usunięto
    e = next(x for x in WS.build(repo, pack, pid, NOW)["entries"] if x["id"] == ids[0])
    assert e["review"] == "disputed" and not e["counted"]
    ingest.review_observation(repo, pack, pid, ids[0], "restored", NOW)            # cofnięcie
    assert repo.list_errors(pid)[0]["count"] == 3
    assert [r["verdict"] for r in repo.conn.execute("SELECT verdict FROM observation_review ORDER BY id")] == \
        ["disputed", "restored"]


def test_marking_all_as_stt_error_removes_derived_weakspot(repo, pack):
    pid, sid, ids = setup(repo, pack, 1)
    ingest.review_observation(repo, pack, pid, ids[0], "stt_error", NOW)
    rep = WS.build(repo, pack, pid, NOW)
    assert rep["errors"] == [] and rep["entries"][0]["review"] == "stt_error" and rep["has_data"]


def test_disputed_correction_not_in_session_summary(repo, pack):
    pid, sid, ids = setup(repo, pack, 1)
    assert FB.summary_lines(repo, pack, pid, sid)
    ingest.review_observation(repo, pack, pid, ids[0], "disputed", NOW)
    assert FB.summary_lines(repo, pack, pid, sid) == []


def test_review_isolated_per_profile(repo, pack):
    pid, sid, ids = setup(repo, pack, 1)
    other = repo.create_profile("bob")
    with pytest.raises(ValueError):
        ingest.review_observation(repo, pack, other, ids[0], "disputed", NOW)
    api = TutorAPI(repo)
    api._packs = {"en": pack}
    with pytest.raises(ServiceError):
        api.review_observation(other, ids[0], "disputed")
