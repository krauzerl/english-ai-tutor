"""Funkcja oceny benchmarku B-lite (bez modelu)."""
from bench.b_lite import load, score
from tutor.pedagogy.assessment import Classified, UttResult


def _o(span, fix, conf="h"):
    return Classified("error", "valid", None, span, fix, "tense", 2, conf)


def test_score_counts_tp_fp_critical_and_levels():
    cases = [{"id": "a", "kind": "clean", "text": "The patient denies chest pain.", "keep": ["denies"]},
             {"id": "b", "kind": "multi", "text": "She have three cat.",
              "errors": [{"fix_has": "has", "cat": "agreement"}, {"fix_has": "three cats", "cat": "morphology"}]},
             {"id": "c", "kind": "error", "text": "He go home.", "errors": [{"fix_has": "goes", "cat": "agreement"}]}]
    res = [UttResult(0, "evaluated", [_o("denies", "has")]),
           UttResult(0, "evaluated", [_o("She have", "She has"), _o("three cat", "three cats", "m")]),
           UttResult(0, "unrated")]
    r = score(cases, res, "recast")
    assert (r["tp"], r["fp"], r["critical"], r["unrated"]) == (1, 1, 1, 1)
    assert r["recall_by"]["multi"] == "1/2" and r["fcr"] == "1/1"
    r2 = score(cases, res, "log")
    assert r2["tp"] == 2 and r2["recall_by"]["multi"] == "2/2"


def test_control_set_splits_and_ids():
    dev, held = load("b_lite", "dev"), load("b_lite", "held")
    assert dev and held and not {c["id"] for c in dev} & {c["id"] for c in held}
    for c in dev + held:
        for e in c.get("errors", []):           # oczekiwana forma nie może już być w zdaniu (inaczej nie do wykrycia)
            from bench.audit_control import _has
            assert not all(_has(c["text"], a) for a in e["fix_has"].split("|")), c["id"]


def test_applied_matches_whole_words():
    from bench.audit_control import _applied
    assert _applied("Can I have an information?", _o("an", "some")) == "Can I have some information?"
