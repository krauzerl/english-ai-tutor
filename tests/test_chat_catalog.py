"""F7 Quick Chat: poziom × kategoria × tryb, katalog tematów i scenariuszy, CLI (atrapy modeli, bez mastery)."""
import pytest

from tests.llm_fakes import FakeProvider
from tests.test_cli_e2e import Env, EvalProv
from tests.test_feedback import Gated
from tutor.app import quickchat as QC
from tutor.app import settings as ST
from tutor.app import topics as T

CATS = ("general", "technical", "medical", "business", "professional")


@pytest.fixture
def env(repo, conn):
    return Env(repo, conn)


# --- katalog ---
def test_catalog_items_are_complete():
    c = T.chat_catalog()
    assert set(c["categories"]) == set(CATS)
    for t in c["items"].values():
        lo, hi = t["lv"]
        assert lo in T.LEVELS and hi in T.LEVELS and T.LEVELS.index(lo) <= T.LEVELS.index(hi), t["id"]
        assert len(t["q"]) > 15 and t["pl"], t["id"]
        if t["kind"] == "roleplay":
            assert all(t.get(k) for k in ("role", "learner", "context_pl", "setup", "opener")), t["id"]


@pytest.mark.parametrize("cat", CATS)
@pytest.mark.parametrize("level", T.LEVELS)
def test_every_category_and_level_has_topics_and_scenarios(repo, cat, level):
    pid = repo.create_profile("ann")
    topics = T.suggest(repo, pid, 4, seed=1, category=cat, level=level, mode="natural")
    scen = T.suggest(repo, pid, 4, seed=1, category=cat, level=level, mode="roleplay")
    assert len(topics) >= 2 and {t["category"] for t in topics} == {cat} and {t["kind"] for t in topics} == {"topic"}
    assert scen and {t["kind"] for t in scen} == {"roleplay"} and {t["category"] for t in scen} == {cat}


def test_level_filter_and_easier_opener():
    gen = T.chat_catalog()["items"]
    assert not T.fits(gen["gen.ai_society"], "A2") and T.fits(gen["gen.ai_society"], "B2")
    assert T.opener(gen["gen.trip"], "A2") == gen["gen.trip"]["q_easy"]
    assert T.opener(gen["gen.trip"], "B2") == gen["gen.trip"]["q"]
    assert T.opener(gen["med.rp.chest_pain"], "A1") == gen["med.rp.chest_pain"]["opener_easy"]


def test_reroll_and_history_avoid_repeats_within_category(repo):
    pid = repo.create_profile("ann")
    a = T.suggest(repo, pid, 3, seed=1, category="technical", level="B1")
    b = T.suggest(repo, pid, 3, seed=2, category="technical", level="B1", exclude={t["id"] for t in a})
    assert not {t["id"] for t in a} & {t["id"] for t in b}
    seen = set()
    for _ in range(4):                                      # kolejne rozmowy nie powtarzają tematu
        t = T.suggest(repo, pid, 1, category="medical", level="B1", mode="roleplay")[0]
        assert t["id"] not in seen
        seen.add(t["id"])
        QC.start(repo, pid, t, mode="roleplay")


# --- poziom ---
def test_auto_level_without_diagnosis_is_cautious_and_says_so(repo):
    pid = repo.create_profile("ann")
    lv, src, note = QC.resolve_level(repo, pid, "auto")
    assert (lv, src) == ("A2", "default") and "możesz wybrać poziom ręcznie" in note


def test_auto_level_uses_latest_placement_lower_area(repo):
    pid = repo.create_profile("ann")
    repo.add_competence(pid, "grammar", "A2", 0.0, 1.0, 5, "placement", measured_at="2026-01-01T00:00:00Z")
    repo.add_competence(pid, "grammar", "B2", 0.0, 1.0, 5, "placement", measured_at="2026-02-01T00:00:00Z")
    repo.add_competence(pid, "vocabulary", "B1", 0.0, 1.0, 5, "placement", measured_at="2026-02-01T00:00:00Z")
    assert QC.resolve_level(repo, pid, "auto")[:2] == ("B1", "placement")


@pytest.mark.parametrize("level", T.LEVELS)
def test_manual_level_changes_prompt_not_diagnosis(repo, level):
    pid = repo.create_profile("ann")
    assert QC.resolve_level(repo, pid, level)[:2] == (level, "manual")
    p = QC.system_prompt(T.get("gen.trip"), level, "natural")
    assert f"CEFR {level}" in p and "longer answers are welcome" in p
    assert repo.list_competence(pid) == []


# --- tryby i kategorie w prompcie ---
def test_modes_shape_the_prompt():
    t = T.get("biz.meetings")
    assert "natural conversation" in QC.system_prompt(t, "B2", "natural")
    assert "sentence frame" in QC.system_prompt(t, "B2", "guided")
    rp = QC.system_prompt(T.get("med.rp.chest_pain"), "B1", "roleplay")
    assert "You are a 58-year-old man with chest pain" in rp and "Stay in character" in rp
    assert "never present medical recommendations" in rp


def test_custom_topic_in_roleplay_gets_a_generic_role():
    p = QC.system_prompt(T.custom("buying a used car"), "B1", "roleplay")
    assert "fits this situation" in p and "buying a used car" in p


def test_category_notes():
    assert "Technical English" in QC.system_prompt(T.get("it.python"), "B1")
    assert "not clinical training" in QC.system_prompt(T.get("med.shift"), "B1")
    assert "Technical" not in QC.system_prompt(T.get("gen.trip"), "B1")


# --- ustawienia profilu ---
def test_chat_preferences_per_profile(repo):
    a, b = repo.create_profile("a"), repo.create_profile("b")
    ST.update(repo, a, {"chat_level": "B2", "chat_category": "medical", "chat_mode": "roleplay"})
    ea, eb = ST.effective(repo, a), ST.effective(repo, b)
    assert (ea["chat_level"], ea["chat_category"], ea["chat_mode"]) == ("B2", "medical", "roleplay")
    assert (eb["chat_level"], eb["chat_category"], eb["chat_mode"]) == ("auto", "general", "natural")
    with pytest.raises(ST.SettingError):
        ST.update(repo, a, {"chat_mode": "debate"})


# --- CLI: rozmowa od początku do końca ---
def test_cli_medical_roleplay_b1_full_flow(env):
    conv = FakeProvider(chunks=["It started about forty minutes ago. "])
    code, out = env.go(Gated({}, "When did the pain start?", "Could you explain that word, please?", "q"),
                       ["--no-audio", "--chat", "med.rp.chest_pain", "--chat-level", "B1", "--chat-category",
                        "medical", "--chat-mode", "roleplay"], llm=conv, ev=EvalProv())
    text = "\n".join(out)
    assert code == 0
    assert "Ustawienia rozmowy: B1 · Medical English · Roleplay" in text and "Scenariusz: Jesteś ratownikiem" in text
    assert "Tutor: Oh... thank God you're here." in text
    assert "You are a 58-year-old man" in conv.calls[0][0].content and "CEFR B1" in conv.calls[0][0].content
    assert "nie wiedzy ani decyzji klinicznych" in text
    sid = env.repo.list_sessions(env.pid)[0]["id"]
    plan = env.repo.get_session_plan(env.pid, sid)
    assert (plan["level"], plan["level_source"], plan["category"], plan["mode"]) == ("B1", "manual", "medical", "roleplay")
    assert env.repo.conn.execute("SELECT COUNT(*) FROM attempt").fetchone()[0] == 0          # rozmowa ≠ mastery
    assert env.repo.list_skill_states(env.pid) == [] and env.repo.list_competence(env.pid) == []


def test_cli_auto_level_notice_and_topic_change_stays_in_category(env):
    conv = FakeProvider(chunks=["Ok. "])
    code, out = env.go(Gated({}, "hi", "can we change the topic please", "q"),
                       ["--no-audio", "--chat", "it.python", "--chat-category", "technical"], llm=conv, ev=EvalProv())
    text = "\n".join(out)
    assert "Poziom automatyczny: A2" in text and "Ustawienia rozmowy: A2 · Technical English / IT" in text
    plan = env.repo.get_session_plan(env.pid, env.repo.list_sessions(env.pid)[0]["id"])
    assert len(plan["topics"]) == 2 and plan["topic"]["category"] == "technical" and plan["level"] == "A2"


def test_cli_resume_keeps_scenario_level_and_mode(env):
    env.go(Gated({}, "Hello", "q"), ["--no-audio", "--chat", "biz.rp.investor", "--chat-level", "C1",
                                     "--chat-mode", "roleplay"], llm=FakeProvider(chunks=["Go on. "]), ev=EvalProv())
    sid = env.repo.list_sessions(env.pid)[0]["id"]
    env.repo.conn.execute("UPDATE session SET status='paused', ended_at=NULL WHERE id=?", (sid,))
    conv = FakeProvider(chunks=["Right. "])
    code, out = env.go(Gated({}, "We sell software.", "q"), ["--no-audio", "--chat", "biz.rp.investor",
                                                              "--chat-level", "A2"], llm=conv, ev=EvalProv())
    text = "\n".join(out)
    assert "Wznawiam sesję" in text and len(env.repo.list_sessions(env.pid)) == 1
    assert "Ustawienia rozmowy: C1 · Business English · Roleplay" in text            # bez zmiany scenariusza
    assert "angel investor" in conv.calls[0][0].content and "CEFR C1" in conv.calls[0][0].content


def test_cli_custom_category_with_guided_mode(env):
    conv = FakeProvider(chunks=["Sure. "])
    code, out = env.go(Gated({}, "I fix old radios.", "q"), ["--no-audio", "--chat", "repairing old radios",
                                                             "--chat-category", "custom", "--chat-mode", "guided",
                                                             "--chat-level", "B2"], llm=conv, ev=EvalProv())
    text = "\n".join(out)
    assert "Ustawienia rozmowy: B2 · Własny temat · Rozmowa prowadzona" in text
    assert "sentence frame" in conv.calls[0][0].content and "repairing old radios" in conv.calls[0][0].content


def test_roleplay_prompt_drops_always_ask_rule_and_forbids_role_takeover():
    p = QC.system_prompt(T.get("med.rp.chest_pain"), "B1", "roleplay")
    assert "ONE short follow-up" not in p and "you're the professional" in p and "Never take over" in p
    # F7: także zwykła rozmowa nie wymaga pytania w każdej odpowiedzi (schemat pochwała → pytanie)
    assert "ONE short follow-up" not in QC.system_prompt(T.get("gen.trip"), "B1", "natural")


def test_custom_topic_opener_does_not_paste_a_sentence_into_template():
    """Audyt F7 (Qwen3 na żywo): „Let's talk about I like cooking. What do you like or dislike about I like…”."""
    assert T.custom("my job")["q"] == "Let's talk about your job. What do you like or dislike about it?"
    for s in ("I like cooking.", "I'd say remote work has been a mixed blessing for our team."):
        q = T.custom(s)["q"]
        assert "Let's talk about" not in q and s in q
    assert T.custom("What is your favourite film?")["q"] == "What is your favourite film?"
