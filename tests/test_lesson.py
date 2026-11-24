"""F5.8: pierwsza kompletna lekcja: cel → wyjaśnienie → ćwiczenia → informacja zwrotna → zapis → rozmowa z celem."""
from datetime import UTC, datetime

import pytest

from tests.test_cli_e2e import Env, EvalProv, Interrupt, WaitLines
from tests.test_feedback import Gated
from tests.test_stt_detailed import DetailedSTT
from tests.voice_fakes import FakeMic, Lines, blocks, tone
from tutor.app import lesson as L
from tutor.pedagogy import content as C
from tutor.voice import audio as A
from tutor.voice.stt import Transcript

SKILL = "en.gram.to_be_present"
NOW = datetime(2026, 11, 24, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


# --- materiał ---
def test_prepare_picks_closed_practice_items_for_the_goal(pack):
    sk, items = L.prepare(pack, SKILL)
    assert sk.id == SKILL and len(items) == 3
    assert all(SKILL in i.skill_ids and i.type not in C.OPEN_TYPES and i.answers for i in items)
    assert all("practice" in i.pools and i.review.status in ("ai_checked", "human_reviewed") for i in items)
    assert [i.difficulty for i in items] == sorted(i.difficulty for i in items)       # od łatwych


def test_prepare_rejects_unknown_or_unteachable_goal(pack):
    with pytest.raises(L.LessonError):
        L.prepare(pack, "en.nope")
    with pytest.raises(L.LessonError):
        L.prepare(pack, "en.listen.numbers_names")                                     # brak wyjaśnienia / zadań zamkniętych


def test_explanation_is_body_without_front_matter_or_sources_and_labelled(pack):
    sk, _ = L.prepare(pack, SKILL)
    t = L.explanation(pack, sk)
    assert "## Zasada" in t and "provenance" not in t and "## Źródła" not in t and "---" not in t
    assert "nie zostały zrecenzowane przez człowieka" in t                             # draft/ai_checked ⇒ etykieta


def test_check_answer_variants_and_mc_choice(pack):
    sk, items = L.prepare(pack, SKILL)
    gap = next(i for i in items if i.type == "gap")
    assert L.check(pack, gap, gap.answers[0].upper() + ".") and not L.check(pack, gap, "are")
    mc = next(i for i in items if i.type == "mc")
    n = mc.options.index(mc.answers[0]) + 1
    assert L.check(pack, mc, str(n)) and L.check(pack, mc, mc.answers[0]) and not L.check(pack, mc, "99")


# --- przebieg ćwiczeń z atrapą wejścia ---
def run_ex(repo, pack, answers, *, kind="text"):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    out = []
    feed = list(answers)

    def ask(item, i):
        return feed.pop(0) if feed else None

    sk, items = L.prepare(pack, SKILL)
    res = L.run_exercises(repo, pack, pid, sid, sk, items, ask, out.append, now=NOW)
    return pid, sid, items, out, res


def A_(text, mode="text", low=None):
    return L.Answer(text, mode, low)


def test_all_correct_first_try_recorded_without_hints(repo, pack):
    _, items = L.prepare(pack, SKILL)
    pid, sid, items, out, res = run_ex(repo, pack, [A_(i.answers[0]) for i in items])
    h = repo.attempt_history(pid, SKILL)
    assert [(a["correct"], a["hint_level"], a["source"]) for a in h] == [(1, 0, "practice")] * 3
    assert res.correct == 3 and res.total == 3
    assert not any("Spróbuj jeszcze raz" in o for o in out)


def test_wrong_then_right_gives_hint_from_error_category_and_records_hint_level(repo, pack):
    _, items = L.prepare(pack, SKILL)
    answers = [A_("zzz"), A_(items[0].answers[0]), A_(items[1].answers[0]), A_(items[2].answers[0])]
    pid, sid, items, out, res = run_ex(repo, pack, answers)
    h = repo.attempt_history(pid, SKILL)
    assert [(a["correct"], a["hint_level"]) for a in h] == [(1, 1), (1, 0), (1, 0)]
    cat = next(c for c in pack.errors.categories if c.id in pack.skills[SKILL].error_categories)
    assert any(cat.l1 in o for o in out) and any("Spróbuj jeszcze raz" in o for o in out)


def test_wrong_twice_reveals_answer_and_explanation_and_records_incorrect(repo, pack):
    _, items = L.prepare(pack, SKILL)
    answers = [A_("zzz"), A_("yyy"), A_(items[1].answers[0]), A_(items[2].answers[0])]
    pid, sid, items, out, res = run_ex(repo, pack, answers)
    a = repo.attempt_history(pid, SKILL)
    assert [x["correct"] for x in a] == [0, 1, 1] and a[0]["response"] == "yyy"
    assert any(items[0].answers[0] in o for o in out) and any(items[0].explanation_pl in o for o in out)
    assert res.correct == 2


def test_voice_wrong_with_low_confidence_is_not_counted_as_error(repo, pack):
    _, items = L.prepare(pack, SKILL)
    ans = [A_("they is", "voice", ["is"]), A_(items[0].answers[0]), A_(items[1].answers[0]), A_(items[2].answers[0])]
    pid, sid, items, out, res = run_ex(repo, pack, ans)
    assert [(a["correct"], a["hint_level"]) for a in repo.attempt_history(pid, SKILL)] == [(1, 0)] * 3
    assert any("nie jestem pewien" in o.lower() for o in out)                          # prośba o powtórzenie, nie błąd


def test_voice_wrong_without_stt_data_is_not_counted_either(repo, pack):
    _, items = L.prepare(pack, SKILL)
    ans = [A_("zzz", "voice", None), A_(items[0].answers[0]), A_(items[1].answers[0]), A_(items[2].answers[0])]
    pid, *_ = run_ex(repo, pack, ans)
    assert all(a["correct"] == 1 and a["hint_level"] == 0 for a in repo.attempt_history(pid, SKILL))


def test_voice_wrong_with_confident_stt_is_a_real_error(repo, pack):
    _, items = L.prepare(pack, SKILL)
    ans = [A_("zzz", "voice", []), A_("yyy", "voice", []), A_(items[1].answers[0]), A_(items[2].answers[0])]
    pid, *_ = run_ex(repo, pack, ans)
    assert [a["correct"] for a in repo.attempt_history(pid, SKILL)][0] == 0


def test_one_lesson_never_marks_skill_mastered_and_summary_says_so(repo, pack):
    _, items = L.prepare(pack, SKILL)
    pid, sid, items, out, res = run_ex(repo, pack, [A_(i.answers[0]) for i in items])
    st = repo.get_skill_state(pid, SKILL)
    assert st["status"] == "learning" and st["mastered_at"] is None
    s = L.summary(res)
    assert "nie oznacza opanowania" in s and "3/3" in s


def test_quit_during_exercises_keeps_recorded_progress_and_resumes(repo, pack):
    _, items = L.prepare(pack, SKILL)
    pid, sid, items, out, res = run_ex(repo, pack, [A_(items[0].answers[0])])             # potem EOF = wyjście
    assert res.quit and len(repo.attempt_history(pid, SKILL)) == 1
    sk, items = L.prepare(pack, SKILL)
    out2 = []
    feed = [A_(i.answers[0]) for i in items[1:]]
    res2 = L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i: feed.pop(0), out2.append, now=NOW)
    assert not res2.quit and len(repo.attempt_history(pid, SKILL)) == 3                  # pierwsza nie powtórzona
    assert not any(items[0].prompt in o for o in out2)


# --- CLI end-to-end ---
@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


def goal_in_eval_prompts(ev):
    return any(SKILL in m.content for call in ev.calls for m in call)


def test_cli_lesson_text_end_to_end(env, pack):
    _, items = L.prepare(pack, SKILL)
    answers = [items[0].answers[0], "zzz", items[1].answers[0], items[2].answers[0]]
    ev = EvalProv()
    code, out = env.go(WaitLines(lambda: env.applied() >= 1, *answers, "She tired"), ["--no-audio", "--lesson", SKILL],
                       ev=ev)
    assert code == 0
    text = "\n".join(out)
    assert "Cel lekcji" in text and "en.gram.to_be_present" in text and "## Zasada" in text
    assert "Spróbuj jeszcze raz" in text and "Wynik ćwiczeń: 3/3" in text and "nie oznacza opanowania" in text
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and s[0]["kind"] == "lesson" and s[0]["status"] == "ended"
    assert env.repo.get_session_plan(env.pid, s[0]["id"])["lesson"] == SKILL
    hist = env.repo.attempt_history(env.pid, SKILL)
    assert len(hist) == 3 and [a["hint_level"] for a in hist] == [0, 1, 0]              # tylko ćwiczenia; rozmowa nie dodaje prób
    assert [u["text"] for u in env.users()] == ["She tired"]                             # odpowiedzi ćwiczeń to nie tury rozmowy
    assert goal_in_eval_prompts(ev) and env.applied() == 1                               # cel trafił do oceny
    st = env.repo.get_skill_state(env.pid, SKILL)
    assert st["status"] == "learning" and st["mastered_at"] is None


def test_cli_lesson_voice_answer_with_stt_data(env, pack):
    _, items = L.prepare(pack, SKILL)
    mic = FakeMic(loop=blocks(tone(0.1))[0])
    stt = DetailedSTT(Transcript(items[0].answers[0], []))
    ev = EvalProv()
    env.go(Gated({}, "", "", items[1].answers[0], items[2].answers[0], "q"), ["--mode", "ptt", "--lesson", SKILL],
           ev=ev, mic=mic, stt=stt, sink=A.SimSink())
    h = env.repo.attempt_history(env.pid, SKILL)
    assert len(h) == 3 and all(a["correct"] == 1 and a["hint_level"] == 0 for a in h)
    assert h[0]["response"] == items[0].answers[0]


def test_cli_lesson_interrupt_and_resume_has_no_duplicates(env, pack):
    _, items = L.prepare(pack, SKILL)
    env.go(Interrupt(items[0].answers[0]), ["--no-audio", "--lesson", SKILL], ev=EvalProv())
    s = env.repo.list_sessions(env.pid)
    assert len(s) == 1 and s[0]["status"] == "paused" and len(env.repo.attempt_history(env.pid, SKILL)) == 1
    code, out = env.go(Lines(items[1].answers[0], items[2].answers[0], "q"), ["--no-audio", "--lesson", SKILL],
                       ev=EvalProv())
    text = "\n".join(out)
    assert "Wznawiam" in text and items[0].prompt not in text and items[1].prompt in text
    assert len(env.repo.list_sessions(env.pid)) == 1 and len(env.repo.attempt_history(env.pid, SKILL)) == 3
    assert env.repo.get_skill_state(env.pid, SKILL)["status"] == "learning"


def test_cli_lesson_unknown_goal_exits_with_error(env):
    code, out = env.go(Lines("q"), ["--no-audio", "--lesson", "en.nope"], ev=EvalProv())
    assert code == 1 and env.repo.list_sessions(env.pid) == []


def test_repeated_lessons_on_several_days_never_auto_master(repo, pack):
    """Bez straży silnik przyznałby `mastered` (p ≥ 0,85 i poprawne próby produkcyjne w ≥ 2 dniach)."""
    pid = repo.create_profile("ann")
    sk, items = L.prepare(pack, SKILL)
    for day in range(1, 4):
        sid = repo.start_session(pid, "lesson")
        answers = {i.id: A_(i.answers[0]) for i in items}
        L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i, a=answers: a[it.id], lambda s: None, now=NOW)
        if day < 3:                                                    # przesuń próby tej lekcji na wcześniejszy dzień
            repo.conn.execute("UPDATE attempt SET created_at=? WHERE session_id=?",
                              (f"2026-01-0{day}T10:00:00.000Z", sid))
    st = repo.get_skill_state(pid, SKILL)
    assert len(repo.attempt_days(pid, SKILL)) == 3 and st["p_mastery"] > 0.85       # warunki silnika spełnione
    assert st["status"] == "learning" and st["mastered_at"] is None and st["verify_due_at"] is None


def test_allow_mastery_guard_is_opt_in_default_engine_unchanged(repo, pack):
    """Straż jest tylko w ścieżce lekcji: domyślne `apply_item_attempt` (np. AGV/remediation) działa jak w F4."""
    from tutor.app import ingest
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "lesson")
    for day in range(1, 4):
        repo.add_attempt(pid, SKILL, True, session_id=sid, created_at=f"2026-01-0{day}T10:00:00.000Z",
                         source="practice", feedback={"bkt": "production"}, dedupe_key=f"h{day}")
    r = ingest.apply_item_attempt(repo, pack, pid, sid, "en.f46.gram.a1.01", SKILL, True, source="practice",
                                  dedupe_key="x1", now=NOW)
    assert r["to"] == "mastered"                                    # domyślnie silnik awansuje jak dawniej
    pid2 = repo.create_profile("bob")
    sid2 = repo.start_session(pid2, "lesson")
    for day in range(1, 4):
        repo.add_attempt(pid2, SKILL, True, session_id=sid2, created_at=f"2026-01-0{day}T10:00:00.000Z",
                         source="practice", feedback={"bkt": "production", "no_mastery": True}, dedupe_key=f"h{day}")
    r = ingest.apply_item_attempt(repo, pack, pid2, sid2, "en.f46.gram.a1.01", SKILL, True, source="practice",
                                  dedupe_key="x1", now=NOW, allow_mastery=False)
    assert r["to"] == "learning" and repo.get_skill_state(pid2, SKILL)["status"] == "learning"
    assert repo.get_skill_state(pid, SKILL)["status"] == "mastered"  # izolacja profili
