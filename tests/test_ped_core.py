"""F4 rdzeń: cefr, diagnosis, mastery, srs, retention (T-PED-1..10, T-RET-1/2)."""
import json
import random
from datetime import UTC, datetime, timedelta

import pytest

from tests.helpers import bank, promote, simulate
from tutor.pedagogy import cefr, mastery, retention, srs
from tutor.pedagogy import content as C
from tutor.pedagogy import diagnosis as D
from tutor.pedagogy.mastery import SkillState

NOW = datetime(2026, 11, 22, 10, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture(scope="module")
def rb(pack):
    return pack.rubric


# --- cefr ---
def test_cefr_labels_and_ceiling():
    assert cefr.label_of(2.4) == "A2" and cefr.label_of(2.6) == "B1" and cefr.label_of(9) == "C2"
    assert cefr.label_of(9, top_index=5) == "C1"
    assert cefr.clamp_theta(6.1) == 5.5
    assert cefr.interval_text(3, 2.4, 3.6, ceiling=True) == "C1 lub wyżej"
    assert cefr.interval_text(1, 0.5, 1.2, floor=True) == "A1 lub niżej"
    assert cefr.interval_text(3.0, 2.4, 3.6) == "przedział A2–B2 (środek: B1)"
    assert cefr.interval_text(3.0, 2.6, 3.4) == "B1"


# --- diagnoza ---
def test_t_ped_1_recovers_level_within_one_and_areas_independent(rb):  # spójność algorytmu, nie trafność CEFR
    items = bank()
    rng = random.Random(1)
    ok = 0
    for i in range(500):
        true = rng.uniform(1.0, 5.0)
        r = D.result(simulate(rb, items, true, seed=i), rb)
        ok += abs(cefr.level_index(r.level) - cefr.level_index(cefr.label_of(true, 5))) <= 1
    assert ok / 500 >= 0.90
    hi = D.result(simulate(rb, items, 4.0, seed=7), rb)   # „vocab B2”
    lo = D.result(simulate(rb, items, 2.0, seed=7), rb)   # „grammar A2”: osobny estymator, wynik niezależny
    assert cefr.level_index(hi.level) - cefr.level_index(lo.level) >= 1


def test_t_ped_2_interval_covers_true_level_and_narrows(rb):
    items = bank()
    rng = random.Random(2)
    cover = 0
    w5 = w10 = 0.0
    for i in range(300):
        true = rng.uniform(1.0, 5.0)
        st = simulate(rb, items, true, seed=i)
        r = D.result(st, rb)
        tl = cefr.level_index(cefr.label_of(true, 5))
        cover += cefr.level_index(cefr.label_of(r.lo, 5)) <= tl <= cefr.level_index(cefr.label_of(r.hi, 5))
        early = D.stats(D.posterior(st["asked"][:5], rb), rb)
        late = D.stats(D.posterior(st["asked"], rb), rb)
        w5 += early["hi"] - early["lo"]
        w10 += late["hi"] - late["lo"]
    assert cover / 300 >= 0.90
    assert w10 < w5


def test_t_ped_3_ceiling_and_floor_never_c2_no_loop(rb):
    items = bank()
    top = simulate(rb, items, 5, seed=1, always=True)
    r = D.result(top, rb)
    assert r.ceiling and r.label == "C1 lub wyżej" and "C2" not in r.label and r.theta <= 5.5
    assert len(top["asked"]) <= rb.diagnosis["max_items"]
    low = D.result(simulate(rb, items, 1, seed=1, always=False), rb)
    assert low.floor and low.label == "A1 lub niżej"


def test_diagnosis_deterministic_resume_and_time_limit(rb):
    items = bank()
    a = simulate(rb, items, 3.3, seed=5)
    b = simulate(rb, items, 3.3, seed=5)
    assert a == b
    st = {"area": "grammar", "mode": "verified", "seed": 5, "asked": [], "elapsed_min": 0.0}
    for _ in range(4):
        it = D.next_item(st, items, rb)
        st = D.record(st, it, True, rb, 1.0)
    st = json.loads(json.dumps(st))                       # zapis/wznowienie przez JSON
    it = D.next_item(st, items, rb)
    cont = D.record(st, it, True, rb)
    whole = st
    whole = D.record(whole, D.next_item(whole, items, rb), True, rb)
    assert cont == whole
    st["elapsed_min"] = rb.diagnosis["time_limit_min"]
    assert D.stop_reason(st, rb) == "time_limit"


def test_diagnosis_min_items_before_precision_stop(rb):
    items = bank()
    st = simulate(rb, items, 3.0, seed=3)
    assert len(st["asked"]) >= rb.diagnosis["min_items"]


def test_verified_gate_closed_provisional_open_on_real_bank(pack, rb):
    for area in C.CLOSED_AREAS:
        with pytest.raises(D.GateClosed):
            D.start(pack, area, "verified", 1)               # 0 zadań human_reviewed
        st = D.start(pack, area, "provisional", 1)           # ai_checked wystarcza do wstępnego dopasowania
        items = D.available_items(pack, area, "provisional")
        assert len(items) >= rb.diagnosis["min_items"] and all(i.review.status == "ai_checked" for i in items)
        assert st["mode"] == "provisional"


def test_provisional_result_is_not_presented_as_diagnosis(pack, rb):
    items = D.available_items(pack, "reading", "provisional")
    st = D.start(pack, "reading", "provisional", 4)
    while D.stop_reason(st, rb) is None and (it := D.next_item(st, items, rb)):
        st = D.record(st, it, True, rb)
    r = D.result(st, rb)
    assert r.provisional and r.source == "placement_provisional"
    assert r.label.startswith("wstępnie:") and "nie jest diagnozą CEFR" in r.notice


def test_verified_with_promoted_in_memory_pack_needs_gate(pack, rb):
    big = promote(pack)                                       # w pamięci; 3/poziom < 15 → brama dalej zamknięta
    with pytest.raises(D.GateClosed):
        D.start(big, "grammar", "verified", 1)
    assert C.diagnosis_gate(big, "grammar", 3)["open"]        # przy progu 3 otwarta: brama liczy human_reviewed


def test_refine_moves_toward_evidence(rb):
    it = bank()[40]  # B2-ish
    up, _ = D.refine(3.0, 0.8, it, True, rb)
    down, _ = D.refine(3.0, 0.8, it, False, rb)
    assert down < 3.0 < up or down < up


# --- mastery ---
def att(correct, day, bkt="production", hint=0, n=None):
    return {"correct": correct, "day": day, "bkt": bkt, "hint_level": hint, "n_options": n}


def test_t_ped_4_mastery_rises_and_falls(rb):
    up = mastery.replay([att(True, "d1")] * 4, rb, 0.2)
    down = mastery.replay([att(False, "d1")] * 4, rb, 0.2)
    assert up > 0.85 > 0.2 > down or (up > 0.2 > down)
    assert up > mastery.replay([att(True, "d1")], rb, 0.2)


def test_t_ped_4_9_mastered_needs_two_days_and_production(rb):
    st = SkillState("s")
    five = [att(True, "2026-11-01")] * 5
    p = mastery.replay(five, rb, 0.2)
    assert p >= 0.85
    assert mastery.update_status(st, p, five, "grammar", rb, NOW).status == "learning"      # jeden dzień
    two = five + [att(True, "2026-11-02")]
    s2 = mastery.update_status(st, mastery.replay(two, rb, 0.2), two, "grammar", rb, NOW)
    assert s2.status == "mastered" and s2.mastered_at and s2.verify_due_at.startswith("2026-11-29")
    mc_only = [att(True, f"2026-11-0{d}", "mc", n=4) for d in range(1, 6)]                   # same MC nie wystarczą
    s3 = mastery.update_status(st, mastery.replay(mc_only, rb, 0.2), mc_only, "grammar", rb, NOW)
    assert s3.status == "learning"
    s4 = mastery.update_status(st, mastery.replay(mc_only, rb, 0.2), mc_only, "reading", rb, NOW)
    assert s4.status == "mastered"                                                            # obszar receptywny
    hinted = [att(True, f"2026-11-0{d}", "correction", hint=2) for d in range(1, 6)]
    assert mastery.update_status(st, 0.99, hinted, "grammar", rb, NOW).status == "learning"  # z podpowiedzią nie


def test_bkt_sources_and_p_init(rb):
    assert mastery.bkt_source("correction", 1, rb) == "conversation"
    assert mastery.bkt_source("correction", 3, rb) == "correction"
    assert mastery.bkt_source("conversation", 0, rb) == "conversation"
    lo, hi = rb.mastery["p_init_clamp"]
    assert mastery.p_init(10, 1, rb) == hi and mastery.p_init(-5, 1, rb) == lo


def test_t_ped_10_prereqs(pack):
    sk = pack.skills
    s = sk["en.gram.past_simple_regular"]
    assert not mastery.unlocked(s, {}, {}, sk)
    ok = {p: SkillState(p, status="mastered") for p in s.prereqs}
    assert mastery.unlocked(s, ok, {}, sk)
    adv = {"grammar": 4, "vocabulary": 4}                   # poziom obszaru ≥ prereq+1
    assert mastery.unlocked(s, {}, adv, sk)
    assert not mastery.unlocked(s, {}, {"grammar": 2}, sk)  # prereq A2 → trzeba ≥3


# --- FSRS ---
def test_t_ped_7_fsrs_interval_grows_then_shrinks(rb):
    j, due = srs.review(None, srs.grade(rb, correct=True), NOW, rb)
    t = NOW
    prev = None
    for _ in range(3):
        t = datetime.fromisoformat(due.replace("Z", "+00:00"))
        j, due = srs.review(j, srs.grade(rb, correct=True), t, rb)
        gap = datetime.fromisoformat(due.replace("Z", "+00:00")) - t
        assert prev is None or gap > prev
        prev = gap
    t2 = datetime.fromisoformat(due.replace("Z", "+00:00"))
    _, due_bad = srs.review(j, srs.grade(rb, correct=False), t2, rb)
    assert datetime.fromisoformat(due_bad.replace("Z", "+00:00")) - t2 < prev
    assert srs.retrievability(j, t2, rb) <= 1.0


def test_fsrs_grade_mapping(rb):
    from fsrs import Rating
    g = lambda **k: srs.grade(rb, **k)  # noqa: E731
    assert g(correct=False) == Rating.Again and g(correct=True, hint_level=4) == Rating.Again
    assert g(correct=True, hint_level=1) == Rating.Good and g(correct=True, hint_level=2) == Rating.Hard
    assert g(correct=True, partial=True) == Rating.Hard
    assert g(correct=True, elapsed_ms=1000, item_type="mc") == Rating.Easy
    assert g(correct=True, elapsed_ms=99999, item_type="mc") == Rating.Good
    assert g(correct=True, elapsed_ms=1000, item_type="mc", hint_level=2) == Rating.Hard


# --- retencja ---
def _mastered(days_ago):
    t = NOW - timedelta(days=days_ago)
    return SkillState("s", p=0.9, status="mastered", mastered_at=t.strftime("%Y-%m-%dT%H:%M:%SZ"),
                      verify_due_at=(t + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ"))


def test_t_ped_6_and_t_ret_2_transitions(rb):
    st = _mastered(8)
    assert retention.is_due(st, NOW) and not retention.is_due(_mastered(3), NOW)
    assert retention.delay_days(st, NOW) == 1
    s7 = retention.apply_result(st, True, NOW, rb)
    assert s7.status == "retained_7d" and s7.verified_7d_at and s7.verify_due_at.startswith(
        (NOW - timedelta(days=8) + timedelta(days=30)).strftime("%Y-%m-%d"))
    s30 = retention.apply_result(s7, True, NOW + timedelta(days=23), rb)
    assert s30.status == "retained_30d" and s30.verify_due_at is None and s30.verified_30d_at
    bad = retention.apply_result(s7, False, NOW + timedelta(days=23), rb)
    assert bad.status == "learning" and bad.p <= 0.6 and bad.mastered_at is None and bad.relapses == 1
    fail7 = retention.apply_result(st, False, NOW, rb)
    assert fail7.p <= 0.6 and fail7.relapses == 1
    with pytest.raises(ValueError):
        retention.apply_result(s30, True, NOW, rb)


def test_t_ret_2_missed_window_records_delay(rb):
    st = _mastered(20)
    assert retention.is_due(st, NOW) and retention.delay_days(st, NOW) == 13


def test_retention_passed_rule(rb):
    assert retention.passed([(True, True), (True, False), (False, False)], rb)
    assert not retention.passed([(True, False), (True, False), (False, True)], rb)      # brak poprawnego produkcyjnego
    assert not retention.passed([(True, True), (False, False), (False, False)], rb)


def test_t_ret_1_unseen_only_and_deferred_without_content(pack, rb):
    # prawdziwy pakiet: umiejętność bez puli retention (poza pilotażem F4.6) ⇒ odroczenie z sygnałem, nie „udane”
    pk = retention.pick_items(promote(pack), rb, "en.gram.third_conditional", set(), 1)
    assert pk.deferred and pk.reason == "not_enough_content" and pk.items == []
    # pakiet z dodanymi zadaniami retention (w pamięci)
    base = next(i for i in pack.items.values() if i.type == "gap")
    rev = C.Review(status="human_reviewed", reviewer="t", reviewed_at="x")
    extra = {f"r{k}": base.model_copy(update={"id": f"r{k}", "pools": ["retention"], "review": rev,
                                              "skill_ids": ["en.gram.past_simple_regular"],
                                              "type": "mc" if k in (1, 4) else "gap"}) for k in range(5)}
    pk2 = C.Pack(**{**pack.__dict__, "items": extra})
    seen = {"r0", "r1"}
    got = retention.pick_items(pk2, rb, "en.gram.past_simple_regular", seen, 1)
    assert not got.deferred and len(got.items) == 3 and not ({i.id for i in got.items} & seen)
    assert any(i.productive for i in got.items)
    all_seen = retention.pick_items(pk2, rb, "en.gram.past_simple_regular", {"r0", "r1", "r2"}, 1)
    assert all_seen.deferred                                  # zostały 2 niewidziane < 3
    for i in got.items:
        assert "practice" not in i.pools
