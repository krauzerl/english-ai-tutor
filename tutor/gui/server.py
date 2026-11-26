"""Lokalny serwer GUI: `python main.py --gui`. Tylko 127.0.0.1, biblioteka standardowa, bez CDN.

Bezpieczeństwo (aplikacja jednego użytkownika na jego komputerze):
 * nasłuch wyłącznie na 127.0.0.1; nagłówek Host musi wskazywać localhost (ochrona przed DNS rebinding);
 * każde żądanie POST wymaga tokenu z bieżącego uruchomienia (`X-Tutor-Token`) i JSON-a — strona z innej
   domeny nie odczyta tokenu, więc nie wyśle poleceń (CSRF);
 * brak nagłówków CORS; limit rozmiaru treści; argumenty sesji walidowane i budowane z białej listy.
Logika nauki zostaje w `tutor.app` / `tutor.services`; serwer tylko tłumaczy HTTP na wywołania.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import secrets
import sqlite3
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from tutor import config
from tutor.gui.runner import Busy, Runner
from tutor.i18n import localize
from tutor.services.api import ServiceError, TutorAPI
from tutor.store.db import open_db
from tutor.store.repo import Repo

STATIC = Path(__file__).parent / "static"
MAX_BODY = 64 * 1024
MAX_TEXT = 500
KINDS = ("chat", "lesson", "placement", "review", "drill", "exam", "evals", "assessment")


class BadRequest(Exception):
    pass


def system_status(ollama_url: str | None = None) -> dict:
    """Co jest dostępne na tym komputerze — GUI pokazuje tylko obsługiwane opcje."""
    import requests

    from tutor.llm import llm_settings
    s = llm_settings()
    url = ollama_url or s["ollama"].get("url", "http://localhost:11434")
    models, ollama = [], False
    try:
        r = requests.get(url.rstrip("/") + "/api/tags", timeout=2, allow_redirects=False)
        r.raise_for_status()
        models, ollama = sorted(m["name"] for m in r.json().get("models", [])), True
    except Exception:  # noqa: BLE001 - brak Ollamy to stan, nie błąd serwera
        pass
    kdir = config.data_dir() / "models" / "kokoro"
    voices = []
    try:
        import numpy as np
        with np.load(kdir / "voices-v1.0.bin", allow_pickle=False) as z:
            voices = sorted(v for v in z.files if v[:2] in ("af", "am", "bf", "bm"))   # tylko głosy angielskie
    except Exception:  # noqa: BLE001
        pass
    devices, audio_error = [], None
    try:
        from tutor.voice import audio as A
        devices = A.device_names()
    except Exception as e:  # noqa: BLE001 - brak PortAudio/urządzeń: GUI proponuje tryb tekstowy
        audio_error = str(e) or type(e).__name__
    return {"ollama": ollama, "models": models, "roles": {k: v.get("model") for k, v in s["roles"].items()},
            "kokoro": (kdir / "kokoro-v1.0.int8.onnx").exists() and bool(voices), "voices": voices,
            "devices": devices, "audio_error": audio_error}


def chat_choice(src: dict) -> tuple[str, str, str]:
    """Poziom, kategoria i tryb Quick Chat z białej listy (brak = wartości domyślne)."""
    from tutor.app import topics as T
    level = str(src.get("level") or "auto")
    category = str(src.get("category") or "general")
    mode = str(src.get("mode") or "natural")
    if level not in ("auto", *T.LEVELS):
        raise BadRequest("level: auto, A1–C1")
    if category not in T.CATEGORIES:
        raise BadRequest(f"category: {', '.join(T.CATEGORIES)}")
    if mode not in T.MODES:
        raise BadRequest(f"mode: {', '.join(T.MODES)}")
    return level, category, mode


def session_argv(api: TutorAPI, pid: int, kind: str, args: dict) -> list[str]:
    """Białe listy wartości. Wszystkie wartości jako `--opcja=wartość` (tekst ucznia nie stanie się flagą)."""
    from tutor.app import exams as EX
    from tutor.app import quickchat as QC
    from tutor.app import topics as T
    if kind not in KINDS:
        raise BadRequest(f"kind: {', '.join(KINDS)}")
    argv = ["--voice", f"--profile={pid}"]
    if kind == "chat":
        topic = args.get("topic")
        if topic and T.get(topic) is None:
            raise BadRequest("Nieznany temat")
        custom = str(args.get("custom") or "").strip()
        if len(custom) > 80:
            raise BadRequest("Temat: najwyżej 80 znaków")
        value = topic or custom
        if not value or value == "ask":
            raise BadRequest("Wybierz albo wpisz temat")
        argv.append(f"--chat={value}")
        level, category, mode = chat_choice(args)
        argv += [f"--chat-level={level}", f"--chat-category={category}", f"--chat-mode={mode}"]
        if (m := args.get("minutes")) not in (None, ""):
            if int(m) not in QC.MINUTES:
                raise BadRequest(f"minutes: {QC.MINUTES}")
            argv.append(f"--minutes={int(m)}")
    elif kind == "lesson":
        skill = args.get("skill")
        if skill:
            if skill not in api.pack(pid).skills:
                raise BadRequest("Nieznany cel lekcji")
            argv.append(f"--lesson={skill}")
        else:
            argv.append("--lesson")
    elif kind == "placement":
        argv.append("--placement")
    elif kind == "assessment":
        from tutor.app import diagnostic as DG
        areas = args.get("areas") or list(DG.AREAS)
        if not isinstance(areas, list) or not areas or any(a not in DG.AREAS for a in areas):
            raise BadRequest(f"areas: {', '.join(DG.AREAS)}")
        argv.append("--assess=" + ",".join(dict.fromkeys(areas)))
    elif kind == "evals":                                   # dokończenie oczekujących ocen (ten sam silnik co CLI)
        argv.append("--finish-evals")
    elif kind == "review":
        argv.append("--review")
    elif kind == "drill":
        target = str(args.get("target") or "")
        if not ((target.isdigit() and 1 <= int(target) <= 99) or target in api.pack(pid).skills
                or target in api.pack(pid).errors.ids()):
            raise BadRequest("drill: numer wpisu z dziennika, kategoria błędu albo umiejętność")
        argv.append(f"--drill={target}")
    elif kind == "exam":
        path = args.get("path")
        if path not in EX.load_all():
            raise BadRequest("Nieznana ścieżka egzaminacyjna")
        argv.append(f"--exam={path}")
    corr = args.get("correction")
    if corr:
        if corr not in ("summary", "periodic", "intensive"):
            raise BadRequest("correction")
        argv.append(f"--correction={corr}")
    if args.get("text_mode"):
        argv.append("--no-audio")
    return argv


class App:
    def __init__(self, db_path: Path | None = None, runner: Runner | None = None, token: str | None = None,
                 status=system_status):
        self.db_path = db_path or config.db_path()
        self.runner = runner or Runner()
        self.token = token or secrets.token_urlsafe(24)
        self.status = status
        conn = open_db(self.db_path)          # migracje raz, przy starcie
        conn.close()
        self._packs: dict = {}                # pakiety treści (tylko do odczytu) wspólne dla żądań: ~0,7 s każdy

    def api(self) -> tuple[TutorAPI, sqlite3.Connection]:
        conn = open_db(self.db_path)
        api = TutorAPI(Repo(conn))
        api._packs = self._packs              # shortcut: zmiana plików treści wymaga restartu GUI
        return api, conn

    # --- trasy ---
    def get(self, path: str, q: dict) -> object:
        if path == "/api/session/events":
            return self.runner.since(int(q.get("since", 0)))
        if path == "/api/system":
            return self.status()
        api, conn = self.api()
        try:
            if path == "/api/profiles":
                return {"profiles": api.profiles(), "last": config.get_last_profile()}
            pid = int(q.get("pid", 0))
            lang = api._profile(pid)["ui_lang"]
            return localize(self._get(api, path, q, pid), lang)
        finally:
            conn.close()

    def _get(self, api: TutorAPI, path: str, q: dict, pid: int) -> object:
        if path == "/api/home":
            return api.home(pid)
        if path == "/api/topics":
            seed = q.get("seed")
            level, category, mode = chat_choice(q)
            return api.chat_topics(pid, 4, seed=int(seed) if seed not in (None, "") else None,
                                   category=category, level=level, mode=mode)
        if path == "/api/chat_options":
            return api.chat_options(pid)
        if path == "/api/session_feedback":
            return api.session_feedback(pid, int(q.get("sid", 0)))
        if path == "/api/lessons":
            return {"suggestion": api.lesson_suggestion(pid), "catalog": api.lesson_catalog(pid)}
        simple = {"/api/placement": api.placement_info, "/api/progress": api.progress,
                  "/api/assessment": api.assessment,
                  "/api/weakspots": api.weakspots, "/api/achievements": api.achievements,
                  "/api/history": api.history, "/api/exams": api.exam_paths, "/api/settings": api.settings,
                  "/api/chats": api.chat_history}
        if path in simple:
            return simple[path](pid)
        raise LookupError(path)

    def post(self, path: str, body: dict) -> object:
        if path == "/api/session/send":
            text = str(body.get("text", ""))
            if len(text) > MAX_TEXT or "\n" in text:
                raise BadRequest(f"Tekst: jedna linia, najwyżej {MAX_TEXT} znaków")
            self.runner.send(text)
            return {"ok": True}
        if path == "/api/session/stop":
            self.runner.stop()
            return {"ok": True}
        api, conn = self.api()
        try:
            if path == "/api/profiles":
                name = str(body.get("name", "")).strip()
                if not name or len(name) > 40:
                    raise BadRequest("Nazwa profilu: 1–40 znaków")
                p = api.create_profile(name)
                config.set_last_profile(p["id"])
                return p
            pid = int(body.get("pid", 0))
            api._profile(pid)
            if path in ("/api/profiles/reset", "/api/profiles/delete"):
                if self.runner.running:                    # nie ruszamy danych w trakcie żadnej sesji
                    raise BadRequest("Trwa sesja — zakończ ją przed resetem lub usunięciem profilu.")
                op = path.rsplit("/", 1)[-1]
                return api.reset_or_delete(pid, op, str(body.get("confirm", "")), bool(body.get("backup", True)))
            if path == "/api/profiles/select":
                config.set_last_profile(pid)
                return {"ok": True}
            if path == "/api/weakspots/review":
                verdict = str(body.get("verdict", ""))
                if verdict not in ("disputed", "stt_error", "restored"):
                    raise BadRequest("verdict: disputed, stt_error, restored")
                return api.review_observation(pid, int(body.get("observation_id", 0)), verdict)
            if path == "/api/settings":
                ch = body.get("changes")
                if not isinstance(ch, dict):
                    raise BadRequest("changes: obiekt")
                return api.update_settings(pid, ch)
            if path == "/api/session/start":
                kind = str(body.get("kind", ""))
                args = body.get("args") or {}
                argv = session_argv(api, pid, kind, args)
                self.runner.start(argv, kind, lang=api._profile(pid)["ui_lang"])
                if kind == "chat":                       # ostatnie ustawienia rozmowy zapamiętane w profilu
                    level, category, mode = chat_choice(args)
                    api.update_settings(pid, {"chat_level": level, "chat_category": category, "chat_mode": mode})
                return {"ok": True, "kind": kind}
            raise LookupError(path)
        finally:
            conn.close()


def make_handler(app: App, port_ref: list[int]):
    class Handler(BaseHTTPRequestHandler):
        server_version = "Tutor"
        sys_version = ""

        def log_message(self, fmt, *args):  # cicho: bez logowania treści wypowiedzi
            pass

        def _host_ok(self) -> bool:
            host = (self.headers.get("Host") or "").lower()
            return host in {f"127.0.0.1:{port_ref[0]}", f"localhost:{port_ref[0]}"}

        def _send(self, code: int, data: bytes, ctype: str) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
                             "connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def _json(self, code: int, obj) -> None:
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str).encode(), "application/json")

        def _dispatch(self, fn):
            try:
                self._json(200, fn())
            except (BadRequest, ServiceError, Busy, ValueError) as e:
                self._json(400, {"error": str(e)})
            except LookupError:
                self._json(404, {"error": "nie znaleziono"})
            except Exception as e:  # noqa: BLE001 - błąd jednej trasy nie zatrzymuje serwera
                self._json(500, {"error": f"{type(e).__name__}: {e}"})

        def do_GET(self):  # noqa: N802
            if not self._host_ok():
                return self._json(403, {"error": "host"})
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                q = {k: v[0] for k, v in parse_qs(u.query).items()}
                return self._dispatch(lambda: app.get(u.path, q))
            name = "index.html" if u.path in ("/", "/index.html") else u.path.lstrip("/")
            f = (STATIC / name).resolve()
            if not f.is_file() or STATIC.resolve() not in f.parents:
                return self._json(404, {"error": "nie znaleziono"})
            data = f.read_bytes()
            if name == "index.html":
                data = data.replace(b"__TOKEN__", app.token.encode())
            ctype = mimetypes.guess_type(f.name)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype.endswith("javascript"):
                ctype += "; charset=utf-8"
            self._send(200, data, ctype)

        def do_POST(self):  # noqa: N802
            if not self._host_ok():
                return self._json(403, {"error": "host"})
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{port_ref[0]}", f"http://localhost:{port_ref[0]}"):
                return self._json(403, {"error": "origin"})
            if not secrets.compare_digest(self.headers.get("X-Tutor-Token", ""), app.token):
                return self._json(403, {"error": "token"})
            if not (self.headers.get("Content-Type") or "").startswith("application/json"):
                return self._json(415, {"error": "json"})
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                n = -1
            if not 0 <= n <= MAX_BODY:
                return self._json(413, {"error": "rozmiar"})
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
                if not isinstance(body, dict):
                    raise ValueError
            except ValueError:
                return self._json(400, {"error": "niepoprawny JSON"})
            self._dispatch(lambda: app.post(urlparse(self.path).path, body))

        do_PUT = do_DELETE = do_PATCH = lambda self: self._json(405, {"error": "metoda"})  # noqa: E731

    return Handler


def serve(app: App, port: int = 8765) -> ThreadingHTTPServer:
    port_ref = [port]
    httpd = ThreadingHTTPServer(("127.0.0.1", port), make_handler(app, port_ref))
    port_ref[0] = httpd.server_address[1]
    httpd.daemon_threads = True
    return httpd


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="main.py --gui")
    ap.add_argument("--gui", action="store_true")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--no-browser", action="store_true", help="nie otwieraj przeglądarki")
    a = ap.parse_args(argv)
    app = App()
    try:
        httpd = serve(app, a.port)
    except OSError as e:
        print(f"Nie mogę otworzyć portu {a.port} na 127.0.0.1: {e}. Użyj --port INNY.", file=sys.stderr)
        return 1
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    print(f"AI Language Tutor: {url}  (tylko ten komputer; Ctrl+C = zamknij)")
    if not a.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.runner.stop()
        httpd.server_close()
    return 0
