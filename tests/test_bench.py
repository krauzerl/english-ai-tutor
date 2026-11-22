"""F4.6/C5: harness benchmarku (T-BENCH-1..4) + jednoznaczne dopasowanie, minimalna czułość, brama bez recenzji."""
import json
from collections import Counter

import pytest

from bench import grammar as G
from tests.llm_fakes import FakeProvider
from tutor.app.languagetool import LTMatch
from tutor.llm.base import Reply, Usage
from tutor.llm.structured import structured
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def cl(span, fix, cat="agreement.subject_verb", p="m"):
    return A.Classified("error", "valid", None, span, fix, cat, 2, p)


def case(id_, set_, text, gold=(), status="draft", mode="text"):
    return G.Case(id_, set_, mode, text, list(gold), words=[[w, 0, 1, 0.9] for w in text.split()] if mode == "voice" else None,
                  status=status)


def test_bench_1_gold_set_shape():  # T-BENCH-1
    cases = G.load_cases()
    assert G.validate_cases(cases) == []
    assert Counter(c.set for c in cases) == G.SET_SIZES and len(cases) == 130
    assert all(c.status == "draft" for c in cases)                      # nic nie jest zrecenzowane przez człowieka
    assert all(c.input_mode == "voice" for c in cases if c.set in ("S", "D", "C3"))
    assert all(c.gold for c in cases if c.set in ("E1", "E2")) and not any(c.gold for c in cases if c.set in G.CLEAN_SETS)
    f3 = json.loads(json.dumps(__import__("yaml").safe_load((G.CASES / "f3_mismatch.yaml").read_text())))
    assert len(f3) == 11 and all(r["human_key"] is None for r in f3)
    bad = [case("x", "E1", "hello world", [G.Gold("nope", ["x"], "article")])]
    assert any("dosłownie" in e for e in G.validate_cases(bad, sizes=None))


def test_bench_2_metrics_by_hand():  # T-BENCH-2
    t = "She have a dog and he work here."
    gold = [G.Gold("She have", ["She has"], "agreement.subject_verb"), G.Gold("he work", ["he works"], "agreement.subject_verb")]
    runs = [
        G.CaseRun(case("e", "E2", t, gold), reports=[cl("She have", "She has"), cl("work", "works"), cl("a dog", "dogs", "article")]),
        G.CaseRun(case("c1", "C1", "I am fine."), reports=[cl("am", "is")]),     # fałszywy alarm
        G.CaseRun(case("c2", "C2", "The colour is nice."), reports=[]),
        G.CaseRun(case("c3", "C1", "OK then."), reports=[]),
    ]
    s = G.score(runs)
    assert (s["tp"], s["reports"], s["gold"]) == (2, 4, 2)               # 3 zgłoszenia w E2 + 1 w C1; 2 trafienia
    assert s["precision"] == 0.5 and s["recall"] == 1.0
    assert s["fpr"]["C1"] == 0.5 and s["fpr"]["C2"] == 0.0 and s["fpr_c123"] == pytest.approx(1 / 3)
    assert s["correction_accuracy"] == 1.0 and s["category_agreement"] == 1.0
    lo, hi = G.wilson(2, 4)
    assert (round(lo, 3), round(hi, 3)) == (0.15, 0.85)                  # wartość wzorcowa Wilsona
    assert s["per_category"]["article"] == {"reports": 1, "hits": 0, "precision": 0.0}


def test_bench_2_one_to_one_matching():
    t = "She have a dog."
    g = [G.Gold("She have", ["She has"], "agreement.subject_verb")]
    # dwa zgłoszenia w ten sam span złoty: 1 trafienie, 1 fałszywy alarm (bez wielokrotnego naliczania)
    m = G.match(t, [cl("She have", "She has"), cl("have", "has")], g)
    assert len(m) == 1
    run = G.CaseRun(case("e", "E1", t, g), reports=[cl("She have", "She has"), cl("have", "has")])
    s = G.score([run])
    assert (s["tp"], s["reports"]) == (1, 2) and s["precision"] == 0.5
    # jedno szerokie zgłoszenie dotykające dwóch spanów złotych liczy się najwyżej raz
    t2 = "She have a dog and he work."
    g2 = [G.Gold("She have", ["She has"], "x"), G.Gold("he work", ["he works"], "x")]
    assert len(G.match(t2, [cl("She have a dog and he work", "She has a dog and he works")], g2)) == 1
    # maksymalne skojarzenie: zgłoszenie A pasuje do obu, B tylko do 1 ⇒ oba przypisane
    assert G.one_to_one({0: [0, 1], 1: [0]}) == {1: 0, 0: 1}


def test_bench_2_correction_and_meaning_guard():
    t = "I have 25 years and I work in IT."
    g = G.Gold("I have 25 years", ["I am 25", "I'm 25 years old"], "l1_calque.have_years")
    assert G.correction_ok(t, cl("I have 25 years", "I'm 25 years old"), g)
    assert not G.correction_ok(t, cl("I have 25 years", "I am 52"), g)
    assert G.meaning_guard_fail(t, cl("I have 25 years and I work", "Nothing here is the same at all"))
    assert not G.meaning_guard_fail(t, cl("I have 25 years", "I am 25"))


def perfect():
    return {"cases": 130, "unrated": 0, "reports": 60, "tp": 55, "gold": 60, "precision": 0.9, "precision_ci": (0.8, 0.95),
            "recall": 0.9, "recall_ci": (0.8, 0.95), "fpr": {"C2": 0.0}, "fpr_c123": 0.02, "stt_clean": 1.0,
            "disfluency_clean": 1.0, "correction_accuracy": 0.9, "category_agreement": 0.9, "meaning_human": 0.97,
            "explanation_human": 4.5, "latency_ms": {"lt_p50": 20, "lt_p95": 50, "queue_p50_s": 1, "queue_p95_s": 3},
            "per_category": {}}


def test_gate_requires_recall_reports_and_reviewed_gold(pack):
    g = pack.rubric.correction["quality_gate"]
    ok = G.gate(perfect(), g, reviewed_cases=130, reviewed_gold=60)
    assert ok["eligible"] and not ok["failed"]
    assert not G.gate(perfect(), g, reviewed_cases=0, reviewed_gold=0)["eligible"]            # brak recenzji człowieka
    assert "zrecenzowanych przypadków 0 < 100" in G.gate(perfect(), g, reviewed_cases=0, reviewed_gold=0)["blockers"]
    lazy = {**perfect(), "reports": 0, "tp": 0, "precision": None, "precision_ci": None, "recall": 0.0,
            "recall_ci": (0.0, 0.05)}                                                         # system, który nic nie wykrywa
    r = G.gate(lazy, g, reviewed_cases=130, reviewed_gold=60)
    assert not r["eligible"] and any(k.startswith("recall") for k in r["failed"]) and any(k.startswith("reports") for k in r["failed"])
    low_recall = {**perfect(), "recall": 0.3, "recall_ci": (0.2, 0.4)}
    assert not G.gate(low_recall, g, reviewed_cases=130, reviewed_gold=60)["eligible"]
    no_human = {**perfect(), "meaning_human": None, "explanation_human": None}
    assert not G.gate(no_human, g, reviewed_cases=130, reviewed_gold=60)["eligible"]          # ocena człowieka wymagana
    assert pack.rubric.correction["quality_gate"]["trusted_categories"] == []
    assert pack.rubric.correction["quality_gate"]["lt_trusted_rules"] == []
    assert pack.rubric.correction["quality_gate"]["bielik_benchmark_passed"] is False


def test_bench_3_only_reviewed_and_preliminary(pack, tmp_path):  # T-BENCH-3
    import yaml
    raw = yaml.safe_load(G.CASES.joinpath("grammar_gold.yaml").read_text())
    raw[0]["review"] = {"status": "human_reviewed", "reviewer": "x", "reviewed_at": "2026-01-01"}
    p = tmp_path / "g.yaml"
    p.write_text(yaml.safe_dump(raw, allow_unicode=True))
    assert len(G.load_cases(p, only_reviewed=True)) == 1 and len(G.load_cases(p)) == 130
    assert G.load_cases(only_reviewed=True) == []
    res, meta = G.run_all(["B"], [case("c", "C1", "I am fine.")], pack, lt_fn=lambda t: [])
    md = G.render_md(res, meta)
    assert "WSTĘPNY" in md and "NIE dopuszczony" in md and res["B"]["gate"]["eligible"] is False


class ScriptedProvider(FakeProvider):
    """Odpowiada JSON-em TurnEval zależnie od tekstu wypowiedzi w prompcie (deterministycznie)."""
    def __init__(self, table):
        super().__init__()
        self.table = table

    def chat(self, messages, *, temperature=0.0, max_tokens=256, schema=None):
        prompt = messages[0].content if hasattr(messages[0], "content") else str(messages[0])
        for text, obs in self.table.items():
            if json.dumps(text, ensure_ascii=False) in prompt:
                return Reply(json.dumps({"u": [{"i": 0, "o": obs}]}), Usage(1, 1), "fake", "m")
        return Reply(json.dumps({"u": [{"i": 0, "o": []}]}), Usage(1, 1), "fake", "m")


def test_bench_4_systems_deterministic_on_fakes(pack):  # T-BENCH-4
    t1, t2 = "She have a dog.", "I am fine."
    cases = [case("e", "E1", t1, [G.Gold("She have", ["She has"], "agreement.subject_verb")]), case("c", "C1", t2)]
    prov = ScriptedProvider({t1: [{"s": "She have", "f": "She has", "k": "error", "c": "agreement.subject_verb",
                                   "v": 2, "p": "m"}]})
    lt = {t1: [LTMatch(0, 8, "m", ("She has",), "HE_VERB_AGR", "grammar", "GRAMMAR")],
          t2: [LTMatch(2, 2, "m", ("is",), "HE_VERB_AGR", "grammar", "GRAMMAR")]}
    lt_fn = lambda t: lt.get(t, [])  # noqa: E731
    out = []
    for _ in range(2):
        res, _ = G.run_all(["A", "B", "C"], cases, pack, provider=prov, structured=structured, lt_fn=lt_fn)
        out.append({k: (v["score"]["tp"], v["score"]["reports"], v["score"]["fpr_c123"]) for k, v in res.items()})
    assert out[0] == out[1]
    assert out[0]["A"] == (1, 1, 0.0)                                  # Bielik trafia, brak fałszywych alarmów
    assert out[0]["B"] == (1, 2, 1.0)                                  # LT: trafienie + fałszywy alarm na poprawnym zdaniu
    assert out[0]["C"] == (1, 1, 0.0)                                  # C: LT-only ma p=l ⇒ tylko sugestia; Bielik+LT podnosi p
    resC, _ = G.run_all(["C"], cases, pack, provider=prov, structured=structured, lt_fn=lt_fn)
    assert resC["C"]["runs"][0].reports[0].confidence == "h" and resC["C"]["runs"][1].suggestions
    # LT niedostępny: B nieocenione, C degraduje do A
    resB, _ = G.run_all(["B", "C"], cases, pack, provider=prov, structured=structured, lt_fn=lambda t: None)
    assert resB["B"]["score"]["unrated"] == 2 and resB["C"]["score"]["tp"] == 1


def test_brae_ame_and_stt_sets_not_counted(pack):
    """Przypadek głosowy z niskim prob: błąd modelu w tym słowie to stt_suspect, nie zgłoszenie liczone."""
    t = "I have apple for lunch"
    c = G.Case("s", "S", "voice", t, [], words=[["I", 0, 1, .9], ["have", 1, 2, .9], ["apple", 2, 3, .38], ["for", 3, 4, .9],
                                                ["lunch", 4, 5, .9]])
    prov = ScriptedProvider({t: [{"s": "have apple", "f": "have an apple", "k": "error", "c": "article.missing", "v": 2, "p": "h"}]})
    run = G.run_case("A", c, pack, provider=prov, structured=structured)
    assert run.reports == [] and G.score([run])["stt_clean"] == 1.0
