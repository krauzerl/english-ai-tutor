"""Smart speaking corrections (Quick Chat): waga błędu z edycji, natychmiastowa korekta tylko poważnych błędów,
drobne do podsumowania, STT jako pytanie, walidatory kategorii, dziennik decyzji, brak wpływu na mastery.

Przypadki A–E z pierwszej rozmowy właściciela są tu jako ZACHOWANIE systemu wobec odpowiedzi Qwen3 (wejście
modelu wpisane na sztywno), nie jako etykiety poprawności zdań."""
import json
from datetime import UTC, datetime

import pytest

from tests.llm_fakes import FakeProvider
from tests.voice_fakes import FakeTTS
from tutor.app import feedback as FB
from tutor.app import goal as G
from tutor.app import ingest
from tutor.app import learnlog as LL
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import correction as K
from tutor.pedagogy import errors as ER
from tutor.pedagogy.schemas import Obs, TurnEval, Utt
from tutor.voice import audio as AU
from tutor.voice.conversation import SAY, VoiceTutor

PACK = C.load("en")
NOW = datetime(2026, 11, 27, 10, tzinfo=UTC)


def cls(text, span, fix, cat, mode="text", low=(), kind="error", sev=2):
    o = Obs(s=span, f=fix, k=kind, c=cat, v=sev, p="h")
    return A.classify(o, text, input_mode=mode, low_prob_words=set(low), pre=A.prefilter(text, PACK.disfluency),
                      variants=PACK.variants, confusables=PACK.confusables,
                      taxonomy=ER.allowed_categories(PACK.errors), rubric=PACK.rubric)


def obs(repo, pid, sid, text, span, fix, cat, *, kind="error", sev=2, mode="voice"):
    tid = repo.add_turn(pid, sid, "user", text, input_mode=mode, low_probs=[] if mode == "voice" else None)
    repo.add_observation(pid, sid, tid, kind, span, category=cat, fix=fix, severity=sev, confidence="h")
    return tid


def chat(repo):
    pid = repo.create_profile("sc")
    return pid, repo.start_session(pid, "chat")


def events(repo, pid, kind="log.correction"):
    return [e["data"] for e in LL.events(repo, pid) if e["kind"] == kind]


# 1. jednoznaczny błąd zmieniający znaczenie → krótka korekta od razu (wypowiada ją kod), potem rozmowa
def test_1_meaning_changing_error_is_corrected_immediately_and_spoken_first(repo):
    pid, sid = chat(repo)
    obs(repo, pid, sid, "I was very boring at that meeting.", "boring", "bored", "word_choice")
    d = FB.recast_directive(repo, PACK, pid, sid, "periodic", set())
    assert d.startswith(SAY)
    _, say, note = d.split(SAY, 2)
    assert say.startswith("Quick note: we say “bored” here, not “boring”.") and "-ed" in say
    assert "Do not repeat" in note and "grammar lesson" not in say
    t = VoiceTutor(repo, pid, sid, FakeProvider(chunks=["Meetings can be long. ", "What was it about?"]), FakeTTS(),
                   AU.SimSink(), feedback=lambda _t: d)
    r = t.respond("Then I went home.")
    assert r.reply.startswith("Quick note: we say “bored”") and "What was it about?" in r.reply
    assert t.llm.calls[-1][-1].content.split("\n\n")[0] == "Then I went home."
    assert events(repo, pid)[0]["decision"] == "immediate" and events(repo, pid)[0]["tier"] == "serious"


@pytest.mark.parametrize("text,span,fix,why", [
    ("Can you borrow me your charger?", "borrow", "lend", "meaning:pair"),
    ("I'm really exciting about this job.", "exciting", "excited", "meaning:ing_ed"),
    ("I no understand you.", "no", "don't", "negation_form"),
])
def test_1b_serious_rules(text, span, fix, why):
    assert K.impact(text, span, fix, "word_choice") == (K.SERIOUS, why)


# 2. błąd nieutrudniający komunikacji → bez przerywania, do podsumowania
def test_2_minor_error_is_not_interrupted_but_listed_later(repo):
    pid, sid = chat(repo)
    obs(repo, pid, sid, "I arrived to the airport early.", "to", "at", "preposition.place", sev=3)
    assert FB.recast_directive(repo, PACK, pid, sid, "periodic", set()) is None
    assert events(repo, pid)[-1]["decision"] == "deferred_summary"
    assert any("„to” → „at”" in x for x in FB.summary_lines(repo, PACK, pid, sid))
    assert events(repo, pid)[-1]["decision"] == "summary_shown"


# 3. poprawna wypowiedź → żadnej korekty (także: przeszły → teraźniejszy bez podstaw jest odrzucany)
def test_3_correct_utterance_gets_no_correction(repo):
    pid, sid = chat(repo)
    repo.add_turn(pid, sid, "user", "We spent two weeks in Portugal.", input_mode="voice", low_probs=[])
    assert FB.recast_directive(repo, PACK, pid, sid, "periodic", set()) is None
    c = cls("I usually go to the gym, but this week I was too tired.", "was", "am", "tense.present_simple")
    assert c.status == "dropped" and c.drop_reason == "unsupported_tense"     # Qwen3 na żywo (dev d01)
    assert cls("Right now I worked at home.", "worked", "work", "tense.present_simple").status == "valid"


# 4. / 5. poprawne warianty BrE i AmE nie są błędem
@pytest.mark.parametrize("text,span,fix", [
    ("I painted the kitchen a bright colour.", "colour", "color"),              # BrE → AmE
    ("We need to organise the files.", "organise", "organize"),
])
def test_4_british_variant_is_not_an_error(text, span, fix):
    assert cls(text, span, fix, "spelling").kind == "variant"


@pytest.mark.parametrize("text,span,fix", [
    ("I painted the kitchen a bright color.", "color", "colour"),               # AmE → BrE
    ("Last year I traveled to Spain.", "traveled", "travelled"),
])
def test_5_american_variant_is_not_an_error(text, span, fix):
    assert cls(text, span, fix, "spelling").kind == "variant"


# 6. podejrzenie błędu Whispera: nie przypisujemy błędu; pytamy tylko, gdy chodzi o sens
def test_6_whisper_suspicion(repo):
    c = cls("I bought the ticket at the station.", "the ticket", "a ticket", "article.wrong", mode="voice",
            low=["the"])
    assert c.kind == "stt_suspect"
    pid, sid = chat(repo)
    obs(repo, pid, sid, "I bought the ticket.", "the", "a", "article.wrong", kind="stt_suspect")
    assert FB.recast_directive(repo, PACK, pid, sid, "periodic", set()) is None          # nic: nie przerywamy
    assert events(repo, pid)[-1]["decision"] == "skipped_stt" and events(repo, pid)[-1]["stt_suspect"]
    obs(repo, pid, sid, "Can you borrow me a pen?", "borrow", "lend", "word_choice", kind="stt_suspect")
    d = FB.recast_directive(repo, PACK, pid, sid, "periodic", set())
    assert d and "Did you mean lend?" in d and "Do not call it a mistake" in d


# 7. błędna kategoria korekty (przypadek B; bored/boring jako „irregular_past”; travel → travelled)
def test_7_wrong_category(repo):
    text = "You go to the station, put your bicycle in, lock it and take the ticket."
    c = cls(text, ", lock", " and lock", "preposition.dependent")
    assert c.status == "dropped" and c.drop_reason == "category_mismatch"
    assert cls("The talk was so boring.", "boring", "bored", "morphology.irregular_past").category == \
        "morphology.word_form"
    assert cls("Last year I travel to Spain.", "travel", "travelled", "morphology.irregular_past").category == \
        "tense.past_simple"
    assert cls("I no like it.", "no", "don't", "word_choice.confusable").category == "omission.auxiliary"
    assert cls("I arrived to the airport.", "to", "at", "preposition.place").status == "valid"   # prawdziwy przyimek


# 8. nieprawidłowa / niepełna korekta Qwen3 (A, C, E) i literówka w ręcznej poprawce transkrypcji (D)
@pytest.mark.parametrize("text,span,fix,cat", [
    ("I don't like or say about my travels last year.", "say", "talk", "word_choice"),              # A
    ("Two, maybe three times I try race in my town.", "try", "ran a", "word_choice.confusable"),     # C
    ("We need signature our email.", "signature", "sign", "word_choice.confusable"),                 # E
])
def test_8_partial_lexical_fix_is_never_an_interruption(repo, text, span, fix, cat):
    assert K.impact(text, span, fix, cat)[0] == K.MINOR
    pid, sid = chat(repo)
    obs(repo, pid, sid, text, span, fix, cat, sev=3)
    assert FB.recast_directive(repo, PACK, pid, sid, "periodic", set()) is None


def test_8b_typo_in_corrected_transcript_is_not_a_speaking_error():
    c = cls("Maybe I don't realy remember that.", "realy", "really", "spelling", mode="voice")   # D: ręczna poprawka
    assert c.status == "dropped" and c.drop_reason == "category_not_spoken"


# 9. cytat modelu nieobecny w wypowiedzi
def test_9_span_not_in_utterance_is_dropped():
    c = cls("Yesterday I go to the cinema with my friend.", "I go there", "I went there", "tense.past_simple")
    assert c.status == "dropped" and c.drop_reason == "span_not_found"


# 10. wszystkie tryby korekt zachowane
def test_10_all_correction_modes_preserved(repo):
    pid, sid = chat(repo)
    obs(repo, pid, sid, "She don't like it.", "don't", "doesn't", "agreement.subject_verb")
    assert FB.directive(repo, PACK, pid, sid, "summary", set(), "x") is None               # wyłączony w trakcie
    assert "gentle recast" in FB.directive(repo, PACK, pid, sid, "periodic", set(), "x")    # konwersacyjny
    pid2, sid2 = repo.create_profile("sc2"), None
    sid2 = repo.start_session(pid2, "chat")
    obs(repo, pid2, sid2, "She don't like it.", "don't", "doesn't", "agreement.subject_verb")
    assert "Correction step 1 of 4" in FB.directive(repo, PACK, pid2, sid2, "intensive", set(), "x")   # intensywny
    assert events(repo, pid2)[-1]["decision"] == "ladder"
    assert set(K.STYLES) == {"summary", "periodic", "intensive"}


# 11. learning logs: decyzja, waga, powód, STT, bez tekstu w JSONL
def test_11_learning_log_records_decisions_without_text(repo):
    pid, sid = chat(repo)
    obs(repo, pid, sid, "I was so boring there.", "boring", "bored", "word_choice")
    FB.recast_directive(repo, PACK, pid, sid, "periodic", set())
    e = events(repo, pid)[-1]
    for k in ("observation_id", "turn_id", "category", "severity", "tier", "reason", "decision", "stt_suspect",
              "model_confidence", "verified"):
        assert k in e, k
    assert e["verified"] is False and e["model_confidence"] == "h"               # sugestia modelu, nie zweryfikowana
    f = LL.session_file(repo, pid, sid)
    assert f and "log.correction" in f.read_text() and "boring" not in f.read_text()


# 12. bez złego wpływu na planer i mastery
def test_12_no_wrong_planner_or_mastery_effect(repo):
    pid = repo.create_profile("sc12")
    text = "You go to the station, put your bicycle in, lock it and take the ticket."
    for k in range(4):
        sid = repo.start_session(pid, "chat")
        tid = repo.add_turn(pid, sid, "user", text, input_mode="voice", low_probs=[])
        ev = TurnEval(u=[Utt(i=0, o=[Obs(s=", lock", f=" and lock", k="error", c="preposition.dependent", v=2,
                                         p="h")])])
        r = A.evaluate_batch(ev, [text], input_modes=["voice"], low_probs=[set()], pack=PACK, goals=set())[0]
        ingest.apply_turn_evaluation(repo, PACK, pid, sid, tid, r, input_mode="voice", text=text, goals=set(),
                                     now=NOW)
    assert repo.list_errors(pid) == []                                     # odrzucona kategoria nie trafia do planera
    ch = G.choose(repo, PACK, pid, NOW)
    assert ch is None or ch.source != "error"
    sid = repo.start_session(pid, "chat")
    obs(repo, pid, sid, "I was boring.", "boring", "bored", "word_choice")
    FB.recast_directive(repo, PACK, pid, sid, "periodic", set())            # korekta natychmiastowa ≠ dowód
    assert all(a["source"] != "correction" for s in repo.list_skill_states(pid)
               for a in repo.attempt_history(pid, s["skill_id"]))
    assert all(s["status"] != "mastered" for s in repo.list_skill_states(pid))
    assert PACK.rubric.correction["quality_gate"]["trusted_categories"] == []
    assert json.dumps(events(repo, pid)).count('"verified": false') >= 1
