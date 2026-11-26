"""B-lite: przepływ dowodów błąd → ćwiczenie potwierdzające → uptake → retencja; bramy mastery nadal zamknięte."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from tests import test_f4_flow as F
from tests.test_eval_runner import Prov, structured
from tutor.app import feedback as FB
from tutor.app import goal as G
from tutor.app import growth, ingest
from tutor.app import lesson as L
from tutor.app.eval_queue import Pending
from tutor.app.eval_runner import make_queue, tutor_prev
from tutor.llm.base import CancelToken
from tutor.pedagogy import content as C
from tutor.pedagogy import correction as K
from tutor.pedagogy import diagnosis as D
from tutor.pedagogy.schemas import Obs

NOW = datetime(2026, 11, 26, 10, tzinfo=UTC)
SKILL = L.DEFAULT_SKILL                       # en.gram.to_be_present: omission.copula, agreement.subject_verb
CAT = "omission.copula"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def recurring(repo, pid, last_seen="2026-11-20T10:00:00.000Z"):
    repo.put_error_log(pid, CAT, None, count=4, status="recurring", severity_max=2, reopened=0, example="I happy",
                       correction="I am happy", example_observation_id=None, first_seen="2026-11-01T10:00:00.000Z",
                       last_seen=last_seen)


def lesson_from_error(repo, pack, pid, correct: bool):
    ch = G.choose(repo, pack, pid, NOW)
    assert ch.source == "error" and ch.category == CAT and ch.skill_id == SKILL
    sid = repo.start_session(pid, "lesson")
    sk, items = L.begin(repo, pack, pid, sid, ch.skill_id, {"source": ch.source, "reason": ch.reason,
                                                            "provisional": True, "category": ch.category})
    ans = {i.id: L.Answer(i.answers[0] if correct else "zzz wrong answer here") for i in items}
    L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i: ans[it.id], lambda s: None, now=NOW)
    return sid, items


# --- potwierdzenie ćwiczeniem (AGV) ---
def test_error_lesson_records_confirmation_without_mastery(repo, pack):
    pid = repo.create_profile("agv")
    recurring(repo, pid)
    sid, items = lesson_from_error(repo, pack, pid, correct=False)
    agv = repo.get_session_plan(pid, sid)["agv"]
    assert agv["outcome"] == "confirmed" and agv["category"] == CAT and agv["after_explanation"]
    atts = repo.attempt_history(pid, SKILL)
    assert {a["source"] for a in atts} == {"remediation"}
    assert all(json.loads(a["feedback_json"])["no_mastery"] for a in atts)   # potwierdzenie ≠ opanowanie
    assert repo.get_skill_state(pid, SKILL)["status"] != "mastered"
    again = G.choose(repo, pack, pid, NOW)                  # potwierdzony problem: dalej proponowany, z uzasadnieniem
    assert again.source == "error" and "potwierdzony" in again.reason
    from tutor.app import weakspots as W
    e = next(x for x in W.build(repo, pack, pid, NOW)["errors"] if x["category"] == CAT)
    assert e["agv"] == "confirmed" and e["reliability"] == "potwierdzony ćwiczeniem kontrolnym"


def test_not_confirmed_stops_forcing_until_new_observation(repo, pack):
    pid = repo.create_profile("agv2")
    recurring(repo, pid)
    sid, _ = lesson_from_error(repo, pack, pid, correct=True)
    assert repo.get_session_plan(pid, sid)["agv"]["outcome"] == "not_confirmed"
    # reguła AGV osobno (bez reguły „ukończona bezbłędnie lekcja nie wraca”): plan z wynikiem, zadania niezrobione
    pid2 = repo.create_profile("agv3")
    recurring(repo, pid2)
    s2 = repo.start_session(pid2, "lesson")
    repo.set_session_plan(pid2, s2, {"lesson": SKILL, "items": ["a"], "done": [], "ok": [],
                                     "agv": {"category": CAT, "outcome": "not_confirmed", "skill_id": SKILL,
                                             "at": "2026-11-25T10:00:00Z"}})
    assert G.choose(repo, pack, pid2, NOW).source != "error"    # jedna niepotwierdzona sugestia nie wymusza lekcji
    recurring(repo, pid2, last_seen="2026-11-25T12:00:00.000Z")  # nowa obserwacja po ćwiczeniu ⇒ znów sugestia
    assert G.choose(repo, pack, pid2, NOW).source == "error"


def test_plain_lesson_stays_practice(repo, pack):
    pid = repo.create_profile("plain")
    sid = repo.start_session(pid, "lesson")
    sk, items = L.begin(repo, pack, pid, sid, SKILL, {"source": "manual", "reason": "x", "provisional": False})
    L.run_exercises(repo, pack, pid, sid, sk, items, lambda it, i: L.Answer(it.answers[0]), lambda s: None, now=NOW)
    assert "agv" not in repo.get_session_plan(pid, sid)
    assert {a["source"] for a in repo.attempt_history(pid, SKILL)} == {"practice"}


def test_apply_confirmation_never_allows_mastery(repo, pack):
    from tutor.pedagogy import evidence as EV
    pid = repo.create_profile("cf")
    req = EV.confirm_request(pack, {"skill_id": SKILL, "reason": f"error:{CAT}"})
    ingest.apply_confirmation(repo, pack, pid, None, req, req.item_ids[0], True, now=NOW, dedupe_key="k")
    fb = json.loads(repo.attempt_history(pid, SKILL)[0]["feedback_json"])
    assert fb["no_mastery"] and fb["agv"]["category"] == CAT


# --- uptake ---
def test_uptake_check_unit(pack):
    t = {"category": "tense.past_simple", "fix": "I went there", "span": "I go there", "from_turn": 3}
    assert K.changed_words("I go there", "I went there") == {"went"}
    assert K.uptake_check(t, 4, "I went home", set(), pack.rubric) is None             # przed oknem (echo)
    assert K.uptake_check(t, 5, "Then I went home", set(), pack.rubric) == "used_ok"
    assert K.uptake_check(t, 5, "I go home", {"tense.past_simple"}, pack.rubric) == "repeated"
    assert K.uptake_check(t, 6, "I like it", set(), pack.rubric) is None               # brak okazji ≠ błąd
    assert K.uptake_check(t, 9, "I went", set(), pack.rubric) is None                  # po oknie


def test_recast_creates_reuse_target_and_later_turn_records_uptake(repo, pack):
    pid = repo.create_profile("up")
    sid = repo.start_session(pid, "chat")
    tid = F.turn(repo, pid, sid, "Yesterday I go to the park.")
    res = F.evaluate(pack, "Yesterday I go to the park.",
                     o=[Obs(s="I go", f="I went", k="error", c="tense.past_simple", v=2, p="h")])
    F.apply(repo, pack, pid, sid, tid, res, "Yesterday I go to the park.")
    assert FB.recast_directive(repo, pack, pid, sid, "periodic", set()) is not None
    plan = repo.get_session_plan(pid, sid)
    assert plan["reuse_targets"][0]["fix"] == "I went" and plan["recast"]["done"]
    for text in ("It was sunny.", "And then I went home."):           # tury 2 i 3 (okno [2, 5] od tury 1)
        t2 = F.turn(repo, pid, sid, text)
        out = F.apply(repo, pack, pid, sid, t2, F.evaluate(pack, text), text)
    up = repo.get_session_plan(pid, sid)["uptake"]
    assert [u["result"] for u in up] == ["used_ok"] and out["events"]["uptake"][0]["fix"] == "I went"
    assert repo.attempt_history(pid, "en.gram.past_simple_regular") == []   # uptake nie zasila BKT


def test_plan_key_update_does_not_clobber_other_keys(repo):
    pid = repo.create_profile("k")
    sid = repo.start_session(pid, "chat")
    repo.set_session_plan(pid, sid, {"recast": {"done": [1]}, "level": "B1"})
    repo.set_session_plan_keys(pid, sid, uptake=[{"x": 1}])
    assert repo.get_session_plan(pid, sid) == {"recast": {"done": [1]}, "level": "B1", "uptake": [{"x": 1}]}


# --- kontekst oceny ---
def test_tutor_prev_and_context_flag(tmp_path, pack):
    from tutor.store.db import open_db
    from tutor.store.repo import Repo
    repo = Repo(open_db(tmp_path / "c.db"))
    pid = repo.create_profile("ctx")
    sid = repo.start_session(pid, "chat")
    repo.add_turn(pid, sid, "assistant", "What did you do yesterday?")
    tid = repo.add_turn(pid, sid, "user", "I goed home")
    assert tutor_prev(repo, pid, sid, tid) == "What did you do yesterday?"
    for ctx, expect in ((False, "(none)"), (True, "What did you do yesterday?")):
        prov = Prov()
        q = make_queue(repo, pack, prov, structured, profile_id=pid, session_id=sid, goals={}, context=ctx)
        q.submit(Pending(tid, "I goed home", "text"))
        q.drain(CancelToken())
        assert f"TUTOR PREVIOUS MESSAGE\n{expect}\n" in prov.calls[0][-1].content
        repo.conn.execute("DELETE FROM turn_meta")
        repo.conn.execute("DELETE FROM observation")


# --- retencja i pule ---
def _att(skill, item, days, correct=True):
    return {"skill_id": skill, "item_id": item, "hint_level": 0, "correct": correct, "feedback_json": None,
            "created_at": (NOW + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z")}


def test_retention_counts_only_new_items(pack):
    same = growth._retention([_att("s", "i1", 0), _att("s", "i1", 8)], pack)
    assert same["after_7_days"]["n"] == 0                  # to samo zadanie po tygodniu = pamięć zadania
    new = growth._retention([_att("s", "i1", 0), _att("s", "i2", 8)], pack)
    assert new["after_7_days"] == {"correct": 1, "n": 1}
    conv = growth._retention([_att("s", "i1", 0), _att("s", None, 8)], pack)
    assert conv["after_3_days"]["n"] == 0                  # próba bez zadania nie jest dowodem trwałości


def test_fresh_pool_and_lesson_prefers_practice_only(repo, pack):
    pool = [type("I", (), {"id": f"i{k}"})() for k in range(6)]
    assert [i.id for i in D.fresh_pool(pool, {"i0", "i1"}, 4)] == ["i2", "i3", "i4", "i5"]
    assert len(D.fresh_pool(pool, {"i0", "i1", "i2", "i3"}, 4)) == 6      # za mało świeżych: cała pula
    for sid in pack.skills:
        try:
            _, items = L.prepare(pack, sid)
        except L.LessonError:
            continue
        pool = [i for i in C.select_items(pack, pool="practice", purpose="practice", skill_id=sid)
                if i.type not in C.OPEN_TYPES and i.answers]
        only = [i for i in pool if "diagnosis" not in i.pools]
        assert sum("diagnosis" not in i.pools for i in items) == min(len(only), len(items)), sid
    pid = repo.create_profile("pr")
    repo.add_attempt(pid, SKILL, True, item_id="en.x", source="practice", dedupe_key="a")
    repo.add_attempt(pid, SKILL, True, item_id="en.y", source="diagnosis", dedupe_key="b")
    assert repo.practiced_items(pid) == {"en.x"}


def test_pattern_confirmed_use_feeds_p_but_never_mastery_status(repo, pack):
    """`target_patterns` potwierdza twierdzenie modelu o użyciu konstrukcji celu: próba trafia do p (BKT), z flagą
    `no_mastery` — rozmowa nie może samodzielnie przyznać statusu opanowania."""
    from tutor.pedagogy.assessment import evaluate_batch
    from tutor.pedagogy.schemas import TurnEval, Use, Utt
    goal = "en.gram.irregular_past"
    pid = repo.create_profile("tp")
    sid = repo.start_session(pid, "chat")
    for day, text in ((20, "Yesterday I went to the cinema."), (21, "I saw my friend there.")):
        tid = repo.add_turn(pid, sid, "user", text)
        q = text.split(" ", 1)[1].rstrip(".") if day == 20 else text.rstrip(".")
        ev = TurnEval(u=[Utt(i=0, o=[], t=[Use(id=goal, r="ok", s=q)])])
        res = evaluate_batch(ev, [text], input_modes=["text"], low_probs=[set()], pack=pack, goals={goal})[0]
        ingest.apply_turn_evaluation(repo, pack, pid, sid, tid, res, input_mode="text", text=text, goals={goal},
                                     now=datetime(2026, 11, day, 10, tzinfo=UTC))
    atts = repo.attempt_history(pid, goal)
    assert [a["correct"] for a in atts] == [True, True]
    assert all(json.loads(a["feedback_json"])["no_mastery"] for a in atts)
    assert repo.get_skill_state(pid, goal)["status"] not in ("mastered", "verified")


# --- LanguageTool: polityka fuzji i awaria ---
def test_lt_disabled_by_default_and_failure_falls_back_to_model(repo, pack):
    from tutor.app import eval_runner as ER
    from tutor.app import languagetool as LT
    assert ER.lt_candidates(pack, LT.settings({})) is None                     # domyślnie wyłączony
    cfg = LT.settings({"languagetool": {"enabled": True, "url": "http://127.0.0.1:9", "timeout": 0.2}})
    check = ER.lt_candidates(pack, cfg)
    assert check("He go home.", "text") is None                                 # serwer nie działa ⇒ None
    pid = repo.create_profile("lt")
    sid = repo.start_session(pid, "chat")
    tid = repo.add_turn(pid, sid, "user", "I goed home")
    prov = Prov()
    q = make_queue(repo, pack, prov, structured, profile_id=pid, session_id=sid, goals={}, lt=check)
    q.submit(Pending(tid, "I goed home", "text"))
    assert q.drain(CancelToken()) == 1 and len(repo.list_observations(pid)) == 1   # ocena samym modelem


def test_lt_policy_agreement_does_not_raise_and_names_skipped(pack):
    from tutor.app.languagetool import LTMatch
    from tutor.pedagogy import lt_merge as M
    text = "Dr Nowak have two childrens."
    ms = [LTMatch(3, 5, "", ("Novak",), "MORFOLOGIK_RULE_EN_US", "misspelling", "TYPOS"),
          LTMatch(18, 9, "", ("children's", "children"), "MORFOLOGIK_RULE_EN_US", "misspelling", "TYPOS"),
          LTMatch(9, 4, "", ("has",), "HE_VERB_AGR", "grammar", "GRAMMAR")]
    forms = {"children", "has"}
    obs, st = M.to_obs(ms, text, pack.lt_map, input_mode="text", known_forms=forms, trusted_rules=set(),
                       version="6.6")
    assert st["proper_name"] == 1 and [o.f for o in obs] == ["children", "has"]      # nazwisko nie jest literówką
    assert {o.p for o in obs} == {"l"}                         # produkcja: brak zaufanych reguł ⇒ podejrzenia
    trusted, _ = M.to_obs(ms, text, pack.lt_map, input_mode="text", known_forms=forms,
                          trusted_rules={"HE_VERB_AGR"}, version="6.6")
    assert [o.p for o in trusted if o.f == "has"] == ["m"]
    model = Obs(s="have", f="has", k="error", c="agreement.subject_verb", v=2, p="m")
    out, _ = M.merge([model], [o for o in trusted if o.f == "has"], text)
    assert out[0].p == "m" and out[0].src == "bielik+lt"      # zgodność nie podnosi pewności
