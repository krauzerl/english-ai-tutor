"""Połączenie SQLite: WAL, foreign_keys, migracje wersjonowane, backup, uprawnienia 0600/0700."""
import os
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
LATEST_VERSION = max(int(f.name[:3]) for f in MIGRATIONS_DIR.glob("[0-9][0-9][0-9]_*.sql"))


def _private_dir(p: Path) -> None:
    p.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(p, 0o700)


def _migrations(d: Path) -> list[tuple[int, Path]]:
    found = sorted((int(m.group(1)), f) for f in d.glob("*.sql")
                   if (m := re.match(r"(\d{3})_", f.name)))
    for i, (n, _) in enumerate(found, 1):
        if n != i:
            raise RuntimeError(f"migrations not contiguous at {n}")
    return found


def _backup(conn: sqlite3.Connection, path: Path, version: int) -> None:
    bdir = path.parent / "backups"
    _private_dir(bdir)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    dest = bdir / f"{path.stem}.v{version}.{stamp}.bak"
    old = os.umask(0o077)
    try:
        out = sqlite3.connect(dest)
        with out:
            conn.backup(out)  # spójna kopia także przy aktywnym WAL
        out.close()
    finally:
        os.umask(old)
    os.chmod(dest, 0o600)


def open_db(path: str | Path, migrations_dir: Path = MIGRATIONS_DIR) -> sqlite3.Connection:
    path = Path(path)
    _private_dir(path.parent)
    migs = _migrations(migrations_dir)
    latest = len(migs)
    old = os.umask(0o077)  # plik bazy, -wal, -shm powstają jako 0600
    try:
        conn = sqlite3.connect(path, isolation_level=None)
    finally:
        os.umask(old)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys=ON")
        current = conn.execute("PRAGMA user_version").fetchone()[0]
        if current > latest:
            raise RuntimeError(f"DB version {current} is newer than app ({latest})")
        if current < latest:
            if current > 0:  # istniejąca baza: kopia przed zmianą schematu
                _backup(conn, path, current)
            for n, f in migs[current:]:
                try:
                    sql = f.read_text()
                    conn.executescript(f"BEGIN;\n{sql}\nPRAGMA user_version={n};\nCOMMIT;")
                except Exception:
                    if conn.in_transaction:
                        conn.execute("ROLLBACK")
                    raise
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
    except Exception:
        conn.close()
        raise
    os.chmod(path, 0o600)
    return conn


def student_tables(conn: sqlite3.Connection) -> list[str]:
    """Tabele z kolumną profile_id (poza `profile`), z introspekcji: nowe tabele wchodzą same."""
    names = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
        "ORDER BY name")]
    return [t for t in names if t != "profile"
            and any(c[1] == "profile_id" for c in conn.execute(f"PRAGMA table_info({t})"))]
