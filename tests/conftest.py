import pytest

from tutor.store.db import open_db
from tutor.store.repo import Repo


@pytest.fixture
def conn(tmp_path):
    c = open_db(tmp_path / "data" / "tutor.db")
    yield c
    c.close()


@pytest.fixture
def repo(conn):
    return Repo(conn)
