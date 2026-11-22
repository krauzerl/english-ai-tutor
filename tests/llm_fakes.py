"""Atrapy dostawców do testów (żadnych prawdziwych wywołań)."""
from tutor.llm.base import CancelToken, LLMUnavailable, Reply, Stream, Usage


class FakeProvider:
    def __init__(self, name="fake", model="m", external=False, replies=(), chunks=(),
                 fail_after=None, usage=Usage(10, 5)):
        self.name, self.model, self.external = name, model, external
        self.replies, self.chunks, self.fail_after, self.usage = list(replies), chunks, fail_after, usage
        self.calls = []

    def chat(self, messages, *, temperature=0.0, max_tokens=256, schema=None):
        self.calls.append(messages)
        r = self.replies.pop(0) if self.replies else "ok"
        if isinstance(r, Exception):
            raise r
        return Reply(r, self.usage, self.name, self.model)

    def stream(self, messages, *, temperature=0.0, max_tokens=256, cancel=None):
        self.calls.append(messages)

        def gen():
            for i, c in enumerate(self.chunks):
                if self.fail_after is not None and i == self.fail_after:
                    raise LLMUnavailable("boom")
                yield c
            return self.usage
        return Stream(gen(), cancel or CancelToken())

    def health(self):
        return True
