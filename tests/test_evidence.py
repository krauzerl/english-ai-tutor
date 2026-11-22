"""F4.7: poziomy dowodu (podejrzenie / obserwacja / potwierdzenie) i kontrakt AGV dla F5."""
import pytest

from tests import test_f4_flow as F
from tutor.app import ingest
from tutor.pedagogy import content as C
from tutor.pedagogy import evidence as EV
from tutor.pedagogy.schemas import Obs


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def obs(p="h", src=None, s="I goed", f="I went"):
    return Obs(s=s, f=f, k="error", c="tense.past_simple", v=2, p=p, src=src)


def test_levels(pack):
    lv = lambda o, mode="text", text="I goed there.": EV.level(F.evaluate(pack, text, o=[o], mode=mode).observations[0], pack)  # noqa: E731
    assert lv(obs("h")) == EV.OBSERVATION
    assert lv(obs("l")) == EV.SUSPICION
    assert lv(obs("h", "languagetool-6.6")) == EV.SUSPICION
    assert lv(obs("h", "bielik|lt-conflict")) == EV.SUSPICION
    assert lv(obs("h", "bielik+lt")) == EV.OBSERVATION
    assert lv(Obs(s="colour", f="color", k="error", c="spelling", v=1, p="h"), text="nice colour") is None   # wariant
    assert lv(Obs(s="can", f="can't", k="error", c="agreement", v=2, p="h"), "voice", "He can go") == EV.SUSPICION


def test_conversation_never_confirms_and_gate_stays_closed(repo, pack):
    pid = repo.create_profile("EV")
    sid = repo.start_session(pid, "chat")
    tid = repo.add_turn(pid, sid, "user", "I goed there.")
    res = F.evaluate(pack, "I goed there.", o=[obs("h")])
    out = ingest.apply_turn_evaluation(repo, pack, pid, sid, tid, res, input_mode="text", text="I goed there.",
                                       goals=F.GOALS, now=F.NOW)
    assert out["events"]["levels"] == {"observation": 1} and out["events"]["gated"] == 1
    assert repo.attempt_history(pid, F.GOAL) == []                       # wiarygodna obserwacja ≠ zmiana mastery


def test_agv_contract(repo, pack):
    sid = next(s for s in pack.skills if C.select_items(pack, pool="practice", purpose="practice", skill_id=s))
    req = EV.confirm_request(pack, {"skill_id": sid, "reason": "error:tense.past_simple", "unverified": True})
    assert req and 1 <= len(req.item_ids) <= 2 and req.category == "tense.past_simple"
    assert all("practice" in pack.items[i].pools and "retention" not in pack.items[i].pools for i in req.item_ids)
    assert req.unverified_items                                         # 0 human_reviewed: etykieta dla ucznia
    assert EV.confirm_request(pack, {"skill_id": None}) is None
    assert EV.outcome([False, False]) == EV.CONFIRMED and EV.outcome([True]) == "not_confirmed"
    assert EV.outcome([True, False]) == EV.outcome([]) == "inconclusive"
    pid = repo.create_profile("AGV")
    it = req.item_ids[0]
    r = ingest.apply_confirmation(repo, pack, pid, None, req, it, False, now=F.NOW, dedupe_key=f"agv:{it}:1")
    assert r["applied"]
    h = repo.attempt_history(pid, sid)
    assert len(h) == 1 and h[0]["source"] == "remediation"
    again = ingest.apply_confirmation(repo, pack, pid, None, req, it, False, now=F.NOW, dedupe_key=f"agv:{it}:1")
    assert again["applied"] is False                                    # idempotentne
    with pytest.raises(ValueError):
        ingest.apply_confirmation(repo, pack, pid, None, req, "nope", True, now=F.NOW, dedupe_key="x")
