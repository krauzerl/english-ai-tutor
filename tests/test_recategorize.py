"""F7: kategoria błędu od modelu bywa niezgodna z samą edycją („drinks → drink” opisane jako irregular past).

Korekta jest deterministyczna i wąska: pojedyncza zmiana końcówki -s/-es/-ies czasownika tuż po zaimku-podmiocie
to zgodność podmiotu z orzeczeniem, a nie forma przeszła. Inne przypadki zostają bez zmian.
"""
import pytest

from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import edits as E
from tutor.pedagogy import errors as ER
from tutor.pedagogy.schemas import Obs


@pytest.mark.parametrize("text,span,fix,cat", [
    ("After work I usually drinks tea.", "I usually drinks", "I usually drink", "morphology.irregular_past"),
    ("After work I usually drinks tea.", "drinks", "drink", "morphology.irregular_past"),
    ("She go to school by bus.", "go", "goes", "tense.past_simple"),
    ("They watches films every day.", "watches", "watch", "morphology"),
    ("He really study a lot.", "study", "studies", "morphology.irregular_past"),
])
def test_third_person_s_after_pronoun_is_agreement(text, span, fix, cat):
    assert E.recategorize(text, span, fix, cat) == "agreement.subject_verb"


@pytest.mark.parametrize("text,span,fix,cat", [
    ("Yesterday I goed home.", "goed", "went", "morphology.irregular_past"),     # prawdziwa forma przeszła
    ("I have two cat.", "cat", "cats", "morphology"),                           # liczba mnoga rzeczownika
    ("My wife drink tea.", "drink", "drinks", "morphology.irregular_past"),     # podmiot nie jest zaimkiem: bez zgadywania
    ("I usually drinks tea.", "drinks", "drink", "agreement.subject_verb"),      # już poprawna kategoria
    ("I usually drinks tea.", "drinks", "drink", "word_choice"),                 # kategoria spoza rodziny „przeszłej”
])
def test_other_cases_unchanged(text, span, fix, cat):
    assert E.recategorize(text, span, fix, cat) == cat


def test_classify_stores_corrected_category():
    pack = C.load("en")
    text = "After work I usually drinks tea and watch films with my wife."
    o = Obs(s="drinks", f="drink", k="error", c="morphology.irregular_past", v=2, p="h")
    c = A.classify(o, text, input_mode="text", low_prob_words=set(), pre=A.prefilter(text, pack.disfluency),
                   variants=pack.variants, confusables=pack.confusables, taxonomy=ER.allowed_categories(pack.errors),
                   rubric=pack.rubric)
    assert (c.status, c.category) == ("valid", "agreement.subject_verb")
