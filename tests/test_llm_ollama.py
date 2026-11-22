"""Ollama na prawdziwym lokalnym serwerze HTTP-atrapie (bez Ollamy)."""
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from tutor.llm.base import (
    CancelToken,
    LLMError,
    LLMTimeout,
    LLMUnavailable,
    Message,
    StreamInterrupted,
)
from tutor.llm.ollama import OllamaProvider

MSG = [Message("system", "S"), Message("user", "hi")]


class Srv:
    def __init__(self, handler):
        self.requests, self.closed_early = [], threading.Event()
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a): ...

            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'{"models":[]}')

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                outer.requests.append(body)
                handler(self, body, outer)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_port}"

    def close(self):
        self.httpd.shutdown()


@pytest.fixture
def serve():
    servers = []

    def make(handler):
        servers.append(Srv(handler))
        return servers[-1]
    yield make
    for s in servers:
        s.close()


def ok_chat(h, body, srv):
    out = json.dumps({"message": {"content": '{"a":1}'}, "done": True, "prompt_eval_count": 12,
                      "eval_count": 7}).encode()
    h.send_response(200); h.send_header("Content-Length", str(len(out))); h.end_headers(); h.wfile.write(out)


def provider(srv, **kw):
    return OllamaProvider(model="SpeakLeash/bielik-11b-v2.3-instruct:Q4_K_M", url=srv.url, **kw)


def test_chat_returns_text_usage_and_sends_options(serve):
    srv = serve(ok_chat)
    r = provider(srv, num_ctx=8192).chat(MSG, temperature=0.3, max_tokens=99)
    assert r.text == '{"a":1}' and (r.usage.in_tokens, r.usage.out_tokens) == (12, 7)
    req = srv.requests[0]
    assert req["model"].startswith("SpeakLeash/bielik-11b") and req["stream"] is False
    assert req["options"]["num_predict"] == 99 and req["options"]["num_ctx"] == 8192
    assert req["messages"][0] == {"role": "system", "content": "S"}


def test_structured_sends_schema_as_format(serve):
    srv = serve(ok_chat)
    provider(srv).chat(MSG, temperature=0, max_tokens=9, schema={"type": "object"})
    assert srv.requests[0]["format"] == {"type": "object"}


def test_model_is_configurable(serve):
    srv = serve(ok_chat)
    OllamaProvider(model="inny:7b", url=srv.url).chat(MSG, temperature=0, max_tokens=5)
    assert srv.requests[0]["model"] == "inny:7b"


def test_stream_chunks_and_usage(serve):
    def h(hd, body, srv):
        hd.send_response(200); hd.end_headers()
        for c in ("He", "llo"):
            hd.wfile.write(json.dumps({"message": {"content": c}, "done": False}).encode() + b"\n")
        hd.wfile.write(json.dumps({"message": {"content": ""}, "done": True, "prompt_eval_count": 3,
                                   "eval_count": 2}).encode() + b"\n")
    s = provider(serve(h)).stream(MSG, temperature=0, max_tokens=9)
    assert "".join(s) == "Hello" and s.usage.in_tokens == 3 and s.usage.out_tokens == 2


def test_stream_cancel_stops_and_closes_connection(serve):
    def h(hd, body, srv):
        hd.send_response(200); hd.end_headers()
        try:
            for i in range(200):
                hd.wfile.write(json.dumps({"message": {"content": "x"}, "done": False}).encode() + b"\n")
                hd.wfile.flush(); time.sleep(0.01)
        except OSError:
            srv.closed_early.set()
    srv = serve(h)
    tok = CancelToken()
    s = provider(srv).stream(MSG, temperature=0, max_tokens=9, cancel=tok)
    assert next(s) == "x"
    tok.set()
    assert list(s) == [] and s.cancelled
    assert srv.closed_early.wait(3)


def test_unreachable_is_unavailable_with_message():
    p = OllamaProvider(model="m", url="http://127.0.0.1:9", timeout=2)
    with pytest.raises(LLMUnavailable) as e:
        p.chat(MSG, temperature=0, max_tokens=5)
    assert e.value.user_message
    assert p.health() is False


def test_timeout(serve):
    srv = serve(lambda h, b, s: time.sleep(1.5))
    with pytest.raises(LLMTimeout):
        provider(srv, timeout=0.3).chat(MSG, temperature=0, max_tokens=5)


def test_http_error_controlled_without_body(serve):
    def h(hd, body, srv):
        out = b"SEKRET-BODY"
        hd.send_response(500); hd.send_header("Content-Length", str(len(out))); hd.end_headers(); hd.wfile.write(out)
    with pytest.raises(LLMError) as e:
        provider(serve(h)).chat(MSG, temperature=0, max_tokens=5)
    assert "SEKRET-BODY" not in str(e.value) and "500" in str(e.value)


def test_stream_dropped_midway_raises_interrupted_with_partial(serve):
    def h(hd, body, srv):
        hd.send_response(200); hd.end_headers()
        hd.wfile.write(json.dumps({"message": {"content": "ab"}, "done": False}).encode() + b"\n")
        hd.wfile.flush()  # i urwanie połączenia bez done
    s = provider(serve(h)).stream(MSG, temperature=0, max_tokens=9)
    with pytest.raises(StreamInterrupted) as e:
        list(s)
    assert e.value.partial == "ab"


def test_health(serve):
    assert provider(serve(ok_chat)).health() is True


def test_think_flag_sent_only_when_set():  # F4.7: Qwen3 z wyłączonym thinking
    m = [Message("user", "hi")]
    assert "think" not in OllamaProvider()._body(m, 0.0, 10, False)
    assert OllamaProvider(think=False)._body(m, 0.0, 10, False)["think"] is False
