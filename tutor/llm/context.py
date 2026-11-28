"""Budżet kontekstu: system + pamięć (≤3000 tok) + bieżąca wiadomość + rezerwa na odpowiedź.

Wyłącznie dane bieżącego profilu (każde zapytanie do Repo filtruje profile_id).
"""
from __future__ import annotations

import json
import math
from collections.abc import Callable
from dataclasses import dataclass

from tutor.llm.base import ContextTooLarge, Message

MEMORY_TOKENS = 3000
BLOCK_TOKENS = 300  # podsumowanie i checkpoint: limit każdego
TURN_OVERHEAD = 4


def estimate_tokens(text: str) -> int:
    """Konserwatywnie: znaki/3 (bezpieczniej niż 3.5–4; polskie znaki diakrytyczne)."""
    return math.ceil(len(text) / 3)


def _clip(text: str, tokens: int) -> str:
    return text[: tokens * 3]


@dataclass
class Context:
    messages: list[Message]
    est_tokens: int
    memory_tokens: int
    dropped_turns: int


def _summary_text(raw: str) -> str:
    v = json.loads(raw)
    return v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)


def build_context(repo, profile_id: int, session_id: int, system_prompt: str, user_message: str,
                  *, context_window: int, reserve_out: int,
                  memory_budget: int = MEMORY_TOKENS, exclude_turn: int | None = None) -> Context:
    """`context_window` = limit modelu (wejście + odpowiedź). `user_message` jeszcze nie w DB albo zapisana jako
    tura `exclude_turn` (rozmowa zapisuje turę przed oceną, a model dostaje ją jako bieżącą wiadomość)."""
    fixed = estimate_tokens(system_prompt) + estimate_tokens(user_message) + 2 * TURN_OVERHEAD
    room = context_window - reserve_out - fixed
    if room < 0:
        raise ContextTooLarge("Wiadomość jest za długa dla wybranego modelu.")
    budget = min(memory_budget, room)

    parts: list[str] = []
    used = 0
    cps = repo.list_checkpoints(profile_id, session_id)
    upto = cps[-1]["upto_turn_id"] if cps else 0
    blocks = []
    prior = [s for s in repo.list_summaries(profile_id, "session") if s["session_id"] != session_id]
    if prior:
        blocks.append("Previous session summary: " + _clip(_summary_text(prior[-1]["summary_json"]),
                                                            BLOCK_TOKENS))
    if cps:
        blocks.append("Earlier in this session: " + _clip(cps[-1]["summary"], BLOCK_TOKENS))
    for b in reversed(blocks):  # checkpoint ważniejszy od starego podsumowania
        t = estimate_tokens(b)
        if used + t <= budget:
            parts.insert(0, b)
            used += t

    turns = [t for t in repo.list_turns(profile_id, session_id)
             if t["id"] > upto and t["role"] in ("user", "assistant") and t["id"] != exclude_turn]
    kept: list[dict] = []
    for t in reversed(turns):  # od najnowszych, ciągły ogon historii
        c = estimate_tokens(t["text"]) + TURN_OVERHEAD
        if used + c > budget:
            break
        kept.append(t)
        used += c
    kept.reverse()

    system = system_prompt + ("\n\n[Memory]\n" + "\n".join(parts) if parts else "")
    msgs = [Message("system", system)] + [Message(t["role"], t["text"]) for t in kept]
    msgs.append(Message("user", user_message))
    return Context(msgs, fixed + used + (estimate_tokens("\n\n[Memory]\n") if parts else 0), used,
                   len(turns) - len(kept))


def needs_checkpoint(repo, profile_id: int, session_id: int, every: int = 10) -> bool:
    cps = repo.list_checkpoints(profile_id, session_id)
    upto = cps[-1]["upto_turn_id"] if cps else 0
    return sum(1 for t in repo.list_turns(profile_id, session_id) if t["id"] > upto) >= every


def make_checkpoint(repo, profile_id: int, session_id: int,
                    summarize: Callable[[str | None, list[dict]], str], every: int = 10) -> int | None:
    """`summarize(poprzedni_checkpoint, nowe_tury) -> tekst` (wywołanie LLM wstrzykuje wywołujący)."""
    cps = repo.list_checkpoints(profile_id, session_id)
    prev = cps[-1] if cps else None
    new = [t for t in repo.list_turns(profile_id, session_id)
           if t["id"] > (prev["upto_turn_id"] if prev else 0)]
    if len(new) < every:
        return None
    text = _clip(summarize(prev["summary"] if prev else None, new), BLOCK_TOKENS)
    return repo.add_checkpoint(profile_id, session_id, new[-1]["id"], text)
