"""Konfiguracja LLM, .env, fabryka dostawców, T-LLM-8 (klucz poza repo/DB)."""
import subprocess
from pathlib import Path

import pytest

from tutor import config
from tutor.llm import build_provider, llm_settings
from tutor.llm.base import LLMError


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return tmp_path


def write_cfg(text):
    p = config.config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def test_set_last_profile_preserves_llm_sections(home):
    write_cfg('last_profile_id = 1\n[llm.conversation]\nprovider = "ollama"\nmodel = "m"\n'
              '[limits]\ndaily_usd = 1.5\n')
    config.set_last_profile(2)
    assert config.get_last_profile() == 2
    s = llm_settings()
    assert s["limits"]["daily_usd"] == 1.5 and s["roles"]["conversation"]["model"] == "m"


def test_defaults_use_installed_bielik(home):
    s = llm_settings()
    for role in ("conversation", "evaluation", "generation"):
        assert s["roles"][role]["provider"] == "ollama"
        assert "bielik-11b" in s["roles"][role]["model"]
    assert s["limits"] == {"daily_usd": None, "monthly_usd": None}


def test_key_from_env_file_outside_repo(home):
    env = config.config_path().parent / ".env"
    env.parent.mkdir(parents=True, exist_ok=True)
    env.write_text('# c\nGEMINI_API_KEY="abc123"\n')
    assert config.gemini_api_key() == "abc123"
    assert Path(env).is_relative_to(home)  # poza katalogiem repo


def test_env_var_wins_and_missing_key_is_controlled(home, monkeypatch):
    assert config.gemini_api_key() is None
    write_cfg('[llm.conversation]\nprovider = "gemini"\nmodel = "g-test"\n')
    with pytest.raises(LLMError) as e:
        build_provider("conversation")
    assert "GEMINI_API_KEY" in e.value.user_message
    monkeypatch.setenv("GEMINI_API_KEY", "fromenv")
    assert build_provider("conversation").external is True


def test_gemini_without_model_is_error(home, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    write_cfg('[llm.conversation]\nprovider = "gemini"\n')
    with pytest.raises(LLMError):
        build_provider("conversation")


def test_user_picks_provider_per_role(home, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "k")
    write_cfg('[llm.conversation]\nprovider = "ollama"\nmodel = "x:1b"\n'
              '[llm.evaluation]\nprovider = "gemini"\nmodel = "g"\n')
    assert build_provider("conversation").model == "x:1b"
    assert build_provider("evaluation").name == "gemini"
    assert build_provider("generation").name == "ollama"


def test_t_llm_8_key_not_in_repo_files():
    out = subprocess.run(["git", "grep", "-nE", r"AIza[0-9A-Za-z_-]{20,}", "--", "."],
                         capture_output=True, text=True)
    assert out.stdout == ""
    assert ".env" in Path(".gitignore").read_text().splitlines()
