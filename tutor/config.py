"""Ścieżki XDG i minimalna konfiguracja (config.toml, 0600 w katalogu 0700)."""
import os
import tomllib
from pathlib import Path

APP = "english-ai-tutor"


def _xdg(var: str, default: str) -> Path:
    return Path(os.environ.get(var) or Path.home() / default) / APP


def db_path() -> Path:
    return _xdg("XDG_DATA_HOME", ".local/share") / "tutor.db"


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
    p = config_path()
    p.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(p.parent, 0o700)
    data = _read()
    if profile_id is None:
        data.pop("last_profile_id", None)
    else:
        data["last_profile_id"] = int(profile_id)
    text = "".join(f"{k} = {int(v)}\n" for k, v in data.items() if isinstance(v, int))
    tmp = p.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(text)
    os.replace(tmp, p)
