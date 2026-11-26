"""Niezależna recenzja banku F7: zadania zamknięte mają dokładnie jedną poprawną odpowiedź.

Każdy wpis = opcja, która BYŁA w zadaniu i też jest poprawną angielszczyzną (uczeń tracił punkt za dobrą
odpowiedź). Test pilnuje, żeby taki dystraktor nie wrócił.
"""
from tutor.pedagogy import content as C

AMBIGUOUS = {
    "en.f7.gram.b2.01": "was already leaving",    # "the train was already leaving" — poprawne gramatycznie
    "en.f7.gram.c1.02": "would live",             # mieszany tryb: "I would live in London now" — poprawne
    "en.f7.vocab.a1.01": "clean",                 # BrE: "I clean my teeth"
    "en.f7.vocab.a2.02": "put",                   # "Can I put this jacket on?" — poprawne
    "en.f7.read.a1.02": "Every evening",          # sklep po 18:00 też jest zamknięty
}


def test_no_second_correct_option():
    pack = C.load("en")
    for iid, bad in AMBIGUOUS.items():
        it = pack.items[iid]
        assert bad not in (it.options or []), iid
        assert it.answers[0] in it.options, iid


def test_can_item_has_disambiguating_context():
    it = C.load("en").items["en.f7.gram.a1.03"]
    assert "Yes, I can" in it.prompt
