"""F4.6/C6: brama jakości korekt (T-GATE-1). Niezweryfikowane błędy = sugestie; brak błędu ≠ dowód poprawności."""
import dataclasses

import pytest

from tests import test_f4_flow as F
from tutor.app import ingest
from tutor.pedagogy import content as C
from tutor.pedagogy import planner as P
from tutor.pedagogy.schemas import Obs, Use

ERR = Obs(s="I goed", f="I went", k="error", c="tense.past_simple", v=2, p="h")


@pytest.fixture(scope="module")
def closed():
    return C.load("en")           # prawdziwy pakiet: trusted_categories: []


@pytest.fixture(scope="module")
def trusted(closed):
    return F.open_gate(closed)


def run(repo, pack, text="I goed there.", **kw):
    pid = repo.create_profile(f"G{len(repo.list_profiles())}")
    sid = repo.start_session(pid, "chat")
    tid = repo.add_turn(pid, sid, "user", text)
    res = F.evaluate(pack, text, o=[ERR], t=kw.get("t", []), cm="ok", cq="I goed")
    out = ingest.apply_turn_evaluation(repo, pack, pid, sid, tid, res, input_mode="text", text=text, goals=F.GOALS,
                                       now=F.NOW)
    return pid, out


def test_gate_defaults_closed(closed):
    g = closed.rubric.correction["quality_gate"]
    assert g["trusted_categories"] == [] and g["lt_trusted_rules"] == [] and g["bielik_benchmark_passed"] is False
    assert g["recall_min"] == 0.5 and g["min_reports"] >= 1 and g["judge_agreement_min"] == 0.90
    assert C.diagnosis_gate(closed, "grammar", 15)["open"] is False


def test_gate_1_untrusted_error_is_suggestion_only(repo, closed):  # T-GATE-1
    pid, out = run(repo, closed)
    assert out["applied"] and out["events"]["gated"] == 1
    assert repo.attempt_history(pid, F.GOAL) == [] and repo.get_skill_state(pid, F.GOAL) is None   # BKT/mastery bez zmian
    obs = repo.list_observations(pid)
    assert len(obs) == 1 and obs[0]["category"] == "tense.past_simple" and obs[0]["status"] == "valid"
    errs = repo.list_errors(pid)                                      # error_log działa (rejestr, bez wpływu na mastery)
    assert len(errs) == 1 and errs[0]["category"] == "tense.past_simple"


def test_gate_1_trusted_category_updates_bkt_like_f4(repo, trusted):
    pid, out = run(repo, trusted)
    assert out["events"]["gated"] == 0
    assert len(repo.attempt_history(pid, F.GOAL)) == 1 and repo.get_skill_state(pid, F.GOAL) is not None


def test_gate_1_parent_category_matches_subcategory(repo, closed):
    cor = {**closed.rubric.correction, "quality_gate": {**closed.rubric.correction["quality_gate"],
                                                         "trusted_categories": ["tense"]}}
    pk = dataclasses.replace(closed, rubric=closed.rubric.model_copy(update={"correction": cor}))
    pid, _ = run(repo, pk)
    assert len(repo.attempt_history(pid, F.GOAL)) == 1
    assert ingest.trusted("tense.past_simple", pk) and not ingest.trusted("article.missing", pk)
    assert not ingest.trusted(None, pk)


def test_gate_1_model_positive_needs_deterministic_confirmation(repo, closed):
    use = Use(id=F.GOAL, r="ok", s="I walked")
    skill = closed.skills[F.GOAL]
    assert not skill.target_patterns                                  # brak wzorca ⇒ twierdzenie modelu niepotwierdzone
    pid, out = run(repo, closed, "I walked there. I goed there.", t=[use])
    assert [a["correct"] for a in repo.attempt_history(pid, F.GOAL)] == [] and out["events"]["gated"] == 2
    pk = dataclasses.replace(closed, skills={**closed.skills, F.GOAL: skill.model_copy(
        update={"target_patterns": [r"\bwalked\b"]})})
    pid, _ = run(repo, pk, "I walked there. I goed there.", t=[use])
    assert [a["correct"] for a in repo.attempt_history(pid, F.GOAL)] == [True]     # tylko potwierdzone użycie


def test_gate_1_unverified_errors_do_not_force_remediation(closed, trusted):
    errors = [{"category": "tense.past_simple", "skill_id": None, "status": "recurring", "count": 3, "severity_max": 2}]
    plan = P.plan(F.pinput(closed, 30, errors=errors))
    assert not any(t["kind"] == "remediation" for t in plan["practice"])
    assert plan["suggested"] and plan["suggested"][0]["unverified"] is True
    forced = P.plan(F.pinput(trusted, 30, errors=errors))
    assert any(t["kind"] == "remediation" for t in forced["practice"]) and forced["suggested"] == []


def test_no_error_detected_is_not_evidence_of_correctness(repo, closed):
    """Wypowiedź bez zgłoszeń nie tworzy próby ani nie podnosi mastery."""
    pid = repo.create_profile("N")
    sid = repo.start_session(pid, "chat")
    tid = repo.add_turn(pid, sid, "user", "I went there.")
    out = ingest.apply_turn_evaluation(repo, closed, pid, sid, tid, F.evaluate(closed, "I went there."),
                                       input_mode="text", text="I went there.", goals=F.GOALS, now=F.NOW)
    assert out["applied"] and repo.attempt_history(pid, F.GOAL) == [] and repo.get_skill_state(pid, F.GOAL) is None
