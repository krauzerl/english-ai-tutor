"""T-LLM-6, T-ISO-4, checkpointy."""
import pytest

from tutor.llm.base import ContextTooLarge
from tutor.llm.context import build_context, estimate_tokens, make_checkpoint, needs_checkpoint

KW = dict(context_window=4096, reserve_out=512)


def _text(msgs):
    return "\n".join(m.content for m in msgs)


def test_estimate_is_conservative():
    assert estimate_tokens("a" * 350) >= 100  # >= znaki/3.5
    assert estimate_tokens("") == 0


def test_t_llm_6_200_turns_within_budget_and_checkpoint_every_10(repo):
    pid = repo.create_profile("A")
    s = repo.start_session(pid, "chat")
    for i in range(200):
        repo.add_turn(pid, s, "user" if i % 2 == 0 else "assistant", f"turn-{i:03d} " + "słowo " * 60)
        if needs_checkpoint(repo, pid, s):
            make_checkpoint(repo, pid, s, lambda prev, turns: f"cp up to {turns[-1]['id']} " + "x" * 5000)
        ctx = build_context(repo, pid, s, "SYSTEM", "bieżąca wiadomość", **KW)
        assert ctx.est_tokens <= KW["context_window"] - KW["reserve_out"]
        assert ctx.memory_tokens <= 3000
    assert len(repo.list_checkpoints(pid, s)) == 20
    repo.add_turn(pid, s, "user", "extra-after-checkpoint")  # checkpoint pokrył już turę 199
    final = _text(build_context(repo, pid, s, "SYSTEM", "bieżąca", **KW).messages)
    assert "extra-after-checkpoint" in final and "turn-000" not in final  # nie cała historia
    assert ctx.messages[0].role == "system" and ctx.messages[-1].content == "bieżąca wiadomość"


def test_memory_budget_default_3000(repo):
    pid = repo.create_profile("A")
    s = repo.start_session(pid, "chat")
    for i in range(100):
        repo.add_turn(pid, s, "user", "x" * 600)
    ctx = build_context(repo, pid, s, "S", "hi", context_window=100_000, reserve_out=500)
    assert 0 < ctx.memory_tokens <= 3000


def test_uses_checkpoint_and_skips_covered_turns(repo):
    pid = repo.create_profile("A")
    s = repo.start_session(pid, "chat")
    ids = [repo.add_turn(pid, s, "user", f"old-{i}") for i in range(5)]
    repo.add_checkpoint(pid, s, ids[-1], "CHECKPOINT-SUMMARY")
    repo.add_turn(pid, s, "user", "fresh-turn")
    text = _text(build_context(repo, pid, s, "S", "hi", **KW).messages)
    assert "CHECKPOINT-SUMMARY" in text and "fresh-turn" in text and "old-0" not in text


def test_uses_latest_prior_session_summary(repo):
    pid = repo.create_profile("A")
    s1 = repo.start_session(pid, "chat")
    repo.put_session_summary(pid, "session", "PRIOR-SUMMARY", session_id=s1)
    s2 = repo.start_session(pid, "chat")
    text = _text(build_context(repo, pid, s2, "S", "hi", **KW).messages)
    assert "PRIOR-SUMMARY" in text


def test_t_iso_4_context_has_no_other_profile_data(repo):
    a, b = repo.create_profile("A"), repo.create_profile("B")
    sa, sb = repo.start_session(a, "chat"), repo.start_session(b, "chat")
    for pid, s, tag in ((a, sa, "alpha"), (b, sb, "bravo")):
        t = repo.add_turn(pid, s, "user", f"turn-{tag}")
        repo.add_checkpoint(pid, s, t, f"cp-{tag}")
        repo.add_turn(pid, s, "user", f"after-{tag}")
        repo.put_session_summary(pid, "session", f"sum-{tag}", session_id=s)
    sa2 = repo.start_session(a, "chat")
    text = _text(build_context(repo, a, sa2, "S", "hi", **KW).messages)
    assert "sum-alpha" in text and "bravo" not in text
    # cudza sesja podana przy własnym profilu: nic nie wycieka
    leak = _text(build_context(repo, a, sb, "S", "hi", **KW).messages)
    assert "bravo" not in leak


def test_message_larger_than_window_raises(repo):
    pid = repo.create_profile("A")
    s = repo.start_session(pid, "chat")
    with pytest.raises(ContextTooLarge):
        build_context(repo, pid, s, "S", "x" * 50_000, **KW)


def test_checkpoint_summarizer_gets_previous_checkpoint(repo):
    pid = repo.create_profile("A")
    s = repo.start_session(pid, "chat")
    seen = []
    for i in range(20):
        repo.add_turn(pid, s, "user", f"t{i}")
        if needs_checkpoint(repo, pid, s):
            make_checkpoint(repo, pid, s, lambda prev, turns: (seen.append((prev, len(turns))) or f"cp{len(seen)}"))
    assert seen == [(None, 10), ("cp1", 10)]


def test_summary_json_decoded(repo):
    pid = repo.create_profile("A")
    s1 = repo.start_session(pid, "chat")
    repo.put_session_summary(pid, "session", {"topics": ["travel"]}, session_id=s1)
    s2 = repo.start_session(pid, "chat")
    assert "travel" in _text(build_context(repo, pid, s2, "S", "hi", **KW).messages)
