"""F7: ustawienia profilu używane przez GUI i CLI — model rozmowy, tryb tekstowy, urządzenia."""
import pytest

from tutor.app import settings as ST
from tutor.voice import cli


@pytest.fixture
def pid(repo):
    return repo.create_profile("ann")


def test_defaults_and_validation(repo, pid):
    v = ST.effective(repo, pid)
    assert (v["chat_model"], v["io_mode"], v["input_device"]) == ("qwen3:8b", "voice", "default")
    with pytest.raises(ST.SettingError):
        ST.update(repo, pid, {"chat_model": "llama3:70b"})          # tylko obsługiwane modele
    with pytest.raises(ST.SettingError):
        ST.update(repo, pid, {"io_mode": "telepathy"})


def test_io_mode_text_and_devices_apply_to_cli(repo, pid):
    ST.update(repo, pid, {"io_mode": "text", "input_device": "3"})
    a = cli.parse(["--voice"])
    cli._apply_settings(a, ["--voice"], repo, repo.get_profile(pid))
    assert a.no_audio is True and a.input_device == "3" and a.output_device is None
    assert a.chat_model is None                                      # brak jawnego wyboru = config.toml
    b = cli.parse(["--voice", "--input-device", "1"])
    cli._apply_settings(b, ["--voice", "--input-device", "1"], repo, repo.get_profile(pid))
    assert b.input_device == "1"                                     # CLI wygrywa


def test_chat_model_changes_only_conversation_role(repo, pid, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    ST.update(repo, pid, {"chat_model": "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M"})
    a = cli.parse(["--voice"])
    cli._apply_settings(a, ["--voice"], repo, repo.get_profile(pid))
    p = cli._chat_provider(a)
    assert p.model.startswith("SpeakLeash/bielik") and p.think is None   # Bielik bez trybu thinking
    from tutor.llm import build_provider
    assert build_provider("evaluation").model == "qwen3:8b"           # model oceny bez zmian
    a.chat_model = "qwen3:8b"
    assert cli._chat_provider(a).think is False
