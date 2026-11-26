"""F4.6/C4: adapter LanguageTool i scalenie (T-LT-1..6). Bez prawdziwego serwera: fikstury + lokalny serwer testowy."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from tests.test_f4_flow import GOALS, evaluate
from tutor.app import languagetool as LT
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import lt_merge as M
from tutor.pedagogy.schemas import Obs, TurnEval, Use, Utt

FIX = Path(__file__).parent / "fixtures" / "lt" / "check_unverified.json"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def cfg(**kw):
    return {"enabled": True, "url": "http://127.0.0.1:9", "timeout": 0.5, **kw}


def lt_obs(pack, matches, text, mode="text", trusted=frozenset()):
    forms = {f.lower() for e in C.load_vocab(pack.root.parent).values() for f in e.forms}
    return M.to_obs(matches, text, pack.lt_map, input_mode=mode, known_forms=forms, trusted_rules=set(trusted),
                    version="6.6")


def test_lt_1_disabled_or_unreachable_returns_none():  # T-LT-1
    assert LT.check("hello", {"enabled": False, "url": "http://127.0.0.1:9"}) is None
    assert LT.check("hello", cfg()) is None            # port zamknięty ⇒ None, bez wyjątku

    class Slow:
        trust_env = True

        def post(self, *a, **k):
            import requests
            raise requests.Timeout()
    assert LT.check("hello", cfg(), session=Slow()) is None


def test_lt_1_non_200_and_redirect_not_followed():
    hits = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            hits.append(self.path)
            self.send_response(302)
            self.send_header("Location", "http://example.invalid/steal")
            self.end_headers()

        def log_message(self, *a):
            pass
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        assert LT.check("My text", cfg(url=f"http://127.0.0.1:{srv.server_port}")) is None
        assert hits == ["/v2/check"]                   # jedno żądanie: przekierowanie NIE było śledzone
    finally:
        srv.shutdown()


def test_lt_1_parse_fixture_and_params():
    ms = LT.parse(json.loads(FIX.read_text()))
    assert ms[0].rule_id == "EN_A_VS_AN" and ms[0].replacements == ("an",) and ms[1].category_id == "GRAMMAR"
    sent = {}

    class Ok:
        trust_env = True

        def post(self, url, data, timeout, allow_redirects):
            sent.update(url=url, data=data, redirects=allow_redirects)

            class R:
                status_code = 200

                def json(self_):
                    return json.loads(FIX.read_text())
            return R()
    s = Ok()
    out = LT.check("x" * 5000, cfg(), disabled_categories=["STYLE"], session=s)
    assert len(out) == 5 and len(sent["data"]["text"]) == LT.MAX_TEXT
    assert sent["redirects"] is False and s.trust_env is False and sent["data"]["disabledCategories"] == "STYLE"


@pytest.mark.parametrize("url", ["http://example.com:8081", "http://192.168.1.5:8081", "https://api.languagetool.org",
                                 "http://user:pw@127.0.0.1:8081", "ftp://127.0.0.1", "http://127.0.0.1.evil.com"])
def test_lt_2_non_local_urls_rejected(url):  # T-LT-2
    with pytest.raises(LT.LTConfigError):
        LT.validate_url(url)
    with pytest.raises(LT.LTConfigError):
        LT.settings({"languagetool": {"enabled": False, "url": url}})   # także przy wyłączonym LT


@pytest.mark.parametrize("url", ["http://127.0.0.1:8081", "http://localhost:8081/", "http://[::1]:8081"])
def test_lt_2_local_urls_ok(url):
    assert LT.validate_url(url).startswith("http://")
    assert LT.settings({})["enabled"] is False          # domyślnie wyłączony


def test_lt_3_mapping(pack):  # T-LT-3
    ms = LT.parse(json.loads(FIX.read_text()))
    text = "This is a apple. works fine colour"
    obs, st = lt_obs(pack, ms, text)
    cats = {o.c for o in obs}
    assert "article.wrong" in cats and "agreement.subject_verb" in cats
    assert st["ignored"] == 1 and st["unmapped:UNKNOWN_RULE"] == 1 and st["variant"] == 1   # colour→color: BrE/AmE
    assert all(o.k == "error" and o.src == "languagetool-6.6" and o.p == "l" for o in obs)  # brak zaufanych reguł
    tax = A.allowed_categories(pack.errors)
    assert all(o.c in tax for o in obs)


def test_lt_4_merge_rules(pack):  # T-LT-4: R1–R7
    text = "She have a apple and goes home"
    B = lambda s, f, c, p="m", k="error": Obs(s=s, f=f, k=k, c=c, v=2, p=p)   # noqa: E731
    L = lambda s, f, c, p="l": Obs(s=s, f=f, k="error", c=c, v=1, p=p, src="languagetool-6.6")  # noqa: E731
    # R1: ten sam span i zgodna kategoria ⇒ 1 obserwacja, poprawka Bielika, pewność +1, źródło bielik+lt
    out, _ = M.merge([B("She have", "She has", "agreement.subject_verb", "m")],
                     [L("She have", "She has", "agreement.subject_verb")], text)
    assert len(out) == 1 and out[0].p == "m" and out[0].src == "bielik+lt" and out[0].f == "She has"  # F1: bez +1
    out, _ = M.merge([B("She have", "She has", "agreement.subject_verb", "l")],
                     [L("She have", "He has", "agreement.subject_verb")], text)
    assert out[0].p == "l" and out[0].src is None   # F4.7: różne edycje (LT zmienia też podmiot) ≠ zgodność
    # R2: ta sama poprawka, inna kategoria ⇒ kategoria i pewność Bielika, `src` bielik+lt-fix (F4.7), alternatywa w logu
    out, alts = M.merge([B("a apple", "an apple", "article.wrong")], [L("a apple", "an apple", "word_choice")], text)
    assert len(out) == 1 and out[0].c == "article.wrong" and out[0].p == "m" and out[0].src == "bielik+lt-fix"
    assert len(alts) == 1
    # R3: tylko Bielik
    out, _ = M.merge([B("a apple", "an apple", "article.wrong")], [], text)
    assert out == [B("a apple", "an apple", "article.wrong")]
    # R4/R5: tylko LT (p ustawia to_obs): trafia jako kandydat, jedna obserwacja na span
    out, _ = M.merge([], [L("a apple", "an apple", "article.wrong", "m"), ], text)
    assert len(out) == 1 and out[0].p == "m"
    out, _ = M.merge([], [L("a apple", "an apple", "article.wrong", "l")], text)
    assert out[0].p == "l"
    # R6: Bielik oznaczył jako wariant/naturalne ⇒ LT nie dodaje błędu
    out, alts = M.merge([B("goes home", "goes home", "tense", k="natural")], [L("goes home", "go home", "tense")], text)
    assert [o.k for o in out] == ["natural"] and len(alts) == 1
    # R7: Bielik uznał konstrukcję za poprawną (t: ok) ⇒ LT p=l
    out, _ = M.merge([], [L("goes", "go", "agreement.subject_verb", "m")], text, ok_spans=["goes home"])
    assert out[0].p == "l"


def test_lt_4_trusted_rule_gives_m_only_for_text(pack):
    ms = LT.parse(json.loads(FIX.read_text()))
    o, _ = lt_obs(pack, ms, "This is a apple. works fine colour", trusted={"EN_A_VS_AN"})
    assert next(x for x in o if x.c == "article.wrong").p == "m"
    v, _ = lt_obs(pack, ms, "This is a apple. works fine colour", mode="voice", trusted={"EN_A_VS_AN"})
    assert not any(x.c == "article.wrong" for x in v)          # voice: false ⇒ pominięta w głosie


def test_lt_4_merge_eval_and_unrated_stays_unrated(pack):
    text = "She have a dog."
    ev = TurnEval(u=[Utt(i=0, o=[Obs(s="She have", f="She has", k="error", c="agreement.subject_verb", v=2, p="m")],
                         t=[Use(id="en.gram.present_simple", r="ok", s="a dog")])])
    lt = [[Obs(s="She have", f="She has", k="error", c="agreement.subject_verb", v=1, p="l", src="languagetool-6.6")]]
    merged = M.merge_eval(ev, [text], lt)
    res = A.evaluate_batch(merged, [text], input_modes=["text"], low_probs=[set()], pack=pack, goals=GOALS | {"en.gram.present_simple"})[0]
    assert res.rated and len(res.observations) == 1 and res.observations[0].confidence == "m"   # F1: bez +1
    assert res.observations[0].source == "bielik+lt"
    # brak oceny modelu ⇒ nieoceniona; LT sam nie dowodzi poprawności ani błędu
    none = A.evaluate_batch(None, [text], input_modes=["text"], low_probs=[set()], pack=pack, goals=GOALS)[0]
    assert not none.rated


def test_lt_5_voice(pack):  # T-LT-5
    text = "I goed to the shop and gonna buy colour"
    ms = [LT.LTMatch(0, 1, "x", ("A",), "TYPO_R", "misspelling", "TYPOS"),
          LT.LTMatch(2, 4, "x", ("went",), "HE_VERB_AGR", "grammar", "GRAMMAR")]
    obs, st = lt_obs(pack, ms, text, mode="voice")
    assert [o.c for o in obs] == ["agreement.subject_verb"] and st["voice"] == 1   # pisownia w głosie odrzucona
    # słowo z niskim prob / para z stt_confusables ⇒ stt_suspect (przez classify)
    r = evaluate(pack, "He can go there", o=[Obs(s="can", f="can't", k="error", c="agreement", v=2, p="m")],
                 mode="voice")
    assert r.observations[0].kind == "stt_suspect"
    # formy potoczne (07 §4.3): „gonna → going to” to wariant, nie błąd; zdania z kluczem ich nie akceptują
    r = evaluate(pack, "I am gonna go.", o=[Obs(s="gonna go", f="going to go", k="error", c="tense.future", v=1, p="m")])
    assert r.observations[0].kind == "variant"
    assert not C.expand_answers(["I am going to go"], pack.variants, "grammar") >= {"i am gonna go"}
    assert "i am gonna go" in C.expand_answers(["I am going to go"], pack.variants, "conversation")


def test_lt_6_bre_spelling_not_error(pack):  # T-LT-6
    for span, fix in [("colour", "color"), ("travelling", "traveling"), ("centre", "center"),
                      ("organise", "organize"), ("colour", "colours")]:
        ms = [LT.LTMatch(0, len(span), "x", (fix,), "MORFOLOGIK_RULE_EN_US", "misspelling", "TYPOS")]
        obs, st = lt_obs(pack, ms, f"{span} is nice")
        if fix != "colours":
            assert obs == [] and st["variant"] == 1, (span, fix)
    ms = [LT.LTMatch(0, 6, "x", ("friend",), "MORFOLOGIK_RULE_EN_US", "misspelling", "TYPOS")]
    obs, _ = lt_obs(pack, [LT.LTMatch(0, 6, "x", ("friend",), "MORFOLOGIK_RULE_EN_US", "misspelling", "TYPOS")], "freind is nice")
    assert len(obs) == 1 and obs[0].c == "spelling"


def test_lt_contract_real_6_6_response(pack):
    """Kontrakt na zapisie prawdziwej odpowiedzi LT 6.6 (nie fikstury pisanej ręcznie)."""
    d = json.loads((Path(__file__).parent / "fixtures/lt/check_real_6_6.json").read_text())
    ms = LT.parse(d)
    ids = {m.rule_id for m in ms}
    assert {"HE_VERB_AGR", "EN_A_VS_AN", "MORFOLOGIK_RULE_EN_US", "I_AM_VB"} <= ids
    assert pack.lt_map.lt_version_tested == "6.6"
    obs, st = lt_obs(pack, ms, d["_text"])
    assert {"agreement.subject_verb", "article.wrong", "morphology.word_form"} <= {o.c for o in obs}
    assert st["variant"] == 1 and not st["unmapped:HE_VERB_AGR"]      # „colour” (BrE) to wariant, nie błąd
    assert not any(o.s == "I have 25 years" for o in obs)             # brak wykrycia ≠ poprawność (kalka niezłapana)
