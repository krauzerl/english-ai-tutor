"""F6/B7: próby ćwiczeniowe nie mogą dać `mastered` żadną ścieżką przeliczania (poziom dowodów, nie chwila zapisu)."""
from datetime import UTC, datetime

import pytest

from tutor.app import ingest
from tutor.app import lesson as L
from tutor.pedagogy import content as C

SKILL = "en.gram.to_be_present"
NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def lesson_days(repo, pack, pid, days):
    sk, items = L.prepare(pack, SKILL)
    for day in range(1, days + 1):
        sid = repo.start_session(pid, "lesson")
        ans = {i.id: L.Answer(i.answers[0]) for i in items}
        L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i, a=ans: a[it.id], lambda s: None, now=NOW)
        repo.conn.execute("UPDATE attempt SET created_at=? WHERE session_id=?", (f"2026-01-0{day}T10:00:00.000Z", sid))
    return sid


def test_later_recompute_by_another_path_does_not_promote_lesson_evidence(repo, pack):
    pid = repo.create_profile("ann")
    sid = lesson_days(repo, pack, pid, 3)
    assert repo.get_skill_state(pid, SKILL)["status"] == "learning"
    # inna ścieżka (AGV/remediation, domyślne allow_mastery=True) przelicza całą historię, w tym próby z lekcji
    r = ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", SKILL, True, source="remediation",
                                  dedupe_key="agv1", now=NOW)
    st = repo.get_skill_state(pid, SKILL)
    assert r["to"] == "learning" and st["status"] == "learning" and st["mastered_at"] is None
    assert st["p_mastery"] > 0.85                                   # p rośnie, ale dowody ćwiczeń nie wystarczą


def test_independent_evidence_on_two_days_can_still_promote_when_gate_logic_allows(repo, pack):
    """Domyślna ścieżka silnika (AGV/remediation) działa jak dawniej: ≥2 dni własnych dowodów + p ≥ 0,85."""
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    for day in range(1, 4):
        repo.add_attempt(pid, SKILL, True, session_id=sid, created_at=f"2026-01-0{day}T10:00:00.000Z",
                         source="remediation", feedback={"bkt": "production"}, dedupe_key=f"h{day}")
    r = ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", SKILL, True, source="remediation",
                                  dedupe_key="x1", now=NOW)
    assert r["to"] == "mastered"


def test_restart_replay_keeps_gate_closed(repo, pack, conn):
    pid = repo.create_profile("ann")
    lesson_days(repo, pack, pid, 3)
    from tutor.store.repo import Repo
    repo2 = Repo(conn)                                              # „nowy start aplikacji”: stan tylko z bazy
    ingest._recompute_skill(repo2, pack, pid, SKILL, NOW)
    assert repo2.get_skill_state(pid, SKILL)["status"] == "learning"


def test_duplicate_lesson_attempt_is_not_counted_twice(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    for _ in range(2):
        ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", SKILL, True, source="practice",
                                  dedupe_key="lesson:1:x", now=NOW, allow_mastery=False)
    assert len(repo.attempt_history(pid, SKILL)) == 1


def test_profiles_are_isolated(repo, pack):
    a, b = repo.create_profile("ann"), repo.create_profile("bob")
    lesson_days(repo, pack, a, 3)
    sb = repo.start_session(b, "lesson")
    r = ingest.apply_item_attempt(repo, pack, b, sb, "en.f46.gram.a1.01", SKILL, True, source="remediation",
                                  dedupe_key="b1", now=NOW)
    assert r["to"] == "learning" and repo.get_skill_state(b, SKILL)["attempts"] == 1


def test_attempts_from_uncertain_transcripts_never_count_as_mastery_evidence(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    for day in range(1, 4):                      # trzy dni „poprawnych” prób z niepewnym STT (flaga w dowodzie)
        repo.add_attempt(pid, SKILL, True, session_id=sid, created_at=f"2026-01-0{day}T10:00:00.000Z",
                         source="practice", feedback={"bkt": "production", "stt_uncertain": True}, dedupe_key=f"u{day}")
    r = ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", SKILL, True, source="remediation",
                                  dedupe_key="x1", now=NOW)
    assert r["to"] == "learning"


def test_quality_gate_still_closed_and_mastery_unreachable_from_conversation(pack):
    assert pack.rubric.correction["quality_gate"]["trusted_categories"] == []
