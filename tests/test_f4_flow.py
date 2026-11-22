"""F4: idempotencja (decyzje 3–4), korekta, planer, raport, T-LANG-1, T-ARCH-1."""
import ast
import dataclasses
import json
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tests.helpers import promote
from tutor.app import ingest
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import correction as K
from tutor.pedagogy import diagnosis as D
from tutor.pedagogy import planner as P
from tutor.pedagogy import report as RP
from tutor.pedagogy.mastery import SkillState
from tutor.pedagogy.schemas import Obs, TurnEval, Use, Utt

NOW = datetime(2026, 11, 22, 10, tzinfo=UTC)
GOAL = "en.gram.past_simple_regular"
GOALS = {GOAL}
XX_ROOT = Path(__file__).parent / "fixtures" / "content"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def ctx(repo, pack):
    pid = repo.create_profile("P")
    sid = repo.start_session(pid, "chat")
    return repo, pack, pid, sid


def turn(repo, pid, sid, text, mode="text"):
    return repo.add_turn(pid, sid, "user", text)


def evaluate(pack, text, o=(), t=(), cm="na", cq="", mode="text", ev=True, failure="unrated", low=frozenset()):
    e = TurnEval(u=[Utt(i=0, o=list(o), t=list(t), cm=cm, cq=cq)]) if ev else None
    return A.evaluate_batch(e, [text], input_modes=[mode], low_probs=[set(low)], pack=pack, goals=GOALS,
                            failure=failure)[0]


def apply(repo, pack, pid, sid, tid, res, text, now=NOW, mode="text"):
    return ingest.apply_turn_evaluation(repo, pack, pid, sid, tid, res, input_mode=mode, text=text, goals=GOALS,
                                        now=now, model="m", prompt_version="turn_eval.v1")


def snapshot(repo, pid):
    c = repo.conn
    q = lambda sql: c.execute(sql, (pid,)).fetchall()  # noqa: E731
    return {"obs": [tuple(r) for r in q("SELECT kind,span,category,status FROM observation WHERE profile_id=? ORDER BY id")],
            "att": [tuple(r) for r in q("SELECT skill_id,correct,source,dedupe_key FROM attempt WHERE profile_id=? ORDER BY id")],
            "ss": [tuple(r) for r in q("SELECT skill_id,p_mastery,attempts,status FROM skill_state WHERE profile_id=? ORDER BY skill_id")],
            "el": [tuple(r) for r in q("SELECT category,skill_id,count,status,reopened FROM error_log WHERE profile_id=? ORDER BY id")],
            "srs": [tuple(r) for r in q("SELECT card_type,ref_id,fsrs_json,due_at FROM srs_card WHERE profile_id=? ORDER BY ref_id")],
            "tm": [tuple(r) for r in q("SELECT eval_status,comm,applied_at FROM turn_meta WHERE profile_id=? ORDER BY turn_id")]}


ERR = Obs(s="I goed", f="I went", k="error", c="tense.past_simple", v=2, p="h")
USE_OK = Use(id=GOAL, r="ok", s="I walked")


# --- idempotencja ---
def test_reanalysis_of_same_utterance_does_not_double_update(ctx):  # decyzja 3
    repo, pack, pid, sid = ctx
    text = "Yesterday I goed home and I walked"
    tid = turn(repo, pid, sid, text)
    res = evaluate(pack, text, o=[ERR], t=[USE_OK], cm="ok", cq="I walked")
    r1 = apply(repo, pack, pid, sid, tid, res, text)
    assert r1["applied"] and r1["events"]["new_observations"] == 1
    snap = snapshot(repo, pid)
    assert len(snap["obs"]) == 1 and len(snap["att"]) == 2 and snap["srs"]
    r2 = apply(repo, pack, pid, sid, tid, res, text, now=NOW + timedelta(hours=1))
    assert not r2["applied"] and r2["reason"] == "already_applied"
    assert snapshot(repo, pid) == snap


def test_reanalysis_after_crash_before_ledger_still_idempotent(ctx):
    """Nawet gdy ledger tury zniknie (np. awaria), unikalne klucze i stany pochodne nie dublują postępów."""
    repo, pack, pid, sid = ctx
    text = "Yesterday I goed home and I walked"
    tid = turn(repo, pid, sid, text)
    res = evaluate(pack, text, o=[ERR], t=[USE_OK])
    apply(repo, pack, pid, sid, tid, res, text)
    snap = snapshot(repo, pid)
    repo.conn.execute("UPDATE turn_meta SET applied_at=NULL WHERE turn_id=?", (tid,))
    r = apply(repo, pack, pid, sid, tid, res, text, now=NOW + timedelta(days=1))
    assert r["applied"] and r["events"]["new_observations"] == 0
    after = snapshot(repo, pid)
    for k in ("obs", "att", "el"):
        assert after[k] == snap[k], k
    assert after["ss"][0][2] == snap["ss"][0][2]                      # liczba prób nie wzrosła
    assert after["srs"] == snap["srs"]                                # karta FSRS nie była oceniana drugi raz


def test_failed_apply_rolls_back_everything(ctx, monkeypatch):
    repo, pack, pid, sid = ctx
    text = "Yesterday I goed home"
    tid = turn(repo, pid, sid, text)
    monkeypatch.setattr(ingest, "_recompute_errors", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        apply(repo, pack, pid, sid, tid, evaluate(pack, text, o=[ERR]), text)
    assert snapshot(repo, pid) == {"obs": [], "att": [], "ss": [], "el": [], "srs": [], "tm": []}
    monkeypatch.undo()
    assert apply(repo, pack, pid, sid, tid, evaluate(pack, text, o=[ERR]), text)["applied"]


def test_correct_vs_unrated_vs_aborted_vs_rejected_in_db(ctx):  # decyzja 4
    repo, pack, pid, sid = ctx
    ok_text = "I walked home"
    t_ok = turn(repo, pid, sid, ok_text)
    r = apply(repo, pack, pid, sid, t_ok, evaluate(pack, ok_text, t=[USE_OK], cm="ok", cq="walked home"), ok_text)
    assert r["applied"]
    others = []
    for failure in ("unrated", "aborted", "rejected"):
        t = turn(repo, pid, sid, f"text {failure}")
        res = evaluate(pack, "x", ev=False, failure=failure)
        out = apply(repo, pack, pid, sid, t, res, f"text {failure}")
        assert out == {"applied": False, "reason": f"not_rated:{failure}", "events": {}}
        others.append(repo.get_turn_meta(pid, t))
    assert [m["eval_status"] for m in others] == ["unrated", "aborted", "rejected"]
    assert all(m["comm"] is None and m["applied_at"] is None for m in others)
    meta_ok = repo.get_turn_meta(pid, t_ok)
    assert meta_ok["eval_status"] == "evaluated" and meta_ok["comm"] == "ok" and meta_ok["applied_at"]
    assert len(repo.attempt_history(pid, GOAL)) == 1                     # tylko poprawna wypowiedź dała dowód
    # nieoceniona może zostać oceniona później (nie jest „poprawna”, tylko czeka)
    t_late = turn(repo, pid, sid, "Yesterday I goed")
    apply(repo, pack, pid, sid, t_late, evaluate(pack, "x", ev=False), "Yesterday I goed")
    late = apply(repo, pack, pid, sid, t_late, evaluate(pack, "Yesterday I goed", o=[ERR]), "Yesterday I goed")
    assert late["applied"] and len(repo.list_observations(pid)) == 1


def test_dropped_and_stt_observations_stored_but_never_counted(ctx):
    repo, pack, pid, sid = ctx
    text = "yesterday I went home"
    tid = turn(repo, pid, sid, text)
    bad = Obs(s="I goed", f="I went", k="error", c="tense.past_simple", v=2, p="h")     # span nieobecny
    low = Obs(s="went", f="go", k="error", c="tense.present_simple", v=2, p="h")
    res = evaluate(pack, text, o=[bad, low], mode="voice", low={"went"})
    apply(repo, pack, pid, sid, tid, res, text, mode="voice")
    rows = {(o["kind"], o["status"]): o for o in repo.list_observations(pid)}
    assert ("error", "dropped") in rows and rows[("error", "dropped")]["drop_reason"] == "span_not_found"
    assert ("stt_suspect", "valid") in rows
    assert repo.list_errors(pid) == [] and repo.list_skill_states(pid) == [] and repo.attempt_history(pid, GOAL) == []


def test_invalid_positive_and_comm_evidence_not_stored(ctx):  # decyzja 4: dowody pozytywne i komunikatywność
    repo, pack, pid, sid = ctx
    text = "I walked home"
    tid = turn(repo, pid, sid, text)
    res = evaluate(pack, text, t=[Use(id=GOAL, r="ok", s="I ran"), Use(id="en.gram.nope", r="ok", s="I walked")],
                   cm="ok", cq="invented quote")
    apply(repo, pack, pid, sid, tid, res, text)
    assert repo.attempt_history(pid, GOAL) == []
    m = repo.get_turn_meta(pid, tid)
    assert m["eval_status"] == "evaluated" and m["comm"] == "na" and m["comm_quote"] is None


def test_item_attempt_idempotent_including_fsrs(ctx):
    repo, pack, pid, sid = ctx
    kw = dict(source="practice", dedupe_key="s1:item1:1", now=NOW)
    r1 = ingest.apply_item_attempt(repo, pack, pid, sid, "en.pilot.gram.a2.01", GOAL, True, **kw)
    snap = snapshot(repo, pid)
    r2 = ingest.apply_item_attempt(repo, pack, pid, sid, "en.pilot.gram.a2.01", GOAL, True,
                                   **{**kw, "now": NOW + timedelta(days=3)})
    assert r1["applied"] and not r2["applied"] and r2["reason"] == "already_applied"
    assert snapshot(repo, pid) == snap
    again = ingest.apply_item_attempt(repo, pack, pid, sid, "en.pilot.gram.a2.01", GOAL, True,
                                      **{**kw, "dedupe_key": "s1:item1:2"})      # nowa próba tego samego zadania
    assert again["applied"] and len(repo.attempt_history(pid, GOAL)) == 2


def test_mastery_two_days_through_ingest(ctx):
    repo, pack, pid, sid = ctx
    for k in range(6):
        ingest.apply_item_attempt(repo, pack, pid, sid, "en.pilot.gram.a2.01", GOAL, True, source="practice",
                                  dedupe_key=f"d1:{k}", now=NOW, created_at=None) if False else None
    for k in range(6):
        repo.add_attempt(pid, GOAL, True, session_id=sid, created_at="2026-11-20T10:00:00.000Z", source="practice",
                         feedback={"bkt": "production"}, dedupe_key=f"day1:{k}")
    ingest._recompute_skill(repo, pack, pid, GOAL, NOW)
    assert repo.get_skill_state(pid, GOAL)["status"] == "learning"        # jeden dzień
    ingest.apply_item_attempt(repo, pack, pid, sid, "en.pilot.gram.a2.01", GOAL, True, source="practice",
                              dedupe_key="day2", now=NOW)
    st = repo.get_skill_state(pid, GOAL)
    assert st["status"] == "mastered" and st["verify_due_at"].startswith("2026-11-29")


def test_error_log_lifecycle_through_ingest(ctx):
    repo, pack, pid, sid = ctx
    for k, day in enumerate((18, 19, 20)):
        t = f"Yesterday I goed number {k}"
        tid = turn(repo, pid, sid, t)
        o = Obs(s="I goed", f="I went", k="error", c="morphology.irregular_past", v=2, p="h")
        apply(repo, pack, pid, sid, tid, evaluate(pack, t, o=[o]), t, now=datetime(2026, 11, day, tzinfo=UTC))
    el = repo.list_errors(pid)[0]
    assert el["count"] == 3 and el["status"] == "recurring" and el["example_observation_id"]


def test_retention_pass_fail_and_idempotency(ctx):
    repo, pack, pid, sid = ctx
    mastered = (NOW - timedelta(days=8)).strftime("%Y-%m-%dT%H:%M:%SZ")
    due = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    repo.upsert_skill_state(pid, GOAL, 0.9, 6, mastered, status="mastered", verify_due_at=due)
    res = [{"item_id": "r1", "correct": True, "productive": True}, {"item_id": "r2", "correct": True, "productive": False},
           {"item_id": "r3", "correct": False, "productive": False}]
    out = ingest.apply_retention_result(repo, pack, pid, GOAL, sid, res, run_key="run1", now=NOW)
    assert out["applied"] and out["passed"] and out["to"] == "retained_7d" and out["delay_days"] == 1
    snap = snapshot(repo, pid)
    dup = ingest.apply_retention_result(repo, pack, pid, GOAL, sid, res, run_key="run1", now=NOW)
    assert not dup["applied"] and snapshot(repo, pid) == snap
    st = repo.get_skill_state(pid, GOAL)
    assert st["status"] == "retained_7d" and st["verify_due_at"].startswith((NOW - timedelta(days=8) + timedelta(days=30)).strftime("%Y-%m-%d"))
    # porażka testu 30 d: learning, p ≤ 0.6, relapses+1; stara historia nie zwraca od razu statusu mastered
    bad = [{"item_id": f"x{i}", "correct": False, "productive": i == 0} for i in range(3)]
    later = NOW + timedelta(days=23)
    repo.conn.execute("UPDATE skill_state SET verify_due_at=? WHERE profile_id=?", (later.strftime("%Y-%m-%dT%H:%M:%SZ"), pid))
    out = ingest.apply_retention_result(repo, pack, pid, GOAL, sid, bad, run_key="run2", now=later)
    assert out["applied"] and not out["passed"] and out["to"] == "learning"
    st = repo.get_skill_state(pid, GOAL)
    assert st["status"] == "learning" and st["p_mastery"] <= 0.6 and st["relapses"] == 1 and st["mastered_at"] is None
    ingest.apply_item_attempt(repo, pack, pid, sid, "en.pilot.gram.a2.01", GOAL, True, source="practice",
                              dedupe_key="after-relapse", now=later)
    assert repo.get_skill_state(pid, GOAL)["status"] == "learning"        # jeden poprawny po porażce nie wystarczy
    assert not ingest.apply_retention_result(repo, pack, pid, GOAL, sid, res, run_key="run3", now=later)["applied"]


# --- T-CORR-1..3 ---
def cand(sev=2, count=0, goal=False, cat="tense.past_simple", turn_id=1, obs_id=1):
    return K.Candidate(obs_id, turn_id, cat, "s", sev, count, goal, "I go", "I went")


def test_decision2_default_style_is_summary_until_gate(pack):
    rb = pack.rubric
    d = K.effective_style(None, rb)
    assert d["style"] == "summary" and not d["gate_passed"] and not d["suggestion_wording"]
    p = K.effective_style("periodic", rb)
    assert p["style"] == "periodic" and p["suggestion_wording"]           # gate niespełniona ⇒ „sugestia”
    assert K.effective_style("nonsense", rb)["style"] == "summary"


def test_t_corr_1_policies(pack):
    rb = pack.rubric
    cs = [cand(2, 0, turn_id=1), cand(1, 0, turn_id=2), cand(3, 1, turn_id=3, cat="article")]
    kw = dict(corrected_categories=set(), rubric=rb)
    assert K.select(cs, "summary", turn_index=5, last_correction_turn=None, **kw) == []
    p1 = K.select(cs, "periodic", turn_index=3, last_correction_turn=None, **kw)
    assert len(p1) == 1 and p1[0].form == "recast" and p1[0].candidate.severity == 3           # max 1, najwyższy priorytet
    assert K.select(cs, "periodic", turn_index=4, last_correction_turn=3, **kw) == []          # ≤ 1 na 3 tury
    assert K.select(cs, "periodic", turn_index=6, last_correction_turn=3, **kw)
    assert K.select([cand(1)], "periodic", turn_index=9, last_correction_turn=None, **kw) == []  # sev 1: nie przerywa
    assert K.select([cand(1, count=3)], "periodic", turn_index=9, last_correction_turn=None, **kw)  # nawracający
    assert K.select([cand(1, goal=True)], "periodic", turn_index=9, last_correction_turn=None, **kw)  # cel lekcji
    it = K.select(cs, "intensive", turn_index=1, last_correction_turn=None, **kw)
    assert [d.candidate.severity for d in it] == [3, 2] and all(d.form == "ladder" for d in it)
    assert K.select([cand(1, goal=True)], "intensive", turn_index=1, last_correction_turn=None, **kw)


def test_priority_formula(pack):
    rb = pack.rubric
    assert K.priority(2, 4, False, False, rb) == pytest.approx(2 * (1 + 2))
    assert K.priority(2, 4, True, False, rb) == pytest.approx(2 * 3 * 2)
    assert K.priority(2, 4, False, True, rb) == pytest.approx(2 * 3 * 0.5)
    assert K.priority(1, 0, False, False, rb) == 1


def test_t_corr_1_ladder_l1_to_l4_stops_on_correct_attempt(pack):
    lad = K.start_ladder(cand())
    assert lad.level == 1
    lad, act = K.advance(lad, K.check_attempt("I go there", lad))
    assert act == "show_L2" and lad.level == 2
    lad, act = K.advance(lad, K.check_attempt("I go", lad))
    assert act == "show_L3"
    lad, act = K.advance(lad, K.check_attempt("Hmm I went", lad))
    assert act == "done" and lad.outcome == "correct" and lad.level == 3 and lad.done
    with pytest.raises(ValueError):
        K.advance(lad, "correct")
    l2 = K.start_ladder(cand())
    for lvl in (2, 3, 4):
        l2, act = K.advance(l2, "incorrect")
        assert l2.level == lvl
    l2, act = K.advance(l2, "incorrect")
    assert act == "done" and l2.outcome == "failed" and l2.level == 4
    amb, act = K.advance(K.start_ladder(cand()), K.check_attempt("something else entirely", K.start_ladder(cand())))
    assert act == K.NEEDS_EVAL and amb.level == 1 and not amb.done
    assert K.check_attempt("", K.start_ladder(cand())) == "incorrect"
    rec = K.attempt_record(lad, True)
    assert rec["source"] == "correction" and rec["hint_level"] == 3


def test_ladder_hint_texts_from_templates(pack):
    cat = next(c for c in pack.errors.categories if c.id == "tense.past_simple")
    lad = K.start_ladder(cand())
    assert K.render_hint(1, cat, lad, pack.errors.choice_template) == cat.l1
    assert K.render_hint(2, cat, lad, pack.errors.choice_template) == cat.l2_pl
    h3 = K.render_hint(3, cat, lad, pack.errors.choice_template)
    assert "I go" in h3 and "I went" in h3
    h4 = K.render_hint(4, cat, lad, pack.errors.choice_template)
    assert "I went" in h4 and cat.explanation_pl in h4


def test_t_corr_2_intensive_timeout_means_no_correction(pack):
    rb = pack.rubric
    out = K.select([cand(3)], "intensive", turn_index=1, last_correction_turn=None, corrected_categories=set(),
                   rubric=rb, elapsed_s=rb.correction["intensive_timeout_s"] + 0.1)
    assert out == [K.Decision(None, None, "timeout")]                   # żadnej zmyślonej obserwacji
    ok = K.select([cand(3)], "intensive", turn_index=1, last_correction_turn=None, corrected_categories=set(),
                  rubric=rb, elapsed_s=rb.correction["intensive_target_s"])
    assert ok and ok[0].candidate


def test_t_corr_3_reuse_targets_and_uptake(pack):
    rb = pack.rubric
    plan = K.add_reuse_target({}, skill_id=GOAL, category="tense.past_simple", fix="I went", from_turn=4)
    plan = K.add_reuse_target(plan, skill_id=GOAL, category="tense.past_simple", fix="I went", from_turn=4)
    assert len(plan["reuse_targets"]) == 1 and K.reuse_window(plan["reuse_targets"][0], rb) == (6, 9)
    t = plan["reuse_targets"][0]
    ok = K.reuse_outcome(t, 7, positive_skills={GOAL}, error_categories=set(), rubric=rb)
    assert ok == {"source": "conversation", "hint_level": 0, "correct": True, "skill_id": GOAL}
    assert K.reuse_outcome(t, 5, positive_skills={GOAL}, error_categories=set(), rubric=rb) is None   # za wcześnie
    assert K.reuse_outcome(t, 10, positive_skills={GOAL}, error_categories=set(), rubric=rb) is None
    assert K.reuse_outcome(t, 7, positive_skills=set(), error_categories={"tense.past_simple"}, rubric=rb)["correct"] is False


def test_summary_batches_and_quiz(pack):
    rb = pack.rubric
    assert not K.summary_batch_due(4, False, rb) and K.summary_batch_due(5, False, rb) and K.summary_batch_due(1, True, rb)
    cs = [cand(2, turn_id=i, obs_id=i) for i in range(1, 9)]
    q = K.quiz(cs, rb)
    assert len(q) == rb.correction["quiz_sentences_max"] and len({x.turn_id for x in q}) == len(q)


# --- planer (T-PED-5, decyzje 1, 5) ---
def pinput(pack, minutes=30, **kw):
    base = dict(states={}, levels={"grammar": 2.0, "vocabulary": 2.0})
    return P.PlanInput(minutes=minutes, now=NOW, seed=1, pack=pack, **{**base, **kw})


def test_t_ped_5_blocks_sum_and_review_cap(pack):
    for m in (15, 30, 45, 60):
        cards = [{"card_type": "vocab", "ref_id": f"c{i}", "due_at": "2026-11-01T00:00:00Z"} for i in range(100)]
        out = P.plan(pinput(pack, m, due_cards=cards))
        assert sum(out["blocks"].values()) == m
        assert out["blocks"]["review"] <= 0.3 * m
        assert len(out["review"]) <= out["blocks"]["review"] / pack.rubric.planner["minutes_per_card"]
    few = P.plan(pinput(pack, 30, due_cards=[{"card_type": "vocab", "ref_id": "c", "due_at": "2026-11-01T00:00:00Z"}]))
    assert few["blocks"]["review"] == 1 and sum(few["blocks"].values()) == 30      # niewykorzystane minuty → ćwiczenia
    with pytest.raises(ValueError):
        P.plan(pinput(pack, 20))


def test_t_ped_5_recurring_error_and_prereqs(pack):
    errors = [{"category": "tense.past_simple", "skill_id": None, "status": "recurring", "count": 3, "severity_max": 2}]
    out = P.plan(pinput(pack, 30, errors=errors))
    kinds = {(t["kind"], t["skill_id"]) for t in out["practice"]}
    assert any(k == "remediation" for k, _ in kinds)
    assert out["practice"][0]["kind"] == "remediation"                    # priorytet 2 przed nową umiejętnością
    # nieodblokowana umiejętność (prerekwizyty bez statusu) nie trafia do planu jako nowa
    locked = pinput(pack, 60)
    locked.levels = {"grammar": 3.0}                                      # B1-ish: past_simple_regular wymaga to_be_past
    out2 = P.plan(locked)
    for t in out2["practice"]:
        if t["kind"] == "new":
            assert C.CEFR_LEVELS.index(t["cefr"]) + 1 <= 4
    sk = pack.skills
    planned = [t["skill_id"] for t in P.plan(dataclasses.replace(pinput(pack, 60), levels={"grammar": 1.0,
                                                                                         "vocabulary": 1.0}))["practice"]]
    from tutor.pedagogy.mastery import unlocked
    assert all(unlocked(sk[s], {}, {"grammar": 1.0, "vocabulary": 1.0}, sk) for s in planned)


def test_planner_stt_suspects_insufficient_evidence_and_gaps(pack):
    out = P.plan(pinput(pack, 30, stt_suspects_14d={"article": 3}))
    assert any(t["kind"] == "written_task" and t["reason"] == "stt_suspect:article" for t in out["practice"])
    base = P.plan(pinput(pack, 30))
    ins = P.plan(pinput(pack, 30, last_dims={"grammar": {"status": "insufficient_evidence", "score": None, "range": None}}))
    assert ins["blocks"]["conversation"] == base["blocks"]["conversation"] + 2
    assert sum(ins["blocks"].values()) == 30
    due = (NOW - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    st = SkillState(GOAL, 0.9, "mastered", 6, "2026-11-10T00:00:00Z", due)
    v = P.plan(pinput(pack, 30, states={GOAL: st}))
    assert v["verify"][0]["deferred"] and v["verify"][0]["reason"] == "not_enough_content"   # nie udajemy testu
    assert f"retention:{GOAL}" in v["content_gaps"]


def test_planner_item_labels_status_policy_and_provisional(pack):
    out = P.plan(pinput(pack, 30))
    items = [i for t in out["practice"] for i in t["items"]]
    assert items and all(i["unverified"] for i in items)                  # tylko ai_checked w pilotażu → etykieta
    strict = P.plan(pinput(pack, 30, allow_unreviewed_practice=False))
    assert all(not t["items"] for t in strict["practice"]) and strict["content_gaps"]
    assert all(pack.items[i["id"]].review.status == "ai_checked" for i in items)  # draft/rejected nigdy
    prov = P.plan(pinput(pack, 30, provisional_areas={"grammar"}))
    assert any(t["provisional_level"] for t in prov["practice"] if t["area"] == "grammar")


def test_planner_deterministic_and_fast(pack):
    assert P.plan(pinput(pack, 30)) == P.plan(pinput(pack, 30))
    skills = {}
    for i in range(500):
        s = next(iter(pack.skills.values())).model_copy(update={"id": f"en.gram.s{i}", "prereqs": [f"en.gram.s{i - 1}"] if i else [],
                                                                 "cefr": C.CEFR_LEVELS[i % 5]})
        skills[s.id] = s
    base = next(iter(pack.items.values()))
    items = {f"i{k}": base.model_copy(update={"id": f"i{k}", "skill_ids": [f"en.gram.s{k % 500}"],
                                              "review": C.Review(status="ai_checked")}) for k in range(1500)}
    big = dataclasses.replace(pack, skills=skills, items=items)
    states = {f"en.gram.s{i}": SkillState(f"en.gram.s{i}", 0.5, "learning", 3) for i in range(0, 500, 3)}
    inp = P.PlanInput(minutes=60, now=NOW, seed=1, pack=big, states=states, levels={"grammar": 2.5},
                      due_cards=[{"card_type": "vocab", "ref_id": f"c{i}", "due_at": "2026-11-01T00:00:00Z"} for i in range(300)])
    t0 = time.perf_counter()
    P.plan(inp)
    assert time.perf_counter() - t0 < 0.05


# --- raport (T-REPORT-1..3, decyzja 4) ---
TURNS = {1: "Yesterday I goed home and I walked to school", 2: "I like colour blue and I walked a lot"}


def rinput(pack, **kw):
    base = dict(session_id=1, pack=pack, turns=TURNS, input_modes={"text"})
    return RP.ReportInput(**{**base, **kw})


ERRS = [{"turn_id": 1, "span": "I goed", "fix": "I went", "category": "morphology.irregular_past", "severity": 2,
         "count_session": 1, "count_30d": 3, "is_goal": True},
        {"turn_id": 2, "span": "invented", "fix": "x", "category": "tense", "severity": 3, "count_session": 1,
         "count_30d": 9, "is_goal": True}]


def test_t_report_1_every_error_and_strength_has_literal_quote(pack):
    strengths = [{"kind": "goal_use", "skill_id": GOAL, "turn_id": 1, "quote": "I walked", "hint_level": 0},
                 {"kind": "goal_use", "skill_id": GOAL, "turn_id": 2, "quote": "I walked", "hint_level": 0},
                 {"kind": "goal_use", "skill_id": "en.gram.x", "turn_id": 1, "quote": "I walked", "hint_level": 0},
                 {"kind": "goal_use", "skill_id": "en.gram.y", "turn_id": 2, "quote": "never said", "hint_level": 0},
                 {"kind": "goal_use", "skill_id": "en.gram.y", "turn_id": 2, "quote": "never said", "hint_level": 0}]
    rep = RP.build(rinput(pack, errors=ERRS, strengths=strengths))
    assert [e["quote"] for e in rep["top_errors"]] == ["I goed"]          # cytat spoza tekstu odrzucony
    assert [s["skill_id"] for s in rep["strengths"]["items"]] == [GOAL]  # ≥2× bez podpowiedzi, cytat dosłowny
    assert RP.validate_report(rep, TURNS) == []
    empty = RP.build(rinput(pack))
    assert empty["strengths"] == {"status": RP.NO_DATA, "items": []} and empty["top_errors"] == []
    hinted = RP.build(rinput(pack, strengths=[{**strengths[0], "hint_level": 2}, {**strengths[1], "hint_level": 3}]))
    assert hinted["strengths"]["status"] == RP.NO_DATA                    # z podpowiedzią to nie mocna strona


def test_report_dimensions_labels_and_no_citation_rule(pack):
    dims = {"grammar": {"status": "scored", "score": 3, "range": None, "quotes": ["I goed"]},
            "vocabulary": {"status": "scored", "score": None, "range": [2, 3], "quotes": ["colour blue"]},
            "naturalness": {"status": "insufficient_evidence", "score": None, "range": None, "quotes": []},
            "communication": {"status": "scored", "score": 4, "range": None, "quotes": []},
            "fluency": {"status": "not_applicable", "score": None, "range": None, "quotes": []}}
    rep = RP.build(rinput(pack, dims=dims))
    lab = {k: v["label"] for k, v in rep["dimensions"].items()}
    assert lab == {"grammar": "3", "vocabulary": "2–3, niepewne", "naturalness": "za mało danych",
                   "communication": "4", "fluency": "nie dotyczy"}
    assert RP.validate_report(rep, TURNS) == []
    dims["grammar"]["quotes"] = []                                        # ocena < 4 bez cytatu = błąd walidacji
    assert "no_quote:grammar" in RP.validate_report(RP.build(rinput(pack, dims=dims)), TURNS)


def test_report_competence_labels_provisional_and_no_c2(pack):
    comp = [{"area": "grammar", "theta": 5.5, "lo": 4.5, "hi": 6.4, "ceiling": True, "provisional": False},
            {"area": "reading", "theta": 3.0, "lo": 2.4, "hi": 3.6, "provisional": True}]
    rep = RP.build(rinput(pack, competence=comp))
    txt = json.dumps(rep, ensure_ascii=False)
    assert "C1 lub wyżej" in txt and "C2" not in txt
    rd = next(c for c in rep["competence"] if c["area"] == "reading")
    assert rd["label"].startswith("wstępnie:") and "nie jest diagnozą CEFR" in rd["notice"]
    gr = next(c for c in rep["competence"] if c["area"] == "grammar")
    assert "trafność niezweryfikowana" in gr["notice"]


def test_t_report_3_pronunciation_never_graded(pack):
    rep = RP.build(rinput(pack, input_modes={"text", "voice"}))
    assert rep["notes"]["pronunciation"] == "Wymowa nieoceniana."
    assert "pronunciation" not in RP.build(rinput(pack))["notes"]
    assert RP.validate_report(rep, TURNS) == []
    rep["notes"]["x"] = "Twoja wymowa jest świetna"
    assert "pronunciation_claim" in RP.validate_report(rep, TURNS)
    assert "pronunciation_claim" in RP.validate_narrative("Wymowa jest dobra.", rep)
    assert "pronunciation_claim" not in RP.validate_narrative("Wymowa nieoceniana.", rep)


def test_t_report_2_narrative_validation(pack):
    rep = RP.build(rinput(pack, errors=ERRS[:1], skill_events=[{"skill_id": GOAL, "from": "new", "to": "learning"}],
                          competence=[{"area": "grammar", "theta": 3.0, "lo": 2.4, "hi": 3.6}]))
    good = "Dobra robota: „I goed” → „I went”. W tej sesji zmieniły się statusy umiejętności: 1."
    assert RP.validate_narrative(good, rep) == []
    assert RP.choose_narrative(good, rep) == (good, "llm")
    for bad, why in [("Poprawiłeś się o 23%.", "percent_sign"), ("Zrobiłeś 7 ćwiczeń.", "number:7"),
                     ("Jesteś na poziomie A1.", "cefr:A1"), ("Powiedziałeś „I runned” — źle.", "quote:I runned")]:
        probs = RP.validate_narrative(bad, rep)
        assert why in probs, (bad, probs)
        text, src = RP.choose_narrative(bad, rep)
        assert src == "template" and RP.validate_narrative(text, rep) == []   # szablon sam przechodzi walidację
    assert RP.choose_narrative(None, rep)[1] == "template"
    assert "„I goed”" in RP.template_narrative(rep) or "I goed" in RP.template_narrative(rep)


def test_report_has_no_numbers_outside_input(pack):  # kryterium odbioru 9
    rep = RP.build(rinput(pack, errors=ERRS[:1], skill_events=[], srs={"new_cards": 2, "reviews": 5}))
    text = RP.template_narrative(rep)
    assert RP.validate_narrative(text, rep) == []
    nums = RP._json_numbers(rep)
    assert {"2", "5"} <= nums


# --- T-LANG-1 / T-ARCH-1 ---
def test_t_lang_1_synthetic_language_pack_runs_same_code():
    pk = C.load("xx", XX_ROOT)
    assert pk.lang == "xx" and len(pk.skills) == 6
    rb = pk.rubric
    # klasyfikacja używa wariantów/wypełniaczy/podejrzeń STT z pakietu xx, bez słów języka w kodzie
    pre = A.prefilter("ehm, ta kolour", pk.disfluency)
    assert any(k == "filler" for *_, k in pre.spans)
    o = Obs(s="kolor", f="kolour", k="error", c="spelling", v=1, p="h")
    c = A.classify(o, "ta kolor", input_mode="text", low_prob_words=set(), pre=A.prefilter("ta kolor", pk.disfluency),
                   variants=pk.variants, confusables=pk.confusables, taxonomy={"spelling"}, rubric=rb)
    assert c.kind == "variant"
    v = A.classify(Obs(s="ta", f="tha", k="error", c="word_order", v=2, p="h"), "to ta tak", input_mode="voice",
                   low_prob_words=set(), pre=A.prefilter("to ta tak", pk.disfluency), variants=pk.variants,
                   confusables=pk.confusables, taxonomy={"word_order"}, rubric=rb)
    assert v.kind == "stt_suspect"
    # wstępne dopasowanie na pakiecie xx (statusy podniesione W PAMIĘCI testu)
    prom = promote(pk, "ai_checked")
    st = D.start(prom, "grammar", "provisional", 1)
    items = D.available_items(prom, "grammar", "provisional")
    while D.stop_reason(st, rb) is None and (it := D.next_item(st, items, rb)):
        st = D.record(st, it, True, rb)
    assert D.result(st, rb).provisional
    with pytest.raises(D.GateClosed):
        D.start(pk, "grammar", "provisional", 1)                          # draft nie wystarcza
    out = P.plan(P.PlanInput(minutes=15, now=NOW, seed=1, pack=prom, states={}, levels={"grammar": 1.0}))
    assert out["practice"] and all(t["skill_id"].startswith("xx.") for t in out["practice"])
    rep = RP.build(RP.ReportInput(session_id=1, pack=pk, turns={1: "ta kolor"}, errors=[
        {"turn_id": 1, "span": "kolor", "fix": "x", "category": "spelling", "severity": 1, "count_session": 1,
         "count_30d": 1}]))
    assert rep["top_errors"][0]["category_pl"].startswith("Wyjaśnienie")


def test_t_arch_1_pedagogy_has_no_forbidden_imports():
    forbidden = ("tutor.llm", "tutor.voice", "tutor.ui", "tutor.speech", "requests")
    root = Path(__file__).resolve().parent.parent / "tutor" / "pedagogy"
    files = list(root.glob("*.py"))
    assert len(files) >= 12
    for f in files:
        for n in ast.walk(ast.parse(f.read_text())):
            names = [a.name for a in n.names] if isinstance(n, ast.Import) else [n.module or ""] if isinstance(n, ast.ImportFrom) else []
            for name in names:
                assert not any(name == b or name.startswith(b + ".") for b in forbidden), (f.name, name)
