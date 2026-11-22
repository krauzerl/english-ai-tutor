"""F4.6/C2: słownictwo (T-VOC-1..7). Testy bez modeli i sieci."""
import csv
import random
from datetime import timedelta
from pathlib import Path

import pytest

from tests.test_f4_flow import GOALS, NOW, evaluate, pinput
from tools import import_ngsl as N
from tutor.app import ingest
from tutor.pedagogy import assessment as A
from tutor.pedagogy import content as C
from tutor.pedagogy import planner as P
from tutor.pedagogy import vocab as V

SRC = Path.home() / ".local/share/english-ai-tutor/content_sources/vocabulary"
needs_src = pytest.mark.skipif(not (SRC / "NGSL_12_stats.csv").exists(), reason="brak lokalnych źródeł NGSL")


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture(scope="module")
def ngsl(pack):
    return C.load_vocab(pack.root.parent, "en")


def test_vocab_1_committed_list(ngsl):  # T-VOC-1 (plik w repo)
    assert len(ngsl) == 2809 and all(e.cefr == "" and e.gloss_pl == "" for e in ngsl.values())
    ranks = [e.rank for e in ngsl.values()]
    assert len(set(ranks)) == 2809 and ngsl["the"].rank == 1 and ngsl["the"].freq_band == 1
    assert ngsl["found"].homograph and ngsl["color"].variants


@needs_src
def test_vocab_1_rank_independent_of_row_order(tmp_path):  # T-VOC-1: przetasowanie wejścia nie zmienia rangi
    s = SRC / "NGSL_1.2_lemmatized_for_teaching.csv"
    lines = [ln for ln in s.read_text(encoding="utf8").splitlines() if not ln.startswith("##") and ln.strip()]
    random.Random(1).shuffle(lines)
    shuf = tmp_path / "t.csv"
    shuf.write_text("\n".join(lines), encoding="utf8")
    a = N.build(s, SRC / "NGSL_1.2_with_English_definitions.xlsx", SRC / "NGSL_12_stats.csv")
    b = N.build(shuf, SRC / "NGSL_1.2_with_English_definitions.xlsx", SRC / "NGSL_12_stats.csv")
    assert {r["lemma"]: r["rank"] for r in a} == {r["lemma"]: r["rank"] for r in b}
    assert N.build(s, SRC / "NGSL_1.2_with_English_definitions.xlsx", None)[0]["rank"] == ""  # bez stats: puste
    csv_path = tmp_path / "o.csv"
    N.write(a, csv_path, {})
    assert len(list(csv.DictReader(ln for ln in csv_path.open() if not ln.startswith("#")))) == 2809


def test_vocab_2_variants_only_when_both_forms_present():  # T-VOC-2
    assert ("color", "colour") in N.variants_of(["color", "colors", "colour"])
    assert N.variants_of(["color", "colors"]) == []
    assert ("organize", "organise") in N.variants_of(["organize", "organise"])
    assert ("traveled", "travelled") in N.variants_of(["travel", "traveled", "travelled"])


def test_vocab_3_no_cards_until_trigger(repo, pack):  # T-VOC-3
    pid = repo.create_profile("V")
    assert repo.vocab_card_stats(pid, "2026-11-22") == (0, 0) and repo.list_vocab(pid) == []
    r = ingest.record_vocab_recall(repo, pack, pid, "travel", True, now=NOW)  # brak wyzwalacza
    assert not r["card_created"] and repo.get_card(pid, "vocab", "travel") is None
    r = ingest.record_vocab_recall(repo, pack, pid, "travel", False, now=NOW, trigger="lesson_target_not_recalled")
    assert r["card_created"] and repo.get_card(pid, "vocab", "travel")
    assert not V.card_allowed("recognized", pack.rubric, active_cards=0, new_today=0)  # rozpoznanie nie tworzy kart
    # limity dzienny i łączny
    assert not V.card_allowed("manual", pack.rubric, active_cards=0, new_today=pack.rubric.srs["vocab_new_per_day"])
    assert not V.card_allowed("manual", pack.rubric, active_cards=pack.rubric.srs["vocab_max_active"], new_today=0)
    for k in range(pack.rubric.srs["vocab_new_per_day"] + 3):  # 10 nowych dziennie
        ingest.record_vocab_recall(repo, pack, pid, f"w{k}", False, now=NOW, trigger="manual")
    assert repo.vocab_card_stats(pid, "2026-11-22")[1] == pack.rubric.srs["vocab_new_per_day"]


def test_vocab_4_transitions(pack):  # T-VOC-4
    rb, st = pack.rubric, {}
    st |= V.apply_event(st, "recognized", rb)
    assert st["knowledge"] == "passive"
    st |= V.apply_event(st, "recall_ok", rb, day="d1")
    assert st["knowledge"] == "passive"
    st |= V.apply_event(st, "recall_ok", rb, day="d1")      # ten sam dzień: bez postępu
    assert st["knowledge"] == "passive" and st["recall_ok"] == 1
    st |= V.apply_event(st, "recall_ok", rb, day="d2")
    assert st["knowledge"] == "active"
    st |= V.apply_event(st, "recall_fail", rb)
    assert st["knowledge"] == "active"
    st |= V.apply_event(st, "recall_fail", rb)              # 2 porażki z rzędu
    assert st["knowledge"] == "passive"
    st |= V.apply_event(st, "used_ok", rb, session=1)
    st |= V.apply_event(st, "used_ok", rb, session=1)       # ta sama sesja ≠ druga sesja
    assert st["knowledge"] == "passive"
    st |= V.apply_event(st, "used_ok", rb, session=2)
    assert st["knowledge"] == "active"
    for _ in range(5):
        st |= V.apply_event(st, "recall_fail", rb)
    assert st["knowledge"] != "unknown"                     # active nigdy → unknown


def test_vocab_5_yes_no_test(pack):  # T-VOC-5
    rb = pack.rubric
    words = {f"w{i}": True for i in range(10)}
    pseudo = {f"p{i}": False for i in range(5)}
    bands = {w: 1 for w in words}
    ok = V.recognition_result({**words, **pseudo}, bands, pseudo, rb, pseudo_reviewed=True)
    assert not ok["rejected"] and ok["bands"][1] == 1.0 and not ok["preliminary"] and len(ok["passive"]) == 10
    guess = V.recognition_result({**words, **{p: i < 2 for i, p in enumerate(pseudo)}}, bands, pseudo, rb,
                                 pseudo_reviewed=True)   # 2/5 = 40% fałszywych „tak” ≥ 30%
    assert guess["rejected"] and guess["passive"] == []
    draft = V.recognition_result({**words, **pseudo}, bands, pseudo, rb, pseudo_reviewed=False)
    assert draft["preliminary"]                           # pseudosłowa nie-human_reviewed ⇒ wstępny
    assert V.recognition_result({**words, **pseudo}, {w: None for w in words}, pseudo, rb,
                                pseudo_reviewed=True)["preliminary"]   # bez rang ⇒ przybliżenie
    corrected = V.recognition_result({**words, **{p: i < 1 for i, p in enumerate(pseudo)}}, bands, pseudo, rb,
                                     pseudo_reviewed=True)
    assert corrected["bands"][1] == pytest.approx(0.8) and corrected["passive"]   # h − f = 1 − 0.2
    ps, rev = C.load_pseudowords()
    assert len(ps) >= 30 and rev is False


def test_vocab_6_detect_use(pack, ngsl):  # T-VOC-6
    rb = pack.rubric

    def use(text, lemma="color", **kw):
        return V.detect_use(text, A.prefilter(text, pack.disfluency), C.vocab_forms(ngsl[lemma], pack.variants),
                            rb, **kw)
    assert use("I like this colour a lot.") and use("What a nice color!")            # BrE i AmE
    assert not use("I like blue.")
    assert not use("I like this colour.", tutor_prev="Do you like this colour or that one?")   # echo ≥ 3 słów
    assert use("I painted it in a colour I love.", tutor_prev="What colour is it?")
    assert not use("I like this colour.", low_prob_words={"colour"})                  # prob < 0,5
    # słowo w wypełniaczu/powtórzeniu nie liczy się: „like” jako wtrącenie
    assert not use("Well, like, I went home.", lemma="like")


def test_vocab_6_ingest_use_needs_two_sessions(repo, pack):  # samo wykrycie ≠ opanowanie
    pid = repo.create_profile("U")
    for k, (sid_n, text) in enumerate([(1, "I love this colour."), (2, "Colour is nice.")]):
        sid = repo.start_session(pid, "chat")
        tid = repo.add_turn(pid, sid, "user", text)
        res = evaluate(pack, text)
        out = ingest.apply_turn_evaluation(repo, pack, pid, sid, tid, res, input_mode="text", text=text,
                                           goals=GOALS, now=NOW + timedelta(minutes=k), vocab_targets=["color"])
        row = repo.get_vocab(pid, "en", "color")
        assert out["events"]["vocab"][0]["lemma"] == "color"
        assert row["knowledge"] == ("passive" if k == 0 else "active") and row["used_count"] == k + 1
        again = ingest.apply_turn_evaluation(repo, pack, pid, sid, tid, res, input_mode="text", text=text,
                                             goals=GOALS, now=NOW, vocab_targets=["color"])
        assert again["reason"] == "already_applied" and repo.get_vocab(pid, "en", "color")["used_count"] == k + 1


def test_vocab_7_planner_targets(pack):  # T-VOC-7
    due = [{"card_type": "vocab", "ref_id": f"w{i}", "due_at": "2026-11-21T00:00:00Z"} for i in range(4)]
    plan = P.plan(pinput(pack, due_cards=due, lesson_vocab=["a1", "a2", "a3"]))
    vt = plan["conversation"]["vocab_targets"]
    assert vt == ["w0", "w1", "w2", "w3", "a1"] and len(vt) <= pack.rubric.vocab["planner_targets"]
    base = P.plan(pinput(pack))
    assert base["conversation"]["vocab_targets"] == [] and base["practice"] == P.plan(pinput(pack))["practice"]
