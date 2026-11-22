"""F4.7: fuzja korekt po minimalnych edycjach (nie po zakresach), Unicode/UTF-16, minimalny span, strażnik znaczenia."""
import unicodedata

import pytest

from tests.test_f4_flow import evaluate
from tutor.app import languagetool as LT
from tutor.app import turn_eval as TE
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import edits as E
from tutor.pedagogy import lt_merge as M
from tutor.pedagogy.schemas import Obs, TurnEval, Utt


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def B(s, f, c="agreement.subject_verb", p="m", k="error"):
    return Obs(s=s, f=f, k=k, c=c, v=2, p=p)


def L(s, f, c="agreement.subject_verb", p="l"):
    return Obs(s=s, f=f, k="error", c=c, v=1, p=p, src="languagetool-6.6")


def ed(text, s, f):
    return E.edits(text, E.locate(text, s), f)


# --- Unicode, cytaty, jednostki offsetów ---
def test_utf16_offsets_to_python_index():
    text = "Great 😀 she have a dog"
    py = text.index("have")
    assert E.utf16_index(text, py + 1) == py          # emoji = 2 jednostki UTF-16 (Java), 1 znak w Pythonie
    assert E.utf16_index("abc", 2) == 2


def test_lt_offsets_in_utf16_give_correct_span(pack):
    text = "Great 😀 she have a dog"
    py = text.index("have")
    ms = [LT.LTMatch(py + 1, 4, "x", ("has",), "HE_VERB_AGR", "grammar", "GRAMMAR")]
    obs, _ = M.to_obs(ms, text, pack.lt_map, input_mode="text", known_forms=set(), trusted_rules=set(),
                      version="6.6")
    assert [o.s for o in obs] == ["have"]


def test_find_spans_tolerates_quotes_and_nfd():
    text = "I don’t like the café"
    assert A.find_spans(text, "don't like")
    assert A.find_spans("I don't like it", "don’t like")
    assert A.find_spans(text, unicodedata.normalize("NFD", "the café")) == [(13, 21)]


# --- minimalne edycje i relacje ---
def test_same_edit_from_broad_and_minimal_span():
    t = "She have a dog."
    assert ed(t, "She have a dog.", "She has a dog.") == ed(t, "have", "has")
    assert E.relation(ed(t, "She have a dog.", "She has a dog."), ed(t, "have", "has")) == "same"


def test_relations_partial_conflict_disjoint():
    t = "She have a apple and goes home"
    both = ed(t, "She have a apple", "She has an apple")
    assert E.relation(both, ed(t, "a", "an")) == "partial"
    assert E.relation(ed(t, "have", "has"), ed(t, "have", "had")) == "conflict"
    assert E.relation(ed(t, "She have a apple", "She has a apple"), ed(t, "a apple", "an apple")) == "disjoint"
    assert E.relation(ed(t, "have", "has"), ed(t, "She have", "She has")) == "same"


def test_insertion_edit():
    t = "I have car"
    assert E.relation(ed(t, "have car", "have a car"), ed(t, "car", "a car")) == "same"


# --- scalenie ---
def test_merge_broad_bielik_and_minimal_lt_agree():  # problem F4.6: R1 nie zachodziło
    t = "She have a dog."
    out, alts = M.merge([B("She have a dog.", "She has a dog.")], [L("have", "has")], t)
    assert len(out) == 1 and out[0].p == "h" and out[0].src == "bielik+lt" and alts == []


def test_merge_conflict_downgrades_and_logs():
    t = "She have a dog."
    out, alts = M.merge([B("have", "has", p="h")], [L("have", "had")], t)
    assert len(out) == 1 and out[0].f == "has" and out[0].p == "m" and out[0].src == "bielik|lt-conflict"
    assert len(alts) == 1


def test_merge_partial_no_raise_no_duplicate():
    t = "She have a apple."
    out, alts = M.merge([B("She have a apple", "She has an apple")], [L("a", "an", "article.wrong")], t)
    assert len(out) == 1 and out[0].p == "m" and out[0].src is None and len(alts) == 1


def test_merge_disjoint_inside_broad_span_adds_candidate():
    t = "She have a apple."
    out, _ = M.merge([B("She have a apple", "She has a apple")], [L("a apple", "an apple", "article.wrong")], t)
    assert [o.c for o in out] == ["agreement.subject_verb", "article.wrong"] and out[1].p == "l"


# --- minimalny span ---
def test_minimize_broad_span():
    t = "Yesterday she have a dog."
    o = E.minimize(t, B("Yesterday she have a dog.", "Yesterday she has a dog."))
    assert (o.s, o.f) == ("have", "has")


def test_minimize_insertion_and_uniqueness():
    o = E.minimize("I have car", B("I have car", "I have a car", "article.missing"))
    assert (o.s, o.f) == ("car", "a car")
    o = E.minimize("I like a apple and a pear", B("I like a apple", "I like an apple", "article.wrong"))
    assert (o.s, o.f) == ("a apple", "an apple")          # samo „a” niejednoznaczne ⇒ rozszerzenie
    keep = B("x", "y")
    assert E.minimize("no such span", keep) is keep


def test_evaluate_texts_minimizes_model_spans(pack):
    t = "Yesterday she have a dog."
    ev = TurnEval(u=[Utt(i=0, o=[B(t, "Yesterday she has a dog.")])])
    res = TE.evaluate_texts(pack, None, lambda *a, **k: ev, [t], input_modes=["text"], low_probs=[set()])[0]
    assert [(o.span, o.fix) for o in res.observations] == [("have", "has")]


def test_prompt_requires_minimal_span(pack):
    p = pack.prompts["turn_eval"]
    assert p["version"] == "turn_eval.v3" and "Keep `s` short" in p["text"]


# --- strażnik znaczenia ---
@pytest.mark.parametrize("text,s,f,c", [
    ("I like it very much", "like", "don't like", "omission.auxiliary"),
    ("I have 2 cats at home", "2 cats", "3 cats", "agreement.number"),
    ("She go to work every day", "She go", "He goes", "agreement.subject_verb"),
    ("I go to school by bus", "by bus", "by car", "preposition"),
])
def test_meaning_change_dropped(pack, text, s, f, c):
    r = evaluate(pack, text, o=[B(s, f, c)])
    assert r.observations[0].status == "dropped" and r.observations[0].drop_reason == "meaning_change"


@pytest.mark.parametrize("text,s,f,c", [
    ("My sister lives with his husband", "his husband", "her husband", "determiner.possessive"),
    ("He learned me English", "learned", "taught", "word_choice"),
    ("I don't know nothing", "nothing", "anything", "word_choice"),
    ("Yesterday I buyed bread", "buyed", "bought", "morphology.irregular_past"),
    ("Is raining today", "Is raining", "It is raining", "omission.subject"),
])
def test_legit_corrections_kept(pack, text, s, f, c):
    r = evaluate(pack, text, o=[B(s, f, c)])
    assert r.observations[0].status == "valid" and r.observations[0].kind == "error"


def test_variants_and_stt_still_win(pack):
    r = evaluate(pack, "I like this colour", o=[B("colour", "color", "spelling")])
    assert r.observations[0].kind == "variant"
    r = evaluate(pack, "He can go there", o=[B("can", "can't", "agreement")], mode="voice")
    assert r.observations[0].kind == "stt_suspect"


def test_lt_subword_span_expanded_to_token(pack):
    text = "She don't like it"
    ms = [LT.LTMatch(4, 2, "x", ("does",), "HE_VERB_AGR", "grammar", "GRAMMAR")]       # LT: „do” w „don't”
    obs, _ = M.to_obs(ms, text, pack.lt_map, input_mode="text", known_forms=set(), trusted_rules=set(),
                      version="6.6")
    assert [(o.s, o.f) for o in obs] == [("don't", "doesn't")]
    out, _ = M.merge([B("don't", "doesn't", "omission.auxiliary")], obs, text)
    assert out[0].src == "bielik+lt-fix" and out[0].p == "m"          # ta sama poprawka, inna kategoria


def test_same_fix_different_category_is_not_conflict(pack):
    t = "She walk to school."
    out, alts = M.merge([B("walk", "walks", "tense.present_simple")], [L("walk", "walks")], t)
    assert len(out) == 1 and out[0].src == "bielik+lt-fix" and out[0].p == "m" and len(alts) == 1
    from tutor.pedagogy import evidence as EV
    r = evaluate(pack, t, o=out)
    assert EV.level(r.observations[0], pack) == EV.OBSERVATION
