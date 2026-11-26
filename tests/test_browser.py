"""F7 UI: główne przepływy w prawdziwej przeglądarce (Playwright + Chromium), silnik z atrapą modelu.

Pomijane, gdy brak pakietu `playwright` albo przeglądarki. Instalacja: `pip install -e .[browser-tests]`
i `playwright install chromium` (albo zmienna TUTOR_CHROMIUM ze ścieżką do istniejącego Chromium).
Mikrofon NIE jest tu testowany: tryb głosowy wymaga prawdziwego urządzenia (test akceptacyjny użytkownika).
CSP strony blokuje `eval`, więc czekamy przez lokatory (`expect`), nie przez `wait_for_function`.
"""
import glob
import os
import re
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from tests.test_gui import STATUS, fake_run, xdg  # noqa: F401 - fixture xdg używana przez `site`
from tutor import config
from tutor.gui import runner as R
from tutor.gui import server as SV
from tutor.voice import cli

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect


def _launch(p):
    paths = [os.environ.get("TUTOR_CHROMIUM")] + sorted(glob.glob(os.path.expanduser(
        "~/.cache/ms-playwright/chromium-*/chrome-linux64/chrome")), reverse=True)
    try:
        return p.chromium.launch()
    except Exception:  # noqa: BLE001 - brak przeglądarki w domyślnym miejscu Playwright
        for exe in filter(None, paths):
            if os.path.exists(exe):
                return p.chromium.launch(executable_path=exe)
    pytest.skip("brak Chromium dla Playwright")


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        b = _launch(p)
        yield b
        b.close()


@pytest.fixture
def site(xdg):  # noqa: F811
    app = SV.App(runner=R.Runner(run=fake_run), token="T0K", status=lambda: STATUS)
    httpd = SV.serve(app, 0)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield SimpleNamespace(url=f"http://127.0.0.1:{httpd.server_address[1]}", app=app)
    app.runner.stop()
    httpd.shutdown()
    httpd.server_close()


@pytest.fixture
def page(browser, site):
    ctx = browser.new_context(viewport={"width": 1366, "height": 860})
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    pg.on("console", lambda m: m.type == "error" and pg.errors.append(m.text))
    pg.site = site.url
    pg.app = site.app
    yield pg
    ctx.close()


def start_profile(pg, name="Ola"):
    pg.goto(pg.site + "/")
    pg.get_by_label("Nazwa nowego profilu").fill(name)
    pg.get_by_role("button", name="Utwórz profil").click()
    expect(pg.locator("main h1")).to_contain_text(f"Cześć, {name}!")


def end_session(pg):
    pg.locator("#stage").get_by_role("button", name=re.compile("Zakończ rozmowę|Przerwij i zapisz")).click()
    expect(pg.locator("#sstate")).to_have_text("Sesja zakończona", timeout=15000)
    expect(pg.locator("#say")).to_be_disabled()


def chat_with_custom(pg, topic="football"):
    pg.goto(pg.site + "/#/chat")
    pg.get_by_label("Własny temat").fill(topic)
    pg.get_by_label("Własny temat").press("Enter")
    expect(pg).to_have_url(re.compile("#/session$"))
    expect(pg.locator(".msg.tutor").first).to_contain_text(topic)
    expect(pg.locator("#sstate")).to_have_text("Twoja kolej")


def say(pg, text, tutor_count):
    pg.locator("#say").fill(text)
    pg.locator("#say").press("Enter")
    expect(pg.locator(".msg.tutor")).to_have_count(tutor_count, timeout=15000)


# --- profile ---

def test_first_run_profile_and_home_priorities(page):
    page.goto(page.site + "/")
    expect(page.locator("main h1")).to_contain_text("Witaj!")
    start_profile(page)
    expect(page.locator("#nav .nav-item")).to_have_count(10)
    actions = page.locator(".actions-4 .action")
    expect(actions).to_have_count(4)
    for i, word in enumerate(["Rozmowa", "Nauka", "Powtórka", "Postępy"]):
        expect(actions.nth(i)).to_contain_text(word)
    expect(page.locator(".profile-chip")).to_contain_text("Ola")
    assert page.errors == []


def test_switch_profile_keeps_data_separate(page):
    start_profile(page, "Ola")
    chat_with_custom(page)
    say(page, "I like football.", 2)
    end_session(page)
    page.goto(page.site + "/#/profiles")
    page.get_by_label("Nazwa nowego profilu").fill("Bob")
    page.get_by_role("button", name="Utwórz profil").click()
    expect(page.locator("main h1")).to_contain_text("Cześć, Bob!")
    expect(page.get_by_text("Jeszcze nic — pierwsza rozmowa")).to_be_visible()
    page.goto(page.site + "/#/profiles")
    page.locator(".profile-card", has_text="Ola").click()
    expect(page.locator("main h1")).to_contain_text("Cześć, Ola!")
    expect(page.locator(".mini-list").last).to_contain_text("Quick Chat")
    assert page.errors == []


def test_every_screen_renders_without_errors(page):
    start_profile(page)
    for route, heading in [("chat", "Quick Chat"), ("lesson", "Lekcje"), ("review", "Powtórki"),
                           ("placement", "Diagnoza"), ("weak", "Słabe strony"), ("exam", "Egzaminy"),
                           ("progress", "Postępy"), ("achievements", "Osiągnięcia"), ("settings", "Ustawienia"),
                           ("profiles", "Profile")]:
        page.goto(f"{page.site}/#/{route}")
        expect(page.locator("main h1").first).to_contain_text(heading)
        if route != "profiles":
            expect(page.locator(f'#nav a[href="#/{route}"]')).to_have_attribute("aria-current", "page")
    assert page.errors == []


# --- Quick Chat ---

def test_quick_chat_turns_named_topic_change_and_finish(page):
    start_profile(page)
    chat_with_custom(page)
    expect(page.locator(".stage .mascot")).to_have_attribute("data-state", "idle")
    say(page, "I likes football very much.", 2)
    expect(page.locator(".msg.you")).to_contain_text("I likes football")
    say(page, "Can we talk about something else? Maybe travel.", 3)
    expect(page.locator(".msg.notice", has_text="nowy temat: travel")).to_be_visible()
    expect(page.locator("#topicnow")).to_contain_text("travel")
    page.locator(".stage").get_by_role("button", name="Zmień temat").click()
    expect(page.locator(".msg.notice")).to_have_count(2, timeout=15000)
    end_session(page)
    assert page.locator(".msg.info", has_text="[Enter]").count() == 0       # instrukcje CLI nie trafiają do rozmowy
    assert page.errors == []


def test_layout_rebuild_keeps_transcript(page):
    start_profile(page)
    chat_with_custom(page)
    say(page, "I like football.", 2)
    page.evaluate("() => route()")                       # ten sam mechanizm co przejście lekcji w rozmowę
    expect(page.locator(".msg.tutor")).to_have_count(2)
    expect(page.locator(".msg.you")).to_have_count(1)
    end_session(page)


def test_reload_reattaches_to_running_session(page):
    start_profile(page)
    page.goto(page.site + "/#/chat")
    page.locator(".topic").first.click()
    expect(page.locator(".msg.tutor").first).to_be_visible()
    page.reload()
    expect(page).to_have_url(re.compile("#/session$"))
    expect(page.locator(".msg.tutor").first).to_be_visible()
    end_session(page)


def test_ollama_down_shows_clear_problem(page, monkeypatch):
    page.app.runner._run = lambda argv, **kw: cli.run(argv, **kw)          # prawdziwy dostawca, Ollama „nie działa”
    monkeypatch.setattr("tutor.llm.ollama.OllamaProvider.health", lambda self: False)
    start_profile(page)
    page.goto(page.site + "/#/chat")
    page.locator(".topic").first.click()
    expect(page.locator("#sstate")).to_have_text("Problem", timeout=15000)
    expect(page.locator(".msg.error")).to_contain_text("ollama serve")
    expect(page.locator("#next")).to_contain_text("Ollama")
    expect(page.get_by_role("button", name="Na start")).to_be_visible()


# --- lekcje, powtórki, diagnoza ---

def test_lesson_task_pause_and_resume(page):
    start_profile(page)
    page.goto(page.site + "/#/lesson")
    expect(page.locator(".chapter").first).to_contain_text("Rozdział 1")
    assert page.locator(".mission").count() >= 10
    page.locator(".mission").first.click()
    expect(page.locator(".task-card .stem")).not_to_contain_text("Pierwsze zadanie", timeout=15000)
    expect(page.locator(".mission-bar .steps")).to_be_visible()
    expect(page.locator("#now")).to_contain_text(re.compile("Wybierz|Napisz|Odpowiedz"))
    expect(page.locator("#explainbox details")).to_be_visible()
    opts = page.locator(".options .btn")
    if opts.count():
        opts.first.click()
    else:
        page.locator("#say").fill("I don't know")
        page.locator("#say").press("Enter")
    expect(page.locator("#verdict .verdict")).not_to_have_count(0, timeout=15000)
    end_session(page)
    page.goto(page.site + "/#/home")
    resume = page.locator(".action", has_text="Wróć do lekcji")
    expect(resume).to_be_visible()
    resume.click()
    expect(page.locator(".task-card .stem")).not_to_contain_text("Pierwsze zadanie", timeout=15000)
    expect(page.locator(".msg.info", has_text="Wznawiam")).to_have_count(1)
    end_session(page)
    assert page.errors == []


def test_review_flow_when_due(page):
    from fsrs import Rating

    from tutor.pedagogy import content as C
    from tutor.pedagogy import srs
    from tutor.store.db import open_db
    from tutor.store.repo import Repo
    start_profile(page)
    repo = Repo(open_db(config.db_path()))
    pid = repo.conn.execute("select id from profile").fetchone()[0]
    cj, _ = srs.review(None, Rating.Good, datetime(2026, 1, 1, tzinfo=UTC), C.load("en").rubric)
    repo.put_card(pid, "skill_check", "en.gram.articles_basic", cj, "2026-01-02T00:00:00Z")
    repo.conn.close()
    page.goto(page.site + "/#/review")
    expect(page.get_by_text("Do powtórki dziś: 1")).to_be_visible()
    page.get_by_role("button", name="Zacznij powtórki").click()
    expect(page.locator(".mission-bar h1")).to_have_text("Powtórki")
    expect(page.locator(".task-card .stem")).not_to_contain_text("Pierwsze zadanie", timeout=15000)
    end_session(page)


def test_placement_start_and_pause(page):
    start_profile(page)
    page.goto(page.site + "/#/placement")
    page.get_by_role("button", name="Zacznij szybkie dopasowanie").click()
    expect(page.locator(".mission-bar h1")).to_have_text("Szybkie dopasowanie")
    expect(page.locator(".task-card .stem")).not_to_contain_text("Pierwsze zadanie", timeout=15000)
    expect(page.locator(".coach").get_by_role("button", name="Podpowiedź")).to_have_count(0)   # w diagnozie bez podpowiedzi
    end_session(page)
    page.goto(page.site + "/#/home")
    expect(page.locator(".action", has_text="Wróć do sprawdzania poziomu")).to_be_visible()


# --- dzienniki i ustawienia ---

def test_weakspots_progress_achievements_settings(page):
    start_profile(page)
    chat_with_custom(page)
    say(page, "Hello there.", 2)
    end_session(page)
    page.goto(page.site + "/#/weak")
    expect(page.locator("main h1")).to_contain_text("Słabe strony")
    page.goto(page.site + "/#/progress")
    expect(page.locator(".stat", has_text="Sesje")).to_contain_text("1")
    expect(page.locator("table.grid").last).to_contain_text("Quick Chat")
    page.goto(page.site + "/#/achievements")
    earned, total = map(int, page.locator(".counter strong").inner_text().split("/"))
    expect(page.locator(".badge-card")).to_have_count(total)
    assert earned >= 1                                   # pierwsza sesja daje odznakę z prawdziwego silnika
    page.get_by_role("button", name="Zdobyte").click()
    expect(page.locator(".badge-card")).to_have_count(earned)
    page.get_by_role("button", name="Do zdobycia").click()
    expect(page.locator(".badge-card.locked")).to_have_count(total - earned)
    page.get_by_role("button", name="Sekrety").click()
    expect(page.locator(".badge-card")).to_have_count(50)                           # 50 ukrytych
    expect(page.locator(".badge-card.secret").first).to_contain_text("???")
    page.get_by_role("button", name="Wszystkie").click()
    page.get_by_label("Szukaj odznaki…").fill("Trzy dni")
    expect(page.locator(".badge-card").first).to_contain_text("Trzy dni z rzędu")
    assert total >= 150
    page.goto(page.site + "/#/settings")
    page.get_by_label("Tempo mowy").select_option("slow")
    page.get_by_role("button", name="Zapisz ustawienia").click()
    expect(page.locator("#toast")).to_have_text("Zapisano ustawienia.")
    page.reload()
    expect(page.get_by_label("Tempo mowy")).to_have_value("slow")
    assert page.errors == []


# --- dostępność i rozdzielczości ---

def test_keyboard_skip_link_and_focus(page):
    start_profile(page)
    page.goto(page.site + "/?fresh=1#/home")
    page.locator("main h1").first.wait_for()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "skip"
    page.goto(page.site + "/#/chat")
    page.locator(".topic").first.focus()
    assert page.evaluate("document.activeElement.classList.contains('topic')")


@pytest.mark.parametrize("w,h", [(1280, 720), (1366, 768), (1440, 900), (1920, 1080)])
def test_session_controls_visible_without_scrolling(page, w, h):
    start_profile(page)
    page.set_viewport_size({"width": w, "height": h})
    chat_with_custom(page)
    for name in ("Wyślij", "Zakończ rozmowę", "Zmień temat"):
        box = page.get_by_role("button", name=name).bounding_box()
        assert box and box["y"] + box["height"] <= h, (name, w, h)
    end_session(page)
    page.goto(page.site + "/#/lesson")
    page.locator(".mission").first.click()
    expect(page.locator(".task-card .stem")).not_to_contain_text("Pierwsze zadanie", timeout=15000)
    for loc in (page.locator("#say"), page.locator(".answer").get_by_role("button", name="Wyślij"),
                page.get_by_role("button", name="Przerwij i zapisz")):
        box = loc.bounding_box()
        assert box and box["y"] + box["height"] <= h, (w, h)
    end_session(page)


def test_phone_width_has_no_horizontal_scroll(page):
    start_profile(page)
    page.set_viewport_size({"width": 390, "height": 800})
    for route in ("home", "chat", "lesson", "achievements", "progress", "settings"):
        page.goto(f"{page.site}/#/{route}")
        page.locator("main h1").first.wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), route


# --- Quick Chat: poziom, kategoria, tryb ---

def test_medical_roleplay_b1_from_setup_to_feedback_and_prefs_remembered(page):
    start_profile(page)
    page.goto(page.site + "/#/chat")
    expect(page.get_by_text("Poziom automatyczny: A2")).to_be_visible()
    page.get_by_role("group", name="Poziom").get_by_role("button", name="B1").click()
    page.locator(".choice", has_text="Medical English").click()
    page.get_by_role("group", name="Tryb rozmowy").get_by_role("button", name="Roleplay").click()
    expect(page.locator(".topic").first).to_contain_text("Roleplay")
    assert page.locator(".topic", has_text="Plan działań w zespole").count() == 0     # B2–C1: nie dla B1
    page.get_by_role("button", name="Rozpocznij rozmowę").click()
    expect(page.locator(".msg.scenario")).to_contain_text("Nauczyciel gra")
    expect(page.locator("#topicnow")).to_contain_text("B1 · Medical English · Roleplay")
    say(page, "Hello, I am a paramedic. Where does it hurt?", 2)
    page.locator(".stage").get_by_role("button", name="Zmień temat").click()
    expect(page.locator(".msg.notice", has_text="nowy temat")).to_be_visible(timeout=15000)
    expect(page.locator("#topicnow")).to_contain_text("Medical English")
    end_session(page)
    expect(page.locator(".msg.info", has_text="nie wiedzy ani decyzji klinicznych")).to_be_visible()
    page.goto(page.site + "/#/chat")
    expect(page.get_by_role("group", name="Poziom").get_by_role("button", name="B1")).to_have_attribute("aria-pressed", "true")
    expect(page.locator(".choice", has_text="Medical English")).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_role("group", name="Tryb rozmowy").get_by_role("button", name="Roleplay")).to_have_attribute(
        "aria-pressed", "true")
    assert page.errors == []


@pytest.mark.parametrize("cat,word", [("Technical English", "Technical"), ("Business English", "Business"),
                                      ("Professional Situations", "Professional"), ("General English", "General")])
def test_category_and_guided_mode_start(page, cat, word):
    start_profile(page)
    page.goto(page.site + "/#/chat")
    page.locator(".choice", has_text=cat).click()
    page.get_by_role("group", name="Tryb rozmowy").get_by_role("button", name="Rozmowa prowadzona").click()
    page.get_by_role("button", name="Rozpocznij rozmowę").click()
    expect(page.locator("#topicnow")).to_contain_text(f"{word}")
    expect(page.locator("#topicnow")).to_contain_text("Rozmowa prowadzona")
    end_session(page)


def test_custom_category_requires_own_topic(page):
    start_profile(page)
    page.goto(page.site + "/#/chat")
    page.locator(".choice", has_text="Custom Topic").click()
    page.get_by_role("button", name="Rozpocznij rozmowę").click()
    expect(page.locator("#toast")).to_have_text("Wpisz temat.")
    page.get_by_label("Własny temat").fill("restoring old motorbikes")
    page.get_by_role("button", name="Rozpocznij rozmowę").click()
    expect(page.locator("#topicnow")).to_contain_text("restoring old motorbikes")
    expect(page.locator("#topicnow")).to_contain_text("Własny temat")
    end_session(page)


def test_full_assessment_screen_and_start(page):
    start_profile(page)
    page.goto(page.site + "/#/placement")
    expect(page.locator("main h1").first).to_contain_text("Diagnoza")
    expect(page.get_by_text("nie oficjalny poziom CEFR").first).to_be_visible()
    page.get_by_role("button", name="Zacznij diagnozę").click()
    expect(page.locator(".mission-bar h1")).to_have_text("Diagnoza")
    end_session(page)
    assert page.errors == []


def test_interface_language_switch_to_english(page):
    start_profile(page)
    page.goto(page.site + "/#/settings")
    page.get_by_label("Język interfejsu").select_option("en")
    page.get_by_role("button", name="Zapisz ustawienia").click()
    expect(page.get_by_role("link", name="Progress")).to_be_visible()          # przeładowanie w EN
    for route, heading in (("home", "Hi, Ola!"), ("placement", "Assessment"), ("progress", "Progress"),
                           ("weak", "Weak spots"), ("settings", "Settings")):
        page.goto(page.site + "/#/" + route)
        expect(page.locator("main h1").first).to_contain_text(heading)
    page.goto(page.site + "/#/progress")
    expect(page.get_by_text("Am I really improving?")).to_be_visible()
    assert page.evaluate("[...I18N.missing]") == [] and page.errors == []
    page.get_by_role("link", name="Settings").click()
    page.get_by_label("Interface language").select_option("pl")
    page.get_by_role("button", name="Save settings").click()
    expect(page.get_by_role("link", name="Postępy")).to_be_visible()
