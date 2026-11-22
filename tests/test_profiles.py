import json
import os
import stat

import pytest

from tutor import config
from tutor.cli import main as cli


@pytest.fixture
def xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    return tmp_path


def test_paths_follow_xdg(xdg):
    assert config.db_path() == xdg / "data" / "english-ai-tutor" / "tutor.db"
    assert config.config_path() == xdg / "cfg" / "english-ai-tutor" / "config.toml"


def test_select_profile_persisted_0600(xdg):
    config.set_last_profile(7)
    assert config.get_last_profile() == 7
    p = config.config_path()
    assert stat.S_IMODE(os.stat(p).st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p.parent).st_mode) == 0o700


def test_last_profile_missing_is_none(xdg):
    assert config.get_last_profile() is None


def test_cli_create_list_select_export_delete(xdg, capsys, tmp_path):
    assert cli(["create", "Ala"]) == 0
    assert cli(["create", "Ala"]) != 0  # nazwa unikalna
    cli(["create", "Bob"])
    capsys.readouterr()
    cli(["list"])
    out = capsys.readouterr().out
    assert "Ala" in out and "Bob" in out
    assert cli(["select", "Bob"]) == 0
    assert cli(["select", "Zed"]) != 0
    out_file = tmp_path / "bob.json"
    assert cli(["export", "Bob", "-o", str(out_file)]) == 0
    assert stat.S_IMODE(os.stat(out_file).st_mode) == 0o600
    assert json.loads(out_file.read_text())["profile"]["name"] == "Bob"
    assert cli(["delete", "Bob"]) != 0  # bez --yes nic nie robi
    assert cli(["delete", "Bob", "--yes"]) == 0
    assert config.get_last_profile() is None  # wybrany profil usunięty
    capsys.readouterr()
    cli(["list"])
    assert "Bob" not in capsys.readouterr().out
