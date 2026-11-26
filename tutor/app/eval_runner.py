"""Spięcie EvalQueue z oceną modelu i zapisem postępów (F5.2). Minimalna integracja przed `SessionService`.

Tekst tury jest zapisany w `turn` zanim trafi do kolejki, więc błąd modelu, anulowanie ani restart go nie tracą.
Bramka jakości i mastery działają wyłącznie w `ingest.apply_turn_evaluation` (tu bez zmian).
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

from tutor.app import ingest, turn_eval
from tutor.app.eval_queue import EvalQueue, Pending
from tutor.pedagogy.content import Pack


class ModelUnavailable(Exception):
    """Model nie dał żadnej oceny partii (błąd/niepoprawny JSON) — partia wraca do kolejki."""


def make_queue(repo, pack: Pack, provider, structured, *, profile_id: int, session_id: int,
               goals: dict[str, str], clock: Callable[[], datetime] = lambda: datetime.now(UTC),
               model: str | None = None, prompt_version: str = "turn_eval.v3",
               theta: dict[str, float] | None = None, batch: int = 1, context: bool = False) -> EvalQueue:
    """`context`: model oceny dostaje poprzednią wypowiedź tutora (tylko przy partii 1 — kontekst jest wspólny dla
    całego wywołania). Domyślnie wyłączone do czasu wyniku eksperymentu B (bench/b_lite.py)."""
    def evaluate(items: list[Pending]):
        prev = tutor_prev(repo, profile_id, session_id, items[0].turn_id) if context and len(items) == 1 else ""
        res = turn_eval.evaluate_texts(pack, provider, structured, [p.text for p in items],
                                       input_modes=[p.input_mode for p in items],
                                       low_probs=[set(p.low_probs) for p in items], goals=goals, tutor_prev=prev)
        if all(r.eval_status != "evaluated" for r in res):
            raise ModelUnavailable
        return res

    def apply(p: Pending, r) -> None:
        ingest.apply_turn_evaluation(repo, pack, profile_id, session_id, p.turn_id, r, input_mode=p.input_mode,
                                     text=p.text, goals=set(goals), now=clock(), model=model,
                                     prompt_version=prompt_version + ("+ctx" if context else ""),
                                     low_prob_words=sorted(p.low_probs) or None,
                                     theta=theta, tutor_prev=tutor_prev(repo, profile_id, session_id, p.turn_id))
        repo.clear_dropped(profile_id, p.turn_id)

    def on_drop(p: Pending) -> None:
        repo.mark_dropped(profile_id, session_id, p.turn_id, p.input_mode, clock().isoformat())

    return EvalQueue(evaluate, apply, batch=batch, on_drop=on_drop)


def eval_context() -> bool:
    """Ustawienie `[evaluation] context` w config.toml (domyślnie False: eksperyment B bez potwierdzonej korzyści)."""
    from tutor import config
    return bool((config.raw_config().get("evaluation") or {}).get("context", False))


def tutor_prev(repo, profile_id: int, session_id: int, turn_id: int) -> str:
    """Ostatnia wypowiedź tutora przed turą ucznia `turn_id` (z SQLite, więc działa też po restarcie)."""
    prev = ""
    for t in repo.list_turns(profile_id, session_id):
        if t["id"] >= turn_id:
            break
        if t["role"] == "assistant":
            prev = t["text"]
    return prev


def restore_pending(repo, queue: EvalQueue, profile_id: int, session_id: int) -> int:
    """Po restarcie: tury ucznia bez wpisu oceny wracają do kolejki. Idempotentne (kolejka dedupuje po `turn_id`);
    tury ocenione, nieocenione-final i porzucone (`dropped_at`) mają wiersz `turn_meta` i nie wracają."""
    n = len(queue)
    for t in repo.list_pending_turns(profile_id, session_id):
        queue.submit(Pending(t["turn_id"], t["text"], t["input_mode"], frozenset(t["low_probs"])))
    return len(queue) - n


def catch_up(repo, pack: Pack, provider, structured, profile_id: int, *, skip_session: int | None = None,
             cancel=None, model: str | None = None) -> dict:
    """Dokańcza oceny tur czekających w sesjach profilu (np. rozmowa zakończona przed oceną ostatnich wypowiedzi).
    Idempotentne: tura z wierszem `turn_meta` nie wraca, więc nic nie jest liczone drugi raz. Zwraca
    {"done": n, "left": m, "sessions": [sid…]}. Model niedostępny ⇒ tury zostają oczekujące (po 3 błędach: dropped)."""
    from tutor.llm.base import CancelToken
    cancel = cancel or CancelToken()
    done, touched = 0, []
    for sid, _n in sorted(repo.pending_by_session(profile_id).items()):
        if sid == skip_session or cancel.is_set():
            continue
        plan = repo.get_session_plan(profile_id, sid) or {}
        goals = {}
        if plan.get("lesson") and plan["lesson"] in pack.skills:
            goals = {plan["lesson"]: pack.skills[plan["lesson"]].can_do_pl}
        q = make_queue(repo, pack, provider, structured, profile_id=profile_id, session_id=sid, goals=goals,
                       model=model, batch=1)
        restore_pending(repo, q, profile_id, sid)
        for _ in range(3):                  # 3 podejścia na sesję (EvalQueue porzuca turę po 3 błędach)
            done += q.drain(cancel)
            if not len(q) or cancel.is_set():
                break
        touched.append(sid)
    left = sum(n for s, n in repo.pending_by_session(profile_id).items() if s != skip_session)
    return {"done": done, "left": left, "sessions": touched}
