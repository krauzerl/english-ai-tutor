"""T-CORR-4: kolejka oceny — priorytet rozmowy, przerwanie, partie, idempotencja."""
from tutor.app.eval_queue import MAX_TRIES, EvalQueue, Pending
from tutor.llm.base import CancelToken


def P(i):
    return Pending(i, f"t{i}", "text")


def make(evaluate=None, batch=5):
    calls, applied = [], []

    def ev(b):
        calls.append([p.turn_id for p in b])
        return [f"r{p.turn_id}" for p in b]
    q = EvalQueue(evaluate or ev, lambda p, r: applied.append((p.turn_id, r)), batch=batch)
    return q, calls, applied


def test_batches_of_five_in_order():
    q, calls, applied = make()
    for i in range(7):
        q.submit(P(i))
    assert q.drain(CancelToken()) == 7
    assert calls == [[0, 1, 2, 3, 4], [5, 6]]
    assert [a[0] for a in applied] == list(range(7)) and len(q) == 0


def test_submit_dedups_turn():
    q, calls, _ = make()
    q.submit(P(1)); q.submit(P(1))
    assert len(q) == 1


def test_no_eval_while_conversation_active():
    q, calls, _ = make()
    q.submit(P(1))
    assert q.drain(CancelToken(), conversation_active=lambda: True) == 0
    assert calls == [] and len(q) == 1


def test_cancel_before_start_keeps_queue():
    q, calls, _ = make()
    q.submit(P(1))
    c = CancelToken(); c.set()
    assert q.drain(c) == 0 and calls == [] and len(q) == 1


def test_cancel_during_eval_requeues_batch_and_later_evaluates():
    c = CancelToken()
    q, calls, applied = make()
    inner = q._evaluate
    q._evaluate = lambda b: (c.set(), inner(b))[1]    # nowa tura ucznia w trakcie oceny
    q.submit(P(1)); q.submit(P(2))
    assert q.drain(c) == 0 and applied == [] and len(q) == 2
    q._evaluate = inner
    assert q.drain(CancelToken()) == 2 and [a[0] for a in applied] == [1, 2]


def test_failure_keeps_items_then_drops_poison_batch():
    def boom(b):
        raise RuntimeError("model down")
    q, _, applied = make(evaluate=boom)
    q.submit(P(1))
    for _ in range(MAX_TRIES - 1):
        assert q.drain(CancelToken()) == 0 and len(q) == 1
    q.drain(CancelToken())
    assert len(q) == 0 and q.dropped == [1] and applied == []


def test_wrong_result_count_is_failure_not_partial_apply():
    q, _, applied = make(evaluate=lambda b: [])
    q.submit(P(1))
    assert q.drain(CancelToken()) == 0 and applied == [] and len(q) == 1
