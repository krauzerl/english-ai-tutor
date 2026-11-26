"""F7: interfejs PL/EN — jeden centralny mechanizm; wypowiedzi ucznia i tutora nie są tłumaczone."""
import json
import re
from pathlib import Path

from tutor import i18n as I

STATIC = Path(__file__).resolve().parents[1] / "tutor" / "gui" / "static"


def test_polish_is_unchanged_and_unknown_text_passes_through():
    assert I.tr("Brak zaległych powtórek na dziś.", "pl") == "Brak zaległych powtórek na dziś."
    assert I.tr("I goed home yesterday", "en") == "I goed home yesterday"          # wypowiedź ucznia
    assert I.tr("Jakiś nieznany komunikat", "en") == "Jakiś nieznany komunikat"


def test_engine_messages_translate_with_parameters():
    assert I.tr("Brak zaległych powtórek na dziś.", "en") == "No reviews due today."
    assert I.tr("[nowy temat: Zdrowe nawyki]", "en") == "[new topic: Healthy habits]" or \
        I.tr("[nowy temat: Zdrowe nawyki]", "en").startswith("[new topic:")
    assert I.tr("Poprawna odpowiedź: went", "en") == "Correct answer: went"
    assert I.tr("To czasownik nieregularny: forma przeszła to „went”, nie „goed”.", "en") == \
        "This is an irregular verb: the past form is “went”, not “goed”."
    assert I.tr("\nRozmowa #4:", "en") == "\nConversation #4:"


def test_events_never_translate_learner_or_tutor_text():
    ev = {"kind": "you", "text": "Brak zaległych powtórek na dziś."}
    assert I.tr_event(ev, "en") == ev
    assert I.tr_event({"kind": "notice", "text": "poprawiona transkrypcja — to nie jest błąd językowy"}, "en")["text"] \
        == "corrected transcript — this is not a language error"


def test_localize_walks_api_json():
    data = {"topics": [{"pl": "Zdrowe nawyki", "q": "Which habit…?"}], "n": 3}
    assert I.localize(data, "en") == {"topics": [{"pl": "Healthy habits", "q": "Which habit…?"}], "n": 3}
    assert I.localize(data, "pl") is data


def _gui_keys():
    s = (STATIC / "app.js").read_text(encoding="utf-8")
    return set(re.findall(r'\bt\("((?:[^"\\]|\\.)*)"', s))


def _dict():
    s = (STATIC / "i18n_strings.js").read_text(encoding="utf-8")
    pairs = {}
    for m in re.finditer(r'\[\s*("(?:[^"\\]|\\.)*")\s*,\s*("(?:[^"\\]|\\.)*")\s*,\s*("(?:[^"\\]|\\.)*")\s*\]', s):
        k, pl, en = (json.loads(x) for x in m.groups())
        pairs[k] = (pl, en)
    return pairs


def test_every_gui_key_has_polish_and_english():
    d = _dict()
    missing = sorted(k for k in _gui_keys() if k not in d and not k.endswith("."))   # "area." + nazwa: dynamiczne
    assert not missing, missing[:20]
    assert all(pl and en for pl, en in d.values())


def test_english_texts_have_no_polish_letters():
    bad = [en for _pl, en in _dict().values() if re.search("[ąćęłńóśźżĄĆĘŁŃÓŚŹŻ]", en)]
    assert not bad, bad[:10]


def test_ui_lang_setting_is_per_profile(repo):
    from tutor.app import settings as ST
    a, b = repo.create_profile("a"), repo.create_profile("b")
    ST.update(repo, a, {"ui_lang": "en"})
    assert ST.effective(repo, a)["ui_lang"] == "en" and ST.effective(repo, b)["ui_lang"] == "pl"
    assert ST.effective(repo, a)["target_lang"] == "en"                       # język nauki niezależny


def test_exam_texts_translated_including_yaml_newline_and_joined_labels():
    """Audyt F7: ekran Egzaminy w EN pokazywał polskie zastrzeżenie (klucz z \\n), uwagi sekcji i tematy."""
    from tutor.app import exams as EX
    from tutor.i18n import tr
    p = EX.load_all()["e8_english"]
    texts = [p["disclaimer_pl"], p["official"]["note_pl"], p["speaking_extra"]["note_pl"],
             *(t["pl"] for t in p["speaking_extra"]["topics"]),
             *(f"{s['name_pl']}: {s['note_pl']}" for s in p["sections"] if s.get("note_pl"))]
    for t in texts:
        assert tr(t, "en") != t, t
    assert tr("Słuchanie: coś nowego", "en") == "Słuchanie: coś nowego"     # tylko gdy obie części są znane


def test_chat_session_events_in_english():
    """Zrzuty README: w sesji EN nazwa tematu, ustawienia rozmowy i scenka zostawały po polsku."""
    from tutor.app import topics as T
    from tutor.gui.runner import classify
    from tutor.i18n import tr, tr_event

    def ev(line, lang="en"):
        return tr_event(classify(line), lang)["text"]
    topic = ev("Quick Chat — temat: Miejsce, w którym mieszkasz. (Powiedz „change the topic”, by zmienić; q = koniec.)")
    assert topic.startswith("Quick Chat — temat: The place where you live.")       # prefiks czyta app.js
    assert ev("Ustawienia rozmowy: B1 · General English · Naturalna rozmowa") == "B1 · General English · Natural conversation"
    rp = T.get("med.rp.trauma")
    assert ev("Scenariusz: " + rp["context_pl"]) == f"You are {rp['learner']}. The tutor plays {rp['role']}."
    assert ev("Scenariusz: " + rp["context_pl"], "pl") == rp["context_pl"]
    assert tr("bez limitu", "en") == "no limit" and tr("B1 · coś nowego", "en") == "B1 · coś nowego"
