"""Learning logs (pilot): przebieg nauki i zachowanie nauczyciela do późniejszej analizy. Bez sieci, bez telemetrii.

Źródło prawdy: SQLite. Istniejące tabele (`session`, `turn`, `turn_meta`, `observation`, `observation_review`,
`attempt`, plan sesji) już trzymają dialog, korekty i próby; tu dochodzą tylko zdarzenia, których tam nie było
(STT, błędy wykonania, koniec sesji, zgłoszenia ucznia) — jako wiersze `app_event` (`log.*`, `report.*`) z `session_id`.

Obok bazy, w `<katalog danych>/learning-logs/sessions/p<profil>-session-<sesja>.jsonl`, zapisujemy lustro zdarzeń
BEZ tekstu wypowiedzi (tylko identyfikatory, długości i metadane) — do korelacji i analizy, nie do odtwarzania rozmowy.

Zasady: błąd logowania nigdy nie przerywa lekcji (wszystko w try/except); profil może wyłączyć szczegółowy zapis
(`learning_log=false`) — zgłoszenia ucznia zapisujemy zawsze, bo to jego świadoma akcja. Audio nie jest zapisywane.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

log_ = logging.getLogger(__name__)

FORMAT_VERSION = 1
RETENTION_DAYS = 180                # tylko pliki JSONL; historia nauki w SQLite nie jest kasowana automatycznie
REPORT_KINDS = {
    "wrong_correction": "Ta poprawka jest błędna",
    "missed_error": "Nauczyciel nie zauważył mojego błędu",
    "stt_misheard": "Whisper źle mnie zrozumiał",
    "unclear_explanation": "Wyjaśnienie jest niejasne",
    "wrong_answer_key": "Ćwiczenie ma nieprawidłową odpowiedź",
}
# Pola z tekstem ucznia/nauczyciela: w bazie (prywatnej) zostają, w JSONL tylko ich długość.
TEXT_KEYS = {"text", "original", "corrected", "quote", "note", "utterance", "span", "fix", "response", "error",
             "topic", "expected"}
_VERSION: str | None = None


def app_version() -> str:
    """Wersja pakietu + commit (z `.git/HEAD`, bez uruchamiania gita), np. `0.1.0+3ad26f6`."""
    global _VERSION
    if _VERSION is None:
        v = "0.1.0"
        try:
            from importlib.metadata import version
            v = version("english-ai-tutor")
        except Exception:  # noqa: BLE001
            pass
        try:
            git = Path(__file__).resolve().parents[2] / ".git"
            head = (git / "HEAD").read_text().strip()
            sha = (git / head[5:]).read_text().strip() if head.startswith("ref: ") and (git / head[5:]).exists() \
                else head if not head.startswith("ref: ") else ""
            if not sha and head.startswith("ref: "):          # gałąź tylko w packed-refs
                ref = head[5:]
                sha = next((ln.split()[0] for ln in (git / "packed-refs").read_text().splitlines()
                            if ln.endswith(" " + ref)), "")
            v += f"+{sha[:7]}" if sha else ""
        except Exception:  # noqa: BLE001 - instalacja bez .git
            pass
        _VERSION = v
    return _VERSION


def logs_dir(repo) -> Path | None:
    """`learning-logs/` obok pliku bazy (testy na kopii bazy piszą do swojego katalogu). Baza w pamięci: None."""
    try:
        path = repo.conn.execute("PRAGMA database_list").fetchone()[2]
    except Exception:  # noqa: BLE001
        return None
    return Path(path).parent / "learning-logs" if path else None


def _private(p: Path) -> Path:
    """Katalog 0700 — także każdy pośredni katalog dziennika (`mkdir(parents=True)` nadaje im domyślne 0775)."""
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    chain = (p, *p.parents)
    root = next((i for i, d in enumerate(chain) if d.name == "learning-logs"), 0)   # poza dziennikiem: tylko `p`
    for d in chain[:root + 1]:
        os.chmod(d, 0o700)
    return p


def enabled(repo, pid: int) -> bool:
    try:
        v = repo.get_settings(pid).get("learning_log", True)
    except Exception:  # noqa: BLE001
        return True
    return v not in (False, 0, "false", "0")


def session_file(repo, pid: int, sid: int) -> Path | None:
    d = logs_dir(repo)
    return d / "sessions" / f"p{int(pid)}-session-{int(sid)}.jsonl" if d else None


def _strip(data: dict) -> dict:
    out = {}
    for k, v in data.items():
        if k in TEXT_KEYS and isinstance(v, str):
            out[f"{k}_len"] = len(v)
        elif isinstance(v, (str, int, float, bool)) or v is None:
            out[k] = v
        elif isinstance(v, (list, tuple)) and k not in TEXT_KEYS:
            out[k] = len(v) if k in ("low_probs",) else [x for x in v if isinstance(x, (int, float, bool))]
        elif isinstance(v, dict):
            out[k] = _strip(v)
    return out


def _append(repo, pid: int, sid: int | None, row: dict) -> None:
    if sid is None:
        return
    f = session_file(repo, pid, sid)
    if f is None:
        return
    _private(f.parent)
    line = json.dumps(row, ensure_ascii=False, default=str) + "\n"
    fd = os.open(f, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)   # jedna linia = jeden write: odporne na przerwanie
    try:
        os.write(fd, line.encode())
    finally:
        os.close(fd)


def log(repo, pid: int, kind: str, session_id: int | None = None, *, force: bool = False, **data) -> int | None:
    """Zdarzenie dziennika nauki. Nigdy nie rzuca wyjątku. `force` = zapisz mimo wyłączonego dziennika (zgłoszenia).
    Zwraca id wiersza `app_event` albo None."""
    try:
        if not force and not enabled(repo, pid):
            return None
        data = {k: v for k, v in data.items() if v is not None}
        eid = repo.conn.execute(
            "INSERT INTO app_event(profile_id,kind,data_json,session_id) VALUES (?,?,?,?)",
            (pid, kind, json.dumps({**data, "app": app_version()}, ensure_ascii=False, default=str),
             session_id)).lastrowid
        _append(repo, pid, session_id, {"v": FORMAT_VERSION, "ts": datetime.now(UTC).isoformat(timespec="milliseconds"),
                                        "app": app_version(), "profile": pid, "session": session_id, "event": eid,
                                        "kind": kind, **_strip(data)})
        return eid
    except Exception as e:  # noqa: BLE001 - logowanie nie może zatrzymać nauki
        log_.warning("learning log %s failed: %s", kind, e)
        return None


def session_meta(repo, pid: int, sid: int, **meta) -> None:
    """Wersje komponentów i ustawienia sesji (`session.model_json`); scala z wcześniejszym wpisem (wznowienie)."""
    try:
        row = repo.conn.execute("SELECT model_json FROM session WHERE id=? AND profile_id=?", (sid, pid)).fetchone()
        if row is None:
            return
        cur = json.loads(row[0] or "{}")
        meta = {k: v for k, v in meta.items() if v is not None}
        new = {**cur, **meta, "app": app_version()}
        if cur.get("app") and cur["app"] != new["app"]:
            new["app_history"] = sorted({*cur.get("app_history", []), cur["app"]})
        repo.conn.execute("UPDATE session SET model_json=? WHERE id=? AND profile_id=?",
                          (json.dumps(new, ensure_ascii=False), sid, pid))
        log(repo, pid, "log.session_start", sid, **{k: v for k, v in meta.items() if k != "topic"})
    except Exception as e:  # noqa: BLE001
        log_.warning("session meta failed: %s", e)


def report(repo, pid: int, kind: str, *, session_id: int | None = None, turn_id: int | None = None,
           observation_id: int | None = None, quote: str | None = None, note: str | None = None) -> dict:
    """Zgłoszenie ucznia (problem nauczyciela) z kontekstem. To NIE jest etykieta prawdy — materiał do przeglądu.
    Brak sesji/tury: kontekst z ostatniej sesji profilu (tura ucznia i ostatnia próba ćwiczenia)."""
    if kind not in REPORT_KINDS:
        raise ValueError(f"kind: {', '.join(REPORT_KINDS)}")
    quote = (quote or "").strip()[:500] or None
    note = (note or "").strip()[:1000] or None
    c = repo.conn
    if observation_id is not None:
        o = c.execute("SELECT session_id, turn_id FROM observation WHERE id=? AND profile_id=?",
                      (observation_id, pid)).fetchone()
        if o is None:
            raise ValueError("observation")
        session_id, turn_id = o["session_id"], o["turn_id"]
    if session_id is None:
        s = c.execute("SELECT id FROM session WHERE profile_id=? ORDER BY (status!='ended') DESC, id DESC LIMIT 1",
                      (pid,)).fetchone()
        session_id = s["id"] if s else None
    elif c.execute("SELECT 1 FROM session WHERE id=? AND profile_id=?", (session_id, pid)).fetchone() is None:
        raise ValueError("session")                                 # cudza sesja: odmowa (izolacja profili)
    if turn_id is None and session_id is not None:
        t = c.execute("SELECT id FROM turn WHERE profile_id=? AND session_id=? AND role='user' ORDER BY id DESC"
                      " LIMIT 1", (pid, session_id)).fetchone()
        turn_id = t["id"] if t else None
    att = None
    if kind == "wrong_answer_key" and session_id is not None:
        a = c.execute("SELECT id, item_id, skill_id, correct, response FROM attempt WHERE profile_id=? AND session_id=?"
                      " ORDER BY id DESC LIMIT 1", (pid, session_id)).fetchone()
        att = dict(a) if a else None
    eid = log(repo, pid, f"report.{kind}", session_id, force=True, turn_id=turn_id, observation_id=observation_id,
              attempt_id=att["id"] if att else None, item_id=att["item_id"] if att else None,
              quote=quote, note=note, status="unverified")
    return {"id": eid, "kind": kind, "session_id": session_id, "turn_id": turn_id, "observation_id": observation_id,
            "attempt": att, "status": "unverified"}


def events(repo, pid: int, *, session_id: int | None = None, since: str | None = None,
           prefix: tuple[str, ...] = ("log.", "report.")) -> list[dict]:
    q = "SELECT id, kind, data_json, session_id, created_at FROM app_event WHERE profile_id=?"
    args: list = [pid]
    if session_id is not None:
        q, args = q + " AND session_id=?", [*args, session_id]
    if since:
        q, args = q + " AND created_at>=?", [*args, since]
    out = []
    for r in repo.conn.execute(q + " ORDER BY id", args):
        if r["kind"].startswith(prefix):
            out.append({**dict(r), "data": json.loads(r["data_json"] or "{}")})
    return out


def prune(repo, days: int = RETENTION_DAYS, now: float | None = None) -> int:
    """Usuwa pliki JSONL starsze niż `days` (wg czasu modyfikacji). Baza i raporty zostają. Zwraca liczbę plików."""
    d = logs_dir(repo)
    if d is None or not (d / "sessions").is_dir():
        return 0
    limit, n = (now or time.time()) - days * 86400, 0
    for f in (d / "sessions").glob("p*-session-*.jsonl"):
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
                n += 1
        except OSError:
            pass
    return n


def delete_profile_logs(repo, pid: int, *, db_events: bool = True) -> dict:
    """Usuwa pliki dziennika profilu (JSONL, raporty, eksporty tego profilu) i — opcjonalnie — zdarzenia `log.*`/
    `report.*` z bazy. Historia nauki (sesje, tury, próby, obserwacje) zostaje."""
    files = 0
    d = logs_dir(repo)
    if d is not None and d.is_dir():
        for pat in (f"sessions/p{int(pid)}-session-*.jsonl", f"reports/p{int(pid)}-*.md", f"exports/p{int(pid)}-*/*"):
            for f in d.glob(pat):
                try:
                    f.unlink()
                    files += 1
                except OSError:
                    pass
        for e in d.glob(f"exports/p{int(pid)}-*"):
            try:
                e.rmdir()
            except OSError:
                pass
    rows = 0
    if db_events:
        rows = repo.conn.execute("DELETE FROM app_event WHERE profile_id=? AND (kind LIKE 'log.%' OR kind LIKE "
                                 "'report.%')", (pid,)).rowcount
    return {"files": files, "events": rows}


def since_days(days: int, now: datetime | None = None) -> str:
    return ((now or datetime.now(UTC)) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S")
