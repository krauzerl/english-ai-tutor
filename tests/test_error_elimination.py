"""Nauka na powtarzających się błędach: sprawdzenie → wyjaśnienie → ćwiczenia → test → transfer → planer.

Prawdziwa SQLite w tmp_path (nigdy baza właściciela), prawdziwa paczka treści, odpowiedzi ucznia z listy.
Mastery zamknięte we wszystkich ścieżkach. Ostatnie testy: Quick Chat (sprawdzenie głosowe na starcie i 7 dni
samych rozmów → raport: aktywność oddzielona od dowodów).
"""
import json
from datetime import UTC, datetime, timedelta

import pytest

from tutor.app import goal as G
from tutor.app import learning_report as LR
from tutor.app import learnlog as LL
from tutor.app import lesson as L
from tutor.app import remediation as R
from tutor.app import weakspots as W
from tutor.pedagogy import content as C

NOW = datetime(2026, 11, 26, 10, tzinfo=UTC)
SKILL, CAT = "en.gram.past_simple_regular", "tense.past_simple"
WRONG = "zzz wrong answer here"


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


def recurring(repo, pid, cat=CAT, last_seen="2026-11-20T10:00:00.000Z"):
    repo.put_error_log(pid, cat, None, count=4, status="recurring", severity_max=2, reopened=0, example="I walk "
                       "yesterday", correction="I walked yesterday", example_observation_id=None,
                       first_seen="2026-11-01T10:00:00.000Z", last_seen=last_seen)


def start(repo, pack, pid, now=NOW):
    ch = G.choose(repo, pack, pid, now)
    sid = repo.start_session(pid, "lesson")
    sk, items = L.begin(repo, pack, pid, sid, ch.skill_id, {"source": ch.source, "reason": ch.reason,
                                                            "provisional": True, "category": ch.category})
    return ch, sid, sk, items


def answers(policy):
    """policy: {stage: "ok" | "wrong" | callable(item) -> Answer}; zwraca `ask` dla run_exercises."""
    def ask_for(repo, pid, sid):
        def ask(item, _i):
            st = repo.get_session_plan(pid, sid)["stages"][item.id]
            p = policy.get(st, "ok")
            if callable(p):
                return p(item)
            return L.Answer(item.answers[0] if p == "ok" else WRONG)
        return ask
    return ask_for


def run(repo, pack, pid, sid, sk, items, policy, now=NOW, said=None):
    return L.run_exercises(repo, pack, pid, sid, sk, items, answers(policy)(repo, pid, sid),
                           (said.append if said is not None else lambda s: None), now=now)


def stages(repo, pid, sid):
    p = repo.get_session_plan(pid, sid)
    return {k: [i for i in p["items"] if p["stages"][i] == k] for k in set(p["stages"].values())}


# 1. błąd → sprawdzenie przed wyjaśnieniem
def test_1_recurring_error_starts_with_check_before_explanation(repo, pack):
    pid = repo.create_profile("e1")
    recurring(repo, pid)
    ch, sid, sk, items = start(repo, pack, pid)
    assert ch.source == "error" and ch.category == CAT and ch.skill_id == SKILL
    assert "sprawdzenia" in ch.reason and "niezweryfikowana" in ch.reason
    st = repo.get_session_plan(pid, sid)["stages"]
    assert st[items[0].id] == "pre" and [st[i.id] for i in items][-1] == "post"
    said: list[str] = []

    def pre(item):                     # prośba o pomoc w sprawdzeniu: bez podpowiedzi, potem odpowiedź
        pre.n = getattr(pre, "n", 0) + 1
        return L.Answer("I don't understand" if pre.n == 1 else item.answers[0])
    run(repo, pack, pid, sid, sk, items, {"pre": pre}, said=said)
    text = "\n".join(said)
    expl = L.explanation(pack, sk)[:40]
    i_pre_task = text.index("Zadanie 1/")
    i_expl = text.index(expl)
    assert i_pre_task < text.index("Sprawdzenie:") < i_expl            # reguła dopiero po sprawdzeniu
    assert "nie podpowiadam" in text and "Przypomnienie — poprawne przykłady" not in text[:i_expl]
    assert items[0].answers[0] not in text[:text.index("Sprawdzenie:")].replace(items[0].prompt, "")
    assert L.intro(pack, sk, None, repo.get_session_plan(pid, sid)).count(expl) == 0


# 2. / 3. wynik sprawdzenia przed lekcją
def test_2_precheck_correct_is_not_proof_error_never_existed(repo, pack):
    pid = repo.create_profile("e2")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    said: list[str] = []
    run(repo, pack, pid, sid, sk, items, {"pre": "ok"}, said=said)
    agv = repo.get_session_plan(pid, sid)["agv"]
    assert agv["outcome"] == "not_confirmed" and agv["after_explanation"] is False and agv["stage"] == "pre"
    assert any("nie znaczy, że błędu w rozmowie nie było" in s for s in said)


def test_3_precheck_wrong_confirms_problem_in_exercise(repo, pack):
    pid = repo.create_profile("e3")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    run(repo, pack, pid, sid, sk, items, {"pre": "wrong"})
    plan = repo.get_session_plan(pid, sid)
    assert plan["agv"]["outcome"] == "confirmed" and plan["results"][items[0].id] == "wrong"
    e = next(x for x in W.build(repo, pack, pid, NOW)["errors"] if x["category"] == CAT)
    assert e["reliability"] == "potwierdzony ćwiczeniem kontrolnym" and e["learning"]


# 4. wyjaśnienie i ćwiczenia (podpowiedź = wynik „z pomocą”, rosnąca trudność, bez mastery)
def test_4_practice_with_hint_is_assisted_and_plain_practice(repo, pack):
    pid = repo.create_profile("e4")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    tries: dict[str, int] = {}

    def prac(item):
        tries[item.id] = tries.get(item.id, 0) + 1
        return L.Answer(WRONG if tries[item.id] == 1 else item.answers[0])
    said: list[str] = []
    run(repo, pack, pid, sid, sk, items, {"practice": prac}, said=said)
    plan = repo.get_session_plan(pid, sid)
    prac_ids = stages(repo, pid, sid)["practice"]
    assert prac_ids and all(plan["results"][i] == "assisted" for i in prac_ids)
    assert any(s.endswith("Spróbuj jeszcze raz.") for s in said)        # drabina podpowiedzi tylko w ćwiczeniach
    diffs = [pack.items[i].difficulty for i in prac_ids]
    assert diffs == sorted(diffs)
    srcs = {a["item_id"]: a["source"] for a in repo.attempt_history(pid, SKILL)}
    assert {srcs[i] for i in prac_ids} == {"practice"}
    assert {srcs[i] for i in stages(repo, pid, sid)["pre"] + stages(repo, pid, sid)["post"]} == {"remediation"}


# 5. samodzielny test po lekcji: nowe zadania, kategorie wyników
def test_5_posttest_uses_other_items_and_distinguishes_help(repo, pack):
    pid = repo.create_profile("e5")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    st = stages(repo, pid, sid)
    assert not set(st["post"]) & (set(st["pre"]) | set(st["practice"]))
    asked: list[int] = []

    def post(item):                                    # najpierw prośba o pomoc, potem poprawnie = „z pomocą”
        asked.append(1)
        return L.Answer("I don't understand" if len(asked) == 1 else item.answers[0])
    run(repo, pack, pid, sid, sk, items, {"post": post})
    plan = repo.get_session_plan(pid, sid)
    assert [plan["results"][i] for i in st["post"]] == ["assisted"]
    summ = L.stage_summary(plan)
    assert "Test samodzielny: 0/1 samodzielnie (1 z pomocą)" in summ and "nie trwałe opanowanie" in summ
    rec = R.history(repo, pid)[CAT][-1]
    assert R.outcome(rec["stages"]["post"]) == "inconclusive" and "do powtórki" in R.status_pl([rec])


# 6. ponowne wystąpienie problemu po lekcji + brak pętli tej samej lekcji
def test_6_recurrence_after_lesson_and_lesson_cap(repo, pack):
    pid = repo.create_profile("e6")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    run(repo, pack, pid, sid, sk, items, {})                         # wszystko samodzielnie poprawnie
    assert G.choose(repo, pack, pid, NOW + timedelta(days=1)).source not in ("error", "transfer")
    recurring(repo, pid, last_seen="2026-11-27T09:00:00.000Z")       # błąd znowu w rozmowie
    ch = G.choose(repo, pack, pid, NOW + timedelta(days=1))
    assert ch.source == "error" and "pojawił się znowu" in ch.reason
    s2 = repo.start_session(pid, "lesson")
    sk2, it2 = L.begin(repo, pack, pid, s2, ch.skill_id, {"source": "error", "category": CAT, "reason": ch.reason})
    assert repo.get_session_plan(pid, s2)["cycle"]["fresh"] is False   # 3 zadania w puli: znane — zapisane jawnie
    run(repo, pack, pid, s2, sk2, it2, {"post": "wrong"}, now=NOW + timedelta(days=1))
    recurring(repo, pid, last_seen="2026-11-28T09:00:00.000Z")
    later = G.choose(repo, pack, pid, NOW + timedelta(days=2, hours=12))
    assert later.source != "error"                                    # 2 lekcje w 14 dniach: nie w kółko
    assert any("Ponowne wystąpienie" in x for x in R.lines(R.history(repo, pid)[CAT], repo, pid))


# 7. retencja / transfer na nowym zadaniu po przerwie
def test_7_transfer_on_new_items_after_break(repo, pack):
    pid = repo.create_profile("e7")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    run(repo, pack, pid, sid, sk, items, {})
    assert G.choose(repo, pack, pid, NOW + timedelta(days=2)).source != "transfer"    # za wcześnie
    later = NOW + timedelta(days=4)
    ch = G.choose(repo, pack, pid, later)
    assert ch.source == "transfer" and ch.category == CAT and "nowe zadania" in ch.reason
    s2 = repo.start_session(pid, "lesson")
    sk2, it2 = L.begin(repo, pack, pid, s2, ch.skill_id, {"source": "transfer", "category": CAT, "reason": ch.reason})
    plan = repo.get_session_plan(pid, s2)
    assert set(plan["stages"].values()) == {"transfer"} and not {i.id for i in it2} & {i.id for i in items}
    assert all("retention" in i.pools for i in it2)
    said: list[str] = []
    run(repo, pack, pid, s2, sk2, it2, {"transfer": "ok"}, now=later, said=said)
    assert L.explanation(pack, sk)[:40] not in "\n".join(said)       # bez wyjaśnienia
    recs = R.history(repo, pid)[CAT]
    assert recs[-1]["kind"] == "transfer" and "nie trwałe opanowanie" in R.status_pl(recs)
    assert G.choose(repo, pack, pid, later + timedelta(days=1)).source not in ("error", "transfer")
    assert all(i.id not in R.seen_items(repo, pid, SKILL) - {x.id for x in it2} for i in it2)
    assert G.completed(repo, pid)[SKILL]["total"] == len(items)       # transfer nie jest „ukończoną lekcją”


# 8. przerwanie i wznowienie lekcji
def test_8_interrupt_and_resume_keeps_stage_results(repo, pack):
    pid = repo.create_profile("e8")
    recurring(repo, pid)
    ch, sid, sk, items = start(repo, pack, pid)
    first = {"n": 0}

    def quit_after_pre(item):
        first["n"] += 1
        return L.Answer(WRONG) if first["n"] == 1 else None
    res = L.run_exercises(repo, pack, pid, sid, sk, items,
                          lambda it, i: quit_after_pre(it), lambda s: None, now=NOW)
    assert res.quit
    plan = repo.get_session_plan(pid, sid)
    assert plan["results"] == {items[0].id: "wrong"} and plan["agv"]["outcome"] == "confirmed"
    sk_b, it_b = L.begin(repo, pack, pid, sid, ch.skill_id, plan["choice"])     # wznowienie: te same zadania
    assert [i.id for i in it_b] == [i.id for i in items]
    said: list[str] = []
    run(repo, pack, pid, sid, sk_b, it_b, {}, said=said)
    assert L.explanation(pack, sk)[:40] in "\n".join(said)            # wyjaśnienie przed ćwiczeniami po wznowieniu
    plan = repo.get_session_plan(pid, sid)
    assert plan["results"][items[0].id] == "wrong" and len(plan["done"]) == len(items)


# 9. learning logs: etapy, porównanie przed/po w raporcie
def test_9_learning_log_events_and_before_after_report(repo, pack):
    pid = repo.create_profile("e9")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    run(repo, pack, pid, sid, sk, items, {"pre": "wrong"})
    evs = [e for e in LL.events(repo, pid, session_id=sid) if e["kind"] == "log.remediation"]
    assert [e["data"]["stage"] for e in evs] == ["pre", "practice", "post"]
    assert evs[0]["data"]["outcome"] == "confirmed" and evs[0]["data"]["wrong"] == 1
    assert all(e["data"]["category"] == CAT for e in evs)
    rep = LR.build(repo, pack, pid, session_id=sid)
    rem = rep["progress"]["remediation"][0]
    md = LR.render(rep, pack)
    assert rem["category"] == CAT and "Nauka na błędach" in md
    line = next(x for x in rem["lines"] if x.startswith("Lekcja"))
    assert "Sprawdzenie wstępne: 0/1 samodzielnie" in line and "Test samodzielny: 1/1 samodzielnie" in line
    assert any("Transfer" in x and "niesprawdzony" in x for x in rem["lines"])
    f = LL.session_file(repo, pid, sid)
    assert f and "log.remediation" in f.read_text() and WRONG not in f.read_text()   # JSONL bez tekstu odpowiedzi


# 10. izolacja profili
def test_10_profile_isolation(repo, pack):
    a, b = repo.create_profile("ea"), repo.create_profile("eb")
    recurring(repo, a)
    _, sid, sk, items = start(repo, pack, a)
    run(repo, pack, a, sid, sk, items, {"pre": "wrong"})
    assert R.history(repo, b) == {} and CAT in R.history(repo, a)
    recurring(repo, b)
    ch = G.choose(repo, pack, b, NOW)
    assert ch.source == "error" and "zaczniemy od krótkiego sprawdzenia" in ch.reason
    assert repo.attempt_history(b, SKILL) == []


# 11. brak automatycznego mastery
def test_11_no_mastery_after_perfect_cycle_and_transfer(repo, pack):
    pid = repo.create_profile("e11")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    run(repo, pack, pid, sid, sk, items, {})
    ch = G.choose(repo, pack, pid, NOW + timedelta(days=4))
    s2 = repo.start_session(pid, "lesson")
    sk2, it2 = L.begin(repo, pack, pid, s2, ch.skill_id, {"source": "transfer", "category": CAT})
    run(repo, pack, pid, s2, sk2, it2, {})
    atts = repo.attempt_history(pid, SKILL)
    assert atts and all(json.loads(a["feedback_json"])["no_mastery"] for a in atts)
    assert repo.get_skill_state(pid, SKILL)["status"] not in ("mastered", "verified")
    assert pack.rubric.correction["quality_gate"]["trusted_categories"] == []


# 12. odpowiedzi niejednoznaczne (niepewne STT) i warianty BrE/AmE
def test_12_ambiguous_voice_answers_are_not_counted(repo, pack):
    pid = repo.create_profile("e12")
    recurring(repo, pid)
    _, sid, sk, items = start(repo, pack, pid)
    said: list[str] = []
    run(repo, pack, pid, sid, sk, items, {"pre": lambda it: L.Answer("mmm", mode="voice", low_probs=["mmm"])},
        said=said)
    plan = repo.get_session_plan(pid, sid)
    assert plan["results"][items[0].id] == "ambiguous" and plan["agv"]["outcome"] == "no_data"
    assert any("niejednoznaczną" in s for s in said)
    pre_atts = [a for a in repo.attempt_history(pid, SKILL) if a["item_id"] == items[0].id]
    assert pre_atts == []                               # brak oceny = brak próby (ani błąd, ani sukces)
    assert "1 niejednoznaczne" in L.stage_summary(plan)


def test_12b_bre_ame_variants_accepted(pack):
    base = next(i for i in pack.items.values() if i.type == "gap" and i.answers)
    it = base.model_copy(update={"answers": ["travelled"], "options": None, "prompt": "We ___ to Spain.",
                                 "domain": "general"})
    assert L.check(pack, it, "traveled") and L.check(pack, it, "travelled")
    it2 = it.model_copy(update={"answers": ["colour"]})
    assert L.check(pack, it2, "color")


def test_pool_too_small_marks_no_data(pack):
    st = R.staged(pack, SKILL, set(), True)
    assert len(st["pre"]) == 1 and len(st["post"]) == 1               # 3 zadania: 1 + 1 + 1, nie wymyślamy więcej
    assert R.outcome({"independent": 0, "assisted": 0, "wrong": 0, "ambiguous": 2, "n": 2, "answered": 2}) == \
        "no_data"
    assert "brak danych" in R._frac(None)


# --- Quick Chat: sprawdzenie głosowe na starcie rozmowy (CLI, ten sam silnik co GUI) ---
def test_chat_check_runs_at_chat_start_and_is_recorded(repo, conn, pack):
    from tests.test_cli_e2e import Env, EvalProv
    from tests.voice_fakes import Lines
    env = Env(repo, conn)
    recurring(repo, env.pid)
    chk = R.chat_check(repo, pack, env.pid, datetime.now(UTC), True)
    assert chk and chk["category"] == CAT
    ans = [i.answers[0] for i in chk["items"]]
    code, out = env.go(Lines(*ans, "I walked to work today", "q"), ["--no-audio", "--chat", "Work"], ev=EvalProv())
    assert code == 0
    s = [x for x in repo.list_sessions(env.pid) if x["kind"] == "chat"][-1]
    plan = repo.get_session_plan(env.pid, s["id"])
    assert plan["cycle"]["kind"] == "check" and set(plan["results"].values()) == {"independent"}
    text = "\n".join(out)
    assert "Krótkie sprawdzenie głosowe" in text and "Sprawdzenie głosowe w Quick Chat: 2/2" in text
    assert any(t["text"] == "I walked to work today" for t in env.turns())     # potem zwykła rozmowa
    assert R.chat_check(repo, pack, env.pid, datetime.now(UTC), True) is None   # nie częściej niż co 2 dni


def test_chat_check_can_be_disabled_and_skipped(repo, conn, pack):
    from tests.test_cli_e2e import Env, EvalProv
    from tests.voice_fakes import Lines
    from tutor.app import settings as S
    env = Env(repo, conn)
    recurring(repo, env.pid)
    code, out = env.go(Lines("skip", "Hello there", "q"), ["--no-audio", "--chat", "Work"], ev=EvalProv())
    assert "pomijamy sprawdzenie" in "\n".join(out) and any(t["text"] == "Hello there" for t in env.turns())
    S.update(repo, env.pid, {"chat_checks": False})
    repo.conn.execute("DELETE FROM session WHERE profile_id=?", (env.pid,))
    code, out = env.go(Lines("Hi", "q"), ["--no-audio", "--chat", "Work"], ev=EvalProv())
    assert "Krótkie sprawdzenie" not in "\n".join(out)


# --- 7 dni wyłącznie Quick Chat (dane symulowane) → raport: aktywność ≠ dowody ---
def _wrong(item):
    """Wyraźna błędna odpowiedź (głosem dla zadań wyboru; inne tekstem — głosowa „zła” luka bywa niejasna)."""
    if item.options:
        return L.Answer(next(o for o in item.options if o not in item.answers), mode="voice", low_probs=[])
    return L.Answer(WRONG)


def _at(repo, table, rid, ts):
    col = "started_at" if table == "session" else "created_at"
    repo.conn.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (ts, rid))


def test_seven_days_quick_chat_only_report(repo, pack, tmp_path):
    pid = repo.create_profile("week")
    day0 = datetime.now(UTC).replace(microsecond=0) - timedelta(days=7)
    check_ok = {1: [False, False], 3: [True, False], 5: [True, True], 7: [True, True]}   # sprawdzenia co 2 dni
    for d in range(1, 8):
        t = day0 + timedelta(days=d)
        ts = t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        sid = repo.start_session(pid, "chat", planned_minutes=15)
        _at(repo, "session", sid, ts)
        repo.set_session_plan(pid, sid, {"topic": {"pl": f"Temat {d}"}, "mode": "natural"})
        for k in range(4 + d):                                     # coraz więcej wypowiedzi (aktywność)
            repo.add_turn(pid, sid, "assistant", "What did you do yesterday?")
            text = "I walk to work yesterday and then I go home" if k == 0 and d < 5 else \
                "Yesterday I walked to the office — I worked on a report"
            tid = repo.add_turn(pid, sid, "user", text, input_mode="voice")
            _at(repo, "turn", tid, ts)
            repo.put_turn_meta(pid, sid, tid, "voice", eval_status="evaluated")
            LL.log(repo, pid, "log.stt", sid, status="ok", text=text, audio_s=6.0 + d, stt_s=0.4)
            if k == 0 and d < 5:                                     # sugestia modelu (dni 1–4)
                oid = repo.add_observation(pid, sid, tid, "error", "walk", fix="walked", category=CAT,
                                           confidence="h", model="qwen3:8b", prompt_version="turn_eval.v3")
                _at(repo, "observation", oid, ts)
        recurring(repo, pid, last_seen=(day0 + timedelta(days=4)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))
        if d in check_ok:                                            # sprawdzenie głosowe na starcie rozmowy
            items = R.fresh_items(pack, SKILL, R.seen_items(repo, pid, SKILL), True) or \
                R.staged(pack, SKILL, set(), True)["pre"][:2]
            cyc = {"category": CAT, "skill_id": SKILL, "kind": "check", "fresh": True, "unverified_items": True}
            repo.set_session_plan(pid, sid, {**repo.get_session_plan(pid, sid), **R.plan_for({"check": items}, cyc)})
            oks = iter(check_ok[d])
            L.run_exercises(repo, pack, pid, sid, pack.skills[SKILL], items,
                            lambda it, i, oks=oks: L.Answer(it.answers[0], mode="voice", low_probs=[])
                            if next(oks, True) else _wrong(it),
                            lambda s: None, now=t)
    rep = LR.build(repo, pack, pid, since=(day0 + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"))
    act = rep["activity"]["total"]
    assert act["days"] == 7 and act["chat_sessions"] == 7 and act["voice"] == act["utterances"] == sum(
        4 + d for d in range(1, 8))
    assert act["speaking_known"] == act["utterances"] and act["speaking_s"] == sum((6 + d) * (4 + d)
                                                                                    for d in range(1, 8))
    assert act["suggestions"] == 4 and act["self_repairs"] >= 0
    rem = next(r for r in rep["progress"]["remediation"] if r["category"] == CAT)
    checks = [x for x in rem["lines"] if x.startswith("Sprawdzenie głosowe")]
    # porównywalne zadania na NOWYCH pozycjach (pula się kończy: ostatnie sprawdzenie ma 1 zadanie — oznaczone)
    assert len(checks) == 4 and "0/2" in checks[0] and "1/1" in checks[-1] and "słaby dowód" in checks[-1]
    md = LR.render(rep, pack)
    assert "to NIE są dowody postępu" in md and "Wymowa nie jest oceniana" in md
    assert "NIE jest uznawana za poprawną" in md and "dowody z zadań kontrolnych" in md
    assert all(a["source"] == "remediation" for a in repo.attempt_history(pid, SKILL))
    assert repo.get_skill_state(pid, SKILL)["status"] not in ("mastered", "verified")
    (tmp_path / "week.md").write_text(md, encoding="utf-8")
