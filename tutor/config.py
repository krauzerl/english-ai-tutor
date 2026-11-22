"""Ścieżki XDG i minimalna konfiguracja (config.toml, 0600 w katalogu 0700)."""
import os
import tomllib
from pathlib import Path

APP = "english-ai-tutor"


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default) / APP


def db_path() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "tutor.db"


def data_dir() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share")


def config_path() -> Path:
    return _xdg("XDG_CONFIG_HOME", ".config") / "config.toml"


def _read() -> dict:
    try:
        return tomllib.loads(config_path().read_text())
    except FileNotFoundError:
        return {}


def get_last_profile() -> int | None:
    return _read().get("last_profile_id")


def set_last_profile(profile_id: int | None) -> None:
    """Zmienia tylko linię last_profile_id; reszta pliku (sekcje [llm], [limits]) zostaje."""
    p = config_path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    try:
        lines = p.read_text().splitlines(keepends=True)
    except FileNotFoundError:
        lines = []
    lines = [ln for ln in lines if not ln.lstrip().startswith("last_profile_id")]
    if profile_id is not None:
        lines.insert(0, f"last_profile_id = {int(profile_id)}\n")  # klucze główne przed [sekcjami]
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("".join(lines))
    os.replace(tmp, p)


def raw_config() -> dict:
    return _read()


def gemini_api_key() -> str | None:
    """Zmienna środowiskowa albo ~/.config/english-ai-tutor/.env (poza repozytorium)."""
    if key := os.environ.get("GEMINI_API_KEY"):
        return key
    try:
        for ln in (config_path().parent / ".env").read_text().splitlines():
            k, sep, v = ln.partition("=")
            if sep and k.strip() == "GEMINI_API_KEY" and v.strip().strip("\"'"):
                return v.strip().strip("\"'")
    except FileNotFoundError:
        pass
    return None
