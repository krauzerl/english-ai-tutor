"""F4.6/C3: pilotaż 12 umiejętności (T-CONTENT-6..8) i rozróżnienie puli retention."""
import re
import shutil

import pytest
import yaml

from tutor import cli
from tutor.pedagogy import content as C

PILOT = ["en.gram.to_be_present", "en.gram.present_simple", "en.gram.articles_basic", "en.vocab.daily_routine",
         "en.gram.past_simple_regular", "en.gram.present_perfect", "en.conv.ask_clarification",
         "en.conv.agree_disagree", "en.vocab.collocations_make_do", "en.gram.passive_basic",
         "en.tech.incident_report", "en.gram.participle_clauses"]
REAL = C.content_root()


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def test_content_6_explanations_structure(pack, tmp_path):  # T-CONTENT-6
    refs = [pack.skills[s].explanation_ref for s in PILOT]
    assert all(refs) and len(set(refs)) == 12
    for r in refs:
        assert pack.explanations[r].structure == "v2"
        assert not pack.explanations[r].review.status == "human_reviewed"
    cats = pack.errors.ids()
    bad = tmp_path / "x.md"
    bad.write_text("---\nstructure: v2\n---\n# T\n\n## Zasada\nx\n\n## Poprawnie\n- one\n\n"
                   "## Błędnie → poprawnie\n- a → a [article]\n- b → c [nope]\n\n## Typowe błędy Polaków\n- bez kategorii\n")
    rep = C.Report()
    C.check_explanation_md(bad.read_text(), cats, "x.md", rep, False)
    msg = "\n".join(rep.errors)
    for frag in ("brak sekcji „Formy”", "≥ 4 zdań", "identyczna", "nieznana kategoria", "Typowe błędy Polaków"):
        assert frag in msg
    rep2 = C.Report()  # poprawny wzorzec przechodzi
    C.check_explanation_md((REAL / "en" / pack.skills["en.gram.present_perfect"].explanation_ref).read_text(),
                           cats, "pp.md", rep2, True)
    assert rep2.ok, rep2.errors


def test_content_6_new_l1_calque_categories(pack):
    assert {"l1_calque.make_photo", "l1_calque.have_years", "l1_calque.explain_me"} <= pack.errors.ids()


def test_content_7_pilot_items_shape(pack):  # T-CONTENT-7
    for sid in PILOT:
        its = [i for i in pack.items.values() if sid in i.skill_ids and i.id.startswith("en.f46.")]
        prac = [i for i in its if "practice" in i.pools]
        ret = [i for i in its if "retention" in i.pools]
        assert len(prac) == 4 and sum(i.productive for i in prac) >= 2, sid
        assert len(ret) == 3 and sum(i.productive for i in ret) >= 1, sid
        assert not any(set(i.pools) & {"diagnosis"} for i in its)           # pilotaż poza diagnozą
        assert not any("practice" in i.pools and "retention" in i.pools for i in its)
        assert all(i.review.status != "human_reviewed" for i in its)
        assert {i.prompt for i in prac}.isdisjoint({i.prompt for i in ret})


def test_gates_stay_closed(pack):
    assert not C.diagnosis_gate(pack, "grammar", 15)["open"]
    assert not any(i.review.status == "human_reviewed" for i in pack.items.values())


def test_retention_existing_vs_admitted(pack):  # istniejąca pula ≠ pula dopuszczona do sprawdzania trwałości
    rb = pack.rubric.retention
    st = C.retention_pool_status(pack, rb["n_items"], rb["productive_required"])
    for sid in PILOT:
        assert st[sid]["existing"] == 3 and st[sid]["existing_productive"] >= 1
        assert st[sid]["admitted"] == 0 and not st[sid]["ready"]
    gaps = C.retention_gaps(pack, rb["n_items"], rb["productive_required"])
    assert set(PILOT) <= set(gaps)         # bez recenzji człowieka żadna umiejętność nie jest „gotowa”


def test_content_8_phrases(pack):  # T-CONTENT-8
    assert len(pack.phrases) >= 30
    per_skill = {}
    for p in pack.phrases.values():
        assert all(s in pack.skills for s in p.skill_ids)
        if p.pattern:
            re.compile(p.pattern)
        assert p.review.status != "human_reviewed"
        for s in p.skill_ids:
            per_skill[s] = per_skill.get(s, 0) + 1
    for sid in ("en.vocab.daily_routine", "en.conv.ask_clarification", "en.conv.agree_disagree",
                "en.vocab.collocations_make_do", "en.tech.incident_report"):
        assert per_skill[sid] >= 6
    ph = next(iter(pack.phrases.values()))
    assert not C.usable_phrase(ph.model_copy(update={"review": C.Review(status="draft")}), True)
    assert C.usable_phrase(ph.model_copy(update={"review": C.Review(status="ai_checked")}), True)
    assert not C.usable_phrase(ph.model_copy(update={"review": C.Review(status="ai_checked")}), False)


def test_phrase_validation_errors(tmp_path):
    shutil.copytree(REAL / "en", tmp_path / "en")
    f = tmp_path / "en/phrases.yaml"
    d = yaml.safe_load(f.read_text())
    d[0]["skill_ids"] = ["en.nope"]
    d[1]["pattern"] = "("
    f.write_text(yaml.safe_dump(d, allow_unicode=True))
    with pytest.raises(C.ContentError) as e:
        C.load("en", tmp_path)
    msg = "\n".join(e.value.report.errors)
    assert "nieznane skill_id" in msg and "pattern" in msg


def test_review_cli_covers_docs(tmp_path):
    shutil.copytree(REAL / "en", tmp_path / "en")
    (tmp_path / "en/reviewers.yaml").write_text("reviewers:\n  - {id: tester, name: Tester}\n")
    pack = C.load("en", tmp_path)
    ph = next(iter(pack.phrases))
    expl = "grammar/to_be_present.md"
    C.set_review_doc(pack, "phrase", ph, "human_reviewed", reviewer='tester', now="2026-01-01")
    C.set_review_doc(pack, "explanation", expl, "human_reviewed", reviewer='tester', now="2026-01-01")
    p2 = C.load("en", tmp_path)
    assert p2.phrases[ph].review.status == "human_reviewed" and C.usable_phrase(p2.phrases[ph], False)
    assert p2.explanations[expl].review.reviewer == "tester"
    with pytest.raises(ValueError):
        C.set_review_doc(pack, "phrase", ph, "human_reviewed", reviewer="ktoś-spoza", now="x")
    assert "Poprawnie" in (tmp_path / "en" / expl).read_text()      # treść wyjaśnienia nietknięta
    # CLI: kolejka docs nie pomija elementów i działa na kopii
    answers = iter(["q"])
    out = []
    import tutor.pedagogy.content as cm
    orig = cm.content_root
    cm.content_root = lambda: tmp_path
    try:
        rc = cli.content_main(["review", "en", "--reviewer", 'tester', "--kind", "docs"],
                              inp=lambda _="": next(answers), out=out.append)
    finally:
        cm.content_root = orig
    assert rc == 0 and any("Do przeglądu" in x for x in out)


def test_review_bench_cases_only_by_human_path(tmp_path):
    import yaml

    from bench import grammar as BG
    shutil.copytree(REAL / "en", tmp_path / "en")
    (tmp_path / "en/reviewers.yaml").write_text("reviewers:\n  - {id: tester, name: Tester}\n")
    pack = C.load("en", tmp_path)
    gold = tmp_path / "grammar_gold.yaml"
    gold.write_text((BG.CASES / "grammar_gold.yaml").read_text())
    f3 = tmp_path / "f3_mismatch.yaml"
    f3.write_text((BG.CASES / "f3_mismatch.yaml").read_text())
    C.set_review_bench(pack, gold, "g.e1.001", "human_reviewed", reviewer="tester", now="2026-01-01")
    C.set_review_bench(pack, f3, "en.pilot.gram.a1.03", "human_reviewed", reviewer="tester", now="2026-01-01")
    assert [c.id for c in BG.load_cases(gold, only_reviewed=True)] == ["g.e1.001"]
    assert next(d for d in yaml.safe_load(f3.read_text()) if d["item_id"] == "en.pilot.gram.a1.03")["review"][
        "reviewer"] == "tester"
    with pytest.raises(ValueError):
        C.set_review_bench(pack, gold, "g.e1.002", "human_reviewed", reviewer="nobody", now="x")
    assert all(c.status == "draft" for c in BG.load_cases())     # oryginały w repo nietknięte
