"""B-lite: `target_patterns` — tylko konstrukcje rozpoznawalne deterministycznie; kontrprzykłady i poprawne
alternatywy. Wzorzec potwierdza OBECNOŚĆ konstrukcji w cytacie modelu, nie poprawność zdania; brak dopasowania
nie jest błędem ucznia (tylko brak dowodu)."""
import re

import pytest

from tutor.pedagogy import content as C

CASES = {
    "en.gram.present_perfect": (
        ["I have finished the report", "She has never been to Rome", "We've already eaten", "I haven't seen it",
         "They have worked here"],
        ["I have went there", "I have a car", "He has to go", "I have seed", "I have need", "I had finished"]),
    "en.gram.irregular_past": (
        ["Yesterday I went home", "We saw a film", "She wrote a letter", "I forgot my keys", "He became a doctor"],
        ["I didn't went", "I have went", "I want to went", "I will went", "I go home", "turn left"]),
    "en.gram.comparatives": (
        ["She is taller than me", "This is more expensive than that", "It's better than before", "older than him"],
        ["He is more taller than me", "rather than", "other than that", "I'd rather walk", "more better than",
         "the tallest"]),
    "en.gram.third_conditional": (
        ["If I had known, I would have come", "If she hadn't left early, she would have met him",
         "if we had driven we could have arrived"],
        ["If I had money, I would have a car", "If I had money I would buy it", "If I knew, I would tell you"]),
}


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def test_only_reviewed_constructions_have_patterns(pack):
    assert {s.id for s in pack.skills.values() if s.target_patterns} == set(CASES)


@pytest.mark.parametrize("skill", sorted(CASES))
def test_patterns_positive_and_counterexamples(pack, skill):
    pats = pack.skills[skill].target_patterns
    pos, neg = CASES[skill]
    for t in pos:
        assert any(re.search(p, t, re.I) for p in pats), (skill, t)
    for t in neg:
        assert not any(re.search(p, t, re.I) for p in pats), (skill, t)
