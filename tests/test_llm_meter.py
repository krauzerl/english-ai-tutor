"""T-LLM-4/5, zgoda, limity, awarie, fallback."""
import logging
from datetime import UTC, datetime

import pytest

from tests.llm_fakes import FakeProvider
from tutor.llm.base import (
    BudgetExceeded,
    CancelToken,
    ConsentRequired,
    LimitsNotConfigured,
    LLMUnavailable,
    LocalFallback,
    Message,
    StreamInterrupted,
    Usage,
)
from tutor.llm.meter import Guarded, Limits, Meter, Price

MSG = [Message("user", "x" * 300)]  # ~100 tok
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def setup(repo):
    pid = repo.create_profile("A")
    repo.set_consent(pid, True)
    meter = Meter(repo, Limits(daily_usd=1.0, monthly_usd=10.0),
                  {"gm": Price(in_per_mtok=1000.0, out_per_mtok=4000.0)}, now=lambda: NOW)
    return repo, pid, meter


def cloud(**kw):
    return FakeProvider(name="gemini", model="gm", external=True, usage=Usage(100, 50, reasoning_tokens=50), **kw)


def guard(setup, prov, pid=None):
    repo, p, meter = setup
    return Guarded(prov, repo, pid or p, "conversation", meter)


def test_no_consent_blocks_cloud_even_with_key_and_limits(setup):
    repo, pid, _ = setup
    repo.set_consent(pid, False)
    p = cloud()
    with pytest.raises(ConsentRequired):
        guard(setup, p).chat(MSG, temperature=0, max_tokens=100)
    assert p.calls == []  # t_llm_4: żadnego żądania


def test_revoked_consent_blocks_next_request(setup):
    repo, pid, _ = setup
    g = guard(setup, cloud())
    g.chat(MSG, temperature=0, max_tokens=100)
    repo.set_consent(pid, False)
    with pytest.raises(ConsentRequired):
        g.chat(MSG, temperature=0, max_tokens=100)


def test_revoked_consent_stops_stream(setup):
    repo, pid, _ = setup
    s = guard(setup, cloud(chunks=["a", "b", "c"])).stream(MSG, temperature=0, max_tokens=100)
    assert next(s) == "a"
    repo.set_consent(pid, False)
    with pytest.raises(ConsentRequired):
        next(s)


@pytest.mark.parametrize("meter", [
    Meter(None, Limits(None, 10.0), {"gm": Price(1, 1)}),
    Meter(None, Limits(1.0, None), {"gm": Price(1, 1)}),
    Meter(None, Limits(1.0, 10.0), {}),  # brak cennika
])
def test_cloud_needs_limits_and_price(setup, meter):
    repo, pid, _ = setup
    meter.repo = repo
    p = cloud()
    with pytest.raises(LimitsNotConfigured):
        Guarded(p, repo, pid, "conversation", meter).chat(MSG, temperature=0, max_tokens=100)
    assert p.calls == []


def test_local_needs_no_consent_limits_and_costs_zero(repo):
    pid = repo.create_profile("A")  # brak zgody
    meter = Meter(repo, Limits(None, None), {})
    p = FakeProvider(name="ollama", model="bielik", external=False)
    Guarded(p, repo, pid, "conversation", meter).chat(MSG, temperature=0, max_tokens=100)
    row = repo.conn.execute("SELECT * FROM llm_usage").fetchone()
    assert row["cost_usd"] == 0 and row["provider"] == "ollama"


def test_usage_recorded_with_reasoning_billed_as_output(setup):
    repo, pid, _ = setup
    guard(setup, cloud()).chat(MSG, temperature=0, max_tokens=100)
    r = repo.conn.execute("SELECT * FROM llm_usage").fetchone()
    assert (r["in_tokens"], r["out_tokens"]) == (100, 100)  # 50 + 50 rozumowania
    assert r["cost_usd"] == pytest.approx(100 * 1000e-6 + 100 * 4000e-6)


def test_t_llm_5_block_at_limit_before_call(setup):
    repo, pid, _ = setup
    repo.add_llm_usage(pid, "gemini", "gm", "conversation", 1, 1, 1, 0.99, created_at="2026-11-22T01:00:00.000Z")
    p = cloud()
    with pytest.raises(BudgetExceeded):
        guard(setup, p).chat(MSG, temperature=0, max_tokens=100)  # est ≈ 0.1+0.4 > reszta
    assert p.calls == []


def test_t_llm_5_warning_at_80_percent(setup):
    repo, pid, _ = setup
    repo.add_llm_usage(pid, "gemini", "gm", "conversation", 1, 1, 1, 0.75, created_at="2026-11-22T01:00:00.000Z")
    rep = guard(setup, cloud()).chat(MSG, temperature=0, max_tokens=20)  # est ≈ 0.1+0.08 → >80%, ≤100%
    assert any("80" in n or "%" in n for n in rep.notices)


def test_no_warning_below_80(setup):
    rep = guard(setup, cloud()).chat(MSG, temperature=0, max_tokens=1)
    assert rep.notices == []


def test_monthly_limit_blocks(setup):
    repo, pid, _ = setup
    repo.add_llm_usage(pid, "gemini", "gm", "conversation", 1, 1, 1, 9.95, created_at="2026-11-02T01:00:00.000Z")
    with pytest.raises(BudgetExceeded):
        guard(setup, cloud()).chat(MSG, temperature=0, max_tokens=100)


def test_limit_shared_across_profiles(setup):
    repo, a, _ = setup
    b = repo.create_profile("B")
    repo.set_consent(b, True)
    repo.add_llm_usage(a, "gemini", "gm", "conversation", 1, 1, 1, 0.99, created_at="2026-11-22T01:00:00.000Z")
    with pytest.raises(BudgetExceeded):
        guard(setup, cloud(), pid=b).chat(MSG, temperature=0, max_tokens=100)


def test_spend_survives_profile_deletion(setup):
    repo, pid, meter = setup
    repo.add_llm_usage(pid, "gemini", "gm", "conversation", 1, 1, 1, 0.5, created_at="2026-11-22T01:00:00.000Z")
    repo.delete_profile(pid)
    assert meter.spent()[0] == pytest.approx(0.5)


def test_stream_cancel_records_estimated_usage_and_stops(setup):
    repo, pid, _ = setup
    tok = CancelToken()
    p = cloud(chunks=["aa", "bb", "cc", "dd"])
    s = guard(setup, p).stream(MSG, temperature=0, max_tokens=100, cancel=tok)
    got = [next(s), next(s)]
    tok.set()
    assert list(s) == []  # po anulowaniu nic więcej
    assert got == ["aa", "bb"] and s.cancelled
    r = repo.conn.execute("SELECT * FROM llm_usage").fetchone()
    assert r["in_tokens"] > 0 and r["cost_usd"] > 0  # szacunek zapisany


def test_stream_failure_raises_with_partial_never_merged(setup):
    repo, pid, _ = setup
    s = guard(setup, cloud(chunks=["a", "b", "c"], fail_after=2)).stream(MSG, temperature=0, max_tokens=100)
    with pytest.raises(StreamInterrupted) as e:
        list(s)
    assert e.value.partial == "ab"
    assert repo.conn.execute("SELECT COUNT(*) FROM llm_usage").fetchone()[0] == 1


def test_stream_success_records_provider_usage(setup):
    repo, *_ = setup
    s = guard(setup, cloud(chunks=["a", "b"])).stream(MSG, temperature=0, max_tokens=100)
    assert "".join(s) == "ab"
    assert repo.conn.execute("SELECT out_tokens FROM llm_usage").fetchone()[0] == 100


def test_t_llm_8_no_content_or_key_in_logs_or_db(setup, caplog):
    repo, pid, _ = setup
    caplog.set_level(logging.DEBUG)
    p = cloud(replies=["ODPOWIEDZ-SEKRET"])
    guard(setup, p).chat([Message("user", "TRESC-UCZNIA-SEKRET")], temperature=0, max_tokens=50)
    dump = repr(repo.export_profile(pid))
    for secret in ("TRESC-UCZNIA-SEKRET", "ODPOWIEDZ-SEKRET"):
        assert secret not in caplog.text and secret not in dump


# --- fallback ---
def test_fallback_signals_user():
    prim = cloud(replies=[LLMUnavailable("down")])
    loc = FakeProvider(name="ollama", model="bielik", replies=["hej"])
    rep = LocalFallback(prim, loc).chat(MSG, temperature=0, max_tokens=10)
    assert rep.text == "hej" and rep.provider == "ollama"
    assert any("ollama" in n.lower() for n in rep.notices)


def test_fallback_on_consent_missing(setup):
    repo, pid, _ = setup
    repo.set_consent(pid, False)
    loc = FakeProvider(name="ollama", model="bielik", replies=["hej"])
    rep = LocalFallback(guard(setup, cloud()), loc).chat(MSG, temperature=0, max_tokens=10)
    assert rep.provider == "ollama" and rep.notices


def test_never_local_to_cloud():
    with pytest.raises(ValueError):
        LocalFallback(FakeProvider(external=False), cloud())  # lokalny nie przechodzi na chmurę
    with pytest.raises(ValueError):
        LocalFallback(cloud(), cloud())


def test_stream_fallback_before_first_chunk_only():
    prim = cloud(chunks=["x"], fail_after=0)
    loc = FakeProvider(name="ollama", model="b", chunks=["lo", "cal"])
    s = LocalFallback(prim, loc).stream(MSG, temperature=0, max_tokens=10)
    assert "".join(s) == "local" and s.notices


def test_stream_midway_failure_not_merged_with_fallback():
    prim = cloud(chunks=["a", "b", "c"], fail_after=1)
    loc = FakeProvider(name="ollama", model="b", chunks=["LOCAL"])
    s = LocalFallback(prim, loc).stream(MSG, temperature=0, max_tokens=10)
    with pytest.raises(StreamInterrupted) as e:
        list(s)
    assert e.value.partial == "a" and loc.calls == []


def test_t_llm_7_switching_provider_keeps_history(setup):
    repo, pid, meter = setup
    s = repo.start_session(pid, "chat")
    repo.add_turn(pid, s, "user", "hello")
    before = repo.export_profile(pid)["tables"]
    for prov in (FakeProvider(name="ollama", model="b"), cloud()):
        Guarded(prov, repo, pid, "conversation", meter).chat(MSG, temperature=0, max_tokens=10)
    after = repo.export_profile(pid)["tables"]
    for t in before:
        if t != "llm_usage":
            assert before[t] == after[t]
