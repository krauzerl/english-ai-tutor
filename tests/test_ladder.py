"""F6: drabina L1–L4 w rozmowie (styl intensive): uczeń poprawia się sam, bez zapisu prób i bez mastery."""
import pytest

from tests.test_feedback import obs
from tutor.app import feedback as FB
from tutor.pedagogy import content as C


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def setup(repo, **kw):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I goed home.", cat="tense.past_simple", span="goed", fix="went", sev=2, **kw)
    return pid, sid


def test_ladder_climbs_one_level_per_turn_and_ends_with_the_form(repo, pack):
    pid, sid = setup(repo)
    notes = [FB.directive(repo, pack, pid, sid, "intensive", set(), "I goed home.")]
    for t in ("I goed there", "I goed again", "I goed one more time"):
        repo.add_turn(pid, sid, "user", t)
        notes.append(FB.directive(repo, pack, pid, sid, "intensive", set(), t))
    assert all(notes[:4]) and [f"step {i} of 4" in n for i, n in enumerate(notes, 1)] == [True] * 4
    assert "Do NOT give the correct form" in notes[0] and "went" in notes[3] and "Now say the correct form" in notes[3]
    assert "went or goed" in notes[2] or "goed or went" in notes[2]
    repo.add_turn(pid, sid, "user", "ok")
    assert FB.directive(repo, pack, pid, sid, "intensive", set(), "ok") is None          # po L4 koniec drabiny


def test_self_correction_ends_ladder_with_short_acknowledgement(repo, pack):
    pid, sid = setup(repo)
    FB.directive(repo, pack, pid, sid, "intensive", set(), "I goed home.")
    n = FB.directive(repo, pack, pid, sid, "intensive", set(), "Sorry, I went home.")
    assert n and "corrected themselves" in n and "step" not in n
    assert FB.directive(repo, pack, pid, sid, "intensive", set(), "More") is None


def test_ladder_drops_when_conversation_moves_on(repo, pack):
    pid, sid = setup(repo)
    FB.directive(repo, pack, pid, sid, "intensive", set(), "I goed home.")
    assert FB.directive(repo, pack, pid, sid, "intensive", set(), "I like football") is None
    assert FB.directive(repo, pack, pid, sid, "intensive", set(), "And tennis") is None
    assert repo.get_session_plan(pid, sid)["ladder"]["outcome"] == "dropped"


def test_ladder_never_starts_from_stt_suspect_or_uncertain_observations(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "voice")
    obs(repo, pid, sid, "I goed", kind="stt_suspect", cat="tense.past_simple", span="goed", fix="went", mode="voice")
    obs(repo, pid, sid, "x", cat="tense.past_simple", span="runned", fix="ran", conf="m")
    assert FB.directive(repo, pack, pid, sid, "intensive", set(), "hello") is None


def test_ladder_writes_no_attempts_and_no_mastery(repo, pack):
    pid, sid = setup(repo)
    FB.directive(repo, pack, pid, sid, "intensive", set(), "I goed home.")
    FB.directive(repo, pack, pid, sid, "intensive", set(), "I went home")
    assert repo.list_skill_states(pid) == [] and repo.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0] == 0


def test_periodic_and_summary_styles_unchanged(repo, pack):
    pid, sid = setup(repo)
    assert FB.directive(repo, pack, pid, sid, "summary", set(), "x") is None
    n = FB.directive(repo, pack, pid, sid, "periodic", set(), "x")
    assert n and "went" in n and "step" not in n


def test_ladder_isolated_per_session(repo, pack):
    pid, sid = setup(repo)
    FB.directive(repo, pack, pid, sid, "intensive", set(), "I goed home.")
    s2 = repo.start_session(pid, "voice")
    assert FB.directive(repo, pack, pid, s2, "intensive", set(), "hi") is None
