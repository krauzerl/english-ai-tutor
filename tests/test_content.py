"""F3: treść (T-CONTENT-1,3,4,5, T-ARCH-2) + CLI review + generator na FakeProvider."""
import ast
import json
import shutil
from pathlib import Path

import pytest
import yaml

from tests.llm_fakes import FakeProvider
from tools import gen_items
from tutor import cli
from tutor.llm.structured import structured
from tutor.pedagogy import content as C

REAL = C.content_root()


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


@pytest.fixture
def tmp_root(tmp_path):
    shutil.copytree(REAL / "en", tmp_path / "en")
    return tmp_path


def test_content_validates_clean():  # DoD F3
    rep = C.validate("en")
    assert rep.ok, rep.errors
    assert rep.n_skills >= 80 and rep.n_items == 60 + 84 + 60 + 33   # F3 + F4.6 (84) + F7 (60) + przyimki UX (33)


def test_content_1_items_schema_and_pilot_shape(pack):  # T-CONTENT-1
    cells = {}
    for i in pack.items.values():
        if i.id.startswith(("en.f46.", "en.f7.", "en.ux.")):   # pilotaż F4.6, diagnoza F7, przyimki UX: własne testy
            continue
        assert i.skill_ids and all(s in pack.skills for s in i.skill_ids)
        assert i.review.status in C.STATUSES and i.answers
        cells[(i.area, i.cefr)] = cells.get((i.area, i.cefr), 0) + 1
    assert {k[0] for k in cells} == set(C.CLOSED_AREAS)
    assert {k[1] for k in cells} == set(C.CEFR_LEVELS[:5])
    assert set(cells.values()) == {3} and len(cells) == 20
    assert len({i.type for i in pack.items.values()}) >= 5 and len({i.domain for i in pack.items.values()}) >= 4
    for i in pack.items.values():
        if i.type in C.MC_TYPES:
            assert len(i.answers) == 1 and i.answers[0] in i.options


def test_content_1_bad_items_rejected(tmp_root):
    f = tmp_root / "en/items/grammar/A1.yaml"
    d = yaml.safe_load(f.read_text())
    d[1]["answers"] = ["goes"]                  # klucz spoza opcji
    d[0]["prompt"] = "My sister ___ a ___."     # dwie luki
    d[2]["skill_ids"] = ["en.gram.nope"]
    f.write_text(yaml.safe_dump(d))
    rep = C.validate("en", tmp_root)
    msg = "\n".join(rep.errors)
    assert "A1.yaml:" in msg and "MC" in msg and "luka" in msg and "nieznane skill_id" in msg


def test_content_1_variants_accepted(pack):  # T-PED-8 / RQ-3.10
    item = C.Item.model_validate({**yaml.safe_load(
        (REAL / "en/items/grammar/A2.yaml").read_text())[2]})
    assert C.answer_ok(item, "I'm going to call my manager tomorrow.", pack.variants)
    assert C.answer_ok(item, "i am going to call my manager tomorrow", pack.variants)
    assert not C.answer_ok(item, "I going to call my manager tomorrow", pack.variants)
    exp = C.expand_answers(["I have got a flat"], pack.variants)  # have got/have, flat/apartment; kończy się
    assert {"i have an apartment", "i have got an apartment", "i have a flat"} <= exp
    assert not {"i have a apartment", "i have got a apartment"} & exp


def test_variant_swap_fixes_article(pack):
    exp = C.expand_answers(["an apartment"], pack.variants)
    assert exp == {"an apartment", "a flat"}
    exp = C.expand_answers(["I took a lift"], pack.variants)
    assert "i took an elevator" in exp and "i took a elevator" not in exp


def test_content_3_human_reviewed_needs_reviewer(tmp_root):  # T-CONTENT-3
    f = tmp_root / "en/items/grammar/A1.yaml"
    d = yaml.safe_load(f.read_text())
    d[0]["review"] = {"status": "human_reviewed", "reviewer": "ghost", "reviewed_at": "2026-11-22"}
    f.write_text(yaml.safe_dump(d))
    assert any("reviewers.yaml" in e for e in C.validate("en", tmp_root).errors)
    d[0]["review"] = {"status": "human_reviewed", "reviewer": None, "reviewed_at": None}
    f.write_text(yaml.safe_dump(d))
    assert any("reviewer" in e for e in C.validate("en", tmp_root).errors)


def test_content_3_no_human_reviewed_in_repo(pack):  # decyzja 6: nic nie jest zrecenzowane przez człowieka
    assert pack.reviewers.reviewers == []
    assert all(i.review.status != "human_reviewed" for i in pack.items.values())
    assert all(s.review.status != "human_reviewed" for s in pack.scenarios.values())


def test_content_3_generator_cannot_set_human_fields(tmp_root):
    pack = C.load("en", tmp_root)
    with pytest.raises(ValueError):
        C.set_ai_check(pack, "en.pilot.gram.a1.01", "human_reviewed")
    item = {"id": "en.gen.gram.a1.0001", "lang": "en", "skill_ids": ["en.gram.to_be_present"], "area": "grammar",
            "type": "gap", "cefr": "A1", "difficulty": 0.0, "pools": ["practice"], "domain": "general",
            "prompt": "They ___ happy.", "answers": ["are"],
            "provenance": {"source": "human", "prompt_version": "gen_item.v1"},
            "review": {"status": "human_reviewed", "reviewer": "x", "reviewed_at": "2026"}}
    C.append_draft(pack, item)
    again = C.load("en", tmp_root).items["en.gen.gram.a1.0001"]
    assert again.review.status == "draft" and again.review.reviewer is None and again.review.reviewed_at is None
    assert again.provenance.source == "ai_generated"


def test_content_4_graph_acyclic_and_categories(pack):  # T-CONTENT-4
    assert C.find_cycle(pack.skills) is None
    cats = pack.errors.ids()
    for s in pack.skills.values():
        assert s.id.startswith("en.") and set(s.error_categories) <= cats
    assert len({*pack.skills}) == len(pack.skills)
    assert {d for d in (s.domain for s in pack.skills.values())} == set(C.DOMAINS)


def test_content_4_cycle_detected(tmp_root):
    f = tmp_root / "en/skills/grammar.yaml"
    d = yaml.safe_load(f.read_text())
    d[0]["prereqs"] = ["en.gram.present_simple"]  # to_be_present <- present_simple <- to_be_present
    f.write_text(yaml.safe_dump(d))
    assert any("cykl" in e for e in C.validate("en", tmp_root).errors)


def test_pools_retention_and_practice_disjoint(tmp_root):
    f = tmp_root / "en/items/grammar/A1.yaml"
    d = yaml.safe_load(f.read_text())
    d[0]["pools"] = ["practice", "retention"]
    f.write_text(yaml.safe_dump(d))
    assert any("rozłączne" in e for e in C.validate("en", tmp_root).errors)


def test_content_5_status_gates(pack):  # T-CONTENT-5 (+ decyzja 1: placement z ai_checked)
    base = next(iter(pack.items.values()))

    def with_status(s):
        return base.model_copy(update={"review": base.review.model_copy(update={"status": s})})
    for s in ("draft", "rejected", "suspect"):
        for purpose in ("diagnosis", "retention", "cefr_check", "practice", "placement"):
            assert not C.usable(with_status(s), purpose, True)
    ai = with_status("ai_checked")
    assert C.usable(ai, "placement", True) and C.usable(ai, "placement", False)
    assert C.usable(ai, "practice", True) and not C.usable(ai, "practice", False)
    for purpose in ("diagnosis", "retention", "cefr_check"):
        assert not C.usable(ai, purpose, True)
    hr = with_status("human_reviewed")
    assert all(C.usable(hr, p, False) for p in ("diagnosis", "retention", "cefr_check", "practice", "placement"))


def test_diagnosis_gate_closed_without_human_review(pack):
    assert not C.diagnosis_gate(pack, "grammar", 15)["open"]
    assert C.select_items(pack, pool="diagnosis", purpose="diagnosis", area="grammar") == []


def test_retention_gaps_reported(pack):
    assert "en.gram.past_simple_regular" in C.retention_gaps(pack, 3, 1)


def test_arch_2_no_target_language_content_outside_content_dir():  # T-ARCH-2
    root = Path(__file__).resolve().parent.parent / "tutor"
    bad = [p for p in root.rglob("*.yaml") if (root / "content") not in p.parents]
    assert bad == []
    assert not (REAL / "en/items").parent.parent.joinpath("pedagogy").exists()
    # rdzeń nie zna słów ćwiczeń: żaden literał zadania w kodzie pedagogy
    words = {"deployed", "passport", "cogent", "noncommittal"}
    for p in (root / "pedagogy").glob("*.py"):
        lits = {n.value for n in ast.walk(ast.parse(p.read_text())) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert not (words & lits), p


# --- CLI ---
def test_cli_validate_reports_counts(capsys):
    assert cli.content_main(["validate", "en"]) == 0
    out = capsys.readouterr().out
    assert "grammar    A1:" in out and "listening  C1:" in out and out.strip().endswith("OK")


def test_cli_review_flow(tmp_root, monkeypatch):
    (tmp_root / "en/reviewers.yaml").write_text("reviewers:\n  - {id: tester, name: Tester}\n")
    monkeypatch.setattr(C, "content_root", lambda: tmp_root)
    answers = iter(["a", "o", "powód", "e", "notka", "a", "p", "q"])
    lines = []
    rc = cli.content_main(["review", "en", "--reviewer", "tester"], inp=lambda _="": next(answers), out=lines.append)
    assert rc == 0
    pack = C.load("en", tmp_root)
    first = pack.items["en.pilot.gram.a1.01"]
    assert first.review.status == "human_reviewed" and first.review.reviewer == "tester" and first.review.reviewed_at
    assert pack.items["en.pilot.gram.a1.02"].review.status == "rejected"
    assert pack.items["en.pilot.gram.a1.03"].review.notes == "notka"
    assert pack.items["en.pilot.gram.a1.03"].review.status == "human_reviewed"  # po „a” wg kolejności wejścia


def test_cli_review_refuses_unknown_reviewer(tmp_root, monkeypatch):
    monkeypatch.setattr(C, "content_root", lambda: tmp_root)
    lines = []
    assert cli.content_main(["review", "en", "--reviewer", "ghost"], inp=lambda _="": "q", out=lines.append) == 1
    assert "reviewers.yaml" in lines[0]
    assert all(i.review.status != "human_reviewed" for i in C.load("en", tmp_root).items.values())


# --- generator (FakeProvider, zero prawdziwych modeli) ---
GOOD = {"prompt": "She ___ to work by bus.", "options": None, "answers": ["goes"], "explanation_pl": "3. os.",
        "difficulty": 0.0}


def test_generator_saves_only_valid_draft(tmp_root):
    pack = C.load("en", tmp_root)
    p = FakeProvider(replies=[json.dumps(GOOD)])
    iid, errs = gen_items.generate(pack, p, structured, skill_id="en.gram.present_simple", item_type="gap",
                                   cefr="A1", domain="general", model_name="fake", today="2026-11-22")
    assert errs == [] and iid
    it = C.load("en", tmp_root).items[iid]
    assert it.review.status == "draft" and it.provenance.source == "ai_generated"
    assert it.provenance.prompt_version == "gen_item.v1"


def test_generator_rejects_invalid_and_duplicate(tmp_root):
    pack = C.load("en", tmp_root)
    bad = {**GOOD, "prompt": "She ___ to ___ by bus."}
    iid, errs = gen_items.generate(pack, FakeProvider(replies=[json.dumps(bad)]), structured,
                                   skill_id="en.gram.present_simple", item_type="gap", cefr="A1",
                                   domain="general", model_name="fake", today="x")
    assert iid is None and any("luka" in e for e in errs)
    dup = {**GOOD, "prompt": "My sister ___ a nurse.", "answers": ["is"]}
    iid, errs = gen_items.generate(pack, FakeProvider(replies=[json.dumps(dup)]), structured,
                                   skill_id="en.gram.to_be_present", item_type="gap", cefr="A1",
                                   domain="general", model_name="fake", today="x")
    assert iid is None and "duplikat" in errs[0]


def test_solve_check_agree_disagree(tmp_root):
    pack = C.load("en", tmp_root)
    it = pack.items["en.pilot.gram.a1.02"]  # klucz: drinks
    ok = FakeProvider(replies=[json.dumps({"answer": "drinks"})])
    assert gen_items.solve_check(pack, ok, structured, it)[0] == "ai_checked"
    no = FakeProvider(replies=[json.dumps({"answer": "drink"})])
    assert gen_items.solve_check(pack, no, structured, it)[0] == "draft"
    assert gen_items.solve_check(pack, FakeProvider(replies=[json.dumps({"answer": "drink"})]), structured, it,
                                 reject_on_mismatch=True)[0] == "rejected"
    multi = FakeProvider(replies=[json.dumps({"answer": "drinks", "multiple_correct": True})])
    assert gen_items.solve_check(pack, multi, structured, it)[0] == "draft"
    C.set_ai_check(pack, it.id, "ai_checked", "n")
    after = C.load("en", tmp_root).items[it.id]
    assert after.review.status == "ai_checked" and after.review.reviewer is None


def test_gen_items_refuses_mass_generation(capsys):
    assert gen_items.main(["en", "--skill", "x", "--n", "50"]) == 1


def test_f7_diagnostic_items_are_ai_drafts_with_honest_status():
    pack = C.load("en")
    f7 = [i for i in pack.items.values() if i.id.startswith("en.f7.")]
    assert len(f7) == 60 and all(i.pools == ["diagnosis"] for i in f7)
    assert all(i.provenance.source == "ai_generated" and i.review.status in ("draft", "ai_checked") for i in f7)
    assert not any(i.review.status == "human_reviewed" for i in f7)           # AI ≠ recenzja człowieka
    for area in ("grammar", "vocabulary", "reading", "listening"):
        for lv in C.CEFR_LEVELS[:5]:
            assert any(i.area == area and i.cefr == lv for i in f7), (area, lv)
    assert all(i.audio_text for i in f7 if i.type == "listening_mc")
