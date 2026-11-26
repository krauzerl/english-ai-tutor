"""F7 UI: kluczowe interakcje w prawdziwej przeglądarce (Playwright + Chromium), silnik z atrapą modelu.

Pomijane, gdy brak pakietu `playwright` albo przeglądarki. Instalacja: `pip install -e .[browser-tests]`
i `playwright install chromium` (albo zmienna TUTOR_CHROMIUM ze ścieżką do istniejącego Chromium).
Mikrofon NIE jest tu testowany: tryb głosowy wymaga prawdziwego urządzenia (test akceptacyjny użytkownika).
"""
import glob
import os
import re
import threading

import pytest

from tests.test_gui import STATUS, fake_run, xdg  # noqa: F401 - fixture xdg używana przez `site`
from tutor.gui import runner as R
from tutor.gui import server as SV

sync_api = pytest.importorskip("playwright.sync_api")


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
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
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
    pg.site = site
    yield pg
    ctx.close()


def start_profile(pg, name="Ola"):
    pg.goto(pg.site + "/")
    pg.get_by_label("Nazwa nowego profilu").fill(name)
    pg.get_by_role("button", name="Utwórz profil").click()
    sync_api.expect(pg.locator("h1")).to_contain_text(f"Cześć, {name}!")


def end_session(pg):
    pg.locator(".quickbar").get_by_role("button", name="Zakończ").click()
    sync_api.expect(pg.locator("#sstate")).to_have_text("Sesja zakończona", timeout=15000)
    sync_api.expect(pg.locator("#say")).to_be_disabled()


def test_first_run_profile_and_home(page):
    page.goto(page.site + "/")
    sync_api.expect(page.locator("h1")).to_contain_text("Witaj!")
    start_profile(page)
    sync_api.expect(page.locator("#nav .nav-item")).to_have_count(10)
    sync_api.expect(page.get_by_role("button", name="Szybka rozmowa")).to_be_visible()
    sync_api.expect(page.get_by_text("Proponowane zadania")).to_be_visible()
    sync_api.expect(page.get_by_text("Aktualne wyzwania")).to_be_visible()
    assert page.errors == []


def test_every_screen_renders_without_errors(page):
    start_profile(page)
    for route, heading in [("chat", "Quick Chat"), ("lesson", "Lekcje"), ("review", "Powtórki"),
                           ("placement", "Określ poziom"), ("weak", "Słabe strony"), ("exam", "Egzaminy"),
                           ("progress", "Postępy"), ("achievements", "Osiągnięcia"), ("settings", "Ustawienia")]:
        page.goto(f"{page.site}/#/{route}")
        sync_api.expect(page.locator("main h1").first).to_contain_text(heading)
        sync_api.expect(page.locator(f'#nav a[href="#/{route}"]')).to_have_attribute("aria-current", "page")
    assert page.errors == []


def test_quick_chat_custom_topic_turn_and_finish(page):
    start_profile(page)
    page.goto(page.site + "/#/chat")
    sync_api.expect(page.locator(".topic")).to_have_count(4)
    page.get_by_label("Własny temat").fill("football")
    page.get_by_label("Własny temat").press("Enter")
    sync_api.expect(page).to_have_url(re.compile("#/session$"))
    sync_api.expect(page.locator(".msg.tutor").first).to_contain_text("football")
    sync_api.expect(page.locator("#sstate")).to_have_text("Twoja kolej")
    sync_api.expect(page.locator(".tutor-card .mascot")).to_have_attribute("data-state", "turn")
    page.locator("#say").fill("I likes football very much.")
    page.locator("#say").press("Enter")
    sync_api.expect(page.locator(".msg.you")).to_contain_text("I likes football")
    sync_api.expect(page.locator(".msg.tutor")).to_have_count(2, timeout=15000)
    page.get_by_role("button", name="Zmień temat").click()
    sync_api.expect(page.locator(".msg.notice, .msg.info").filter(has_text="temat")).not_to_have_count(0)
    end_session(page)
    assert page.errors == []


def test_reload_reattaches_to_running_session(page):
    start_profile(page)
    page.goto(page.site + "/#/chat")
    page.locator(".topic").first.click()
    sync_api.expect(page.locator(".msg.tutor").first).to_be_visible()
    page.reload()
    sync_api.expect(page).to_have_url(re.compile("#/session$"))
    sync_api.expect(page.locator(".msg.tutor").first).to_be_visible()
    end_session(page)


def test_lesson_mission_map_task_and_pause(page):
    start_profile(page)
    page.goto(page.site + "/#/lesson")
    sync_api.expect(page.locator(".chapter").first).to_contain_text("Rozdział 1")
    n = page.locator(".mission").count()
    assert n >= 10
    page.locator(".mission").first.click()
    sync_api.expect(page.locator(".side .steps")).to_be_visible(timeout=15000)
    sync_api.expect(page.locator(".side").get_by_text("Cel misji")).to_be_visible()
    opts = page.locator(".options .btn")
    if opts.count():
        opts.first.click()
    else:
        page.locator("#say").fill("I don't know")
        page.locator("#say").press("Enter")
    sync_api.expect(page.locator(".msg.you")).to_have_count(1)
    end_session(page)
    page.goto(page.site + "/#/home")
    sync_api.expect(page.get_by_text("Niedokończona sesja")).to_be_visible()
    assert page.errors == []


def test_achievements_collection_and_filter(page):
    start_profile(page)
    page.goto(page.site + "/#/chat")
    page.locator(".topic").first.click()
    sync_api.expect(page.locator(".msg.tutor").first).to_be_visible()
    page.locator("#say").fill("Hello there.")
    page.locator("#say").press("Enter")
    sync_api.expect(page.locator(".msg.tutor")).to_have_count(2, timeout=15000)
    end_session(page)
    page.goto(page.site + "/#/achievements")
    counter = page.locator(".counter strong").inner_text()
    earned, total = map(int, counter.split("/"))
    sync_api.expect(page.locator(".badge-card")).to_have_count(total)
    assert earned >= 1                                   # pierwsza sesja daje odznakę z prawdziwego silnika
    page.get_by_role("button", name="Zdobyte").click()
    sync_api.expect(page.locator(".badge-card")).to_have_count(earned)
    sync_api.expect(page.locator(".badge-card.locked")).to_have_count(0)
    page.get_by_role("button", name="Do zdobycia").click()
    sync_api.expect(page.locator(".badge-card")).to_have_count(total - earned)
    assert page.errors == []


def test_keyboard_and_small_screen(page):
    start_profile(page)
    page.goto(page.site + "/?fresh=1#/home")
    page.locator("main h1").first.wait_for()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "skip"
    page.keyboard.press("Enter")
    page.goto(page.site + "/#/chat")
    page.locator(".topic").first.focus()
    assert page.evaluate("document.activeElement.classList.contains('topic')")
    page.set_viewport_size({"width": 390, "height": 800})
    for route in ("home", "chat", "lesson", "achievements"):
        page.goto(f"{page.site}/#/{route}")
        page.locator("main h1").first.wait_for()
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth + 1"), route
