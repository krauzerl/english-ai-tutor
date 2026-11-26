"""F7: 100 standardowych + 50 ukrytych osiągnięć — każda reguła z wykrywalnym warunkiem, granice progów,
idempotencja, restart, izolacja profili, brak wpływu na mastery, ukrywanie sekretów."""
import json
from datetime import UTC, datetime, timedelta

import pytest

from tutor.app import achievements as AC
from tutor.pedagogy import content as C
from tutor.store.db import open_db
from tutor.store.repo import Repo

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


@pytest.fixture(scope="module")
def pack():
    return C.load("en")


# --- katalog ---
def test_catalog_has_100_standard_and_50_hidden_unique_codes():
    assert len(AC.STANDARD) == 100 and len(AC.SECRETS) == 50
    assert len({a["code"] for a in AC.CATALOG}) == 150
    assert all(not a["hidden"] for a in AC.STANDARD) and all(a["hidden"] for a in AC.SECRETS)
    for a in AC.CATALOG:
        assert a["name_pl"] and a["name_en"] and a["desc_pl"] and a["desc_en"] and a["target"] >= 1
        assert a["category"] in AC.CATEGORIES and a["category"] in AC.CATEGORIES_EN
    assert all(a["hint_pl"] and a["hint_en"] for a in AC.SECRETS)
    cats = {a["category"] for a in AC.STANDARD}
    assert {"regularity", "lessons", "conversation", "reviews", "improvement", "challenges", "assessment",
            "milestones"} <= cats
    assert len({a["metric"] for a in AC.CATALOG}) >= 60                     # nie tylko jeden licznik


def test_legacy_codes_kept_so_old_badges_stay():
    for code in ("streak_3", "streak_7", "streak_14", "streak_30", "days_10", "talk_10m", "talk_60m", "talk_300m",
                 "lesson_1", "lesson_5", "lesson_20", "review_10", "review_50", "review_200", "improved_1",
                 "improved_3", "improved_10", "exam_1", "exam_5", "topics_5", "triple_day", "comeback",
                 "first_session", "turns_100", "placement_done"):
        assert code in AC.BY_CODE


# --- granice każdej reguły (wszystkie 150) ---
@pytest.mark.parametrize("a", AC.CATALOG, ids=[a["code"] for a in AC.CATALOG])
def test_each_rule_threshold_boundary(repo, monkeypatch, a):
    pid = repo.create_profile("ann")
    monkeypatch.setattr(AC, "facts", lambda *_a, **_k: {a["metric"]: a["target"] - 1})
    assert a["code"] not in {n["code"] for n in AC.award(repo, pid, NOW, pack=object())}
    monkeypatch.setattr(AC, "facts", lambda *_a, **_k: {a["metric"]: a["target"]})
    assert a["code"] in {n["code"] for n in AC.award(repo, pid, NOW, pack=object())}


# --- profil z rzeczywistych zapisów: każda metryka jest wykrywalna ---
def _at(repo, table, rid, when):
    col = "started_at" if table == "session" else "created_at"
    repo.conn.execute(f"UPDATE {table} SET {col}=? WHERE id=?", (when.strftime("%Y-%m-%dT%H:%M:%S.000Z"), rid))


def _session(repo, pid, kind, when, plan=None, users=(), voice=False, ended=True, gap_s=60):
    sid = repo.start_session(pid, kind)
    _at(repo, "session", sid, when)
    t = when
    _at(repo, "turn", repo.add_turn(pid, sid, "assistant", "Hello, what do you think?"), t)
    for text in users:
        t += timedelta(seconds=gap_s)
        tid = repo.add_turn(pid, sid, "user", text, input_mode="voice" if voice else "text",
                            low_probs=[] if voice else None)
        _at(repo, "turn", tid, t)
    if plan:
        repo.set_session_plan(pid, sid, plan)
    if ended:
        repo.end_session(pid, sid)
    return sid


def _items(pack, area, lv):
    return [i for i in pack.items.values() if i.area == area and i.cefr == lv and i.answers]


@pytest.fixture(scope="module")
def rich(tmp_path_factory, pack):
    """Jeden profil z wieloma rodzajami aktywności rozłożonymi w czasie."""
    repo = Repo(open_db(tmp_path_factory.mktemp("ach") / "t.db"))
    pid = repo.create_profile("rich")
    long = " ".join(["word"] * 65)
    base = datetime(2026, 1, 1, 9, tzinfo=UTC)                                 # 1 stycznia (czwartek)
    # rozmowy: kategorie, tryby, poziomy, roleplay, intencje, głos, długie odpowiedzi
    cats = [("general", "gen.trip"), ("technical", "it.python"), ("medical", "med.shift"),
            ("business", "biz.meetings"), ("professional", "pro.career")]
    for k, (cat, tid) in enumerate(cats):
        _session(repo, pid, "chat", base + timedelta(days=k), {"topics": [{"id": tid, "category": cat}],
                 "category": cat, "mode": "natural", "level": ["A2", "B1", "C1", "B2", "B1"][k]},
                 users=["I like it a lot.", "Could you repeat that, please?", "What does booking mean?",
                        long, "No, I want to finish our conversation for now.", "x y z"])
    _session(repo, pid, "chat", base + timedelta(days=5), {"topics": [{"pl": "my cat"}], "category": "custom",
             "mode": "guided", "level": "B1", "slow_voice": True}, users=["a b c"] * 4, voice=True)
    for k, (cat, rid) in enumerate([("medical", "med.rp.chest_pain"), ("medical", "med.rp.breathless"),
                                    ("medical", "med.rp.trauma"), ("business", "biz.rp.investor"),
                                    ("technical", "it.rp.standup")]):
        _session(repo, pid, "chat", base + timedelta(days=6, hours=k), {
            "topics": [{"id": rid, "category": cat, "kind": "roleplay"}, {"id": "x"}, {"id": "y"}, {"id": "z"}],
            "category": cat, "mode": "roleplay", "level": "B1", "ladder_history": ["correct", "failed"]},
            users=["fine thanks"] * 16, gap_s=120)
    # noc, wczesny ranek, weekendy (sobota+niedziela), przerwy ≥7 i ≥30 dni
    _session(repo, pid, "chat", datetime(2026, 1, 10, 23, tzinfo=UTC), {"category": "general"},
             users=["night talk"] * 10)                                         # sobota
    _session(repo, pid, "chat", datetime(2026, 1, 11, 6, tzinfo=UTC), {"category": "general"},
             users=["early talk"] * 10)                                         # niedziela
    _session(repo, pid, "chat", datetime(2026, 3, 1, 10, tzinfo=UTC), {"category": "general"}, users=["back"] * 3)
    # lekcje (ukończone, bez podpowiedzi), próby w obszarach i poziomach, podpowiedzi, retencja
    sk = "en.gram.to_be_present"
    for k in range(3):
        when = datetime(2026, 3, 2, 9 + k, tzinfo=UTC)
        its = _items(pack, "grammar", "A1")[k * 2:k * 2 + 2]
        sid = _session(repo, pid, "lesson", when, {"lesson": f"{sk}{k}" if k else sk,
                       "items": [i.id for i in its], "done": [i.id for i in its], "ok": [i.id for i in its]})
        for i in its:
            aid = repo.add_attempt(pid, i.skill_ids[0], True, session_id=sid, item_id=i.id, hint_level=0)
            _at(repo, "attempt", aid, when)
    t = datetime(2026, 3, 3, 9, tzinfo=UTC)
    rsid = _session(repo, pid, "review", t, {"review": {}})
    for area in ("grammar", "vocabulary", "reading", "listening"):
        for lv in ("A1", "A2", "B1", "B2", "C1"):
            for i in _items(pack, area, lv)[:2]:
                t += timedelta(minutes=1)
                aid = repo.add_attempt(pid, i.skill_ids[0], True, session_id=rsid, item_id=i.id,
                                       feedback={"review": 1})
                _at(repo, "attempt", aid, t)
    hint_item = _items(pack, "grammar", "A2")[0]
    aid = repo.add_attempt(pid, hint_item.skill_ids[0], True, session_id=rsid, item_id=hint_item.id, hint_level=1)
    _at(repo, "attempt", aid, t + timedelta(minutes=5))
    later = _session(repo, pid, "review", datetime(2026, 3, 20, 9, tzinfo=UTC), {"review": {}})
    for i in _items(pack, "grammar", "A1")[:3]:
        aid = repo.add_attempt(pid, i.skill_ids[0], True, session_id=later, item_id=i.id, feedback={"review": 1})
        _at(repo, "attempt", aid, datetime(2026, 3, 20, 9, tzinfo=UTC))
    # diagnoza (pełna, z zadaniami otwartymi), powtórzona z wyższym wynikiem, sufit; szybkie dopasowanie
    res = {a: {"theta": 3.0, "se": 0.3, "label": "x"} for a in ("grammar", "vocabulary", "reading", "listening")}
    _session(repo, pid, "assessment", datetime(2026, 3, 21, 9, tzinfo=UTC), {"assessment": {
        "done": True, "results": res, "open": {"writing": {"status": "evidence"}, "speaking": {"status": "evidence"}}}})
    for area, th in (("grammar", 2.0), ("vocabulary", 1.5), ("reading", 3.0), ("listening", 3.0)):
        repo.add_competence(pid, area, "A2", th, 0.3, 8, "assessment_provisional", {"ceiling": area == "reading"},
                            measured_at="2026-03-21T09:00:00Z")
    lsid = _session(repo, pid, "lesson", datetime(2026, 3, 22, 9, tzinfo=UTC), {})
    _session(repo, pid, "review", datetime(2026, 3, 23, 9, tzinfo=UTC), {"review": {}},
             users=["ok"])                                                       # obieg: diagnoza→lekcja→powtórka
    _session(repo, pid, "assessment", datetime(2026, 4, 1, 9, tzinfo=UTC), {"assessment": {"done": True,
             "results": res, "open": {}}})
    repo.add_competence(pid, "vocabulary", "B1", 2.5, 0.3, 8, "assessment_provisional",
                        measured_at="2026-04-01T09:00:00Z")
    repo.add_competence(pid, "grammar", "A2", 2.0, 0.4, 6, "placement_provisional")
    # egzamin, drill + poprawa błędu, przegląd korekt, samopoprawki, zdarzenia aplikacji
    _session(repo, pid, "exam", datetime(2026, 4, 2, 9, tzinfo=UTC), {"exam": {"finished": True,
             "results": [{"verdict": "correct"}] * 5}})
    dsid = _session(repo, pid, "drill", datetime(2026, 4, 3, 9, tzinfo=UTC), {"drill": {"category": "article.missing"}})
    it = _items(pack, "grammar", "A2")[1]
    _at(repo, "attempt", repo.add_attempt(pid, it.skill_ids[0], True, session_id=dsid, item_id=it.id),
        datetime(2026, 4, 3, 9, tzinfo=UTC))
    _session(repo, pid, "chat", datetime(2026, 3, 2, 18, tzinfo=UTC), {"category": "general"}, users=["evening"] * 3)
    r2 = _session(repo, pid, "review", datetime(2026, 3, 2, 19, tzinfo=UTC), {"review": {}})
    _at(repo, "attempt", repo.add_attempt(pid, it.skill_ids[0], True, session_id=r2, item_id=it.id,
                                          feedback={"review": 1}), datetime(2026, 3, 2, 19, tzinfo=UTC))
    tid = repo.list_turns(pid, lsid)[0]["id"]
    for k in range(2):
        oid = repo.add_observation(pid, lsid, tid, "error", f"span{k}", category="article.missing", fix="a span",
                                   severity=2, confidence="h")
        repo.add_observation_review(pid, oid, "disputed" if k == 0 else "stt_error")
    repo.put_error_log(pid, "article.missing", None, count=3, status="improving", severity_max=2, reopened=0,
                       example="x", correction="y", example_observation_id=None, first_seen="2026-03-01T00:00:00Z",
                       last_seen="2026-04-01T00:00:00Z")
    for kind, data in (("ui_lang", {"value": "en", "from": "pl"}), ("stt_corrected", {}), ("stt_rerecord", {}),
                       ("setting", {"key": "speed", "value": 0.8})):
        AC.record_event(repo, pid, kind, data)
    yield repo, pid
    repo.conn.close()


# metryki, które bogaty profil celowo osiąga (≥ 1); progi duże (np. 50 000 słów) sprawdza test granic
REACHED = {
    "streak", "study_days", "active_weeks", "active_months", "weekend_days", "full_weekends", "comeback",
    "comeback30", "days_two_kinds", "lessons", "lessons_perfect", "hint_free_lessons", "skills_practised",
    "areas_practised", "hint_successes", "lessons_day_max", "first_try_streak", "talk_minutes", "chats",
    "chat_categories", "chat_modes", "roleplays", "roleplay_scenarios", "long_answers", "voice_turns",
    "clear_voice_turns", "chat_levels", "custom_topics", "chat_minutes_max", "reviews", "review_correct",
    "retention7", "retention14", "review_days", "review_streak", "review_big_session", "perfect_review_sessions",
    "errors_improved", "drills", "self_corrections", "journal_reviews", "disputes", "stt_marks",
    "drill_then_improved", "exam_sessions", "exam_perfect", "hard_correct", "c1_correct", "listening_correct",
    "reading_correct", "medical_roleplays", "business_roleplays", "it_roleplays", "roleplays_day_max",
    "placements", "assess_areas", "assess_full", "open_tasks", "open_both", "assess_all_six", "assessments",
    "precise_areas", "assess_up", "ceiling_area", "weak_area_up", "full_circle", "sessions", "user_turns",
    "words", "attempts", "night_session", "early_session", "new_year", "ui_langs", "longest_answer",
    "finish_requests", "repeat_requests", "explain_requests", "topic_changes_max", "guided_chats",
    "slow_voice_session", "c1_chats", "level_climb", "long_roleplay", "listening_levels", "reading_levels",
    "grammar_levels", "vocabulary_levels", "stt_corrections", "stt_rerecords", "language_settings",
    "comeback_after_review", "week_kinds_max", "day_minutes_max", "triple_days", "triple_day",
}
NOT_IN_RICH = {"errors_resolved", "exam_correct", "fewer_errors", "mixed_input_chats"}   # osobne testy niżej


def test_every_catalog_metric_is_computed_or_tested_separately():
    metrics = {a["metric"] for a in AC.CATALOG}
    assert metrics <= REACHED | NOT_IN_RICH, sorted(metrics - REACHED - NOT_IN_RICH)


@pytest.mark.parametrize("metric", sorted(REACHED))
def test_metric_detected_from_real_records(rich, pack, metric):
    repo, pid = rich
    f = AC.facts(repo, pid, NOW, pack)
    assert f.get(metric, 0) >= 1, (metric, {k: v for k, v in f.items() if v})


def test_rich_profile_values_are_exact_where_known(rich, pack):
    repo, pid = rich
    f = AC.facts(repo, pid, NOW, pack)
    assert f["chat_categories"] == 6 and f["chat_modes"] == 3 and f["medical_roleplays"] == 3
    assert f["disputes"] == 1 and f["stt_marks"] == 1 and f["ui_langs"] == 2 and f["new_year"] == 1
    assert f["full_weekends"] == 2 and f["comeback30"] == 1   # 3–4 i 10–11 stycznia and f["self_corrections"] == 5


def test_resolved_exam_and_mixed_input(repo, pack):
    pid = repo.create_profile("ann")
    sid = _session(repo, pid, "exam", NOW - timedelta(days=1), {"exam": {"finished": True, "results": []}})
    it = _items(pack, "grammar", "B1")[0]
    repo.add_attempt(pid, it.skill_ids[0], True, session_id=sid, item_id=it.id)
    repo.put_error_log(pid, "tense", None, count=3, status="resolved", severity_max=2, reopened=0, example="x",
                       correction="y", example_observation_id=None, first_seen="2026-01-01T00:00:00Z",
                       last_seen="2026-02-01T00:00:00Z")
    chat = _session(repo, pid, "chat", NOW - timedelta(days=2), {"category": "general", "mode": "natural"},
                    users=["typed one", "typed two"])
    repo.add_turn(pid, chat, "user", "spoken", input_mode="voice", low_probs=[])
    f = AC.facts(repo, pid, NOW, pack)
    assert f["errors_resolved"] == 1 and f["exam_correct"] == 1 and f["mixed_input_chats"] == 1


def test_fewer_errors_needs_60_evaluated_answers(repo, pack):
    pid = repo.create_profile("ann")
    sid = repo.start_session(pid, "chat")
    for k in range(60):
        tid = repo.add_turn(pid, sid, "user", f"answer {k}")
        repo.conn.execute("INSERT INTO turn_meta(turn_id,session_id,profile_id,input_mode,eval_status) "
                          "VALUES (?,?,?,?,?)", (tid, sid, pid, "text", "evaluated"))
        if k < 10:
            repo.add_observation(pid, sid, tid, "error", "answer", category="tense", fix="answers", severity=2,
                                 confidence="h")
    assert AC.facts(repo, pid, NOW, pack)["fewer_errors"] == 1


# --- trwałość, idempotencja, izolacja, mastery ---
def test_award_is_idempotent_and_survives_restart(tmp_path, pack):
    path = tmp_path / "t.db"
    repo = Repo(open_db(path))
    pid = repo.create_profile("ann")
    _session(repo, pid, "chat", NOW - timedelta(days=1), {"category": "general"}, users=["a b c"] * 3)
    first = AC.award(repo, pid, NOW, pack)
    assert {"first_session", "chats_1"} <= {a["code"] for a in first}
    assert AC.award(repo, pid, NOW, pack) == []                                   # drugi raz nic nowego
    repo.conn.close()
    repo = Repo(open_db(path))                                                    # restart aplikacji
    assert AC.award(repo, pid, NOW, pack) == []
    ov = AC.overview(repo, pid, NOW, pack)
    assert next(i for i in ov["items"] if i["code"] == "first_session")["earned"]
    repo.conn.close()


def test_profiles_isolated(repo, pack):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    _session(repo, a, "chat", NOW - timedelta(days=1), {"category": "general"}, users=["x y"] * 3)
    AC.award(repo, a, NOW, pack)
    assert AC.award(repo, b, NOW, pack) == [] and repo.list_achievements(b) == []


def test_achievements_never_touch_mastery_or_results(rich, pack):
    repo, pid = rich
    before = (repo.list_skill_states(pid), repo.list_competence(pid), len(repo.list_errors(pid)))
    AC.award(repo, pid, NOW, pack)
    assert (repo.list_skill_states(pid), repo.list_competence(pid), len(repo.list_errors(pid))) == before


def test_hidden_show_hint_only_until_earned(repo, pack):
    pid = repo.create_profile("ann")
    ov = AC.overview(repo, pid, NOW, pack)
    s = next(i for i in ov["items"] if i["code"] == "s_night_owl")
    assert s["name"] == "???" and s["progress"] is None and s["description"] == AC.BY_CODE["s_night_owl"]["hint_pl"]
    _session(repo, pid, "chat", datetime(2026, 11, 20, 23, tzinfo=UTC), {"category": "general"},
             users=["late"] * 10)
    AC.award(repo, pid, NOW, pack)
    s = next(i for i in AC.overview(repo, pid, NOW, pack)["items"] if i["code"] == "s_night_owl")
    assert s["earned"] and s["name"] == "Nocny marek" and s["name_en"] == "Night owl"
    assert AC.overview(repo, pid, NOW, pack)["secret"] == {"earned": 1, "total": 50}


def test_old_earned_codes_stay_visible(repo, pack):
    pid = repo.create_profile("ann")
    repo.add_achievement(pid, "streak_3", {})
    repo.add_achievement(pid, "some_removed_code", {})
    items = {i["code"]: i for i in AC.overview(repo, pid, NOW, pack)["items"]}
    assert items["streak_3"]["earned"] and items["some_removed_code"]["earned"]


def test_short_clicky_sessions_do_not_count(repo, pack):
    pid = repo.create_profile("ann")
    for k in range(5):                                                            # puste sesje bez pracy
        sid = repo.start_session(pid, "chat")
        repo.end_session(pid, sid)
    f = AC.facts(repo, pid, NOW, pack)
    assert f.get("study_days", 0) == 0 and f.get("chats", 0) == 0 and f.get("night_session", 0) == 0


def test_settings_events_recorded_only_on_real_change(repo, pack):
    from tutor.services.api import TutorAPI
    api = TutorAPI(repo)
    api._packs = {"en": pack}
    pid = repo.create_profile("ann")
    api.update_settings(pid, {"speed": 0.9})                                      # bez zmiany (domyślne 0.9)
    assert repo.conn.execute("SELECT COUNT(*) FROM app_event").fetchone()[0] == 0
    api.update_settings(pid, {"ui_lang": "en"})
    api.update_settings(pid, {"ui_lang": "pl"})
    assert AC.facts(repo, pid, NOW, pack)["ui_langs"] == 2
    assert json.loads(repo.conn.execute("SELECT data_json FROM app_event").fetchone()[0])["value"] == "en"
