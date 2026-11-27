"""Klucze API per profil: systemowy magazyn sekretów (Secret Service przez `keyring`), a gdy go brak — tylko pamięć
bieżącego uruchomienia. Nigdy SQLite, JSON ani config.toml.

Identyfikator sekretu: losowy `secret_ref` zapisany w ustawieniach profilu (nie nazwa profilu, nie numer — numer
mógłby trafić do nowego profilu po usunięciu starego). Klucz nie wraca do interfejsu; `status()` mówi tylko, czy jest.
Procesy sesji (GUI uruchamia je w tym samym procesie, w wątku) czytają klucz stąd.
"""
from __future__ import annotations

import logging
import secrets
import threading

log = logging.getLogger("tutor.llm")
SERVICE = "english-ai-tutor"
REF_SETTING = "secret_ref"
_memory: dict[str, str] = {}
_lock = threading.Lock()


def _backend():
    """Trwały magazyn albo None (brak pakietu, brak Secret Service, backend „fail”/plaintext)."""
    try:
        import keyring
        from keyring.backends import fail
        kr = keyring.get_keyring()
    except Exception:  # noqa: BLE001 - brak pakietu/D-Bus = brak trwałego magazynu
        return None
    if isinstance(kr, fail.Keyring) or getattr(kr, "priority", 0) < 1:
        return None
    if "plaintext" in type(kr).__module__.lower() or "PlaintextKeyring" in type(kr).__name__:
        return None                                    # keyrings.alt zapisuje jawnym tekstem: nie używamy
    return kr


def persistent_available() -> bool:
    return _backend() is not None


def _ref(repo, pid: int, create: bool = False) -> str | None:
    ref = repo.get_settings(pid).get(REF_SETTING)
    if ref or not create:
        return ref
    ref = secrets.token_hex(16)
    repo.set_setting(pid, REF_SETTING, ref)
    return ref


def _user(ref: str, provider: str) -> str:
    return f"{provider}:{ref}"


def save(repo, pid: int, key: str, provider: str = "gemini", *, persist: bool = True) -> str:
    """Zapisuje (zastępuje) klucz profilu. Zwraca 'keyring' albo 'memory'. Klucz bez spacji, ≤ 200 znaków."""
    key = (key or "").strip()
    if not key or len(key) > 200 or any(c.isspace() for c in key):
        raise ValueError("Klucz API: wklej sam klucz (bez spacji, najwyżej 200 znaków).")
    ref = _ref(repo, pid, create=True)
    kr = _backend() if persist else None
    with _lock:
        _memory.pop(_user(ref, provider), None)
        if kr is not None:
            try:
                kr.set_password(SERVICE, _user(ref, provider), key)
                return "keyring"
            except Exception as e:  # noqa: BLE001 - zablokowany portfel itp.: tylko pamięć
                log.warning("keyring save failed %s", type(e).__name__)
        _memory[_user(ref, provider)] = key
    return "memory"


def get(repo, pid: int, provider: str = "gemini") -> str | None:
    ref = _ref(repo, pid)
    if not ref:
        return None
    with _lock:
        if (k := _memory.get(_user(ref, provider))) is not None:
            return k
    kr = _backend()
    if kr is None:
        return None
    try:
        return kr.get_password(SERVICE, _user(ref, provider))
    except Exception as e:  # noqa: BLE001
        log.warning("keyring read failed %s", type(e).__name__)
        return None


def status(repo, pid: int, provider: str = "gemini") -> str | None:
    """'memory' | 'keyring' | None — bez zwracania klucza."""
    ref = _ref(repo, pid)
    if not ref:
        return None
    with _lock:
        if _user(ref, provider) in _memory:
            return "memory"
    return "keyring" if get(repo, pid, provider) else None


def delete(repo, pid: int, provider: str = "gemini") -> None:
    ref = _ref(repo, pid)
    if not ref:
        return
    with _lock:
        _memory.pop(_user(ref, provider), None)
    kr = _backend()
    if kr is not None:
        try:
            kr.delete_password(SERVICE, _user(ref, provider))
        except Exception:  # noqa: BLE001, S110 - brak wpisu = już usunięty
            pass
