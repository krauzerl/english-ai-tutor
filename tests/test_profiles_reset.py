"""F7: reset postępów i usunięcie profilu — tylko tymczasowe bazy (fixture `repo`), nigdy dane użytkownika."""
import json

import pytest

from tutor.app import profiles as PR
from tutor.app import settings as ST
from tutor.cli import main as profile_main


def fill(repo, pid):
    sid = repo.start_session(pid, "chat")
    repo.end_session(pid, sid)
    tid = repo.add_turn(pid, sid, "user", "I goed")
    repo.add_observation(pid, sid, tid, "error", "goed", category="morphology", fix="went", severity=2,
                         confidence="h")
    repo.add_attempt(pid, "en.gram.to_be_present", True, session_id=sid, item_id="x")
    repo.conn.execute("INSERT INTO achievement(profile_id,code) VALUES (?,?)", (pid, "first"))
    ST.update(repo, pid, {"speed": 0.8, "ui_lang": "en"})
    return sid


def counts(repo, pid):
    return {t: repo.conn.execute(f"SELECT COUNT(*) FROM {t} WHERE profile_id=?", (pid,)).fetchone()[0]
            for t in repo.student_tables()}


def test_reset_keeps_profile_and_settings_removes_progress(repo, tmp_path):
    a, b = repo.create_profile("ann"), repo.create_profile("bob")
    fill(repo, a)
    fill(repo, b)
    before_b = counts(repo, b)
    r = PR.reset_progress(repo, a, "ANN", directory=tmp_path)
    c = counts(repo, a)
    assert repo.get_profile(a)["name"] == "ann" and ST.effective(repo, a)["speed"] == 0.8
    assert ST.effective(repo, a)["ui_lang"] == "en"
    assert all(n == 0 for t, n in c.items() if t not in PR.KEEP_ON_RESET)
    assert counts(repo, b) == before_b                                         # inne profile nietknięte
    data = json.loads(open(r["backup"]).read())
    assert data["profile"]["name"] == "ann" and data["tables"]["attempt"]       # kopia ma stare dane
    assert (tmp_path / r["backup"].split("/")[-1]).stat().st_mode & 0o777 == 0o600


def test_delete_removes_only_that_profile(repo, tmp_path):
    a, b = repo.create_profile("ann"), repo.create_profile("bob")
    fill(repo, a)
    fill(repo, b)
    before_b = counts(repo, b)
    r = PR.delete(repo, a, "ann", directory=tmp_path)
    assert repo.get_profile(a) is None and all(n == 0 for n in counts(repo, a).values())
    assert counts(repo, b) == before_b and r["backup"]


@pytest.mark.parametrize("op", [PR.reset_progress, PR.delete])
def test_wrong_confirmation_changes_nothing(repo, tmp_path, op):
    a = repo.create_profile("ann")
    fill(repo, a)
    before = counts(repo, a)
    with pytest.raises(PR.ProfileOpError):
        op(repo, a, "bob", directory=tmp_path / "bk")
    assert counts(repo, a) == before and not (tmp_path / "bk").exists()


@pytest.mark.parametrize("op", [PR.reset_progress, PR.delete])
def test_active_session_blocks_operation(repo, tmp_path, op):
    a = repo.create_profile("ann")
    repo.start_session(a, "chat")                                               # trwa (status active)
    with pytest.raises(PR.ProfileOpError):
        op(repo, a, "ann", directory=tmp_path)
    assert repo.get_profile(a) is not None


def test_cli_reset_requires_yes_then_resets_with_backup(tmp_path, monkeypatch, capsys):
    from tutor.store.db import open_db
    from tutor.store.repo import Repo
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    from tutor import config
    repo = Repo(open_db(config.db_path()))
    a = repo.create_profile("ann")
    fill(repo, a)
    repo.conn.close()
    assert profile_main(["reset", "ann"]) == 1                                # bez --yes nic się nie dzieje
    assert profile_main(["reset", "ann", "--yes"]) == 0
    repo = Repo(open_db(config.db_path()))
    assert counts(repo, a)["attempt"] == 0 and repo.get_profile(a)
    assert "Kopia zapasowa" in capsys.readouterr().out
