"""Ustawienia per profil (personalizacja). Jedno miejsce prawdy: `profile_setting` + istniejące kolumny profilu
(styl korekt, minuty, materiały). Domyślne wartości głosu: `config.toml [voice]`; do pliku nic nie zapisujemy."""
from __future__ import annotations

from tutor import config

LANGS = ("en",)                     # języki z paczką treści
CHAT_MODELS = ("qwen3:8b", "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M")   # obsługiwane i zmierzone (F4.7)
SCHEMA: dict[str, dict] = {
    "target_lang": {"type": "choice", "choices": LANGS, "column": "target_lang"},
    "ui_lang": {"type": "choice", "choices": ("pl", "en"), "column": "ui_lang"},     # F7: język interfejsu
    "mascot": {"type": "choice", "choices": ("A", "B", "C", "classic")},   # F7: koncepcje do wyboru (niezatwierdzone)
    "tts_voice": {"type": "str"},
    "speed": {"type": "float", "min": 0.6, "max": 1.5},
    "correction": {"type": "choice", "choices": ("summary", "periodic", "intensive"), "column": "correction_style"},
    "session_minutes": {"type": "choice", "choices": (15, 30, 45, 60), "column": "daily_minutes"},
    "mic_mode": {"type": "choice", "choices": ("ptt", "auto")},
    "stt_model": {"type": "str"},
    "stt_confirm": {"type": "choice", "choices": ("uncertain", "always", "never")},
    "allow_unreviewed": {"type": "bool", "column": "allow_unreviewed_practice"},
    "conversation_mode": {"type": "choice", "choices": ("quick_chat", "lesson")},
    # F7: model rozmowy (ocena zostaje przy domyślnym Qwen3 — zmiana oceny wymaga kontroli jakości).
    "chat_model": {"type": "choice", "choices": CHAT_MODELS},
    "io_mode": {"type": "choice", "choices": ("voice", "text")},
    "input_device": {"type": "str"},          # "default" = urządzenie systemowe
    "output_device": {"type": "str"},
    # F7: ostatnie ustawienia Quick Chat (poziom „auto” = z diagnozy albo ostrożne A2; nie zmienia diagnozy ani mastery)
    "chat_level": {"type": "choice", "choices": ("auto", "A1", "A2", "B1", "B2", "C1")},
    "chat_category": {"type": "choice", "choices": ("general", "technical", "medical", "business", "professional",
                                                    "custom")},
    "chat_mode": {"type": "choice", "choices": ("natural", "guided", "roleplay")},
    # Pilot: szczegółowy dziennik nauki (zdarzenia STT/błędy/koniec sesji + pliki JSONL). Zgłoszenia ucznia zawsze.
    "learning_log": {"type": "bool"},
}
# F7: tempo mowy. Kokoro zmienia tempo w modelu (długość fonemów), więc wysokość głosu się nie zmienia (bez
# przepróbkowania). Domyślnie „normalnie” = 0,9 — test właściciela: 1,0 było za szybkie.
SPEED_PRESETS = {"slow": 0.8, "normal": 0.9, "fast": 1.05}
DEFAULT_SPEED = SPEED_PRESETS["normal"]
DEFAULTS = {"tts_voice": "bf_emma", "speed": DEFAULT_SPEED, "mic_mode": "ptt", "stt_model": "small.en",
            "stt_confirm": "uncertain", "mascot": "A",
            "conversation_mode": "lesson", "chat_model": CHAT_MODELS[0], "io_mode": "voice",
            "input_device": "default", "output_device": "default",
            "chat_level": "auto", "chat_category": "general", "chat_mode": "natural", "learning_log": True}


class SettingError(ValueError):
    pass


def _coerce(key: str, value):
    spec = SCHEMA.get(key)
    if spec is None:
        raise SettingError(f"nieznane ustawienie: {key}")
    t = spec["type"]
    if key == "speed" and str(value) in SPEED_PRESETS:      # „slow / normal / fast” z GUI
        value = SPEED_PRESETS[str(value)]
    try:
        if t == "float":
            value = float(value)
            if not spec["min"] <= value <= spec["max"]:
                raise SettingError(f"{key}: dozwolone {spec['min']}–{spec['max']}")
        elif t == "bool":
            if isinstance(value, str):
                value = value.lower() in ("1", "true", "tak", "yes", "on")
            value = bool(value)
        elif t == "choice":
            ch = spec["choices"]
            value = type(ch[0])(value)
            if value not in ch:
                raise SettingError(f"{key}: dozwolone {', '.join(map(str, ch))}")
        else:
            value = str(value).strip()
            if not value:
                raise SettingError(f"{key}: pusta wartość")
    except (TypeError, ValueError) as e:
        if isinstance(e, SettingError):
            raise
        raise SettingError(f"{key}: niepoprawna wartość") from e
    return value


def effective(repo, profile_id: int) -> dict:
    """Wartości obowiązujące: domyślne ← config.toml [voice] ← profil/kolumny ← `profile_setting`."""
    v = config.raw_config().get("voice", {})
    p = repo.get_profile(profile_id)
    out = {**DEFAULTS, "tts_voice": v.get("tts_voice") or DEFAULTS["tts_voice"], "speed": v.get("speed", DEFAULT_SPEED),
           "mic_mode": v.get("mode", "ptt"), "stt_model": v.get("stt_model", "small.en"),
           "target_lang": p["target_lang"], "ui_lang": p["ui_lang"], "correction": p["correction_style"],
           "session_minutes": p["daily_minutes"], "allow_unreviewed": bool(p["allow_unreviewed_practice"])}
    out.update({k: x for k, x in repo.get_settings(profile_id).items() if k in SCHEMA})
    return out


def update(repo, profile_id: int, changes: dict) -> dict:
    """Waliduje WSZYSTKIE zmiany przed zapisem (atomowo); zwraca obowiązujące ustawienia."""
    clean = {k: _coerce(k, v) for k, v in changes.items()}
    with repo.transaction():
        cols = {}
        for k, v in clean.items():
            col = SCHEMA[k].get("column")
            if col:
                cols[col] = int(v) if isinstance(v, bool) else v
            repo.set_setting(profile_id, k, v)
        repo.update_profile_columns(profile_id, **cols)
    return effective(repo, profile_id)
