"""Istniejący czat CLI zachowuje działanie."""
import builtins

import main as legacy


class FakeResp:
    def raise_for_status(self):
        pass

    def json(self):
        return {"message": {"content": "Hi there"}}


def test_chat_loop_same_request_and_exit(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(
        legacy.requests, "post", lambda url, **kw: calls.append((url, kw)) or FakeResp()
    )
    inputs = iter(["hello", "/bye"])
    monkeypatch.setattr(builtins, "input", lambda _="": next(inputs))
    legacy.chat()
    out = capsys.readouterr().out
    assert "Tutor: Hi there" in out and "Tutor: Goodbye!" in out
    (url, kw), = calls
    assert url == "http://localhost:11434/api/chat"
    assert kw["timeout"] == 120
    assert kw["json"]["model"] == "SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M"
    assert kw["json"]["stream"] is False
    assert kw["json"]["messages"][0]["role"] == "system"
    assert kw["json"]["messages"][1] == {"role": "user", "content": "hello"}
