"""Ścieżki egzaminacyjne: wspólna architektura + jedna ścieżka demonstracyjna; uczciwa gotowość, brak punktów/prognoz."""
import json
import re
from datetime import UTC, datetime

import pytest

from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tests.test_placement import sentence
from tutor.app import exams as EX
from tutor.app import lesson as L
from tutor.pedagogy import content as C

NOW = datetime.now(UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def path():
    return EX.get("e8_english")


def correct(it):
    return L.Answer(sentence(it))


def run(repo, pack, pid, path, policy, sid=None):
    sid = sid or repo.start_session(pid, "exam")
    out, sp = [], []
    res = EX.run(repo, pack, pid, sid, path, lambda it, n: policy(it), out.append, now=NOW, speak=sp.append)
    return res, out, sp, sid


# --- architektura ---
def test_definition_is_valid_and_marks_official_data_as_unconfirmed(path):
    assert EX.validate(path) == []
    assert path["official"]["status"] == "confirm_in_cke_informator" and path["official"]["sources"]
    assert "nie jest oficjalnym wynikiem" in path["disclaimer_pl"]


def test_invalid_definition_is_rejected():
    assert EX.validate({"id": "x"}) and EX.validate({"id": "x", "name_pl": "n", "lang": "en", "official": {},
                                                    "sections": [], "disclaimer_pl": "d"})


def test_unknown_path_raises():
    with pytest.raises(EX.ExamError):
        EX.get("nope")


def test_coverage_is_honest_writing_has_no_materials(pack, path):
    cov = {c["section"]: c for c in EX.coverage(pack, path)}
    assert cov["writing"]["status"] == "no_materials" and cov["writing"]["items"] == 0
    assert cov["listening"]["items"] > 0 and cov["reading"]["items"] > 0 and cov["language_use"]["items"] > 0


def test_pick_takes_per_section_and_prefers_unseen(repo, pack, path):
    pid = repo.create_profile("ann")
    first = EX.pick(repo, pack, pid, path)
    secs = [s for s, _ in first]
    assert secs.count("listening") == 3 and secs.count("reading") == 3 and secs.count("language_use") == 6
    assert len({i.id for _, i in first}) == len(first)
    res, *_ = run(repo, pack, pid, path, correct)
    second = {i.id for _, i in EX.pick(repo, pack, pid, path)}
    assert len({i.id for _, i in first} & second) < len(first)             # nowe zadania zamiast powtórek


# --- sesja ---
def test_full_session_records_practice_attempts_without_mastery(repo, pack, path):
    pid = repo.create_profile("ann")
    res, out, sp, sid = run(repo, pack, pid, path, correct)
    assert res["finished"] and res["asked"] == 12
    rows = repo.conn.execute("SELECT feedback_json, source FROM attempt WHERE profile_id=?", (pid,)).fetchall()
    assert len(rows) == 12 and all(json.loads(r[0])["exam"] == "e8_english" and json.loads(r[0])["no_mastery"]
                                   for r in rows)
    assert all(s["status"] != "mastered" for s in repo.list_skill_states(pid))
    assert any("To nie jest wynik egzaminu" in x for x in out) and any("not an official result" in x for x in sp)


def test_listening_is_read_aloud_and_reading_has_stimulus_on_screen(repo, pack, path):
    pid = repo.create_profile("ann")
    _, out, sp, _ = run(repo, pack, pid, path, correct)
    lis = next(i for s, i in EX.pick(repo, pack, pid, path) if s == "listening")
    assert any(i.audio_text in sp for _, i in EX.pick(repo, pack, pid, path) if i.audio_text) or any(
        "nagranie odtworzone" in x for x in out)
    assert any("Look at the screen" in s for s in sp)                        # czytanie: tekst na ekranie
    assert lis


def test_unclear_stt_and_skip_are_unscored_not_errors(repo, pack, path):
    pid = repo.create_profile("ann")
    res, out, _, sid = run(repo, pack, pid, path, lambda it: L.Answer("mumble", "voice", None))
    assert res["finished"]
    h = EX.history(repo, pid)[0]
    assert h["scored"] == 0 and h["unscored"] == 12 and repo.list_errors(pid) == []
    assert repo.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0] == 0


def test_wrong_answers_scored_and_resume_without_duplicates(repo, pack, path):
    pid = repo.create_profile("ann")
    n = {"i": 0}

    def policy(it):
        n["i"] += 1
        return None if n["i"] > 4 else (correct(it) if n["i"] % 2 else L.Answer("zzz yyy"))
    r1, *_, sid = run(repo, pack, pid, path, policy)
    assert r1["quit"] and r1["asked"] == 4
    r2, *_ = run(repo, pack, pid, path, correct, sid=sid)
    assert r2["finished"] and r2["asked"] == 12
    assert repo.conn.execute("SELECT COUNT(*) FROM attempt WHERE profile_id=?", (pid,)).fetchone()[0] == 12
    h = EX.history(repo, pid)
    assert len(h) == 1 and h[0]["scored"] == 12 and h[0]["correct"] == 2 + 8   # 2 z 4 pierwszych + 8/8


def test_help_request_gets_no_hint_in_exam_mode(repo, pack, path):
    pid = repo.create_profile("ann")
    seq = iter(["I don't understand"])
    res, out, *_ = run(repo, pack, pid, path, lambda it: L.Answer(next(seq, None) or sentence(it)))
    assert any("nie ma podpowiedzi" in x for x in out) and res["finished"]


# --- gotowość ---
def test_readiness_without_data_says_not_checked(repo, pack, path):
    pid = repo.create_profile("ann")
    r = EX.readiness(repo, pack, pid, path)
    assert {s["label"] for s in r["sections"]} == {"nie sprawdzono", "nie sprawdzane przez aplikację"}
    assert r["overall"] == "za mało danych" and r["official_data_status"] == "confirm_in_cke_informator"


def test_readiness_after_one_session_is_too_little_data_and_has_no_points(repo, pack, path):
    pid = repo.create_profile("ann")
    run(repo, pack, pid, path, correct)
    r = EX.readiness(repo, pack, pid, path)
    labels = {s["section"]: s["label"] for s in r["sections"]}
    assert labels["listening"] == "za mało danych" and labels["writing"] == "nie sprawdzane przez aplikację"
    text = "\n".join(EX.render(r))
    assert not re.search(r"\d+\s*(pkt|punkt)", text) and "%" not in text and "nie są zadania CKE" in text


def test_readiness_isolated_between_profiles(repo, pack, path):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    run(repo, pack, a, path, correct)
    assert EX.readiness(repo, pack, b, path)["sections"][0]["scored"] == 0 and EX.history(repo, b) == []


# --- CLI ---
def test_cli_exam_list_and_session(repo, conn, pack, path):
    env = Env(repo, conn)
    code, out = env.go(Gated({}), ["--exam"], ev=EvalProv())
    text = "\n".join(out)
    assert code == 0 and "Gotowość" in text and "Uruchom ćwiczenia: `--exam e8_english`" in text
    answers = [sentence(i) for _, i in EX.pick(repo, pack, env.pid, path)]
    code, out = env.go(Gated({}, *answers), ["--no-audio", "--exam", "e8_english"], ev=EvalProv())
    assert code == 0 and EX.history(repo, env.pid)[0]["finished"]
    assert [s["status"] for s in repo.list_sessions(env.pid)] == ["ended"]


def test_cli_exam_unknown_path(repo, conn):
    env = Env(repo, conn)
    code, out = env.go(Gated({}), ["--no-audio", "--exam", "zzz"], ev=EvalProv())
    assert code == 0 and any("Nieznana ścieżka" in x for x in out) and repo.list_sessions(env.pid) == []
