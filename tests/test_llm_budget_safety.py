"""Współbieżność wspólnego budżetu, walidacja cennika, rozliczanie tokenów rozumowania."""
import threading
import time
from datetime import UTC, datetime

import pytest

from tests.llm_fakes import FakeProvider
from tutor.llm import llm_settings
from tutor.llm.base import BudgetExceeded, LLMError, Message, Usage
from tutor.llm.meter import Guarded, Limits, Meter, Price
from tutor.store.db import open_db
from tutor.store.repo import Repo

MSG = [Message("user", "x" * 300)]  # ~100 tok → 0.1 USD przy 1000 USD/Mtok
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)
PRICES = {"gm": Price(1000.0, 4000.0)}  # żądanie max_tokens=100: 0.1 + 0.4 = 0.5 USD


class SlowCloud(FakeProvider):
    def chat(self, *a, **kw):
        time.sleep(0.4)  # rezerwacje nakładają się w czasie
        return super().chat(*a, **kw)


def test_concurrent_requests_cannot_overshoot_shared_limit(tmp_path):
    path = tmp_path / "d" / "t.db"
    c0 = open_db(path)
    r0 = Repo(c0)
    pids = [r0.create_profile(f"P{i}") for i in range(8)]
    for p in pids:
        r0.set_consent(p, True)
    barrier = threading.Barrier(8)
    results = []

    def worker(pid):
        conn = open_db(path)  # osobne połączenie na wątek (jak osobne procesy)
        repo = Repo(conn)
        meter = Meter(repo, Limits(1.02, 10.0), PRICES, now=lambda: NOW)  # 2 × 0.504 mieści się, 3 nie
        prov = SlowCloud(name="gemini", model="gm", external=True, usage=Usage(100, 10))
        barrier.wait()
        try:
            Guarded(prov, repo, pid, "conversation", meter).chat(MSG, temperature=0, max_tokens=100)
            results.append("ok")
        except BudgetExceeded:
            results.append("blocked")
        finally:
            conn.close()

    ts = [threading.Thread(target=worker, args=(p,)) for p in pids]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert results.count("ok") == 2 and results.count("blocked") == 6  
    c0.close()


def test_reservation_is_settled_to_actual_cost(repo):
    pid = repo.create_profile("A")
    repo.set_consent(pid, True)
    meter = Meter(repo, Limits(1.0, 10.0), PRICES, now=lambda: NOW)
    prov = FakeProvider(name="gemini", model="gm", external=True, usage=Usage(100, 10))
    Guarded(prov, repo, pid, "conversation", meter).chat(MSG, temperature=0, max_tokens=100)
    assert meter.spent()[0] == pytest.approx(100 * 1000e-6 + 10 * 4000e-6)  # nie 0.5
    assert repo.conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 1


def test_failed_chat_does_not_leave_full_reservation(repo):
    from tutor.llm.base import LLMUnavailable
    pid = repo.create_profile("A")
    repo.set_consent(pid, True)
    meter = Meter(repo, Limits(1.0, 10.0), PRICES, now=lambda: NOW)
    prov = FakeProvider(name="gemini", model="gm", external=True, replies=[LLMUnavailable("x")])
    with pytest.raises(LLMUnavailable):
        Guarded(prov, repo, pid, "conversation", meter).chat(MSG, temperature=0, max_tokens=100)
    assert meter.spent()[0] < 0.2  # tylko szacunek wejścia, nie rezerwacja 0.5


def test_reasoning_tokens_count_toward_limit(repo):
    pid = repo.create_profile("A")
    repo.set_consent(pid, True)
    meter = Meter(repo, Limits(0.6, 10.0), PRICES, now=lambda: NOW)
    # 10 tokenów odpowiedzi + 90 rozumowania = 100 rozliczonych jako wyjście (≤ max_tokens)
    prov = FakeProvider(name="gemini", model="gm", external=True, usage=Usage(100, 10, reasoning_tokens=90))
    g = Guarded(prov, repo, pid, "conversation", meter)
    g.chat(MSG, temperature=0, max_tokens=100)
    assert meter.spent()[0] == pytest.approx(100 * 1000e-6 + 100 * 4000e-6)  # 0.5, nie 0.14
    with pytest.raises(BudgetExceeded):  # 0.5 + 0.5 > 0.6
        g.chat(MSG, temperature=0, max_tokens=100)


def test_actual_overshoot_is_recorded_in_full(repo):
    pid = repo.create_profile("A")
    repo.set_consent(pid, True)
    meter = Meter(repo, Limits(1.0, 10.0), PRICES, now=lambda: NOW)
    prov = FakeProvider(name="gemini", model="gm", external=True, usage=Usage(100, 100, reasoning_tokens=400))
    Guarded(prov, repo, pid, "conversation", meter).chat(MSG, temperature=0, max_tokens=100)
    assert meter.spent()[0] == pytest.approx(100 * 1000e-6 + 500 * 4000e-6)  # więcej niż rezerwacja


@pytest.mark.parametrize("a,b", [(0, 1), (1, 0), (-1, 1), (float("nan"), 1)])
def test_zero_or_invalid_price_rejected(a, b):
    with pytest.raises(ValueError):
        Price(a, b)


def test_zero_price_in_config_is_error_not_free(tmp_path, monkeypatch):
    from tutor import config
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    p = config.config_path()
    p.parent.mkdir(parents=True)
    p.write_text('[pricing."g"]\nin_per_mtok = 0.0\nout_per_mtok = 0.0\n')
    with pytest.raises(LLMError):
        llm_settings()
    p.write_text('[pricing."g"]\nin_per_mtok = 1.0\n')  # brak out
    with pytest.raises(LLMError):
        llm_settings()
