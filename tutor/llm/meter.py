"""Koszty, limity i bramka bezpieczeństwa przed każdym żądaniem zewnętrznym."""
from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

from tutor.llm.base import (
    BudgetExceeded,
    CancelToken,
    ConsentRequired,
    LimitsNotConfigured,
    LLMProvider,
    Message,
    Reply,
    Stream,
    Usage,
    log,
)
from tutor.llm.context import TURN_OVERHEAD, estimate_tokens

WARN_AT = 0.8


@dataclass(frozen=True)
class Price:
    in_per_mtok: float  # USD za 1M tokenów (wpisuje użytkownik, weryfikuje z cennikiem dostawcy)
    out_per_mtok: float


@dataclass(frozen=True)
class Limits:
    daily_usd: float | None = None
    monthly_usd: float | None = None


def estimate_input(messages: list[Message]) -> int:
    return sum(estimate_tokens(m.content) + TURN_OVERHEAD for m in messages)


class Meter:
    """Limity liczone po UTC i wspólnie dla wszystkich profili (llm_usage bez filtra profilu)."""

    def __init__(self, repo, limits: Limits, prices: dict[str, Price],
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)):
        self.repo, self.limits, self.prices, self.now = repo, limits, prices, now

    def _iso(self, d: datetime) -> str:
        return d.strftime("%Y-%m-%dT%H:%M:%S.000Z")

    def spent(self) -> tuple[float, float]:
        n = self.now()
        day = n.replace(hour=0, minute=0, second=0, microsecond=0)
        month = day.replace(day=1)
        return self.repo.llm_cost_since(self._iso(day)), self.repo.llm_cost_since(self._iso(month))

    def cost(self, model: str, u: Usage) -> float:
        p = self.prices[model]
        return (u.in_tokens * p.in_per_mtok + u.billed_out * p.out_per_mtok) / 1e6

    def check(self, provider: LLMProvider, est_in: int, est_out: int) -> list[str]:
        """Dla dostawcy zewnętrznego: limity+cennik skonfigurowane, koszt maks. mieści się w limicie.

        shortcut: bez rezerwacji, równoległe żądania mogą razem przekroczyć limit; przy
        wielu wątkach dodać rezerwację.
        """
        if not provider.external:
            return []
        lim = self.limits
        if lim.daily_usd is None or lim.monthly_usd is None or provider.model not in self.prices:
            raise LimitsNotConfigured(
                "Ustaw dzienny i miesięczny limit oraz cennik modelu w config.toml.")
        est = self.cost(provider.model, Usage(est_in, est_out))
        day, month = self.spent()
        warnings = []
        for label, spent, limit in (("dzienny", day, lim.daily_usd), ("miesięczny", month, lim.monthly_usd)):
            if limit <= 0 or spent + est > limit:
                raise BudgetExceeded(f"Przekroczyłbyś {label} limit API ({limit:.2f} USD).")
            if (spent + est) / limit >= WARN_AT:
                warnings.append(f"Uwaga: {label} limit API wykorzystany w "
                                f"{(spent + est) / limit:.0%} ({limit:.2f} USD).")
        return warnings

    def record(self, profile_id: int, provider: LLMProvider, role: str, u: Usage) -> float:
        cost = self.cost(provider.model, u) if provider.external and provider.model in self.prices else 0.0
        self.repo.add_llm_usage(profile_id, provider.name, provider.model, role, u.in_tokens,
                                u.billed_out, u.latency_ms, cost, self._iso(self.now()))
        log.info("usage provider=%s model=%s role=%s in=%d out=%d cost=%.6f", provider.name,
                 provider.model, role, u.in_tokens, u.billed_out, cost)
        return cost


class Guarded:
    """Dostawca z bramką: zgoda profilu (przy każdym żądaniu), limity, zapis użycia."""

    def __init__(self, provider: LLMProvider, repo, profile_id: int, role: str, meter: Meter):
        self.provider, self.repo, self.profile_id, self.role, self.meter = (
            provider, repo, profile_id, role, meter)
        self.name, self.model, self.external = provider.name, provider.model, provider.external

    def _gate(self, messages, max_tokens) -> list[str]:
        if self.external:
            p = self.repo.get_profile(self.profile_id)
            if not p or not p["external_api_consent_at"]:
                raise ConsentRequired("Brak zgody na użycie zewnętrznego API dla tego profilu.")
        return self.meter.check(self.provider, estimate_input(messages), max_tokens)

    def _consent_guard(self) -> None:
        if self.external:
            p = self.repo.get_profile(self.profile_id)
            if not p or not p["external_api_consent_at"]:
                raise ConsentRequired("Zgoda na zewnętrzne API cofnięta.")

    def chat(self, messages, *, temperature=0.7, max_tokens=512, schema=None) -> Reply:
        warnings = self._gate(messages, max_tokens)
        t0 = time.monotonic()
        try:
            r = self.provider.chat(messages, temperature=temperature, max_tokens=max_tokens, schema=schema)
        except Exception:
            # żądanie mogło zostać rozliczone mimo błędu: zapisz szacunek wejścia
            self.meter.record(self.profile_id, self.provider, self.role,
                              Usage(estimate_input(messages), 0, latency_ms=int((time.monotonic() - t0) * 1000),
                                    estimated=True))
            raise
        self.meter.record(self.profile_id, self.provider, self.role, r.usage)
        r.notices.extend(warnings)
        return r

    def stream(self, messages, *, temperature=0.7, max_tokens=512, cancel: CancelToken | None = None) -> Stream:
        warnings = self._gate(messages, max_tokens)
        t0 = time.monotonic()
        s = self.provider.stream(messages, temperature=temperature, max_tokens=max_tokens, cancel=cancel)
        s.notices.extend(warnings)
        s.guard = self._consent_guard

        def done(st: Stream, ok: bool) -> None:
            u = st.usage
            if u is None:  # anulowano/awaria: szacunek zachowawczy
                u = Usage(estimate_input(messages), estimate_tokens(st.text), estimated=True)
            u.latency_ms = u.latency_ms or int((time.monotonic() - t0) * 1000)
            self.meter.record(self.profile_id, self.provider, self.role, u)

        s.on_finish = done
        return s

    def health(self) -> bool:
        return self.provider.health()
