"""T-DB: migracje, PRAGMA, backup, uprawnienia, trwałość."""
import os
import sqlite3
import stat

import pytest

from tutor.store.db import LATEST_VERSION, open_db


def mode(p):
    return stat.S_IMODE(os.stat(p).st_mode)


def test_t_db_2_pragmas(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"


def test_t_db_1_fresh_db_migrated_no_backup(tmp_path):
    p = tmp_path / "tutor.db"
    c = open_db(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
    assert not (tmp_path / "backups").exists()
    c.close()


def _migs(tmp_path, n):
    d = tmp_path / "migs"
    d.mkdir()
    (d / "001_a.sql").write_text("CREATE TABLE a(x);")
    if n >= 2:
        (d / "002_b.sql").write_text("CREATE TABLE b(y); INSERT INTO a VALUES (1);")
    return d


def test_t_db_1_upgrade_n_minus_1_creates_backup(tmp_path):
    p = tmp_path / "tutor.db"
    open_db(p, migrations_dir=_migs(tmp_path, 1)).close()
    d2 = tmp_path / "migs2"
    d2.mkdir()
    for f in (tmp_path / "migs").iterdir():
        (d2 / f.name).write_text(f.read_text())
    (d2 / "002_b.sql").write_text("CREATE TABLE b(y); INSERT INTO a VALUES (1);")
    c = open_db(p, migrations_dir=d2)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 2
    assert c.execute("SELECT x FROM a").fetchone()[0] == 1
    backups = list((tmp_path / "backups").iterdir())
    assert len(backups) == 1
    b = sqlite3.connect(backups[0])
    assert b.execute("PRAGMA user_version").fetchone()[0] == 1
    assert b.execute("SELECT name FROM sqlite_master WHERE name='b'").fetchone() is None
    assert mode(backups[0]) == 0o600
    assert mode(tmp_path / "backups") == 0o700


def test_failed_migration_rolls_back(tmp_path):
    p = tmp_path / "tutor.db"
    d = _migs(tmp_path, 1)
    open_db(p, migrations_dir=d).close()
    (d / "002_bad.sql").write_text("CREATE TABLE b(y); SELECT * FROM nope;")
    with pytest.raises(sqlite3.Error):
        open_db(p, migrations_dir=d)
    c = sqlite3.connect(p)
    assert c.execute("PRAGMA user_version").fetchone()[0] == 1
    assert c.execute("SELECT name FROM sqlite_master WHERE name='b'").fetchone() is None


def test_db_newer_than_code_refused(tmp_path):
    p = tmp_path / "tutor.db"
    open_db(p).close()
    c = sqlite3.connect(p)
    c.execute(f"PRAGMA user_version={LATEST_VERSION + 5}")
    c.close()
    with pytest.raises(RuntimeError):
        open_db(p)


def test_permissions(tmp_path):
    p = tmp_path / "data" / "tutor.db"
    c = open_db(p)
    c.execute("CREATE TABLE IF NOT EXISTS t(x)")
    c.execute("INSERT INTO t VALUES (1)")  # tworzy WAL
    assert mode(p.parent) == 0o700
    for f in p.parent.iterdir():
        assert mode(f) == 0o600, f
    c.close()


def test_persistence_after_reopen(tmp_path):
    p = tmp_path / "tutor.db"
    from tutor.store.repo import Repo

    c = open_db(p)
    r = Repo(c)
    pid = r.create_profile("Ala")
    sid = r.start_session(pid, "lesson", 15)
    r.add_turn(pid, sid, "user", "hello")
    c.close()
    c2 = open_db(p)
    r2 = Repo(c2)
    assert r2.get_profile(pid)["name"] == "Ala"
    assert [t["text"] for t in r2.list_turns(pid, sid)] == ["hello"]
    c2.close()


def test_migration_002_keeps_usage_rows_from_v1(tmp_path):
    """T-DB-1 (realne n-1): baza v1 z wierszem llm_usage przechodzi na v2 bez utraty danych."""
    import shutil

    from tutor.store.db import MIGRATIONS_DIR, open_db
    v1 = tmp_path / "v1"
    v1.mkdir()
    shutil.copy(MIGRATIONS_DIR / "001_init.sql", v1)
    c = open_db(tmp_path / "d" / "t.db", migrations_dir=v1)
    pid = c.execute("INSERT INTO profile(name) VALUES ('A')").lastrowid
    c.execute("INSERT INTO llm_usage(profile_id,provider,model,role,cost_usd) VALUES (?,?,?,?,?)",
              (pid, "gemini", "m", "conversation", 0.5))
    c.close()
    c = open_db(tmp_path / "d" / "t.db")
    assert c.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
    assert c.execute("SELECT cost_usd FROM llm_usage").fetchone()[0] == 0.5
    c.execute("DELETE FROM profile WHERE id=?", (pid,))
    r = c.execute("SELECT profile_id, cost_usd FROM llm_usage").fetchone()
    assert (r[0], r[1]) == (None, 0.5)
    assert list((tmp_path / "d" / "backups").glob("*.bak"))
