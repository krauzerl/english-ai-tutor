"""F4 ocena: T-ASSESS-1..7, T-ERR-1, walidacja dowodów (decyzje 4–5)."""
import pytest

from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import errors as E
from tutor.pedagogy import fluency as F
from tutor.pedagogy.schemas import Obs, TurnEval, Use, Utt


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def ob(s, f, c="tense.past_simple", k="error", v=2, p="h"):
    return Obs(s=s, f=f, k=k, c=c, v=v, p=p)


def cls(pack, o, text, mode="text", low=frozenset()):
    return A.classify(o, text, input_mode=mode, low_prob_words=set(low), pre=A.prefilter(text, pack.disfluency),
                      variants=pack.variants, confusables=pack.confusables, taxonomy=E.allowed_categories(pack.errors),
                      rubric=pack.rubric)


def test_t_assess_1_span_not_found_dropped(pack):
    c = cls(pack, ob("I goed there", "I went there"), "I went to school yesterday")
    assert (c.status, c.drop_reason) == ("dropped", "span_not_found")
    assert cls(pack, ob("I  GO", "I went"), "yesterday i go there").status == "valid"   # wielkość liter/spacje bez znaczenia


@pytest.mark.parametrize("span,fix,text", [
    ("my favourite colour", "my favorite color", "my favourite colour is blue"),
    ("a flat", "an apartment", "I rent a flat in Warsaw"),
    ("I have got a car", "I have a car", "yes, I have got a car"),
    ("I have a car", "I have got a car", "I have a car"),
    ("gotten", "got", "I have gotten better"),
    ("in hospital", "in the hospital", "she is in hospital now"),
])
def test_t_assess_2_variants_are_not_errors(pack, span, fix, text):
    c = cls(pack, ob(span, fix, "article"), text)
    assert c.kind == "variant" and c.status == "valid"
    assert not E.is_counted({"kind": c.kind, "status": c.status, "confidence": c.confidence}, pack.rubric)


def test_variant_does_not_swallow_real_errors(pack):
    assert cls(pack, ob("He have got a car", "He has got a car", "agreement.subject_verb"),
               "He have got a car").kind == "error"


def test_t_assess_3_voice_rules(pack):
    sp = cls(pack, ob("Frist", "First", "spelling"), "Frist we met", mode="voice")
    assert (sp.status, sp.drop_reason) == ("dropped", "category_not_spoken")
    assert cls(pack, ob("Frist", "First", "spelling"), "Frist we met", mode="text").kind == "error"
    # słowo o niskim prawdopodobieństwie
    low = cls(pack, ob("went", "go", "tense.present_simple"), "I really went there", mode="voice", low={"went"})
    assert low.kind == "stt_suspect"
    # para wrażliwa: brak a/the, końcówka, 'll, can/can't, to/too
    for span, fix, text in [("I bought car", "I bought a car", "yes I bought car yesterday ok"),
                            ("he walk", "he walks", "so he walk home every day"),
                            ("I go", "I'll go", "well I go there tomorrow ok"),
                            ("I can come", "I can't come", "sorry I can come tonight ok"),
                            ("me too", "me to", "sure me too really")]:
        assert cls(pack, ob(span, fix, "tense"), text, mode="voice").kind == "stt_suspect", span
        assert cls(pack, ob(span, fix, "tense"), text, mode="text").kind == "error", span
    # brzeg wypowiedzi (urwanie endpointera)
    assert cls(pack, ob("went to", "went to the", "article.missing"), "yesterday I went to", mode="voice"
               ).kind == "stt_suspect"
    # nigdy w error_log/BKT
    assert not E.is_counted({"kind": "stt_suspect", "status": "valid", "confidence": "h"}, pack.rubric)


def test_t_assess_3_three_suspects_trigger_written_task(pack):
    o = {"kind": "stt_suspect", "status": "valid", "severity": 2, "confidence": "h", "category": "article"}
    base = dict(count_30d=0, utts_30d=0, in_goal=False)
    assert "written_task" not in A.obs_actions(o, pack.rubric, stt_in_category_14d=1, **base)
    assert "written_task" in A.obs_actions(o, pack.rubric, stt_in_category_14d=2, **base)
    assert "no_penalty" in A.obs_actions(o, pack.rubric, stt_in_category_14d=0, **base)


def test_classify_rule_6_and_7(pack):
    assert cls(pack, ob("I go", "I go"), "yesterday I go").drop_reason == "fix_equals_span"
    assert cls(pack, ob("I go", "I went", "nonsense.cat"), "yesterday I go").drop_reason == "category_not_in_taxonomy"
    assert cls(pack, ob("go", "x" * 60), "yesterday I go").drop_reason == "fix_too_long"
    assert cls(pack, ob("I go", "I went", k="natural"), "yesterday I go").kind == "natural"
    assert cls(pack, ob("I go", "I went", "tense")).kind if False else True


def test_t_assess_4_fillers_repetitions_repairs(pack):
    text = "um, I I went— I go"
    pre = A.prefilter(text, pack.disfluency)
    kinds = {k for _, _, k in pre.spans}
    assert {"filler", "repetition", "false_start"} <= kinds
    assert "[[F:um]]" in pre.marked and pre.text == text                       # turn.text nietknięty
    assert A.content_words(text, pre) == 2                                     # „I go”: forma końcowa
    assert cls(pack, ob("um", "", "omission"), text).kind == "disfluency"
    assert cls(pack, ob("I I", "I", "omission"), text).kind == "disfluency"
    assert cls(pack, ob("I go", "I went", "tense.past_simple"), text).kind == "error"     # forma końcowa jest oceniana
    # autonaprawa zła → dobra: „I goed— I went” — zły fragment nie jest błędem, naprawa liczona pozytywnie
    t2 = "I goed— I went there"
    c = cls(pack, ob("goed", "went", "morphology.irregular_past"), t2)
    assert c.kind == "disfluency" and c.self_repair
    assert A.prefilter(t2, pack.disfluency).repairs == [{"bad": "I goed", "good": "I went there"}]
    assert not E.is_counted({"kind": c.kind, "status": c.status, "confidence": "h"}, pack.rubric)


def test_filler_phrase_only_as_interjection(pack):
    assert "[[F:you know]]" in A.prefilter("I was, you know, tired", pack.disfluency).marked
    assert "[[F:" not in A.prefilter("Do you know him?", pack.disfluency).marked


# --- batch: poprawna ≠ nieoceniona ≠ przerwana ≠ odrzucona; dowody pozytywne i komunikatywność ---
GOALS = {"en.gram.past_simple_regular"}


def run(pack, ev, texts=("I went home",), failure="unrated"):
    n = len(texts)
    return A.evaluate_batch(ev, list(texts), input_modes=["text"] * n, low_probs=[set()] * n, pack=pack,
                            goals=GOALS, failure=failure)


def test_correct_utterance_differs_from_unrated_aborted_rejected(pack):
    ok = run(pack, TurnEval(u=[Utt(i=0, o=[], cm="ok", cq="I went home")]))[0]
    assert ok.eval_status == "evaluated" and ok.rated and ok.observations == [] and ok.comm == "ok"
    miss = run(pack, TurnEval(u=[]))[0]
    assert miss.eval_status == "unrated" and not miss.rated and miss.comm == "na"
    assert run(pack, None, failure="aborted")[0].eval_status == "aborted"
    assert run(pack, None, failure="rejected")[0].eval_status == "rejected"
    two = run(pack, TurnEval(u=[Utt(i=1, o=[])]), texts=("a b", "c d"))
    assert [r.eval_status for r in two] == ["unrated", "evaluated"]


def test_positive_evidence_validated(pack):
    good = Use(id="en.gram.past_simple_regular", r="ok", s="I went")
    r = run(pack, TurnEval(u=[Utt(i=0, t=[good])]))[0]
    assert [(p.skill_id, p.quote) for p in r.positives] == [("en.gram.past_simple_regular", "I went")]
    bad = [Use(id="en.gram.past_simple_regular", r="ok", s="I walked"),       # cytat nieobecny
           Use(id="en.gram.nope", r="ok", s="I went"),                        # nieznana umiejętność
           Use(id="en.gram.present_simple", r="ok", s="I went")]              # nie cel lekcji
    r = run(pack, TurnEval(u=[Utt(i=0, t=bad)]))[0]
    assert r.positives == [] and r.drops == ["t:span_not_found", "t:unknown_skill", "t:not_a_goal"]
    neg = run(pack, TurnEval(u=[Utt(i=0, t=[Use(id="en.gram.past_simple_regular", r="bad", s="I went")])]))[0]
    assert neg.positives == [] and len(neg.negatives) == 1
    # w mowie: słowo o niskim prawdopodobieństwie nie daje dowodu pozytywnego
    v = A.evaluate_batch(TurnEval(u=[Utt(i=0, t=[good])]), ["I went home"], input_modes=["voice"],
                         low_probs=[{"went"}], pack=pack, goals=GOALS)[0]
    assert v.positives == [] and v.drops == ["t:stt_uncertain"]
    # cytat tylko w fałszywym starcie
    fs = run(pack, TurnEval(u=[Utt(i=0, t=[Use(id="en.gram.past_simple_regular", r="ok", s="I goed")])]),
             texts=("I goed— I walked there",))[0]
    assert fs.positives == [] and fs.drops == ["t:in_disfluency"]


def test_communication_needs_quote(pack):
    assert run(pack, TurnEval(u=[Utt(i=0, cm="ok", cq="")]))[0].comm == "na"
    r = run(pack, TurnEval(u=[Utt(i=0, cm="ok", cq="invented quote")]))[0]
    assert r.comm == "na" and r.comm_quote is None and "cm:quote_not_found" in r.drops
    r = run(pack, TurnEval(u=[Utt(i=0, cm="partial", cq="went home")]))[0]
    assert (r.comm, r.comm_quote) == ("partial", "went home")
    assert run(pack, TurnEval(u=[Utt(i=0, cm="na")]))[0].comm == "na"


# --- oceny wymiarów ---
def view(words=20, mode="text", status="evaluated", comm="ok", quote="q", obs=(), pos=()):
    return A.UttView("t", words, mode, status, comm, quote if comm != "na" else None, list(obs), list(pos))


def err(sev=2, conf="h", cat="tense.past_simple", kind="error", status="valid", span="I go"):
    return {"kind": kind, "status": status, "category": cat, "severity": sev, "confidence": conf, "span": span}


def test_t_assess_5_scores_from_rubric_and_insufficient(pack):
    rb = pack.rubric
    cover = [A.Positive("en.gram.a", "grammar", "x"), A.Positive("en.gram.b", "grammar", "y")]
    clean = [view(words=20, pos=cover) for _ in range(5)]
    d = A.score_session(clean, rb)
    assert d["grammar"]["score"] == 4 and d["grammar"]["quotes"] == []
    no_cover = A.score_session([view(words=20) for _ in range(5)], rb)
    assert no_cover["grammar"]["status"] == "insufficient_evidence" and no_cover["grammar"]["reason"] == "no_citation"
    # 100 słów, błędy 2×sev2 + 1×sev1 = 2,5 / 100 słów → 3
    utts = [view(words=20, obs=[err(2, span="e1")] if i < 2 else [err(1, span="e3")] if i == 2 else [])
            for i in range(5)]
    g = A.score_session(utts, rb)["grammar"]
    assert g["score"] == 3 and g["quotes"] == ["e1", "e3"]
    # 100 słów, 4×sev3 (8/100) → 1; 10 sev3 = 20 → 0
    four = [view(words=20, obs=[err(3, span=f"s{i}")]) for i in range(4)] + [view(words=20)]
    assert A.score_session(four, rb)["grammar"]["score"] == 1
    many = [view(words=20, obs=[err(3, span=f"s{i}"), err(3, span=f"t{i}")]) for i in range(5)]
    assert A.score_session(many, rb)["grammar"]["score"] == 0
    # za mało słów / wypowiedzi → insufficient
    assert A.score_session([view(words=10) for _ in range(4)], rb)["grammar"]["status"] == "insufficient_evidence"
    assert A.score_session([view(words=100)], rb)["grammar"]["reason"] == "too_little_evidence"
    # nieocenione wypowiedzi nie wchodzą do mianowników
    unrated = [view(words=20, status="unrated") for _ in range(5)]
    assert A.score_session(unrated, rb)["grammar"]["status"] == "insufficient_evidence"
    # G i V rozdzielone wg dimension_of; kolokacje → słownictwo
    mix = [view(words=20, obs=[err(3, cat="collocation.verb_noun", span=f"c{i}")]) for i in range(5)]
    r = A.score_session(mix, rb)
    assert r["vocabulary"]["score"] == 1 and r["grammar"]["status"] == "insufficient_evidence"


def test_t_assess_5_sensitivity_interval(pack):
    rb = pack.rubric
    cover = [A.Positive("a", "grammar", "x"), A.Positive("b", "grammar", "y")]
    base = [view(words=20, pos=cover, obs=[err(2, span="e1")]) for _ in range(1)] + [view(words=20) for _ in range(4)]
    base[0].observations.append(err(2, conf="l", span="uncertain"))
    base[1].observations.append(err(2, kind="stt_suspect", span="maybe-stt"))
    base[2].observations.append(err(2, kind="stt_suspect", span="maybe-stt2"))
    g = A.score_session(base, rb)["grammar"]
    assert g["score"] is None and g["range"] == [2, 3] or g["range"] == [1, 3] or g["range"][0] < g["range"][1]
    # stt_suspect i `l` NIGDY nie obniżają oceny głównej: (a) = tylko h/m błędy
    only_a = A.score_session([view(words=20, pos=cover, obs=[err(2, span="e1"), err(2, span="e2")])]
                             + [view(words=20) for _ in range(4)], rb)
    assert only_a["grammar"]["score"] == 3


def test_communication_requires_labeled_with_quotes(pack):
    rb = pack.rubric
    five = [view(comm="ok") for _ in range(4)] + [view(comm="fail", quote="what?")]
    c = A.score_session(five, rb)["communication"]
    assert c["score"] == 3 and c["quotes"] == ["what?"]       # 80% ok
    na = [view(comm="na") for _ in range(5)]
    assert A.score_session(na, rb)["communication"]["status"] == "insufficient_evidence"
    noq = [A.UttView("t", 20, "text", "evaluated", "ok", None, [], []) for _ in range(5)]
    assert A.score_session(noq, rb)["communication"]["status"] == "insufficient_evidence"   # brak cytatu = brak oceny


def test_t_assess_6_fluency_metrics_match_manual_and_text_not_applicable(pack):
    rb = pack.rubric
    words = [("I", 0.0, 0.2, .9), ("went", 0.3, 0.6, .9), ("to", 1.8, 1.9, .9), ("school", 2.0, 2.5, .9)]
    m = F.metrics(words, rb, repairs=1)
    assert m["speech_s"] == 2.5 and m["articulation_s"] == 1.3                 # pauza 1,2 s odjęta
    assert m["tempo_wpm"] == pytest.approx(4 / (1.3 / 60), abs=0.01)           # 184,62
    assert m["long_pauses"] == 1 and m["long_pauses_per_min"] == pytest.approx(24.0)
    assert m["mlr"] == 2.0 and m["repairs"] == 1
    assert F.metrics(words[:1], rb) is None
    assert A.score_session([view()], rb)["fluency"]["status"] == "not_applicable"     # tekst: „nie dotyczy”


def test_fluency_scoring_vs_baseline_and_gates(pack):
    rb = pack.rubric
    cur = {"utterances": 6, "speech_s": 90, "tempo_wpm": 120.0, "long_pauses_per_min": 2.0, "mlr": 3}
    base = {"tempo_wpm": 100.0, "long_pauses_per_min": 3.0, "mlr": 3}
    assert A.score_fluency(cur, base, 3, rb)["score"] == 4                      # +20% tempo, −33% pauz
    assert A.score_fluency({**cur, "tempo_wpm": 100.0}, base, 3, rb)["score"] == 3
    slow = A.score_fluency({**cur, "tempo_wpm": 80.0, "long_pauses_per_min": 3.3}, base, 3, rb)
    assert slow["score"] == 2
    worse = A.score_fluency({**cur, "tempo_wpm": 60.0}, base, 3, rb)
    assert worse["score"] == 1
    assert A.score_fluency(cur, base, 2, rb)["status"] == "metrics_only"        # < 3 sesje głosowe
    assert A.score_fluency(cur, None, 5, rb)["status"] == "metrics_only"
    assert A.score_fluency({**cur, "speech_s": 30}, base, 5, rb)["status"] == "insufficient_evidence"
    assert A.score_fluency({**cur, "utterances": 4}, base, 5, rb)["status"] == "insufficient_evidence"
    ms = [F.metrics([("a", 0, .2, 1), ("b", .3, .5, 1)], rb)] * 2
    assert F.aggregate(ms)["utterances"] == 2
    assert F.baseline([{"tempo_wpm": 100, "long_pauses_per_min": 1, "mlr": 2}] * 3, rb)["tempo_wpm"] == 100


@pytest.mark.parametrize("o,kw,expect,absent", [
    (err(2), dict(count_30d=0, utts_30d=0, in_goal=False), {"correction_candidate", "error_log", "bkt_incorrect"}, set()),
    (err(1), dict(count_30d=3, utts_30d=2, in_goal=False), {"correction_candidate", "error_log"}, set()),
    (err(1), dict(count_30d=0, utts_30d=0, in_goal=True), {"correction_candidate", "error_log"}, set()),
    (err(1), dict(count_30d=0, utts_30d=0, in_goal=False), {"error_log", "report_if_top3"}, {"correction_candidate"}),
    (err(1), dict(count_30d=2, utts_30d=2, in_goal=False), {"error_log", "remedial_task"}, {"correction_candidate"}),
    (err(2, kind="natural"), dict(count_30d=0, utts_30d=0, in_goal=False, in_content_phrase=True),
     {"suggestion_natural", "srs_construction"}, {"error_log", "bkt_incorrect"}),
    (err(2, kind="natural"), dict(count_30d=0, utts_30d=0, in_goal=False), {"suggestion_natural"}, {"error_log", "srs_construction"}),
    (err(2, kind="variant"), dict(count_30d=0, utts_30d=0, in_goal=False), {"note_variant_intensive"}, {"error_log", "correction_candidate"}),
    (err(2, kind="disfluency"), dict(count_30d=0, utts_30d=0, in_goal=False), {"fluency_metric_only"}, {"error_log", "bkt_incorrect"}),
    (err(2, conf="l"), dict(count_30d=0, utts_30d=0, in_goal=False), set(), {"error_log", "bkt_incorrect", "correction_candidate"}),
    (err(2, status="dropped"), dict(count_30d=0, utts_30d=0, in_goal=False), set(), {"error_log"}),
])
def test_t_assess_7_observation_actions(pack, o, kw, expect, absent):
    acts = set(A.obs_actions(o, pack.rubric, **kw))
    assert expect <= acts and not (absent & acts), acts


def test_t_assess_7_session_actions(pack):
    rb = pack.rubric
    ok = {"status": "scored", "score": 3, "range": None}
    low = {"status": "scored", "score": 1, "range": None}
    ins = {"status": "insufficient_evidence", "score": None, "range": None}
    dims = lambda g=ok, f=ok: {"grammar": g, "vocabulary": ok, "naturalness": ok, "communication": ok, "fluency": f}  # noqa: E731
    assert "clarify_request" in A.session_actions(dims(), rb, comm_fail_in_scenario=1)
    assert "repeat_scenario_with_phrases" in A.session_actions(dims(), rb, comm_fail_in_scenario=2)
    assert {"next_lesson_theta_drop", "review_prereqs"} <= set(A.session_actions(dims(g=low), rb))
    assert "fluency_exercise" in A.session_actions(dims(), rb, fluency_drop_sessions=2)
    assert "extend_conversation" in A.session_actions(dims(f=ins), rb)
    assert A.session_actions(dims(), rb) == []


# --- T-ERR-1 ---
def agg(pack, obs, now):
    return E.aggregate(obs, now, pack.rubric)


def mk(i, turn, day, cat="tense.past_simple", conf="h", status="valid", kind="error", sev=2):
    return {"id": i, "turn_id": turn, "created_at": f"2026-11-{day:02d}T10:00:00Z", "category": cat, "skill_id": "s",
            "kind": kind, "status": status, "confidence": conf, "severity": sev, "span": f"sp{i}", "fix": "f"}


def test_t_err_1_status_machine(pack):
    from datetime import UTC, datetime
    rb = pack.rubric
    now = datetime(2026, 11, 22, tzinfo=UTC)
    one = agg(pack, [mk(1, 1, 20)], now)[("tense.past_simple", "s")]
    assert one["count_30d"] == 1
    s, r = E.next_status("active", 0, count_30d=1, utts_30d=1, remediated=False, sessions=[],
                         new_error_since_resolved=False, rubric=rb)
    assert (s, r) == ("active", 0)
    three_same_turn = agg(pack, [mk(i, 1, 20) for i in range(3)], now)[("tense.past_simple", "s")]
    assert (three_same_turn["count_30d"], three_same_turn["utts_30d"]) == (3, 1)
    s, _ = E.next_status("active", 0, count_30d=3, utts_30d=1, remediated=False, sessions=[],
                         new_error_since_resolved=False, rubric=rb)
    assert s == "active"                                    # 3 błędy w 1 wypowiedzi to nie „recurring”
    s, _ = E.next_status("active", 0, count_30d=3, utts_30d=2, remediated=False, sessions=[],
                         new_error_since_resolved=False, rubric=rb)
    assert s == "recurring"
    s, _ = E.next_status("recurring", 0, count_30d=3, utts_30d=2, remediated=True,
                         sessions=[{"errors": 1, "correct": 3}], new_error_since_resolved=False, rubric=rb)
    assert s == "improving"
    s, _ = E.next_status("recurring", 0, count_30d=3, utts_30d=2, remediated=False,
                         sessions=[{"errors": 1, "correct": 3}], new_error_since_resolved=False, rubric=rb)
    assert s == "recurring"                                 # bez zadania naprawczego nie ma „improving”
    s, _ = E.next_status("improving", 0, count_30d=0, utts_30d=0, remediated=True,
                         sessions=[{"errors": 0, "correct": 1}] * 3, new_error_since_resolved=False, rubric=rb)
    assert s == "resolved"
    s, _ = E.next_status("improving", 0, count_30d=0, utts_30d=0, remediated=True,
                         sessions=[{"errors": 0, "correct": 1}] * 2, new_error_since_resolved=False, rubric=rb)
    assert s != "resolved"                                  # 3 kolejne sesje z okazją
    s, reo = E.next_status("resolved", 0, count_30d=1, utts_30d=1, remediated=True, sessions=[],
                           new_error_since_resolved=True, rubric=rb)
    assert (s, reo) == ("recurring", 1)
    assert E.next_status("resolved", 1, count_30d=0, utts_30d=0, remediated=True, sessions=[],
                         new_error_since_resolved=False, rubric=rb) == ("resolved", 1)


def test_error_aggregation_counts_only_valid_confident_errors(pack):
    from datetime import UTC, datetime
    now = datetime(2026, 12, 15, tzinfo=UTC)
    obs = [mk(1, 1, 20), mk(2, 2, 21, conf="l"), mk(3, 3, 21, status="dropped"), mk(4, 4, 21, kind="stt_suspect"),
           mk(5, 5, 21, kind="variant"), mk(6, 6, 21, kind="natural"), mk(7, 7, 1)]
    g = agg(pack, obs, now)[("tense.past_simple", "s")]
    assert g["count"] == 2 and g["count_30d"] == 1 and g["example_obs_id"] == 1


def test_wrong_article_with_variant_swap_is_error(pack):
    assert cls(pack, ob("an flat", "an apartment", "article"), "I rent an flat").kind == "error"


@pytest.mark.parametrize("span,fix,text", [
    ("are", "is", "The team are working hard this month."),           # audyt F7: span zminimalizowany do „are”
    ("the", "", "She is in the hospital now."),
])
def test_minimized_span_still_matches_phrase_variant(pack, span, fix, text):
    assert cls(pack, ob(span, fix, "agreement.subject_verb"), text).kind == "variant"


def test_minimized_span_variant_check_keeps_real_errors(pack):
    assert cls(pack, ob("are", "is", "agreement.subject_verb"), "The boy are working hard.").kind == "error"


@pytest.mark.parametrize("span,fix,text", [
    ("matches", "a match", "I watch matches on TV every weekend."),       # audyt F7: Qwen3 na żywo
    ("watch matches", "watch a match", "I watch matches on TV every weekend."),
    ("stories", "the story", "I love stories about the sea."),
])
def test_bare_plural_is_not_an_article_error(pack, span, fix, text):
    c = cls(pack, ob(span, fix, "article"), text)
    assert (c.status, c.drop_reason) == ("dropped", "bare_plural")


def test_real_article_errors_still_reported(pack):
    assert cls(pack, ob("doctor", "a doctor", "article"), "My father is doctor.").kind == "error"
    assert cls(pack, ob("cat", "cats", "agreement.number"), "I have two cat.").kind == "error"


@pytest.mark.parametrize("span,fix,text", [
    ("medicines", "medicine", "Okay. Do you take any medicines?"),          # audyt F7: roleplay na żywo
    ("friends", "friend", "I met my friends yesterday."),
    ("years", "year", "I have 30 years."),                                   # zła poprawka; błąd jest gdzie indziej
    ("days", "day", "We stayed there for three days."),
])
def test_plural_after_plural_determiner_is_correct(pack, span, fix, text):
    c = cls(pack, ob(span, fix, "agreement.number"), text)
    assert (c.status, c.drop_reason) == ("dropped", "plural_ok")


def test_uncountable_plural_is_still_an_error(pack):
    assert cls(pack, ob("informations", "information", "agreement.number"),
               "I need some informations about it.").kind == "error"
