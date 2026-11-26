"""F7: pełna diagnoza kompetencji — adaptacja, przerwanie/wznowienie, profil, uczciwe etykiety."""
from datetime import UTC, datetime

import pytest

from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tutor.app import diagnostic as DG
from tutor.app import lesson as L
from tutor.pedagogy import content as C
from tutor.pedagogy import diagnosis as D

NOW = datetime(2026, 11, 26, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def oracle(pack, skill_level: dict[str, str]):
    """Uczeń symulowany: poprawnie na zadaniach do swojego poziomu w danym obszarze, źle powyżej."""
    order = ["A1", "A2", "B1", "B2", "C1"]

    def ask(item, n):
        if isinstance(item, dict):                                     # zadanie otwarte
            return L.Answer("I live in Gdansk and I work as a nurse. I like walking with my dog in the park.",
                            "text", None)
        ok = order.index(item.cefr) <= order.index(skill_level.get(item.area, "B1"))
        return L.Answer(item.answers[0] if ok else "zzz wrong", "text", None)
    return ask


def run(repo, pack, pid, ask, areas=DG.AREAS, **kw):
    sid = repo.start_session(pid, "assessment")
    out = []
    rep = DG.run(repo, pack, pid, sid, ask, out.append, now=NOW, areas=areas, **kw)
    return sid, rep, out


def test_new_profile_without_diagnosis_has_untested_profile(repo, pack):
    pid = repo.create_profile("ann")
    p = DG.profile(repo, pack, pid)
    assert p["untested"] == list(DG.AREAS) and all(not a["tested"] for a in p["areas"])
    assert "nie jest oficjalny" in p["notice"]


def test_bank_covers_all_levels_for_closed_areas(pack):
    cov = DG.coverage(pack)
    for a in DG.CLOSED:
        assert all(n >= 3 for n in cov[a].values()), (a, cov[a])


def test_different_levels_per_area_and_no_mastery(repo, pack):
    pid = repo.create_profile("ann")
    ask = oracle(pack, {"grammar": "C1", "vocabulary": "A1", "reading": "B1"})
    sid, rep, out = run(repo, pack, pid, ask, areas=("grammar", "vocabulary", "reading"))
    th = {o.area: o.result["theta"] for o in rep.outcomes if o.status == "estimated"}
    assert th["grammar"] > th["reading"] > th["vocabulary"]
    assert all(s["status"] != "mastered" for s in repo.list_skill_states(pid))
    assert all("wstępnie" in o.result["label"] for o in rep.outcomes if o.result)


def test_cross_area_prior_moves_start_of_next_area(repo, pack):
    pid = repo.create_profile("ann")
    sid, rep, _ = run(repo, pack, pid, oracle(pack, {"grammar": "C1", "vocabulary": "C1"}),
                      areas=("grammar", "vocabulary"))
    st = repo.get_session_plan(pid, sid)["assessment"]["states"]
    assert st["grammar"].get("prior") is None and st["vocabulary"]["prior"][0] > 3.0   # start bliżej wyniku gramatyki
    first_vocab = st["vocabulary"]["asked"][0]["b"]
    assert first_vocab > D.item_b(type("I", (), {"cefr": "A2", "difficulty": 0.0})(), pack.rubric)


def test_interrupt_and_resume_without_losing_answers(repo, pack):
    pid = repo.create_profile("ann")
    base = oracle(pack, {"grammar": "B1"})
    calls = {"n": 0}

    def ask(item, n):
        calls["n"] += 1
        return None if calls["n"] == 3 else base(item, n)
    sid, rep, _ = run(repo, pack, pid, ask, areas=("grammar",))
    assert rep.quit
    asked = len(repo.get_session_plan(pid, sid)["assessment"]["states"]["grammar"]["asked"])
    assert asked == 2
    rep2 = DG.run(repo, pack, pid, sid, base, lambda s: None, now=NOW)
    st = repo.get_session_plan(pid, sid)["assessment"]
    assert not rep2.quit and st["done"] and len(st["states"]["grammar"]["asked"]) >= 5
    ids = [a["id"] for a in st["states"]["grammar"]["asked"]]
    assert len(ids) == len(set(ids))                                              # bez powtórek po wznowieniu


def test_text_mode_marks_listening_and_speaking_not_tested(repo, pack):
    pid = repo.create_profile("ann")
    sid, rep, _ = run(repo, pack, pid, oracle(pack, {}), areas=("listening", "speaking", "writing"),
                      audio=False, mode="text")
    st = {o.area: o.status for o in rep.outcomes}
    assert st == {"listening": "not_tested", "speaking": "not_tested", "writing": "evidence"}
    p = DG.profile(repo, pack, pid)
    w = next(a for a in p["areas"] if a["area"] == "writing")
    assert w["tested"] and w["latest"] is None and w["open_evidence"][0]["words"] > 10     # dowód, bez poziomu
    assert "listening" in p["untested"] and "writing" not in p["untested"]


def test_listening_is_spoken_twice_when_audio(repo, pack):
    pid = repo.create_profile("ann")
    spoken = []
    run(repo, pack, pid, oracle(pack, {"listening": "B1"}), areas=("listening",), speak=spoken.append)
    assert any(s.count("Once more") == 1 for s in spoken)


def test_unclear_stt_never_lowers_result(repo, pack):
    pid = repo.create_profile("ann")
    base = oracle(pack, {"grammar": "B2"})

    def ask(item, n):
        if n == 1:
            return L.Answer("mm", "voice", ["mm"])                                # niepewne rozpoznanie
        return base(item, n)
    sid, rep, _ = run(repo, pack, pid, ask, areas=("grammar",), mode="voice")
    c = rep.outcomes[0].counts
    assert c["unverified"] >= 1 and c["wrong"] == 0


def test_repeated_assessment_keeps_history(repo, pack):
    pid = repo.create_profile("ann")
    run(repo, pack, pid, oracle(pack, {"grammar": "A2"}), areas=("grammar",))
    run(repo, pack, pid, oracle(pack, {"grammar": "B2"}), areas=("grammar",))
    g = next(a for a in DG.profile(repo, pack, pid)["areas"] if a["area"] == "grammar")
    assert len(g["history"]) == 2 and g["history"][1]["theta"] > g["history"][0]["theta"]


def test_profile_strengths_weaknesses_and_recommendations(repo, pack):
    pid = repo.create_profile("ann")
    run(repo, pack, pid, oracle(pack, {"grammar": "C1", "vocabulary": "A1", "reading": "B1"}),
        areas=("grammar", "vocabulary", "reading"))
    p = DG.profile(repo, pack, pid)
    assert "vocabulary" in p["weaknesses"] and "grammar" in p["strengths"]
    assert p["recommendations"][0]["area"] == "vocabulary" and p["recommendations"][0]["skills"]
    assert {"listening", "writing", "speaking"} <= set(p["untested"])


def test_results_feed_lesson_planning(repo, pack):
    from tutor.app import goal as G
    pid = repo.create_profile("ann")
    run(repo, pack, pid, oracle(pack, {"grammar": "B2", "vocabulary": "B2"}), areas=("grammar", "vocabulary"))
    ch = G.choose(repo, pack, pid, NOW)
    assert ch is not None and ch.source != "starter"                              # planer korzysta z wyniku


def test_profiles_isolated(repo, pack):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    run(repo, pack, a, oracle(pack, {"grammar": "B1"}), areas=("grammar",))
    assert DG.profile(repo, pack, b)["untested"] == list(DG.AREAS)


def test_cli_assess_interrupt_and_resume(repo, conn):
    env = Env(repo, conn)
    pack = C.load("en")
    first = next(iter(DG.items_for(pack, "grammar")))
    code, out = env.go(Gated({}, "q"), ["--no-audio", "--assess", "grammar"], ev=EvalProv())
    s = repo.list_sessions(env.pid)[-1]
    assert code == 0 and s["kind"] == "assessment" and s["status"] == "paused" and first
    code, out = env.go(Gated({}, "q"), ["--no-audio", "--assess"], ev=EvalProv())
    assert any("Wznawiam diagnozę" in x for x in out)


def test_cli_assess_rejects_unknown_area(repo, conn):
    Env(repo, conn)                                       # tworzy profil „ann”
    errs = []
    from tutor.voice.cli import run as cli_run
    code = cli_run(["--voice", "--profile", "ann", "--no-audio", "--assess", "maths"], eval_llm=EvalProv(),
                   out=lambda s: None, err=errs.append, db=conn, lines=Gated({}))
    assert code == 1 and errs
