"""F7: pomiar postępów — tylko wiarygodne dowody, trudność zadań, brak sztucznego postępu, trend przy dość danych."""
from datetime import UTC, datetime, timedelta

import pytest

from tutor.app import growth as GR
from tutor.pedagogy import content as C

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def items(pack, area, levels):
    return [i for i in pack.items.values() if i.area == area and i.cefr in levels and i.answers]


def add(repo, pid, sid, it, ok, when, hint=0, fb=None):
    repo.add_attempt(pid, it.skill_ids[0], ok, session_id=sid, item_id=it.id, created_at=when.isoformat(),
                     hint_level=hint, feedback=fb)


@pytest.fixture
def env(repo):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    return repo, pid, sid


def test_no_data_means_no_trend(env, pack):
    repo, pid, sid = env
    g = GR.build(repo, pack, pid, NOW)
    assert all(g["areas"][a]["compare"]["status"] == "insufficient" for a in GR.AREAS)
    assert g["areas"]["grammar"]["estimate"] is None and not g["retention"]["enough"]


def test_repeating_same_item_does_not_raise_estimate(env, pack):
    repo, pid, sid = env
    it = items(pack, "grammar", ("A1",))[0]
    add(repo, pid, sid, it, False, NOW - timedelta(days=2))
    for k in range(10):
        add(repo, pid, sid, it, True, NOW - timedelta(days=1, minutes=k))
    g = GR.build(repo, pack, pid, NOW)["areas"]["grammar"]
    assert g["independent"] == 1 and g["repeats_excluded"] == 10 and g["estimate"]["correct"] == 0


def test_after_hint_is_counted_separately(env, pack):
    repo, pid, sid = env
    its = items(pack, "grammar", ("A2",))[:3]
    for it in its:
        add(repo, pid, sid, it, True, NOW - timedelta(hours=1), hint=1)
    g = GR.build(repo, pack, pid, NOW)["areas"]["grammar"]
    assert g["estimate"] is None and g["after_hint"] == {"n": 3, "correct": 3}


def test_difficulty_matters(repo, pack):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    sa, sb = repo.start_session(a, "lesson"), repo.start_session(b, "lesson")
    for it in items(pack, "grammar", ("A1",))[:6]:
        add(repo, a, sa, it, True, NOW - timedelta(hours=2))
    for it in items(pack, "grammar", ("B2", "C1"))[:6]:
        add(repo, b, sb, it, True, NOW - timedelta(hours=2))
    ea = GR.build(repo, pack, a, NOW)["areas"]["grammar"]["estimate"]
    eb = GR.build(repo, pack, b, NOW)["areas"]["grammar"]["estimate"]
    assert ea["correct"] == eb["correct"] == 6 and eb["theta"] > ea["theta"]


def test_improvement_on_new_items_shows_trend_up(env, pack):
    repo, pid, sid = env
    by = {lv: items(pack, "grammar", (lv,)) for lv in ("A1", "A2", "B1", "B2", "C1")}
    early = [it for lv in by for it in by[lv][:2]]
    late = [it for lv in by for it in by[lv][2:4]]
    for k, it in enumerate(early):
        add(repo, pid, sid, it, it.cefr == "A1", NOW - timedelta(days=40, minutes=k))
    for k, it in enumerate(late):
        add(repo, pid, sid, it, True, NOW - timedelta(days=2, minutes=k))
    c = GR.build(repo, pack, pid, NOW)["areas"]["grammar"]["compare"]
    assert c["status"] == "up" and c["first"]["n"] >= 8 and c["last"]["n"] >= 8


def test_small_sample_gives_no_trend(env, pack):
    repo, pid, sid = env
    pool = items(pack, "vocabulary", ("A1", "A2", "B1"))
    for k, it in enumerate(pool[:3]):
        add(repo, pid, sid, it, False, NOW - timedelta(days=40, minutes=k))
    for k, it in enumerate(pool[3:6]):
        add(repo, pid, sid, it, True, NOW - timedelta(days=1, minutes=k))
    assert GR.build(repo, pack, pid, NOW)["areas"]["vocabulary"]["compare"]["status"] == "insufficient"


def test_stt_uncertain_attempt_does_not_lower_estimate(env, pack):
    repo, pid, sid = env
    it = items(pack, "grammar", ("A1",))[0]
    add(repo, pid, sid, it, False, NOW - timedelta(hours=1), fb={"stt_uncertain": True})
    assert GR.build(repo, pack, pid, NOW)["areas"]["grammar"]["estimate"] is None


def test_retention_after_days(env, pack):
    repo, pid, sid = env
    its = [i for i in pack.items.values() if i.answers and i.skill_ids[0] == items(pack, "grammar", ("A1",))[0].skill_ids[0]]
    add(repo, pid, sid, its[0], True, NOW - timedelta(days=10))
    add(repo, pid, sid, its[1], True, NOW - timedelta(days=1), fb={"review": 1})
    r = GR.build(repo, pack, pid, NOW)["retention"]
    assert r["after_7_days"] == {"correct": 1, "n": 1} and r["reviews"] == {"correct": 1, "n": 1}


def test_time_and_badges_are_not_evidence(env, pack):
    repo, pid, sid = env
    repo.conn.execute("INSERT INTO achievement(profile_id,code) VALUES (?,?)", (pid, "streak_3"))
    g = GR.build(repo, pack, pid, NOW)
    assert g["evidence"]["first_attempts"] == 0 and "XP i odznaki" in g["not_evidence"]
