"""Reset postępów i usunięcie profilu (F7). Obie operacje: jednoznaczne potwierdzenie (nazwa profilu), domyślnie
kopia zapasowa (eksport JSON), tylko wybrany profil, odmowa przy trwającej sesji tego profilu.

* reset postępów — zostaje profil, jego ustawienia (`profile`, `profile_setting`) i licznik kosztów API
  (`llm_usage`, limity budżetu); znika cała historia nauki, wyniki, dziennik, osiągnięcia;
* usunięcie profilu — profil i wszystkie jego dane (kaskada FK).
"""
from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path

from tutor import config

KEEP_ON_RESET = {"profile_setting", "llm_usage"}


class ProfileOpError(ValueError):
    pass


def _check(repo, pid: int, confirm_name: str) -> dict:
    p = repo.get_profile(pid)
    if p is None:
        raise ProfileOpError("Brak profilu")
    if (confirm_name or "").strip().casefold() != p["name"].strip().casefold():
        raise ProfileOpError("Potwierdzenie: wpisz dokładnie nazwę profilu")
    if repo.conn.execute("SELECT 1 FROM session WHERE profile_id=? AND status='active'", (pid,)).fetchone():
        raise ProfileOpError("Profil ma trwającą sesję — zakończ ją najpierw")
    return p


def backup(repo, pid: int, directory: Path | None = None) -> Path:
    """Eksport JSON profilu do katalogu kopii (pliki 0600). Zwraca ścieżkę."""
    d = directory or (config.data_dir() / "backups")
    d.mkdir(parents=True, exist_ok=True)
    os.chmod(d, 0o700)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    path = d / f"profile-{pid}-{stamp}.json"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(repo.export_profile(pid), f, ensure_ascii=False, indent=1, default=str)
    return path


def reset_progress(repo, pid: int, confirm_name: str, *, make_backup: bool = True,
                   directory: Path | None = None) -> dict:
    _check(repo, pid, confirm_name)
    path = backup(repo, pid, directory) if make_backup else None
    removed = {}
    with repo.transaction():
        for t in repo.student_tables():
            if t in KEEP_ON_RESET:
                continue
            removed[t] = repo.conn.execute(f"DELETE FROM {t} WHERE profile_id=?", (pid,)).rowcount  # noqa: S608
    _drop_log_files(repo, pid)
    return {"backup": str(path) if path else None, "removed": removed}


def delete(repo, pid: int, confirm_name: str, *, make_backup: bool = True, directory: Path | None = None) -> dict:
    p = _check(repo, pid, confirm_name)
    path = backup(repo, pid, directory) if make_backup else None
    from tutor.llm import keystore
    keystore.delete(repo, pid)                        # klucz API profilu z magazynu sekretów (przed usunięciem ref)
    with repo.transaction():
        repo.delete_profile(pid)
    _drop_log_files(repo, pid)
    if config.get_last_profile() == pid:
        config.set_last_profile(None)
    return {"backup": str(path) if path else None, "deleted": p["name"]}


def _drop_log_files(repo, pid: int) -> None:
    """Pliki dziennika nauki profilu (JSONL, raporty, eksporty) idą razem z jego danymi w bazie."""
    from tutor.app import learnlog as LL
    try:
        LL.delete_profile_logs(repo, pid, db_events=False)
    except Exception:  # noqa: BLE001 - brak plików/uprawnień nie cofa usunięcia z bazy
        pass
